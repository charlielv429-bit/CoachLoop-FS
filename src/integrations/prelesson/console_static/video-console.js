(()=>{
'use strict';
const base='/api/v2/video';
const videoForm=document.querySelector('#video-form');
const player=document.querySelector('#analysis-video');
const canvas=document.querySelector('#pose-overlay');
const context=canvas.getContext('2d');
const message=document.querySelector('#video-message');
const start=document.querySelector('#video-start');
let job=null,result=null,report=null,blob=null,version=0,upload=null,available=false;
const features={knee_angle_deg:'膝关节二维角度',torso_pitch_deg:'躯干二维倾角',hip_ankle_offset_norm:'髋踝二维相对偏移'};
const states={pending:'待审核',confirmed:'确认可观察变化（非技术错误）',normal_movement:'报告为正常动作',tracking_error:'关键点跟踪误差',uncertain:'证据不足，无法判断'};
const messages={video_prerequisites_missing:'缺少视频隔离环境、模型或FFmpeg，请按视频环境说明安装。',video_session_expired:'视频会话已过期，请刷新页面。',video_size_limit:'视频超过25MiB。',unsupported_container:'文件不是支持的MP4/MOV容器。',media_limits:'视频超过时长、分辨率或帧率限制。',unsupported_codec:'本机不支持此视频编码。',unreadable_video:'视频无法解码或媒体信息异常。',normalization_failed:'视频规范化失败，请更换可解码文件。',pose_runtime_failed:'MediaPipe运行失败，请检查本机模型与环境。',processing_failed:'本机处理失败，可清除任务后重新上传。',review_sequence_conflict:'审核记录已变化，请刷新当前结果后重试。',video_job_not_found:'任务不存在、已删除或不属于当前会话。',delete_previous_video_first:'请先清除上一任务。',video_job_limit:'本机任务已满，请先清理或稍后重试。'};
function status(text){message.textContent=text;}
async function api(path,payload){
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
  try{
    const options={credentials:'same-origin',redirect:'error',signal:controller.signal};
    if(payload!==undefined)Object.assign(options,{method:'POST',headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},body:JSON.stringify(payload)});
    const response=await fetch(base+path,options);
    if(!response.ok){let data={};try{data=await response.json();}catch(_){}throw new Error(messages[data.detail]||(response.status===422?'输入字段或授权声明无效。':response.status===429?'本机资源已达限制，请稍后重试。':'本机视频请求失败，请检查会话或重新上传。'));}
    return await response.json();
  }finally{clearTimeout(timer);}
}
function switchTab(name){
  for(const pane of ['prelesson','video','feedback'])document.querySelector('#'+pane+'-pane').hidden=pane!==name;
  for(const button of document.querySelectorAll('#stage-nav [data-stage]'))button.setAttribute('aria-pressed',String(button.dataset.stage===name));
  if(name==='video')requestAnimationFrame(draw);
}
for(const button of document.querySelectorAll('#stage-nav [data-stage]')){button.addEventListener('click',()=>switchTab(button.dataset.stage));button.disabled=false;}
function clearView(){
  result=null;report=null;document.querySelector('#video-events').replaceChildren();
  document.querySelector('#video-export').disabled=true;document.querySelector('#feedback-export').disabled=true;
  document.querySelector('#feedback-content').hidden=true;document.querySelector('#video-quality').textContent='';
  context.clearRect(0,0,canvas.width,canvas.height);
}
async function clearJob(){
  version++;if(upload)upload.abort();clearView();start.disabled=!available;
  const previous=job;job=null;player.pause();player.removeAttribute('src');player.load();
  if(blob){URL.revokeObjectURL(blob);blob=null;}
  if(previous)await api('/delete',{job_id:previous});
}
document.querySelector('#video-file').addEventListener('change',async()=>{
  try{await clearJob();const file=document.querySelector('#video-file').files[0];if(file){blob=URL.createObjectURL(file);player.src=blob;status('仅在当前浏览器预览；点击分析后发送到本机服务。');}}catch(error){status(error.message);}
});
document.querySelector('#video-delete').addEventListener('click',async()=>{try{await clearJob();status('本机任务已清除；已经导出的文件需您自行保管或删除。');}catch(error){status(error.message);}});
function sendFile(key,file,format,progress){
  return new Promise((resolve,reject)=>{
    const request=new XMLHttpRequest();upload=request;
    request.open('POST',base+'/upload?job_id='+encodeURIComponent(key)+'&format='+format);
    request.setRequestHeader('Content-Type',format==='mov'?'video/quicktime':'video/mp4');
    request.setRequestHeader('X-CoachLoop-Console','1');request.timeout=120000;
    request.upload.onprogress=event=>{if(event.lengthComputable)progress(Math.round(event.loaded/event.total*100));};
    request.onload=()=>{if(upload===request)upload=null;let data={};try{data=JSON.parse(request.responseText);}catch(_){}if(request.status===200)resolve(data);else reject(new Error(messages[data.detail]||'上传失败，请清除任务后重试。'));};
    request.onerror=()=>reject(new Error('无法连接本机视频服务。'));
    request.onabort=()=>{if(upload===request)upload=null;reject(new Error('上传已取消。'));};request.ontimeout=()=>reject(new Error('上传超时。'));
    request.send(file);
  });
}
videoForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!videoForm.reportValidity())return;
  const file=document.querySelector('#video-file').files[0];const extension=file&&file.name.match(/\.(mp4|mov)$/i);
  if(!extension||!file.size||file.size>25*1024*1024){status('仅支持非空MP4/MOV，大小不超过25MiB。');return;}
  if(job){status('请先清除上一任务。');return;}
  const current=++version;start.disabled=true;clearView();
  try{
    status('正在创建本机会话任务…');
    const created=await api('/jobs',{side:document.querySelector('#video-side').value,authorized_use:document.querySelector('#video-rights').checked,privacy_acknowledged:document.querySelector('#video-privacy').checked,single_subject_side_view:document.querySelector('#video-single').checked});
    if(current!==version){await api('/delete',{job_id:created.job_id});return;}
    job=created.job_id;
    await sendFile(job,file,extension[1].toLowerCase(),percent=>{if(current===version)status('上传到本机：'+percent+'%（尚未完成姿态识别）');});
    await waitForJob(current);
  }catch(error){if(current===version)status(error.message);}
  finally{if(current===version)start.disabled=false;}
});
async function waitForJob(current){
    for(let i=0;i<400;i++){
      if(current!==version)return;
      const state=await api('/status?job_id='+encodeURIComponent(job));
      if(current!==version)return;
      if(state.state==='failed')throw new Error(messages[state.error]||'处理失败，请清除后重新上传。');
      if(state.state==='ready'){
        result=await api('/result?job_id='+encodeURIComponent(job));
        if(current!==version)return;
        if(result.is_mock!==false||result.authenticated_coach!==false||result.review_verification!=='local_unverified'||result.technical_error_assessment!=='not_assessed')throw new Error('结果来源或审核保护异常。');
        if(blob){URL.revokeObjectURL(blob);blob=null;}
        player.src=base+'/media?job_id='+encodeURIComponent(job);
        renderResult();status('本机真实视频分析完成。所有候选变化待人工复核，审核身份未认证。');return;
      }
      status(state.state==='queued'?'等待本机处理资源…':'本机解码 / MediaPipe / 特征与事件处理中，请稍候…');
      await new Promise(resolve=>setTimeout(resolve,750));
    }
    throw new Error('等待超时，可清除任务后重试。');
}
function renderResult(){
  const quality=result.quality;
  document.querySelector('#video-quality').textContent='真实视频 · 检出 '+quality.detected_frames+'/'+quality.source_frames+' 帧；检出比例 '+(quality.valid_frame_ratio*100).toFixed(1)+'%。检出不代表几何有效或技术正确。候选事件 '+result.review.records.length+' 条。';
  const events=document.querySelector('#video-events');events.replaceChildren();
  if(!result.review.records.length){const p=document.createElement('p');p.textContent='未检出满足当前探索性参数的候选变化，不表示动作正确。';events.append(p);}
  for(const record of result.review.records){
    const data=record.original_event;const box=document.createElement('article');box.className='video-event';
    const title=document.createElement('h3');title.textContent=(features[data.feature]||data.feature)+' · '+(data.start_time_ms/1000).toFixed(2)+'–'+(data.end_time_ms/1000).toFixed(2)+'秒';
    const detail=document.createElement('p');detail.textContent='事件 '+record.event_id+'；相对基线偏离量 '+data.deviation_max+'；当前：'+states[record.review_status]+'；审核序列 '+record.review_history.length+'。本地操作者未认证。';
    const seek=document.createElement('button');seek.type='button';seek.className='secondary';seek.textContent='跳转原片时间';seek.addEventListener('click',()=>{player.currentTime=data.start_time_ms/1000;player.pause();draw();});
    const choice=document.createElement('select');choice.setAttribute('aria-label','事件状态 '+record.event_id);
    for(const [value,label] of Object.entries(states)){const option=document.createElement('option');option.value=value;option.textContent=label;choice.append(option);}choice.value=record.review_status;
    const note=document.createElement('input');note.maxLength=500;note.placeholder='审核备注（不填写真实姓名、健康记录）';note.value=record.notes;note.setAttribute('aria-label','审核备注 '+record.event_id);
    const save=document.createElement('button');save.type='button';save.textContent='提交本地未认证审核';
    save.addEventListener('click',async()=>{
      save.disabled=true;const reviewedJob=job,current=version;
      try{await api('/review',{job_id:reviewedJob,event_id:record.event_id,status:choice.value,note:note.value,expected_sequence:record.review_history.length,request_id:crypto.randomUUID()});
        if(current!==version)return;const updated=await api('/result?job_id='+encodeURIComponent(reviewedJob));if(current!==version)return;result=updated;report=null;document.querySelector('#feedback-content').hidden=true;document.querySelector('#feedback-export').disabled=true;renderResult();status('操作已追加到本地审核历史。身份未认证，不构成正式技术结论。');
      }catch(error){status(error.message);}finally{save.disabled=false;}
    });
    box.append(title,detail,seek,choice,note,save);events.append(box);
  }
  document.querySelector('#video-export').disabled=false;
}
const connections=[[11,12],[11,23],[12,24],[23,24],[11,13],[13,15],[12,14],[14,16],[23,25],[25,27],[24,26],[26,28],[27,31],[28,32]];
function draw(){
  canvas.width=player.clientWidth;canvas.height=player.clientHeight;context.clearRect(0,0,canvas.width,canvas.height);
  if(!result||!result.keypoints.length||!player.videoWidth||!player.videoHeight)return;
  const renderedWidth=Math.min(canvas.width,canvas.height*player.videoWidth/player.videoHeight);
  const renderedHeight=renderedWidth*player.videoHeight/player.videoWidth;
  const offsetX=(canvas.width-renderedWidth)/2,offsetY=(canvas.height-renderedHeight)/2;
  const ms=player.currentTime*1000;let frame=result.keypoints[0];
  for(const point of result.keypoints){if(Math.abs(point.timestamp_ms-ms)<Math.abs(frame.timestamp_ms-ms))frame=point;}
  const landmarks=new Map(frame.landmarks.map(point=>[point.id,point]));
  context.strokeStyle='#4be7b1';context.fillStyle='#4be7b1';context.lineWidth=2;
  for(const [a,b] of connections){const left=landmarks.get(a),right=landmarks.get(b);if(!left||!right||left.visibility<0.5||right.visibility<0.5)continue;context.beginPath();context.moveTo(offsetX+left.x*renderedWidth,offsetY+left.y*renderedHeight);context.lineTo(offsetX+right.x*renderedWidth,offsetY+right.y*renderedHeight);context.stroke();}
  const valid=frame.landmarks.filter(point=>Number.isFinite(point.visibility));
  const visibility=valid.length?valid.reduce((sum,p)=>sum+p.visibility,0)/valid.length:0;
  document.querySelector('#frame-quality').textContent='分析帧 '+frame.frame_idx+'；可见度均值 '+visibility.toFixed(2)+'；骨架显示可见度0.5为UI绘制假设，不是技术或安全合格线。原片重采样误差与缺失需人工复核。';
}
player.addEventListener('timeupdate',draw);player.addEventListener('seeked',draw);player.addEventListener('loadedmetadata',draw);window.addEventListener('resize',draw);
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
document.querySelector('#video-export').addEventListener('click',async()=>{try{if(job){const current=version;const data=await api('/result?job_id='+encodeURIComponent(job));if(current!==version)return;download(data,'coachloop-real-video.local-unverified.json');}}catch(error){status(error.message);}});
document.querySelector('#feedback-refresh').addEventListener('click',async()=>{
  const target=document.querySelector('#feedback-message');
  if(!job||!result){target.textContent='请先完成本机视频分析。';return;}
  const current=version;
  try{const next=await api('/feedback?job_id='+encodeURIComponent(job));if(current!==version)return;report=next;if(report.requires_teacher_review!==true||report.authenticated_coach!==false||report.review_status!=='draft'||report.technical_error_assessment!=='not_assessed'||report.trusted_observations.length)throw new Error('反馈保护校验失败。');
    const area=document.querySelector('#feedback-content');area.replaceChildren(render(report));area.hidden=false;document.querySelector('#feedback-export').disabled=false;target.textContent='反馈草稿已生成：本地审核未认证，等待教师专业复核。';
  }catch(error){report=null;document.querySelector('#feedback-content').hidden=true;document.querySelector('#feedback-export').disabled=true;target.textContent=error.message;}
});
document.querySelector('#feedback-export').addEventListener('click',()=>{if(report)download(report,'coachloop-postlesson.local-unverified.draft.json');});
const initialVersion=version;
api('/capabilities').then(async data=>{
  available=data.available;document.querySelector('#video-capabilities').textContent=data.available?'环境文件与工具已就绪；实际解码和MediaPipe运行仍需视频验证。':'缺少：'+data.missing.join('、')+'。请先运行视频环境准备脚本；备课仍可使用。';start.disabled=!data.available;
  const active=await api('/current');
  if(active&&version===initialVersion&&!job){
    job=active.job_id;const current=++version;
    if(['queued','running','ready'].includes(active.state)){status('正在恢复当前浏览器的本机任务…');await waitForJob(current);}
    else status('上一任务未完成或失败，请清除任务后重新上传。');
  }
}).catch(error=>{status(error.message);});
window.addEventListener('beforeunload',()=>{if(blob)URL.revokeObjectURL(blob);});
})();
