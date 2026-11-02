"""Optional real-browser acceptance runner (Chromium + existing websockets).
Runs loopback only, with synthetic inputs; outputs reviewable local evidence.
Uses a temporary SQLite copy of the provided candidate package plus explicitly SYNTHETIC probes. No real approvals, models or videos.
Linux test containers may require --no-sandbox; do not expose this browser.
"""
import argparse
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

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--p34',action='store_true',help='Also load pending original-page revisions into the isolated test KB')
args=parser.parse_args()

root=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix='coachloop-ui-browser-'))
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env={k:v for k,v in os.environ.items() if not (k.startswith('PG') or 'DATABASE' in k or k.startswith(('COACHLOOP_','TEACHING_')))}
env.update(PYTHONDONTWRITEBYTECODE='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
# Isolated data: real supplied candidates stay pending; synthetic probes stay labeled.
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.registry import Archive, Knowledge
from integrations.curriculum_v3.review import EvidenceBundle
registry=SQLiteRegistry(work/'knowledge')
registry.import_archive(Archive.model_validate(json.loads((root/'docs/p32-input/p32-knowledge-import.json').read_text())))
registry.save_reports(EvidenceBundle.model_validate(json.loads((root/'docs/p32-input/p32-evidence-reports.json').read_text())).reports)
if args.p34:
    registry.import_archive(Archive.model_validate(json.loads((root/'docs/p34/knowledge-revisions.json').read_text())))
    registry.save_reports(EvidenceBundle.model_validate(json.loads((root/'docs/p34/source-evidence-reports.json').read_text())).reports)
probe=Knowledge(knowledge_id='SYNTHETIC_P33_BROWSER',category='KB-S',title='模拟浏览器失效素材（非教材）',content='SYNTHETIC_QUOTE_TO_WITHDRAW',lesson_ids=['L05'],source_id='SYNTHETIC_SOURCE',source_title='模拟来源非教材',source_locator='模拟页码',content_kind='source_summary',version=1)
registry.save(probe);registry.close()
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
        assert evaluate("document.querySelector('#lp-result').textContent.includes('专项知识素材') && document.querySelector('#lp-result').textContent.includes('课程进阶建议') && document.querySelector('#lp-result').textContent.includes('评价观察建议')")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('K011') && document.querySelector('#lp-result').textContent.includes('K018') && document.querySelector('#lp-result').textContent.includes('K019') && document.querySelector('#lp-result').textContent.includes('B03')")
        if args.p34:
            assert evaluate("document.querySelector('#lp-result').textContent.includes('原PDF91') && document.querySelector('#lp-result').textContent.includes('原PDF39')")
            assert evaluate("!document.querySelector('#lp-result').textContent.includes('尚无原PDF')")
        else:
            assert evaluate("document.querySelector('#lp-result').textContent.includes('页码定位冲突')")
        names=['goal_draft','action_points','practice_steps','common_errors','safety_notes','differentiation_notes','evaluation_observations']
        for name in names:
            evaluate("document.querySelector('#lp-edit-form').elements["+json.dumps(name)+"].value="+json.dumps('模拟教师填写：'+name)+";document.querySelector('#lp-edit-form').elements["+json.dumps(name)+"].dispatchEvent(new Event('input',{bubbles:true}));true")
        evaluate("document.querySelector('#lp-export').click();true")
        wait_for("document.querySelector('#lp-message').textContent.includes('未保存修改')")
        evaluate("document.querySelector('#lp-edit-form').requestSubmit();true")
        wait_for("document.querySelector('#lp-message').textContent.includes('版本2')")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('模拟教师填写：action_points')")
        downloads=work/'downloads';downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(downloads)})
        evaluate("document.querySelector('#lp-export').click();true")
        for _ in range(100):
            files=list(downloads.glob('*.json'))
            if files:break
            time.sleep(.1)
        assert files,'Actual L05 export missing'
        exported=json.loads(files[0].read_text())
        assert exported['version']==2 and exported['technical_guidance']==exported['formal_teaching_evidence']==[]
        if args.p34:
            cards=[c for group in exported['l05_teaching_design']['material_groups'].values() for c in group if not c['knowledge_id'].startswith('SYNTHETIC')]
            assert {(c['knowledge_id'],c['version']) for c in cards}=={('K011',2),('K012',2),('K018',2),('K019',1)}
            assert all(c['source_verification_status']==c['specialist_review_status']=='pending' and not c['is_formal_guidance'] for c in cards)
            assert len([r for r in exported['evidence_reports'] if r['evidence_id'].startswith('P34_')])==3
        assert [p['minutes'] for p in exported['teaching_flow']['phases']]==[9,29,7]
        for name in names:
            assert exported['l05_teaching_design']['areas'][name]['text']=='模拟教师填写：'+name
            assert exported['l05_teaching_design']['areas'][name]['review_status']=='pending_review'
        registry=SQLiteRegistry(work/'knowledge')
        registry.save(Knowledge(**{**probe.model_dump(),'version':2,'content':'SYNTHETIC_NEW_VERSION'}));registry.close()
        evaluate("document.querySelector('#lp-refresh-evidence').click();true")
        wait_for("document.querySelector('#lp-message').textContent.includes('知识版本或课次已变化')")
        assert evaluate("!document.querySelector('#lp-result').textContent.includes('SYNTHETIC_QUOTE_TO_WITHDRAW')")
        evaluate("document.querySelector('#lp-history').click();true")
        wait_for("document.querySelector('#lp-history-result').textContent.includes('superseded_or_unlinked')")
        after_update=work/'after-update';after_update.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(after_update)})
        evaluate("document.querySelector('#lp-export').click();true")
        for _ in range(100):
            files=list(after_update.glob('*.json'))
            if files:break
            time.sleep(.1)
        assert files,'Post-update actual export missing'
        latest=json.loads(files[0].read_text())
        card=next(c for c in latest['l05_teaching_design']['material_groups']['specialist_knowledge'] if c['knowledge_id']==probe.knowledge_id)
        assert card['candidate_text']=='' and card['citation_status']=='superseded_or_unlinked'
        race_downloads=work/'race-downloads';race_downloads.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(race_downloads)})
        evaluate("window.p33OriginalFetch=window.fetch;window.fetch=async(...args)=>{const response=await window.p33OriginalFetch(...args);if(String(args[0]).includes('/plans/export'))await new Promise(resolve=>window.p33Release=resolve);return response;};document.querySelector('#lp-export').click();true")
        wait_for("typeof window.p33Release==='function'")
        evaluate("document.querySelector('#lp-form').elements.coach_count.value='0';document.querySelector('#lp-form').dispatchEvent(new Event('input',{bubbles:true}));window.p33Release();window.fetch=window.p33OriginalFetch;true")
        evaluate("new Promise(resolve=>setTimeout(()=>resolve(true),150))")
        assert evaluate("document.querySelector('#lp-output').hidden")
        assert not list(race_downloads.glob('*.json')),'Stale export should be cancelled'
        evaluate("document.querySelector('#lp-form').elements.coach_count.value='0';document.querySelector('#lp-form').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#lp-form').requestSubmit();true")
        wait_for("!document.querySelector('#lp-output').hidden")
        assert evaluate("document.querySelector('#lp-result').textContent.includes('无专项教练')")
        for stage in ('video','feedback','prelesson'):
            evaluate("document.querySelector('[data-stage="+stage+"]').click();true")
            assert evaluate("!document.querySelector('#"+stage+"-pane').hidden")
        assert evaluate("document.querySelectorAll('[name=theme_id] option').length")>0
        print(('P3.4' if args.p34 else 'P3.3')+' Chromium PASS: L05 real candidate groups/conflicts, seven teacher fields, saved versions, actual exports, stale-reference refresh, holds, legacy tabs')
finally:
    if browser is not None:
        browser.terminate()
        browser.wait(timeout=10)
    server.terminate()
    server.wait(timeout=10)
    shutil.rmtree(work,ignore_errors=True)
