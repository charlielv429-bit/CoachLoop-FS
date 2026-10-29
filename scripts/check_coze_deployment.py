#!/usr/bin/env python3
"""Stdlib-only, redacted readiness checks. Never invokes legacy workflows/models."""
import argparse
import importlib.metadata
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlsplit
from functools import lru_cache

RESPONSE_CONTRACT=Path(__file__).resolve().parents[1]/'docs/prelesson-workflow-v01.response.schema.json'
ERROR_CONTRACT=Path(__file__).resolve().parents[1]/'docs/coze-integration-v01.openapi.json'

ROOT_FIELDS=('guiding_ideology','teaching_material_analysis','learner_analysis','venue_equipment',
             'safety_precautions','teaching_flow','load_accounting')
CANONICAL='/api/v1/lesson-plans/draft'
ALIAS='/prelesson/draft'
SAMPLE={'class_label':'MOCK-DEPLOY-01','student_count':20,'theme':'冰上双足滑行与身体姿态控制',
        'skill_level':'零基础','total_minutes':45,'coach_count':1,'teacher_count':1,
        'venue_conditions':'合成冰场一片，容量待核定','equipment_conditions':'合成冰鞋护具各20套'}


def preflight(environ=None):
    env=os.environ if environ is None else environ
    token=env.get('COACHLOOP_PRELESSON_TOKEN','')
    checks=[{'name':'python_3_12_or_later','passed':sys.version_info>=(3,12)},
        {'name':'prelesson_only_profile','passed':env.get('COACHLOOP_PRELESSON_ONLY')=='1'},
        {'name':'service_credential_format','passed':len(token)>=32 and token.isascii() and not any(c.isspace() or ord(c)<33 or ord(c)>126 for c in token)},
        {'name':'database_disabled_in_prelesson_only_profile','passed':env.get('COACHLOOP_PRELESSON_ONLY')=='1'},
        {'name':'published_response_contract_present','passed':contract_available()},
        {'name':'published_error_contract_present','passed':error_contract_available()}]
    for package in ('fastapi','pydantic','langgraph','uvicorn','coze-coding-utils','coze-coding-dev-sdk','psycopg','psycopg2-binary'):
        try:importlib.metadata.version(package);present=True
        except importlib.metadata.PackageNotFoundError:present=False
        checks.append({'name':'dependency_'+package,'passed':present})
    return {'mode':'local_preflight','passed':all(c['passed'] for c in checks),'checks':checks,
            'database_mode':'disabled' if env.get('COACHLOOP_PRELESSON_ONLY')=='1' else 'unsupported_profile',
            'coze_platform_status':'待 Coze 实测'}


def validate_origin(value):
    if any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value) or '\\' in value:
        raise ValueError('Origin must not contain whitespace, controls or backslashes')
    parsed=urlsplit(value)
    if (parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in ('','/') or not parsed.hostname):
        raise ValueError('Use a credential-free origin with no query/path/fragment')
    _=parsed.port
    if parsed.scheme=='http':
        try:loopback=ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:loopback=parsed.hostname=='localhost'
        if not loopback:raise ValueError('Plain HTTP is limited to loopback tests')
    elif parsed.scheme!='https':raise ValueError('HTTPS required')
    return value.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):return None


class RedactedParser(argparse.ArgumentParser):
    def error(self,_message):
        # argparse's default error echoes unknown arguments, which may contain
        # an accidentally pasted credential. Never print argv values.
        self.exit(2,'Invalid arguments; use --preflight or --base-url. Values omitted.\n')


