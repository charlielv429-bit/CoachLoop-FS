'use strict';
const form=document.querySelector('#lesson-form');
const output=document.querySelector('#result');
const empty=document.querySelector('#empty');
const message=document.querySelector('#message');
const submit=document.querySelector('#generate');
let draft=null;
let requestVersion=0;
let activeController=null;
const labels={content:'内容',principles:'原则',skill_description:'动作说明',key_points:'重点',difficulties:'难点',
  common_errors:'易错现象',goals:'目标',audience_description:'教学对象',assumptions:'设计假设',tiered_plan:'分层练习',
  grouping:'分组',organization:'组织安排',organization_status:'组织确认状态',layout:'场地布置',equipment:'器材',
  risks:'风险提示',precautions:'注意事项',contraindications:'禁忌与限制',emergency_plan:'应急预案',
  safety_review_status:'安全审核状态',phases:'三阶段流程',phase:'阶段',minutes:'分钟',teacher_activity:'教师活动',
  student_activity:'学生活动',safety_tip:'安全提示',evaluation:'评价与反馈',total_minutes:'总课时',
  avg_hr:'预计平均心率',group_density:'预计群体运动密度',individual_density:'预计个体运动密度',
  name:'指标',kind:'数据类型',formula:'核算公式',numerator:'分子',denominator:'分母',unit:'单位',
  result:'计算结果',display_result:'展示值',target:'设计参考',note:'说明',statement:'依据陈述',source:'依据状态',
  citation:'引用',unreviewed:'待专项审核',pending_confirmation:'待确认',estimated:'预计',unverified:'未核实',
  motor_competence:'运动能力',healthy_behavior:'健康行为',sports_ethics:'体育品德',technical_composition:'技术组成',
  progression:'教学递进',note_2d_limitation:'二维观察边界',student_profile:'学情',common_difficulties:'学习难点',
  proposed_group_sizes:'建议分组人数',zones:'教学区域',route:'移动路线',observation_position:'教师观察位置',
  equipment_list:'器材清单',camera_position:'拍摄位置建议',risk_screening:'课前风险核查',ice_check:'冰面检查',
  equipment_check:'器材检查',staffing:'师资安排',zone_management:'区域管理',emergency_flow:'应急交接',medical_note:'医学边界提示',
  prep:'准备阶段',preparation:'准备阶段',main:'基本阶段',closing:'结束阶段'};
const elements=[['guiding_ideology','01 指导思想'],['teaching_material_analysis','02 教材分析'],
  ['learner_analysis','03 学情分析与分层练习'],['venue_equipment','04 场地器材与组织'],
  ['safety_precautions','05 安全防范与禁忌'],['teaching_flow','06 教学流程'],['load_accounting','07 预计运动负荷']];
