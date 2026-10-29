"""PR #4 independent review regressions; synthetic classroom and token only."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from graphs.prelesson_graph import run_prelesson
from integrations.prelesson.api import create_app
from integrations.prelesson.schemas import DraftRequest,DraftResponse

ROOT=Path(__file__).resolve().parents[1]
URL='/api/v1/lesson-plans/draft'
TOKEN='synthetic-independent-review-token'


@pytest.fixture
def payload():
    return json.loads((ROOT/'docs/prelesson-workflow-v01.example-request.json').read_text())


@pytest.fixture
def client():
    with TestClient(create_app(access_token=TOKEN),raise_server_exceptions=False) as c:yield c


@pytest.mark.parametrize('field,token',[
    ('estimated_group_active_min','-1e-1000'),('estimated_group_active_min','1e-1000'),
    ('estimated_group_active_min','45.0000000000000000000001'),
    ('estimated_individual_active_min','45.0000000000000000000001'),
    ('estimated_avg_hr','250.0000000000000000000001'),
    ('estimated_avg_hr','19.99999999999999999999999'),
])
def test_exact_numeric_boundary_rejects_before_float_rounding(client,payload,field,token):
    body=json.dumps(payload)[:-1]+',"'+field+'":'+token+'}'
    response=client.post(URL,content=body,headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
    assert response.status_code==422,response.text
    with pytest.raises(ValidationError):DraftRequest.model_validate({**payload,field:Decimal(token)})


@pytest.mark.parametrize('mutation',['approved','no_review','verified','wrong_schema','wrong_status','measured_basis','measured_metric','safety_approved','organization_approved','invalid_phase_ranges'])
def test_mutated_response_cannot_escape_output_guards(payload,mutation):
    result=run_prelesson(payload)
    if mutation=='approved':result.lesson_plan.review_status='approved'
    if mutation=='no_review':result.requires_teacher_review=False
    if mutation=='verified':result.knowledge_status='verified'
    if mutation=='wrong_schema':result.schema_version='other'
    if mutation=='wrong_status':result.status='approved'
    if mutation=='measured_basis':result.load_basis='measured'
    if mutation=='measured_metric':result.lesson_plan.load_accounting.avg_hr.kind='measured'
    if mutation=='safety_approved':result.lesson_plan.safety_precautions.safety_review_status='approved'
    if mutation=='organization_approved':result.lesson_plan.venue_equipment.organization_status='approved'
    if mutation=='invalid_phase_ranges':
        result.lesson_plan.teaching_flow.phases[0].minutes=1
        result.lesson_plan.teaching_flow.phases[1].minutes=37
    for output in (result.model_dump,result.model_dump_json,lambda:DraftResponse.model_validate(result)):
        with pytest.raises(ValueError):output()


def test_error_contract_describes_real_responses(client,payload):
    spec=client.get('/openapi.json').json()
    operation=spec['paths'][URL]['post']
    for status in ('401','403','413','422','503'):
        schema=operation['responses'][status]['content']['application/json']['schema']
        assert schema['$ref'].endswith('/ErrorResponse')
    responses=[client.post(URL,json=payload),
               client.post(URL,json=payload,headers={'Authorization':'Bearer wrong'}),
               client.post(URL,content='{',headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}),
               client.post(URL,json={**payload,'student_count':0},headers={'Authorization':'Bearer '+TOKEN}),
               client.post(URL,content=b'x'*(1024*1024+1))]
    with TestClient(create_app(access_token='')) as closed:responses.append(closed.post(URL,json=payload))
    from integrations.prelesson.schemas import ErrorResponse
    assert {r.status_code for r in responses}=={401,403,413,422,503}
    for response in responses:ErrorResponse.model_validate(response.json())


@pytest.mark.parametrize('headers',[
    {},{'Authorization':'Bearer wrong'}, {'Authorization':'Basic '+TOKEN},
    {'X-Role':'teacher','X-API-Key':TOKEN}, {'Authorization':'Bearer '+TOKEN+'-suffix'},
])
def test_bad_credentials_never_reach_generator(client,payload,headers,monkeypatch):
    import integrations.prelesson.api as api
    def forbidden(*_args):pytest.fail('Unauthorized request reached generation')
    monkeypatch.setattr(api,'run_prelesson',forbidden)
    response=client.post(URL,json=payload,headers=headers)
    assert response.status_code in (401,403)
    assert TOKEN not in response.text


def test_standard_auth_whitespace_still_requires_the_exact_token(client,payload):
    # FastAPI normalizes HTTP optional whitespace; this is not a credential bypass.
    response=client.post(URL,json=payload,headers={'Authorization':'Bearer '+TOKEN+' '})
    assert response.status_code==200
    assert response.json()['requires_teacher_review'] is True
    bad=client.post(URL,json=payload,headers={'Authorization':'Bearer '+TOKEN+'-wrong '})
    assert bad.status_code==403


def test_configured_credential_not_exposed_in_contract_or_results(client,payload):
    responses=[client.get('/openapi.json'),client.post(URL,json=payload,headers={'Authorization':'Bearer '+TOKEN}),
               client.post(URL,json=payload,headers={'Authorization':'Bearer wrong'})]
    assert [r.status_code for r in responses]==[200,200,403]
    assert all(TOKEN not in r.text for r in responses)


@pytest.mark.parametrize('field',['class_label','venue_conditions','equipment_conditions'])
def test_unpaired_unicode_is_rejected_without_echo_or_500(client,payload,field):
    response=client.post(URL,content=json.dumps({**payload,field:'MOCK-\ud800'}),headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'})
    assert response.status_code==422
    assert '\\ud800' not in response.text


@pytest.mark.parametrize('field,value',[
    ('estimated_group_active_min',0),('estimated_group_active_min',45),
    ('estimated_individual_active_min',0),('estimated_individual_active_min',45),
    ('estimated_avg_hr',20),('estimated_avg_hr',250),
])
def test_exact_legal_numeric_edges_remain_supported(client,payload,field,value):
    response=client.post(URL,json={**payload,field:value},headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==200,response.text
    assert response.json()['load_basis']=='estimated_design_assumptions'