class Transport:
    def __init__(self,origin):
        self.origin=validate_origin(origin)
        # Honor configured proxies/CA trust. No credential-bearing redirects.
        handlers=[NoRedirect()]
        if urlsplit(self.origin).scheme=='http':
            # validate_origin only permits loopback HTTP. Never proxy local
            # synthetic tests; remote HTTPS keeps the managed proxy/CA policy.
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener=urllib.request.build_opener(*handlers)

    def __call__(self,method,path,payload=None,token=None,extra_headers=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        if extra_headers:headers.update(extra_headers)
        req=urllib.request.Request(self.origin+path,method=method,headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None)
        try:response=self.opener.open(req,timeout=10)
        except HTTPError as error:response=error
        with response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('Response too large')
            return response.status,json.loads(raw)


@lru_cache(maxsize=1)
def response_contract():
    return json.loads(RESPONSE_CONTRACT.read_text())


def contract_available():
    try:return response_contract().get('type')=='object'
    except (OSError,ValueError):return False


@lru_cache(maxsize=1)
def error_contract():
    root=json.loads(ERROR_CONTRACT.read_text())
    return root['components']['schemas']['ErrorResponse'],root


def error_contract_available():
    try:
        schema,_=error_contract()
        return schema.get('type')=='object' and 'detail' in schema.get('required',[])
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False


def contract_shape(value,schema,root):
    """Check the published response's required structure/types without an SDK.

    This is the subset used by our generated contract, not a general JSON Schema
    engine. Business invariants below remain separate from structural checks.
    """
    if '$ref' in schema:
        ref=schema['$ref']
        if not ref.startswith('#/'):return False  # Local JSON pointers only; no URL fetches.
        target=root
        for key in ref[2:].split('/'):
            target=target[key.replace('~1','/').replace('~0','~')]
        return contract_shape(value,target,root)
    if 'anyOf' in schema:return any(contract_shape(value,s,root) for s in schema['anyOf'])
    kind=schema.get('type')
    if kind=='object':
        if not isinstance(value,dict) or not set(schema.get('required',[]))<=value.keys():return False
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False and not value.keys()<=props.keys():return False
        return all(contract_shape(v,props[k],root) for k,v in value.items() if k in props)
    if kind=='array':
        return (isinstance(value,list) and len(value)>=schema.get('minItems',0)
                and len(value)<=schema.get('maxItems',len(value))
                and all(contract_shape(v,schema.get('items',{}),root) for v in value))
    if kind=='string':
        if not isinstance(value,str) or not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',len(value)):return False
        if 'pattern' in schema and re.search(schema['pattern'],value) is None:return False
    elif kind=='integer':
        if type(value) is not int:return False
    elif kind=='number':
        if type(value) not in (int,float) or not math.isfinite(value):return False
    elif kind=='boolean':
        if type(value) is not bool:return False
    elif kind=='null':
        if value is not None:return False
    elif kind is not None:return False
    if 'const' in schema and (value!=schema['const'] or type(value) is not type(schema['const'])):return False
    if 'enum' in schema and value not in schema['enum']:return False
    if kind in ('number','integer'):
        if 'minimum' in schema and value<schema['minimum']:return False
        if 'maximum' in schema and value>schema['maximum']:return False
        if 'exclusiveMinimum' in schema and value<=schema['exclusiveMinimum']:return False
        if 'exclusiveMaximum' in schema and value>=schema['exclusiveMaximum']:return False
    return True


@lru_cache(maxsize=1)
def success_payload_keys():
    schema=response_contract()
    return (set(schema['properties']) | set(schema['$defs']['DraftPlan']['properties'])
            | {'draft_ready'})


def contains_success_payload(value,depth=0):
    if depth>32:return True  # Fail closed for abnormally nested error data.
    if isinstance(value,dict):
        return (bool(value.keys() & success_payload_keys())
                or any(contains_success_payload(v,depth+1) for v in value.values()))
    if isinstance(value,list):return any(contains_success_payload(v,depth+1) for v in value)
    if isinstance(value,str):
        if value=='draft_ready':return True
        if value.lstrip().startswith(('{','[','"')):
            try:decoded=json.loads(value)
            except (ValueError,RecursionError):return False
            return contains_success_payload(decoded,depth+1)
    return False


def valid_error_response(data):
    """Use the API's published ErrorResponse; deny success data in any error.

    The API schema permits additional properties, but deployment safety checks
    deliberately accept only its actual detail envelope, without success fields.
    """
    try:
        if not isinstance(data,dict) or set(data)!={'detail'}:return False
        schema,root=error_contract()
        return contract_shape(data,schema,root) and not contains_success_payload(data)
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError):return False


