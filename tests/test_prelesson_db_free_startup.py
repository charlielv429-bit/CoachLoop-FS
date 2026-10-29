"""DB-free main lifespan and real checked-launcher acceptance; synthetic only."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import urllib.request
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from integrations.prelesson.schemas import DraftResponse

ROOT = Path(__file__).resolve().parents[1]
PATHS = ('/api/v1/lesson-plans/draft', '/prelesson/draft')
TOKEN = 'synthetic-db-free-startup-token-at-least-32'


def load_main(monkeypatch, profile):
    if profile is None:
        monkeypatch.delenv('COACHLOOP_PRELESSON_ONLY', raising=False)
    else:
        monkeypatch.setenv('COACHLOOP_PRELESSON_ONLY', profile)
    monkeypatch.setenv('COACHLOOP_PRELESSON_TOKEN', TOKEN)
    spec = importlib.util.spec_from_file_location('db_free_test_main', ROOT / 'src/main.py')
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    return main


def remove_db_variables(env):
    return {k: v for k, v in env.items() if not (
        k.startswith('PG') or 'DATABASE' in k or k.startswith('TEACHING_'))}


def test_restricted_lifespan_never_initializes_legacy_or_db(monkeypatch):
    for key in set(os.environ) - set(remove_db_variables(os.environ)):
        monkeypatch.delenv(key)
    main = load_main(monkeypatch, '1')
    forbidden = Mock(side_effect=AssertionError('Legacy/DB initialization is forbidden'))
    for name in ('get_engine', 'get_memory_saver', 'AsyncTaskRuntime'):
        monkeypatch.setattr(main, name, forbidden)
    monkeypatch.setattr(main.graph_helper, 'get_graph_instance', forbidden)
    monkeypatch.setattr(main.graph_helper, 'get_agent_instance', forbidden)
    monkeypatch.setattr(main.service, 'set_graph', forbidden)
    # Environment mutation after import must not desynchronize startup/guard.
    monkeypatch.setenv('COACHLOOP_PRELESSON_ONLY', '0')
    with TestClient(main.app) as client:
        assert client.get('/health').status_code == 200
        assert main.async_runtime is None and main.async_graph is None
        for path in ('/run', '/async_run', '/stream_run', '/task/mock', '/docs', '/openapi.json', '/v1/chat/completions'):
            for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE'):
                assert client.request(method, path).status_code == 404
        for path in PATHS:
            for method in ('GET', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE'):
                assert client.request(method, path).status_code == 404
        assert client.post('/health').status_code == 404
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect('/prelesson/draft'):
                pytest.fail('WebSocket must not open')
        assert error.value.code == 1008
    forbidden.assert_not_called()


@pytest.mark.parametrize('profile', [None, '0'])
@pytest.mark.parametrize('is_agent', [False, True])
def test_normal_lifespan_preserves_original_initialization(monkeypatch, profile, is_agent):
    main = load_main(monkeypatch, profile)
    engine, checkpointer = object(), object()
    get_engine = Mock(return_value=engine)
    get_memory = Mock(return_value=checkpointer)
    builder = SimpleNamespace(compile=Mock(side_effect=['sync-graph', 'async-graph']))
    get_graph = Mock(return_value=SimpleNamespace(builder=builder))
    runtime = SimpleNamespace(shutdown=AsyncMock())
    factory = Mock(return_value=runtime)
    monkeypatch.setattr(main, 'get_engine', get_engine)
    monkeypatch.setattr(main, 'get_memory_saver', get_memory)
    monkeypatch.setattr(main.event, 'listens_for', lambda *args: lambda fn: fn)
    monkeypatch.setattr(main.graph_helper, 'is_agent_proj', lambda: is_agent)
    monkeypatch.setattr(main.graph_helper, 'get_agent_instance', get_graph)
    monkeypatch.setattr(main.graph_helper, 'get_graph_instance', get_graph)
    monkeypatch.setattr(main, 'AsyncTaskRuntime', factory)
    set_graph = Mock()
    monkeypatch.setattr(main.service, 'set_graph', set_graph)
    # The normal profile also stays frozen even if the environment later changes.
    monkeypatch.setenv('COACHLOOP_PRELESSON_ONLY', '1')
    async def exercise():
        async with main.lifespan(main.app):
            assert main.async_runtime is runtime and main.async_graph == 'async-graph'
    asyncio.run(exercise())
    get_engine.assert_called_once_with()
    get_memory.assert_called_once_with()
    assert builder.compile.call_args_list[0].kwargs == ({'checkpointer': checkpointer} if is_agent else {})
    assert builder.compile.call_args_list[1].kwargs == {'checkpointer': checkpointer}
    set_graph.assert_called_once_with('sync-graph')
    factory.assert_called_once_with(session_factory=main.get_session, engine=engine,
        graph='async-graph', checkpointer=checkpointer)
    runtime.shutdown.assert_awaited_once()


@pytest.mark.parametrize('database_variables', [{}, {'PGDATABASE_URL': 'invalid-unused', 'DATABASE_URL': 'invalid-unused'}])
def test_preflight_does_not_require_or_parse_database_variables(database_variables):
    spec = importlib.util.spec_from_file_location('db_free_check', ROOT / 'scripts/check_coze_deployment.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    report = check.preflight({'COACHLOOP_PRELESSON_ONLY': '1',
        'COACHLOOP_PRELESSON_TOKEN': TOKEN, **database_variables})
    assert report['passed'] and report['database_mode'] == 'disabled'
    assert 'invalid-unused' not in json.dumps(report)


@pytest.mark.parametrize('injected_db', [False, True], ids=['no-db-variables', 'ignore-injected-db'])
def test_real_launcher_uvicorn_http_and_smoke_without_database(tmp_path, injected_db):
    marker = tmp_path / 'forbidden-calls.txt'
    # Runs in every child Python before main import. Never record arguments,
    # URLs or secrets. Any DB/legacy initialization or outbound socket attempt
    # is rejected and recorded even if the caller swallows the exception.
    (tmp_path / 'sitecustomize.py').write_text('''
import sys
from pathlib import Path
marker = Path(__file__).with_name('forbidden-calls.txt')
def forbidden(*args, **kwargs):
    with marker.open('a') as output: output.write('forbidden initialization or connection\\n')
    raise RuntimeError('Forbidden in DB-free startup acceptance test')
def audit(event, args):
    if event == 'socket.connect': forbidden()
sys.addaudithook(audit)
import sqlalchemy
sqlalchemy.create_engine = forbidden
import psycopg, psycopg2
psycopg.connect = forbidden
psycopg2.connect = forbidden
import storage.database.db as db
db.get_db_url = db.get_engine = db.get_session = forbidden
import storage.memory.memory_saver as memory
memory.get_memory_saver = forbidden
memory.PostgresSaver.setup = forbidden
import coze_coding_utils.async_tasks as tasks
tasks.AsyncTaskRuntime = forbidden
from coze_coding_utils.helper import graph_helper
graph_helper.get_graph_instance = graph_helper.get_agent_instance = forbidden
with Path(__file__).with_name('instrumentation-ready.txt').open('a') as output:
    output.write('ready\\n')
''')
    token = secrets.token_urlsafe(32)
    env = remove_db_variables(os.environ)
    env.update(COZE_WORKSPACE_PATH=str(ROOT), COZE_PROJECT_ENV='PROD',
        COACHLOOP_PRELESSON_ONLY='1', COACHLOOP_PRELESSON_TOKEN=token,
        PYTHONPATH=os.pathsep.join([str(tmp_path), str(ROOT / 'src')]),
        PYTHONDONTWRITEBYTECODE='1', LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    if injected_db:
        env.update(PGDATABASE_URL='invalid-unused', DATABASE_URL='invalid-unused')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env['DEPLOY_RUN_PORT'] = str(port)
    process = subprocess.Popen(['bash', str(ROOT / 'scripts/coze_prelesson_run.sh')], cwd=ROOT,
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, payload=None, auth=None, extra=None):
        headers = {'Content-Type': 'application/json', **(extra or {})}
        if auth is not None:
            headers['Authorization'] = auth
        req = urllib.request.Request(base + path, headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with opener.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)
    try:
        for _ in range(200):
            assert process.poll() is None, 'Checked local launcher exited; logs deliberately omitted'
            try:
                if request('/health')[0] == 200:
                    break
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(.1)
        else:
            pytest.fail('DB-free main did not become ready')
        payload = json.loads((ROOT / 'docs/prelesson-workflow-v01.example-request.json').read_text())
        for path in PATHS:
            assert request(path, payload)[0] == 401
            assert request(path, payload, 'Basic synthetic')[0] == 401
            assert request(path, payload, 'Bearer synthetic-wrong')[0] == 403
            assert request(path, payload, extra={'X-Coze-Authenticated': 'true'})[0] == 401
            status, data = request(path, payload, 'Bearer ' + token)
            assert status == 200
            draft = DraftResponse.model_validate(data)
            assert draft.knowledge_status == 'unverified' and draft.requires_teacher_review
            assert draft.lesson_plan.review_status == 'draft'
            assert draft.lesson_plan.load_accounting.total_minutes == 45
            assert request(path, {**payload, 'total_minutes': 44}, 'Bearer ' + token)[0] == 422
            assert request(path, {**payload, 'review_status': 'approved'}, 'Bearer ' + token)[0] == 422
        for path in ('/run', '/async_run', '/stream_run', '/task/mock', '/openapi.json'):
            assert request(path)[0] == 404
            assert request(path, {}, 'Bearer ' + token)[0] == 404
        # The smoke client needs outbound loopback sockets; remove only the
        # child-server instrumentation, keeping the same sanitized environment.
        smoke_env = {**env, 'PYTHONPATH': str(ROOT / 'src')}
        smoke = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/check_coze_deployment.py'),
            '--base-url', base], env=smoke_env, cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert smoke.returncode == 0, 'DB-free real HTTP smoke failed; raw output omitted'
        report = json.loads(smoke.stdout)
        assert report['passed'] and len(report['checks']) == 18
        assert token not in smoke.stdout + smoke.stderr
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert not marker.exists(), 'DB/legacy initialization or outbound network attempted'
    assert (tmp_path / 'instrumentation-ready.txt').read_text().splitlines() == ['ready', 'ready']
