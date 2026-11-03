"""Teacher-facing adapters only: bundled pending seed, readable guarded printing.

No new authority, schema, inference or caller-supplied initialization archive.
"""
import hashlib
from html import escape
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import field_validator
from starlette.responses import HTMLResponse
from integrations.prelesson.api import PrelessonRoute
from integrations.prelesson.adaptive_api import local_session
from integrations.curriculum_v3.api import plan_owner
from integrations.curriculum_v3.registry import Strict, Archive, RegistryError
from integrations.curriculum_v3.review import EvidenceBundle
from integrations.curriculum_v3.full_backup import snapshot
from integrations.curriculum_v3.persistence import SQLiteRegistry
from integrations.curriculum_v3.planning import guard_current_evidence
from integrations.local_video.api import owner as video_owner
from integrations.prelesson.textbook_content import assemble, markers_current

ROOT=Path(__file__).resolve().parents[3]
READ_PATHS={'/api/v4/catalogue','/api/v4/knowledge-status','/api/v4/print-plan','/api/v4/print-loop'}
WRITE_PATHS={'/api/v4/initialize'}
CONTENT_KINDS={'course_proposal':'课程自拟建议（非教材原文）','source_summary':'候选来源摘要','catalogue_lead':'目录线索','unspecified':'内容性质待确认'}
LABELS={'goal_draft':'教学目标','action_points':'教学重点与难点（专项待审核）','practice_steps':'具体教学流程与练习步骤',
        'organization_note':'练习组织','resource_note':'教学准备与资源','common_errors':'待复核问题',
        'safety_notes':'安全注意事项','differentiation_notes':'分层组织','evaluation_observations':'评价观察项'}


class Consent(Strict):
    acknowledged: bool

    @field_validator('acknowledged')
    @classmethod
    def required(cls,value):
        if value is not True:raise ValueError('Explicit pending knowledge initialization consent required')
        return value


