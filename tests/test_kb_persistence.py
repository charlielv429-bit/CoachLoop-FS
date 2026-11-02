"""Explicitly synthetic local SQLite fixtures; never professional source material."""
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from urllib.error import URLError

from fastapi.testclient import TestClient
import pytest
from integrations.curriculum_v3.persistence import SQLiteRegistry, PersistenceError, review_materials
from integrations.curriculum_v3.registry import Knowledge, Archive, RegistryError
from integrations.prelesson.console import create_console_app

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='http://127.0.0.1:8767'
HEADERS={'Origin':ORIGIN,'X-CoachLoop-Console':'1'}


def entry(**updates):
    return Knowledge(**{**dict(knowledge_id='SYNTHETIC_ONLY',category='KB-S',title='模拟测试资料（非专业知识）',content='合成内容，仅用于测试',lesson_ids=['L05'],version=1),**updates})


def app_client(directory):
    return TestClient(create_console_app(knowledge_store=SQLiteRegistry(directory)),base_url=ORIGIN,client=('127.0.0.1',55001))


def test_reopen_sources_versions_and_all_categories(tmp_path):
    directory=tmp_path/'kb'
    store=SQLiteRegistry(directory)
    for category in ('KB-S','KB-P','KB-A','KB-E'):
        store.save(entry(knowledge_id=category,category=category))
    store.save(entry(knowledge_id='KB-S',version=2,source_id='SYNTHETIC',source_title='模拟来源非文献',source_locator='模拟页码1',source_verification_status='submitted'))
    before=store.export();store.close()
    restored=SQLiteRegistry(directory)
    assert restored.export()==before
    assert [x['version'] for x in restored.history('KB-S')]==[1,2]
    assert restored.search(category='KB-S',lesson_id='L05',keyword='模拟')[0]['source_locator']=='模拟页码1'
    assert len(restored.search())==4
    assert (directory.stat().st_mode & 0o777)==0o700
    assert (restored.path.stat().st_mode & 0o777)==0o600
    restored.close()


def test_http_restart_retains_only_shared_kb(tmp_path):
    with app_client(tmp_path/'kb') as client:
        client.get('/')
        assert client.post('/api/v3/knowledge',json=entry().model_dump(),headers=HEADERS).status_code==200
    with app_client(tmp_path/'kb') as client:
        assert client.get('/api/v3/export').status_code==401
        client.get('/')
        assert client.get('/api/v3/export').json()['entries']==[entry().model_dump()]
        assert 'SQLite' in client.get('/api/v3/lessons').json()['storage']


def test_backup_restore_atomic_conflict_and_invalid_status(tmp_path):
    source=SQLiteRegistry(tmp_path/'source')
    source.save(entry());source.save(entry(version=2,content='模拟第二版'))
    backup=json.loads(json.dumps(source.export()))
    target=SQLiteRegistry(tmp_path/'target')
    target.import_archive(Archive.model_validate(backup))
    assert target.export()==backup
    before=target.export()
    archive=Archive(entries=[entry(knowledge_id='NEW_SYNTHETIC'),entry()])
    with pytest.raises(RegistryError):target.import_archive(archive)
    assert target.export()==before
    with pytest.raises(ValueError):Archive.model_validate({'entries':[{**entry().model_dump(),'specialist_review_status':'approved'}]})
    assert target.export()==before
    packet=review_materials(target)
    assert packet['archive']==backup and packet['status']=='pending_review'
    with pytest.raises(ValueError):Archive.model_validate(packet)
    source.close();target.close()


def test_multiple_instances_and_concurrent_conflict(tmp_path):
    left=SQLiteRegistry(tmp_path/'kb');right=SQLiteRegistry(tmp_path/'kb')
    def save(store):
        try:store.save(entry());return 'saved'
        except RegistryError:return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save,[left,right]))==['conflict','saved']
    assert left.export()==right.export()
    right.save(entry(version=2))
    assert len(left.history(entry().knowledge_id))==2
    left.close();right.close()


