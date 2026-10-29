"""Real uvicorn main startup + HTTP; disposable PostgreSQL fixture only."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.error import HTTPError,URLError
import pytest

from integrations.prelesson.schemas import DraftResponse

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('configured',[True,False],ids=['configured-bearer','missing-bearer-config'])
@pytest.mark.parametrize('public_profile',[False,True],ids=['legacy-surface','prelesson-only-surface'])
def test_real_uvicorn_main_routes_with_isolated_postgres(database,configured,public_profile):
    admin,_actors=database
    token=secrets.token_urlsafe(32)
    # Never use inherited production URLs or print URLs/credentials/process env.
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1',
         'PGDATABASE_URL':admin.url.set(drivername='postgresql').render_as_string(hide_password=False),
         'COACHLOOP_PRELESSON_TOKEN':token if configured else '',
         'COACHLOOP_PRELESSON_ONLY':'1' if public_profile else '0',
         'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-B','-m','uvicorn','main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],
        cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{port}'
    def request(path,payload=None,authorized=False,extra_headers=None):
        headers={'Content-Type':'application/json'}
        if authorized:headers['Authorization']='Bearer '+token
        if extra_headers:headers.update(extra_headers)
        req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        # Loopback test transport: no external proxy/service is contacted.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req,timeout=10) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)
    try:
        ready=False
        for _ in range(160):
            assert process.poll() is None,'Real main startup exited; credentials/logs deliberately not echoed'
            try:
                if request('/health')[0]==200:ready=True;break
            except (URLError,TimeoutError,ConnectionError):pass
            time.sleep(.1)
        assert ready,'Real uvicorn main did not become ready on isolated PostgreSQL'
        payload=json.loads((ROOT/'docs/prelesson-workflow-v01.example-request.json').read_text())
        outputs=[]
        for path in ('/api/v1/lesson-plans/draft','/prelesson/draft'):
            assert request(path,payload)[0]==(401 if configured else 503)
            status,data=request(path,payload,True)
            if not configured:
                assert status==503
                assert request(path,payload,extra_headers={'X-Coze-Authenticated':'true','X-Authenticated-User':'teacher'})[0]==503
                assert token not in json.dumps(data)
                continue
            assert status==200
            result=DraftResponse.model_validate(data)
            assert result.requires_teacher_review and result.lesson_plan.review_status=='draft'
            assert result.lesson_plan.load_accounting.total_minutes==45
            assert result.knowledge_status=='unverified'
            assert request(path,{**payload,'total_minutes':40},True)[0]==422
            outputs.append(data)
        if configured:assert outputs[0]==outputs[1]
        status,spec=request('/openapi.json')
        assert status==(404 if public_profile else 200)
        if not public_profile:assert '/prelesson/draft' in spec['paths']
        assert token not in json.dumps(spec)
        if public_profile:
            for path in ('/run','/async_run','/stream_run'):
                assert request(path)[0]==404
                assert request(path,{},True)[0]==404
            if configured:
                smoke=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/check_coze_deployment.py'),'--base-url',base],
                    env=env,cwd=ROOT,capture_output=True,text=True,timeout=30)
                assert smoke.returncode==0,'Local readiness smoke failed; raw output deliberately omitted'
                report=json.loads(smoke.stdout)
                assert report['passed'] and token not in smoke.stdout+smoke.stderr
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
