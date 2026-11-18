// 真实前端模块 + jsdom 驱动测试：渲染、事件、角色权限、完整排产生命周期与导航。
import {JSDOM} from '/tmp/webtest/node_modules/jsdom/lib/api.js';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
const BASE='http://127.0.0.1:19317';
const RUN_ID='ft'+Date.now();
const DB='/tmp/planning_browser_'+RUN_ID+'.db';
if(fs.existsSync(DB))fs.rmSync(DB);
const server=spawn('python3',['-I','/workspace/test-artifacts/gb-0041/harness/serve_test_app.py'],
  {env:{...process.env,TEST_RUN_ID:RUN_ID},stdio:['ignore','pipe','pipe']});
let serveLog='';
server.stdout.on('data',d=>{serveLog+=d;});server.stderr.on('data',d=>{serveLog+=d;});
const shutdown=code=>{try{server.kill('SIGKILL')}catch{};try{fs.rmSync(DB)}catch{};process.exit(code);};
process.on('exit',()=>{try{server.kill('SIGKILL')}catch{}});
process.on('unhandledRejection',e=>{console.error('未处理异常:',e);shutdown(1);});
const t0=Date.now();
while(Date.now()-t0<25000){
  try{const r=await fetch(BASE+'/health');if(r.ok)break;}catch{}
  await new Promise(r=>setTimeout(r,200));
  if(server.exitCode!==null){console.error(serveLog);throw new Error('测试后端启动失败');}
}
try{await (await fetch(BASE+'/health')).json();}catch(e){console.error(serveLog);throw e;}
const dom=new JSDOM('<!doctype html><html><body><div id="notice" hidden></div><div id="app"></div></body></html>',
  {url:BASE+'/#login',pretendToBeVisual:true});
