"""L05 teacher worksheet. Quoted candidates are never generated technical advice.

Reuses the existing lesson framework/review authority; no AI, scoring or new IO.
"""
from copy import deepcopy

AREA_SPECS = {
    'goal_draft': ('教学目标', '本课聚焦单次完整动作任务：说明任务与课堂约定，形成观察和自评记录。专项动作完成目标由教师核对原文及先修后填写；不设未经核实的次数、角度或速度阈值。'),
    'action_points': ('动作要点', '待专项教师对照正确原页逐项填写；当前不从候选页码或二维骨架推断脚序、内外刃或身体姿态要求。'),
    'practice_steps': ('练习步骤', '准备9分钟核对条件；基本29分钟预留示范核查5分钟与轮换组织24分钟；结束7分钟整理记录。专项步骤由教师填写并复核，未复核不实施。'),
    'common_errors': ('常见错误与待复核问题', '教师填写实际观察到的表现、观察条件及待核实原因；当前不自动诊断技术错误或编造纠错方法。'),
    'safety_notes': ('安全提示', '核对冰面、装备、实际人员与等待区；保留资源暂缓。具体路线、间距、保护和应急处置由现场责任人核定，不给出统一安全数值。'),
    'differentiation_notes': ('分层练习', '支持层：核对未具备的先修条件；巩固层：教师填写当前适用任务；进阶层：仅在专业及现场许可后填写，不自动提高难度。'),
    'evaluation_observations': ('评价观察项', '教师记录任务、观察条件、完成情况与待复核问题，分开记录算法观察和人工判断；不生成官方等级、技术分数或评分阈值。'),
}
GROUPS = {'KB-S':'specialist_knowledge','KB-P':'teaching_progression','KB-E':'evaluation_suggestions'}


def material_card(entry):
    quoted = entry['content'] if entry.get('content_kind') in ('source_summary','course_proposal','catalogue_lead') else ''
    return {**{key:deepcopy(entry[key]) for key in ('knowledge_id','version','category','title','source_id','source_title','source_locator','chapter','content_kind','applicability_limitations','source_verification_status','specialist_review_status','source_conflict_status','source_conflict_note')},
            'candidate_text':quoted, 'citation_status':'registered_not_verified',
            'label':'候选素材引用，不是已核实教材原文或正式技术指导；课程自拟内容不归因于教材原文。',
            'is_formal_guidance':False}


def initialize(plan, entries, location_checks):
    groups={group:[] for group in GROUPS.values()}
    for entry in entries:
        if entry['category'] in GROUPS:groups[GROUPS[entry['category']]].append(material_card(entry))
    plan['l05_teaching_design']={
        'title':'L05 左前交叉步完整动作练习｜教师可审阅教学设计草稿',
        'review_status':'pending_review',
        'notice':'仅为教师工作底稿。下列候选摘要与教师填写内容未经专项审核；不得作为正式技术指导或实施许可。',
        'material_groups':groups,
        'location_checks':location_checks,
        'areas':{}, 'reviewed_citations':[],
        'reference_scope_note':'L05候选与来源定位保留原记录；K010属于L04先修资料定位核查，不作为L05教材引用。',
    }
    apply_teacher_fields(plan)


def apply_teacher_fields(plan):
    if 'l05_teaching_design' not in plan:return
    edits=plan['current_teacher_edits']
    plan['l05_teaching_design']['areas']={key:{'label':label,'text':edits.get(key) or placeholder,
        'origin':'teacher_unverified' if edits.get(key) else 'framework_placeholder',
        'review_status':'pending_review','is_formal_guidance':False}
        for key,(label,placeholder) in AREA_SPECS.items()}


def current_view(plan, registry):
    """Refresh qualifications in exports/history without changing saved versions."""
    if 'l05_teaching_design' not in plan:return plan
    plan=deepcopy(plan)
    design=plan['l05_teaching_design']
    current={entry['knowledge_id']:entry for entry in registry.search(lesson_id='L05')}
    citations={(item['knowledge_id'],item['version']):item for item in plan.get('formal_teaching_evidence',[])}
    stale=[]
    for cards in design['material_groups'].values():
        for card in cards:
            latest=current.get(card['knowledge_id'])
            if latest is None or latest['version']!=card['version']:
                card.update(citation_status='superseded_or_unlinked',candidate_text='',is_formal_guidance=False)
                stale.append({key:card[key] for key in ('knowledge_id','version','source_id','source_locator')})
            elif card['source_conflict_status']=='unresolved':card['citation_status']='locator_conflict_pending'
            elif (card['knowledge_id'],card['version']) in citations:
                card['citation_status']='reviewed_for_draft_only'
                card['label']='本地受控审阅的草稿依据，不等于官方认证；教师填写内容仍待复核。'
            else:card['citation_status']='registered_not_verified'
    design['reviewed_citations']=deepcopy(plan.get('formal_teaching_evidence',[]))
    if plan.get('withdrawn_evidence'):
        withdrawn={(item['knowledge_id'],item['version']) for item in plan['withdrawn_evidence']}
        for cards in design['material_groups'].values():
            for card in cards:
                if (card['knowledge_id'],card['version']) in withdrawn:
                    card.update(citation_status='withdrawn_pending_regeneration',candidate_text='')
    if stale:
        design['stale_reference_audit']=stale
        plan['evidence_status']='requires_regeneration_after_knowledge_change'
        plan['warning']='关联知识版本或课次已变化，已撤下过期素材正文；请重新生成并由教师复核。'
    return plan
