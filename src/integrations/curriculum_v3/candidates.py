"""Explicit conversion of the supplied draft-0.1 format, never an approval."""
from typing import Literal
from pydantic import Field, model_validator
from .registry import Strict, Knowledge, Archive
from .review import EvidenceReport, knowledge_digest


class Candidate(Strict):
    knowledge_id: str
    category: Literal['KB-S','KB-P','KB-E']
    lesson_ids: list[str]
    title: str
    claim: str
    source_id: str
    source_title: str
    source_locator: str
    source_verification_status: Literal['unverified']
    evidence_inspection_note: str
    specialist_review_status: Literal['pending']
    reviewer: None
    version: Literal['draft-0.1']
    applicability_limitations: str
    import_warning: Literal['candidate_not_approved']


class CandidatePackage(Strict):
    schema_version: Literal['coachloop-knowledge-candidates-0.1']
    status: Literal['DRAFT_NOT_APPROVED']
    source_registry: dict[str,str]
    entries: list[Candidate] = Field(max_length=200)

    @model_validator(mode='after')
    def sources(self):
        if len({e.knowledge_id for e in self.entries})!=len(self.entries):raise ValueError('Duplicate candidate IDs')
        if any(self.source_registry.get(e.source_id)!=e.source_title for e in self.entries):raise ValueError('Source registry mismatch')
        return self


def convert(package):
    package=CandidatePackage.model_validate(package)
    entries=[]
    for candidate in package.entries:
        kind='source_summary'
        if '目录' in candidate.evidence_inspection_note:kind='catalogue_lead'
        elif candidate.knowledge_id in ('K011','K016','K018','K019','K020','K021'):kind='course_proposal'
        entries.append(Knowledge(knowledge_id=candidate.knowledge_id,category=candidate.category,
            lesson_ids=candidate.lesson_ids,title=candidate.title,content=candidate.claim,
            source_id=candidate.source_id,source_title=candidate.source_title,source_locator=candidate.source_locator,
            source_verification_status='pending',specialist_review_status='pending',version=1,
            candidate_version=candidate.version,evidence_inspection_note=candidate.evidence_inspection_note,
            applicability_limitations=candidate.applicability_limitations,content_kind=kind))
    return Archive(entries=entries)


def reported_evidence(archive,candidate_hash,answers_hash):
    records=[]
    for entry in archive.entries:
        common=dict(knowledge_id=entry.knowledge_id,knowledge_version=entry.version,
            knowledge_digest=knowledge_digest(entry.model_dump()),source_id=entry.source_id,reviewer=None,review_date=None)
        records.append(EvidenceReport(**common,evidence_id=f'REPORT_{entry.knowledge_id}_SOURCE',kind='source_report',
            basis_kind='supplied_summary',artifact_name='03_Knowledge_Candidates.json',artifact_sha256=candidate_hash,
            locator=entry.source_locator,statement='上传整理材料声明：'+entry.evidence_inspection_note+'；本次未获得教材原PDF，系统未核实原文。'))
        records.append(EvidenceReport(**common,evidence_id=f'REPORT_{entry.knowledge_id}_CONTEXT',kind='user_confirmation',
            basis_kind='user_statement',artifact_name='01_Expert_Reviewed_Answers.docx',artifact_sha256=answers_hash,
            locator='五问填答稿及本会话用户说明（不是逐条专项审核）',
            statement='用户说明专项同学认可五问内容；未提供本条具名审核记录。该文件自述不是专项教师签署的审核证明。不得推定此条已获得逐条确认。'))
    return records