function text(value){return typeof value==='string'?(labels[value]||value):String(value);}
function render(value){
  if(Array.isArray(value)){const list=document.createElement('ul');for(const item of value){const li=document.createElement('li');li.append(render(item));list.append(li);}return list;}
  if(value!==null&&typeof value==='object'){const dl=document.createElement('dl');for(const [key,item] of Object.entries(value)){if(item===null)continue;const dt=document.createElement('dt');dt.textContent=labels[key]||key;const dd=document.createElement('dd');dd.append(render(item));dl.append(dt,dd);}return dl;}
  const span=document.createElement('span');span.textContent=value===null?'未提供':text(value);return span;
}
function invalidate(){draft=null;output.hidden=true;empty.hidden=false;}
function status(value,error=false){message.textContent=value;message.dataset.error=String(error);}
function validateResponse(data){
  const p=data&&data.lesson_plan;
  if(!p||data.schema_version!=='prelesson-draft-v1'||data.status!=='draft_ready'||data.requires_teacher_review!==true||data.knowledge_status!=='unverified'
    ||data.load_basis!=='estimated_design_assumptions'||p.review_status!=='draft'
    ||p.teaching_flow.total_minutes!==45||p.teaching_flow.phases.reduce((sum,x)=>sum+x.minutes,0)!==45
    ||p.safety_precautions.safety_review_status!=='unreviewed'||p.venue_equipment.organization_status!=='pending_confirmation'
    ||p.load_accounting.total_minutes!==45||elements.some(([key])=>!p[key])
    ||!p.evidence_log.some(e=>e.source==='unverified')
    ||p.evidence_log.some(e=>['kb_evidence','real_analysis'].includes(e.source)||(e.source==='unverified'&&e.citation!==null))
    ||['avg_hr','group_density','individual_density'].some(k=>p.load_accounting[k].kind!=='estimated')){
    throw new Error('响应未通过草稿保护检查，未展示教案。');
  }
}
function show(data){
  validateResponse(data);
  const p=data.lesson_plan;
  document.querySelector('#plan-title').textContent=p.title;
  document.querySelector('#audience').textContent=p.teacher_input.audience;
  const time=document.querySelector('#time-summary');time.replaceChildren();
  const heading=document.createElement('h3');heading.textContent='三阶段 · 共45分钟';time.append(heading);
  const strip=document.createElement('div');strip.className='time-strip';
  for(const phase of p.teaching_flow.phases){const box=document.createElement('div');box.textContent=labels[phase.phase]||phase.phase;const minutes=document.createElement('strong');minutes.textContent=phase.minutes+' 分钟';box.append(minutes);strip.append(box);}time.append(strip);
  const container=document.querySelector('#elements');container.replaceChildren();
  for(const [key,title] of elements){const section=document.createElement('details');section.className='panel element';section.open=true;const summary=document.createElement('summary');summary.textContent=title;section.append(summary,render(p[key]));container.append(section);}
  const evidence=document.createElement('details');evidence.className='panel element';const summary=document.createElement('summary');summary.textContent='知识依据 · 未核实';evidence.append(summary,render(p.evidence_log));container.append(evidence);
  draft=data;empty.hidden=true;output.hidden=false;
}
form.addEventListener('input',()=>{requestVersion++;if(activeController)activeController.abort();invalidate();status('输入已变更，请重新生成教案。');});
form.addEventListener('submit',async event=>{
  event.preventDefault();if(!form.reportValidity())return;
  if(activeController)activeController.abort();
  const version=++requestVersion;const controller=new AbortController();activeController=controller;
  invalidate();submit.disabled=true;status('正在调用教案 Agent…');
  const values=new FormData(form);const payload=Object.fromEntries(values);
  for(const key of ['student_count','total_minutes','coach_count','teacher_count']){payload[key]=values.get(key)===''?null:Number(values.get(key));}
  const timer=setTimeout(()=>controller.abort(),15000);
  try{
    const response=await fetch('/api/v1/lesson-plans/draft',{method:'POST',credentials:'same-origin',redirect:'error',
      headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(payload),signal:controller.signal});
    if(!response.ok){const errors={401:'本地会话已失效，请刷新页面。',403:'请求未通过本地安全检查。',413:'输入过长，请缩短内容。',422:'输入不符合当前模板，请检查人数、师资及场地器材描述。',503:'生成服务暂不可用。'};throw new Error(errors[response.status]||'生成失败，请稍后重试。');}
    const data=await response.json();if(version!==requestVersion)return;
    show(data);status('教案已动态生成。请由教师复核组织、安全与知识依据。');
  }catch(error){if(version===requestVersion){invalidate();status(error.name==='AbortError'?'请求已取消或超时，请重试。':error instanceof TypeError?'无法连接本地服务，请确认服务窗口仍在运行。':error.message,true);}}
  finally{clearTimeout(timer);if(activeController===controller){activeController=null;submit.disabled=false;}}
});
document.querySelector('#download').addEventListener('click',()=>{
  if(!draft)return;validateResponse(draft);
  const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='coachloop-lesson-plan.draft.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
