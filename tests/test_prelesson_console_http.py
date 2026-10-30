"""Real loopback uvicorn test, with outbound and DB initialization probes."""
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

from integrations.prelesson.schemas import DraftResponse

ROOT = Path(__file__).resolve().parents[1]


def test_real_interactive_console_has_no_database_or_outbound_dependency(tmp_path):
    marker = tmp_path / 'forbidden.txt'
    (tmp_path / 'sitecustomize.py').write_text('''
import sys
from pathlib import Path
def forbidden(*args, **kwargs):
    with Path(__file__).with_name('forbidden.txt').open('a') as output: output.write('forbidden\\n')
    raise RuntimeError('Database or outbound dependency forbidden')
def audit(event,args):
    if event=='socket.connect':forbidden()
sys.addaudithook(audit)
import sqlalchemy,psycopg,psycopg2
sqlalchemy.create_engine=psycopg.connect=psycopg2.connect=forbidden
import storage.database.db as db
db.get_db_url=db.get_engine=forbidden
import storage.memory.memory_saver as memory
memory.get_memory_saver=forbidden
Path(__file__).with_name('ready.txt').write_text('ready')
''')
    env = {k:v for k,v in os.environ.items() if not (k.startswith('PG') or 'DATABASE' in k or k.startswith(('TEACHING_', 'COACHLOOP_')))}
    env.update(PYTHONPATH=os.pathsep.join([str(tmp_path),str(ROOT/'src')]), PYTHONDONTWRITEBYTECODE='1',
        LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/run_prelesson_console.py'),'--port',str(port)],
        cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path,payload=None):
        req=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json','Origin':base,'X-CoachLoop-Console':'1'})
        try:
            with opener.open(req,timeout=5) as response:
                return response.status,response.read(),response.headers
        except HTTPError as error:
            return error.code,error.read(),error.headers
    try:
        for _ in range(160):
            assert process.poll() is None,'Local console exited; raw logs deliberately omitted'
            try:
                if request('/health')[0]==200:break
            except (URLError,TimeoutError,ConnectionError):pass
            time.sleep(.1)
        else:raise AssertionError('Local console not ready')
        payload=json.loads((ROOT/'docs/prelesson-workflow-v01.example-request.json').read_text())
        assert request('/api/v1/lesson-plans/draft',payload)[0]==401
        status,html,headers=request('/')
        assert status==200 and 'HttpOnly' in headers['set-cookie'] and b'/console.js' in html
        for path in ('/console.js','/console.css'):
            assert request(path)[0]==200
        plans=[]
        for count in (1,20):
            status,body,_=request('/api/v1/lesson-plans/draft',{**payload,'student_count':count})
            assert status==200
            plan=DraftResponse.model_validate_json(body)
            assert f'{count}人' in plan.lesson_plan.teacher_input.audience
            assert plan.lesson_plan.review_status=='draft' and plan.requires_teacher_review
            plans.append(body)
        assert plans[0]!=plans[1]
        assert request('/api/v1/lesson-plans/draft',{**payload,'total_minutes':44})[0]==422
        for path in ('/run','/async_run','/stream_run','/openapi.json'):
            assert request(path,{})[0]==404
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    assert (tmp_path/'ready.txt').read_text()=='ready'
    assert not marker.exists(),'Database initialization or outbound connection attempted'
