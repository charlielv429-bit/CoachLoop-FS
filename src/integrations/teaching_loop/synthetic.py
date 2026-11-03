"""Explicit mock keypoints through unchanged geometry/V4/V5, NOT MediaPipe evidence."""
from uuid import uuid4
from integrations.local_video.service import Job, VideoError
from tools.video_analysis.schemas import KeypointDataset, KeypointFrame, Landmark
from tools.video_analysis.features import process_keypoint_dataset
from tools.video_analysis.event_detection import detect_changes
from tools.video_analysis.event_review import build_review_records


def install_demo(store, token):
    with store.lock:
        store.authorized(token)
        if len(store.jobs) >= 8: raise VideoError(429, 'video_job_limit')
        if any(j.owner == token for j in store.jobs.values()):
            raise VideoError(409, 'delete_previous_video_first')
        key = uuid4().hex
        source = 'mock://L05-synthetic/' + key
        frames = []
        for i in range(40):
            knee_x = .75 if 16 <= i < 24 else .45
            points = [(11,'left_shoulder',.4,.2),(12,'right_shoulder',.6,.2),
                      (23,'left_hip',.45,.5),(24,'right_hip',.55,.5),
                      (25,'left_knee',knee_x,.7),(27,'left_ankle',.45,.9)]
            frames.append(KeypointFrame(frame_idx=i,timestamp_ms=float(i*100),is_mock=True,source=source,
                landmarks=[Landmark(id=n,name=name,x=x,y=y,visibility=.95) for n,name,x,y in points]))
        data = KeypointDataset(is_mock=True,source=source,fps=10.,frames=frames)
        pose = process_keypoint_dataset(data,side='left')
        rows = [f.model_dump() for f in pose.frames]
        source_info = {**pose.source,'video_path':source}
        detection = detect_changes(rows,source=source_info,is_mock=True)
        review = build_review_records(detection.model_dump(),source)
        result = dict(schema_version='local-video-v2',is_mock=True,synthetic_demo=True,source=source_info,
            metadata={'duration_seconds':4.,'fps':10.,'analysis_fps':10.,'synthetic':True},
            quality={**pose.summary,'source_frames':40,'detected_frames':40,'valid_frame_ratio':1.,'synthetic':True},
            frames=rows,keypoints=[f.model_dump() for f in frames],detection=detection.model_dump(),
            review=review.model_dump(mode='json'),review_verification='local_unverified',
            authenticated_coach=False,technical_error_assessment='not_assessed',
            limitations=['合成关键点演示，不是真实视频、学生记录或花滑技术验证。',
                          '只复用几何、V4事件和V5复核；没有调用MediaPipe或训练模型。'])
        path = store.root/key
        path.mkdir(mode=0o700)
        job = Job(key,token,store.sessions[token]['actor'],'left',path,store.clock())
        job.state, job.result = 'ready', result
        store.jobs[key] = job
        return {'job_id':key,'state':'ready','is_mock':True,'synthetic_demo':True,
                'notice':'仅为合成关键点教学闭环演示；未执行真实视频识别。'}
