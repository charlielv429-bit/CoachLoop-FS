'use strict';
(() => {
  const el = id => document.getElementById('v3-' + id);
  if (document.querySelector('meta[name=coachloop-mode]')) return;
  document.getElementById('curriculum-entry').hidden = false;
  const form = el('form');
  let lessons = [];
  const message = text => { el('message').textContent = text; };
  async function api(path, data) {
    const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'}, body:JSON.stringify(data)};
    const response = await fetch('/api/v3/' + path, options);
    if (!response.ok) throw new Error('请求被拒绝（' + response.status + '）；请检查字段、来源完整性与版本号。');
    return response.json();
  }
  async function guarded(action) { try { await action(); } catch (error) { message(error.message); } }
  function detail() {
    const lesson = lessons.find(x => x.lesson_id === el('lesson').value);
    el('detail').textContent = lesson ? JSON.stringify(lesson, null, 2) : '';
  }
  async function loadLessons() {
    const data = await api('lessons');
    lessons = data.lessons;
    el('storage').textContent = data.storage;
    if (!el('lesson').options.length) for (const lesson of lessons) {
      const option = document.createElement('option');
      option.value = lesson.lesson_id; option.textContent = lesson.lesson_id + ' ' + lesson.title + ' · 45分钟';
      el('lesson').append(option);
    }
    detail();
  }
  async function search() {
    const params = new URLSearchParams({keyword:el('keyword').value});
    if (el('category').value) params.set('category',el('category').value);
    if (el('only-lesson').checked) params.set('lesson_id',el('lesson').value);
    const data = await api('knowledge?' + params);
    el('list').replaceChildren();
    if (!data.entries.length) el('list').textContent = '暂无匹配条目（四类知识库初始为空）。';
    for (const entry of data.entries) {
      const box = document.createElement('section');
      const text = document.createElement('pre');
      text.textContent = JSON.stringify(entry,null,2);
      const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '编辑并追加版本';
      edit.addEventListener('click',() => {
        for (const input of form.elements) if (input.name && Object.hasOwn(entry,input.name)) input.value = input.name === 'lesson_ids' ? entry.lesson_ids.join(',') : entry[input.name];
        form.elements.version.value = entry.version + 1;
        message('编辑为新版本；原版本保留，审核状态仍未认证。');
      });
      const history = document.createElement('button'); history.type = 'button'; history.textContent = '查看全部版本';
      history.addEventListener('click',() => guarded(async () => { text.textContent = JSON.stringify(await api('history?knowledge_id=' + encodeURIComponent(entry.knowledge_id)),null,2); }));
      box.append(text,edit,history); el('list').append(box);
    }
  }
  form.addEventListener('submit',event => { event.preventDefault(); guarded(async () => {
    const data = Object.fromEntries(new FormData(form));
    data.version = Number(data.version);
    data.lesson_ids = data.lesson_ids.split(',').map(x => x.trim()).filter(Boolean);
    const saved = await api('knowledge',data);
    form.elements.version.value = saved.version + 1;
    await loadLessons(); await search(); message('已保存版本 ' + saved.version + '；待审核，不作为正式教学依据。');
  }); });
  el('new').addEventListener('click',() => { form.reset(); message('新增条目从版本1开始。'); });
  el('search').addEventListener('click',() => guarded(search));
  el('lesson').addEventListener('change',() => { detail(); if(el('only-lesson').checked) guarded(search); });
  el('export').addEventListener('click',() => guarded(async () => {
    const data = await api('export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link = document.createElement('a'); link.href=url; link.download='coachloop.kb-backup.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url),1000); message('已导出知识版本；不含材料、审核决定或撤回历史，完整恢复请使用离线full-backup。');
  }));
  el('review').addEventListener('click',() => guarded(async () => {
    const data = await api('review-materials');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link = document.createElement('a'); link.href=url; link.download='coachloop.kb-review.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url),1000); message('已导出离线待审核材料；不含完整审核决定与撤回历史，不代表认证通过。');
  }));
  el('import').addEventListener('click',() => guarded(async () => {
    const file = el('import-file').files[0];
    if (!file || file.size > 1024 * 1024) throw new Error('请选择不超过1MiB的JSON文件。');
    // Send original JSON: server rejects duplicate keys rather than losing them in JSON.parse.
    const response = await fetch('/api/v3/import',{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:await file.text()});
    if (!response.ok) throw new Error('导入失败（' + response.status + '），请检查格式、审核状态和版本冲突；未写入任何条目。');
    await loadLessons(); await search(); message('导入成功；保留未核实／待审核状态。');
  }));
  guarded(async () => { await loadLessons(); await search(); });
})();
