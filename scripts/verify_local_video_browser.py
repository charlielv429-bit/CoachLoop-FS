"""Real local browser + real video inference acceptance, not synthetic keypoints.

Requires an explicitly supplied licensed video fixture, the optional video
runtime/model, Chromium and existing websockets test tooling. Never downloads
video/model at runtime. Private exports stay in /tmp; committed evidence is
aggregate-only with video/event details redacted in screenshots.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from websockets.sync.client import connect

ROOT=Path(__file__).resolve().parents[1]
VIDEO=Path(os.environ['COACHLOOP_TEST_VIDEO']).resolve()
work=Path(tempfile.mkdtemp(prefix='coachloop-video-browser-private-'))
prior=set(Path('/tmp').glob('coachloop-local-video-*'))
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env={k:v for k,v in os.environ.items() if not (k.startswith(('PG','COACHLOOP_','TEACHING_')) or 'DATABASE' in k)}
env['PYTHONDONTWRITEBYTECODE']='1'
server=subprocess.Popen([sys.executable,str(ROOT/'scripts/run_prelesson_console.py'),'--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
browser=None
report=None
try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(base+'/health',timeout=1) as response:
                if response.status==200:break
        except Exception:time.sleep(.1)
    profile=work/'profile';profile.mkdir()
    browser=subprocess.Popen([shutil.which('chromium') or '/usr/lib/chromium/chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--disable-extensions','--no-first-run','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--remote-allow-origins=http://localhost','--user-data-dir='+str(profile),base],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (profile/'DevToolsActivePort').exists():break
        time.sleep(.1)
    debugport=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
    with opener.open(f'http://127.0.0.1:{debugport}/json/list',timeout=5) as response:
        target=next(t for t in json.load(response) if t['type']=='page')
    with connect(target['webSocketDebuggerUrl'],origin='http://localhost',open_timeout=5) as ws:
        sequence=0
        def command(method,params):
            global sequence
            sequence+=1;ws.send(json.dumps({'id':sequence,'method':method,'params':params}))
            while True:
                response=json.loads(ws.recv(timeout=15))
                if response.get('id')==sequence:
                    if 'error' in response:raise AssertionError('Browser command failed')
                    return response
        def evaluate(expression):
            response=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in response.get('result',{}):raise AssertionError('Browser evaluation failed')
            return response.get('result',{}).get('result',{}).get('value')
        def wait(expression,seconds=15):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if evaluate(expression):return
                time.sleep(.1)
            raise AssertionError('Browser acceptance timed out: '+expression)
        command('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
        wait("Boolean(document.querySelector('#stage-nav')) && document.querySelector('#video-capabilities').textContent.includes('已就绪') && !document.querySelector('#video-start').disabled")
        evaluate("document.querySelector('[data-stage=video]').click();true")
        root=command('DOM.getDocument',{})['result']['root']['nodeId']
        node=command('DOM.querySelector',{'nodeId':root,'selector':'#video-file'})['result']['nodeId']
        command('DOM.setFileInputFiles',{'nodeId':node,'files':[str(VIDEO)]})
        wait("document.querySelector('#analysis-video').readyState>=1")
        evaluate("for(const id of ['video-rights','video-privacy','video-single'])document.getElementById(id).checked=true;document.querySelector('#video-form').requestSubmit();true")
        wait("document.querySelector('#video-message').textContent.includes('本机真实视频分析完成')",seconds=80)
        wait("document.querySelector('#analysis-video').readyState>=1")
        count=evaluate("document.querySelectorAll('.video-event').length")
        assert count>0
        evaluate("document.querySelector('.video-event button').click();true")
        wait("!document.querySelector('#analysis-video').seeking")
        assert evaluate("document.querySelector('#analysis-video').videoWidth>0")
        assert evaluate("document.querySelector('#pose-overlay').width>0 && document.querySelector('#frame-quality').textContent.includes('可见度')")
        # Actual UI action, explicitly automated and NOT a professional confirmation.
        evaluate("document.querySelector('.video-event select').value='confirmed';document.querySelector('.video-event input').value='自动化浏览器验收操作，非专业教练结论';document.querySelector('.video-event button:last-child').click();true")
        wait("document.querySelector('.video-event p').textContent.includes('审核序列 1')")
        downloads=work/'downloads';downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
        evaluate("document.querySelector('#video-export').click();true")
        deadline=time.monotonic()+10
        while not list(downloads.glob('*video*.json')) and time.monotonic()<deadline:time.sleep(.1)
        data=json.loads(next(downloads.glob('*video*.json')).read_text())
        assert data['is_mock'] is False and data['source']['mode']=='real'
        assert data['quality']['detected_frames']>0 and len(data['keypoints'])==len(data['frames'])
        assert data['review']['records'][0]['review_history'][0]['status']=='confirmed'
        assert data['authenticated_coach'] is False and data['review_verification']=='local_unverified'
        assert str(ROOT) not in json.dumps(data) and str(VIDEO) not in json.dumps(data)
        evaluate("document.querySelector('[data-stage=feedback]').click();document.querySelector('#feedback-refresh').click();true")
        wait("!document.querySelector('#feedback-content').hidden")
        evaluate("document.querySelector('#feedback-export').click();true")
        deadline=time.monotonic()+10
        while not list(downloads.glob('*postlesson*.json')) and time.monotonic()<deadline:time.sleep(.1)
        feedback=json.loads(next(downloads.glob('*postlesson*.json')).read_text())
        assert feedback['is_mock'] is False and feedback['technical_error_assessment']=='not_assessed'
        assert feedback['trusted_observations']==[] and feedback['authenticated_coach'] is False
        assert feedback['review_status']=='draft' and feedback['requires_teacher_review'] is True
        assert len(feedback['reported_observations'])==1 and not feedback['reported_observations'][0]['eligible_for_technical_conclusions']
        # Redact before capture, never commit video frames, landmarks, raw events,
        # private export files or personal appearance. This is UI evidence only.
        evaluate("document.querySelector('[data-stage=video]').click();document.querySelector('.video-stage').replaceChildren(document.createTextNode('隐私遮蔽：真实授权测试原片与骨架未随截图提交'));document.querySelector('#frame-quality').textContent='实时可见度与骨架已验证；逐帧数据未随截图提交。';for(const event of document.querySelectorAll('.video-event')){event.querySelector('h3').textContent='候选变化事件（具体时间与观测量已遮蔽）';event.querySelector('p').textContent='本地自动化审核动作已追加；身份未认证，不构成专业教练结论。';}document.querySelector('#video-pane').scrollIntoView();true")
        destination=ROOT/'docs/local-video-v20-evidence';destination.mkdir(exist_ok=True)
        screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['result']['data']
        (destination/'video-ui.redacted.png').write_bytes(base64.b64decode(screenshot))
        evaluate("document.querySelector('#video-delete').click();true")
        wait("document.querySelector('#video-message').textContent.includes('本机任务已清除')")
        assert evaluate("document.querySelectorAll('.video-event').length===0 && document.querySelector('#video-export').disabled")
        report=dict(kind='real_local_chromium_real_video_pipeline',source_is_mock=False,
            video_sha256=hashlib.sha256(VIDEO.read_bytes()).hexdigest(),source_frames=len(data['frames']),
            detected_frames=data['quality']['detected_frames'],candidate_event_count=count,
            actual_upload=True,actual_mediapipe_subprocess=True,preview_and_event_seek=True,
            keypoint_overlay=True,review_action='automated_local_unverified',authenticated_coach=False,
            structured_export=True,postlesson_draft=True,technical_error_assessment='not_assessed',
            teacher_review_required=True,delete_cleans_ui=True,screenshot='privacy_redacted_ui_only',
            raw_video_or_landmarks_or_event_records_committed=False,cloud_or_coze_or_paid_calls=False)
finally:
    for process in (browser,server):
        if process:
            process.terminate()
            try:process.wait(timeout=12)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
if report is not None:
    assert set(Path('/tmp').glob('coachloop-local-video-*'))<=prior,'Private temp directory leaked on shutdown'
    report['server_shutdown_cleanup']=True
    (ROOT/'docs/local-video-v20-evidence/browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