def valid_draft(data,expected_request=None):
    try:
        contract=response_contract()
        if not contract_shape(data,contract,contract):return False
        if data['schema_version']!='prelesson-draft-v1':return False
        p=data['lesson_plan'];flow=p['teaching_flow'];load=p['load_accounting']
        if p['teacher_input']['theme']!=SAMPLE['theme'] or p['teacher_input']['class_data_available'] is not False:return False
        if expected_request is not None:
            audience=f"{expected_request['class_label']}·{expected_request['student_count']}人·初学者"
            if p['teacher_input']['audience']!=audience:return False
        if not all(isinstance(p[k],dict) and p[k] for k in ROOT_FIELDS):return False
        phases=flow['phases']
        ranges={'prep':(8,10),'main':(28,30),'closing':(5,7)}
        if len(phases)!=3 or {p['phase'] for p in phases}!=set(ranges):return False
        if any(type(p['minutes']) is not int or not ranges[p['phase']][0]<=p['minutes']<=ranges[p['phase']][1] for p in phases):return False
        if flow['total_minutes']!=45 or sum(p['minutes'] for p in phases)!=45 or load['total_minutes']!=45:return False
        if (data['status']!='draft_ready' or data['requires_teacher_review'] is not True
                or data['knowledge_status']!='unverified' or data['load_basis']!='estimated_design_assumptions'
                or p['review_status']!='draft' or p['safety_precautions']['safety_review_status']!='unreviewed'
                or p['venue_equipment']['organization_status']!='pending_confirmation'):return False
        if not p['learner_analysis']['tiered_plan'] or not all(p['safety_tip'] for p in phases):return False
        if not any(e['source']=='unverified' for e in p['evidence_log']):return False
        if any(e.get('citation') is not None or e.get('event_ref') is not None
               or e['source'] in ('kb_evidence','real_analysis') for e in p['evidence_log']):return False
        for name in ('group_density','individual_density','avg_hr'):
            m=load[name]
            if m['kind']!='estimated':return False
            if any(type(m[k]) not in (int,float) or not math.isfinite(m[k]) for k in ('numerator','denominator','result')):return False
            if m['numerator']<0 or m['denominator']<=0 or m['result']<0:return False
            if name=='avg_hr':
                if m['unit']!='次/分' or m['denominator']!=1 or not 20<=m['result']<=250:return False
                expected=m['numerator']
            else:
                if m['unit']!='%' or m['denominator']!=45 or m['numerator']>45:return False
                expected=m['numerator']/45*100
            if not math.isclose(m['result'],expected,rel_tol=1e-12,abs_tol=1e-12):return False
        return True
    except (KeyError,TypeError,ValueError,OverflowError,ZeroDivisionError,OSError,RecursionError):return False


def check_http(origin,token,requestor=None):
    origin=validate_origin(origin)
    if not token or not token.isascii() or any(ord(c)<33 or ord(c)>126 for c in token):
        raise ValueError('Credential unavailable or invalid')
    requestor=requestor or Transport(origin)
    checks=[]
    def probe(name,method,path,expected,payload=None,credential=None,extra=None,validator=None):
        try:
            status,data=requestor(method,path,payload,credential,extra)
            status_ok=type(status) is int and status in expected
            error_ok=valid_error_response(data) if status_ok and 400<=status<=599 else True
            passed=status_ok and error_ok and (validator(data) if validator else True)
            item={'name':name,'passed':bool(passed)}
            if type(status) is int:item['status']=status
            else:item['error']='invalid_http_status'
            checks.append(item)
            return data if passed else None
        except Exception:
            # Deliberately omit raw exceptions/URLs/headers/response text.
            checks.append({'name':name,'passed':False,'error':'transport_or_response_failed'})
            return None
    probe('health','GET','/health',{200},validator=lambda d:d.get('status')=='ok')
    for label,path in (('canonical',CANONICAL),('alias',ALIAS)):
        probe(label+'_missing_auth','POST',path,{401},SAMPLE)
        probe(label+'_wrong_auth','POST',path,{403},SAMPLE,'invalid-synthetic-probe-token')
        probe(label+'_spoofed_gateway','POST',path,{401},SAMPLE,extra={'X-Coze-Authenticated':'true','X-Authenticated-User':'teacher'})
        probe(label+'_draft','POST',path,{200},SAMPLE,token,validator=lambda d:valid_draft(d,SAMPLE))
        for key,value in (('total_minutes',40),('theme','不支持的主题'),('review_status','approved')):
            probe(label+'_reject_'+key,'POST',path,{422},{**SAMPLE,key:value},token)
    # GET cannot execute these POST-only legacy workflows or enqueue async jobs.
    # 405 means a legacy route may still be exposed; fail rather than claim safety.
    for path in ('/run','/async_run','/stream_run'):
        probe('legacy_blocked_'+path[1:],'GET',path,{403,404},credential=token)
    return {'mode':'http_smoke','passed':all(c['passed'] for c in checks),'checks':checks,
            'coze_platform_status':'待 Coze 实测','scope':'Observed endpoint checks only; not gateway identity attestation'}


def main(argv=None):
    parser=RedactedParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preflight',action='store_true')
    group.add_argument('--base-url',help='Approved HTTPS origin, or loopback HTTP for local tests; no credentials')
    args=parser.parse_args(argv)
    try:
        result=preflight() if args.preflight else check_http(args.base_url,os.environ.get('COACHLOOP_PRELESSON_TOKEN',''))
    except Exception:
        result={'passed':False,'error':'Invalid configuration or target; values deliberately omitted','coze_platform_status':'待 Coze 实测'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
