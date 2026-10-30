'use strict';
const login=document.querySelector('#classroom-login');
login.addEventListener('submit',async event=>{
  event.preventDefault();if(!login.reportValidity())return;
  const button=login.querySelector('button');const message=document.querySelector('#login-message');
  button.disabled=true;message.textContent='正在验证课堂访问…';
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
  try{
    const response=await fetch('/classroom/login',{method:'POST',credentials:'same-origin',redirect:'error',
      headers:{'Content-Type':'application/json','X-CoachLoop-Console':'1'},signal:controller.signal,
      body:JSON.stringify({code:login.elements.code.value,mock_acknowledged:login.elements.mock_acknowledged.checked})});
    login.elements.code.value='';
    if(!response.ok)throw new Error(response.status===429?'请求过于频繁，请一分钟后重试。':'无法登录，请核对课堂访问码或联系教师。');
    const data=await response.json();if(data.status!=='signed_in'||data.data_domain!=='mock')throw new Error('登录响应异常。');
    location.replace('/');
  }catch(error){message.textContent=error.name==='AbortError'?'连接超时，请重试。':error instanceof TypeError?'无法连接课堂服务。':error.message;}
  finally{clearTimeout(timer);button.disabled=false;login.elements.code.value='';}
});
