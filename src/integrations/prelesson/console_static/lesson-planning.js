'use strict';
(() => {
  if (document.querySelector('meta[name=coachloop-mode]')) return;
  const byId = id => document.getElementById('lp-'+id);
  document.getElementById('lesson-planning-mode').hidden=false;
  let current=null, sequence=0, editDirty=false, editSequence=0;
  const form=byId('form'), edit=byId('edit-form');
  async function api(path,body) {
    const response=await fetch('/api/v3/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(body)});
    if(!response.ok) throw new Error('请求失败（'+response.status+'）；检查字段、版本、会话或容量限制。');
    return response.json();
  }
  function message(value){byId('message').textContent=value;}
  async function guard(action){try{await action();}catch(error){message(error.message);}}
  function renderL05(design,container){
    const heading=document.createElement('h2');heading.textContent=design.title;container.append(heading);
    const notice=document.createElement('p');notice.className='notice';notice.textContent=design.notice;container.append(notice);
    for(const area of Object.values(design.areas)){
      const box=document.createElement('article');box.className='panel';const title=document.createElement('h3');title.textContent=area.label+' · 待教师复核';
      const text=document.createElement('pre');text.textContent=area.text;box.append(title,text);container.append(box);
    }
    const labels={specialist_knowledge:'专项知识素材',teaching_progression:'课程进阶建议（自拟内容不冒充教材原文）',evaluation_suggestions:'评价观察建议（不自动评分）'};
    const states={registered_not_verified:'来源已登记，原文和专项审核待确认',locator_conflict_pending:'页码定位冲突，尚无原PDF核查，不得认证',reviewed_for_draft_only:'满足受控草稿引用条件，仍待现场教师复核',superseded_or_unlinked:'条目已失效或更新，请重新生成',withdrawn_pending_regeneration:'审核已撤回，已撤下素材正文'};
    for(const [group,cards] of Object.entries(design.material_groups)){
      const title=document.createElement('h3');title.textContent=labels[group];container.append(title);
      if(!cards.length){const empty=document.createElement('p');empty.textContent='暂无关联条目；由教师补充，不生成虚构内容。';container.append(empty);}
      for(const card of cards){
        const box=document.createElement('article');box.className='panel';const title=document.createElement('h4');title.textContent=card.title;
        const citation=document.createElement('p');citation.textContent=card.knowledge_id+' v'+card.version+' / '+card.source_id+' / '+card.source_title+' / '+card.source_locator;
        const status=document.createElement('p');status.className='notice';status.textContent=states[card.citation_status]+'；'+card.label;
        box.append(title,citation,status);
        if(card.candidate_text){const quote=document.createElement('blockquote');quote.textContent='材料中的候选陈述（不等于已核实原文）：'+card.candidate_text;box.append(quote);}
        const limits=document.createElement('p');limits.textContent='适用限制：'+card.applicability_limitations;box.append(limits);
        if(card.source_conflict_note){const conflict=document.createElement('p');conflict.textContent=card.source_conflict_note;box.append(conflict);}
        container.append(box);
      }
    }
    for(const [label,value] of [['教材定位核查（含L04先修素材K010）',design.location_checks],['当前受控教材引用（没有则为空）',design.reviewed_citations]]){
      const details=document.createElement('details');const title=document.createElement('summary');title.textContent=label;const text=document.createElement('pre');text.textContent=JSON.stringify(value,null,2);details.append(title,text);container.append(details);
    }
  }
  function show(plan,preserveEdits=false){
    const unsaved=preserveEdits?Object.fromEntries(new FormData(edit)):null;
    current=plan;byId('output').hidden=false;
    byId('result').replaceChildren();
    byId('l05-fields').hidden=!plan.l05_teaching_design;byId('l05-fields').disabled=!plan.l05_teaching_design;
    if(plan.l05_teaching_design)renderL05(plan.l05_teaching_design,byId('result'));
    const sections=[['课次与目标草稿', {lesson:plan.lesson,objective_draft:plan.effective_goal_draft,warning:plan.warning}],
      ['课堂准备与资源条件',{checks:plan.preparation_checklist,conditions:plan.conditions,prerequisites:plan.prerequisites}],
      ['45分钟阶段框架',plan.teaching_flow],['师生组织与预计负荷',{organization:plan.organization,staff_tasks:plan.staff_tasks,load_accounting:plan.load_accounting}],
      ['分层占位',plan.differentiation],['满足本地审核条件的草稿依据（不等于官方认证）',plan.formal_teaching_evidence],
      ['受控审阅教学建议（仍待现场教师复核，含条目与出处）',plan.teaching_suggestions],['独立材料声明（不等于系统审核）',plan.evidence_reports],['关联资料登记与审核状态（不作为动作指导）',plan.knowledge_inventory],['尚缺专项资料',plan.missing_materials],
      ['教师审核清单',plan.teacher_review_checklist],['教师修改记录（待复核）',plan.teacher_edits]];
    for(const [title,value] of sections){const heading=document.createElement('h3');heading.textContent=title;const pre=document.createElement('pre');pre.textContent=JSON.stringify(value,null,2);byId('result').append(heading,pre);}
    for(const input of edit.elements)if(input.name)input.value=(unsaved&&Object.hasOwn(unsaved,input.name))?unsaved[input.name]:plan.current_teacher_edits[input.name];
    editDirty=preserveEdits;
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
  edit.addEventListener('input',()=>{editDirty=true;editSequence++;});
  edit.addEventListener('submit',event=>{event.preventDefault();guard(async()=>{
    if(!current)throw new Error('请先生成课次框架。');
    const token=sequence, editToken=editSequence, plan=await api('plans/edit',{plan_id:current.plan_id,expected_version:current.version,...Object.fromEntries(new FormData(edit))});
    if(token!==sequence)return;const stillEditing=editToken!==editSequence;show(plan,stillEditing);message('教师修改已保存为版本'+plan.version+'，仍待复核。'+(stillEditing?'新增输入尚未保存。':''));
  });});
  byId('export').addEventListener('click',()=>guard(async()=>{
    if(!current)throw new Error('请先生成框架。');
    if(editDirty)throw new Error('有未保存修改，请先保存再导出或核对引用。');
    const token=sequence,id=current.plan_id,version=current.version;
    const plan=await api('plans/export?plan_id='+id);
    if(token!==sequence||current?.plan_id!==id||current.version!==version)return;
    if(editDirty)throw new Error('有未保存修改，请先保存再导出或核对引用。');
    show(plan);
    const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=plan.lesson.lesson_id+'-pending-review-framework.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已从服务端导出待审核框架及修改记录。');
  }));
  byId('refresh-evidence').addEventListener('click',()=>guard(async()=>{
    if(!current)throw new Error('请先生成框架。');
    if(editDirty)throw new Error('有未保存修改，请先保存再核对引用。');
    const token=sequence,id=current.plan_id,version=current.version;const plan=await api('plans/export?plan_id='+id);
    if(token!==sequence||current?.plan_id!==id||current.version!==version)return;
    if(editDirty)throw new Error('有未保存修改，请先保存再核对引用。');
    show(plan);message(plan.warning);
  }));
  byId('history').addEventListener('click',()=>guard(async()=>{
    if(!current)return;const token=sequence,id=current.plan_id,version=current.version;const data=await api('plans/history?plan_id='+id);
    if(token===sequence&&current?.plan_id===id&&current.version===version)byId('history-result').textContent=JSON.stringify(data,null,2);
  }));
  guard(async()=>{const data=await api('lessons');for(const lesson of data.lessons){const option=document.createElement('option');option.value=lesson.lesson_id;option.textContent=lesson.lesson_id+' '+lesson.title;byId('lesson').append(option);}byId('lesson').value='L05';});
})();
