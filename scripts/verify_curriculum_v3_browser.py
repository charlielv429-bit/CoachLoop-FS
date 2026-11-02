"""Optional real-browser acceptance runner (Chromium + existing websockets).
Runs loopback only, with synthetic inputs; outputs reviewable local evidence.
Never invokes Coze, models, video, production credentials or a database.
Linux test containers may require --no-sandbox; do not expose this browser.
"""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import shutil
import subprocess
import tempfile
import time
import urllib.request
from websockets.sync.client import connect

root=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix='coachloop-ui-browser-'))
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env={k:v for k,v in os.environ.items() if not (k.startswith('PG') or 'DATABASE' in k or k.startswith(('COACHLOOP_','TEACHING_')))}
env.update(PYTHONDONTWRITEBYTECODE='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
server=subprocess.Popen([sys.executable,str(root/'scripts/run_prelesson_console.py'),'--port',str(port),'--kb-dir',str(work/'knowledge')],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
browser=None
try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(base+'/health',timeout=1) as response:
                if response.status==200:break
        except Exception:time.sleep(.1)
    profile=work/'profile';profile.mkdir()
    browser=subprocess.Popen([shutil.which('chromium') or shutil.which('google-chrome') or '/usr/lib/chromium/chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--disable-background-networking','--disable-extensions','--no-first-run','--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=0','--remote-allow-origins=http://localhost','--user-data-dir='+str(profile),base],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (profile/'DevToolsActivePort').exists():break
        time.sleep(.1)
    debugport=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
    target=None
    for _ in range(100):
        with opener.open(f'http://127.0.0.1:{debugport}/json/list',timeout=5) as response:
            target=next((t for t in json.load(response) if t['type']=='page'),None)
        if target:break
        time.sleep(.1)
    if target is None:raise RuntimeError('Chromium page target unavailable')
    with connect(target['webSocketDebuggerUrl'],origin='http://localhost',open_timeout=5) as ws:
        sequence=0
        def command(method,params):
            global sequence
            sequence+=1
            ws.send(json.dumps({'id':sequence,'method':method,'params':params}))
            while True:
                response=json.loads(ws.recv(timeout=10))
                if response.get('id')==sequence:return response
        def evaluate(expression):
            response=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            return response.get('result',{}).get('result',{}).get('value')
        command('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
        for _ in range(100):
            ready=evaluate("Boolean(document.querySelector('#lesson-form'))")
            if ready:break
            failure=evaluate("location.protocol==='chrome-error:'?document.body.innerText.slice(0,200):''")
            if failure:raise RuntimeError('Browser organization policy blocked page: '+failure)
            time.sleep(.1)
        assert ready,'Interactive form not loaded'
        for _ in range(100):
            if evaluate("document.querySelector('#v3-lesson').options.length===8"):break
            time.sleep(.1)
        assert evaluate("document.querySelector('#v3-lesson').options.length===8")
        evaluate("document.querySelector('#curriculum-entry').open=true;true")
        assert evaluate("document.querySelector('#v3-detail').textContent.includes('冰上基础技能综合入门')")
        evaluate("document.querySelector('#v3-lesson').value='L08';document.querySelector('#v3-lesson').dispatchEvent(new Event('change'));true")
        assert evaluate("document.querySelector('#v3-detail').textContent.includes('综合评价')")
        evaluate("""const f=document.querySelector('#v3-form');f.elements.knowledge_id.value='SYNTHETIC_BROWSER_ONLY';f.elements.title.value='模拟浏览器条目（非正式知识）';f.elements.content.value='仅测试界面，不作为专项知识';f.elements.lesson_ids.value='L08';f.requestSubmit();true""")
        for _ in range(100):
            if evaluate("document.querySelector('#v3-message').textContent.includes('已保存')"):break
            time.sleep(.1)
        assert evaluate("document.querySelector('#v3-list').textContent.includes('模拟浏览器条目')")
        assert evaluate("document.querySelector('#v3-list').textContent.includes('待补充') && document.querySelector('#v3-list').textContent.includes('待审核')")
        evaluate("document.querySelector('#v3-list button').click();true")
        assert evaluate("document.querySelector('#v3-form').elements.version.value")=='2'
        evaluate("document.querySelector('#v3-form').elements.content.value='模拟修订第二版';document.querySelector('#v3-form').requestSubmit();true")
        for _ in range(100):
            if evaluate("document.querySelector('#v3-message').textContent.includes('已保存版本 2')"):break
            time.sleep(.1)
        assert evaluate("document.querySelector('#v3-message').textContent.includes('已保存版本 2')")
        evaluate("document.querySelectorAll('#v3-list button')[1].click();true")
        for _ in range(100):
            if evaluate("document.querySelector('#v3-list').textContent.includes('仅测试界面')"):break
            time.sleep(.1)
        assert evaluate("document.querySelector('#v3-list').textContent.includes('仅测试界面') && document.querySelector('#v3-list').textContent.includes('模拟修订第二版')")
        downloads=work/'downloads';downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
        evaluate("document.querySelector('#v3-export').click();true")
        for _ in range(100):
            files=list(downloads.glob('*.kb-backup.json'))
            if files:break
            time.sleep(.1)
        assert files,'Knowledge backup download missing'
        backup=json.loads(files[0].read_text())
        assert [entry['version'] for entry in backup['entries']]==[1,2]
        evaluate("document.querySelector('#v3-review').click();true")
        for _ in range(100):
            reviews=list(downloads.glob('*.kb-review.json'))
            if reviews:break
            time.sleep(.1)
        assert reviews,'Offline review download missing'
        packet=json.loads(reviews[0].read_text())
        assert packet['archive']==backup and packet['status']=='pending_review'
        for stage in ('video','feedback','prelesson'):
            evaluate("document.querySelector('[data-stage="+stage+"]').click();true")
            assert evaluate("!document.querySelector('#"+stage+"-pane').hidden")
        print('V3 Chromium acceptance: 8 lessons, selection, create/edit/history, pending labels, backup/review actual downloads, original 3 tabs PASS')
finally:
    if browser is not None:
        browser.terminate()
        browser.wait(timeout=10)
    server.terminate()
    server.wait(timeout=10)
    shutil.rmtree(work,ignore_errors=True)
