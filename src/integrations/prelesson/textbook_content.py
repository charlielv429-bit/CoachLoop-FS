"""Read-only candidate prose, pinned to P3.4 entries AND original-page reports.

This is a presentation adapter, never a review/approval or new KB import channel.
The additional short paraphrases were checked against the supplied page images;
see docs/textbook-lesson-repair/verification.md. No scans are distributed.
"""
import json
from pathlib import Path

from integrations.curriculum_v3.registry import Knowledge
from integrations.curriculum_v3.review import knowledge_digest
from integrations.curriculum_v3.planning import TeacherEdits

ROOT = Path(__file__).resolve().parents[3]
NOTICE = ('教材原页核对与专业批准分开：以下为待审核教学参考，不是认证技术指导。'
          '五问整体内容曾获专项同学认可，但没有逐条签署材料，不能替代逐项审核。'
          '原PDF页序由用户提供，印刷页码与图注由扫描核对；完整版本信息仍缺版权页。')
FACTS = (
    ('W91', 'K010', ('L04', 'L05', 'L06'), '原PDF91／印刷77／图29（1～5）',
     '王树本以前压步中的左前压步为例，图29展示连续动作；左前方向为逆时针。'
     '正文描述两腿交替向侧蹬冰，右腿越过滑足，再收腿衔接下一次动作。'
     '这是教材动作过程的简述，不把图33的后压步混入本课。'),
    ('W92', 'K018', ('L04', 'L05', 'L06'), '原PDF91–92／印刷77–78／图30、图31',
     '王树本练习方法包括陆地侧上台阶、陆地侧走、冰上扶支撑物原地基本姿势和扶支撑物侧走。'
     '图30记录原地姿势的分解，图31记录冰上侧走；教材把陆地侧上台阶与侧走用于两脚平行移动和压步姿势练习。'
     '这些是原页练习素材，不意味着本班已具备实施或保护条件。'),
    ('W93', 'K018', ('L04', 'L05', 'L06'), '原PDF93／印刷79／图32及练习（5）–（7）',
     '王树本先列单足侧蹬冰沿弧线滑左前外（图32），再列单次压步：蹬冰滑行一次、压步一次。'
     '单次练习段提及在此基础上逐渐完成连续压步；后列节奏变化练习。'
     '教材没有规定L04、L05、L06分课，也没有给出本课程45分钟或技术评分阈值。'),
    ('L39', 'K012', ('L05',), '原PDF39／印刷29／第三节一、前压步（无编号动作图）',
     '李乡状等以左前压步为例：右臂在前、左臂在后，上体向左转；'
     '文字描述右脚内刃侧蹬与左脚外刃滑出的配合，右脚收至左脚前外侧，随后左脚侧蹬、收回衔接。'
     '该页另列刀齿向后蹬冰、两腿屈曲差异造成起伏、身体向弧线内侧倾斜及两脚滑行距离等注意事项。'
     '这是教材描述摘要，不是本系统对学员用刃或动作错误的判断。'),
)


