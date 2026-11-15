import {datasets,destructions} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {DestructionStatus,DestructionKind} from '../constants/enums.js';

const isAdmin=()=>session.user.role==='admin';
const GROUPS=[
  {key:'pending',label:'待清理',match:o=>o.status==='sealed'||o.status==='clearing'},
  {key:'failed',label:'清理失败',match:o=>o.status==='failed'},
  {key:'destroyed',label:'已销毁',match:o=>o.status==='destroyed'},
];

function itemRows(o){
 const open=(o.items||[]).filter(i=>i.status!=='cleared');
 if(!open.length)return '<p class="hint">全部清除项已完成，凭证仅保留编号与计数。</p>';
 return '<div class="section-title"><h3>未清除项</h3><span>'+open.length+' 项</span></div><table class="mini-table"><thead><tr><th>类型</th><th>状态</th><th>尝试</th><th>定位</th><th>失败原因</th></tr></thead><tbody>'+
  open.map(i=>'<tr><td>'+esc(DestructionKind[i.kind]||i.kind)+'</td><td><span class="status '+esc(i.status)+'">'+(i.status==='failed'?'失败':'待清除')+'</span></td><td>'+i.attempts+'</td><td>'+esc(i.target||('#'+(i.ref_id??'—')))+'</td><td class="err-cell">'+esc(i.last_error||'—')+'</td></tr>').join('')+
  '</tbody></table>';
}

function orderCard(o){
 const c=o.counts||{};
 const counts=['dataset','job','report','delivery','file']
   .map(k=>(DestructionKind[k]||k)+' '+(c[k]??0)).join(' · ');
 return '<article class="destruction-card '+esc(o.status)+'">'
  +'<div class="destruction-head"><div><strong>'+esc(o.code)+'</strong><p>'+esc(o.dataset_name)+'</p></div>'
  +'<span class="status '+esc(o.status)+'">'+esc(DestructionStatus[o.status]||o.status)+'</span></div>'
  +'<dl class="voucher">'
  +'<div><dt>销毁编号</dt><dd>'+esc(o.code)+'</dd></div>'
  +'<div><dt>清除计数</dt><dd>'+esc(counts)+'</dd></div>'
  +'<div><dt>封存时间</dt><dd>'+date(o.sealed_at)+'</dd></div>'
  +'<div><dt>完成时间</dt><dd>'+(o.finished_at?date(o.finished_at):'—')+'</dd></div>'
  +'<div><dt>操作人</dt><dd>'+esc(o.created_by_email)+'</dd></div>'
  +'</dl>'
  +itemRows(o)
  +(o.status==='failed'&&isAdmin()?'<button class="button small" data-retry="'+o.id+'">重试失败项 ↻</button>':'')
  +(o.last_error&&o.status!=='failed'?'<p class="warning">'+esc(o.last_error)+'</p>':'')
  +'</article>';
}

export async function destructionPage(){
 const [orders,allDatasets]=await Promise.all([destructions.list(),datasets.list()]);
 workspace.destructions=orders;
 const destroyedIds=new Set(orders.map(o=>o.dataset_id));
 const candidates=allDatasets.filter(d=>!d.sealed&&!destroyedIds.has(d.id));
 const groups=GROUPS.map(g=>({...g,rows:orders.filter(g.match)}));
 return heading('06 / DATA DESTRUCTION','试点到期批次销毁','封存后立即拦截读取、下载与新建分析；样本、关联结果与归档文件全部永久清除后才显示已销毁。销毁凭证只保留编号、计数、时间与操作人。')
  +(isAdmin()?'<section class="panel"><div class="section-title"><h2>发起批次销毁</h2><span>负责人操作</span></div>'
   +(candidates.length?'<form id="destruction-form" class="inline-form"><label>选择批次<select name="dataset_id">'+candidates.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label><button type="submit" class="primary">封存并开始销毁 ↗</button><p class="hint">发起即封存该批次；重复发起沿用同一销毁记录，不会影响其他批次。</p></form>'
   :'<p class="empty">当前没有可销毁的批次，其他批次均已封存或已销毁。</p>')+'</section>':'')
  +'<section class="panel"><div class="section-title"><h2>销毁记录</h2><span>'+orders.length+' 条</span></div>'
  +'<div class="destruction-tabs">'+groups.map((g,i)=>'<button class="tab '+(i===0?'active':'')+'" data-tab="'+g.key+'">'+esc(g.label)+' ('+g.rows.length+')</button>').join('')+'</div>'
  +groups.map((g,i)=>'<div class="tab-panel" data-panel="'+g.key+'" '+(i===0?'':'hidden')+'>'
    +(g.rows.length?g.rows.map(orderCard).join(''):'<p class="empty">暂无记录。</p>')+'</div>').join('')
  +'</section>';
}

export function bindDestruction(refresh){
 document.querySelectorAll('[data-tab]').forEach(tab=>tab.onclick=()=>{
  document.querySelectorAll('[data-tab]').forEach(t=>t.classList.remove('active'));
  tab.classList.add('active');
  document.querySelectorAll('[data-panel]').forEach(p=>{p.hidden=p.dataset.panel!==tab.dataset.tab;});
 });
 const form=document.querySelector('#destruction-form');
 form?.addEventListener('submit',async e=>{
  e.preventDefault();
  const id=Number(new FormData(form).get('dataset_id'));
  if(!confirm('封存后该批次将无法读取、下载或新建分析，并进入永久清除流程。确认发起？'))return;
  try{await destructions.initiate(id);notify('批次已封存，销毁流程已开始');await refresh();}
  catch(err){notify(err.message,true);}
 });
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{
  try{await destructions.retry(b.dataset.retry);notify('已重新调度失败项');await refresh();}
  catch(err){notify(err.message,true);}
 });
}
