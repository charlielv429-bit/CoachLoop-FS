"""Real Chromium A-F acceptance. Empty temporary SQLite and deliberately absent video runtime.

Only SYNTHETIC classroom conditions/keypoints/teacher text. No real video inference.
With --textbook-check, textbook summaries refer to the actual supplied page evidence.
"""
import argparse
import base64
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
import urllib.parse
from websockets.sync.client import connect

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,required=True,help='New directory for synthetic screenshots and actual printed PDF')
parser.add_argument('--textbook-check',action='store_true',help='Verify exact pending textbook facts, all eight lessons and printed citations')
args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
work=Path(tempfile.mkdtemp(prefix='coachloop-v4-'))
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env={k:v for k,v in os.environ.items() if not (k.startswith(('COACHLOOP_','TEACHING_','PG')) or 'DATABASE' in k)}
env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'src'),LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
code="from pathlib import Path; from integrations.prelesson.console import create_console_app; from integrations.curriculum_v3.persistence import SQLiteRegistry; from integrations.local_video.service import VideoStore; import uvicorn; app=create_console_app(PORT,knowledge_store=SQLiteRegistry(Path(KB)),video_store=VideoStore(python=Path(MISSING),model=Path(MODEL))); uvicorn.run(app,host='127.0.0.1',port=PORT,proxy_headers=False,log_level='error',access_log=False)"
code=code.replace('PORT',str(port)).replace('KB',repr(str(work/'kb'))).replace('MISSING',repr(str(work/'missing-python'))).replace('MODEL',repr(str(work/'missing-model')))
server=subprocess.Popen([sys.executable,'-B','-c',code],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
browser=None;opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
 for _ in range(150):
  if server.poll() is not None:raise RuntimeError(server.stderr.read().decode()[-1500:])
  try:
   if opener.open(base+'/health',timeout=1).status==200:break
  except Exception:time.sleep(.1)
 profile=work/'profile';profile.mkdir()
 browser=subprocess.Popen([shutil.which('chromium') or '/usr/lib/chromium/chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-background-networking','--disable-extensions','--no-first-run','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--remote-allow-origins=http://localhost','--user-data-dir='+str(profile),base],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 for _ in range(100):
  if (profile/'DevToolsActivePort').exists():break
  time.sleep(.1)
 debug=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
 def targets():
  with opener.open(f'http://127.0.0.1:{debug}/json/list') as f:return json.load(f)
 target=next(t for t in targets() if t['type']=='page')
 with connect(target['webSocketDebuggerUrl'],origin='http://localhost') as ws:
  seq=0
  def command(method,params):
   global seq
   seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params}))
   while True:
    r=json.loads(ws.recv(timeout=20))
    if r.get('id')==seq:
     if 'error' in r:raise AssertionError(r['error'])
     return r
  def evaluate(expr):
   r=command('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True,'userGesture':True})
   if r.get('result',{}).get('exceptionDetails'):raise AssertionError(r['result']['exceptionDetails'])
   return r.get('result',{}).get('result',{}).get('value')
  def wait(expr):
   for _ in range(180):
    if evaluate(expr):return
    time.sleep(.1)
   raise AssertionError('Timed out: '+expr+' / '+str(evaluate("document.querySelector('#notice')?.textContent")))
  def shot(name,selector=None):
   command('Page.bringToFront',{})
   if selector:evaluate('document.querySelector('+json.dumps(selector)+').scrollIntoView();true')
   r=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
   (args.output_dir/name).write_bytes(base64.b64decode(r['result']['data']))
  command('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1100,'deviceScaleFactor':1,'mobile':False})
  wait("document.querySelectorAll('.feature').length===4 && document.querySelectorAll('.lesson-card').length===8 && !document.querySelector('#first-run').hidden")
  shot('01-home-empty.SYNTHETIC.png')
  evaluate("document.querySelector('#home-initialize').click();document.querySelector('#initialize-submit').click();true")
  wait("document.querySelector('#initialize-message').textContent.includes('请先')")
  assert evaluate("(async()=>{const r=await fetch('/api/v4/knowledge-status');const s=await r.json();return s.versions;})()") == 0
  evaluate("document.querySelector('#initialize-ack').checked=true;document.querySelector('#initialize-submit').click();true")
  wait("!document.querySelector('#initialize-dialog').open && document.querySelector('#notice').textContent.includes('23条')")
  status=evaluate("(async()=> await (await fetch('/api/v4/knowledge-status')).json())()")
  assert (status['knowledge_ids'],status['versions'],status['reports'],status['decisions'])==(23,27,50,0)
  evaluate("document.querySelector('[data-open=prelesson]').click();true")
  wait("document.querySelector('#plan-document').textContent.includes('K011')")
  assert evaluate("document.querySelectorAll('pre').length") == 0
  assert evaluate("document.querySelector('#plan-document').textContent.includes('待审核') && document.querySelector('#plan-document').textContent.includes('9分钟')")
  shot('02-L05-readable.SYNTHETIC.png')
  if args.textbook_check:
   text=evaluate("document.querySelector('#plan-document').innerText")
   for term in ('原PDF91／印刷77','图29','原PDF93／印刷79','原PDF39／印刷29','侧走','单次压步','课程自拟','逐条专项'):
    assert term in text,term
   assert '缺少正式专项依据' not in text
   shot('08-L05-textbook-facts.png','#plan-document')
   evaluate("[...document.querySelectorAll('#plan-document h3')].find(h=>h.textContent.includes('原PDF39')).scrollIntoView();true")
   shot('09-L05-Li-page39.png')
   for lesson in ('L01','L02','L03','L04','L06','L07','L08'):
    evaluate("document.querySelector('[data-lesson="+lesson+"]').click();true")
    wait("document.querySelector('.lesson-card.active')?.dataset.lesson==='"+lesson+"' && document.querySelector('#plan-document').textContent.includes('分项证据与现场缺口')")
   evaluate("document.querySelector('[data-lesson=L05]').click();true")
   wait("document.querySelector('.lesson-card.active')?.dataset.lesson==='L05'")
  evaluate("document.querySelector('#plan-document section button').click();true")
  assert evaluate("document.activeElement.name")=='goal_draft'
  evaluate("document.querySelector('#teacher-edits').elements.goal_draft.value='SYNTHETIC：教师V4操作验收修改，仍待审核';document.querySelector('#teacher-edits').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#plan-print').click();true")
  wait("document.querySelector('#notice').textContent.includes('请先保存')")
  evaluate("document.querySelector('#teacher-edits').requestSubmit();true")
  wait("document.querySelector('#notice').textContent.includes('保存为版本2')")
  evaluate("document.querySelector('#plan-print').click();true")
  print_target=None
  for _ in range(100):
   print_target=next((t for t in targets() if '/api/v4/print-plan?' in t.get('url','')),None)
   if print_target:break
   time.sleep(.1)
  assert print_target,'Actual HTML print window missing'
  if args.textbook_check:
   plan_id=urllib.parse.parse_qs(urllib.parse.urlparse(print_target['url']).query)['plan_id'][0]
   exported=evaluate("(async()=>await (await fetch('/api/v3/plans/export?plan_id="+plan_id+"')).json())()")
   assert exported['version']==2 and exported['formal_teaching_evidence']==[]
   (args.output_dir/'L05-plan.SYNTHETIC.json').write_text(json.dumps(exported,ensure_ascii=False,indent=2)+'\n')
  with connect(print_target['webSocketDebuggerUrl'],origin='http://localhost') as pw:
   def pc(method,params,n):
    pw.send(json.dumps({'id':n,'method':method,'params':params}))
    while True:
     x=json.loads(pw.recv(timeout=20))
     if x.get('id')==n:return x
   for n in range(1,50):
    x=pc('Runtime.evaluate',{'expression':'document.body.innerText','returnByValue':True},n)
    text=x.get('result',{}).get('result',{}).get('value','')
    if 'SYNTHETIC：教师V4' in text:break
    time.sleep(.1)
   assert 'SYNTHETIC：教师V4' in text and 'K011 v2' in text and '待审核' in text
   if args.textbook_check:
    assert all(term in text for term in ('原PDF91／印刷77','原PDF39／印刷29','侧走','待审核'))
   pdf=base64.b64decode(pc('Page.printToPDF',{'printBackground':True},100)['result']['data'])
   assert pdf.startswith(b'%PDF-')
   (args.output_dir/'L05-print.SYNTHETIC.pdf').write_bytes(pdf)
  command('Target.closeTarget',{'targetId':print_target['id']})
  command('Page.bringToFront',{})
  evaluate("document.querySelector('[data-stage=knowledge]').click();true")
  wait("document.querySelectorAll('#knowledge-list .source').length===23")
  assert evaluate("document.querySelector('#knowledge-initialize').disabled")
  shot('03-knowledge-pending.SYNTHETIC.png')
  evaluate("document.querySelector('[data-stage=video]').click();true")
  wait("document.querySelector('#teacher-video-status').textContent.includes('模型文件缺失')")
  assert evaluate("document.querySelector('#video-start').disabled")
  shot('04-video-missing.SYNTHETIC.png')
  evaluate("document.querySelector('#teacher-demo').click();true")
  wait("document.querySelector('#video-message').textContent.includes('合成关键点演示已生成')")
  wait("document.querySelectorAll('#teacher-timeline button').length===1")
  evaluate("document.querySelector('#video-events select').value='confirmed';document.querySelector('#video-events input').value='合成V4观察，不是技术错误';document.querySelector('#video-events article button:last-child').click();true")
  wait("document.querySelector('#video-events article p').textContent.includes('报告可观察变化') || document.querySelector('#video-events article p').textContent.includes('确认可观察变化')")
  shot('05-events.SYNTHETIC.png')
  evaluate("document.querySelector('[data-stage=feedback]').click();true")
  wait("document.querySelector('#feedback-context').textContent.includes('合成演示已就绪')")
  evaluate("document.querySelector('#reflection-example').click();true")
  wait("document.querySelector('#reflection-form').elements.observation.value.includes('合成演示')")
  evaluate("document.querySelector('#reflection-form').requestSubmit();true")
  wait("document.querySelector('#notice').textContent.includes('反馈草稿已保存')")
  assert evaluate("document.querySelector('#reflection-document').textContent.includes('反馈草稿')")
  evaluate("document.querySelector('#reflection-ack').checked=true;document.querySelector('#reflection-confirm').click();true")
  wait("document.querySelector('#reflection-document').textContent.includes('本地教师自报确认')")
  shot('06-feedback.SYNTHETIC.png')
  evaluate("document.querySelector('[data-stage=video]').click();document.querySelector('#video-events select').value='uncertain';document.querySelector('#video-events article button:last-child').click();true")
  wait("document.querySelector('#video-events article p').textContent.includes('当前：证据不足')")
  evaluate("document.querySelector('[data-stage=feedback]').click();document.querySelector('#reflection-refresh').click();true")
  wait("document.querySelector('#reflection-document').textContent.includes('反馈草稿')")
  evaluate("document.querySelector('[data-stage=prelesson]').click();document.querySelector('#preset').value='shortage';document.querySelector('#reload-plan').click();true")
  wait("document.querySelector('#plan-document').textContent.includes('专项教练')")
  assert evaluate("document.querySelector('#plan-document').textContent.includes('暂缓')")
  shot('07-resource-hold.SYNTHETIC.png')
  if args.textbook_check:
   status_code=evaluate("(async()=>{const packet=await (await fetch('/api/v3/export')).json();const k=packet.entries.find(e=>e.knowledge_id==='K012'&&e.version===2);k.version=3;k.content='SYNTHETIC 浏览器测试修订，支持关系待重新核对';return (await fetch('/api/v3/knowledge',{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(k)})).status;})()")
   assert status_code==200
   assert evaluate("(async()=> (await fetch("+json.dumps(print_target['url'])+")).status)()")==409
   evaluate("document.querySelector('[data-lesson=L04]').click();true")
   wait("document.querySelector('.lesson-card.active')?.dataset.lesson==='L04'")
   evaluate("document.querySelector('[data-lesson=L05]').click();true")
   wait("document.querySelector('#plan-document').textContent.includes('历史草稿引用的教材版本或声明已变化')")
   evaluate("[...document.querySelectorAll('#plan-document p')].find(p=>p.textContent.includes('历史草稿引用')).scrollIntoView();true")
   shot('10-stale-reference-blocked.SYNTHETIC.png')
  command('Page.navigate',{'url':base+'/advanced'})
  wait("Boolean(document.querySelector('#lesson-form')) && document.querySelectorAll('[name=theme_id] option').length>0")
  wait("document.querySelector('#lp-lesson').options.length===8")
  (args.output_dir/'acceptance.json').write_text(json.dumps({'textbook_facts_checked':args.textbook_check,'stale_textbook_print_blocked':args.textbook_check,'A_empty_init':True,'B_L05_loaded':True,'C_edit_and_real_PDF':True,'D_synthetic_loop':True,'E_missing_model_review_resource_holds':True,'F_advanced_entry':True,'knowledge_counts':status,'is_mock':True,'actual_teacher_review':False,'actual_Mac_test':False,'real_video_inference':False},ensure_ascii=False,indent=2)+'\n')
 print('V4 Chromium A-F PASS: empty seed, 8 lessons, readable L05, edits, actual HTML/PDF print, pending sources, missing model, synthetic events/feedback, invalidated confirmation, resource holds and advanced entry')
finally:
 if browser is not None:browser.terminate();browser.wait(timeout=10)
 server.terminate();server.wait(timeout=10)
 shutil.rmtree(work,ignore_errors=True)
