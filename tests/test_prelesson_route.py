"""Main-app route tests: stub only the DB lifespan; real routes/auth/graph run."""
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from integrations.prelesson.schemas import DraftResponse

ROOT=Path(__file__).resolve().parents[1]
PATHS=('/api/v1/lesson-plans/draft','/prelesson/draft')
TOKEN='synthetic-main-route-token'


@pytest.fixture
def payload():return json.loads((ROOT/'docs/prelesson-workflow-v01.example-request.json').read_text())


@pytest.fixture
def main_client(monkeypatch):
    monkeypatch.setenv('COACHLOOP_PRELESSON_TOKEN',TOKEN)
    main=importlib.import_module('main')
    @asynccontextmanager
    async def offline(_app):yield
    monkeypatch.setattr(main.app.router,'lifespan_context',offline)
    with TestClient(main.app) as client:yield client


@pytest.mark.parametrize('path',PATHS)
def test_main_can_generate_guarded_draft(main_client,payload,path):
    response=main_client.post(path,json=payload,headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==200,response.text
    result=DraftResponse.model_validate(response.json())
    assert result.requires_teacher_review and result.knowledge_status=='unverified'
    assert result.lesson_plan.review_status=='draft'
    assert sum(p.minutes for p in result.lesson_plan.teaching_flow.phases)==45
    assert result.lesson_plan.load_accounting.total_minutes==45
    assert response.headers['cache-control']=='no-store'
    assert TOKEN not in response.text


@pytest.mark.parametrize('path',PATHS)
@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer wrong'},
    {'X-Authenticated-User':'teacher','X-Coze-Authenticated':'true','X-Forwarded-User':'teacher'}])
def test_both_routes_require_proven_access_control(main_client,payload,path,headers):
    response=main_client.post(path,json=payload,headers=headers)
    assert response.status_code in (401,403)


@pytest.mark.parametrize('path',PATHS)
@pytest.mark.parametrize('changes',[{'total_minutes':40},{'skill_level':'中级'},
    {'review_status':'approved'},{'kb_evidence':[{'grade':'A','citation':'伪造课标'}]}])
def test_main_rejects_unsupported_or_forged_inputs(main_client,payload,path,changes):
    response=main_client.post(path,json={**payload,**changes},headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==422
    assert '伪造课标' not in response.text


@pytest.mark.parametrize('path',PATHS)
def test_main_keeps_exact_parser_and_body_limit(main_client,payload,path):
    headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}
    body=json.dumps(payload).replace('"student_count": 20','"student_count": 0,"student_count": 20')
    assert main_client.post(path,content=body,headers=headers).status_code==422
    tiny=json.dumps(payload)[:-1]+',"estimated_group_active_min":-1e-1000}'
    assert main_client.post(path,content=tiny,headers=headers).status_code==422
    assert main_client.post(path,content=b'x'*(1024*1024+1),headers=headers).status_code==413


def test_main_openapi_and_standalone_contract_agree(main_client):
    from integrations.prelesson.api import create_app
    spec=main_client.get('/openapi.json').json()
    standalone=create_app(access_token=TOKEN).openapi()
    published=json.loads((ROOT/'docs/coze-integration-v01.openapi.json').read_text())
    for path in PATHS:
        assert published['paths'][path]==spec['paths'][path]
        operation=spec['paths'][path]['post']
        assert operation['security']==standalone['paths'][PATHS[0]]['post']['security']
        assert operation['requestBody']==standalone['paths'][PATHS[0]]['post']['requestBody']
        assert operation['responses']==standalone['paths'][PATHS[0]]['post']['responses']
    for name in ('DraftRequest','DraftResponse','DraftPlan','ErrorResponse'):
        assert spec['components']['schemas'][name]==standalone['components']['schemas'][name]
    for name,schema in published['components']['schemas'].items():
        assert spec['components']['schemas'][name]==schema
    assert TOKEN not in json.dumps(spec)


def test_installation_does_not_replace_legacy_routes_or_validation():
    from fastapi import FastAPI
    from pydantic import BaseModel
    from integrations.prelesson.api import create_router
    class OldInput(BaseModel):count:int
    app=FastAPI()
    @app.post('/old')
    def old(body:OldInput):return {'count':body.count}
    app.include_router(create_router(TOKEN,include_alias=True))
    with TestClient(app) as c:
        assert c.post('/old',json={'count':'2'}).json()=={'count':2}
        assert c.post('/old',json={'count':'invalid'}).json()['detail'][0]['input']=='invalid'
        assert c.post('/old',json={'count':1},headers={'Content-Type':'application/json'}).status_code==200


def test_main_legacy_graph_still_runs_and_prelesson_nodes_are_not_in_old_graph():
    main=importlib.import_module('main')
    from graphs.graph import main_graph
    from graphs.prelesson_graph import prelesson_graph
    assert 'generate_prelesson_draft' not in main_graph.get_graph().nodes
    assert 'generate_prelesson_draft' in prelesson_graph.get_graph().nodes
    routes={getattr(r,'path',None) for r in main.app.routes}
    assert {'/run','/stream_run','/node_run/{node_id}','/async_run','/health'}<=routes
    result=main_graph.invoke({'student_id':'MOCK-01','skill_code':'MOCK','duration_min':30,'observation':'合成观察'})
    assert result['run_status']=='valid' and result['mock']