const {window}=dom;
globalThis.window=window;globalThis.document=window.document;
globalThis.HTMLElement=window.HTMLElement;globalThis.Event=window.Event;globalThis.MouseEvent=window.MouseEvent;
globalThis.FormData=window.FormData;globalThis.localStorage=window.localStorage;globalThis.location=window.location;
globalThis.Intl=Intl;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function apiFetch(path,options={}){
  const r=await fetch(BASE+path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
  const body=await r.json();if(!r.ok)throw Object.assign(new Error(body.detail||'http '+r.status),{status:r.statusCode});
  return body;
}
const nativeFetch=globalThis.fetch;
// 模拟生产 nginx：/api/xxx -> 后端 /xxx
globalThis.fetch=(path,options)=>{
  let p=typeof path==='string'?path:String(path);
  if(p.startsWith(BASE+'/api/'))p=p.replace(BASE+'/api/',BASE+'/');
  else if(p.startsWith('/api/'))p=p.slice(4);
  if(!p.startsWith(BASE))p=BASE+p;
  return nativeFetch(p,options);
};
window.fetch=globalThis.fetch;
// 通知元素的 scrollIntoView 在 jsdom 中缺失
window.HTMLElement.prototype.scrollIntoView=function(){};

const {session}=await import('/workspace/frontend/src/stores/session.js');
const {planningApi}=await import('/workspace/frontend/src/api/research.js');
const {research}=await import('/workspace/frontend/src/stores/research.js');
const app=await import('/workspace/frontend/src/app.js');  // 导入即启动 render()

let pass=0;const ok=(cond,msg)=>{if(!cond)throw new Error('断言失败：'+msg);pass++;console.log('  ✓',msg);};
const waitFor=async (fn,timeout=20000)=>{const t=Date.now();let last;while(Date.now()-t<timeout){try{last=fn();if(last)return last}catch(e){last=e}await sleep(100)}throw last||new Error('waitFor 超时');};
const text=()=>document.getElementById('app').textContent;
const click=sel=>{const el=document.querySelector(sel);if(!el)throw new Error('缺少元素 '+sel);el.click();};
const setHash=async h=>{window.location.hash=h;await waitFor(()=>window.location.hash==='#'+h);await sleep(60);};
// 触发与应用一致的重渲染（hashchange 驱动 app.js render），并等待断言条件
const app2refresh=async cond=>{
  window.dispatchEvent(new window.Event('hashchange'));
  if(cond)await waitFor(cond);else await sleep(150);
};
// 以 API 权威状态等待某方案到达指定状态
const waitPlan=async(id,state)=>waitFor(async()=>(await planningApi.plan(id)).state===state);
const waitStale=async(id,stale)=>waitFor(async()=>(await planningApi.plan(id)).stale===stale);

// 0. 未登录显示登录页
await waitFor(()=>text().includes('进入业务研究席'));
ok(text().includes('进入业务研究席'),'匿名访问展示登录页');

// 1. analyst 登录
const login=await apiFetch('/auth/login',{method:'POST',body:JSON.stringify({email:'analyst@acoustic-bayes.demo',password:'Research2026!'})});
session.set(login);
await setHash('planning');
await waitFor(()=>text().includes('把折外后验，落成工时内的整批处置'));
ok(text().includes('快速复检工位')&&text().includes('停机检修工位'),'排产页渲染两类工位');
ok(text().includes('故障 / 处置损失表'),'渲染损失表');
ok(!!document.querySelector('#plan-form'),'分析师可见新建方案表单');
ok(text().includes('剩余'),'页面展示剩余工时');

// 2. 导航 7 项含检修排产
const nav=[...document.querySelectorAll('nav a')].map(a=>a.textContent);
ok(nav.some(x=>x.includes('检修排产'))&&nav.length===7,'导航含 7 个模块且包含检修排产');

// 3. 创建方案，轮询到 ready（以 API 权威状态为准）
document.querySelector('#plan-form [name=name]').value='浏览器整批方案';
document.querySelector('#plan-form').dispatchEvent(new window.Event('submit',{cancelable:true,bubbles:true}));
await waitFor(()=>research.planId,10000);
const pid=research.planId;
await waitFor(async()=>(await planningApi.plan(pid)).state==='ready');
await app2refresh(()=>document.querySelector('.run-title'));
ok((await planningApi.plan(pid)).state==='ready','worker 计算完成，方案进入待确认');
ok(text().includes('整批期望损失'),'展示整批期望损失');
ok(text().includes('完整折外后验')&&text().includes('选择原因'),'逐样本可追查后验与选择原因');
ok(text().includes('口径指纹'),'展示口径指纹（可追查）');

// 4. 方案一：确认锁定 -> 执行（验证锁定、执行门禁与幂等按钮）
const before=await planningApi.stations();
click('[data-confirm]');
await waitFor(async()=>{const p=await planningApi.plan(pid);return p.state==='confirmed';});
await app2refresh(()=>[...document.querySelectorAll('.run-title .status')].some(e=>e.textContent==='已锁定工时'));
const confirmedDetail=await planningApi.plan(pid);
const after=await planningApi.stations();
const used=confirmedDetail.result.stats.used_minutes;
const aAfter=after.stations.find(s=>s.code==='A');
ok(aAfter.locked_minutes===used.A,'确认后 A 工位锁定工时正确：'+aAfter.locked_minutes);
const badges=[...document.querySelectorAll('.run-title .status')].map(e=>e.textContent).join(',');
ok(badges.includes('已锁定工时'),'页面状态显示已锁定工时（徽章：'+badges+'）');
click('[data-execute]');
await waitFor(async()=>(await planningApi.plan(pid)).state==='executed');
await app2refresh(()=>[...document.querySelectorAll('.run-title .status')].some(e=>e.textContent==='已执行'));
ok(text().includes('已执行'),'页面显示已执行');
ok(!document.querySelector('[data-cancel]'),'已执行方案不显示撤销按钮');

// 5. 方案二：确认 -> 撤销释放（验证撤销后该方案锁定精确回退）
const p2=await planningApi.createPlan({run_id:research.runs.find(r=>r.state==='completed').id,name:'撤销验证方案'});
research.planId=p2.id;await app2refresh();
await waitPlan(p2.id,'ready');
const locksBefore=Object.fromEntries((await planningApi.stations()).stations.map(s=>[s.code,s.locked_minutes]));
const capBefore=Object.fromEntries((await planningApi.stations()).stations.map(s=>[s.code,s.remaining_minutes]));
click('[data-confirm]');
await waitFor(async()=>(await planningApi.plan(p2.id)).state==='confirmed');
await sleep(60);
const p2Detail=await planningApi.plan(p2.id);
const p2Used=p2Detail.result.stats.used_minutes;
const locksConfirmed=Object.fromEntries((await planningApi.stations()).stations.map(s=>[s.code,s.locked_minutes]));
ok(locksConfirmed.A===locksBefore.A+p2Used.A&&locksConfirmed.B===locksBefore.B+p2Used.B,
  '方案二确认后按其容量内选择精确锁定（+'+p2Used.A+'/'+p2Used.B+' 分钟）');
ok(p2Used.A<=capBefore.A&&p2Used.B<=capBefore.B,'方案二锁定不超过确认前剩余工时（不超订）');
click('[data-cancel]');
await waitFor(async()=>(await planningApi.plan(p2.id)).state==='cancelled');
await app2refresh(()=>[...document.querySelectorAll('.run-title .status')].some(e=>e.textContent==='已撤销'));
const locksReleased=Object.fromEntries((await planningApi.stations()).stations.map(s=>[s.code,s.locked_minutes]));
ok(locksReleased.A===locksBefore.A&&locksReleased.B===locksBefore.B,'撤销后方案二锁定工时精确释放回撤销前水平');
ok(text().includes('已撤销'),'页面显示已撤销');

// 6. 方案三：占用变化 -> 过期 -> 页面重算恢复新鲜 -> 重新确认
const created=await planningApi.createPlan({run_id:research.runs.find(r=>r.state==='completed').id,name:'重算验证方案'});
research.planId=created.id;await app2refresh();
await waitPlan(created.id,'ready');
// 制造口径变化使其过期：减少人工占用（改变指纹且不挤占已锁定工时，避免被防超订拒绝）
// 工位口径仅负责人可改，单独申请 admin 凭证，不切换当前界面会话
const adminTokenForEdit=(await apiFetch('/auth/login',{method:'POST',body:JSON.stringify({email:'admin@acoustic-bayes.demo',password:'Research2026!'})})).token;
const st0=(await planningApi.stations()).stations.find(s=>s.code==='A');
const newManual=Math.max(0,st0.manual_minutes-10);
const upd=await fetch(BASE+'/planning/stations/A',{method:'PUT',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminTokenForEdit},body:JSON.stringify({manual_minutes:newManual})});
ok(upd.ok,'人工占用调整成功（'+st0.manual_minutes+' -> '+newManual+'）');
await waitStale(created.id,true);
await app2refresh();
ok((await planningApi.plan(created.id)).stale===true,'占用变化后方案标记过期');
// 页面重算
click('[data-recompute]');
await waitPlan(created.id,'ready');
await waitStale(created.id,false);
await app2refresh();
ok((await planningApi.plan(created.id)).stale===false,'重算后口径恢复新鲜');
// 还原占用，再重算一次以纳入原容量
await fetch(BASE+'/planning/stations/A',{method:'PUT',headers:{'Content-Type':'application/json',Authorization:'Bearer '+adminTokenForEdit},body:JSON.stringify({manual_minutes:st0.manual_minutes})});
click('[data-recompute]');
await waitFor(async()=>(await planningApi.plan(created.id)).state==='ready',10000);
await app2refresh();
click('[data-confirm]');
await waitFor(async()=>(await planningApi.plan(created.id)).state==='confirmed');
ok(true,'重算后的方案可正常确认锁定');

