"""Teacher UI adapters preserve pending authority, atomic seeding and private prints."""
import json
from pathlib import Path
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from integrations.prelesson.console import create_console_app
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.registry import Knowledge
from integrations.prelesson import teacher_api
from test_teaching_loop import setup,post,HEADERS,ORIGIN


@pytest.fixture
def client(tmp_path):
    registry=SQLiteRegistry(tmp_path/'kb')
    with TestClient(create_console_app(knowledge_store=registry),base_url=ORIGIN,client=('127.0.0.1',4000)) as c:
        c.get('/');yield c,registry


def test_root_teacher_ui_and_advanced_remain_distinct(client):
    c,s=client
    root=c.get('/');advanced=c.get('/advanced')
    assert root.status_code==advanced.status_code==200
    assert '教师工作台' in root.text and 'teacher.js' in root.text and 'lesson-form' not in root.text
    assert 'lesson-form' in advanced.text and 'lesson-planning.js' in advanced.text
    assert 'Content-Security-Policy' in root.headers and 'no-store' in root.headers['cache-control']
    # Asset route cannot be redirected to arbitrary files by a query parameter.
    r=c.get('/teacher.js',params={'filename':'/etc/passwd'})
    assert r.status_code==200 and r.text.startswith("'use strict'")


def test_empty_init_is_atomic_pending_and_restart_durable(client):
    c,s=client
    assert c.get('/api/v4/knowledge-status').json()['can_initialize']
    r=post(c,'/api/v4/initialize',{'acknowledged':True})
    assert (r['knowledge_ids'],r['versions'],r['reports'],r['decisions'])==(23,27,50,0)
    assert not r['can_initialize']
    before=s.export_full()
    assert all(e['source_verification_status']==e['specialist_review_status']=='pending' for e in before['archive']['entries'])
    assert s.teaching_evidence('L05')==[]
    assert [e['version'] for e in s.history('K010')]==[1,2]
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers=HEADERS).status_code==409
    assert s.export_full()==before
    second=SQLiteRegistry(s.directory);assert second.export_full()==before;second.close()


@pytest.mark.parametrize('body',[{}, {'acknowledged':False},{'acknowledged':1},{'acknowledged':'true'}, {'acknowledged':True,'review_status':'approved'}, {'acknowledged':True,'archive':{}}])
def test_initialization_requires_explicit_consent_not_user_archive(client,body):
    c,s=client
    assert c.post('/api/v4/initialize',json=body,headers=HEADERS).status_code==422
    assert s.export()['entries']==[]


def test_existing_partial_or_report_only_state_is_not_overwritten(client):
    c,s=client
    s.save(Knowledge(knowledge_id='SYNTHETIC_EXISTING',category='KB-S',title='合成原有记录',content='仅测试已有数据保护',lesson_ids=[],version=1))
    before=s.export_full()
    assert not c.get('/api/v4/knowledge-status').json()['can_initialize']
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers=HEADERS).status_code==409
    assert s.export_full()==before


def test_late_seed_validation_failure_rolls_back_all_rows(client,monkeypatch):
    c,s=client
    bundle=teacher_api.bundled().model_dump();bundle['evidence_reports'][-1]['knowledge_digest']='0'*64
    from integrations.curriculum_v3.full_backup import snapshot
    bad=snapshot({k:v for k,v in bundle.items() if k not in ('snapshot_digest','authentication_tag')},None)
    monkeypatch.setattr(teacher_api,'bundled',lambda:bad)
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers=HEADERS).status_code==409
    assert s.initialization_counts()['can_initialize'] and s.export()['entries']==[]


def test_prints_are_readable_escaped_and_bound_to_private_owner(client):
    c,s=client;post(c,'/api/v4/initialize',{'acknowledged':True})
    plan,job,body=setup(c)
    plan=post(c,'/api/v3/plans/edit',{'plan_id':plan['plan_id'],'expected_version':1,'goal_draft':'合成教师修改目标 & 仍待审核'})
    params={'plan_id':plan['plan_id'],'expected_version':2}
    html=c.get('/api/v4/print-plan',params=params)
    assert html.status_code==200 and html.headers['content-type'].startswith('text/html')
    assert '教学目标' in html.text and 'K011 v2' in html.text and '&amp;' in html.text
    assert '"teacher_edits"' not in html.text and 'JSON.stringify' not in html.text
    assert '当前教案' not in html.text or '待审核' in html.text
    stale=c.get('/api/v4/print-plan',params={**params,'expected_version':1})
    assert stale.status_code==409 and stale.headers['content-type'].startswith('text/html')
    assert '没有生成PDF' in stale.text
    body['expected_plan_version']=2
    value=post(c,'/api/v3/loops/link',body)
    response=c.get('/api/v4/print-loop',params={'loop_id':value['loop_id']})
    assert response.status_code==200 and '反馈草稿' in response.text and '合成关键点' in response.text
    other=TestClient(c.app,base_url=ORIGIN,client=('127.0.0.1',4001));other.get('/')
    assert other.get('/api/v4/print-plan',params=params).status_code==409
    assert other.get('/api/v4/print-loop',params={'loop_id':value['loop_id']}).status_code==404
    s.close()
    unavailable=c.get('/api/v4/print-plan',params=params)
    assert unavailable.status_code==503 and unavailable.headers['content-type'].startswith('text/html')