def test_database_failure_rolls_back_whole_import(tmp_path):
    store=SQLiteRegistry(tmp_path/'kb');store.save(entry());before=store.export()
    # Simulated SQLite failure after the first insert, not an implementation mock.
    store._connection.execute("CREATE TRIGGER simulate_failure BEFORE INSERT ON revisions WHEN NEW.knowledge_id='FAIL_SYNTHETIC' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(PersistenceError):
        store.import_archive(Archive(entries=[entry(knowledge_id='NEW_SYNTHETIC'),entry(knowledge_id='FAIL_SYNTHETIC')]))
    assert store.export()==before
    store.close()


@pytest.mark.parametrize('mode',[0o755,0o777])
def test_refuses_nonprivate_directory(tmp_path,mode):
    directory=tmp_path/'kb';directory.mkdir(mode=mode);directory.chmod(mode)
    with pytest.raises(PersistenceError):SQLiteRegistry(directory)


def test_symlink_permissions_unknown_schema_and_corruption(tmp_path):
    real=tmp_path/'real';real.mkdir(mode=0o700)
    link=tmp_path/'link';link.symlink_to(real,target_is_directory=True)
    with pytest.raises(PersistenceError):SQLiteRegistry(link)
    store=SQLiteRegistry(real);store.save(entry());store.close()
    database=real/'knowledge.sqlite3'
    database.chmod(0o644)
    with pytest.raises(PersistenceError):SQLiteRegistry(real)
    database.chmod(0o600)
    conn=sqlite3.connect(database);conn.execute('PRAGMA user_version=99');conn.close()
    with pytest.raises(PersistenceError):SQLiteRegistry(real)
    assert sqlite3.connect(database).execute('SELECT COUNT(*) FROM revisions').fetchone()[0]==1
    corrupt=tmp_path/'corrupt';corrupt.mkdir(mode=0o700)
    file=corrupt/'knowledge.sqlite3';file.write_bytes(b'synthetic corrupt file');file.chmod(0o600)
    with pytest.raises(PersistenceError):SQLiteRegistry(corrupt)
    assert file.read_bytes()==b'synthetic corrupt file'


def test_append_only_and_invalid_stored_record_fail_closed(tmp_path):
    directory=tmp_path/'kb';store=SQLiteRegistry(directory);store.save(entry())
    with pytest.raises(sqlite3.DatabaseError):store._connection.execute('DELETE FROM revisions')
    store.close()
    connection=sqlite3.connect(directory/'knowledge.sqlite3')
    forged={**entry().model_dump(),'knowledge_id':'FORGED_SYNTHETIC','source_verification_status':'verified'}
    connection.execute('INSERT INTO revisions VALUES(?,?,?)',('FORGED_SYNTHETIC',1,json.dumps(forged)))
    connection.commit();connection.close()
    with pytest.raises(PersistenceError):SQLiteRegistry(directory)


def test_http_import_guards_and_review_export(tmp_path):
    with app_client(tmp_path/'kb') as client:
        client.get('/')
        assert client.post('/api/v3/knowledge',json=entry().model_dump(),headers=HEADERS).status_code==200
        before=client.get('/api/v3/export').json()
        invalids=[{'entries':[{**entry().model_dump(),'version':2,'specialist_review_status':'certified'}]},
                  {'entries':[{**entry().model_dump(),'source_verification_status':'verified'}]},
                  {'entries':[{**entry().model_dump(),'version':2,'content':'<script>bad</script>'}]},
                  {'entries':[{**entry().model_dump(),'version':True}]}]
        for value in invalids:
            assert client.post('/api/v3/import',json=value,headers=HEADERS).status_code==422
        assert client.post('/api/v3/import',json=before,headers=HEADERS).status_code==409
        assert client.post('/api/v3/import',content='x'*(1024*1024+1),headers={**HEADERS,'Content-Type':'application/json'}).status_code==413
        raw='{"entries":[],"entries":[]}'
        assert client.post('/api/v3/import',content=raw,headers={**HEADERS,'Content-Type':'application/json'}).status_code==422
        assert client.get('/api/v3/export').json()==before
        packet=client.get('/api/v3/review-materials').json()
        assert packet['archive']==before and packet['status']=='pending_review'
        assert client.post('/api/v3/import',json=packet,headers=HEADERS).status_code==422


def test_cli_backup_recovery_private_files_and_no_overwrite(tmp_path):
    directory=tmp_path/'kb';store=SQLiteRegistry(directory);store.save(entry());before=store.export();store.close()
    def run(directory,action,file):
        return subprocess.run([sys.executable,'-B',str(ROOT/'scripts/manage_local_knowledge.py'),'--kb-dir',str(directory),action,'--file',str(file)],capture_output=True,text=True,timeout=10)
    backup=tmp_path/'synthetic.kb-backup.json'
    assert run(directory,'backup',backup).returncode==0
    assert backup.stat().st_mode & 0o777==0o600
    assert json.loads(backup.read_text())==before
    assert run(directory,'backup',backup).returncode==1
    target=tmp_path/'restore'
    assert run(target,'restore',backup).returncode==0
    assert run(target,'restore',backup).returncode==1
    restored=SQLiteRegistry(target);assert restored.export()==before;restored.close()
    review=tmp_path/'synthetic.kb-review.json'
    assert run(directory,'review',review).returncode==0
    assert run(target,'restore',review).returncode==1


def test_real_launcher_process_restart_persists_knowledge(tmp_path):
    directory=tmp_path/'kb'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    def launch(write):
        process=subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/run_prelesson_console.py'),'--port',str(port),'--kb-dir',str(directory)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            for _ in range(150):
                assert process.poll() is None,'Synthetic launcher test exited'
                try:
                    with opener.open(base+'/health',timeout=1):break
                except (URLError,ConnectionError,TimeoutError):time.sleep(.1)
            else:pytest.fail('Launcher startup timed out')
            with opener.open(base+'/'):pass
            if write:
                request=urllib.request.Request(base+'/api/v3/knowledge',data=json.dumps(entry().model_dump()).encode(),headers={'Origin':base,'Content-Type':'application/json','X-CoachLoop-Console':'1'})
                with opener.open(request) as response:assert response.status==200
            with opener.open(base+'/api/v3/export') as response:return json.load(response)
        finally:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
    assert launch(True)==launch(False)=={'schema_version':'coachloop-kb-v3.0','entries':[entry().model_dump()]}


def test_shared_persistent_knowledge_never_contains_private_plan_edits(tmp_path):
    with app_client(tmp_path/'kb') as client:
        client.get('/')
        assert client.post('/api/v3/knowledge',json=entry().model_dump(),headers=HEADERS).status_code==200
        conditions=dict(student_count=10,skill_level='初级',coach_count=1,teacher_count=1,usable_area_m2=100.,declared_practice_capacity=10,equipment_sets=10,safe_waiting_area=True,venue_conditions='模拟场地',equipment_conditions='模拟装备')
        plan=client.post('/api/v3/plans/draft',json={'lesson_id':'L05','conditions':conditions},headers=HEADERS).json()
        result=client.post('/api/v3/plans/edit',json={'plan_id':plan['plan_id'],'expected_version':1,'resource_note':'SYNTHETIC_PRIVATE_NOTE_ONLY'},headers=HEADERS)
        assert result.status_code==200
        other=TestClient(client.app,base_url=ORIGIN,client=('127.0.0.1',55002));other.get('/')
        # Knowledge is explicitly shared. Private plans are independently owned.
        assert other.get('/api/v3/export').json()['entries']==[entry().model_dump()]
        for path in ('export','history'):
            response=other.get('/api/v3/plans/'+path,params={'plan_id':plan['plan_id']})
            assert response.status_code==404 and 'SYNTHETIC_PRIVATE_NOTE_ONLY' not in response.text
        assert other.post('/api/v3/plans/edit',json={'plan_id':plan['plan_id'],'expected_version':2},headers=HEADERS).status_code==409
        assert 'SYNTHETIC_PRIVATE_NOTE_ONLY' not in other.get('/api/v3/review-materials').text
        store=client.app.state.curriculum_registry
        rows=store._connection.execute('SELECT payload FROM revisions').fetchall()
        assert 'SYNTHETIC_PRIVATE_NOTE_ONLY' not in str(rows)
    with app_client(tmp_path/'kb') as restarted:
        restarted.get('/')
        assert restarted.get('/api/v3/plans/export',params={'plan_id':plan['plan_id']}).status_code==404
        assert len(restarted.get('/api/v3/export').json()['entries'])==1


def test_storage_errors_are_redacted_and_fail_closed(tmp_path):
    with app_client(tmp_path/'kb') as client:
        client.get('/')
        client.app.state.curriculum_registry.close()
        response=client.get('/api/v3/export')
        assert response.status_code==503
        assert str(tmp_path) not in response.text and 'Traceback' not in response.text
        assert response.headers['cache-control']=='no-store'


def test_local_data_and_backups_are_gitignored():
    for name in ('.local/coachloop-kb/knowledge.sqlite3','private.sqlite3-journal','local.kb-backup.json','offline.kb-review.json'):
        result=subprocess.run(['git','check-ignore','--no-index',name],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0,name


def test_oversized_stored_payload_refused_before_materializing_json(tmp_path):
    directory=tmp_path/'kb';store=SQLiteRegistry(directory);store.close()
    connection=sqlite3.connect(directory/'knowledge.sqlite3')
    connection.execute('INSERT INTO revisions VALUES(?,?,?)',('SYNTHETIC_LARGE',1,'x'*(128*1024+1)))
    connection.commit();connection.close()
    with pytest.raises(PersistenceError):SQLiteRegistry(directory)
