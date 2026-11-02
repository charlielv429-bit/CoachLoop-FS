"""Bounded process-local registry. No certified review channel exists in phase one.

All edits/imports remain unverified. History is immutable to callers, append-only,
and protected by optimistic versioning and a process lock. Export before restart.
"""
import json
import re
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

LESSONS = json.loads(Path(__file__).with_name('lessons.json').read_text())
LESSON_IDS = {x['lesson_id'] for x in LESSONS}
CATEGORIES = {'KB-S': '花样滑冰专项技能', 'KB-P': '体育教学方法', 'KB-A': 'AI技术', 'KB-E': '学习评价与反馈'}
Identifier = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Knowledge(Strict):
    knowledge_id: Identifier
    category: Literal['KB-S', 'KB-P', 'KB-A', 'KB-E']
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    lesson_ids: list[str] = Field(max_length=8)
    chapter: str = Field(default='', max_length=300)
    candidate_version: str = Field(default='', max_length=100)
    evidence_inspection_note: str = Field(default='', max_length=1000)
    applicability_limitations: str = Field(default='', max_length=2000)
    content_kind: Literal['source_summary','catalogue_lead','course_proposal','unspecified'] = 'unspecified'
    source_id: str = Field(default='', max_length=64)
    source_title: str = Field(default='', max_length=300)
    source_locator: str = Field(default='', max_length=1000)
    source_verification_status: Literal['pending', 'submitted', 'rejected'] = 'pending'
    specialist_review_status: Literal['pending', 'requested', 'rejected'] = 'pending'
    version: int = Field(ge=1, le=10000)

    @field_validator('title', 'content', 'source_id', 'source_title', 'source_locator', 'chapter', 'candidate_version', 'evidence_inspection_note', 'applicability_limitations')
    @classmethod
    def safe_text(cls, value):
        # Plain text only; locators are displayed as text, never fetched or linked.
        if re.search(r'[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value):
            raise ValueError('Plain text required')
        return value.strip()

    @field_validator('title', 'content')
    @classmethod
    def nonblank(cls, value):
        if not value:
            raise ValueError('Text cannot be blank')
        return value

    @field_validator('lesson_ids')
    @classmethod
    def lessons(cls, value):
        if len(value) != len(set(value)) or not set(value) <= LESSON_IDS:
            raise ValueError('Unknown or duplicate lesson')
        return value

    @field_validator('source_verification_status')
    @classmethod
    def source_status(cls, value, info):
        if value == 'submitted' and not all(info.data.get(k) for k in ('source_id', 'source_title', 'source_locator')):
            raise ValueError('Source registration is incomplete')
        return value


class Archive(Strict):
    schema_version: Literal['coachloop-kb-v3.0'] = 'coachloop-kb-v3.0'
    entries: list[Knowledge] = Field(max_length=500)


def source_conflict(entry):
    # A read-only advisory for the supplied v1 candidates. Preserve stored facts.
    if (entry.knowledge_id in ('K010','K011','K018') and entry.version==1
            and entry.source_id=='B02' and entry.candidate_version=='draft-0.1'
            and entry.source_locator=='PDF94–104；印刷80–90'):
        return '用户说明PDF90–93主要为压步/前压步，PDF94起转入后压步；尚无原PDF可核查，原定位保留，待逐页复核，不得认证为前压步原文。'
    return ''


def presented(entry):
    data = entry.model_dump()
    complete = all(data[k] for k in ('source_id', 'source_title', 'source_locator'))
    conflict=source_conflict(entry)
    return {**data,'source_conflict_status':'unresolved' if conflict else 'not_flagged','source_conflict_note':conflict, 'source_label': '已登记，待核实' if complete else '待补充',
            'review_label': '已退回，待审核' if entry.specialist_review_status == 'rejected' else '待审核',
            'formal_teaching_basis': False}


class RegistryError(ValueError):
    pass


class Registry:
    storage_description = '进程内存测试/嵌入模式；知识库共享，退出清空；正式本地启动器默认SQLite。'
    def __init__(self):
        self._history = {}
        self._lock = RLock()

    def clear(self):
        with self._lock:
            self._history.clear()

    def _merged(self, entries):
        history = {k: list(v) for k, v in self._history.items()}
        for entry in entries:
            previous = history.get(entry.knowledge_id, [])
            if entry.version != len(previous) + 1:
                raise RegistryError('Version conflict; reload current history')
            history.setdefault(entry.knowledge_id, []).append(entry.model_copy(deep=True))
        count = sum(map(len, history.values()))
        # Reject aggregate count before Archive's request-schema length validation,
        # otherwise the 501st stored revision raises an unhandled ValidationError.
        if len(history) > 200 or count > 500:
            raise RegistryError('Registry capacity reached; export and use a separate archive')
        # Bound the pretty-printed archive too, so every UI export fits one import.
        archive = Archive(entries=[e for h in history.values() for e in h])
        size = len(json.dumps(archive.model_dump(), ensure_ascii=False, indent=2).encode())
        if size > 900 * 1024:
            raise RegistryError('Registry capacity reached; export and use a separate archive')
        return history

    def save(self, entry):
        # Revalidate even programmatically constructed/mutated models.
        entry = Knowledge.model_validate(entry.model_dump())
        with self._lock:
            self._history = self._merged([entry])
        return presented(entry)

    def import_archive(self, archive):
        archive = Archive.model_validate(archive.model_dump())
        with self._lock:
            self._history = self._merged(archive.entries)
        return {'imported_versions': len(archive.entries)}

    def export(self):
        with self._lock:
            return Archive(entries=[e for h in self._history.values() for e in h]).model_dump()

    def history(self, knowledge_id):
        with self._lock:
            return [presented(e) for e in self._history.get(knowledge_id, [])]

    def search(self, category=None, lesson_id=None, keyword=''):
        with self._lock:
            entries = [h[-1] for h in self._history.values()]
            return [presented(e) for e in entries
                    if (not category or e.category == category)
                    and (not lesson_id or lesson_id in e.lesson_ids)
                    and keyword.casefold() in (e.title + '\n' + e.content + '\n' + e.source_title).casefold()]

    def evidence_reports(self, knowledge_id=None):
        return []

    def teaching_evidence(self, lesson_id):
        return []

    def lessons(self, lesson_id=None):
        result = []
        for lesson in LESSONS:
            if lesson_id and lesson['lesson_id'] != lesson_id:
                continue
            linked = self.search(lesson_id=lesson['lesson_id'])
            result.append({**lesson, 'teaching_objective_draft': '围绕“' + lesson['title'] + '”拟定学习目标；具体动作标准、练习与评价要求待专项教师补充。',
                           'specialist_review_status': 'pending', 'review_label': '待审核',
                           'missing_materials': ['专项教学目标与动作标准待补充', '练习组织与安全要求待补充', '评价量规与真实来源待补充'],
                           'linked_knowledge': linked, 'formal_teaching_basis': []})
        return result
