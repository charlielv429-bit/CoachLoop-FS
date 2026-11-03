/* Existing local console only. Text is always rendered with textContent. */
(()=>{
'use strict';
if(document.querySelector('meta[name=coachloop-mode]'))return;
const root=document.querySelector('#teaching-loop');root.hidden=false;
const form=document.querySelector('#loop-form');
const by=id=>document.querySelector('#loop-'+id);
let current=null,context=null,dirty=false,busy=false,needsRefresh=false,evidenceEpoch=0,responseChanged=false;
const message=text=>{by('message').textContent=text;};
async function api(path,body){
  const requestEpoch=evidenceEpoch;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  try{
    const response=await fetch('/api/v3/loops/'+path,{credentials:'same-origin',redirect:'error',signal:controller.signal,
      ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(body)})});
    if(!response.ok)throw new Error('闭环请求失败（'+response.status+'）：请核对会话、保存版本和证据；失效时重新生成或关联，不覆盖记录。');
    const result=await response.json();responseChanged=requestEpoch!==evidenceEpoch;return result;
  }finally{clearTimeout(timer);}
}
async function run(action){
  if(busy)return;
  busy=true;const controls=[...root.querySelectorAll('button,input,textarea,select')];controls.forEach(x=>x.disabled=true);
  try{await action();}catch(e){message(e.message);}finally{busy=false;controls.forEach(x=>x.disabled=false);}
}
function show(value){
  current=value;dirty=false;needsRefresh=false;by('ack').checked=false;
  form.elements.learner_code.value=value.learner_code;form.elements.learner_code.readOnly=true;
  form.elements.observation.value=value.observation;form.elements.practice_task.value=value.practice_task;
  by('report').hidden=false;by('review-label').textContent=value.review_label+'；'+value.warning;
  by('report-text').textContent=JSON.stringify({课次:value.lesson_id,匿名编号:value.learner_code,闭环版本:value.version,
    关联教案版本:value.plan_version,当前教案版本:value.current_plan_version,数据来源:value.data_origin,
    当前确认:value.confirmation_current,证据已变化:value.evidence_changed,
    教师观察_未认证:value.observation,复练任务_未认证:value.practice_task,
    视频质量:value.analysis.quality,候选二维变化:value.analysis.candidate_changes,
    专项审核:value.specialist_review_status,技术错误评价:value.technical_error_assessment,
    教案待审提示:value.plan.warning,保存生命周期:value.lifecycle},null,2);
  message('已读取闭环版本'+value.version+'；'+value.review_label+'。');
  if(responseChanged){needsRefresh=true;by('report').hidden=true;message('读取期间证据发生变化，请重新核对；暂不显示旧确认。');}
}
async function readContext(){
  if(dirty)throw new Error('有未保存修改，请先保存或重新核对证据。');
  const plan=document.querySelector('#lp-output');
  if(plan.hidden||plan.dataset.lessonId!=='L05'||!plan.dataset.planId)throw new Error('请先生成并保存当前L05教案。');
  if(plan.dataset.unsaved==='true')throw new Error('L05教案有未保存修改，请先保存。');
  const response=await fetch('/api/v2/video/current',{credentials:'same-origin',redirect:'error'});
  if(!response.ok)throw new Error('本机视频会话不可用，请刷新后重试。');
  const job=await response.json();
  if(!job||job.state!=='ready')throw new Error('请先完成本机视频分析，或显式创建合成关键点演示。');
  context={plan_id:plan.dataset.planId,expected_plan_version:Number(plan.dataset.planVersion),job_id:job.job_id};
  current=null;dirty=false;by('report').hidden=true;by('ack').checked=false;form.elements.learner_code.readOnly=false;
  form.elements.observation.value='';form.elements.practice_task.value='';
  by('context').textContent='L05教案版本'+context.expected_plan_version+'；任务'+context.job_id+'；'+(job.source_kind==='synthetic_keypoints_demo'?'合成关键点演示（不是真实视频）':'本机真实视频分析（非技术评价）');
  message('请填写匿名编号、观察与复练任务，再关联保存草稿。');
}
document.querySelector('#lp-loop').addEventListener('click',()=>{
  document.querySelector('[data-stage=feedback]').click();root.open=true;root.scrollIntoView();run(readContext);
});
by('use-context').addEventListener('click',()=>run(readContext));
form.addEventListener('input',()=>{dirty=true;by('ack').checked=false;by('review-label').textContent='当前编辑有未保存修改，属于草稿；请先保存再确认或导出。';});
form.addEventListener('submit',event=>{event.preventDefault();run(async()=>{
  if(!context)throw new Error('请先读取当前L05教案与本机任务。');
  show(await api('link',{...context,learner_code:form.elements.learner_code.value,observation:form.elements.observation.value,practice_task:form.elements.practice_task.value}));
});});
by('save').addEventListener('click',()=>run(async()=>{
  if(!current)throw new Error('请先关联观察或恢复记录。');
  show(await api('edit',{loop_id:current.loop_id,expected_version:current.version,expected_evidence_digest:current.current_evidence_digest,
    observation:form.elements.observation.value,practice_task:form.elements.practice_task.value}));
}));
function requireSaved(){if(!current)throw new Error('请先关联观察或恢复记录。');if(dirty)throw new Error('有未保存修改，请先追加保存。');}
by('confirm').addEventListener('click',()=>run(async()=>{
  requireSaved();if(needsRefresh)throw new Error('资料已变化，请先重新核对当前证据。');if(!by('ack').checked)throw new Error('请显式勾选核对声明；这不是专业认证。');
  show(await api('confirm',{loop_id:current.loop_id,expected_version:current.version,expected_evidence_digest:current.current_evidence_digest,acknowledged:true}));
}));
by('refresh').addEventListener('click',()=>run(async()=>{
  if(!current)throw new Error('请先关联观察或恢复记录。');
  const pending=dirty?{observation:form.elements.observation.value,practice_task:form.elements.practice_task.value}:null;
  show(await api('export?loop_id='+current.loop_id));
  if(pending){form.elements.observation.value=pending.observation;form.elements.practice_task.value=pending.practice_task;dirty=true;by('ack').checked=false;by('review-label').textContent='当前编辑仍为草稿，未保存文字已保留。';message('证据已重新核对，保留未保存文字；请保存后再确认或导出。');}
}));
by('export').addEventListener('click',()=>run(async()=>{
  requireSaved();const value=await api('export?loop_id='+current.loop_id);show(value);
  if(responseChanged)throw new Error('读取期间证据变化，请重新核对后导出。');
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='L05-teaching-loop.'+(value.is_mock?'SYNTHETIC.':'')+value.feedback_review_status+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  message('已导出本会话完整闭环与审计历史；含私有匿名编号/文字，请自行保管。');
}));
async function list(){const value=await api('current');by('records').replaceChildren();for(const record of value.records){const option=document.createElement('option');option.value=record.loop_id;option.textContent=record.learner_code+'／版本'+record.version;by('records').append(option);}message('当前会话可恢复'+value.records.length+'条记录；失效或删除的任务不在列表。');}
by('list').addEventListener('click',()=>run(list));
by('open').addEventListener('click',()=>run(async()=>{if(!by('records').value)throw new Error('请先读取本会话记录列表。');if(dirty)throw new Error('有未保存修改，请先保存。');show(await api('export?loop_id='+by('records').value));}));
by('delete').addEventListener('click',()=>run(async()=>{
  if(!current)throw new Error('没有当前闭环记录。');await api('delete',{loop_id:current.loop_id});current=null;dirty=false;by('report').hidden=true;by('ack').checked=false;form.reset();form.elements.learner_code.readOnly=false;await list();message('当前闭环已从进程内存删除；已导出文件需自行删除。');
}));
document.addEventListener('coachloop-evidence-changed',()=>{evidenceEpoch++;if(current){needsRefresh=true;by('ack').checked=false;by('report').hidden=true;message('资料或事件已变化，原确认暂不显示；请重新核对当前证据，反馈按草稿处理。');}});
document.querySelector('#loop-demo-analysis').addEventListener('click',()=>run(async()=>{
  const value=await api('demo-analysis',{synthetic_demo:true});
  document.dispatchEvent(new CustomEvent('coachloop-demo-analysis',{detail:value}));
  message('已创建明确标记的合成关键点演示；没有上传视频或调用MediaPipe。');
}));
})();
