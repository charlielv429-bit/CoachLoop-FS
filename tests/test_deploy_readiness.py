"""Deployment preparation tests: synthetic data, no remote deployment or models."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from integrations.prelesson.api import create_router
from integrations.prelesson.exposure import PrelessonExposureGuard,prelesson_only_enabled

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('coze_readiness_check',ROOT/'scripts/check_coze_deployment.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
TOKEN='synthetic-deployment-token-at-least-32-characters'


def deployment_app(enabled=True,token=TOKEN):
    app=FastAPI()
    @app.get('/health')
    def health():return {'status':'ok'}
    def legacy():return {'legacy_executed':True}
    for path in ('/run','/async_run','/stream_run'):
        app.add_api_route(path,legacy,methods=['POST'])
    app.include_router(create_router(token,include_alias=True))
    app.add_middleware(PrelessonExposureGuard,enabled=enabled)
    return app


def requestor(client):
    def send(method,path,payload=None,token=None,extra=None):
        headers=dict(extra or {})
        if token:headers['Authorization']='Bearer '+token
        r=client.request(method,path,json=payload,headers=headers,follow_redirects=False)
        return r.status_code,r.json()
    return send


@pytest.mark.parametrize('path',['/run','/async_run','/stream_run','/node_run/mock','/task/mock','/graph_parameter','/docs','/openapi.json','/health/','/api/v1/lesson-plans/draft/'])
@pytest.mark.parametrize('method',['GET','POST'])
def test_public_profile_blocks_nonallowlisted_paths_before_handlers(path,method):
    with TestClient(deployment_app()) as c:
        r=c.request(method,path,json={},headers={'Authorization':'Bearer '+TOKEN})
        assert r.status_code==404
        assert r.headers['cache-control']=='no-store'
        assert 'legacy_executed' not in r.text and TOKEN not in r.text


def test_full_smoke_passes_on_restricted_synthetic_app():
    with TestClient(deployment_app()) as c:
        report=check.check_http('http://127.0.0.1',TOKEN,requestor(c))
        assert report['passed'],report
        assert len(report['checks'])==18
        assert report['coze_platform_status']=='待 Coze 实测'
        assert TOKEN not in json.dumps(report)


def test_smoke_detects_exposed_legacy_without_executing_it():
    with TestClient(deployment_app(enabled=False)) as c:
        report=check.check_http('http://127.0.0.1',TOKEN,requestor(c))
        assert not report['passed']
        assert all(not p['passed'] and p['status']==405 for p in report['checks'] if p['name'].startswith('legacy_blocked'))
        assert c.post('/run').json()=={'legacy_executed':True}


def test_smoke_detects_missing_auth_configuration():
    with TestClient(deployment_app(token='')) as c:
        report=check.check_http('http://127.0.0.1',TOKEN,requestor(c))
        assert not report['passed']
        assert any(p.get('status')==503 for p in report['checks'])


@pytest.mark.parametrize('attack',['approved','no_review','verified','time','load','citation','safety'])
def test_smoke_rejects_broken_handoff_contract(attack):
    data=json.loads((ROOT/'docs/prelesson-workflow-v01.example-response.json').read_text())
    assert check.valid_draft(data)
    if attack=='approved':data['lesson_plan']['review_status']='approved'
    if attack=='no_review':data['requires_teacher_review']=False
    if attack=='verified':data['knowledge_status']='verified'
    if attack=='time':data['lesson_plan']['teaching_flow']['phases'][0]['minutes']=1
    if attack=='load':data['lesson_plan']['load_accounting']['group_density']['denominator']=1
    if attack=='citation':data['lesson_plan']['evidence_log'][1]['citation']='伪造课标'
    if attack=='safety':data['lesson_plan']['safety_precautions']['safety_review_status']='approved'
    assert not check.valid_draft(data)


def test_preflight_redacts_values_and_refuses_missing_settings(monkeypatch,capsys):
    env={'COACHLOOP_PRELESSON_ONLY':'1','COACHLOOP_PRELESSON_TOKEN':TOKEN,
         'PGDATABASE_URL':'postgresql://MOCK:synthetic-password@127.0.0.1/mock'}
    report=check.preflight(env)
    assert report['passed']
    encoded=json.dumps(report)
    assert TOKEN not in encoded and 'synthetic-password' not in encoded
    assert not check.preflight({})['passed']
    for name,value in env.items():monkeypatch.setenv(name,value)
    assert check.main(['--preflight'])==0
    assert TOKEN not in capsys.readouterr().out


@pytest.mark.parametrize('origin',['http://example.invalid','http://127.0.0.1.evil.invalid','ftp://localhost',
    'https://user:secret@example.invalid','https://example.invalid/path','https://example.invalid?token=secret','https://example.invalid/#secret'])
def test_check_refuses_unsafe_or_credential_bearing_origins(origin):
    with pytest.raises(ValueError):check.validate_origin(origin)


def test_no_redirect_and_transport_errors_do_not_leak_credentials():
    assert check.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://example.invalid') is None
    def broken(*_args):raise RuntimeError('secret '+TOKEN)
    report=check.check_http('http://127.0.0.1',TOKEN,broken)
    assert not report['passed'] and TOKEN not in json.dumps(report)
    assert all(x['error']=='transport_or_response_failed' for x in report['checks'])


def test_cli_argument_errors_do_not_echo_accidentally_pasted_credentials(capsys):
    with pytest.raises(SystemExit) as error:check.main(['--token',TOKEN])
    assert error.value.code==2
    output=capsys.readouterr()
    assert TOKEN not in output.out+output.err


def test_profile_configuration_is_explicit_and_fails_closed(monkeypatch):
    monkeypatch.delenv('COACHLOOP_PRELESSON_ONLY',raising=False)
    assert not prelesson_only_enabled()
    monkeypatch.setenv('COACHLOOP_PRELESSON_ONLY','1')
    assert prelesson_only_enabled()
    monkeypatch.setenv('COACHLOOP_PRELESSON_ONLY','yes')
    with pytest.raises(RuntimeError):prelesson_only_enabled()


def test_launcher_and_existing_setup_syntax_valid():
    subprocess.run(['bash','-n',str(ROOT/'scripts/setup.sh'),str(ROOT/'scripts/http_run.sh'),str(ROOT/'scripts/coze_prelesson_run.sh')],check=True)


def test_launcher_refuses_missing_credential_before_main_start():
    env={**os.environ,'COZE_WORKSPACE_PATH':str(ROOT),'COACHLOOP_PRELESSON_ONLY':'1',
         'COACHLOOP_PRELESSON_TOKEN':'','PGDATABASE_URL':'postgresql://MOCK:synthetic@127.0.0.1:1/mock'}
    result=subprocess.run(['bash',str(ROOT/'scripts/coze_prelesson_run.sh')],env=env,cwd=ROOT,
                          capture_output=True,text=True,timeout=5)
    assert result.returncode==1
    assert json.loads(result.stdout)['mode']=='local_preflight'
    assert 'synthetic' not in result.stdout+result.stderr
