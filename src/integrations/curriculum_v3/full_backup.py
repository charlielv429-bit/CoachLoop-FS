"""Offline complete snapshot; ordinary import cannot restore review authority.

The manifest authenticates history ORDER and completeness as one unit. Individual
review tags alone cannot detect deletion of a later revocation.
"""
import hashlib
import hmac
import json
from typing import Literal
from pydantic import Field
from .registry import Strict, Archive, RegistryError
from .review import EvidenceReport, AuthenticatedDecision

MAX_FULL_BACKUP_BYTES = 32 * 1024 * 1024
DOMAIN = b'coachloop-full-backup-v1\x00'


class FullBackup(Strict):
    schema_version: Literal['coachloop-kb-full-v1'] = 'coachloop-kb-full-v1'
    archive: Archive
    evidence_reports: list[EvidenceReport] = Field(max_length=500)
    # Original SQLite insertion order, including rejections and revocations.
    review_decisions: list[AuthenticatedDecision] = Field(max_length=500)
    snapshot_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    authentication_tag: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')


def canonical(body):
    return json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def snapshot(body,key):
    data=canonical(body)
    if len(data)>MAX_FULL_BACKUP_BYTES:raise RegistryError('Complete backup is too large')
    if body['review_decisions'] and key is None:
        raise RegistryError('Complete review history backup requires the private review key')
    return FullBackup.model_validate({**body,'snapshot_digest':hashlib.sha256(data).hexdigest(),
        'authentication_tag':hmac.new(key,DOMAIN+data,hashlib.sha256).hexdigest() if key is not None else None})


def verified_body(backup,key):
    backup=FullBackup.model_validate(backup.model_dump())
    body=backup.model_dump(exclude={'snapshot_digest','authentication_tag'})
    data=canonical(body)
    if len(data)>MAX_FULL_BACKUP_BYTES or not hmac.compare_digest(hashlib.sha256(data).hexdigest(),backup.snapshot_digest):
        raise RegistryError('Complete backup checksum mismatch')
    if backup.review_decisions and backup.authentication_tag is None:
        raise RegistryError('Review history cannot be restored from an unsigned manifest')
    if backup.authentication_tag is not None:
        if key is None or not hmac.compare_digest(hmac.new(key,DOMAIN+data,hashlib.sha256).hexdigest(),backup.authentication_tag):
            raise RegistryError('Complete backup authentication unavailable or invalid')
    return backup
