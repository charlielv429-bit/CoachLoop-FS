"""Synthetic registry records only; none are professional skating knowledge."""
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from integrations.prelesson.console import create_console_app
from integrations.curriculum_v3.registry import Registry, RegistryError, Knowledge, Archive, LESSONS
from agents.lesson_plan_agent.adaptive import catalogue

ORIGIN = 'http://127.0.0.1:8767'
HEADERS = {'Origin': ORIGIN, 'X-CoachLoop-Console': '1'}
TITLES = ['冰上基础技能综合入门', '交替蹬冰滑行与基础停止', '单足平衡与重心控制', '左前交叉步的蹬冰', '左前交叉步完整动作练习', '连续左前交叉步练习', '基础级步法完整练习（一）', '基础级步法完整练习（二）与综合评价']


def record(**updates):
    return dict(knowledge_id='SYNTHETIC_TEST_ONLY', category='KB-S', title='模拟测试资料（非正式知识）',
                content='仅验证存储检索，不提供专项教学建议。', lesson_ids=['L01'], version=1, **updates)


@pytest.fixture
def client():
    with TestClient(create_console_app(), base_url=ORIGIN, client=('127.0.0.1', 55000)) as c:
        c.get('/')
        yield c


def post(c, path, data):
    return c.post('/api/v3/' + path, json=data, headers=HEADERS)


def test_eight_lessons_independent_and_initially_empty(client):
    assert len(catalogue()) == 24
    assert len(LESSONS) == 8
    lessons = client.get('/api/v3/lessons').json()['lessons']
    assert [x['lesson_id'] for x in lessons] == [f'L0{i}' for i in range(1, 9)]
    assert [x['title'] for x in lessons] == TITLES
    assert all(x['duration_min'] == 45 and x['review_label'] == '待审核' and x['missing_materials'] and x['teaching_objective_draft'] for x in lessons)
    assert all(x['linked_knowledge'] == x['formal_teaching_basis'] == [] for x in lessons)
    assert all('theme_id' not in x for x in lessons)
    assert client.get('/api/v3/lessons?lesson_id=L04').json()['lessons'][0]['title'] == TITLES[3]
    assert client.get('/api/v3/export').json()['entries'] == []


def test_all_categories_search_link_and_history(client):
    for i, category in enumerate(('KB-S', 'KB-P', 'KB-A', 'KB-E')):
        entry = record()
        entry.update(knowledge_id=f'SYNTHETIC_{i}', category=category)
        saved = post(client, 'knowledge', entry)
        assert saved.status_code == 200
        assert saved.json()['source_label'] == '待补充'
        assert saved.json()['review_label'] == '待审核'
        assert saved.json()['formal_teaching_basis'] is False
        results = client.get('/api/v3/knowledge', params={'category': category, 'lesson_id': 'L01', 'keyword': '模拟测试'}).json()['entries']
        assert len(results) == 1 and results[0]['category'] == category
    assert client.get('/api/v3/knowledge?lesson_id=L02').json()['entries'] == []
    assert len(client.get('/api/v3/lessons?lesson_id=L01').json()['lessons'][0]['linked_knowledge']) == 4
    entry.update(version=2, content='模拟修订，仍无专业依据。')
    assert post(client, 'knowledge', entry).status_code == 200
    history = client.get('/api/v3/history?knowledge_id=SYNTHETIC_3').json()['entries']
    assert [x['version'] for x in history] == [1, 2]
    assert history[0]['content'] != history[1]['content']
    assert post(client, 'knowledge', entry).status_code == 409


@pytest.mark.parametrize('update', [
    {'source_verification_status': 'verified'}, {'specialist_review_status': 'approved'},
    {'specialist_review_status': 'certified'}, {'formal_teaching_basis': True},
    {'reviewer': 'professional'}, {'source_verification_status': 'submitted'},
    {'title': '<script>alert(1)</script>'}, {'content': '\x00bad'}, {'title': '  '},
    {'lesson_ids': ['L09']}, {'lesson_ids': ['L01','L01']}, {'version': True},
    {'category': 'KB-X'}, {'knowledge_id': '../escape'}, {'content': 'x' * 10001},
])
def test_invalid_or_forged_fields_rejected_in_save_and_import(client, update):
    entry = {**record(), **update}
    assert post(client, 'knowledge', entry).status_code == 422
    assert post(client, 'import', {'entries': [entry]}).status_code == 422
    assert client.get('/api/v3/export').json()['entries'] == []


def test_source_registration_and_review_are_not_certification(client):
    entry = {**record(), 'source_id': 'SYNTHETIC_SOURCE', 'source_title': '模拟来源，非真实文献',
             'source_locator': '模拟页码1（仅测试）', 'source_verification_status': 'submitted', 'specialist_review_status': 'requested'}
    saved = post(client, 'knowledge', entry).json()
    assert saved['source_label'] == '已登记，待核实'
    assert saved['review_label'] == '待审核' and saved['formal_teaching_basis'] is False
    entry.update(version=2, specialist_review_status='rejected', source_verification_status='rejected')
    assert post(client, 'knowledge', entry).status_code == 200
    lesson = client.get('/api/v3/lessons?lesson_id=L01').json()['lessons'][0]
    assert lesson['specialist_review_status'] == 'pending' and lesson['formal_teaching_basis'] == []


def test_archive_roundtrip_and_atomic_conflicts(client):
    entry = record()
    assert post(client, 'knowledge', entry).status_code == 200
    assert post(client, 'knowledge', {**entry, 'version': 2}).status_code == 200
    archive = client.get('/api/v3/export').json()
    fresh = Registry()
    fresh.import_archive(Archive.model_validate(json.loads(json.dumps(archive))))
    assert fresh.export() == archive
    # New entry followed by a conflicting version must roll back the entire batch.
    response = post(client, 'import', {'entries': [{**entry, 'knowledge_id': 'NEW_SYNTHETIC'}, entry]})
    assert response.status_code == 409
    assert client.get('/api/v3/export').json() == archive


