'use strict';
const form=document.querySelector('#lesson-form');
const isClassroom=document.querySelector('meta[name="coachloop-mode"]')?.content==='classroom_mock_demo';
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
  theme_id:'主题标识',theme_version:'主题版本',verification_status:'核实状态',source:'来源',
  prerequisites_missing:'缺少先修技能',core_exercises:'核心练习',evaluation_indicators:'形成性评价',safety_limits:'安全限制',
  staff_tasks:'师资分工',teacher_review_checklist:'教师审核清单',teacher_goal_edit:'教师修改目标',teacher_notes:'教师修改备注',
  differentiation:'差异化练习',capacity_source:'容量依据',declared_capacity:'教师拟定容量',usable_area_m2:'可用面积（平方米）',
  concurrent_students:'同时练习人数',wave_sizes:'各轮人数',groups:'指导组',rotation_count:'轮换次数',
  main_demo_min:'基本阶段示范分钟',main_rotation_min:'基本阶段轮换窗口分钟',transition_min_per_wave:'每轮转换分钟（假设）',
  core_active_min_per_student:'人均核心活动分钟',waiting_students_max:'最多等待人数',group_diagram:'分组轮换示意',
  wave:'轮次',coach:'教练',students:'学生数',role:'角色',number:'人员序号',task:'任务',order:'顺序',
  catalogue_task:'主题库原候选任务',active_min_per_student:'预计人均活动分钟',mode:'练习方式',
  status:'状态',editorial_candidate:'工程整理候选条目（未经专业核实）',withheld:'暂缓冰上实施',candidate_unverified:'候选内容未核实',teacher_declared_unverified:'教师填报，未独立核实',
  editorials:'工程整理',reference:'正式引用（暂无）',kind:'类型',teacher:'体育教师',
  training_information:'训练基本信息',video_quality:'视频分析质量',reported_observations:'本地未认证观察记录',
  trusted_observations:'正式可信观察（当前为空）',pending_questions:'待确认问题',candidate_practice:'候选练习建议',
  authenticated_coach:'专业教练身份已认证',review_verification:'审核认证状态',local_unverified:'本地未认证',
  technical_error_assessment:'技术错误评定',not_assessed:'未作技术错误评定',requires_teacher_review:'需要教师复核',
  knowledge_status:'知识依据状态',review_status:'审核状态',draft:'草稿',generated_at:'草稿生成时间',
  source_frames:'分析帧数',detected_frames:'检出帧数',valid_frame_ratio:'姿态检出比例',
  start_time_ms:'预览开始时间（毫秒）',end_time_ms:'预览结束时间（毫秒）',frame_start:'分析开始帧',frame_end:'分析结束帧',
  deviation_max:'相对基线偏离量',eligible_for_technical_conclusions:'可用于确定技术结论',review_sequences:'当前审核历史序列',
  time_basis:'时间依据',analysis_scope:'分析范围',limitations:'观测局限',interpretation:'保守解释',
  duration_seconds:'视频时长（秒）',width:'原视频宽',height:'原视频高',analysis_fps:'分析预览帧率',
  prep:'准备阶段',preparation:'准备阶段',main:'基本阶段',closing:'结束阶段'};
