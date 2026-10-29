"""Restricted direct SQL inserts and frozen-migration regression cases, synthetic only."""
import ast
import copy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert,select,text
from sqlalchemy.exc import DBAPIError

from storage.teaching.models import EVENT_SNAPSHOT_CHECK,PoseEvent


def event_values(tenant,session):
    original={'feature':'knee_angle_deg','frame_start':1,'frame_end':2,
              'start_time_ms':100,'end_time_ms':200,'deviation_max':12}
    return dict(tenant_id=tenant,training_session_id=session,analysis_run_id=uuid4(),
                **original,original_event=copy.deepcopy(original),
                source_snapshot={'is_mock':True,'source':'mock://synthetic'})


@pytest.mark.parametrize('field,value',[
    ('feature','torso_pitch_deg'),('frame_start',0),('frame_end',3),
    ('start_time_ms',9000),('end_time_ms',99000),('deviation_max',999),
    ('deviation_max',12.0000000001),
    ('frame_start',1.1),('frame_end',2.1),('frame_start',1.0),
])
def test_snapshot_mismatch_blocked_for_real_restricted_teacher(actors,tenant,chain,field,value):
    values=event_values(tenant,chain['session_id'])
    values['original_event'][field]=value
    with pytest.raises(DBAPIError) as error:
        with actors[tenant]['teacher'].begin() as conn:
            conn.execute(insert(PoseEvent).values(**values))
    assert error.value.orig.sqlstate=='23514'
    assert error.value.orig.diag.constraint_name=='ck_event_snapshot'


@pytest.mark.parametrize('field',['feature','frame_start','frame_end','start_time_ms','end_time_ms','deviation_max'])
@pytest.mark.parametrize('bad',['missing',None,False,{},[]])
def test_missing_null_or_wrong_type_never_passes_check(actors,tenant,chain,field,bad):
    values=event_values(tenant,chain['session_id'])
    if bad=='missing': del values['original_event'][field]
    else: values['original_event'][field]=bad
    with pytest.raises(DBAPIError) as error:
        with actors[tenant]['teacher'].begin() as conn:
            conn.execute(insert(PoseEvent).values(**values))
    assert error.value.orig.sqlstate=='23514'
    assert error.value.orig.diag.constraint_name=='ck_event_snapshot'


@pytest.mark.parametrize('value',['100','NaN','Infinity','not-a-number'])
def test_string_values_cannot_impersonate_numeric_evidence(actors,tenant,chain,value):
    values=event_values(tenant,chain['session_id'])
    values['original_event']['start_time_ms']=value
    with pytest.raises(DBAPIError) as error:
        with actors[tenant]['teacher'].begin() as conn:
            conn.execute(insert(PoseEvent).values(**values))
    assert error.value.orig.sqlstate=='23514'


def test_exact_decimal_consistency_and_authenticated_actor(actors,tenant,chain):
    values=event_values(tenant,chain['session_id'])
    # Numeric JSON tokens use their decimal value; generated/structured values keep it.
    values.update(start_time_ms=Decimal('100.125'),end_time_ms=Decimal('200.875'),deviation_max=Decimal('12.0625'))
    values['original_event'].update(start_time_ms=100.125,end_time_ms=200.875,deviation_max=12.0625)
    with actors[tenant]['teacher'].begin() as conn:
        row=conn.execute(insert(PoseEvent).values(**values).returning(PoseEvent.__table__)).mappings().one()
        assert row['deviation_max']==Decimal('12.0625')
        assert row['start_time_ms']==Decimal('100.125')
        assert row['created_by']==f'tdb_{tenant.hex}_teacher'
        attributes=conn.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user')).one()
        assert tuple(attributes)==(False,False)


def test_original_independent_counterexample_now_rejected(actors,tenant,chain):
    values=event_values(tenant,chain['session_id'])
    values['original_event'].update(start_time_ms=9000,end_time_ms=99000,deviation_max=999)
    with pytest.raises(DBAPIError) as error:
        with actors[tenant]['teacher'].begin() as conn:
            conn.execute(insert(PoseEvent).values(**values))
    assert error.value.orig.diag.constraint_name=='ck_event_snapshot'


