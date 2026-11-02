"""Build a review-only course pack via existing local APIs in a temporary SQLite DB.

Never reads/writes the user's KB, stores real feedback, or approves knowledge.
The optional DOCX renderer uses an already installed python-docx; no app dependency.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.registry import Archive
from integrations.curriculum_v3.review import EvidenceBundle, knowledge_digest
from integrations.prelesson.console import create_console_app

ORIGIN = 'http://127.0.0.1:8767'
HEADERS = {'Origin': ORIGIN, 'X-CoachLoop-Console': '1'}
PACKETS = ['docs/p32-input/p32-knowledge-import.json', 'docs/p32-input/p32-evidence-reports.json',
           'docs/p34/knowledge-revisions.json', 'docs/p34/source-evidence-reports.json']
NOTICE = '待审核教案框架；仅供课程展示与教师修改，不是专项批准、实际授课或学生测评记录。'
CONDITIONS = dict(class_label='合成课程验收情境（非真实班级）', student_count=20, skill_level='初级',
                  coach_count=2, teacher_count=1, usable_area_m2=200., declared_practice_capacity=10,
                  equipment_sets=20, safe_waiting_area=True, venue_conditions='合成场地，待现场确认',
                  equipment_conditions='合成装备，待现场确认')
FOCUS = {
    'L01': '明确课程参与约定，列出装备和场地检查项；专项入门动作由教师补齐。',
    'L02': '区分本课滑行与停止的学习任务，建立问题记录；具体停止技术待专项确认。',
    'L03': '说明本课单足平衡观察任务，记录自评问题；不从二维观察推断真实重心。',
    'L04': '识别本课蹬冰学习任务与K010原页定位，提出待教师解释的问题。',
    'L05': '说明单次完整动作的学习任务，区分前压步、后压步与课程自拟安排，建立观察记录；动作达成标准待专项补齐。',
    'L06': '说明连续练习与L05单次任务的课程差别，列出进入条件待教师确认。',
    'L07': '梳理第一组完整步法任务和材料缺项；具体步法组合由教师核定。',
    'L08': '梳理第二组任务与课程回顾问题，分开记录自评、教师意见和待核事项，不生成官方等级。',
}


def read_packet(path):
    return json.loads((ROOT / path).read_text())


def load_store(store):
    store.import_archive(Archive.model_validate(read_packet(PACKETS[0])))
    store.save_reports(EvidenceBundle.model_validate(read_packet(PACKETS[1])).reports)
    store.import_archive(Archive.model_validate(read_packet(PACKETS[2])))
    store.save_reports(EvidenceBundle.model_validate(read_packet(PACKETS[3])).reports)


def checked(response):
    if response.status_code != 200:
        raise RuntimeError(f'Course acceptance API failed: {response.status_code}')
    return response.json()


def collect():
    """Actual generate/edit/history/export; raw exports remain local-only to caller."""
    summaries, exports = [], {}
    with tempfile.TemporaryDirectory(prefix='coachloop-course-') as directory:
        store = SQLiteRegistry(Path(directory) / 'kb')
        load_store(store)
        before = store.export_full()
        with TestClient(create_console_app(knowledge_store=store), base_url=ORIGIN,
                        client=('127.0.0.1', 55300)) as client:
            client.get('/')
            lessons = checked(client.get('/api/v3/lessons'))['lessons']
            assert [l['lesson_id'] for l in lessons] == list(FOCUS)
            for lesson in lessons:
                kid = lesson['lesson_id']
                plan = checked(client.post('/api/v3/plans/draft', json=dict(
                    lesson_id=kid, prerequisites_confirmed=False, conditions=deepcopy(CONDITIONS)), headers=HEADERS))
                fields = dict(goal_draft='课程自拟目标草稿（待审核）：' + FOCUS[kid],
                              organization_note='课程展示设计，非实际授课；先修与专项未确认前仅组织资料核对和口头讨论。',
                              resource_note='实际冰面、装备、路线、等待区、保护及应急制度待现场教师确认。')
                if kid == 'L05':
                    fields.update(action_points='待专项逐条填写。对照K011 v2／B02／原PDF91印刷77图29，及K012 v2／B03／原PDF39印刷29；不自动生成脚序、用刃或纠错指令。',
                                  practice_steps='准备9分钟核查；基本29分钟资料核对5分钟、讨论与待定组织窗口24分钟；结束7分钟整理。专项未审阅前不实施冰上练习。',
                                  common_errors='由专项教师逐项填写观察表现、教材定位、适用条件及修改意见；不自动诊断。',
                                  safety_notes='现场教师核对装备、场地、先修、人员、保护和应急安排；保留所有暂缓提示。',
                                  differentiation_notes='支持／巩固／进阶的任务与进入条件由教师填写；K018 v2是自拟课次安排，不作为教材规定。',
                                  evaluation_observations='教师评价与反馈待填写；没有实际课堂或学生测评数据。只记录观察项、待核问题与改进建议，不给分、不作通过结论。')
                plan = checked(client.post('/api/v3/plans/edit', json=dict(
                    plan_id=plan['plan_id'], expected_version=1, **fields), headers=HEADERS))
                exported = checked(client.get('/api/v3/plans/export', params={'plan_id': plan['plan_id']}))
                history = checked(client.get('/api/v3/plans/history', params={'plan_id': plan['plan_id']}))['versions']
                assert [p['version'] for p in history] == [1, 2]
                assert exported == plan and exported['version'] == 2
                assert [p['minutes'] for p in exported['teaching_flow']['phases']] == [9, 29, 7]
                assert exported['technical_guidance'] == exported['formal_teaching_evidence'] == []
                assert exported['organization']['status'] == 'withheld'
                references = []
                for entry in lesson['linked_knowledge']:
                    # The archive preserves strict source fields without presentation-only labels.
                    source = next(e for e in before['archive']['entries'] if e['knowledge_id'] == entry['knowledge_id'] and e['version'] == entry['version'])
                    references.append({k: entry[k] for k in ('knowledge_id', 'version', 'category', 'source_id', 'source_title', 'source_locator', 'content_kind', 'source_verification_status', 'specialist_review_status')})
                    references[-1]['knowledge_digest'] = knowledge_digest(source)
                summaries.append(dict(lesson=exported['lesson'], notice=NOTICE, plan_version=2,
                    phase_minutes=[9, 29, 7], phases=exported['teaching_flow']['phases'],
                    teacher_fields=exported['current_teacher_edits'], conditions=exported['conditions'],
                    execution_status=exported['execution_status'], organization=exported['organization'],
                    preparation_checklist=exported['preparation_checklist'], staff_tasks=exported['staff_tasks'],
                    missing_materials=exported['missing_materials'], review_checklist=exported['teacher_review_checklist'],
                    references=references, technical_guidance=[], controlled_citations=[],
                    feedback_status='not_received', system_review_status='pending'))
                exports[kid] = exported
        # Console shutdown closes its injected connection; reopen only this temporary DB.
        store = SQLiteRegistry(Path(directory) / 'kb')
        assert store.export_full() == before
        store.close()
    return summaries, exports


def render_lesson(item):
    lesson = item['lesson']; fields = item['teacher_fields']
    lines = [f"# {lesson['lesson_id']} {lesson['title']}｜45分钟教师修改草稿", '', NOTICE,
             '', '本稿为现有HTTP接口生成、编辑至版本2及导出的阅读投影，不是API导入格式。班级与资源为合成验收情境；没有真实教师意见或测评。',
             '', '## 目标草稿', '', fields['goal_draft'], '', '## 课堂条件与资源', '',
             '展示条件：20人、初级、2名专项教练、1名体育教师、200平方米、声明容量10、装备20套；均不是现场核定值。先修未确认，冰上暂缓。', '', fields['resource_note'], '',
             '准备检查：' + '；'.join(item['preparation_checklist']), '', '## 45分钟组织框架', '',
             '| 阶段 | 分钟 | 当前可用安排 |', '|---|---:|---|']
    for name, phase in zip(('准备', '基本', '结束'), item['phases']):
        lines.append(f"| {name} | {phase['minutes']} | {phase['content']} |")
    lines += ['', '教师：核查先修、资源、等待区和职责，记录待核问题；学生：参与资料讨论、复述任务及整理问题。专项未审核前不开展动作实操或技术评价。',
              '', '组织说明：' + fields['organization_note'], '', '## 专项内容与分层待填', '',
              '动作要点：________；练习步骤与进入条件：________；常见错误及纠错依据：________。', '',
              '安全与保护：________；支持层：________；巩固层：________；进阶层及允许条件：________。',
              '', '以上须由专项及现场教师填写后复核；课程展示草稿不补造技术标准。', '', '## 知识登记与审核状态', '',
              '下列为候选知识定位，不是正式教学引用；系统受控引用为空。']
    for ref in item['references']:
        lines += ['', f"- {ref['knowledge_id']} v{ref['version']}／{ref['source_id']}／{ref['source_title']}：{ref['source_locator']}。性质：{ref['content_kind']}；来源状态{ref['source_verification_status']}，专项状态{ref['specialist_review_status']}。"]
    lines += ['', '## 教师评价与反馈（空白）', '', '实际观察与条件：________；教材支持与待核问题：________；修改建议：________；下一步：________。',
              '', '填写者及实际填写日期由本人填写：________。当前未收到反馈；没有实际授课或学生评分。填写不改变系统pending状态。',
              '', '## 待审缺项', '']
    lines += ['- ' + text for text in item['missing_materials']]
    lines += ['', '## 教师复核清单', ''] + ['- [ ] ' + text for text in item['review_checklist']]
    return '\n'.join(lines) + '\n'


def render_docx(source, target):
    from docx import Document
    from docx.oxml.ns import qn
    document = Document()
    normal = document.styles['Normal']
    normal.font.name = 'Arial'
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    document.core_properties.title = 'L05教师送审定稿（未批准）'
    document.core_properties.author = ''
    table = None
    for line in source.splitlines():
        if not line:
            table = None
            continue
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if all(set(cell) <= set('-: ') for cell in cells):
                continue
            if table is None:
                table = document.add_table(rows=0, cols=len(cells))
                table.style = 'Light Shading Accent 1'
            row = table.add_row().cells
            for cell, text in zip(row, cells):
                cell.text = text
        elif line.startswith('#'):
            table = None
            level = len(line) - len(line.lstrip('#'))
            document.add_heading(line[level:].strip(), level=min(level, 3))
        else:
            table = None
            document.add_paragraph(line)
    document.save(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory, never overwritten')
    parser.add_argument('--docx', action='store_true', help='Also render editable L05 DOCX using installed python-docx')
    args = parser.parse_args()
    if args.output_dir.exists(): parser.error('Output must be a new directory; no overwrite')
    summaries, exports = collect()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for item in summaries:
        kid = item['lesson']['lesson_id']
        (args.output_dir / f'{kid}-draft.md').write_text(render_lesson(item))
    manifest = dict(schema_version='course-mvp-review-pack-v1', notice=NOTICE,
                    scope='Existing HTTP outputs projected for review; not a KB archive or platform import format',
                    synthetic_conditions=True, teacher_feedback_received=False, platform_uploaded=False,
                    knowledge_counts=dict(ids=23, versions=27, reports=50, decisions=0),
                    source_packet_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PACKETS}, lessons=summaries)
    (args.output_dir / 'course-inventory.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    # Actual exports include random IDs/times; local regeneration only, never presented as actual teacher records.
    raw = args.output_dir / 'local-api-exports'; raw.mkdir()
    for kid, plan in exports.items():
        (raw / f'{kid}.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    if args.docx:
        source = ROOT / 'docs/course-mvp/L05-teacher-review.md'
        render_docx(source.read_text(), args.output_dir / 'L05-teacher-review.docx')
    print('8 lessons: HTTP generate/edit/history/export PASS; 9+29+7=45; pending; KB unchanged; no platform upload')


if __name__ == '__main__':
    main()
