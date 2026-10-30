import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from integrations.prelesson.console import create_console_app, COOKIE, CANONICAL
from integrations.prelesson.schemas import DraftResponse

PORT = 8767
ORIGIN = f'http://127.0.0.1:{PORT}'
HEADERS = {'Origin': ORIGIN, 'X-CoachLoop-Console': '1'}
ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = json.loads((ROOT / 'docs/prelesson-workflow-v01.example-request.json').read_text())


@pytest.fixture
def client():
    with TestClient(create_console_app(PORT), base_url=ORIGIN, client=('127.0.0.1', 54000)) as c:
        yield c


def test_bootstrap_has_no_production_secret_or_persistent_storage(client, monkeypatch):
    monkeypatch.setenv('COACHLOOP_PRELESSON_TOKEN', 'synthetic-production-secret-not-for-browser')
    response = client.get('/')
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
    for path in ('/', '/console.js', '/console.css', '/health'):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-frame-options'] == 'DENY'
        assert 'synthetic-production-secret-not-for-browser' not in response.text
        assert client.cookies.get(COOKIE) not in response.text
    script = client.get('/console.js').text
    assert all(key not in script for key in ('localStorage', 'sessionStorage', 'innerHTML', 'document.cookie'))
    assert "connect-src 'self'" in response.headers['content-security-policy']


def test_dynamic_generation_uses_existing_agent_and_updates_classroom(client):
    client.get('/')
    plans = []
    for count in (1, 20):
        response = client.post(CANONICAL, json={**PAYLOAD, 'student_count': count}, headers=HEADERS)
        assert response.status_code == 200
        result = DraftResponse.model_validate(response.json())
        assert f'{count}人' in result.lesson_plan.teacher_input.audience
        assert result.lesson_plan.teaching_flow.total_minutes == 45
        assert sum(p.minutes for p in result.lesson_plan.teaching_flow.phases) == 45
        assert result.requires_teacher_review and result.knowledge_status == 'unverified'
        assert result.lesson_plan.review_status == 'draft'
        assert all(e.citation is None for e in result.lesson_plan.evidence_log)
        plans.append(response.json())
    assert plans[0]['lesson_plan']['teacher_input'] != plans[1]['lesson_plan']['teacher_input']


@pytest.mark.parametrize('mutation', [
    {'student_count': 0}, {'student_count': True}, {'student_count': 1.5},
    {'total_minutes': 44}, {'theme': '跳跃'}, {'skill_level': '高级'},
    {'review_status': 'approved'}, {'knowledge_status': 'verified'}, {'teacher_count': -1},
])
def test_invalid_or_forged_input_cannot_create_a_draft(client, mutation):
    client.get('/')
    response = client.post(CANONICAL, json={**PAYLOAD, **mutation}, headers=HEADERS)
    assert response.status_code == 422 and 'lesson_plan' not in response.json()


def test_untrusted_requests_never_reach_agent(client, monkeypatch):
    import integrations.prelesson.api as api
    spy = Mock(side_effect=AssertionError('Unauthenticated request reached Agent'))
    monkeypatch.setattr(api, 'run_prelesson', spy)
    assert client.post(CANONICAL, json=PAYLOAD, headers=HEADERS).status_code == 401
    client.get('/')
    assert client.post(CANONICAL, json=PAYLOAD).status_code == 403
    assert client.post(CANONICAL, json=PAYLOAD, headers={**HEADERS, 'Origin': 'https://untrusted.invalid'}).status_code == 403
    assert client.post(CANONICAL, json=PAYLOAD, headers={**HEADERS, 'Authorization': 'Bearer synthetic-forged'}).status_code == 403
    spy.assert_not_called()


@pytest.mark.parametrize('headers', [
    {'Host': 'untrusted.invalid:8767'}, {'Host': 'localhost:8767'},
    {'X-Forwarded-For': '203.0.113.1'}, {'Forwarded': 'for=203.0.113.1'},
    {'X-Forwarded-Host': 'untrusted.invalid'}, {'X-Real-IP': '203.0.113.1'},
    {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'},
])
def test_rebinding_proxy_and_cross_site_requests_are_rejected(client, headers):
    assert client.get('/', headers=headers).status_code == 403


def test_remote_client_cannot_bootstrap_even_with_correct_host():
    with TestClient(create_console_app(PORT), base_url=ORIGIN, client=('203.0.113.1', 54000)) as remote:
        assert remote.get('/').status_code == 403


def test_duplicate_host_and_origin_headers_are_rejected(client):
    assert client.get('/', headers=[('Host', '127.0.0.1:8767'), ('Host', '127.0.0.1:8767')]).status_code == 403
    client.get('/')
    assert client.post(CANONICAL, json=PAYLOAD, headers=[('Origin', ORIGIN), ('Origin', ORIGIN), ('X-CoachLoop-Console', '1')]).status_code == 403


@pytest.mark.parametrize('path', ['/run', '/async_run', '/stream_run', '/docs', '/openapi.json', '/prelesson/draft', '/api/v1/reviewed-training-results/import'])
def test_console_does_not_expose_legacy_or_database_routes(client, path):
    client.get('/')
    for method in ('GET', 'POST', 'OPTIONS'):
        assert client.request(method, path, headers=HEADERS).status_code == 404


def test_json_size_and_duplicate_key_guards_are_retained(client):
    client.get('/')
    headers = {**HEADERS, 'Content-Type': 'application/json'}
    raw = json.dumps(PAYLOAD).replace('"student_count": 20', '"student_count": 0,"student_count": 20')
    assert client.post(CANONICAL, content=raw, headers=headers).status_code == 422
    assert client.post(CANONICAL, content='x' * (1024 * 1024 + 1), headers=headers).status_code == 413
    assert client.post(CANONICAL, content=json.dumps(PAYLOAD), headers={**HEADERS, 'Content-Type': 'text/plain'}).status_code == 403


def test_websocket_and_wrong_methods_are_closed(client):
    assert client.get(CANONICAL).status_code == 404
    assert client.post('/health').status_code == 404
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect('/'):
            pytest.fail('WebSocket opened')
    assert error.value.code == 1008


def test_restarted_console_rejects_an_old_session(client):
    client.get('/')
    cookie = client.cookies.get(COOKIE)
    with TestClient(create_console_app(PORT), base_url=ORIGIN, client=('127.0.0.1', 54000)) as restarted:
        restarted.cookies.set(COOKIE, cookie)
        assert restarted.post(CANONICAL, json=PAYLOAD, headers=HEADERS).status_code == 401


@pytest.mark.parametrize('port', [0, 65536, True, '8767'])
def test_console_refuses_invalid_ports(port):
    with pytest.raises(ValueError):
        create_console_app(port)


def test_launcher_cannot_be_switched_to_a_public_bind_address():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_prelesson_console.py'),
        '--host', '0.0.0.0'], capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert '0.0.0.0' not in result.stdout + result.stderr
    subprocess.run(['bash', '-n', str(ROOT / 'scripts/start_prelesson_console.command')], check=True)