// 8. 过期方案：admin 改占用后，待确认方案标记 stale
const staleTarget=await planningApi.createPlan({run_id:research.runs.find(r=>r.state==='completed').id,name:'过期验证方案'});
await waitFor(async()=>(await planningApi.plan(staleTarget.id)).state==='ready',10000);
session.logout();
const adminLogin=await apiFetch('/auth/login',{method:'POST',body:JSON.stringify({email:'admin@acoustic-bayes.demo',password:'Research2026!'})});
session.set(adminLogin);
window.location.hash='planning';
await app2refresh(()=>document.querySelector('.station-form'));
ok(!!document.querySelector('.station-form'),'负责人可见工位占用编辑表单');
const aStation=(await planningApi.stations()).stations.find(s=>s.code==='A');
const target=staleTarget.id;
const cur=aStation.manual_minutes;
const adjusted=Math.max(0,cur-10);  // 减少占用以改变指纹，避免挤占已锁定工时
const r2=await fetch(BASE+'/planning/stations/A',{method:'PUT',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.token},body:JSON.stringify({manual_minutes:adjusted})});
ok(r2.ok,'负责人更新人工占用成功');
const stalePlan=await planningApi.plan(target);
ok(stalePlan.stale===true,'占用变化后待确认方案标记为过期');
research.planId=target;await app2refresh();
ok(text().includes('已过期'),'页面展示过期标记');
// 过期拒绝确认
const denied=await fetch(BASE+'/plans/'+target+'/confirm',{method:'POST',headers:{Authorization:'Bearer '+session.token}});
ok(denied.status===409,'过期方案确认被后端拒绝（409）');
// 还原占用
await fetch(BASE+'/planning/stations/A',{method:'PUT',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.token},body:JSON.stringify({manual_minutes:cur})});

// 9. viewer 权限：只读，无写表单
session.logout();
const vLogin=await apiFetch('/auth/login',{method:'POST',body:JSON.stringify({email:'viewer@acoustic-bayes.demo',password:'Research2026!'})});
session.set(vLogin);
window.location.hash='planning';
// 等待只读图专属文案出现，确保读到的是 viewer 角色重渲染后的 DOM
await app2refresh(()=>text().includes('阅读者可查看全部方案与追查口径'));
ok(!document.querySelector('#plan-form')&&!document.querySelector('.station-form'),'阅读者看不到创建与工位编辑表单');
ok(text().includes('快速复检工位'),'阅读者仍可查看工位与剩余工时');

// 10. 原研究模块照常读取
await setHash('results');
await waitFor(()=>text().includes('折外')||text().includes('交叉验证')||text().includes('GaussianNB')||document.querySelector('#run-select'));
ok(!!document.querySelector('#run-select'),'完整结果页正常，原研究照常读取');
await setHash('overview');
await waitFor(()=>text().includes('本轮业务账册'));
ok(true,'业务总览正常');

console.log('\n前端浏览器（jsdom）测试全部通过 ✔ 共 '+pass+' 项断言');
shutdown(0);
