"""Reported evidence is separate from operator-authenticated review decisions.

HMAC authenticates a local operator action, NOT a coach's identity/signature.
No web endpoint can seal/apply decisions; disabled unless a private key is supplied.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Literal
from pydantic import Field, field_validator
from .registry import Strict, Identifier, Knowledge


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def knowledge_digest(entry):
    return digest(Knowledge.model_validate(entry).model_dump())


class EvidenceReport(Strict):
    evidence_id: Identifier
    knowledge_id: Identifier
    knowledge_version: int = Field(ge=1,le=10000)
    knowledge_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    kind: Literal['source_report','specialist_report','user_confirmation']
    basis_kind: Literal['supplied_summary','original_source_excerpt','specialist_review','user_statement']
    artifact_name: str = Field(min_length=1,max_length=200)
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_id: str = Field(min_length=1,max_length=64)
    locator: str = Field(min_length=1,max_length=1000)
    statement: str = Field(min_length=1,max_length=4000)
    reviewer: str | None = Field(default=None,max_length=200)
    review_date: str | None = Field(default=None,max_length=100)

    @field_validator('artifact_name','source_id','locator','statement','reviewer','review_date')
    @classmethod
    def plain(cls,value):
        if value is None:return value
        value=Knowledge.safe_text(value)
        if not value:raise ValueError('Blank evidence text')
        return value


class EvidenceBundle(Strict):
    reports: list[EvidenceReport] = Field(max_length=500)


class ReviewDecision(Strict):
    review_id: Identifier
    knowledge_id: Identifier
    knowledge_version: int = Field(ge=1,le=10000)
    knowledge_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_evidence_id: Identifier
    specialist_evidence_id: Identifier
    decision: Literal['approved_for_lesson_draft','rejected','revoked']
    approved_statement: str = Field(min_length=1,max_length=10000)
    lesson_ids: list[str] = Field(min_length=1,max_length=8)
    reviewer: str = Field(min_length=1,max_length=200)
    review_date: str | None = Field(default=None,max_length=100)

    @field_validator('approved_statement','reviewer','review_date')
    @classmethod
    def plain(cls,value):
        if value is None:return value
        value=Knowledge.safe_text(value)
        if not value:raise ValueError('Blank decision text')
        return value


class AuthenticatedDecision(Strict):
    record: ReviewDecision
    authentication_tag: str = Field(pattern=r'^[a-f0-9]{64}$')


def read_key(path):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            raise ValueError('Review key must be an owner-only regular file')
        key=os.read(fd,33)
        if len(key)!=32:raise ValueError('Review key must contain exactly 32 bytes')
        return key
    finally:os.close(fd)


def seal(record,key):
    record=ReviewDecision.model_validate(record)
    tag=hmac.new(key,json.dumps(record.model_dump(),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    return AuthenticatedDecision(record=record,authentication_tag=tag)


def authenticated(envelope,key):
    return key is not None and hmac.compare_digest(seal(envelope.record.model_dump(),key).authentication_tag,envelope.authentication_tag)
