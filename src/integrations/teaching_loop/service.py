"""Bounded process-local loop records, bound to BOTH existing browser owners.

Every read/export rechecks the current job, plan and evidence. No media, raw
keypoints, names, shared KB writes or permanent student/feedback database.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from uuid import uuid4

from pydantic import Field, field_validator
from integrations.curriculum_v3.registry import Strict, Knowledge, RegistryError
from integrations.curriculum_v3.planning import guard_current_evidence
from integrations.local_video.service import VideoError, feedback

BASE = '/api/v3/loops'
READ_PATHS = {BASE+p for p in ('/current','/export','/history')}
WRITE_PATHS = {BASE+p for p in ('/link','/edit','/confirm','/delete','/demo-analysis')}
ID = r'^[a-f0-9]{32}$'
DIGEST = r'^[a-f0-9]{64}$'


class Fields(Strict):
    observation: str = Field(default='',max_length=1500)
    practice_task: str = Field(default='',max_length=1500)

    @field_validator('observation','practice_task')
    @classmethod
    def plain(cls,value): return Knowledge.safe_text(value)


class Link(Fields):
    plan_id: str = Field(pattern=ID)
    expected_plan_version: int = Field(ge=1,le=100)
    job_id: str = Field(pattern=ID)
    learner_code: str = Field(pattern=r'^ANON-[0-9]{3,8}$')


class Key(Strict):
    loop_id: str = Field(pattern=ID)


class Edit(Key, Fields):
    expected_version: int = Field(ge=1,le=100)
    expected_evidence_digest: str = Field(pattern=DIGEST)


class Confirm(Key):
    expected_version: int = Field(ge=1,le=100)
    expected_evidence_digest: str = Field(pattern=DIGEST)
    acknowledged: bool


def now(): return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def analysis_view(result,job_id):
    # No file paths, video bytes, raw landmarks or cookie/actor identifiers.
    changes = []
    for record in result['review']['records']:
        changes.append(dict(event_id=record['event_id'],candidate=deepcopy(record['original_event']),
            status=record['review_status'],note=record['notes'],sequence=len(record['review_history']),
            local_review_history=[{k:deepcopy(h[k]) for k in ('reviewed_at','status','note') if k in h} for h in record['review_history']],
            interpretation='候选二维变化；本地状态或文字不证明技术错误。'))
    return dict(job_id=job_id,is_mock=result['is_mock'],synthetic_demo=result.get('synthetic_demo',False),
        origin='synthetic_keypoints_demo' if result['is_mock'] else 'local_real_video',
        quality=deepcopy(result['quality']),metadata=deepcopy(result['metadata']),candidate_changes=changes,
        limitations=deepcopy(result.get('limitations',[])),time_basis='analysis_preview_milliseconds',
        technical_error_assessment='not_assessed',authenticated_coach=False)


class LoopStore:
    def __init__(self,plans,registry,videos):
        self.plans,self.registry,self.videos = plans,registry,videos
        self.lock,self.records = RLock(),{}

    def clear(self):
        with self.lock:self.records.clear()

    def _prune(self):
        self.videos.prune()
        self.records = {k:v for k,v in self.records.items() if v[-1]['job_id'] in self.videos.jobs
            and self.videos.jobs[v[-1]['job_id']].owner == v[-1]['_video_owner']}

    def _owned(self,key,owner,token):
        self.videos.authorized(token)
        self._prune()
        versions = self.records.get(key)
        if not versions or (versions[-1]['_owner'],versions[-1]['_video_owner']) != (owner,token):
            raise VideoError(404,'loop_not_found')
        return versions

    def _context(self,record,owner,token):
        raw = self.videos.result(token,record['job_id'])
        versions = self.plans.read(record['plan_id'],history=True,owner=owner)
        linked = next((p for p in versions if p['version']==record['plan_version']),None)
        if linked is None or linked['lesson']['lesson_id']!='L05':raise RegistryError('L05 plan unavailable')
        plan = guard_current_evidence(linked,self.registry)
        latest = guard_current_evidence(versions[-1],self.registry)
        analysis = analysis_view(raw,record['job_id'])
        binding = digest({'plan':plan,'latest_plan':latest,'analysis':analysis})
        return plan,latest['version'],analysis,binding,raw

    def _commit(self,key,versions):
        proposed = {**self.records,key:versions}
        if sum(len(v) for v in proposed.values()) > 100 or len(json.dumps(proposed,ensure_ascii=False).encode()) > 2*1024*1024:
            raise RegistryError('Loop history capacity reached; export and delete old records')
        self.records = proposed

    def link(self,payload,owner,token):
        with self.lock,self.videos.lock:
            self._prune()
            plan = self.plans.read(payload.plan_id,owner=owner)
            if plan['lesson']['lesson_id']!='L05' or plan['version']!=payload.expected_plan_version:
                raise RegistryError('Select the current saved L05 plan version')
            record = dict(loop_id=uuid4().hex,version=1,plan_id=payload.plan_id,plan_version=plan['version'],
                job_id=payload.job_id,learner_code=payload.learner_code,lesson_id='L05',
                observation=payload.observation,practice_task=payload.practice_task,
                _owner=owner,_video_owner=token,changed_at=now(),operation='linked',confirmation=None)
            _,_,analysis,binding,_ = self._context(record,owner,token)
            record.update(saved_analysis=analysis,evidence_digest=binding)
            self._commit(record['loop_id'],[record])
            return self._view(record,owner,token)

    def _view(self,record,owner,token):
        plan,latest,analysis,binding,raw = self._context(record,owner,token)
        value = {k:deepcopy(v) for k,v in record.items() if not k.startswith('_')}
        confirmed = record['confirmation'] is not None and record['evidence_digest']==binding
        value.update(schema_version='l05-teaching-loop-v1',plan=plan,current_plan_version=latest,
            analysis=analysis,current_evidence_digest=binding,evidence_changed=record['evidence_digest']!=binding,
            is_mock=raw['is_mock'],data_origin=analysis['origin'],
            feedback_review_status='locally_confirmed_unverified' if confirmed else 'draft',
            review_label='本地教师自报确认（身份未认证，非专业审核）' if confirmed else '反馈草稿，待本地教师确认',
            confirmation_current=confirmed,requires_teacher_confirmation=not confirmed,
            authenticated_teacher=False,specialist_review_status='pending',technical_error_assessment='not_assessed',
            trusted_observations=[],
            base_feedback=feedback(raw,record['job_id']),
            warning='仅为合成演示，未执行MediaPipe或真实授课。' if raw['is_mock'] else '仅为本机二维观测；不证明动作错误、用刃或技术等级。',
            lifecycle='本机进程内存；受原视频20分钟任务/30分钟会话限制，删除或失效后不可读，访问时清理，退出清空；请自行保管导出。')
        # Reuse existing safe feedback, without copying file/actor references.
        value['base_feedback'].pop('source',None)
        return value

    def change(self,payload,owner,token,*,confirm=False):
        with self.lock,self.videos.lock:
            versions = self._owned(payload.loop_id,owner,token)
            record = deepcopy(versions[-1])
            if record['version']!=payload.expected_version:raise RegistryError('Loop version conflict')
            _,_,analysis,binding,_ = self._context(record,owner,token)
            if binding!=payload.expected_evidence_digest:raise RegistryError('Evidence changed; refresh before saving or confirming')
            if confirm:
                if payload.acknowledged is not True or not record['observation'] or not record['practice_task']:
                    raise RegistryError('Explicit confirmation and saved observation/task required')
                record['confirmation'] = dict(at=now(),actor='local_unverified_operator',verification='local_unverified',
                    acknowledgement='已自行核对质量、候选变化、观察文字和复练任务；身份与专业资格未认证。')
                record['operation']='locally_confirmed'
            else:
                record.update(observation=payload.observation,practice_task=payload.practice_task,confirmation=None,operation='edited')
            record.update(version=record['version']+1,changed_at=now(),saved_analysis=analysis,evidence_digest=binding)
            self._commit(payload.loop_id,[*versions,record])
            return self._view(record,owner,token)

    def read(self,key,owner,token):
        with self.lock,self.videos.lock:
            versions = self._owned(key,owner,token)
            value = self._view(versions[-1],owner,token)
            value['history'] = [{k:deepcopy(v) for k,v in r.items() if not k.startswith('_')} for r in versions]
            return value

    def current(self,owner,token):
        with self.lock,self.videos.lock:
            self.videos.authorized(token);self._prune()
            return {'records':[dict(loop_id=k,learner_code=v[-1]['learner_code'],version=v[-1]['version'])
                for k,v in self.records.items() if (v[-1]['_owner'],v[-1]['_video_owner'])==(owner,token)]}

    def delete(self,key,owner,token):
        with self.lock,self.videos.lock:
            self._owned(key,owner,token)
            del self.records[key]
            return {'state':'deleted'}
