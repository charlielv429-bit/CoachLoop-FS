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

from integrations.prelesson.schemas import DraftResponse

ROOT=Path(__file__).resolve().parents[2]


def test_real_uvicorn_main_routes_with_isolated_postgres(database):
    admin,_actors=database
    token=secrets.token_urlsafe(32)
    # Never use inherited production URLs or print URLs/credentials/process env.
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1',
         'PGDATABASE_URL':admin.url.set(drivername='postgresql').render_as_string(hide_password=False),
         'COACHLOOP_PRELESSON_TOKEN':token,'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-B','-m','uvicorn','main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],
        cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{port}'
    def request(path,payload=None,authorized=False):
        headers={'Content-Type':'application/json'}
        if authorized:headers['Authorization']='Bearer '+token
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
            assert request(path,payload)[0]==401
            status,data=request(path,payload,True)
            assert status==200
            result=DraftResponse.model_validate(data)
            assert result.requires_teacher_review and result.lesson_plan.review_status=='draft'
            assert result.lesson_plan.load_accounting.total_minutes==45
            assert result.knowledge_status=='unverified'
            assert request(path,{**payload,'total_minutes':40},True)[0]==422
            outputs.append(data)
        assert outputs[0]==outputs[1]
        status,spec=request('/openapi.json')
        assert status==200 and '/prelesson/draft' in spec['paths']
        assert token not in json.dumps(spec)
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
