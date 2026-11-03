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
        '--remote-debugging-port=0','--remote-allow-origins=http://localhost','--user-data-dir='+str(profile),base+'/advanced'],
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
        def wait_for(expression):
            for _ in range(100):
                if evaluate(expression):return
                time.sleep(.1)
            raise AssertionError(str(evaluate("document.querySelector('#lp-message').textContent")))
        wait_for("document.querySelector('#lp-lesson').options.length===8")
        evaluate("document.querySelector('#lesson-planning-mode').open=true;true")
        assert evaluate("document.querySelector('#lp-lesson').value")=='L05'
        evaluate("""const f=document.querySelector('#lp-form');f.elements.venue_conditions.value='模拟场地';f.elements.equipment_conditions.value='模拟装备';f.elements.safe_waiting_area.checked=true;f.elements.prerequisites_confirmed.checked=true;f.requestSubmit();true""")
        wait_for("!document.querySelector('#lp-output').hidden")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('左前交叉步完整动作练习')")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('待审核教案框架')")
        evaluate("""const e=document.querySelector('#lp-edit-form');e.elements.goal_draft.value='模拟教师目标修改';e.elements.organization_note.value='模拟分组说明';e.elements.resource_note.value='模拟装备备注';e.requestSubmit();true""")
        wait_for("document.querySelector('#lp-message').textContent.includes('版本2')")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('模拟教师目标修改')")
        evaluate("document.querySelector('#lp-history').click();true")
        wait_for("document.querySelector('#lp-history-result').textContent.includes('模拟装备备注')")
        downloads=work/'downloads';downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
        evaluate("document.querySelector('#lp-export').click();true")
        for _ in range(100):
            files=list(downloads.glob('*.json'))
            if files:break
            time.sleep(.1)
        assert files,'Actual download missing'
        exported=json.loads(files[0].read_text())
        assert exported['lesson']['lesson_id']=='L05' and exported['version']==2
        assert exported['technical_guidance']==exported['formal_teaching_evidence']==[]
        assert sum(p['minutes'] for p in exported['teaching_flow']['phases'])==45
        assert exported['teacher_edits'][-1]['values']['goal_draft']=='模拟教师目标修改'
        evaluate("document.querySelector('#lp-form').elements.coach_count.value='0';document.querySelector('#lp-form').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#lp-form').requestSubmit();true")
        wait_for("!document.querySelector('#lp-output').hidden")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('无专项教练')")
        for stage in ('video','feedback','prelesson'):
            evaluate("document.querySelector('[data-stage="+stage+"]').click();true")
            assert evaluate("!document.querySelector('#"+stage+"-pane').hidden")
        assert evaluate("document.querySelectorAll('[name=theme_id] option').length")>0
        print('V3 phase2 Chromium PASS: L05 generation, edits, history, actual JSON download, resource hold, legacy tabs')
finally:
    if browser is not None:
        browser.terminate()
        browser.wait(timeout=10)
    server.terminate()
    server.wait(timeout=10)
    shutil.rmtree(work,ignore_errors=True)
