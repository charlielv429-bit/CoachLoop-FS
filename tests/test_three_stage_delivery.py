import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_offline_plugin_export_keeps_address_route_and_auth(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/prepare_three_stage_delivery.py'),
        '--output-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0
    plugin = json.loads((tmp_path / 'prelesson.coze-site.openapi.json').read_text())
    assert plugin['servers'][0]['url'] == 'https://33vnf9hq7m.coze.site'
    assert set(plugin['paths']) == {'/api/v1/lesson-plans/draft'}
    assert plugin['paths']['/api/v1/lesson-plans/draft']['post']['security'] == [{'HTTPBearer': []}]
    assert '.invalid' not in json.dumps(plugin)
    assert '尚未通过线上验证' in plugin['info']['description']
    assert not list(tmp_path.glob('*.zip'))


def test_evidence_viewer_escapes_text_and_makes_no_external_requests(tmp_path):
    marker = '<script>synthetic()</script>'
    evidence = dict(kind='synthetic_local_three_stage_evidence', data_domain='mock',
        human_review_performed=False, production_modified=False,
        prelesson={'synthetic_text': marker}, database_results={}, postlesson={})
    (tmp_path / 'three-stage.postgresql.mock-evidence.json').write_text(json.dumps(evidence))
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/prepare_three_stage_delivery.py'),
        '--output-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0
    page = (tmp_path / 'demo.html').read_text()
    assert marker not in page and '&lt;script&gt;' in page
    assert "default-src 'none'" in page and '<script' not in page
    assert '非Coze线上运行' in page and '没有真实学生' in page
