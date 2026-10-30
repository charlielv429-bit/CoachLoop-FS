"""Synthetic proxy simulation: these tests do NOT prove public Cloudflare access."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from agents.lesson_plan_agent.adaptive import AdaptiveResponse
from integrations.prelesson.classroom import (DemoState, create_classroom_app, COOKIE, ADAPTIVE,
    CATALOGUE, checked_origin)

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://synthetic-classroom-review.trycloudflare.com'
CODE = 'synthetic-classroom-code-for-tests-only'
HEADERS = {'X-Forwarded-Proto': 'https', 'Origin': ORIGIN, 'X-CoachLoop-Console': '1'}
BODY = dict(data_domain='mock',is_mock=True,class_label='MOCK-TEST',student_count=10,
    coach_count=2,teacher_count=1,skill_level='零基础',usable_area_m2=200,declared_practice_capacity=10,
    equipment_sets=30,safe_waiting_area=True,venue_conditions='MOCK合成冰场',equipment_conditions='MOCK装备',
    mastered_skills=['safety_equipment'])


def http_origin(app):
    """Model HTTPS browser -> cloudflared -> raw HTTP origin (proxy headers off)."""
    async def proxy(scope, receive, send):
        if scope['type']=='http':scope={**scope,'scheme':'http'}
        return await app(scope,receive,send)
    return proxy


@pytest.fixture
def state():
    state=DemoState(CODE);state.pin(ORIGIN)
    return state


@pytest.fixture
def client(state):
    with TestClient(http_origin(create_classroom_app(state)),base_url=ORIGIN,headers={'X-Forwarded-Proto':'https'},client=('127.0.0.1',54321)) as c:
        yield c


def login(client):
    response=client.post('/classroom/login',json={'code':CODE,'mock_acknowledged':True},headers=HEADERS)
    assert response.status_code==200
    return response


def test_anonymous_login_page_no_bootstrap_bypass_or_secret(client):
    response=client.get('/')
    assert response.status_code==200 and '课堂访问码' in response.text
    assert CODE not in response.text and 'set-cookie' not in response.headers
    assert client.get(CATALOGUE).status_code==401
    assert client.get('/console.js').status_code==401
    assert client.post(ADAPTIVE,json=BODY,headers=HEADERS).status_code==401
    assert client.get('/health').json()['mode']=='classroom_mock_demo'
    assert "connect-src 'self'" in response.headers['content-security-policy']
    assert response.headers['cache-control']=='no-store'


def test_per_browser_secure_cookie_real_agent_and_export(client,state):
    response=login(client)
    cookie=response.headers['set-cookie']
    assert COOKIE+'=' in cookie and all(x in cookie for x in ('HttpOnly','Secure','SameSite=strict','Path=/','Max-Age='))
    assert 'Domain=' not in cookie
    assert len(state.sessions)==1
    assert 'classroom_mock_demo' in client.get('/').text
    assert len(client.get(CATALOGUE).json()['themes'])==24
    plans=[]
    for count in (10,20):
        response=client.post(ADAPTIVE,json={**BODY,'student_count':count},headers=HEADERS)
        assert response.status_code==200
        result=response.json()
        assert result['is_mock'] is True and result['data_domain']=='mock' and result['human_review_performed'] is False
        draft=AdaptiveResponse.model_validate(result['draft'])
        assert draft.lesson_plan.review_status=='draft' and draft.requires_teacher_review
        assert draft.knowledge_status=='unverified' and draft.lesson_plan.teaching_flow.total_minutes==45
        assert not any(word in response.text for word in (CODE,client.cookies.get(COOKIE),'postgresql://'))
        plans.append(result['draft'])
    assert plans[0]['adaptation']['organization']['rotation_count']==1
    assert plans[1]['adaptation']['organization']['rotation_count']==2
    with TestClient(http_origin(create_classroom_app(state)),base_url=ORIGIN,headers={'X-Forwarded-Proto':'https'},client=('127.0.0.1',54322)) as other:
        assert other.get(CATALOGUE).status_code==401
        login(other)
        assert other.cookies.get(COOKIE)!=client.cookies.get(COOKIE)


@pytest.mark.parametrize('headers',[
    {'Host':'evil.example'}, {'Host':'127.0.0.1:8767'}, {'X-Forwarded-Proto':'http'},
    {'X-Forwarded-Proto':'https,http'}, {'Origin':'https://evil.example'}, {'Origin':'null'},
    {'Forwarded':'for=127.0.0.1;proto=https'}, {'X-Forwarded-Host':'evil.example'},
    {'Authorization':'Bearer forged'}, {'CF-Visitor':'{"scheme":"http"}'},
    {'CF-Visitor':'"https"'}, {'Sec-Fetch-Site':'cross-site'},
])
def test_proxy_origin_host_boundary_cannot_be_overridden(client,headers):
    assert client.get('/',headers=headers).status_code==403


def test_duplicate_headers_and_missing_forwarded_https_fail_closed(client):
    assert client.get('/',headers=[('Host',ORIGIN[8:]),('Host',ORIGIN[8:])]).status_code==403
    assert client.get('/',headers=[('X-Forwarded-Proto','https'),('X-Forwarded-Proto','https')]).status_code==403
    login(client)
    assert client.post(ADAPTIVE,json=BODY,headers=[('Origin',ORIGIN),('Origin',ORIGIN),('X-CoachLoop-Console','1')]).status_code==403
    with TestClient(client.app,base_url=ORIGIN,client=('127.0.0.1',5)) as bare:
        assert bare.get('/').status_code==403


def test_remote_peer_even_with_forged_trusted_ip_is_rejected(state):
    with TestClient(http_origin(create_classroom_app(state)),base_url=ORIGIN,client=('203.0.113.1',1)) as c:
        assert c.get('/',headers={**HEADERS,'X-Forwarded-For':'127.0.0.1','CF-Connecting-IP':'127.0.0.1'}).status_code==403


@pytest.mark.parametrize('headers', [{},{'Origin':ORIGIN},{**HEADERS,'Content-Type':'text/plain'},
    {**HEADERS,'X-CoachLoop-Console':'0'}])
def test_login_csrf_cannot_issue_session(client,state,headers):
    response=client.post('/classroom/login',json={'code':CODE,'mock_acknowledged':True},headers=headers)
    assert response.status_code==403
    assert not state.sessions and 'set-cookie' not in response.headers


@pytest.mark.parametrize('body',[
    {'code':'wrong','mock_acknowledged':True}, {'code':CODE,'mock_acknowledged':False},
    {'code':CODE,'mock_acknowledged':1}, {'code':CODE,'mock_acknowledged':True,'role':'teacher'},
])
def test_wrong_code_or_unacknowledged_mock_data_cannot_login(client,state,body):
    response=client.post('/classroom/login',json=body,headers=HEADERS)
    assert response.status_code in (401,422)
    assert not state.sessions and CODE not in response.text


@pytest.mark.parametrize('update',[
    {'data_domain':'pilot'},{'is_mock':False},{'is_mock':1},{'class_label':'真实班级'},
    {'review_status':'approved'},{'student_name':'synthetic-unexpected'}, {'student_count':True},
])
def test_real_domain_relabelling_and_approval_rejected(client,update):
    login(client)
    response=client.post(ADAPTIVE,json={**BODY,**update},headers=HEADERS)
    assert response.status_code==422 and 'draft' not in response.json()


def test_json_duplicate_keys_size_queries_methods_and_websocket(client):
    login(client)
    raw=json.dumps(BODY).replace('"is_mock": true','"is_mock": false,"is_mock": true')
    assert client.post(ADAPTIVE,content=raw,headers={**HEADERS,'Content-Type':'application/json'}).status_code==422
    assert client.post(ADAPTIVE,content=b'x'*32769,headers={**HEADERS,'Content-Type':'application/json'}).status_code==413
    assert client.get('/?code=synthetic').status_code==400
    for path in ('/run','/async_run','/stream_run','/api/v1/lesson-plans/draft','/prelesson/draft','/docs','/openapi.json','/api/v1/reviewed-training-results/import'):
        assert client.post(path,json={},headers=HEADERS).status_code==404
    assert client.get(ADAPTIVE).status_code==404
    assert client.options(ADAPTIVE).status_code==404
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/'):pytest.fail('WebSocket opened')
    assert error.value.code==1008


def test_login_bruteforce_global_budget_cannot_use_spoofed_client_ips(client):
    for i in range(10):
        assert client.post('/classroom/login',json={'code':'wrong','mock_acknowledged':True},
            headers={**HEADERS,'X-Forwarded-For':f'198.51.100.{i}'}).status_code==401
    response=client.post('/classroom/login',json={'code':CODE,'mock_acknowledged':True},headers=HEADERS)
    assert response.status_code==429 and response.headers['retry-after']=='60'


def test_generation_per_session_and_global_budget_is_not_ip_based(client):
    login(client)
    for i in range(6):
        assert client.post(ADAPTIVE,json=BODY,headers={**HEADERS,'X-Forwarded-For':f'198.51.100.{i}'}).status_code==200
    assert client.post(ADAPTIVE,json=BODY,headers=HEADERS).status_code==429
    login(client) # another login does not bypass the process-wide generation budget
    for i in range(24):
        if i and i%6==0:login(client)
        assert client.post(ADAPTIVE,json=BODY,headers=HEADERS).status_code==200
    login(client)
    assert client.post(ADAPTIVE,json=BODY,headers=HEADERS).status_code==429


def test_logout_expiry_and_shutdown_revoke_sessions(client,state):
    login(client); token=client.cookies.get(COOKIE)
    assert client.post('/classroom/logout',json={},headers=HEADERS).status_code==200
    assert not state.authorized(token)
    login(client)
    state.close()
    assert client.get('/').status_code==503 and not state.sessions


def test_lifetime_and_budget_reset_use_injected_monotonic_clock():
    now=[100.0];state=DemoState(CODE,duration=300,clock=lambda:now[0]);state.pin(ORIGIN)
    token=state.login(CODE)
    assert state.authorized(token)
    for _ in range(10):assert state.consume('login',10)
    assert not state.consume('login',10)
    now[0]+=61;assert state.consume('login',10)
    now[0]=401;assert not state.authorized(token)


@pytest.mark.parametrize('origin',['http://a.trycloudflare.com','https://trycloudflare.com','https://a.trycloudflare.com.evil.example',
    'https://user:secret@a.trycloudflare.com','https://a.trycloudflare.com/','https://a.trycloudflare.com:443','https://a.trycloudflare.com?code=x','https://*.trycloudflare.com'])
def test_bad_or_placeholder_origins_rejected(origin):
    with pytest.raises(ValueError):checked_origin(origin)


def test_unpinned_origin_and_repin_fail_closed():
    state=DemoState(CODE)
    with TestClient(http_origin(create_classroom_app(state)),base_url=ORIGIN,headers=HEADERS,client=('127.0.0.1',1)) as c:
        assert c.get('/').status_code==503
    state.pin(ORIGIN)
    with pytest.raises(ValueError):state.pin('https://another.trycloudflare.com')


@pytest.fixture
def launcher():
    spec=importlib.util.spec_from_file_location('classroom_launcher',ROOT/'scripts/run_classroom_tunnel.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_launcher_is_opt_in_and_shell_wrappers_quote_project_paths():
    response=subprocess.run([sys.executable,str(ROOT/'scripts/run_classroom_tunnel.py')],capture_output=True,text=True)
    assert response.returncode==2 and 'explicit' in response.stderr
    for script in ('start_classroom_tunnel.command','stop_classroom_tunnel.command','start_prelesson_console.command'):
        subprocess.run(['bash','-n',str(ROOT/'scripts'/script)],check=True)


def test_private_lock_stop_and_symlinks_do_not_kill_other_processes(launcher,tmp_path):
    directory=launcher.private_directory(tmp_path/'private')
    assert not launcher.request_stop(directory)
    with launcher.acquire_lock(directory):
        with pytest.raises(RuntimeError):launcher.acquire_lock(directory)
        assert launcher.request_stop(directory) and (directory/'STOP').exists()
    link=tmp_path/'symlink';link.symlink_to(directory,target_is_directory=True)
    with pytest.raises(RuntimeError):launcher.private_directory(link)


def test_cloudflared_flags_environment_and_url_parser(launcher,monkeypatch,tmp_path):
    args=launcher.tunnel_command('cloudflared',tmp_path,9876)
    assert 'http://127.0.0.1:9876' in args and '--no-autoupdate' in args
    assert args[args.index('--config')+1]==str(tmp_path/'empty-config.yml')
    assert args[args.index('--metrics')+1]=='127.0.0.1:0'
    monkeypatch.setenv('TUNNEL_TOKEN','synthetic-do-not-inherit')
    monkeypatch.setenv('COACHLOOP_PRELESSON_TOKEN','synthetic-do-not-inherit')
    assert 'TUNNEL_TOKEN' not in launcher.tunnel_environment()
    assert 'COACHLOOP_PRELESSON_TOKEN' not in launcher.tunnel_environment()
    assert launcher.quick_origin('| '+ORIGIN+' |')==ORIGIN
    assert launcher.quick_origin('https://a.trycloudflare.com.evil.example') is None
    assert launcher.quick_origin('https://user:secret@a.trycloudflare.com') is None


def test_qr_encodes_only_url_never_access_code(launcher,tmp_path,monkeypatch):
    # Exercise QR encoding without making the optional extra mandatory for default installs.
    import types
    qr=types.ModuleType('qrcode');image=types.ModuleType('qrcode.image');svg=types.ModuleType('qrcode.image.svg')
    svg.SvgPathImage=object();image.svg=svg;qr.image=image
    class Image:
        def save(self,destination):Path(destination).write_text('<svg/>')
    spy=Mock(return_value=Image());qr.make=spy
    monkeypatch.setitem(sys.modules,'qrcode',qr);monkeypatch.setitem(sys.modules,'qrcode.image',image);monkeypatch.setitem(sys.modules,'qrcode.image.svg',svg)
    assert launcher.make_qr(ORIGIN,tmp_path/'qr.svg')
    assert spy.call_args.args==(ORIGIN,)
    assert CODE not in (tmp_path/'qr.svg').read_text()


def test_supervisor_real_http_and_stop_with_simulated_connector(tmp_path):
    """Real supervisor/uvicorn/HTTP; connector is explicitly FAKE, no public claim."""
    import os,time,urllib.request,urllib.error
    tools=tmp_path/'tools';tools.mkdir()
    state_dir=tmp_path/'private';capture=tmp_path/'fake-connector.json'
    binary=tools/'cloudflared'
    binary.write_text('#!'+sys.executable+'\n'+'''import json,os,sys,time,signal
from pathlib import Path
args=sys.argv[1:]
Path(os.environ['FAKE_CONNECTOR_CAPTURE']).write_text(json.dumps({'url':args[args.index('--url')+1],'token_inherited':'TUNNEL_TOKEN' in os.environ}))
print('https://simulated-classroom-lifecycle.trycloudflare.com',flush=True)
signal.signal(signal.SIGTERM,lambda *a:sys.exit(0))
while True:time.sleep(.1)
''')
    binary.chmod(0o700)
    env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH'],'FAKE_CONNECTOR_CAPTURE':str(capture),'TUNNEL_TOKEN':'synthetic-never-inherit'}
    process=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_classroom_tunnel.py'),'--enable-classroom-tunnel','--state-dir',str(state_dir),'--minutes','5'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for _ in range(200):
            if (state_dir/'origin.json').exists():break
            assert process.poll() is None,'Supervisor exited before mock readiness'
            time.sleep(.05)
        meta=json.loads((state_dir/'origin.json').read_text())
        assert meta['public_verified'] is False
        record=json.loads(capture.read_text());assert record['token_inherited'] is False
        origin=record['url']
        request=urllib.request.Request(origin+'/health',headers={'Host':meta['origin'][8:],'X-Forwarded-Proto':'https'})
        with opener.open(request,timeout=5) as response:
            assert json.load(response)['mode']=='classroom_mock_demo'
        with pytest.raises(urllib.error.HTTPError) as error:opener.open(origin+'/health',timeout=5)
        assert error.value.code==403
        stop=subprocess.run([sys.executable,str(ROOT/'scripts/run_classroom_tunnel.py'),'--stop','--state-dir',str(state_dir)],capture_output=True,text=True,timeout=20)
        assert stop.returncode==0 and 'confirmed' in stop.stdout
        out,err=process.communicate(timeout=10)
        assert process.returncode==0 and 'sessions revoked' in out
        assert not (state_dir/'origin.json').exists()
        assert 'synthetic-never-inherit' not in out+err+stop.stdout+stop.stderr
        with pytest.raises(Exception):opener.open(request,timeout=1)
    finally:
        if process.poll() is None:
            process.send_signal(__import__('signal').SIGINT)
            try:process.communicate(timeout=12)
            except subprocess.TimeoutExpired:process.kill();process.communicate(timeout=5)


@pytest.mark.parametrize('data',[{'lesson_plan':{},'detail':'error'},'detail',{'detail':'error','draft':{}}, {'detail':[{'loc':[],'msg':'x','type':'x','draft':{}}]}])
def test_public_verifier_rejects_error_success_payload_confusion(data):
    spec=importlib.util.spec_from_file_location('classroom_verifier',ROOT/'scripts/check_classroom_https.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert not module.error_shape(data)


def test_session_storage_is_bounded_and_expired_clients_are_removed():
    now=[100.0];state=DemoState(CODE,duration=10800,clock=lambda:now[0]);state.pin(ORIGIN)
    for _ in range(64):assert state.login(CODE)
    assert state.login(CODE) is None and len(state.sessions)==64
    now[0]+=3601
    assert state.login(CODE) and len(state.sessions)==1


def test_expiry_while_reading_a_body_prevents_agent_execution(monkeypatch):
    import asyncio
    import integrations.prelesson.classroom as module
    now=[100.0];state=DemoState(CODE,duration=300,clock=lambda:now[0]);state.pin(ORIGIN)
    token=state.login(CODE)
    spy=Mock(side_effect=AssertionError('Expired body reached Agent'))
    monkeypatch.setattr(module,'generate_adaptive',spy)
    app=create_classroom_app(state)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
           'path':ADAPTIVE,'raw_path':ADAPTIVE.encode(),'query_string':b'',
           'root_path':'','client':('127.0.0.1',1),'server':('127.0.0.1',2),
           'headers':[(b'host',ORIGIN[8:].encode()),(b'x-forwarded-proto',b'https'),(b'origin',ORIGIN.encode()),
                      (b'x-coachloop-console',b'1'),(b'content-type',b'application/json'),(b'cookie',(COOKIE+'='+token).encode())]}
    sent=[]
    async def receive():
        now[0]=401
        return {'type':'http.request','body':json.dumps(BODY).encode(),'more_body':False}
    async def send(message):sent.append(message)
    asyncio.run(app(scope,receive,send))
    assert next(m['status'] for m in sent if m['type']=='http.response.start')==401
    spy.assert_not_called()


def test_shared_link_top_level_navigation_works_but_cross_site_fetch_does_not(client):
    headers={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
    response=client.get('/',headers=headers)
    assert response.status_code==200 and 'set-cookie' not in response.headers
    assert client.get('/',headers={**headers,'Sec-Fetch-Dest':'iframe'}).status_code==403
    assert client.get(CATALOGUE,headers=headers).status_code==403
    assert client.get('/',headers={**headers,'Origin':'https://evil.example'}).status_code==403


def test_internal_generation_error_does_not_expose_details(client,monkeypatch):
    import integrations.prelesson.classroom as module
    login(client)
    monkeypatch.setattr(module,'generate_adaptive',Mock(side_effect=RuntimeError('synthetic-private-error-detail')))
    response=client.post(ADAPTIVE,json=BODY,headers=HEADERS)
    assert response.status_code==503 and response.json()=={'detail':'Classroom generation unavailable'}
    assert response.headers['cache-control']=='no-store'
    assert 'synthetic-private-error-detail' not in response.text


def test_mock_wrapper_cannot_relabel_arbitrary_class_or_mutate_review_flags():
    from integrations.prelesson.classroom import ClassroomResult
    from agents.lesson_plan_agent.adaptive import generate_adaptive
    payload={k:v for k,v in BODY.items() if k not in ('data_domain','is_mock')}
    with pytest.raises(ValueError):ClassroomResult(draft=generate_adaptive({**payload,'class_label':'非模拟班级'}))
    wrapped=ClassroomResult(draft=generate_adaptive(payload))
    wrapped.human_review_performed=True
    with pytest.raises(ValueError):wrapped.model_dump_json()