def test_model_and_new_migration_check_are_identical():
    file=Path(__file__).resolve().parents[2]/'teaching_migrations/versions/0002_event_snapshot.py'
    for node in ast.parse(file.read_text()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='EVENT_SNAPSHOT_CHECK' for t in node.targets):
            assert ast.literal_eval(node.value)==EVENT_SNAPSHOT_CHECK
            break
    else: pytest.fail('Frozen migration expression missing')


@pytest.fixture
def legacy_database(database,monkeypatch):
    """New disposable DB per migration case; never resets existing application data."""
    import os
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    admin,_=database
    name='teaching_snapshot_'+uuid4().hex+'_test'
    with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url=make_url(os.environ['TEACHING_DATABASE_URL']).set(database=name)
    monkeypatch.setenv('TEACHING_DATABASE_URL',url.render_as_string(hide_password=False))
    config=Config(str(Path(__file__).resolve().parents[2]/'teaching_alembic.ini'))
    engine=create_engine(url,hide_parameters=True)
    try:
        command.upgrade(config,'0001_teaching')
        yield engine,config
    finally:
        engine.dispose()
        with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')


def seed_legacy_event(engine,problem=None):
    from storage.teaching.models import Class,Lesson,TrainingSession
    tenant=uuid4()
    with engine.begin() as conn:
        class_id=conn.execute(insert(Class).values(tenant_id=tenant,class_code='MOCK-UPGRADE',
                              display_name='Synthetic migration case',student_count=1).returning(Class.id)).scalar_one()
        lesson_id=conn.execute(insert(Lesson).values(tenant_id=tenant,class_id=class_id,
                               lesson_code='MOCK-UPGRADE').returning(Lesson.id)).scalar_one()
        session=conn.execute(insert(TrainingSession).values(tenant_id=tenant,lesson_id=lesson_id,
                             session_code='MOCK-UPGRADE',participant_code='MOCK-P001').returning(TrainingSession.id)).scalar_one()
        values=event_values(tenant,session)
        if problem=='mismatch': values['original_event']['deviation_max']=999
        if problem=='missing': del values['original_event']['end_time_ms']
        id=conn.execute(insert(PoseEvent).values(**values).returning(PoseEvent.id)).scalar_one()
    return id,values['original_event']


def test_forward_migration_and_downgrade_preserve_consistent_rows(legacy_database):
    from alembic import command
    engine,config=legacy_database
    id,snapshot=seed_legacy_event(engine)
    command.upgrade(config,'head')
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM teaching_alembic_version'))=='0003_training_import'
        assert conn.scalar(select(PoseEvent.original_event).where(PoseEvent.id==id))==snapshot
        policies=conn.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='teaching.pose_events'::regclass")).one()
        assert tuple(policies)==(True,True)
    command.downgrade(config,'0001_teaching')
    with engine.connect() as conn:
        assert conn.scalar(select(PoseEvent.original_event).where(PoseEvent.id==id))==snapshot
        assert conn.scalar(text('SELECT version_num FROM teaching_alembic_version'))=='0001_teaching'
    command.upgrade(config,'head')
    with engine.connect() as conn:
        assert conn.scalar(select(PoseEvent.original_event).where(PoseEvent.id==id))==snapshot


@pytest.mark.parametrize('problem',['missing','mismatch'])
def test_existing_bad_snapshots_abort_upgrade_without_rewrite(legacy_database,problem):
    from alembic import command
    from sqlalchemy import inspect
    engine,config=legacy_database
    id,snapshot=seed_legacy_event(engine,problem)
    with pytest.raises(DBAPIError) as error:
        command.upgrade(config,'head')
    assert error.value.orig.sqlstate=='23514'
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM teaching_alembic_version'))=='0001_teaching'
        assert conn.scalar(select(PoseEvent.original_event).where(PoseEvent.id==id))==snapshot
        constraint=next(c for c in inspect(conn).get_check_constraints('pose_events',schema='teaching') if c['name']=='ck_event_snapshot')
        assert 'start_time_ms' not in constraint['sqltext']  # old constraint restored by transactional DDL
