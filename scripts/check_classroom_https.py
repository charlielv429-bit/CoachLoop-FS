"""Optional REAL public HTTPS acceptance. Prompts privately; no code in argv/logs.

Only calls the mock classroom API. TLS verification stays enabled, redirects are
refused. A Quick Tunnel URL alone is never considered proof of working access.
"""
import argparse
import getpass
from http.cookies import SimpleCookie
import http.cookiejar
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from integrations.prelesson.classroom import checked_origin, COOKIE, ClassroomRequest, ClassroomResult
from integrations.prelesson.schemas import ErrorResponse


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def error_shape(data):
    if not isinstance(data, dict) or set(data) != {'detail'}:
        return False
    detail=data['detail']
    if not isinstance(detail, (str,list)):
        return False
    if isinstance(detail,list) and any(not isinstance(d,dict) or set(d)!={'loc','msg','type'} for d in detail):
        return False
    try:ErrorResponse.model_validate(data)
    except ValueError:return False
    return True


def check(origin, code):
    origin=checked_origin(origin)
    jar=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPCookieProcessor(jar))
    def request(path, payload=None, *, csrf=True):
        headers={'Accept':'application/json'}
        body=None
        if payload is not None:
            headers['Content-Type']='application/json'
            if csrf:headers.update({'Origin':origin,'X-CoachLoop-Console':'1'})
            body=json.dumps(payload).encode()
        req=urllib.request.Request(origin+path,data=body,headers=headers)
        try:response=opener.open(req,timeout=20)
        except urllib.error.HTTPError as response_error:response=response_error
        with response:
            data=response.read(1024*1024+1)
            if len(data)>1024*1024:raise ValueError('Oversized response')
            parsed=json.loads(data,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            return response.status,parsed,response.headers
    results={}
    status,data,_=request('/health')
    results['health']=status==200 and data=={'status':'ok','mode':'classroom_mock_demo','database':'not_used'}
    status,data,_=request('/api/v1/lesson-plans/themes')
    results['anonymous_refused']=status==401 and error_shape(data)
    status,data,_=request('/classroom/login',{'code':'invalid-demo-credential','mock_acknowledged':True})
    results['wrong_code_refused']=status==401 and error_shape(data)
    status,data,_=request('/classroom/login',{'code':'invalid-demo-credential','mock_acknowledged':True},csrf=False)
    results['csrf_refused']=status==403 and error_shape(data)
    status,data,headers=request('/classroom/login',{'code':code,'mock_acknowledged':True})
    results['login']=status==200 and data=={'status':'signed_in','data_domain':'mock'}
    cookie=SimpleCookie();cookie.load(headers.get('Set-Cookie',''))
    item=cookie.get(COOKIE)
    results['secure_cookie']=bool(item and item['secure'] and item['httponly'] and item['samesite'].lower()=='strict' and item['path']=='/' and not item['domain'])
    if not all(results.values()):return results
    status,data,_=request('/api/v1/lesson-plans/themes')
    results['catalogue']=status==200 and data.get('knowledge_status')=='unverified' and len(data.get('themes',[]))==24
    fixture=dict(data_domain='mock',is_mock=True,class_label='MOCK-HTTPS-ACCEPTANCE',student_count=10,coach_count=2,teacher_count=1,
                 skill_level='零基础',usable_area_m2=200,declared_practice_capacity=10,equipment_sets=20,
                 safe_waiting_area=True,venue_conditions='MOCK合成冰场',equipment_conditions='MOCK合成装备',mastered_skills=['safety_equipment'])
    plans=[]
    for n in (10,20):
        status,data,_=request('/api/v1/lesson-plans/adaptive-draft',{**fixture,'student_count':n})
        valid=(status==200 and isinstance(data,dict) and data.get('is_mock') is True
               and data.get('data_domain')=='mock' and data.get('human_review_performed') is False)
        if valid:
            try:
                result=ClassroomResult.model_validate(data)
                result.model_dump_json() # Existing Agent's export guards must pass.
                ClassroomRequest.model_validate({**result.draft.request.model_dump(),'data_domain':'mock','is_mock':True})
                valid=(result.human_review_performed is False and result.is_mock is True)
                plans.append(result.draft.adaptation['organization']['rotation_count'])
            except ValueError:valid=False
        results[f'dynamic_{n}_students']=valid
    results['dynamic_organization']=plans==[1,2]
    status,data,_=request('/api/v1/lesson-plans/adaptive-draft',{**fixture,'data_domain':'pilot'})
    results['pilot_refused']=status==422 and error_shape(data)
    status,data,_=request('/classroom/logout',{})
    results['logout']=status==200 and data=={'status':'signed_out'}
    status,data,_=request('/api/v1/lesson-plans/themes')
    results['session_revoked']=status==401 and error_shape(data)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',required=True)
    args=parser.parse_args()
    try:
        origin=checked_origin(args.origin)
        if not sys.stdin.isatty():raise ValueError('Interactive hidden input required')
        code=getpass.getpass('Classroom code (hidden; never logged): ')
        results=check(origin,code)
        accepted=all(results.values())
        print(json.dumps({'public_https_verified':accepted,'checks':results},ensure_ascii=False))
        return 0 if accepted else 1
    except (ValueError,OSError,urllib.error.URLError):
        print(json.dumps({'public_https_verified':False,'error':'HTTPS verification failed; no credentials or response body logged'}))
        return 1


if __name__=='__main__':raise SystemExit(main())
