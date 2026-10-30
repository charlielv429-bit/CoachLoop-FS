"""Mock contract tests are separate from the opt-in REAL video acceptance test.

No synthetic keypoints are counted as MediaPipe/real-video evidence.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from integrations.local_video.service import VideoStore, VideoError, COOKIE, BASE, feedback
from integrations.local_video.api import create_router
from integrations.prelesson.console import create_console_app
from tools.video_analysis.event_review import build_review_records

ORIGIN='http://127.0.0.1:8767'
HEADERS={'Origin':ORIGIN,'X-CoachLoop-Console':'1'}
ACK={'side':'left','authorized_use':True,'privacy_acknowledged':True,'single_subject_side_view':True}


@pytest.fixture
def store(tmp_path,monkeypatch):
    store=VideoStore()
    monkeypatch.setattr(store,'capabilities',lambda:dict(available=True,missing=[]))
    yield store
    store.close()


@pytest.fixture
def client(store):
    with TestClient(create_console_app(video_store=store),base_url=ORIGIN,client=('127.0.0.1',4000)) as client:
        client.get('/')
        yield client


def create(client,**updates):
    response=client.post(BASE+'/jobs',json={**ACK,**updates},headers=HEADERS)
    assert response.status_code==200
    return response.json()['job_id']


def mock_result(key):
    # Pure manufactured V4 event, explicitly mock; NOT a real video fixture.
    event=dict(feature='knee_angle_deg',frame_start=1,frame_end=3,start_time_ms=100,end_time_ms=300,
               duration_ms=200,n_frames=3,deviation_max=11.2,swing=2.1)
    review=build_review_records({'events':[event],'source':{'is_mock':True,'mode':'mock','video_path':'mock://unit/'+key}},'mock://unit/result')
    return dict(is_mock=True,source={'mode':'mock','is_mock':True},quality={'source_frames':5,'detected_frames':5,'valid_frame_ratio':1},
        metadata={'duration_seconds':0.5},review=review.model_dump(mode='json'),keypoints=[],frames=[],
        review_verification='local_unverified',authenticated_coach=False,technical_error_assessment='not_assessed')


def ready(client,store):
    key=create(client)
    with store.lock:
        job=store.jobs[key];job.state='ready';job.result=mock_result(key)
        (job.path/'preview.mp4').write_bytes(b'unit-preview-not-video')
    return key


def test_video_get_requires_console_and_per_browser_cookie(store):
    with TestClient(create_console_app(video_store=store),base_url=ORIGIN,client=('127.0.0.1',4000)) as client:
        assert client.get(BASE+'/capabilities').status_code==401
        client.get('/')
        assert client.get(BASE+'/capabilities').status_code==200
        token=client.cookies.get(COOKIE)
        assert token and token not in client.get('/').text
        assert 'HttpOnly' in client.get('/').headers['set-cookie']
        assert "media-src 'self' blob:" in client.get('/').headers['content-security-policy']
        client.cookies.delete(COOKIE)
        assert client.get(BASE+'/capabilities').status_code==401


@pytest.mark.parametrize('update',[{'authorized_use':False},{'authorized_use':1},{'privacy_acknowledged':False},
    {'single_subject_side_view':False},{'side':'front'},{'reviewed_by':'coach'},{'authenticated_coach':True},
    {'video_path':'/etc/passwd'},{'is_mock':False}])
def test_initialization_rejects_fake_identity_or_missing_consent(client,update):
    assert client.post(BASE+'/jobs',json={**ACK,**update},headers=HEADERS).status_code==422


def test_cross_session_ids_cannot_read_review_delete_media_or_feedback(client,store):
    key=ready(client,store)
    # Same process cookie is deliberately shared; ONLY independent video cookie isolates jobs.
    app=create_console_app(video_store=store)
    with TestClient(app,base_url=ORIGIN,client=('127.0.0.1',4001)) as other:
        other.get('/')
        assert other.cookies.get(COOKIE)!=client.cookies.get(COOKIE)
        for path in ('status','result','media','feedback'):
            assert other.get(BASE+'/'+path,params={'job_id':key}).status_code==404
        assert other.post(BASE+'/delete',json={'job_id':key},headers=HEADERS).status_code==404
        event=store.jobs[key].result['review']['records'][0]['event_id']
        body={'job_id':key,'event_id':event,'status':'confirmed','note':'','expected_sequence':0,'request_id':uuid4().hex}
        assert other.post(BASE+'/review',json=body,headers=HEADERS).status_code==404


def test_upload_limits_magic_extension_and_retry_cleanup(client,store,monkeypatch):
    for body,fmt,status in [(b'not mp4','mp4',422),(b'1234ftyp'+b'x'*(25*1024*1024),'mp4',413),(b'1234ftyp0000','exe',422)]:
        key=create(client)
        response=client.post(BASE+'/upload',params={'job_id':key,'format':fmt},content=body,headers={**HEADERS,'Content-Type':'video/mp4'})
        assert response.status_code==status
        client.post(BASE+'/delete',json={'job_id':key},headers=HEADERS)
    called=[]
    monkeypatch.setattr(store,'submit',lambda token,key:called.append(key))
    key=create(client)
    assert client.post(BASE+'/upload',params={'job_id':key,'format':'mov'},content=b'1234ftyp0000safe-fixture',headers={**HEADERS,'Content-Type':'video/quicktime'}).status_code==200
    assert called==[key] and (store.jobs[key].path/'upload.bin').exists()
    assert client.post(BASE+'/upload',params={'job_id':key,'format':'mov'},content=b'1234ftyp0000',headers={**HEADERS,'Content-Type':'video/quicktime'}).status_code==409


@pytest.mark.parametrize('path',['/jobs','/upload','/review','/delete'])
def test_all_mutating_paths_preserve_csrf_and_proxy_guards(client,path):
    kwargs={'json':ACK} if path!='/upload' else {'content':b'1234ftyp0000'}
    assert client.post(BASE+path,**kwargs).status_code==403
    assert client.post(BASE+path,headers={**HEADERS,'Origin':'https://evil.example'},**kwargs).status_code==403
    assert client.post(BASE+path,headers={**HEADERS,'X-Forwarded-For':'127.0.0.1'},**kwargs).status_code==403


def test_unprotected_router_fails_closed():
    app=FastAPI()
    for router in create_router():app.include_router(router)
    assert TestClient(app).get(BASE+'/capabilities').status_code==401


@pytest.mark.parametrize('status',['pending','confirmed','normal_movement','tracking_error','uncertain'])
def test_append_only_review_idempotency_sequences_and_safe_feedback(client,store,status):
    key=ready(client,store);record=store.jobs[key].result['review']['records'][0]
    original=copy.deepcopy(record['original_event'])
    body=dict(job_id=key,event_id=record['event_id'],status=status,note='<img src=x onerror=alert(1)>',expected_sequence=0,request_id=uuid4().hex)
    response=client.post(BASE+'/review',json=body,headers=HEADERS)
    assert response.status_code==200
    action=response.json()['records'][0]
    assert action['reviewed_by'].startswith('local-operator-') and action['reviewed_at']
    assert action['original_event']==original and len(action['review_history'])==1
    assert client.post(BASE+'/review',json=body,headers=HEADERS).status_code==200
    assert len(store.jobs[key].result['review']['records'][0]['review_history'])==1
    assert client.post(BASE+'/review',json={**body,'status':'uncertain' if status!='uncertain' else 'pending'},headers=HEADERS).status_code==409
    assert client.post(BASE+'/review',json={**body,'request_id':uuid4().hex},headers=HEADERS).status_code==409
    assert client.post(BASE+'/review',json={**body,'request_id':uuid4().hex,'expected_sequence':1},headers=HEADERS).status_code==200
    report=client.get(BASE+'/feedback',params={'job_id':key}).json()
    assert report['is_mock'] is True # synthetic fixture is NEVER relabelled as real
    assert report['authenticated_coach'] is False and report['requires_teacher_review'] is True
    assert report['trusted_observations']==[] and report['technical_error_assessment']=='not_assessed'
    assert len(report['reported_observations'])==(1 if status in ('confirmed','normal_movement') else 0)
    assert report['review_status']=='draft' and report['knowledge_status']=='unverified'


@pytest.mark.parametrize('mutation',[{'reviewed_by':'forged coach'},{'reviewed_at':'2000-01-01'},
    {'authenticated_coach':True},{'status':'technical_error'},{'event_id':'../../secret'},{'expected_sequence':True},{'note':'bad\nline'}])
def test_review_cannot_forge_identity_history_or_claim(client,store,mutation):
    key=ready(client,store);record=store.jobs[key].result['review']['records'][0]
    body=dict(job_id=key,event_id=record['event_id'],status='confirmed',note='',expected_sequence=0,request_id=uuid4().hex)
    assert client.post(BASE+'/review',json={**body,**mutation},headers=HEADERS).status_code==422


def test_job_session_limits_expiry_and_private_files_are_cleaned(store):
    now=[0.0];store.clock=lambda:now[0]
    token=store.session();key=store.create(token,'left');path=store.jobs[key].path
    with pytest.raises(VideoError):store.create(token,'left')
    now[0]=121;store.prune();assert not path.exists() and key not in store.jobs
    key=store.create(token,'right');store.jobs[key].state='ready';path=store.jobs[key].path
    now[0]=1322;store.prune();assert not path.exists()
    now[0]=1801
    with pytest.raises(VideoError):store.authorized(token)
    for _ in range(16):store.session()
    with pytest.raises(VideoError):store.session()
    root=store.root;store.close();assert not root.exists()


def test_capabilities_no_private_paths_without_runtime(tmp_path):
    with_store=VideoStore(python=tmp_path/'absent',model=tmp_path/'absent-model')
    try:
        result=with_store.capabilities()
        assert not result['available'] and 'pose_model_missing' in result['missing']
        assert str(tmp_path) not in json.dumps(result)
    finally:with_store.close()


def test_classroom_never_exposes_real_video_routes():
    from integrations.prelesson.classroom import DemoState,create_classroom_app
    code='synthetic-test-classroom-code-only'
    state=DemoState(code);state.pin('https://synthetic-video-block.trycloudflare.com')
    app=create_classroom_app(state)
    async def http_proxy(scope,receive,send):
        if scope['type']=='http':scope={**scope,'scheme':'http'}
        await app(scope,receive,send)
    with TestClient(http_proxy,base_url=state.origin,client=('127.0.0.1',4),headers={'X-Forwarded-Proto':'https'}) as client:
        headers={'Origin':state.origin,'X-CoachLoop-Console':'1'}
        assert client.post('/classroom/login',json={'code':code,'mock_acknowledged':True},headers=headers).status_code==200
        for path in ('/jobs','/upload','/media','/result','/review','/feedback','/capabilities'):
            assert client.get(BASE+path).status_code==404
            assert client.post(BASE+path,json=ACK,headers=headers).status_code==404
        assert client.get('/video-console.js').status_code==404
    state.close()


@pytest.mark.parametrize('video_format',['mp4','mov'])
def test_real_authorized_video_through_upload_worker_review_feedback_and_delete(video_format,tmp_path):
    video=os.environ.get('COACHLOOP_TEST_VIDEO')
    if not video:pytest.skip('Explicit licensed real-video fixture required; synthetic data is not real inference acceptance')
    path=Path(video)
    # The fixture is supplied independently; never download user video in a test.
    assert path.is_file()
    if video_format=='mov':
        import subprocess
        converted=tmp_path/'licensed-fixture.mov'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:v:0','-c:v','copy','-an','-y',str(converted)],check=True,timeout=20)
        path=converted
    store=VideoStore()
    root=store.root
    with TestClient(create_console_app(video_store=store),base_url=ORIGIN,client=('127.0.0.1',9)) as client:
        client.get('/')
        assert client.get(BASE+'/capabilities').json()['available']
        key=create(client)
        with path.open('rb') as file:
            response=client.post(BASE+'/upload',params={'job_id':key,'format':video_format},content=file.read(),headers={**HEADERS,'Content-Type':'video/quicktime' if video_format=='mov' else 'video/mp4'})
        assert response.status_code==200
        for _ in range(500):
            state=client.get(BASE+'/status',params={'job_id':key}).json()
            if state['state'] in ('ready','failed'):break
            time.sleep(.1)
        assert state['state']=='ready',state
        data=client.get(BASE+'/result',params={'job_id':key}).json()
        assert data['is_mock'] is False and data['source']['mode']=='real'
        assert data['quality']['detected_frames']>0 and len(data['keypoints'])==len(data['frames'])>0
        assert len(data['keypoints'][0]['landmarks'])==33
        assert all(r['review_status']=='pending' for r in data['review']['records'])
        assert not (store.jobs[key].path/'upload.bin').exists()
        assert str(root) not in json.dumps(data) and str(path) not in json.dumps(data)
        preview=client.get(BASE+'/media',params={'job_id':key},headers={'Range':'bytes=0-63'})
        assert preview.status_code==206 and len(preview.content)==64
        if data['review']['records']:
            record=data['review']['records'][0]
            body=dict(job_id=key,event_id=record['event_id'],status='confirmed',note='自动化验收操作，非专业教练结论',expected_sequence=0,request_id=uuid4().hex)
            assert client.post(BASE+'/review',json=body,headers=HEADERS).status_code==200
            assert client.post(BASE+'/review',json=body,headers=HEADERS).status_code==200
        report=client.get(BASE+'/feedback',params={'job_id':key}).json()
        assert report['is_mock'] is False and report['data_origin']=='real_video'
        assert report['trusted_observations']==[] and report['authenticated_coach'] is False
        assert report['technical_error_assessment']=='not_assessed' and report['requires_teacher_review'] is True
        job_path=store.jobs[key].path
        assert client.post(BASE+'/delete',json={'job_id':key},headers=HEADERS).status_code==200
        assert not job_path.exists() and client.get(BASE+'/result',params={'job_id':key}).status_code==404
    assert not root.exists()


@pytest.mark.parametrize('change',[
    {'duration':'61'},{'duration':'NaN'},{'duration':'0'},{'fps':'0/0'},{'fps':'120/1'},
    {'width':4096},{'height':0},{'codec':'av1'},{'streams':2},{'format':'hls'},
])
def test_probe_rejects_limits_and_external_formats_without_inference(tmp_path,monkeypatch,change):
    from integrations.local_video import worker
    from types import SimpleNamespace
    file=tmp_path/'input.bin';file.write_bytes(b'1234ftyp0000')
    video={'codec_type':'video','codec_name':change.get('codec','h264'),'width':change.get('width',640),
           'height':change.get('height',480),'avg_frame_rate':change.get('fps','30/1')}
    probe={'streams':[video]*change.get('streams',1),'format':{'format_name':change.get('format','mov,mp4,m4a,3gp'),'duration':change.get('duration','1')}}
    commands=[]
    def run(command,**kwargs):
        commands.append(command);return SimpleNamespace(stdout=json.dumps(probe).encode())
    monkeypatch.setattr(worker.subprocess,'run',run)
    with pytest.raises(worker.Rejected):worker.metadata(file)
    assert commands[0][commands[0].index('-protocol_whitelist')+1]=='file,pipe'
    assert commands[0][commands[0].index('-enable_drefs')+1]=='0'


def test_cancellation_kills_only_owned_process_group_and_removes_private_files(store):
    import subprocess,sys
    token=store.session();key=store.create(token,'left');job=store.jobs[key];path=job.path
    process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
    job.process=process;job.state='running'
    try:
        store.delete(token,key)
        assert process.poll() is not None and not path.exists()
        assert key not in store.jobs
    finally:store._kill(process)


def test_unknown_ids_and_traversal_do_not_reveal_local_paths(client):
    for path in ('status','media','result','feedback'):
        response=client.get(BASE+'/'+path,params={'job_id':'../../etc/passwd'})
        assert response.status_code==422
        assert '/etc/passwd' not in response.text
        assert client.get(BASE+'/'+path,params={'job_id':uuid4().hex}).status_code==404


def test_refresh_can_recover_current_job_without_reuploading(client,store):
    assert client.get(BASE+'/current').json() is None
    key=ready(client,store)
    client.get('/') # same browser refresh keeps its private video session
    current=client.get(BASE+'/current').json()
    assert current['job_id']==key and current['state']=='ready'
    assert client.get(BASE+'/result',params={'job_id':key}).status_code==200
    assert client.post(BASE+'/delete',json={'job_id':key},headers=HEADERS).status_code==200
    assert client.get(BASE+'/current').json() is None


@pytest.mark.parametrize('header,expected,length',[('bytes=0-3',206,4),('bytes=-4',206,4),('bytes=99999-',416,0),('bytes=4-1',416,0),('bytes=-',416,0),('bytes=0-1,4-5',416,0)])
def test_preview_ranges_and_invalid_ranges_are_bounded(client,store,header,expected,length):
    key=ready(client,store)
    response=client.get(BASE+'/media',params={'job_id':key},headers={'Range':header})
    assert response.status_code==expected and len(response.content)==length
    assert response.headers['cross-origin-resource-policy']=='same-origin'


def test_invalid_raw_upload_parameters_are_not_echoed(client):
    response=client.post(BASE+'/upload',params={'job_id':'/private/sensitive-path','format':'mp4'},content=b'1234ftyp0000',headers={**HEADERS,'Content-Type':'video/mp4'})
    assert response.status_code==422 and 'sensitive-path' not in response.text
