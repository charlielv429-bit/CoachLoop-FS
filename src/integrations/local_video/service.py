"""Private, expiring local-video jobs. All processing is an owned subprocess.

No database, cloud API or role authentication. Local review actions are genuine
UI operations but their operator is NOT an authenticated professional coach.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

from tools.video_analysis.event_review import EventReviewOutput, apply_review

ROOT = Path(__file__).resolve().parents[3]
COOKIE = 'coachloop_video_session'
BASE = '/api/v2/video'
READ_PATHS = {BASE+p for p in ('/capabilities','/current','/status','/result','/media','/feedback')}
WRITE_PATHS = {BASE+p for p in ('/jobs','/upload','/review','/delete')}
MAX_BYTES = 25*1024*1024


class VideoError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


@dataclass
class Job:
    id: str
    owner: str
    actor: str
    side: str
    path: Path
    created: float
    state: str = 'created'
    error: str | None = None
    process: object = None
    result: dict | None = None
    requests: dict = field(default_factory=dict)


def feedback(result, job_id):
    """Safe adapter instead of abusing the database-only mock postlesson Agent."""
    records = result['review']['records']
    reported = []
    for record in records:
        if record['review_status'] in ('confirmed','normal_movement'):
            event = record['original_event']
            reported.append(dict(event_id=record['event_id'],status=record['review_status'],
                start_time_ms=event['start_time_ms'],end_time_ms=event['end_time_ms'],
                frame_start=event['frame_start'],frame_end=event['frame_end'],
                feature=event['feature'],deviation_max=event['deviation_max'],
                interpretation='用户本机会话报告存在可观察变化' if record['review_status']=='confirmed' else '用户本机会话报告属于正常动作',
                verification='local_unverified',eligible_for_technical_conclusions=False))
    return dict(schema_version='local-postlesson-v2',generated_at=datetime.now(timezone.utc).isoformat(),analysis_id=job_id,data_origin='mock_keypoints' if result['is_mock'] else 'real_video',is_mock=result['is_mock'],
        review_status='draft',requires_teacher_review=True,knowledge_status='unverified',
        authenticated_coach=False,review_verification='local_unverified',technical_error_assessment='not_assessed',
        training_information=result['metadata'],video_quality=result['quality'],
        source=copy.deepcopy(result['source']),time_basis='normalized_preview_milliseconds',
        analysis_scope='bounded_normalized_preview',
        limitations=copy.deepcopy(result.get('limitations',[])),
        trusted_observations=[],reported_observations=reported,
        review_sequences={r['event_id']:len(r['review_history']) for r in records},
        pending_questions=['本地操作者身份与教练资格未认证，以上不是正式教练结论。',
            'pending、tracking_error、uncertain不进入动作评价依据；confirmed仅报告变化，不证明技术错误。',
            '需现场核实拍摄视角、可见度与冰面情境，二维数据不能证明重心或用刃。'],
        excluded_event_count=len(records)-len(reported),
        candidate_practice=['信息复核：教师先核对视频质量与事件原片，不根据噪声纠错。',
            '基础复习：教师确认安全条件后，在已掌握主题内选择低复杂度复习，不由事件自动分级。',
            '专项指导：仅在专业教练核实后选择练习；本稿不生成医学、技术错误或合格线判断。'],
        teacher_review_checklist=['确认合法视频与隐私授权','核实操作者及教练资格','核对每项观察与原片','专业复核后再作评价','本应用不执行批准或数据库归档'])


class VideoStore:
    def __init__(self, *, python=None, model=None, clock=time.monotonic):
        self.python = Path(python or ROOT/'.venv-video/bin/python')
        self.model = Path(model or ROOT/'assets/models/pose_landmarker_full.task')
        self.temp = tempfile.TemporaryDirectory(prefix='coachloop-local-video-')
        self.root = Path(self.temp.name)
        self.clock, self.closed = clock, False
        self.lock = threading.RLock()
        self.sessions, self.jobs = {}, {}
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='local-video')
        self.stop_event=threading.Event()
        self.janitor=threading.Thread(target=self._expire,daemon=True,name='video-expiry')
        self.janitor.start()

    def _expire(self):
        while not self.stop_event.wait(10):
            self.prune()

    def capabilities(self):
        missing = []
        if not self.python.is_file():missing.append('video_python_missing')
        if not self.model.is_file():missing.append('pose_model_missing')
        for tool in ('ffmpeg','ffprobe'):
            if shutil.which(tool) is None:missing.append(tool+'_missing')
        return dict(available=not missing,missing=missing,max_bytes=MAX_BYTES,max_seconds=60,
            supported_extensions=['mp4','mov'],max_resolution=1920,max_pixels=2073600,max_input_fps=60,
            analysis_max_fps=12,job_ttl_seconds=1200,session_ttl_seconds=1800,
            processing='local_subprocess',cloud_upload=False,authenticated_coach=False)

    def prune(self):
        with self.lock:
            now = self.clock()
            for key, value in list(self.sessions.items()):
                if value['expires'] <= now:self.sessions.pop(key,None)
            for key, job in list(self.jobs.items()):
                if job.owner not in self.sessions or job.created+1200 <= now or (job.state=='created' and job.created+120 <= now):
                    self._remove(job)

    def session(self, token=None):
        with self.lock:
            self.prune()
            if self.closed:raise VideoError(503,'video_service_stopped')
            if token in self.sessions:return token
            if len(self.sessions)>=16:raise VideoError(429,'video_session_limit')
            token=secrets.token_urlsafe(32)
            self.sessions[token]={'expires':self.clock()+1800,'actor':'local-operator-'+secrets.token_hex(4)}
            return token

    def authorized(self, token):
        with self.lock:
            self.prune()
            if self.closed or token not in self.sessions:raise VideoError(401,'video_session_expired')
            return token

    def get(self, token, key):
        self.authorized(token)
        job=self.jobs.get(key)
        if job is None or job.owner!=token:raise VideoError(404,'video_job_not_found')
        return job

    def create(self, token, side):
        with self.lock:
            self.authorized(token)
            if self.capabilities()['missing']:raise VideoError(503,'video_prerequisites_missing')
            if len(self.jobs)>=8:raise VideoError(429,'video_job_limit')
            if any(j.owner==token for j in self.jobs.values()):raise VideoError(409,'delete_previous_video_first')
            key=uuid4().hex; path=self.root/key;path.mkdir(mode=0o700)
            job=Job(key,token,self.sessions[token]['actor'],side,path,self.clock())
            self.jobs[key]=job
            return key

    def upload_path(self, token, key):
        with self.lock:
            job=self.get(token,key)
            if job.state!='created':raise VideoError(409,'video_already_uploaded')
            job.state='uploading'
            return job.path/'upload.bin'

    def upload_failed(self, token, key, reason):
        with self.lock:
            job=self.jobs.get(key)
            if job and job.owner==token:
                shutil.rmtree(job.path,ignore_errors=True)
                job.state='failed';job.error=reason

    def submit(self, token, key):
        with self.lock:
            job=self.get(token,key)
            if job.state!='uploading':raise VideoError(409,'video_upload_state')
            job.state='queued'
            self.executor.submit(self._work,job)

    @staticmethod
    def _kill(process):
        if process is not None and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=3)

    def _work(self, job):
        try:
            with self.lock:
                if self.closed or self.jobs.get(job.id) is not job:return
                job.state='running'
                environment={k:v for k,v in os.environ.items() if not (k.startswith(('COZE','COACHLOOP','TEACHING','PG','DATABASE','OPENAI','TUNNEL_')))}
                environment.update(PYTHONPATH=str(ROOT/'src'),MPLCONFIGDIR=str(job.path/'mpl'),OMP_NUM_THREADS='2')
                job.process=subprocess.Popen([str(self.python),'-m','integrations.local_video.worker',
                    '--job-dir',str(job.path),'--model',str(self.model),'--job-id',job.id,'--side',job.side],
                    env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            try:code=job.process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                self._kill(job.process);code=-1
            with self.lock:
                if self.closed or self.jobs.get(job.id) is not job:return
                if code!=0:
                    # Never return child exceptions, native decoder messages or paths.
                    reason='processing_failed'
                    if (job.path/'error.json').is_file():
                        error=json.loads((job.path/'error.json').read_text())['code']
                        if error in ('unsupported_container','unsupported_streams','media_limits','unsupported_codec','unreadable_video','normalization_failed','pose_runtime_failed','no_decodable_frames'):
                            reason=error
                    job.state='failed';job.error=reason;shutil.rmtree(job.path,ignore_errors=True)
                    return
                result_path=job.path/'result.json'
                if result_path.stat().st_size>20*1024*1024:raise ValueError('result limit')
                result=json.loads(result_path.read_text(),parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                if (result['is_mock'] is not False or result['source']['is_mock'] is not False or result['source']['mode']!='real'
                        or result['source']['video_path']!='local-video://'+job.id
                        or any(p['is_mock'] is not False for p in result['keypoints'])):
                    raise ValueError('invalid result provenance')
                if result['review_verification']!='local_unverified' or result['authenticated_coach'] is not False:
                    raise ValueError('invalid review trust')
                result_path.unlink() # Derived data stays in memory, not an automatic archive.
                job.result=result;job.state='ready'
        except Exception:
            with self.lock:
                if self.jobs.get(job.id) is job:
                    self._kill(job.process);shutil.rmtree(job.path,ignore_errors=True)
                    job.state='failed';job.error='processing_failed'

    def current(self, token):
        with self.lock:
            self.authorized(token)
            job=next((j for j in self.jobs.values() if j.owner==token),None)
            return self.status(token,job.id) if job else None

    def status(self, token, key):
        with self.lock:
            job=self.get(token,key)
            return dict(job_id=key,state=job.state,error=job.error,
                source_kind='real_video_upload',authenticated_coach=False,
                quality=copy.deepcopy(job.result['quality']) if job.result else None)

    def result(self, token, key):
        with self.lock:
            job=self.get(token,key)
            if job.state!='ready':raise VideoError(409,'video_not_ready')
            return copy.deepcopy(job.result)

    def media(self, token, key):
        with self.lock:
            job=self.get(token,key)
            if job.state!='ready':raise VideoError(409,'video_not_ready')
            try:return (job.path/'preview.mp4').open('rb')
            except OSError:raise VideoError(404,'video_preview_unavailable') from None

    def review(self, token, key, event_id, status, note, expected, request_id):
        with self.lock:
            job=self.get(token,key)
            if job.state!='ready':raise VideoError(409,'video_not_ready')
            change=(event_id,status,note,expected)
            if request_id in job.requests:
                previous=job.requests[request_id]
                if previous!=change:raise VideoError(409,'review_idempotency_conflict')
                return copy.deepcopy(job.result['review'])
            record=next((r for r in job.result['review']['records'] if r['event_id']==event_id),None)
            if record is None:raise VideoError(404,'event_not_found')
            if len(record['review_history'])!=expected:raise VideoError(409,'review_sequence_conflict')
            if len(job.requests)>=256:raise VideoError(429,'review_history_limit')
            model=EventReviewOutput.model_validate(job.result['review'])
            target=next(r for r in model.records if r.event_id==event_id)
            apply_review(target,status,reviewed_by=job.actor,note=note)
            job.result['review']=model.finalize().model_dump(mode='json')
            job.requests[request_id]=change
            return copy.deepcopy(job.result['review'])

    def _remove(self, job):
        self.jobs.pop(job.id,None)
        self._kill(job.process)
        shutil.rmtree(job.path,ignore_errors=True)
        job.result=None;job.state='deleted'

    def delete(self, token, key):
        with self.lock:self._remove(self.get(token,key))

    def close(self):
        self.stop_event.set()
        if threading.current_thread() is not self.janitor:self.janitor.join(timeout=2)
        with self.lock:
            self.closed=True
            for job in list(self.jobs.values()):self._remove(job)
            self.sessions.clear()
        self.executor.shutdown(wait=True,cancel_futures=True)
        self.temp.cleanup()
