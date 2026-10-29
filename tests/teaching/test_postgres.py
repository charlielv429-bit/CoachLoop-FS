"""Database-level constraints, authenticated role isolation and append-only audit."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

from storage.teaching.models import Base, Class, Lesson, LessonPlan, TrainingSession, PoseEvent, CoachReview
from storage.teaching.mock_data import mock_plan_payload, seed_mock_chain


def sql_error(engine,statement,params=None,codes=None):
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as conn:
            conn.execute(text(statement),params or {})
    if codes: assert error.value.orig.sqlstate in codes


def test_migration_six_tables_and_orm_alignment(database):
    from sqlalchemy import inspect
    admin,_=database
    with admin.connect() as conn:
        tables=inspect(conn).get_table_names(schema='teaching')
        assert set(tables)=={t.name for t in Base.metadata.tables.values()}
        assert conn.scalar(text('SELECT version_num FROM teaching_alembic_version'))=='0001_teaching'
        for table in Base.metadata.tables.values():
            actual={c['name'] for c in inspect(conn).get_columns(table.name,schema='teaching')}
            assert actual==set(table.columns.keys())
        rows=conn.execute(text("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='teaching' AND relkind='r'")).all()
        assert len(rows)==6 and all(enabled and forced for _,enabled,forced in rows)


def test_complete_mock_chain_and_exact_load(actors,tenant,chain):
    with actors[tenant]['reader'].connect() as conn:
        count=conn.scalar(text('''SELECT count(*) FROM teaching.classes c
          JOIN teaching.lessons l ON l.class_id=c.id
          JOIN teaching.lesson_plans p ON p.lesson_id=l.id
          JOIN teaching.training_sessions s ON s.lesson_plan_id=p.id
          JOIN teaching.pose_events e ON e.training_session_id=s.id
          JOIN teaching.coach_reviews r ON r.pose_event_id=e.id WHERE c.id=:id'''),{'id':chain['class_id']})
        assert count==1
        plan=conn.execute(select(LessonPlan.__table__).where(LessonPlan.id==chain['plan_id'])).mappings().one()
        assert plan['group_active_minutes']==Decimal('33.75') and plan['group_density']==75
        assert plan['review_status']=='approved' and len(plan['review_history'])==2
        assert plan['created_by'].endswith('_agent') and plan['reviewed_by'].endswith('_teacher')
        assert plan['updated_at']>=plan['created_at']
        state=conn.execute(text('SELECT * FROM teaching.event_review_state WHERE id=:id'),{'id':chain['event_id']}).mappings().one()
        assert state['review_status']=='confirmed' and state['reviewer_id'].endswith('_coach')
        assert 'technical_error' not in state


def test_cross_tenant_read_write_and_guc_spoof(actors,tenant,chain):
    other=next(t for t in actors if t!=tenant)
    with actors[other]['reader'].begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id',:tenant,true)"),{'tenant':str(tenant)})
        assert conn.scalar(text('SELECT count(*) FROM teaching.classes WHERE id=:id'),{'id':chain['class_id']})==0
        assert conn.scalar(text('SELECT count(*) FROM teaching.event_review_state WHERE id=:id'),{'id':chain['event_id']})==0
    sql_error(actors[other]['teacher'],"INSERT INTO teaching.classes(tenant_id,class_code,display_name,student_count) VALUES(:tenant,'MOCK-ATTACK','Synthetic',1)",{'tenant':tenant},{'42501'})
    sql_error(actors[other]['teacher'],"INSERT INTO teaching.lessons(tenant_id,class_id,lesson_code) VALUES(:tenant,:class,'MOCK-CROSS')",{'tenant':other,'class':chain['class_id']},{'23503'})
    sql_error(actors[other]['agent'],'SELECT teaching.create_draft(:lesson,CAST(:p AS jsonb))',{'lesson':chain['lesson_id'],'p':json.dumps(mock_plan_payload())},{'42501'})


@pytest.mark.parametrize('model,values',[
    (Class,{'class_code':'MOCK-PILOT','display_name':'Synthetic','student_count':1}),
    (Lesson,{'class_id':uuid4(),'lesson_code':'MOCK-PILOT'}),
    (LessonPlan,{'lesson_id':uuid4(),'version_no':1,'payload':{},'prep_minutes':9,'main_minutes':29,'closing_minutes':7,'load_total_minutes':45,'group_active_minutes':30,'individual_active_minutes':25,'avg_hr':140}),
    (TrainingSession,{'lesson_id':uuid4(),'session_code':'MOCK-PILOT','participant_code':'MOCK-P001'}),
    (PoseEvent,{'training_session_id':uuid4(),'analysis_run_id':uuid4(),'feature':'knee_angle_deg','frame_start':1,'frame_end':2,'start_time_ms':0,'end_time_ms':1,'deviation_max':1,'original_event':{'feature':'knee_angle_deg','frame_start':1,'frame_end':2},'source_snapshot':{'is_mock':True,'source':'mock://synthetic'}}),
    (CoachReview,{'pose_event_id':uuid4(),'review_seq':1,'status':'pending','reviewer_id':'synthetic','idempotency_key':uuid4()}),
])
def test_pilot_rejected_even_for_admin(database,tenant,model,values):
    admin,_=database
    with pytest.raises(DBAPIError) as error:
        with admin.begin() as conn:
            conn.execute(insert(model).values(tenant_id=tenant,data_domain='pilot',**values))
    assert error.value.orig.sqlstate=='23514'
    assert error.value.orig.diag.constraint_name=='ck_mock_only'


def test_composite_foreign_keys_include_domain(database):
    from sqlalchemy import inspect
    with database[0].connect() as conn:
        for name in ('lessons','lesson_plans','training_sessions','pose_events','coach_reviews'):
            for fk in inspect(conn).get_foreign_keys(name,schema='teaching'):
                assert fk['constrained_columns'][:2]==['tenant_id','data_domain']


@pytest.mark.parametrize('role',['agent','teacher','coach','reader'])
def test_no_direct_review_writes(actors,tenant,chain,role):
    engine=actors[tenant][role]
    for statement in (
        "UPDATE teaching.lesson_plans SET review_status='approved' WHERE id=:plan",
        "UPDATE teaching.coach_reviews SET status='normal_movement' WHERE pose_event_id=:id",
        "DELETE FROM teaching.coach_reviews WHERE pose_event_id=:id",
        "INSERT INTO teaching.coach_reviews(tenant_id,pose_event_id,review_seq,status,reviewer_id,idempotency_key) VALUES(:tenant,:id,99,'confirmed','forged',:key)",
    ):
        sql_error(engine,statement,{'id':chain['event_id'],'plan':chain['plan_id'],'tenant':tenant,'key':uuid4()},{'42501'})


def test_agent_cannot_approve_or_forge_coach(actors,tenant,chain):
    engine=actors[tenant]['agent']
    sql_error(engine,"SELECT teaching.review_plan(:id,'approved',0,'forged')",{'id':chain['plan_id']},{'42501'})
    sql_error(engine,"SELECT teaching.review_event(:id,'confirmed',1,:key,'forged')",{'id':chain['event_id'],'key':uuid4()},{'42501'})
    sql_error(engine,'SET ROLE teaching_teacher',codes={'42501'})


def test_reviewer_comes_from_login_and_history_appends(actors,tenant,chain):
    engine=actors[tenant]['coach']; key=uuid4()
    with engine.begin() as conn:
        review=conn.scalar(text("SELECT teaching.review_event(:id,'tracking_error',1,:key,'Synthetic correction')"),{'id':chain['event_id'],'key':key})
        repeated=conn.scalar(text("SELECT teaching.review_event(:id,'tracking_error',1,:key,'Synthetic correction')"),{'id':chain['event_id'],'key':key})
        assert review==repeated
        records=conn.execute(text('SELECT review_seq,status,reviewer_id FROM teaching.coach_reviews WHERE pose_event_id=:id ORDER BY review_seq'),{'id':chain['event_id']}).all()
        assert [r.status for r in records]==['confirmed','tracking_error']
        assert all(r.reviewer_id==f'tdb_{tenant.hex}_coach' for r in records)
    sql_error(engine,"SELECT teaching.review_event(:id,'uncertain',2,:key,'Different payload')",{'id':chain['event_id'],'key':key},{'23505'})


def test_concurrent_reviews_do_not_overwrite(actors,tenant,chain):
    def review(status):
        try:
            with actors[tenant]['coach'].begin() as conn:
                conn.execute(text('SELECT teaching.review_event(:id,:status,1,:key)'),{'id':chain['event_id'],'status':status,'key':uuid4()})
            return 'ok'
        except DBAPIError as error:
            return error.orig.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(review,['uncertain','normal_movement']))
    assert sorted(results)==['40001','ok']
    with actors[tenant]['reader'].connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM teaching.coach_reviews WHERE pose_event_id=:id'),{'id':chain['event_id']})==2


@pytest.mark.parametrize('status',['approved','technical_error','',None])
def test_invalid_coach_status_rejected(actors,tenant,chain,status):
    sql_error(actors[tenant]['coach'],'SELECT teaching.review_event(:id,:status,1,:key)',{'id':chain['event_id'],'status':status,'key':uuid4()},{'23514'})


@pytest.mark.parametrize('change',[
    ('teaching_flow','total_minutes',46),('teaching_flow','main_minutes',28),
    ('load_accounting','total_minutes',46),('load_accounting','avg_hr',999),
    ('load_accounting','avg_hr','NaN'),('load_accounting','avg_hr','Infinity'),
    ('load_accounting','group_active_minutes',-1),('load_accounting','group_active_minutes',46),
    ('load_accounting','kind','invalid'),
])
def test_invalid_time_and_load_rejected(actors,tenant,chain,change):
    payload=mock_plan_payload();section,key,value=change;payload[section][key]=value
    sql_error(actors[tenant]['agent'],'SELECT teaching.create_draft(:id,CAST(:p AS jsonb))',{'id':chain['lesson_id'],'p':json.dumps(payload)},{'23514'})


def test_missing_element_rejected(actors,tenant,chain):
    payload=mock_plan_payload();del payload['safety_precautions']
    sql_error(actors[tenant]['agent'],'SELECT teaching.create_draft(:id,CAST(:p AS jsonb))',{'id':chain['lesson_id'],'p':json.dumps(payload)},{'23514'})


def test_snapshots_and_plan_history_immutable_for_admin(database,chain):
    for statement,id in (
        ("UPDATE teaching.pose_events SET original_event='{}' WHERE id=:id",chain['event_id']),
        ("DELETE FROM teaching.coach_reviews WHERE id=:id",chain['review_id']),
        ("UPDATE teaching.lesson_plans SET payload='{}' WHERE id=:id",chain['plan_id']),
        ("UPDATE teaching.lesson_plans SET review_history='[]' WHERE id=:id",chain['plan_id']),
    ):
        sql_error(database[0],statement,{'id':id},{'42501'})


def test_wrong_lesson_plan_association_rejected(actors,tenant,chain):
    engine=actors[tenant]['teacher']
    with engine.begin() as conn:
        other=conn.execute(insert(Lesson).values(tenant_id=tenant,class_id=chain['class_id'],lesson_code='MOCK-'+uuid4().hex[:12]).returning(Lesson.id)).scalar_one()
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as conn:
            conn.execute(insert(TrainingSession).values(tenant_id=tenant,lesson_id=other,lesson_plan_id=chain['plan_id'],session_code='MOCK-'+uuid4().hex[:12],participant_code='MOCK-P001'))
    assert error.value.orig.sqlstate=='23503'


def test_pending_event_defaults_and_rollback(actors,tenant,chain):
    engine=actors[tenant]['coach']
    with engine.connect() as conn:
        transaction=conn.begin()
        conn.execute(text("SELECT teaching.review_event(:id,'uncertain',1,:key)"),{'id':chain['event_id'],'key':uuid4()})
        transaction.rollback()
        assert conn.scalar(text('SELECT review_status FROM teaching.event_review_state WHERE id=:id'),{'id':chain['event_id']})=='confirmed'


@pytest.mark.parametrize('model,key',[(Lesson,'lesson_id'),(LessonPlan,'plan_id'),
    (TrainingSession,'session_id'),(PoseEvent,'event_id'),(CoachReview,'review_id')])
def test_each_child_rejects_cross_tenant_fk_even_for_admin(database,actors,tenant,chain,model,key):
    other=next(t for t in actors if t!=tenant)
    admin=database[0]
    with admin.connect() as conn:
        row=dict(conn.execute(select(model.__table__).where(model.id==chain[key])).mappings().one())
    row={k:v for k,v in row.items() if model.__table__.c[k].computed is None}
    row.update(id=uuid4(),tenant_id=other)
    with pytest.raises(DBAPIError) as error:
        with admin.begin() as conn:
            conn.execute(insert(model).values(**row))
    assert error.value.orig.sqlstate=='23503'


def test_new_candidate_is_pending_and_cannot_claim_technical_error(actors,tenant,chain):
    with actors[tenant]['teacher'].begin() as conn:
        event=conn.execute(insert(PoseEvent).values(tenant_id=tenant,training_session_id=chain['session_id'],
            analysis_run_id=uuid4(),feature='torso_pitch_deg',frame_start=1,frame_end=2,
            start_time_ms=0,end_time_ms=1,deviation_max=2,
            original_event={'feature':'torso_pitch_deg','frame_start':1,'frame_end':2},
            source_snapshot={'is_mock':True,'source':'mock://synthetic'}).returning(PoseEvent.id)).scalar_one()
    with actors[tenant]['agent'].connect() as conn:
        state=conn.execute(text('SELECT * FROM teaching.event_review_state WHERE id=:id'),{'id':event}).mappings().one()
        assert state['review_status']=='pending' and state['reviewer_id'] is None
        assert 'technical_error' not in state


def test_version_allocation_and_approval_history_conflict(actors,tenant,chain):
    agent=actors[tenant]['agent']
    with agent.begin() as conn:
        next_id=conn.scalar(text('SELECT teaching.create_draft(:id,CAST(:p AS jsonb))'),{'id':chain['lesson_id'],'p':json.dumps(mock_plan_payload())})
        version=conn.scalar(select(LessonPlan.version_no).where(LessonPlan.id==next_id))
        assert version==2
        conn.execute(text("SELECT teaching.review_plan(:id,'pending',0)"),{'id':next_id})
    sql_error(actors[tenant]['teacher'],"SELECT teaching.review_plan(:id,'approved',0)",{'id':next_id},{'40001'})
    with actors[tenant]['reader'].connect() as conn:
        assert conn.scalar(select(LessonPlan.review_status).where(LessonPlan.id==next_id))=='pending'


def test_generated_density_cannot_be_forged(database,chain):
    # Generated columns reject client-provided results before any calculation can drift.
    sql_error(database[0],'UPDATE teaching.lesson_plans SET group_density=999 WHERE id=:id',{'id':chain['plan_id']},{'428C9'})


def test_all_six_tables_hide_other_tenant_rows(actors,tenant,chain):
    other=next(t for t in actors if t!=tenant)
    with actors[other]['reader'].connect() as conn:
        for model,key in [(Class,'class_id'),(Lesson,'lesson_id'),(LessonPlan,'plan_id'),
                          (TrainingSession,'session_id'),(PoseEvent,'event_id'),(CoachReview,'review_id')]:
            assert conn.execute(select(model.id).where(model.id==chain[key])).first() is None


@pytest.mark.parametrize('function,role,key', [('plan','teacher','plan_id'),('event','coach','event_id')])
def test_review_functions_reject_other_tenant(actors,tenant,chain,function,role,key):
    other=next(t for t in actors if t!=tenant)
    statement=("SELECT teaching.review_plan(:id,'approved',2)" if function=='plan'
               else "SELECT teaching.review_event(:id,'confirmed',1,:request)")
    sql_error(actors[other][role],statement,{'id':chain[key],'request':uuid4()},{'42501'})


def test_concurrent_drafts_allocate_distinct_versions(actors,tenant,chain):
    def create(_):
        with actors[tenant]['agent'].begin() as conn:
            return conn.scalar(text('SELECT teaching.create_draft(:id,CAST(:p AS jsonb))'),
                               {'id':chain['lesson_id'],'p':json.dumps(mock_plan_payload())})
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(create,range(2)))
    with actors[tenant]['reader'].connect() as conn:
        versions=conn.execute(select(LessonPlan.version_no).where(LessonPlan.id.in_(ids))).scalars().all()
    assert sorted(versions)==[2,3]
