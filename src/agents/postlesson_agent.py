"""Neutral postlesson drafts from tenant-bound database queries, never raw claims.

No model/KB/video calls, writes or teacher approvals. Current data domain is mock.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

from integrations.reviewed_training.schemas import ResultPage
from integrations.reviewed_training.service import TrustedIdentity, checked_connection, query_results

PRACTICE = (
    '基础层：教师确认组织与安全方案后，复习零基础双足滑行与姿态控制。',
    '巩固层：由教师现场选择相同主题的重复练习，不由事件变化自动分层。',
    '复核层：对信息不足或跟踪误差，先复核记录，不生成技术纠错结论。',
)


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    event_id: UUID
    review_sequence: int = Field(strict=True, ge=1)
    status: Literal['confirmed', 'normal_movement']
    interpretation: Literal['reviewed_observable_change', 'reviewed_normal_movement']


class PostlessonDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['postlesson-draft-v1'] = 'postlesson-draft-v1'
    data_domain: Literal['mock'] = 'mock'
    training_session_id: UUID
    analysis_run_id: UUID
    review_status: Literal['draft'] = 'draft'
    requires_teacher_review: Literal[True] = True
    knowledge_status: Literal['unverified'] = 'unverified'
    technical_error_assessment: Literal['not_assessed'] = 'not_assessed'
    recommendation_basis: Literal['beginner_template_not_event_diagnosis'] = 'beginner_template_not_event_diagnosis'
    scope: Literal['returned_page'] = 'returned_page'
    more_events_available: bool = Field(strict=True)
    observations: tuple[Observation, ...]
    excluded_event_count: int = Field(strict=True, ge=0)
    learning_assessment: Literal['insufficient_for_skill_grade'] = 'insufficient_for_skill_grade'
    tiered_practice: tuple[str, ...] = PRACTICE

    @model_validator(mode='after')
    def guard_output(self):
        expected = dict(schema_version='postlesson-draft-v1', data_domain='mock', review_status='draft',
            knowledge_status='unverified', technical_error_assessment='not_assessed',
            recommendation_basis='beginner_template_not_event_diagnosis', scope='returned_page',
            learning_assessment='insufficient_for_skill_grade', tiered_practice=PRACTICE)
        if self.requires_teacher_review is not True or any(getattr(self, k) != v for k, v in expected.items()):
            raise ValueError('Postlesson draft must preserve review and evidence safeguards')
        seen = set()
        for observation in self.observations:
            Observation.model_validate({name: getattr(observation, name) for name in Observation.model_fields})
            if observation.event_id in seen:
                raise ValueError('Duplicate observation in postlesson report')
            seen.add(observation.event_id)
            if observation.interpretation != ('reviewed_observable_change' if observation.status == 'confirmed'
                    else 'reviewed_normal_movement'):
                raise ValueError('Observation interpretation conflicts with review status')
        return self

    @model_serializer(mode='wrap')
    def guarded_export(self, handler):
        self.guard_output()
        # Frozen models still allow model_copy(update=...) without validation.
        # Validate every serialized field, not just the semantic control flags.
        validated = type(self).model_validate({name: getattr(self, name) for name in type(self).model_fields})
        return handler(validated)


def _draft_for_page(page: ResultPage) -> PostlessonDraft:
    """Internal: admission after checked_connection + query_results only."""
    page = ResultPage.model_validate(page.model_dump(mode='python'))
    observations = []
    seen = set()
    for event in page.events:
        if event.event_id in seen or event.analysis_run_id != page.analysis_run_id:
            raise ValueError('Duplicate or cross-analysis event in database page')
        seen.add(event.event_id)
        eligible = (event.effective_review_verification == 'authenticated'
            and event.trusted_review_sequence is not None and event.trusted_review_sequence > 0
            and event.effective_review_status in ('confirmed', 'normal_movement')
            and event.observation_summary_eligible)
        if eligible:
            observations.append(Observation(event_id=event.event_id,
                review_sequence=event.trusted_review_sequence, status=event.effective_review_status,
                interpretation='reviewed_observable_change' if event.effective_review_status == 'confirmed'
                    else 'reviewed_normal_movement'))
    return PostlessonDraft(training_session_id=page.training_session_id, analysis_run_id=page.analysis_run_id,
        observations=tuple(observations), excluded_event_count=len(page.events) - len(observations),
        more_events_available=page.next_cursor is not None)


def draft_from_database(identity: TrustedIdentity, training_session_id: UUID, analysis_run_id: UUID,
                        *, limit: int = 50, cursor: UUID | None = None) -> PostlessonDraft:
    """Read-only Python workflow boundary; identity must be injected server-side.

    No HTTP endpoint accepts caller-supplied auth flags or an identity object.
    This is an observation-page draft, not a complete-session performance grade.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Page limit must be an integer from 1 to 100')
    with identity.engine.connect() as connection:
        checked_connection(connection, identity)
        page = query_results(connection, identity, training_session_id, analysis_run_id, limit, cursor)
    return _draft_for_page(ResultPage.model_validate(page))
