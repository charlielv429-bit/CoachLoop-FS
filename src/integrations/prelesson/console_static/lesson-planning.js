'use strict';
(() => {
  if (document.querySelector('meta[name=coachloop-mode]')) return;
  const byId = id => document.getElementById('lp-'+id);
  document.getElementById('lesson-planning-mode').hidden=false;
  let current=null, sequence=0;
  const form=byId('form'), edit=byId('edit-form');
  async function api(path,body) {
    const response=await fetch('/api/v3/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(body)});
    if(!response.ok) throw new Error('请求失败（'+response.status+'）；检查字段、版本、会话或容量限制。');
    return response.json();
  }
  function message(value){byId('message').textContent=value;}
  async function guard(action){try{await action();}catch(error){message(error.message);}}
  function show(plan){
    current=plan;byId('output').hidden=false;
    byId('result').replaceChildren();
    const sections=[['课次与目标草稿', {lesson:plan.lesson,objective_draft:plan.effective_goal_draft,warning:plan.warning}],
      ['课堂准备与资源条件',{checks:plan.preparation_checklist,conditions:plan.conditions,prerequisites:plan.prerequisites}],
      ['45分钟阶段框架',plan.teaching_flow],['师生组织与预计负荷',{organization:plan.organization,staff_tasks:plan.staff_tasks,load_accounting:plan.load_accounting}],
      ['分层占位',plan.differentiation],['可用正式教学依据（无可信专项审核时为空）',plan.formal_teaching_evidence],
      ['关联资料登记与审核状态（不作为动作指导）',plan.knowledge_inventory],['尚缺专项资料',plan.missing_materials],
      ['教师审核清单',plan.teacher_review_checklist],['教师修改记录（待复核）',plan.teacher_edits]];
    for(const [title,value] of sections){const heading=document.createElement('h3');heading.textContent=title;const pre=document.createElement('pre');pre.textContent=JSON.stringify(value,null,2);byId('result').append(heading,pre);}
    for(const input of edit.elements)if(input.name)input.value=plan.current_teacher_edits[input.name];
    byId('history-result').textContent='';
  }
  form.addEventListener('input',()=>{sequence++;current=null;byId('output').hidden=true;message('条件已变更，请重新生成；旧教案仍保留在本次进程历史中。');});
  form.addEventListener('submit',event=>{event.preventDefault();guard(async()=>{
    const token=++sequence, values=new FormData(form), conditions=Object.fromEntries(values);
    const lesson_id=conditions.lesson_id;delete conditions.lesson_id;delete conditions.prerequisites_confirmed;
    for(const key of ['student_count','coach_count','teacher_count','usable_area_m2','declared_practice_capacity','equipment_sets'])conditions[key]=Number(values.get(key));
    for(const key of ['safe_waiting_area','ice_available'])conditions[key]=values.has(key);
    const plan=await api('plans/draft',{lesson_id,conditions,prerequisites_confirmed:values.has('prerequisites_confirmed')});
    if(token!==sequence)return;show(plan);message('已生成待审核教案框架；专项实操仍暂缓。');
  });});
  edit.addEventListener('submit',event=>{event.preventDefault();guard(async()=>{
    if(!current)throw new Error('请先生成课次框架。');
    const token=sequence, plan=await api('plans/edit',{plan_id:current.plan_id,expected_version:current.version,...Object.fromEntries(new FormData(edit))});
    if(token!==sequence)return;show(plan);message('教师修改已保存为版本'+plan.version+'，仍待复核。');
  });});
  byId('export').addEventListener('click',()=>guard(async()=>{
    if(!current)throw new Error('请先生成框架。');
    const plan=await api('plans/export?plan_id='+current.plan_id);
    const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=plan.lesson.lesson_id+'-pending-review-framework.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已从服务端导出待审核框架及修改记录。');
  }));
  byId('history').addEventListener('click',()=>guard(async()=>{if(current)byId('history-result').textContent=JSON.stringify(await api('plans/history?plan_id='+current.plan_id),null,2);}));
  guard(async()=>{const data=await api('lessons');for(const lesson of data.lessons){const option=document.createElement('option');option.value=lesson.lesson_id;option.textContent=lesson.lesson_id+' '+lesson.title;byId('lesson').append(option);}byId('lesson').value='L05';});
})();
