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
server=subprocess.Popen([sys.executable,str(root/'scripts/run_prelesson_console.py'),'--port',str(port)],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
    with opener.open(f'http://127.0.0.1:{debugport}/json/list',timeout=5) as response:
        target=next(t for t in json.load(response) if t['type']=='page')
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
        def wait_result():
            for _ in range(100):
                if evaluate("!document.querySelector('#result').hidden"):return
                time.sleep(.05)
            raise AssertionError('Draft did not render: '+str(evaluate("document.querySelector('#message').textContent")))
        for _ in range(100):
            if evaluate("document.querySelectorAll('[name=theme_id] option').length===6"):break
            time.sleep(.05)
        assert evaluate("document.querySelectorAll('[name=theme_id] option').length===6")
        evaluate("""const set=(n,v)=>document.querySelector('[name='+n+']').value=v;
            set('class_label','MOCK-BROWSER-V11');set('student_count','10');set('coach_count','2');
            set('venue_conditions','合成冰场');set('equipment_conditions','合成装备30套');
            set('usable_area_m2','200');set('declared_practice_capacity','10');set('equipment_sets','30');
            document.querySelector('[name=safe_waiting_area]').checked=true;
            document.querySelector('[name=mastered_skills][value=safety_equipment]').checked=true;
            document.querySelector('#lesson-form').requestSubmit();true""")
        wait_result()
        assert evaluate("document.querySelector('#audience').textContent.includes('10人')")
        assert evaluate("document.querySelector('#elements').textContent.includes('短段双足滑行')")
        assert evaluate("document.querySelector('#elements').textContent.includes('教练2组5人')")
        first=evaluate("document.querySelector('#elements').textContent")
        stale=evaluate("document.querySelector('[name=student_count]').value='30';document.querySelector('[name=coach_count]').value='1';document.querySelector('[name=student_count]').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#result').hidden")
        assert stale is True
        evaluate("document.querySelector('#lesson-form').requestSubmit();true");wait_result()
        second=evaluate("document.querySelector('#elements').textContent")
        assert first!=second and '轮3' in second
        # Native level filter and Chinese/English search must select real topics.
        evaluate("document.querySelector('[name=skill_level]').value='中级';document.querySelector('[name=skill_level]').dispatchEvent(new Event('change',{bubbles:true}));true")
        assert evaluate("document.querySelectorAll('[name=theme_id] option').length") ==24
        evaluate("document.querySelector('#theme-search').value='spin';document.querySelector('#theme-search').dispatchEvent(new Event('input',{bubbles:true}));true")
        assert evaluate("document.querySelector('[name=theme_id]').value")=='two_foot_spin'
        evaluate("document.querySelector('#theme-search').value='';document.querySelector('#theme-search').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('[name=theme_id]').value='posture';document.querySelector('[name=theme_id]').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#lesson-form').requestSubmit();true")
        wait_result()
        assert evaluate("document.querySelector('#elements').textContent.includes('移动姿态观察')")
        # Real instructor modification propagates to the flow and download.
        evaluate("document.querySelector('[name=teacher_goal_edit]').value='先观察再讨论';document.querySelectorAll('[name=teacher_exercise_edits]')[0].value='教师提出的陆地观察任务';document.querySelector('[name=teacher_notes]').value='MOCK教师修改备注';document.querySelector('#lesson-form').requestSubmit();true")
        wait_result()
        assert evaluate("document.querySelector('#elements').textContent.includes('教师修改候选练习（未审核）：教师提出的陆地观察任务')")
        assert evaluate("document.querySelector('#elements').textContent.includes('先观察再讨论')")
        # An XSS label remains text, with no HTML image node.
        evaluate("document.querySelector('[name=class_label]').value='<img src=x onerror=alert(1)>';document.querySelector('#lesson-form').requestSubmit();true")
        wait_result()
        assert evaluate("document.querySelector('#audience').textContent.includes('<img') && document.querySelector('#result img')===null")
        evaluate("document.querySelector('[name=class_label]').value='MOCK-BROWSER-V11';document.querySelector('#lesson-form').requestSubmit();true");wait_result()
        downloads=work/'downloads';downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
        evaluate("document.querySelector('#download').click();true")
        for _ in range(50):
            exported=list(downloads.glob('*.json'))
            if exported:break
            time.sleep(.1)
        downloaded=json.loads(exported[0].read_text())
        assert downloaded['requires_teacher_review'] is True and downloaded['lesson_plan']['review_status']=='draft'
        assert downloaded['knowledge_status']=='unverified' and downloaded['lesson_plan']['teaching_flow']['total_minutes']==45
        assert downloaded['adaptation']['teacher_notes']=='MOCK教师修改备注'
        assert downloaded['adaptation']['core_exercises'][0]['catalogue_task']=='陆地姿态对照'
        assert not any(term in json.dumps(downloaded) for term in ['Authorization','Bearer ','coachloop_local_console','postgresql://'])
        # Screenshot captures actual generated output rather than a fixed HTML demo.
        evaluate("document.querySelector('#result').scrollIntoView();true")
        screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        destination=root/'docs/adaptive-prelesson-v11-evidence';destination.mkdir(exist_ok=True)
        (destination/'console.png').write_bytes(base64.b64decode(screenshot['result']['data']))
        (destination/'download.example.json').write_text(json.dumps(downloaded,ensure_ascii=False,indent=2)+'\n')
        # Zero-coach or missing-prerequisite requests must show a withheld plan.
        evaluate("document.querySelector('[name=coach_count]').value='0';document.querySelector('#lesson-form').requestSubmit();true");wait_result()
        assert evaluate("document.querySelector('#message').textContent.includes('暂缓冰上方案')")
        assert evaluate("document.querySelector('#elements').textContent.includes('暂缓所有冰上实施')")
        evaluate("document.querySelector('[name=coach_count]').value='1';document.querySelector('[name=mastered_skills][value=safety_equipment]').checked=false;document.querySelector('#lesson-form').requestSubmit();true");wait_result()
        assert evaluate("document.querySelector('#message').textContent.includes('暂缓冰上方案')")
        command('Network.deleteCookies',{'name':'coachloop_local_console','url':base})
        evaluate("document.querySelector('#lesson-form').requestSubmit();true")
        for _ in range(50):
            if evaluate("document.querySelector('#message').textContent.includes('本地会话已失效')"):break
            time.sleep(.1)
        assert evaluate("document.querySelector('#message').textContent.includes('本地会话已失效') && document.querySelector('#result').hidden")
        report=dict(kind='real_local_chromium_interaction',coze_online=False,database_used=False,paid_model_calls=0,
            catalogue_count=24,level_filter=True,english_search=True,dynamic_10_vs_30_students=True,
            dynamic_topic_content=True,teacher_goal_and_exercise_edits=True,original_candidate_provenance_preserved=True,
            withheld_zero_coach=True,withheld_missing_prerequisite=True,
            stale_output_hidden=True,xss_rendered_as_text=True,downloaded_draft_protected=True,
            expired_session_hides_old_plan=True,teacher_review_required=True)
        (destination/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))
finally:
    for process in (browser,server):
        if process:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
