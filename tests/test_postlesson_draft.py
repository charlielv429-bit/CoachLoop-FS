from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.postlesson_agent import _draft_for_page
from integrations.reviewed_training.schemas import ResultPage
from integrations.three_stage_demo import prelesson, database_plan_payload, synthetic_video_stages, import_payload


def page(status='pending', verification='unreviewed', eligible=False, sequence=None):
    run = uuid4()
    return ResultPage.model_validate(dict(schema_version='reviewed-training-results-v1', data_domain='mock',
        training_session_id=uuid4(), analysis_run_id=run, next_cursor=None,
        events=[dict(event_id=uuid4(), source_event_id='evt_123456789abc', analysis_run_id=run,
            feature='knee_angle_deg', frame_start=1, frame_end=2, start_time_ms=40, end_time_ms=80,
            deviation_max=12, effective_review_status=status, effective_review_verification=verification,
            trusted_review_sequence=sequence, observation_summary_eligible=eligible,
            technical_error_assessment='not_assessed', imported_review_claims=[], claim_streams_truncated=False)],
        summary=dict(event_count=1, trusted_reviewed_event_count=0, observation_summary_eligible_count=0,
            technical_error_assessment='not_assessed', scope='returned_page')))


@pytest.mark.parametrize('status', ['pending', 'tracking_error', 'uncertain', 'confirmed', 'normal_movement'])
def test_unverified_claims_never_enter_observations_even_with_claimed_eligibility(status):
    result = _draft_for_page(page(status, eligible=True))
    assert result.observations == () and result.excluded_event_count == 1
    assert result.learning_assessment == 'insufficient_for_skill_grade'


@pytest.mark.parametrize('status', ['pending', 'tracking_error', 'uncertain'])
def test_nonconclusive_authenticated_reviews_cannot_enter_feedback(status):
    assert _draft_for_page(page(status, 'authenticated', True, 1)).observations == ()


@pytest.mark.parametrize('status', ['confirmed', 'normal_movement'])
def test_reviewed_observations_never_become_technical_errors(status):
    result = _draft_for_page(page(status, 'authenticated', True, 1))
    assert len(result.observations) == 1
    assert result.technical_error_assessment == 'not_assessed'
    assert result.review_status == 'draft' and result.requires_teacher_review
    assert result.knowledge_status == 'unverified'


@pytest.mark.parametrize('mutation', [
    {'review_status': 'approved'}, {'requires_teacher_review': False},
    {'knowledge_status': 'verified'}, {'technical_error_assessment': 'confirmed_error'},
    {'tiered_practice': ('未经专项审核的安全处置指令',)},
])
def test_postconstruction_safety_mutations_are_blocked_at_export(mutation):
    result = _draft_for_page(page()).model_copy(update=mutation)
    with pytest.raises((ValueError, ValidationError)):
        result.model_dump_json()


def test_duplicate_or_cross_run_events_are_rejected():
    result = page()
    result.events.append(result.events[0])
    with pytest.raises(ValueError):
        _draft_for_page(result)
    result.events.pop()
    result.events[0].analysis_run_id = uuid4()
    with pytest.raises(ValueError):
        _draft_for_page(result)


def test_page_scope_and_pagination_are_explicit():
    result = page()
    result.next_cursor = uuid4()
    draft = _draft_for_page(result)
    assert draft.scope == 'returned_page' and draft.more_events_available


def test_existing_geometry_events_and_plan_are_reused_without_video_or_model():
    response = prelesson()
    payload = database_plan_payload(response)
    assert payload['source_prelesson_response'] == response.model_dump(mode='json')
    assert payload['teaching_flow']['prep_minutes'] + payload['teaching_flow']['main_minutes'] + payload['teaching_flow']['closing_minutes'] == 45
    assert payload['review_status'] == 'draft'
    assert payload['load_accounting']['kind'] == 'estimated'
    features, candidates, reviews = synthetic_video_stages()
    assert len(features.frames) == 40 and len(candidates.events) > 0
    assert features.source['is_mock'] and all(r.review_status == 'pending' for r in reviews.records)
    from integrations.reviewed_training.schemas import ImportRequest
    request = import_payload(dict(class_id=uuid4(), lesson_id=uuid4(), session_id=uuid4()), reviews)
    assert ImportRequest.model_validate(request).source.is_mock


@pytest.mark.parametrize('limit', [0, 101, True, -1, 1.5])
def test_invalid_limit_cannot_open_a_database_connection(limit):
    from agents.postlesson_agent import draft_from_database
    with pytest.raises(ValueError):
        draft_from_database(None, uuid4(), uuid4(), limit=limit)


@pytest.mark.parametrize('mutation', [
    {'excluded_event_count': -1}, {'excluded_event_count': True},
    {'excluded_event_count': '2'}, {'more_events_available': 'false'},
    {'more_events_available': None}, {'training_session_id': 'not-a-uuid'},
])
def test_all_fields_are_revalidated_after_model_copy(mutation):
    draft = _draft_for_page(page()).model_copy(update=mutation)
    with pytest.raises((ValueError, ValidationError)):
        draft.model_dump_json()


def test_duplicate_observations_cannot_inflate_a_report():
    draft = _draft_for_page(page('confirmed', 'authenticated', True, 1))
    changed = draft.model_copy(update={'observations': draft.observations * 2})
    with pytest.raises(ValueError):
        changed.model_dump_json()


def test_review_sequence_boolean_cannot_be_serialized_as_integer_one():
    draft = _draft_for_page(page('confirmed', 'authenticated', True, 1))
    altered = draft.observations[0].model_copy(update={'review_sequence': True})
    with pytest.raises(ValueError):
        draft.model_copy(update={'observations': (altered,)}).model_dump_json()


@pytest.mark.parametrize('attack', [
    'top_false', 'top_integer', 'source_false', 'source_missing', 'source_integer',
    'source_real_mode', 'source_external_video', 'source_external_source',
    'source_local_file', 'record_false', 'record_missing', 'record_external_video',
])
def test_demo_adapter_never_relabels_real_or_unknown_sources_as_mock(attack):
    _, _, reviews = synthetic_video_stages()
    if attack == 'top_false':
        reviews = reviews.model_copy(update={'is_mock': False})
    elif attack == 'top_integer':
        reviews = reviews.model_copy(update={'is_mock': 1})
    elif attack == 'source_false':
        reviews.source['is_mock'] = False
    elif attack == 'source_missing':
        reviews.source.pop('is_mock')
    elif attack == 'source_integer':
        reviews.source['is_mock'] = 1
    elif attack == 'source_real_mode':
        reviews.source['mode'] = 'real'
    elif attack == 'source_external_video':
        reviews.source['video_path'] = 'https://synthetic-review.invalid/not-mock'
    elif attack == 'source_external_source':
        reviews.source['source'] = 'real://not-a-mock-source'
    elif attack == 'source_local_file':
        reviews.source['input_json'] = '/tmp/unknown-review.json'
    elif attack == 'record_false':
        reviews.records[0].source['is_mock'] = False
    elif attack == 'record_missing':
        reviews.records[0].source.pop('is_mock')
    else:
        reviews.records[0].source['video_path'] = 'real://not-a-mock-source'
    with pytest.raises(ValueError):
        import_payload(dict(class_id=uuid4(), lesson_id=uuid4(), session_id=uuid4()), reviews)