const elements=[['guiding_ideology','01 指导思想'],['teaching_material_analysis','02 教材分析'],
  ['learner_analysis','03 学情分析与分层练习'],['teaching_flow','04 教学流程'],
  ['venue_equipment','05 场地器材与组织'],['safety_precautions','06 安全防范'],['complete_plan','07 完整教案']];
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
  if(isClassroom&&(data.demo_data_domain!=='mock'||data.is_mock!==true||data.human_review_performed!==false))throw new Error('缺少课堂模拟标记。');
  if(!p||data.schema_version!=='adaptive-prelesson-v1.1'||!['draft_ready','needs_confirmation'].includes(data.status)
    ||data.requires_teacher_review!==true||data.knowledge_status!=='unverified'||data.review_status!=='draft'
    ||p.review_status!=='draft'||p.teaching_flow.total_minutes!==45||p.teaching_flow.phases.length!==3
    ||p.teaching_flow.phases.reduce((sum,x)=>sum+x.minutes,0)!==45
    ||p.safety_precautions.safety_review_status!=='unreviewed'||p.venue_equipment.organization_status!=='pending_confirmation'
    ||p.load_accounting.total_minutes!==45||p.load_accounting.avg_hr!==null||p.load_accounting.kind!=='estimated'
    ||elements.some(([key])=>!p[key])||!p.evidence_log.some(e=>e.source==='unverified')
    ||p.evidence_log.some(e=>['kb_evidence','real_analysis'].includes(e.source)||(e.source==='unverified'&&e.citation!==null))
    ||['group_density','individual_density'].some(k=>p.load_accounting[k].kind!=='estimated')
    ||(data.status==='needs_confirmation'&&data.adaptation.core_exercises.length!==0)){
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
  for(const [title,value] of [['预计负荷与核算依据（心率未估计、未实测）',p.load_accounting],['差异化安排与教师审核清单',data.adaptation]]){const section=document.createElement('details');section.className='panel element';section.open=true;const titleNode=document.createElement('summary');titleNode.textContent=title;section.append(titleNode,render(value));container.append(section);}
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
  for(const key of ['student_count','total_minutes','coach_count','teacher_count','usable_area_m2','declared_practice_capacity','equipment_sets']){payload[key]=values.get(key)===''?null:Number(values.get(key));}
  payload.teacher_exercise_edits=values.getAll('teacher_exercise_edits');
  if(isClassroom){payload.data_domain='mock';payload.is_mock=true;}
  payload.mastered_skills=values.getAll('mastered_skills');payload.safe_waiting_area=values.has('safe_waiting_area');payload.ice_available=values.has('ice_available');
  const timer=setTimeout(()=>controller.abort(),15000);
  try{
    const response=await fetch('/api/v1/lesson-plans/adaptive-draft',{method:'POST',credentials:'same-origin',redirect:'error',
      headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(payload),signal:controller.signal});
    if(!response.ok){const errors={429:'课堂生成次数已达限制，请一分钟后重试。',401:isClassroom?'课堂会话已失效，请刷新后登录。':'本地会话已失效，请刷新页面。',403:'请求未通过本地安全检查。',413:'输入过长，请缩短内容。',422:'输入无效，请检查必填条件、数值及主题。',503:'生成服务暂不可用。'};throw new Error(errors[response.status]||'生成失败，请稍后重试。');}
    let data=await response.json();if(version!==requestVersion)return;
    if(isClassroom){if(data.data_domain!=='mock'||data.is_mock!==true||data.human_review_performed!==false)throw new Error('课堂模拟数据标记异常。');data={...data.draft,demo_data_domain:'mock',is_mock:true,human_review_performed:false};}
    show(data);status(data.status==='needs_confirmation'?'条件不足：已暂缓冰上方案，请按限制调整输入。':'教案已动态生成，组织和安全仍待教师与专项教练确认。');
  }catch(error){if(version===requestVersion){invalidate();status(error.name==='AbortError'?'请求已取消或超时，请重试。':error instanceof TypeError?'无法连接本地服务，请确认服务窗口仍在运行。':error.message,true);}}
  finally{clearTimeout(timer);if(activeController===controller){activeController=null;submit.disabled=false;}}
});
document.querySelector('#download').addEventListener('click',()=>{
  if(!draft)return;validateResponse(draft);
  const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=isClassroom?'coachloop-classroom.mock.draft.json':'coachloop-lesson-plan.draft.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});

// All catalogue text is rendered as text, never interpreted as HTML.
let themes=[];
const selector=form.elements.theme_id;
function filterThemes(){
  const previous=selector.value;const query=document.querySelector('#theme-search').value.trim().toLowerCase();
  const matching=themes.filter(t=>t.supported_levels.includes(form.elements.skill_level.value)&&[t.name_zh,t.name_en,t.theme_id].join(' ').toLowerCase().includes(query));
  selector.replaceChildren();
  for(const t of matching){const option=document.createElement('option');option.value=t.theme_id;option.textContent=t.name_zh+' · '+t.name_en;selector.append(option);}
  if(matching.some(t=>t.theme_id===previous))selector.value=previous;
  else if(!query&&matching.some(t=>t.theme_id==='two_foot_glide'))selector.value='two_foot_glide';
  describeTheme();
}
function describeTheme(){
  const t=themes.find(t=>t.theme_id===selector.value);
  document.querySelector('#theme-description').textContent=t?'先修：'+(t.prerequisites.map(id=>themes.find(x=>x.theme_id===id).name_zh).join('、')||'无')+'。候选内容版本'+t.version+'，来源：工程整理，unverified；不满足条件将暂缓冰上练习。':'没有匹配主题，请调整搜索。';
  submit.disabled=!t;
}
form.elements.skill_level.addEventListener('change',filterThemes);
document.querySelector('#theme-search').addEventListener('input',filterThemes);
selector.addEventListener('change',describeTheme);
submit.disabled=true;
fetch('/api/v1/lesson-plans/themes',{credentials:'same-origin',redirect:'error'}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{
  if(data.knowledge_status!=='unverified'||data.themes.length<24)throw new Error();
  themes=data.themes;const skills=document.querySelector('#skills');
  for(const t of themes){const label=document.createElement('label');const check=document.createElement('input');check.type='checkbox';check.name='mastered_skills';check.value=t.theme_id;label.append(check,document.createTextNode(t.name_zh));skills.append(label);}
  filterThemes();
}).catch(()=>{submit.disabled=true;status('无法加载主题库，请确认本地服务版本并刷新页面。',true);});

if(isClassroom){
  document.querySelector('.mode').textContent='临时HTTPS课堂 · 仅模拟数据';
  document.querySelector('.notice').textContent='公网课堂演示：仅允许合成模拟数据，不填写真实姓名、健康记录或凭据。教学知识与安全依据未核实，组织须经现场专业审核。课堂访问码不证明教师身份。';
  form.elements.class_label.value='MOCK-CLASSROOM';form.elements.class_label.pattern='MOCK-[A-Z0-9_-]{1,60}';
  const logout=document.createElement('button');logout.type='button';logout.textContent='退出课堂';logout.className='secondary';
  logout.addEventListener('click',async()=>{try{await fetch('/classroom/logout',{method:'POST',credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:'{}'});}finally{invalidate();location.replace('/');}});
  document.querySelector('.intro').append(logout);
}

if(!isClassroom){const videoScript=document.createElement('script');videoScript.src='/video-console.js';document.head.append(videoScript);}
else{for(const button of document.querySelectorAll('#stage-nav [data-stage]')){if(button.dataset.stage!=='prelesson'){button.disabled=true;button.title='真实视频仅本机可用，模拟课堂禁止上传';}}}