def bundled():
    manifest=json.loads((ROOT/'docs/course-mvp/course-inventory.json').read_text())
    packets={}
    for path,sha in manifest['source_packet_sha256'].items():
        if path not in ('docs/p32-input/p32-knowledge-import.json','docs/p32-input/p32-evidence-reports.json',
                        'docs/p34/knowledge-revisions.json','docs/p34/source-evidence-reports.json'):
            raise RegistryError('Unexpected bundled source')
        raw=(ROOT/path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise RegistryError('Bundled source integrity mismatch')
        packets[path]=json.loads(raw)
    entries=Archive.model_validate(packets['docs/p32-input/p32-knowledge-import.json']).entries+Archive.model_validate(packets['docs/p34/knowledge-revisions.json']).entries
    reports=EvidenceBundle.model_validate(packets['docs/p32-input/p32-evidence-reports.json']).reports+EvidenceBundle.model_validate(packets['docs/p34/source-evidence-reports.json']).reports
    if len(entries)!=27 or len({e.knowledge_id for e in entries})!=23 or len(reports)!=50:
        raise RegistryError('Unexpected bundled counts')
    if any(e.source_verification_status!='pending' or e.specialist_review_status!='pending' for e in entries):
        raise RegistryError('Bundled entries must remain pending')
    return snapshot({'schema_version':'coachloop-kb-full-v1','archive':Archive(entries=entries).model_dump(),
                     'evidence_reports':[r.model_dump() for r in reports],'review_decisions':[]},None)


def counts(store):
    if not isinstance(store,SQLiteRegistry):
        return {'persistent':False,'can_initialize':False,'knowledge_ids':len(store.search()),'versions':len(store.export()['entries']),'reports':0,'decisions':0}
    return {'persistent':True,**store.initialization_counts()}


def document(title,sections):
    content=''.join('<section><h2>'+escape(heading)+'</h2>'+body+'</section>' for heading,body in sections)
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+escape(title)+'</title><link rel="stylesheet" href="/teacher-print.css"><script src="/teacher-print.js" defer></script></head><body><header><button id="print">打印／在系统打印中存储为PDF</button><p>尚未生成PDF文件。请使用浏览器打印；取消打印不会保存文件。</p></header><article><h1>'+escape(title)+'</h1><p class="notice">待审核工作文稿；不是正式专项指导、专业认证或实施许可。离线副本不会自动随证据撤回更新，使用前须重新核对。</p>'+content+'</article></body></html>'


def unavailable_print(status=409):
    return HTMLResponse('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>请重新核对文稿</title><link rel="stylesheet" href="/teacher-print.css"></head><body><h1>这份文稿暂时无法打开</h1><p>版本、证据、会话或运行条件已变化。请返回本机工作台，先保存并重新核对，再打印。没有生成PDF或Word文件。</p><a href="/">返回教师工作台</a></body></html>',status_code=status)


def para(value):return '<p>'+escape(str(value)).replace('\n','<br>')+'</p>'


def display_warning(plan):
    if "缺少正式专项依据" in plan["warning"]:
        return "待审核教学草稿：原页核对、课程建议及现场缺项分列如下。逐条专项审核尚未完成，专项实操、示范与技术评价继续暂缓。"
    return plan["warning"]


def print_plan(plan, reference=None):
    edits=plan['current_teacher_edits']
    sections=[('课次与状态',para(plan['lesson']['title']+' · 45分钟 · 文稿版本'+str(plan['version']))+para(display_warning(plan)))]
    if reference:
        sections.append(('教材证据说明',para(reference['notice'])))
        sections.append(('教材直接支持的事实（摘要，待审核）',''.join(para(f"{f['knowledge_id']} v{f['version']} / {f['source_id']} / {f['source_title']} / {f['locator']} / 声明 {f['report_id']} / "+('跨课次背景；' if f['cross_lesson_background'] else '')+f['text']) for f in reference['facts']) or para('本机尚无精确匹配的本课原页摘要。')))
        sections.append(('基于教材编排的课程建议（非原文）',''.join(para(t) for t in reference['proposals'])))
        sections.append(('分项证据与现场缺口',''.join(para(t) for t in reference['gaps'])))
    for key,label in LABELS.items():
        text=edits.get(key) or (plan['objective_draft'] if key=='goal_draft' else '待教师填写并复核；不自动补造专项动作、纠错或评价阈值。')
        sections.append((label,para(text)))
    sections.append(('45分钟教学组织',''.join('<h3>'+escape(name)+' · '+str(p['minutes'])+'分钟</h3>'+para(p['content']) for name,p in zip(('准备','基本','结束'),plan['teaching_flow']['phases']))))
    sections.append(('资源与先修限制',''.join(para(t) for t in plan['organization']['reasons'])+para('所有预设与教师自报条件均须现场核实，不证明安全容量。')))
    sections.append(('候选知识来源（不作为正式技术指导）',''.join(para(f"{r['knowledge_id']} v{r['version']} / {r['source_id']} / {r['source_title']} / {r['source_locator']} / 系统来源核验与专项状态待审核；性质：{CONTENT_KINDS.get(r['content_kind'],'待确认')}") for r in plan['knowledge_inventory']) or para('尚无关联知识，待补充。')))
    sections.append(('教师修改建议与记录',''.join(para(t) for t in plan['teacher_review_checklist'])+para('历史版本：'+str(plan['version'])+'；教师填写均待复核，不认证身份。')))
    return document(plan['lesson']['title']+'｜待审核教案',sections)


def print_loop(value):
    q=value['analysis']['quality']
    quality=('合成关键点演示，未调用MediaPipe；质量比例均为构造值。' if value['is_mock'] else f"本机分析共{q.get('source_frames','待核')}帧，检出{q.get('detected_frames','待核')}帧；检出不等于几何有效或技术正确。")
    sections=[('当前状态',para(value['review_label'])+para(value['warning'])+para('匿名代号 '+value['learner_code']+'；闭环版本'+str(value['version']))),
              ('教师观察（未认证文字）',para(value['observation'] or '待填写')),('下次复练任务（待专业与安全确认）',para(value['practice_task'] or '待填写')),
              ('质量与不可判断内容',para(quality)+para('不判断用刃、真实重心、技术合格或官方评分。')+para('候选事件数：'+str(len(value['analysis']['candidate_changes'])))),
              ('候选变化',''.join(para(f"{r['candidate']['start_time_ms']/1000:g}–{r['candidate']['end_time_ms']/1000:g}秒；本地状态："+{'pending':'待复核','confirmed':'报告可观察变化，非技术错误','normal_movement':'报告为正常动作，未认证','tracking_error':'跟踪误差','uncertain':'证据不足'}.get(r['status'],'待复核')+'；备注：'+r['note']) for r in value['analysis']['candidate_changes'])),
              ('确认与历史',para('当前确认有效：'+('本地自报确认，身份未认证' if value['confirmation_current'] else '否，待教师确认'))+para('保存版本数：'+str(len(value['history'])))+para(value['lifecycle']))]
    return document('L05教师反馈报告',sections)


def create_router(registry,plans,loops):
    router=APIRouter(route_class=PrelessonRoute,dependencies=[Depends(local_session)])

    @router.get('/api/v4/catalogue')
    def catalogue():
        source=json.loads((ROOT/'docs/course-mvp/course-inventory.json').read_text())
        return {'drafts':[assemble(registry,item['lesson']['lesson_id'],item['teacher_fields']) for item in source['lessons']],
                'notice':'已有课程自拟草稿，所有文字待审核；不是实际教师意见。'}

    @router.get('/api/v4/knowledge-status')
    def status():return counts(registry)

    @router.post('/api/v4/initialize')
    def initialize(body:Consent):
        if not isinstance(registry,SQLiteRegistry):raise HTTPException(409,'本地SQLite未启用，不能初始化。')
        try:
            registry.restore_full(bundled())
            return counts(registry)
        except RegistryError as error:raise HTTPException(409,'初始化未执行：已有数据、资料校验或版本检查未通过；不覆盖或重置。') from error

    @router.get('/api/v4/print-plan',response_class=HTMLResponse)
    def plan_print(plan_id:str=Query(pattern=r'^[a-f0-9]{32}$'),expected_version:int=Query(ge=1,le=100),owner:str=Depends(plan_owner)):
        try:
            plan=guard_current_evidence(plans.read(plan_id,owner=owner),registry)
            if plan['version']!=expected_version:raise RegistryError('Version changed')
            source=json.loads((ROOT/'docs/course-mvp/course-inventory.json').read_text())
            item=next(i for i in source['lessons'] if i['lesson']['lesson_id']==plan['lesson']['lesson_id'])
            reference=assemble(registry,plan['lesson']['lesson_id'],item['teacher_fields'])
            if not markers_current(plan['current_teacher_edits'],reference):
                return unavailable_print()
            return HTMLResponse(print_plan(plan,reference))
        except RegistryError:return unavailable_print()

    @router.get('/api/v4/print-loop',response_class=HTMLResponse)
    def loop_print(loop_id:str=Query(pattern=r'^[a-f0-9]{32}$'),owner:str=Depends(plan_owner),token:str=Depends(video_owner)):
        try:return HTMLResponse(print_loop(loops.read(loop_id,owner,token)))
        except RegistryError:return unavailable_print()
    return router
