"""Offline artifact generation, not a Coze plugin installer or ZIP exporter."""
import argparse
import json
import html
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_coze_prelesson_plugin import build, checked_origin, RedactedParser
from integrations.three_stage_demo import prelesson, synthetic_video_stages
from agents.postlesson_agent import PostlessonDraft


def main():
    parser = RedactedParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'docs/demo-delivery')
    args = parser.parse_args()
    destination = args.output_dir
    destination.mkdir(parents=True, exist_ok=True)
    plugin = build(checked_origin('https://33vnf9hq7m.coze.site'))
    plugin['info']['description'] += ' 尚未通过线上验证；ZIP扩展包格式未确认。'
    plugin['servers'][0]['description'] = '用户提供的HTTPS地址；尚未通过线上验证'
    features, events, reviews = synthetic_video_stages()
    files = {'prelesson.coze-site.openapi.json': plugin,
        'prelesson.mock-response.json': prelesson().model_dump(mode='json'),
        'postlesson-draft.schema.json': PostlessonDraft.model_json_schema(mode='serialization'),
        'video.synthetic-pipeline.json': dict(data_domain='mock', human_review_performed=False,
            model_inference_performed=False, features=features.model_dump(mode='json'),
            candidates=events.model_dump(mode='json'), pending_reviews=reviews.model_dump(mode='json'))}
    for name, value in files.items():
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    evidence_path = destination / 'three-stage.postgresql.mock-evidence.json'
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text())
        if (evidence.get('kind') != 'synthetic_local_three_stage_evidence' or evidence.get('data_domain') != 'mock'
                or evidence.get('human_review_performed') is not False or evidence.get('production_modified') is not False):
            raise ValueError('Only explicitly synthetic local evidence can be rendered')
        sections = [('课前：七要素草稿', evidence['prelesson']),
            ('课中：合成姿态与候选事件', files['video.synthetic-pipeline.json']),
            ('数据库：导入、幂等与只读查询', evidence['database_results']),
            ('课后：待教师复核的观察与练习草稿', evidence['postlesson'])]
        content = ''.join('<details><summary>' + html.escape(title) + '</summary><pre>'
            + html.escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></details>'
            for title, value in sections)
        page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>CoachLoop-FS 本地合成教学闭环</title>
<style>body{font:17px/1.6 system-ui;max-width:1000px;margin:32px auto;padding:0 20px;background:#f6f8fa;color:#172436}h1{font-size:28px}.notice{background:#fff1cf;border-left:5px solid #a85b00;padding:16px}details{background:white;margin:18px 0;padding:16px;border:1px solid #ccd5df;border-radius:8px}summary{cursor:pointer;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}li{margin:8px 0}</style>
<h1>CoachLoop-FS：本地三阶段合成演示</h1>
<p class="notice">非Coze线上运行；没有真实学生、真实视频或真实人工审核。数据库中的审核动作由受限MOCK测试角色显式模拟，不能作为真实教练确认。课后草稿仍待教师复核。</p>
<ol><li>课前：固定零基础主题，七要素、45分钟、预计负荷、draft与unverified。</li>
<li>课中：40帧合成关键点复用原几何提取/V4检测/V5审核；没有运行MediaPipe。</li>
<li>归档：隔离PostgreSQL16受限角色写入与查询，重复请求使用同一收据。</li>
<li>课后：只读数据库审核状态；confirmed仅为可观测变化，技术错误与技能等级均未评定。</li></ol>
<p>点击下列区块查看本次脱敏测试证据。平台认证、插件安装、Agent绑定和在线知识库均尚未验收。课后最终教师确认与报告归档未实现。</p>'''
        (destination / 'demo.html').write_text(page + content + '</html>\n')
    print('Offline synthetic artifacts generated. No installation, deployment, approval or online verification performed.')


if __name__ == '__main__':
    main()