def test_catalogue_and_seed_routes_keep_csrf_and_strict_status(client):
    c,s=client
    data=c.get('/api/v4/catalogue').json()
    assert [r['lesson_id'] for r in data['drafts']]==[f'L0{i}' for i in range(1,9)]
    assert c.post('/api/v4/initialize',json={'acknowledged':True}).status_code==403
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers={**HEADERS,'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers={**HEADERS,'X-Forwarded-For':'127.0.0.1'}).status_code==403
    post(c,'/api/v4/initialize',{'acknowledged':True})
    entry=s.export()['entries'][0]
    assert c.post('/api/v3/knowledge',json={**entry,'version':2,'specialist_review_status':'approved'},headers=HEADERS).status_code==422


def test_new_routes_remain_unavailable_in_classroom():
    from test_classroom_tunnel import CODE, ORIGIN as site, HEADERS as headers, http_origin, login
    from integrations.prelesson.classroom import DemoState,create_classroom_app
    state=DemoState(CODE);state.pin(site)
    with TestClient(http_origin(create_classroom_app(state)),base_url=site,headers={'X-Forwarded-Proto':'https'},client=('127.0.0.1',54321)) as c:
        login(c)
        for path in ('/advanced','/teacher.js','/api/v4/catalogue','/api/v4/knowledge-status','/api/v4/print-plan'):
            assert c.get(path).status_code==404
        assert c.post('/api/v4/initialize',json={'acknowledged':True},headers=headers).status_code==404


def test_two_initializers_cannot_duplicate_or_overwrite(client):
    from concurrent.futures import ThreadPoolExecutor
    c,s=client
    second=SQLiteRegistry(s.directory)
    with TestClient(create_console_app(knowledge_store=second),base_url=ORIGIN,client=('127.0.0.1',4001)) as other:
        other.get('/')
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda browser:browser.post('/api/v4/initialize',json={'acknowledged':True},headers=HEADERS),(c,other)))
        assert sorted(r.status_code for r in responses)==[200,409]
        assert second.initialization_counts()['versions']==27
        assert len(second.evidence_reports())==50
    assert s.initialization_counts()['decisions']==0


def test_modified_bundled_bytes_are_refused_before_initialization(client,tmp_path,monkeypatch):
    import shutil
    c,s=client
    root=tmp_path/'modified-bundle'
    files=['docs/course-mvp/course-inventory.json','docs/p32-input/p32-knowledge-import.json',
           'docs/p32-input/p32-evidence-reports.json','docs/p34/knowledge-revisions.json','docs/p34/source-evidence-reports.json']
    for file in files:
        target=root/file;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(teacher_api.ROOT/file,target)
    modified=root/files[-1];modified.write_bytes(modified.read_bytes()+b'\n')
    monkeypatch.setattr(teacher_api,'ROOT',root)
    assert c.post('/api/v4/initialize',json={'acknowledged':True},headers=HEADERS).status_code==409
    assert s.initialization_counts()['can_initialize']


def test_mac_launcher_browser_hook_is_local_and_browser_failure_keeps_server(tmp_path):
    import os,socket,subprocess,sys,time,urllib.request
    repo=Path(__file__).resolve().parents[1]
    (tmp_path/'sitecustomize.py').write_text('import webbrowser\nfrom pathlib import Path\ndef opened(url):\n Path(__file__).with_name("opened.txt").write_text(url)\n raise webbrowser.Error("SYNTHETIC browser unavailable")\nwebbrowser.open=opened\n')
    env={k:v for k,v in os.environ.items() if not (k.startswith(('COACHLOOP_','TEACHING_','PG')) or 'DATABASE' in k)}
    env.update(PYTHONPATH=os.pathsep.join((str(tmp_path),str(repo/'src'))),PYTHONDONTWRITEBYTECODE='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-B',str(repo/'scripts/run_prelesson_console.py'),'--port',str(port),'--kb-dir',str(tmp_path/'kb'),'--open-browser'],cwd=repo,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for _ in range(150):
            if (tmp_path/'opened.txt').exists():break
            assert process.poll() is None
            time.sleep(.1)
        assert (tmp_path/'opened.txt').read_text()==f'http://127.0.0.1:{port}'
        with opener.open(f'http://127.0.0.1:{port}/health',timeout=5) as response:assert response.status==200
    finally:
        process.terminate();process.wait(timeout=15)
