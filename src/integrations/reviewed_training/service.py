"""Tenant-scoped persistence and neutral, provenance-bearing summaries."""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Engine,text
from sqlalchemy.exc import DBAPIError

from .json_codec import encode
from .schemas import ImportRequest


@dataclass(frozen=True)
class TrustedIdentity:
    """Server-injected after authentication; never deserialize from HTTP input.

    The engine must authenticate as this tenant-bound, restricted database login.
    Do not pass a migration/admin engine or SET ROLE on a shared owner connection.
    """
    tenant_id: UUID
    db_login: str
    engine: Engine


def checked_connection(connection,identity,write=False):
    row=connection.execute(text('SELECT session_user AS login,teaching.current_tenant() AS tenant,pg_has_role(session_user,\'teaching_importer\',\'member\') AS importer')).mappings().one()
    if row['login']!=identity.db_login or row['tenant']!=identity.tenant_id:
        raise HTTPException(403,'Identity and database session do not agree')
    if write and not row['importer']:
        raise HTTPException(403,'A dedicated importer database login is required')


def available_session(connection,identity,session_id):
    if connection.scalar(text("SELECT id FROM teaching.training_sessions WHERE tenant_id=:tenant AND data_domain='mock' AND id=:id"),{'tenant':identity.tenant_id,'id':session_id}) is None:
        raise HTTPException(404,'Training session unavailable')


def event_summary(connection,identity,row):
    claims=connection.execute(text('''SELECT DISTINCT ON(source_stream_id) source_stream_id,source_sequence,source_status,verification_status,text_status
        FROM teaching_ingest.review_claims WHERE tenant_id=:tenant AND data_domain='mock' AND pose_event_id=:event
        ORDER BY source_stream_id,source_sequence DESC LIMIT 101'''),{'tenant':identity.tenant_id,'event':row['id']}).mappings().all()
    trusted=row['review_seq'] is not None
    eligible=trusted and row['review_status'] in ('confirmed','normal_movement') and row['quality_status']=='candidate'
    return dict(event_id=row['id'],source_event_id=row['legacy_event_id'],analysis_run_id=row['analysis_run_id'],
        feature=row['feature'],frame_start=row['frame_start'],frame_end=row['frame_end'],
        start_time_ms=row['start_time_ms'],end_time_ms=row['end_time_ms'],deviation_max=row['deviation_max'],
        effective_review_status=row['review_status'],effective_review_verification='authenticated' if trusted else 'unreviewed',
        trusted_review_sequence=row['review_seq'],observation_summary_eligible=eligible,
        technical_error_assessment='not_assessed',
        imported_review_claims=[dict(c) for c in claims[:100]],claim_streams_truncated=len(claims)>100)


def query_results(connection,identity,session_id,run_id,limit=50,cursor=None,event_ids=None):
    available_session(connection,identity,session_id)
    params={'tenant':identity.tenant_id,'session':session_id,'run':run_id,'limit':limit+1}
    conditions="e.tenant_id=:tenant AND e.data_domain='mock' AND e.training_session_id=:session AND e.analysis_run_id=:run"
    if cursor is not None:
        conditions+=' AND e.id>:cursor';params['cursor']=cursor
    if event_ids is not None:
        conditions+=' AND e.id=ANY(CAST(:ids AS uuid[]))';params['ids']=event_ids
    rows=connection.execute(text('''SELECT e.id,e.legacy_event_id,e.analysis_run_id,e.feature,e.frame_start,e.frame_end,
        e.start_time_ms,e.end_time_ms,e.deviation_max,e.quality_status,s.review_status,s.review_seq
        FROM teaching.pose_events e JOIN teaching.event_review_state s ON s.id=e.id
        AND s.tenant_id=e.tenant_id AND s.data_domain=e.data_domain WHERE '''+conditions+' ORDER BY e.id LIMIT :limit'),params).mappings().all()
    events=[event_summary(connection,identity,row) for row in rows[:limit]]
    return dict(schema_version='reviewed-training-results-v1',data_domain='mock',training_session_id=session_id,
        analysis_run_id=run_id,events=events,next_cursor=events[-1]['event_id'] if len(rows)>limit else None,
        summary=dict(event_count=len(events),trusted_reviewed_event_count=sum(e['effective_review_verification']=='authenticated' for e in events),
                     observation_summary_eligible_count=sum(e['observation_summary_eligible'] for e in events),
                     technical_error_assessment='not_assessed',scope='returned_page'))


def import_results(identity,request: ImportRequest,key: UUID):
    try:
        with identity.engine.begin() as connection:
            checked_connection(connection,identity,write=True)
            receipt=connection.execute(text('SELECT * FROM teaching_ingest.import_results(:key,CAST(:payload AS jsonb))'),
                                       {'key':key,'payload':encode(request.model_dump(mode='python'))}).mappings().one()
            mappings=connection.scalar(text('SELECT event_map FROM teaching_ingest.receipts WHERE id=:id AND tenant_id=:tenant'),{'id':receipt['receipt_id'],'tenant':identity.tenant_id})
            result=query_results(connection,identity,request.training_session_id,request.analysis_run_id,
                                 limit=100,event_ids=[UUID(m['event_id']) for m in mappings])
            return {**result,**dict(receipt),'data_received':True,'upstream_reviews_authenticated':False}
    except DBAPIError as error:
        code=error.orig.sqlstate
        if code=='P0002': raise HTTPException(404,'Training binding unavailable') from None
        if code=='42501': raise HTTPException(403,'Importer permission or registered synthetic provenance required') from None
        if code in ('23505','40001'): raise HTTPException(409,'Idempotency, event or source history conflict') from None
        if code in ('23514','23502','23503','22P02','22007','22008'): raise HTTPException(422,'Import violates the database contract') from None
        raise HTTPException(503,'Training result storage unavailable') from None