def assemble(registry, lesson_id, base_fields):
    """Latest exact revision/report match only; no authority inferred from content."""
    expected_entries = json.loads((ROOT/'docs/p34/knowledge-revisions.json').read_text())['entries']
    expected_reports = json.loads((ROOT/'docs/p34/source-evidence-reports.json').read_text())['reports']
    expected = {e['knowledge_id']: e for e in expected_entries}
    originals = {r['knowledge_id']: r for r in expected_reports}
    latest = {e['knowledge_id']: e for e in registry.search()}
    reports = registry.evidence_reports()
    facts, missing = [], []
    for fact_id, kid, lessons, locator, text in FACTS:
        if lesson_id not in lessons:
            continue
        current = latest.get(kid)
        original = originals[kid]
        # presented() adds display-only keys; digest only the validated KB fields.
        raw = {k: current[k] for k in Knowledge.model_fields} if current else None
        if (not raw or knowledge_digest(raw) != knowledge_digest(expected[kid])
                or original not in reports):
            missing.append(f'{kid}：本机缺少精确匹配的P3.4 v2及原页声明，或版本/状态已变；该项教材摘要不显示。')
            continue
        facts.append(dict(fact_id=fact_id, knowledge_id=kid, version=current['version'],
                          knowledge_digest=original['knowledge_digest'], source_id=current['source_id'],
                          source_title=current['source_title'], locator=locator, text=text,
                          report_id=original['evidence_id'], artifact_sha256=original['artifact_sha256'],
                          record_kind=current['content_kind'],
                          cross_lesson_background=lesson_id not in current['lesson_ids'],
                          status='pending', system_approved=False))
    if lesson_id not in ('L04', 'L05', 'L06'):
        missing.append('本课已关联候选资料，但现有P3.4原页核验范围未形成与本课目标精确绑定的技术事实摘要；不外推前压步材料。')
    missing += ['逐条专项意见与受控审核决定尚缺；教材事实不自动批准专项实操、示范或技术评价。',
                '现场学情、先修能力、场地容量、装备适配、保护与应急安排尚需教师核实。',
                '本课动作名称与教材术语的对应、练习进阶、纠错适用性及评价量规尚待专项确认。']
    proposals = ['课程自拟：准备9分钟核对资料、装备与先修；基本29分钟用于材料研读和教师选择练习；结束7分钟整理观察与待核问题。不是教材规定课时。',
                 ('课程自拟：学生先辨认动作名称、方向和资料出处，再对照教材列出的练习素材讨论单次与连续的区别；不在条件未核实时转入冰上实操。' if facts else '课程自拟：分组核对本课候选资料的书名、页码与内容性质；缺少原文时只登记待补项，不补造动作练习。')]
    if any(f['knowledge_id']=='K018' for f in facts):
        proposals.append('课程自拟：L04蹬冰、L05完整单次、L06连续练习为本课程安排；K018为course_proposal，教材仅提供练习背景，不是三课次方案原文。')
    fields = dict(base_fields)
    def cite(f):
        return f"[教材事实 {f['fact_id']} / {f['knowledge_id']} v{f['version']} / {f['source_id']} / {f['source_title']} / {f['locator']}；待审核] {f['text']}"
    if facts:
        focus = {'L04':'辨认侧蹬与分解姿势的教材描述；','L05':'对照连续图示与单次练习文字；','L06':'比较单次到连续及变奏练习素材；'}[lesson_id]
        fields['goal_draft'] = ('课程自拟目标草稿：'+focus+'能区分教材前压步与后压步的方向和出处；'
                                '能对照图示与文字说明单次、连续练习的资料关系；能记录仍需专项确认的问题。'
                                '不设技术合格阈值，不代表已掌握动作。')
        fields['action_points'] = '\n'.join(cite(f) for f in facts if f['fact_id'] in ('W91', 'L39')) or cite(facts[0])
        fields['practice_steps'] = ('课程自拟资料研读流程（非教材规定、非冰上实施许可）：\n'
            '准备9分钟：核对教材页码、学情及资源，登记先修缺项。\n'
            '基本29分钟：5分钟识别前/后压步与方向；8分钟读图和动作文字；8分钟比较分解、单次、连续练习素材；8分钟由教师记录拟选练习及其安全、保护和审核前提。条件不足时只做资料讨论。\n'
            '结束7分钟：学生口述资料关系，教师汇总问题、安排待复核任务。\n'
            + '\n'.join(cite(f) for f in facts if f['fact_id'] in ('W92', 'W93')))
        fields['common_errors'] = ('候选观察线索，不是纠错诊断：'+next((cite(f) for f in facts if f['fact_id']=='L39'),
            '现有匹配原页未提供本课可用的错误条目，需专项补充；不根据二维视频推断用刃。'))
    else:
        fields['action_points'] = '资料研读任务：区分课程标题、候选知识摘要与已核对原页。当前没有可精确绑定的本课技术事实，不推断动作步骤。'
        fields['practice_steps'] = ('课程自拟资料准备流程：准备9分钟核对学情、先修和装备清单；基本29分钟分组查找本课候选条目、登记书名页码及缺失原文、列出拟请专项确认的问题；结束7分钟汇总资料任务。专项实操暂缓。')
        fields['common_errors'] = '当前仅记录资料缺口与教师问题，不编造本课技术错误及纠正方法。'
    fields['organization_note'] = '课程自拟：教师组织资料研读与逐项记录；学生按资料对照、观察记录轮换。人数与场地采用演示预设，分组容量沿用系统计算，必须现场确认。'
    fields['resource_note'] = ('资料清单：'+ '；'.join(dict.fromkeys(f"{f['source_title']} {f['locator']}" for f in facts)) if facts else '资料清单：本课关联候选条目；原文与精确定位仍需补齐。') + '\n装备、冰场、师资与先修均待现场确认；扫描原页未随软件发布。'
    fields['safety_notes'] = '保留原系统资源不足和先修不足暂缓机制。未完成专项及现场复核前不把教材练习名称作为冰上操作指令；保护方式、滑行路线、间距和应急规则须由实际教师确定。'
    fields['differentiation_notes'] = '课程自拟：资料辨认组核对名称与页码；比较分析组整理本课候选材料的支持关系；提出问题组记录待专项确认项。不是按技术水平作出的真实学员分组，不指定未经核实的练习剂量。'
    fields['evaluation_observations'] = '课程自拟过程观察：能否找到所引页码、辨明术语和适用课次、说明教材事实与课程安排的区别、列出安全缺项。由教师记录；不作为动作技术评分、用刃判断或官方等级评价。'
    return dict(lesson_id=lesson_id, edits=TeacherEdits.model_validate(fields).model_dump(),
                facts=facts, proposals=proposals, gaps=list(dict.fromkeys(missing)), notice=NOTICE)


def markers_current(edits, reference):
    """Saved prose is historical: stale generated fact markers must not be printed."""
    import re
    markers = set(re.findall(r'教材事实 ([A-Z][0-9]+)', '\n'.join(edits.values())))
    return markers <= {f['fact_id'] for f in reference['facts']}
