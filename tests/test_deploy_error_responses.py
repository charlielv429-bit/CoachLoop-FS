"""Regression of PR #6's three false-positive error response counterexamples."""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graphs.prelesson_graph import run_prelesson
from integrations.prelesson.api import create_app
from integrations.prelesson.schemas import ErrorResponse,ErrorDetail

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('readiness_error_review',ROOT/'scripts/check_coze_deployment.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
TOKEN='synthetic-error-response-test-token'


@pytest.fixture(scope='module')
def draft():return run_prelesson(check.SAMPLE).model_dump(mode='json')


def transport(draft,attack=None,legacy_status=404):
    def send(method,path,payload=None,token=None,extra=None):
        if method=='GET':return (200,{'status':'ok'}) if path=='/health' else (legacy_status,{'detail':'blocked'})
        if token is None:
            return 401,draft if attack=='missing_auth_draft' and not extra else {'detail':'required'}
        if token!=TOKEN:return 403,draft if attack=='wrong_auth_draft' else {'detail':'invalid'}
        if payload!=check.SAMPLE:return 422,'detail' if attack=='malformed_422' else {'detail':'invalid input'}
        return 200,draft
    return send


@pytest.mark.parametrize('attack',['malformed_422','missing_auth_draft','wrong_auth_draft'])
def test_original_three_error_false_positives_are_rejected(draft,attack):
    report=check.check_http('http://127.0.0.1',TOKEN,transport(draft,attack))
    assert not report['passed']
    assert len(report['checks'])==18
    assert TOKEN not in json.dumps(report)


@pytest.mark.parametrize('data',[
    'detail',['detail'],None,401,True,{},
    {'detail':401},{'detail':None},{'detail':{}},
    {'detail':[{'loc':['body']}]},
    {'detail':[{'loc':[True],'type':'value_error','msg':'synthetic'}]},
    {'detail':[{'loc':[],'type':1,'msg':'synthetic'}]},
    {'detail':'denied','lesson_plan':{}},{'detail':'draft_ready'},
])
def test_invalid_error_types_and_success_payloads_are_rejected(data):
    assert not check.valid_error_response(data)


@pytest.mark.parametrize('key,value',[
    ('lesson_plan',{}),('status','draft_ready'),('requires_teacher_review',True),
    ('knowledge_status','unverified'),('load_basis','estimated_design_assumptions'),('schema_version','prelesson-draft-v1'),
])
def test_error_envelope_cannot_carry_success_properties(key,value):
    assert not check.valid_error_response({'detail':'denied',key:value})


@pytest.mark.parametrize('data',[
    {'detail':[{'loc':['body'],'type':'value_error','msg':'synthetic','lesson_plan':{}}]},
    {'detail':json.dumps({'lesson_plan':{'review_status':'draft'}})},
    {'detail':json.dumps({'status':'draft_ready'})},
    {'detail':[{'loc':[],'type':'draft_ready','msg':'synthetic'}]},
])
def test_nested_or_json_encoded_success_payloads_are_rejected(data):
    assert not check.valid_error_response(data)


@pytest.mark.parametrize('data',[
    {'detail':'Denied'}, {'detail':''}, {'detail':[]},
    {'detail':[{'loc':['body','student_count'],'type':'greater_than','msg':'Request does not match schema'}]},
    # A field name in an error location is not a returned success object.
    {'detail':[{'loc':['body','lesson_plan',0],'type':'extra_forbidden','msg':'Request does not match schema'}]},
])
def test_actual_error_schema_variants_remain_valid(data):
    ErrorResponse.model_validate(data)
    assert check.valid_error_response(data)


@pytest.mark.parametrize('status',[400,405,413,503])
def test_unexpected_error_status_never_becomes_an_expected_rejection(draft,status):
    original=transport(draft)
    def send(method,path,payload=None,token=None,extra=None):
        code,data=original(method,path,payload,token,extra)
        if code==422:return status,{'detail':'synthetic unexpected error'}
        return code,data
    report=check.check_http('http://127.0.0.1',TOKEN,send)
    assert not report['passed']
    assert all(not c['passed'] for c in report['checks'] if '_reject_' in c['name'])


@pytest.mark.parametrize('status',[403,404])
def test_legacy_denial_codes_also_require_a_valid_error_body(draft,status):
    original=transport(draft,legacy_status=status)
    def send(method,path,payload=None,token=None,extra=None):
        code,data=original(method,path,payload,token,extra)
        if method=='GET' and path!='/health':return code,{'detail':'denied','lesson_plan':draft['lesson_plan']}
        return code,data
    report=check.check_http('http://127.0.0.1',TOKEN,send)
    assert not report['passed']
    assert all(not c['passed'] for c in report['checks'] if c['name'].startswith('legacy_blocked'))


@pytest.mark.parametrize('bad_status',[True,401.0,'401'])
def test_noninteger_http_status_is_rejected_and_not_echoed(bad_status):
    def send(*_args):return bad_status,{'detail':'synthetic'}
    report=check.check_http('http://127.0.0.1',TOKEN,send)
    assert not report['passed']
    assert all(c.get('error')=='invalid_http_status' and 'status' not in c for c in report['checks'])


def test_published_error_contract_matches_actual_api_models():
    schema,root=check.error_contract()
    expected=ErrorResponse.model_json_schema()
    expected.pop('$defs')
    normalized=json.loads(json.dumps(schema).replace('#/components/schemas/','#/$defs/'))
    assert normalized==expected
    assert root['components']['schemas']['ErrorDetail']==ErrorDetail.model_json_schema()


def test_real_api_error_responses_match_the_checker():
    with TestClient(create_app(access_token=TOKEN)) as client:
        url=check.CANONICAL
        responses=[client.post(url,json=check.SAMPLE),
            client.post(url,json=check.SAMPLE,headers={'Authorization':'Bearer wrong'}),
            client.post(url,content='{',headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}),
            client.post(url,json={**check.SAMPLE,'student_count':0},headers={'Authorization':'Bearer '+TOKEN}),
            client.post(url,content=b'x'*(1024*1024+1))]
    with TestClient(create_app(access_token='')) as closed:
        responses.append(closed.post(check.CANONICAL,json=check.SAMPLE))
    assert {r.status_code for r in responses}=={401,403,413,422,503}
    for response in responses:
        ErrorResponse.model_validate(response.json())
        assert check.valid_error_response(response.json())


def test_every_valid_error_path_still_allows_a_complete_smoke(draft):
    for status in (403,404):
        report=check.check_http('http://127.0.0.1',TOKEN,transport(draft,legacy_status=status))
        assert report['passed'] and len(report['checks'])==18


def test_malformed_errors_do_not_leak_response_text_or_secret_values(draft):
    original=transport(draft)
    def send(method,path,payload=None,token=None,extra=None):
        code,data=original(method,path,payload,token,extra)
        if code>=400:return code,{'detail':'synthetic','lesson_plan':{'private':TOKEN}}
        return code,data
    report=check.check_http('http://127.0.0.1',TOKEN,send)
    assert not report['passed']
    assert TOKEN not in json.dumps(report)
