import {research} from '../stores/research.js';import {session} from '../stores/session.js';import {planningApi} from '../api/research.js';import {download} from '../api/client.js';import {runOptions} from '../components/common/business.js';import {status} from '../components/common/status.js';import {table} from '../components/common/table.js';import {actionNames} from '../constants/enums.js';import {esc,fmt,localTime} from '../utils/format.js';import {action,bind,toast} from '../hooks/actions.js';

const PAGE_SIZE=15;
const staleBadge='<span class="status stale">已过期</span>';
function stationsPanel(){
  const st=research.stations;
  if(!st)return '';
  return '<section class="entry-sheet"><h2>工位与剩余工时 <small>两类工位 · 分钟</small></h2>'+
    st.stations.map(s=>'<div class="station-card"><header><b>'+esc(s.name)+'（工位'+esc(s.code)+'）</b>'+
      '<span class="remain">剩余 <strong>'+fmt(s.remaining_minutes)+'</strong> / '+fmt(s.capacity_minutes)+'</span></header>'+
      '<div class="capacity-bar"><i style="--w:'+Math.min(100,Math.round((s.manual_minutes+s.locked_minutes)/Math.max(1,s.capacity_minutes)*100))+'%"></i></div>'+
      '<p class="fine">总工时 '+fmt(s.capacity_minutes)+' · 人工占用 '+fmt(s.manual_minutes)+' · 已锁定 '+fmt(s.locked_minutes)+
      (s.actions.length?' · 动作：'+s.actions.map(a=>esc(a.name)+' '+a.minutes_per_sample+'分钟/件').join('、'):'')+'</p>'+
      (session.user.role==='admin'?'<form class="station-form" data-station="'+esc(s.code)+'"><label>人工占用（分钟）<input name="manual_minutes" type="number" min="0" value="'+s.manual_minutes+'"></label><label>工位总工时（分钟）<input name="capacity_minutes" type="number" min="1" value="'+s.capacity_minutes+'"></label><button type="submit" class="secondary">更新并按新口径重算</button></form>':'')+
      '</div>').join('')+
    (st.none_action?'<p class="fine">'+esc(st.none_action.name)+'不占用任何工位工时。</p>':'')+'</section>';
}
function lossPanel(){
  const lt=research.lossTable;if(!lt)return '';
  const rows=[];
  for(const label of lt.fault_labels)for(const a of lt.actions){
    const e=lt.entries.find(x=>x.fault_label===label&&x.action_code===a.code);
    rows.push({fault:label,action:actionNames[a.code]||a.name,loss:e?e.expected_loss:''});
  }
  return '<section class="entry-sheet"><h2>故障 / 处置损失表 <small>元 · 折后期望</small></h2>'+
    table(rows,[{key:'fault',label:'故障类型'},{key:'action',label:'处置方式'},{key:'loss',label:'期望损失'}],{limit:50})+
    (session.user.role==='admin'?'<details><summary>调整单项期望损失（确认前方案将判过期）</summary><form id="loss-form"><label>故障类型<select name="fault_label">'+lt.fault_labels.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select></label><label>处置方式<select name="action_code">'+lt.actions.map(a=>'<option value="'+esc(a.code)+'">'+esc(actionNames[a.code]||a.name)+'</option>').join('')+'</select></label><label>期望损失（元）<input name="expected_loss" type="number" step="any" min="0" required></label><button type="submit" class="secondary">保存损失口径</button></form></details>':'<p class="fine">仅负责人可调整损失表；调整后待确认方案需重新计算。</p>')+'</section>';
}
function planLedger(){
  if(!research.plans.length)return '<div class="empty">还没有排产方案。在右侧选择已完成研究创建。</div>';
  return '<div class="ledger plan-ledger">'+research.plans.slice(0,10).map(p=>'<a href="#planning" data-plan="'+p.id+'" class="'+(p.id==research.planId?'active':'')+'"><small>#'+p.id+'</small><strong>'+esc(p.name)+'</strong>'+status(p.state)+(p.stale?staleBadge:'')+'<time title="北京时间">'+esc(localTime(p.updated_at))+'</time></a>').join('')+'</div>';
}
async function loadDetail(){
  const id=research.planId;if(!id)return null;
  return await planningApi.plan(id);
}
function detailPanel(p){
  if(!p)return '<div class="empty">选择或创建一个排产方案。</div>';
  const head='<div class="run-title"><h2>'+esc(p.name)+'</h2>'+status(p.state)+(p.stale?'<span class="status stale">口径已变 · 待重算</span>':'')+'<small>#'+p.id+' · 研究 #'+p.run_id+'</small></div>'+
    '<p class="fine">创建 '+esc(p.created_by)+' · '+esc(localTime(p.created_at))+(p.confirmed_by?' · 锁定 '+esc(p.confirmed_by)+' '+esc(localTime(p.confirmed_at)):'')+(p.executed_by?' · 执行 '+esc(p.executed_by):'')+'</p>';
  if(p.state==='computing')return head+'<div class="pending"><span class="spinner"></span><h2>独立 worker 正在排产计算</h2><p>页面自动刷新；中断后可在计算完成前随时重试，不会重复扣减工时。</p></div>';
  if(p.state==='failed')return head+'<div class="failure"><h2>排产计算失败</h2><p>'+esc(p.error)+'</p></div>'+(session.writable?'<button data-recompute="'+p.id+'">重新计算 ↻</button>':'');
  if(!p.result)return head;
  const s=p.result.stats,sum=p.result;
  const metrics='<dl class="metrics plan-metrics"><div><dt>整批期望损失（元）</dt><dd>'+fmt(s.expected_total_loss)+'</dd></div><div><dt>免检 / 快检 / 深检</dt><dd>'+s.action_counts.none+' / '+s.action_counts.quick+' / '+s.action_counts.deep+'</dd></div><div><dt>A工位 占用/剩余</dt><dd>'+s.used_minutes.A+' / '+s.remaining_minutes.A+'</dd></div><div><dt>B工位 占用/剩余</dt><dd>'+s.used_minutes.B+' / '+s.remaining_minutes.B+'</dd></div></dl>';
  const actions='<div class="plan-actions">'+(session.writable?
      (p.state==='ready'?'<button data-confirm="'+p.id+'">确认并锁定工时 ✓</button><button data-recompute="'+p.id+'" class="secondary">按当前口径重算 ↻</button>':'')+
      (p.state==='confirmed'?'<button data-execute="'+p.id+'">执行整批排产 →</button>':'')+
      ((p.state==='ready'||p.state==='confirmed')?'<button data-cancel="'+p.id+'" class="secondary">撤销并释放工时</button>':'')+
      (p.state==='cancelled'?'<span class="fine">方案已撤销，锁定工时已释放。</span>':'')+
      (p.state==='executed'?'<span class="fine">方案已执行，工时保持锁定。</span>':''):'<span class="fine">当前账号只读。</span>')+
    ' <button id="export-plan" class="secondary">下载排产 CSV ↗</button></div>';
  const trace='<aside class="method-sheet trace-sheet"><p class="eyebrow">采用口径可追查</p><p>'+esc(sum.posterior_note||'折外后验来自所选研究')+'</p><p class="fine">研究校验和 <code>'+esc(sum.run_checksum)+'</code><br>口径指纹 <code>'+esc(p.fingerprint)+'</code></p><p class="fine">计算时容量：A 余 '+sum.capacity_snapshot.A+' 分钟 · B 余 '+sum.capacity_snapshot.B+' 分钟</p></aside>';
  const rows=sum.selections.map(x=>({reference:x.reference,action:actionNames[x.action]||x.action,expected_loss:x.expected_loss,
    posterior:Object.entries(x.posteriors).map(([k,v])=>esc(k)+' '+(v*100).toFixed(1)+'%').join(' / '),
    minutes:(x.use_minutes.A||x.use_minutes.B)?(x.use_minutes.A?'A '+x.use_minutes.A:'B '+x.use_minutes.B):'—',
    reason:x.reason}));
  const start=research.planPage*PAGE_SIZE;
  const tableHtml=table(rows,[{key:'reference',label:'样本编号'},{key:'action',label:'选择处置'},{key:'expected_loss',label:'期望损失'},{key:'posterior',label:'完整折外后验'},{key:'minutes',label:'占用工位'},{key:'reason',label:'选择原因'}],{limit:PAGE_SIZE,offset:start});
  const pages=Math.max(1,Math.ceil(rows.length/PAGE_SIZE));
  const pager='<div class="pagination"><button id="plan-prev" '+(research.planPage===0?'disabled':'')+'>上一页</button><span>'+(research.planPage+1)+' / '+pages+'</span><button id="plan-next" '+((research.planPage+1)*PAGE_SIZE>=rows.length?'disabled':'')+'>下一页</button></div>';
  return head+metrics+actions+'<div class="result-grid"><section><h2>逐样本选择 <small>共 '+rows.length+' 条 · 含完整后验与选择原因</small></h2>'+tableHtml+pager+'</section>'+trace+'</div>';
}
export async function planningPage(){
  await research.refreshPlanning(planningApi);
  research.lossTable=await planningApi.lossTable();
  const detail=await loadDetail();research.activePlan=detail;
  const completedRuns=research.runs.filter(r=>r.state==='completed');
  return '<section class="page-heading"><p class="eyebrow">05 / PLAN & CAPACITY</p><h1>把折外后验，落成工时内的整批处置。</h1><p>每个样本在免检、快速复检、停机检修间择一；在两类工位剩余工时内使整批期望损失最小，确认即锁定工时、撤销即释放。</p></section>'+
    '<div class="split planning-split"><section><h2>排产方案台账</h2>'+planLedger()+
      (session.writable?'<form id="plan-form" class="entry-sheet"><h2>新建排产方案</h2><label>已完成研究<select name="run_id">'+runOptions(completedRuns,research.runId,true)+'</select></label><label>方案名称<input name="name" required value="十一月整批检修排产"></label><p class="fine">提交时冻结工位口径、损失表与该研究的完整折外后验；计算期间口径变化将判过期。</p><button type="submit">冻结口径并开始排产 →</button></form>':'<p class="fine">阅读者可查看全部方案与追查口径；创建与确认由分析师或负责人执行。</p>')+
      detailPanel(detail)+'</section><aside>'+stationsPanel()+lossPanel()+'</aside></div>';
}
export function bindPlanning(refresh){
  action('#plan-form',async form=>{const d=Object.fromEntries(new FormData(form));const p=await planningApi.createPlan({run_id:Number(d.run_id),name:d.name});research.planId=p.id;research.planPage=0;await refresh();toast('排产方案已进入 worker 队列')});
  action('#loss-form',async form=>{const d=Object.fromEntries(new FormData(form));d.expected_loss=Number(d.expected_loss);await planningApi.updateLoss(d);await refresh();toast('损失口径已更新，待确认方案需重算')});
  for(const f of document.querySelectorAll('.station-form'))action(f,async form=>{const code=form.dataset.station;const d=Object.fromEntries(new FormData(form));await planningApi.updateStation(code,{manual_minutes:Number(d.manual_minutes),capacity_minutes:Number(d.capacity_minutes)});await refresh();toast('工位工时已更新，待确认方案将判过期')});
  bind('#plan-prev','click',async()=>{research.planPage--;await refresh()});
  bind('#plan-next','click',async()=>{research.planPage++;await refresh()});
  const id=research.planId;if(!id)return;
  bind('#export-plan','click',async()=>{try{await download('/plans/'+id+'/export','maintenance-plan-'+id+'.csv')}catch(e){toast(e.message,true)}});
  const guard=async fn=>{try{await fn();await refresh()}catch(e){toast(e.message,true)}};
  document.querySelector('[data-confirm]')?.addEventListener('click',()=>guard(async()=>{await planningApi.confirm(id);toast('工时已锁定，方案待执行')}));
  document.querySelector('[data-recompute]')?.addEventListener('click',()=>guard(async()=>{await planningApi.recompute(id);toast('已按当前口径重新计算')}));
  document.querySelector('[data-cancel]')?.addEventListener('click',()=>guard(async()=>{await planningApi.cancel(id);toast('方案已撤销，锁定工时已释放')}));
  document.querySelector('[data-execute]')?.addEventListener('click',()=>guard(async()=>{await planningApi.execute(id);toast('整批排产已执行')}));
  if(research.activePlan?.state==='computing')setTimeout(refresh,1500);
}
