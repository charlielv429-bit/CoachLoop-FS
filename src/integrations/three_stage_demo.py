"""Entirely synthetic local demo building blocks; no video/model/network calls."""
from copy import deepcopy
from uuid import uuid4

from graphs.prelesson_graph import run_prelesson
from integrations.prelesson.schemas import DraftResponse, THEME
from tools.video_analysis.schemas import KeypointDataset
from tools.video_analysis.features import process_keypoint_dataset
from tools.video_analysis.event_detection import detect_changes
from tools.video_analysis.event_review import build_review_records


def prelesson():
    return run_prelesson(dict(class_label='MOCK-THREE-STAGE-01', student_count=20, theme=THEME,
        skill_level='零基础', total_minutes=45, coach_count=1, teacher_count=1,
        venue_conditions='合成冰场，容量与组织待教师现场确认', equipment_conditions='合成冰鞋护具20套'))


def database_plan_payload(response: DraftResponse):
    """Explicit adapter to existing db-a-1 payload; retains guarded source draft."""
    response = DraftResponse.model_validate_json(response.model_dump_json())
    plan = response.lesson_plan.model_dump(mode='json')
    result = deepcopy(plan)
    result['schema_version'] = 'db-a-1'
    times = plan['teaching_flow']['phases']
    result['teaching_flow'].update(prep_minutes=times[0]['minutes'],
        main_minutes=times[1]['minutes'], closing_minutes=times[2]['minutes'])
    load = plan['load_accounting']
    result['load_accounting'].update(group_active_minutes=load['group_density']['numerator'],
        individual_active_minutes=load['individual_density']['numerator'], avg_hr=load['avg_hr']['numerator'],
        kind='estimated')
    # The DB-a contract uses scalar avg_hr; preserve the original guarded API
    # response separately instead of pretending these two schemas are identical.
    result['source_prelesson_response'] = response.model_dump(mode='json')
    return result


def synthetic_video_stages():
    source = 'mock://three-stage/synthetic-keypoints'
    frames = []
    for i in range(40):
        knee_x = .70 if 10 <= i <= 16 else .50
        points = [(11, 'left_shoulder', .48, .2), (12, 'right_shoulder', .52, .2),
            (23, 'left_hip', .5, .45), (24, 'right_hip', .54, .45),
            (25, 'left_knee', knee_x, .65), (27, 'left_ankle', .5, .9)]
        frames.append(dict(frame_idx=i, timestamp_ms=i * 40, is_mock=True, source=source,
            landmarks=[dict(id=n, name=name, x=x, y=y, visibility=.99) for n, name, x, y in points]))
    dataset = KeypointDataset(is_mock=True, source=source, fps=25, frames=frames)
    features = process_keypoint_dataset(dataset)
    candidates = detect_changes([f.model_dump(mode='json') for f in features.frames],
        source={**features.source, 'video_path': source})
    reviews = build_review_records(candidates.model_dump(mode='json'), 'mock://three-stage/candidates.json')
    return features, candidates, reviews


def import_payload(chain, reviews):
    """Pending claims only: the import adapter cannot manufacture coach review."""
    def mock_source(source):
        if not isinstance(source, dict) or source.get('is_mock') is not True:
            return False
        if 'mode' in source and source['mode'] != 'mock':
            return False
        paths = [source[key] for key in ('source', 'video_path', 'input_json') if key in source]
        return bool(paths) and all(isinstance(path, str) and path.startswith('mock://') for path in paths)

    # This helper generates a synthetic import declaration. Never relabel real,
    # unknown or contradictory V5 provenance just because it has valid fields.
    if (reviews.is_mock is not True or not mock_source(reviews.source)
            or any(not mock_source(record.source) for record in reviews.records)):
        raise ValueError('Only explicitly synthetic MOCK review sources may enter this demo adapter')
    return dict(schema_version='reviewed-training-import-v1', data_domain='mock', time_unit='ms',
        class_id=str(chain['class_id']), lesson_id=str(chain['lesson_id']),
        training_session_id=str(chain['session_id']), analysis_run_id=str(uuid4()),
        source=dict(kind='synthetic', is_mock=True, artifact_id=str(uuid4()), source_stream_id=str(uuid4())),
        events=[dict(event_id=r.event_id,
            **{k:r.original_event[k] for k in ('feature','frame_start','frame_end','start_time_ms','end_time_ms','deviation_max')},
            original_event=r.original_event, review=dict(review_status='pending', review_history=[]))
            for r in reviews.records])
