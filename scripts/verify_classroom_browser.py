"""Real browser over a simulated loopback HTTPS proxy, NOT public Cloudflare.
Synthetic test only; optional Chromium/websockets/openssl test tooling required.
Self-signed local TLS exception and Linux browser --no-sandbox are fixture-only.
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
sys.path.insert(0,str(root/'src'))
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ssl
import threading
import uvicorn
from integrations.prelesson.classroom import DemoState,create_classroom_app,COOKIE
work=Path(tempfile.mkdtemp(prefix='coachloop-classroom-browser-'))
fake_origin='https://simulated-browser-classroom.trycloudflare.com'
code='synthetic-browser-classroom-code-only'
state=DemoState(code);state.pin(fake_origin)
listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
origin_port=listener.getsockname()[1]
server=uvicorn.Server(uvicorn.Config(create_classroom_app(state),proxy_headers=False,access_log=False,log_level='error'))
worker=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);worker.start()
for _ in range(100):
    if server.started:break
    time.sleep(.05)
# This certificate and its private key exist only in a private temporary test
# directory, never in repository artifacts. No public TLS verification disabled.
subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(work/'key.pem'),'-out',str(work/'cert.pem'),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
base=''
class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def forward(self):
        headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection')}
        if headers.get('Origin')==base:headers['Origin']=fake_origin
        headers.update({'Host':fake_origin[8:],'X-Forwarded-Proto':'https','CF-Visitor':'{"scheme":"https"}'})
        body=self.rfile.read(int(self.headers.get('Content-Length',0)))
        conn=http.client.HTTPConnection('127.0.0.1',origin_port,timeout=10)
        try:
            conn.request(self.command,self.path,body=body,headers=headers);response=conn.getresponse();data=response.read()
            self.send_response(response.status)
            for k,v in response.getheaders():
                if k.lower() not in ('content-length','connection','transfer-encoding'):self.send_header(k,v)
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        finally:conn.close()
    do_GET=forward
    do_POST=forward
proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(work/'cert.pem',work/'key.pem')
proxy.socket=context.wrap_socket(proxy.socket,server_side=True)
thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
base=f'https://127.0.0.1:{proxy.server_port}'
browser=None
try:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    profile=work/'profile';profile.mkdir()
    browser=subprocess.Popen([shutil.which('chromium') or shutil.which('google-chrome') or '/usr/lib/chromium/chromium','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
        '--ignore-certificate-errors','--disable-background-networking','--disable-extensions','--no-first-run','--remote-debugging-address=127.0.0.1',
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
            if evaluate("Boolean(document.querySelector('#classroom-login'))"):break
            time.sleep(.05)
        assert evaluate("Boolean(document.querySelector('#classroom-login'))")
        evaluate("document.querySelector('[name=code]').value='wrong';document.querySelector('[name=mock_acknowledged]').checked=true;document.querySelector('#classroom-login').requestSubmit();true")
        for _ in range(100):
            if evaluate("document.querySelector('#login-message').textContent.includes('无法登录')"):break
            time.sleep(.05)
        assert evaluate("document.querySelector('#login-message').textContent.includes('无法登录') && document.querySelector('[name=code]').value===''")
        evaluate("document.querySelector('[name=code]').value="+json.dumps(code)+";document.querySelector('#classroom-login').requestSubmit();true")
        for _ in range(100):
            if evaluate("Boolean(document.querySelector('#lesson-form'))"):break
            time.sleep(.05)
        assert evaluate("Boolean(document.querySelector('#lesson-form'))")
        cookies=command('Network.getCookies',{'urls':[base]})['result']['cookies']
        session=next(c for c in cookies if c['name']==COOKIE)
        assert session['secure'] is True and session['httpOnly'] is True and session['sameSite']=='Strict'
        assert evaluate("document.querySelector('.mode').textContent.includes('仅模拟数据')")
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
            set('class_label','MOCK-CLASSROOM-BROWSER');set('student_count','10');set('coach_count','2');
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
        evaluate("document.querySelector('[name=teacher_notes]').value='<img src=x onerror=alert(1)>';document.querySelector('#lesson-form').requestSubmit();true");wait_result()
        assert evaluate("document.querySelector('#elements').textContent.includes('<img') && document.querySelector('#result img')===null")
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
        assert downloaded['adaptation']['teacher_notes']=='<img src=x onerror=alert(1)>'
        assert downloaded['is_mock'] is True and downloaded['demo_data_domain']=='mock' and downloaded['human_review_performed'] is False
        assert downloaded['adaptation']['core_exercises'][0]['catalogue_task']=='陆地姿态对照'
        assert not any(term in json.dumps(downloaded) for term in ['Authorization','Bearer ','coachloop_local_console','postgresql://'])
        # Screenshot captures actual generated output rather than a fixed HTML demo.
        evaluate("document.querySelector('#result').scrollIntoView();true")
        screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        destination=root/'docs/classroom-tunnel-evidence';destination.mkdir(exist_ok=True)
        (destination/'console.png').write_bytes(base64.b64decode(screenshot['result']['data']))
        (destination/'download.example.json').write_text(json.dumps(downloaded,ensure_ascii=False,indent=2)+'\n')
        command('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
        evaluate("window.scrollTo(0,0);true")
        screenshot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        (destination/'mobile.png').write_bytes(base64.b64decode(screenshot['result']['data']))
        assert evaluate("document.documentElement.scrollWidth <= 395")
        evaluate("Array.from(document.querySelectorAll('button')).find(x=>x.textContent==='退出课堂').click();true")
        for _ in range(100):
            if evaluate("Boolean(document.querySelector('#classroom-login'))"):break
            time.sleep(.05)
        assert evaluate("Boolean(document.querySelector('#classroom-login'))")
        assert not state.sessions
        report=dict(kind='real_chromium_over_local_simulated_https_proxy',public_cloudflare_verified=False,
            coze_online=False,database_used=False,paid_model_calls=0,
            wrong_code_refused=True,secure_httponly_samesite_cookie=True,anonymous_not_authorized=True,
            classroom_mock_banner=True,dynamic_topic_and_grouping=True,teacher_edits=True,
            download_mock_draft_unverified=True,xss_notes_rendered_as_text=True,
            responsive_mobile_viewport=True,logout_revokes_session=True,
            tls_note='Self-signed loopback fixture only; browser certificate exception is not used by the public verifier')
        (destination/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))
finally:
    state.close();server.should_exit=True
    proxy.shutdown();proxy.server_close();worker.join(timeout=5);listener.close()
    if browser:
        browser.terminate()
        try:browser.wait(timeout=5)
        except subprocess.TimeoutExpired:browser.kill();browser.wait(timeout=5)