def test_concurrent_version_conflict_and_defensive_copies():
    store = Registry()
    def save(_):
        try:
            store.save(Knowledge(**record()))
            return 'saved'
        except RegistryError:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, range(2))) == ['conflict', 'saved']
    exported = store.export()
    exported['entries'][0]['lesson_ids'].clear()
    assert store.search()[0]['lesson_ids'] == ['L01']


def test_registry_lifecycle_and_boundary(client):
    assert post(client, 'knowledge', record()).status_code == 200
    with TestClient(create_console_app(), base_url=ORIGIN, client=('127.0.0.1', 55001)) as fresh:
        for path in ('lessons', 'knowledge', 'export', 'history?knowledge_id=x'):
            assert fresh.get('/api/v3/' + path).status_code == 401
        assert post(fresh, 'knowledge', record()).status_code == 401
        fresh.get('/')
        assert fresh.get('/api/v3/export').json()['entries'] == []
        assert fresh.post('/api/v3/knowledge', json=record()).status_code == 403
        assert fresh.post('/api/v3/import', json={'entries': []}, headers={**HEADERS, 'Origin': 'https://evil.invalid'}).status_code == 403
    assert fresh.app.state.curriculum_registry.export()['entries'] == []
    assert client.get('/api/v3/export', headers={'X-Forwarded-For':'127.0.0.1'}).status_code == 403


def test_json_guards_and_safe_ui(client):
    raw = json.dumps(record()).replace('"version": 1', '"version": 2, "version": 1')
    headers = {**HEADERS, 'Content-Type': 'application/json'}
    assert client.post('/api/v3/knowledge', content=raw, headers=headers).status_code == 422
    assert client.post('/api/v3/import', content='x' * (1024*1024+1), headers=headers).status_code == 413
    assert client.post('/api/v3/import', content='{"entries": [NaN]}', headers=headers).status_code == 422
    script = client.get('/curriculum.js').text
    assert all(x not in script for x in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'localStorage', 'document.cookie'))
    assert 'textContent' in script
    assert 'V3.0 · 8课次课程目录与知识库管理' in client.get('/').text


def test_capacity_limit_is_atomic():
    store = Registry()
    entries = [Knowledge(**{**record(), 'knowledge_id': f'SYNTHETIC_{i}'}) for i in range(200)]
    store.import_archive(Archive(entries=entries))
    with pytest.raises(RegistryError):
        store.save(Knowledge(**{**record(), 'knowledge_id': 'OVERFLOW'}))
    assert len(store.export()['entries']) == 200


def test_export_always_fits_single_ui_import():
    store = Registry()
    for i in range(200):
        candidate = {**record(), 'knowledge_id': f'SYNTHETIC_LARGE_{i}', 'content': '模拟' * 4900}
        try:
            store.save(Knowledge(**candidate))
        except RegistryError:
            break
    else:
        pytest.fail('Expected bounded archive capacity')
    archive = store.export()
    raw = json.dumps(archive, ensure_ascii=False, indent=2).encode()
    assert 0 < len(raw) <= 900 * 1024 < 1024 * 1024
    restored = Registry()
    restored.import_archive(Archive.model_validate_json(raw))
    assert restored.export() == archive


def test_v3_management_not_exposed_to_classroom():
    from integrations.prelesson.classroom import DemoState, create_classroom_app
    origin = 'https://synthetic-v3.trycloudflare.com'
    code = 'synthetic-v3-classroom-code-only'
    state = DemoState(code)
    state.pin(origin)
    app = create_classroom_app(state)
    async def proxy(scope, receive, send):
        if scope['type'] == 'http':
            scope = {**scope, 'scheme': 'http'}
        await app(scope, receive, send)
    headers = {'Origin': origin, 'X-CoachLoop-Console': '1', 'X-Forwarded-Proto': 'https'}
    with TestClient(proxy, base_url=origin, client=('127.0.0.1', 55200), headers=headers) as c:
        assert c.post('/classroom/login', json={'code': code, 'mock_acknowledged': True}).status_code == 200
        for path in ('lessons', 'knowledge', 'history', 'export', 'import'):
            assert c.get('/api/v3/' + path).status_code == 404
            assert c.post('/api/v3/' + path, json={}).status_code == 404
        assert c.get('/curriculum.js').status_code == 404
        assert 'id="curriculum-entry" hidden' in c.get('/').text


@pytest.mark.parametrize('path', ['knowledge', 'import'])
def test_revision_capacity_returns_conflict_without_internal_error(client, path):
    store = client.app.state.curriculum_registry
    versions = [Knowledge(**{**record(), 'version': i}) for i in range(1, 501)]
    store.import_archive(Archive(entries=versions))
    before = store.export()
    entry = {**record(), 'version': 501}
    body = entry if path == 'knowledge' else {'entries': [entry]}
    response = post(client, path, body)
    assert response.status_code == 409
    assert store.export() == before


@pytest.mark.parametrize('field', ['title', 'content', 'source_id', 'source_title', 'source_locator'])
@pytest.mark.parametrize('path', ['knowledge', 'import'])
def test_invalid_unicode_rejected_atomically(client, field, path):
    entry = {**record(), field: 'synthetic-invalid-\ud800'}
    body = entry if path == 'knowledge' else {'entries': [entry]}
    response = client.post('/api/v3/' + path, content=json.dumps(body),
                           headers={**HEADERS, 'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert client.get('/api/v3/export').json()['entries'] == []
