"""Import artifact/real API contract checks; no Coze account or external calls."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from integrations.prelesson.api import create_app
from integrations.prelesson.schemas import DraftResponse

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_script('build_coze_prelesson_plugin')
checker = load_script('check_coze_deployment')
DOCUMENT = json.loads((ROOT / 'docs/coze-prelesson-plugin-v01.openapi.json').read_text())
SAMPLE = json.loads((ROOT / 'docs/prelesson-workflow-v01.example-request.json').read_text())
TOKEN = 'synthetic-plugin-contract-test-only'


def schema31(value):
    if isinstance(value, list):
        return [schema31(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: schema31(v) for k, v in value.items()}
    nullable = result.pop('nullable', False)
    for exclusive, bound in [('exclusiveMinimum', 'minimum'), ('exclusiveMaximum', 'maximum')]:
        if result.get(exclusive) is True:
            result[exclusive] = result.pop(bound)
    return {'anyOf': [result, {'type': 'null'}]} if nullable else result


def shape(name, data):
    document = schema31(DOCUMENT)
    return checker.contract_shape(data, document['components']['schemas'][name], document)


def test_artifact_is_reproducible_and_live_contract_has_not_drifted():
    assert DOCUMENT == builder.build()
    live = create_app(TOKEN).openapi()
    assert DOCUMENT['components']['schemas'] == builder.schema30(
        live['components']['schemas'], live['components']['schemas'])
    operation = DOCUMENT['paths'][builder.PATH]['post']
    expected = builder.schema30(live['paths'][builder.PATH]['post'])
    assert operation['responses'] == {
        **expected['responses'], '200': {**expected['responses']['200'], 'content': {
            'application/json': {**expected['responses']['200']['content']['application/json'],
                                 'example': operation['responses']['200']['content']['application/json']['example']}}}}
    assert operation['requestBody']['content']['application/json']['schema'] == expected['requestBody']['content']['application/json']['schema']
    assert operation['security'] == [{'HTTPBearer': []}]
    assert list(DOCUMENT['paths']) == [builder.PATH]
    assert DOCUMENT['openapi'] == '3.0.3'


def test_exact_45_and_nullable_staff_constraints_survive_conversion():
    fields = DOCUMENT['components']['schemas']['DraftRequest']['properties']
    assert fields['student_count']['minimum'] == 0
    assert fields['student_count']['exclusiveMinimum'] is True
    assert fields['total_minutes']['minimum'] == fields['total_minutes']['maximum'] == 45
    assert fields['theme']['enum'] == ['冰上双足滑行与身体姿态控制']
    assert fields['skill_level']['enum'] == ['零基础']
    assert fields['teacher_count']['nullable'] is True
    assert shape('DraftRequest', SAMPLE)
    assert shape('DraftRequest', {**SAMPLE, 'teacher_count': None})


def test_real_success_and_documented_example_keep_review_and_evidence_protections():
    with TestClient(create_app(TOKEN)) as client:
        response = client.post(builder.PATH, json=SAMPLE, headers={'Authorization': 'Bearer ' + TOKEN})
    assert response.status_code == 200
    data = response.json()
    assert shape('DraftResponse', data)
    DraftResponse.model_validate(data)
    example = DOCUMENT['paths'][builder.PATH]['post']['responses']['200']['content']['application/json']['example']
    assert data == example
    assert data['requires_teacher_review'] is True
    assert data['knowledge_status'] == 'unverified'
    assert data['lesson_plan']['review_status'] == 'draft'
    assert data['lesson_plan']['teaching_flow']['total_minutes'] == 45
    assert all(e.get('citation') is None for e in data['lesson_plan']['evidence_log'])


@pytest.mark.parametrize('mutation', [
    {'total_minutes': 44}, {'student_count': 0}, {'student_count': True},
    {'theme': '跳跃'}, {'skill_level': '高级'}, {'review_status': 'approved'},
    {'knowledge_status': 'verified'}, {'requires_teacher_review': False},
    {'teacher_count': -1}, {'estimated_avg_hr': 999},
])
def test_adversarial_input_is_rejected(mutation):
    with TestClient(create_app(TOKEN)) as client:
        response = client.post(builder.PATH, json={**SAMPLE, **mutation}, headers={'Authorization': 'Bearer ' + TOKEN})
    assert response.status_code == 422
    assert shape('ErrorResponse', response.json())
    assert 'lesson_plan' not in response.json()


@pytest.mark.parametrize('configured,headers,status', [
    (TOKEN, {}, 401), (TOKEN, {'Authorization': 'Bearer synthetic-wrong'}, 403),
    ('', {'Authorization': 'Bearer ' + TOKEN}, 503),
])
def test_bearer_is_not_a_plugin_parameter_or_bypass(configured, headers, status):
    with TestClient(create_app(configured)) as client:
        response = client.post(builder.PATH, json=SAMPLE, headers=headers)
    assert response.status_code == status
    assert shape('ErrorResponse', response.json())
    assert TOKEN not in response.text


@pytest.mark.parametrize('origin', [
    'http://service.org', 'https://user:secret@service.org', 'https://service.org/api',
    'https://service.org?token=secret', 'https://service.org#secret',
    builder.PLACEHOLDER, 'https://example.com', 'https://127.0.0.1',
    'https://localhost', 'https://10.0.0.1', 'https://service.org\\bad',
    'https://service.org\n', 'https://service.org:0',
])
def test_unsafe_or_placeholder_final_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        builder.checked_origin(origin)


def test_all_references_are_local_and_resolvable():
    def visit(value):
        if isinstance(value, dict):
            if '$ref' in value:
                assert value['$ref'].startswith('#/components/schemas/')
                assert value['$ref'].split('/')[-1] in DOCUMENT['components']['schemas']
            assert 'const' not in value
            assert value.get('type') != 'null'
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(DOCUMENT)


def test_configuring_origin_does_not_add_secrets_or_claim_endpoint_verification():
    # Illustrative hostname only: this test does not perform DNS/HTTP or deploy.
    origin = builder.checked_origin('https://school-service.org:8443/')
    document = builder.build(origin)
    assert document['servers'][0]['url'] == 'https://school-service.org:8443'
    assert '未验证' in document['servers'][0]['description']
    assert 'Authorization' not in json.dumps(document)


def test_cli_writes_configured_contract_without_network(tmp_path):
    target = tmp_path / 'plugin.json'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_coze_prelesson_plugin.py'),
        '--origin', 'https://school-service.org', '--output', str(target)], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(target.read_text()) == builder.build('https://school-service.org')


def test_cli_rejects_credentials_without_echoing_them(tmp_path):
    target = tmp_path / 'plugin.json'
    secret = 'synthetic-do-not-echo-secret'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_coze_prelesson_plugin.py'),
        '--origin', 'https://user:' + secret + '@school-service.org', '--output', str(target)],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    assert not target.exists()
