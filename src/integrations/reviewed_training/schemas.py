"""Versioned, narrow V4/V5 interchange contract. All incoming reviews are claims."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema,
                      field_validator, model_validator)


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('JSON number required')
    value=value if isinstance(value,Decimal) else Decimal(str(value))
    if not value.is_finite(): raise ValueError('Finite JSON number required')
    if value==0: return Decimal(0)
    # Inspect the tuple directly: normalization can underflow tiny exponents and
    # must not permit an exponent that expands a small JSON token into gigabytes.
    parts=value.as_tuple()
    if max(0,-parts.exponent)>60 or len(parts.digits)+max(0,parts.exponent)>80:
        raise ValueError('Numeric precision exceeds interchange limits')
    return value



Number = Annotated[Decimal, BeforeValidator(numeric), Field(ge=0, le=Decimal('1e12'), max_digits=80, decimal_places=60, allow_inf_nan=False),
                   WithJsonSchema({'type':'number','minimum':0,'maximum':1000000000000,
                                   'x-max-digits':80,'x-max-decimal-places':60})]
Status = Literal['pending','confirmed','normal_movement','tracking_error','uncertain']
Feature = Literal['knee_angle_deg','torso_pitch_deg','hip_ankle_offset_norm']
LegacyID = Annotated[str, Field(pattern=r'^evt_[0-9a-f]{12}$', max_length=16)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class EventFields(StrictModel):
    feature: Feature
    frame_start: int = Field(strict=True, ge=0, le=2147483647)
    frame_end: int = Field(strict=True, ge=0, le=2147483647)
    start_time_ms: Number
    end_time_ms: Number
    deviation_max: Number

    @model_validator(mode='after')
    def ordered(self):
        if self.frame_end < self.frame_start or self.end_time_ms < self.start_time_ms:
            raise ValueError('Frame and time intervals must be ordered')
        return self


class OriginalEvent(EventFields):
    duration_ms: Number | None = None
    n_frames: int | None = Field(default=None,strict=True,ge=1)
    swing: Number | None = None

    @model_validator(mode='after')
    def derived_fields(self):
        if self.n_frames is not None and self.n_frames != self.frame_end-self.frame_start+1:
            raise ValueError('Source frame count contradicts frame interval')
        with localcontext() as context:
            context.prec=160
            if self.duration_ms is not None and self.duration_ms != round(self.end_time_ms-self.start_time_ms,3):
                raise ValueError('Source duration contradicts millisecond interval')
        return self


class ReviewClaim(StrictModel):
    sequence: int = Field(strict=True,ge=1,le=100)
    status: Status
    reviewed_by: str = Field(pattern=r'^MOCK-[A-Z0-9_-]{1,48}$',max_length=53)
    reviewed_at: datetime
    note: str = Field(default='',max_length=1000)

    @field_validator('reviewed_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timezone-aware source review time required')
        try: return value.astimezone(timezone.utc)
        except (ValueError,OverflowError): raise ValueError('UTC timestamp outside supported range') from None

    @field_validator('note')
    @classmethod
    def no_controls(cls,value):
        if any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('Control characters are not accepted')
        return value  # All free text is quarantined at rest, never returned to an Agent.


class Review(StrictModel):
    review_status: Status = 'pending'
    review_history: list[ReviewClaim] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def consistent(self):
        if [r.sequence for r in self.review_history] != list(range(1,len(self.review_history)+1)):
            raise ValueError('Source review history must start at 1 and be contiguous')
        if self.review_history:
            if self.review_status != self.review_history[-1].status:
                raise ValueError('Source current status contradicts history')
            if any(a.reviewed_at>b.reviewed_at for a,b in zip(self.review_history,self.review_history[1:])):
                raise ValueError('Source review times must be ordered')
        elif self.review_status != 'pending':
            raise ValueError('Non-pending source status requires source history')
        return self


class ImportedEvent(EventFields):
    event_id: LegacyID
    original_event: OriginalEvent
    review: Review = Field(default_factory=Review)

    @model_validator(mode='after')
    def equal_snapshot(self):
        if any(getattr(self,key)!=getattr(self.original_event,key) for key in EventFields.model_fields):
            raise ValueError('Structured event and original snapshot must agree exactly')
        return self


class Source(StrictModel):
    kind: Literal['synthetic']
    is_mock: Literal[True]
    artifact_id: UUID
    source_stream_id: UUID

    @field_validator('is_mock',mode='before')
    @classmethod
    def genuine_boolean(cls,value):
        if type(value) is not bool or value is not True:
            raise ValueError('Explicit boolean true required for synthetic input')
        return value


class ImportRequest(StrictModel):
    schema_version: Literal['reviewed-training-import-v1']
    data_domain: Literal['mock']
    time_unit: Literal['ms']
    class_id: UUID
    lesson_id: UUID
    training_session_id: UUID
    analysis_run_id: UUID
    source: Source
    events: list[ImportedEvent] = Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def no_duplicate_events(self):
        ids=[e.event_id for e in self.events]
        spans=[(e.feature,e.frame_start,e.frame_end) for e in self.events]
        if len(set(ids))!=len(ids) or len(set(spans))!=len(spans):
            raise ValueError('Duplicate event identifiers or spans in one batch')
        return self


class ImportedClaimSummary(StrictModel):
    source_stream_id: UUID
    source_sequence: int
    source_status: Status
    verification_status: Literal['imported_unverified']
    text_status: Literal['quarantined']


class EventSummary(EventFields):
    event_id: UUID
    source_event_id: LegacyID | None
    analysis_run_id: UUID
    effective_review_status: Status
    effective_review_verification: Literal['authenticated','unreviewed']
    trusted_review_sequence: int | None
    observation_summary_eligible: bool
    technical_error_assessment: Literal['not_assessed']
    imported_review_claims: list[ImportedClaimSummary]
    claim_streams_truncated: bool


class EvidenceSummary(StrictModel):
    event_count: int
    trusted_reviewed_event_count: int
    observation_summary_eligible_count: int
    technical_error_assessment: Literal['not_assessed']
    scope: Literal['returned_page']


class ResultPage(StrictModel):
    schema_version: Literal['reviewed-training-results-v1']
    data_domain: Literal['mock']
    training_session_id: UUID
    analysis_run_id: UUID
    events: list[EventSummary]
    next_cursor: UUID | None
    summary: EvidenceSummary


class ImportResponse(ResultPage):
    receipt_id: UUID
    replayed: bool
    data_received: Literal[True]
    upstream_reviews_authenticated: Literal[False]
