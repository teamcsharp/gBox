// Bot learning: what hurts the RE Mercenaries bots, what changed, and whether it helped (operator 2026-10-27 ~19:50: "the
// bot on the road to self-improvement"). One read-only GET: /api/mercs/learning (gbox/mercs/learning.py + damage_clusters.py
// + tuner.py). Per title: rounds and deaths per round; the causes of his hits and deaths with their rate per round, trend per
// turn, batch request and the measured effect of the last change; the round faults; the learned tuning in force and its log.
// Shared by the web app (Mercenaries tab) and the desktop app (Control > Bot learning).
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxBotLearning=api;})(globalThis,function(){
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const GAMES=[['','All RE titles'],['re5','RE5 Switch'],['re6','RE6 Switch'],['re5-ps3','RE5 PS3']];
  const num=(v,d=2)=>typeof v==='number'&&isFinite(v)?String(Math.round(v*10**d)/10**d):'–';
  const when=t=>typeof t==='number'&&t>0?new Date(t*1000).toLocaleString([], {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'–';
  const VERDICT={improved:'better',worse:'worse',unchanged:'no change',pending:'measuring',not_improved:'no drop: reopened',
    no_change_live:'no fix live: reopened',kept:'kept',reverted:'reverted',expired:'expired',trial:'on trial'};
  function bars(values){            // the per-turn rates, oldest first, as a tiny bar chart
    const v=(values||[]).filter(x=>typeof x==='number'&&isFinite(x)).slice(-12);
    if(!v.length)return '';
    const top=Math.max(...v,0.001),w=6,h=18;
    return `<svg class="bl-bars" width="${v.length*(w+2)}" height="${h}" viewBox="0 0 ${v.length*(w+2)} ${h}" aria-hidden="true">${
      v.map((x,i)=>{const bh=Math.max(1,Math.round(x/top*h));return `<rect x="${i*(w+2)}" y="${h-bh}" width="${w}" height="${bh}" rx="1"></rect>`;}).join('')}</svg>`;
  }
  function lastEffect(changes,signature){       // the newest change that measured this cause (a tuning trial: its own causes)
    for(const c of [...(changes||[])].reverse()){
      if(c.kind==='tuning'&&Array.isArray(c.causes)&&!c.causes.includes(signature))continue;
      const e=(c.effects||{})[signature];
      if(e&&e.before!=null)return {change:c,effect:e};
    }
    return null;
  }
  function changeLabel(c){
    if(!c)return '';
    if(c.kind==='tuning')return `tuning ${esc(String(c.param||'').split('.').pop())} ${esc(c.old??'shipped')}→${esc(c.new??'shipped')} (${esc(VERDICT[c.status]||c.status||'')})`;
    const what=(c.modules||c.files||[]).map(m=>String(m).split(/[./]/).filter(Boolean).slice(-1)[0]).join(', ');
    return `${esc(c.kind)} ${esc(what)} ${esc(when(c.at))}`;
  }
  function batch(c){
    if(!c.request_id)return c.batchable?'<span class="mut">batch due (next pass)</span>':'<span class="mut">below batch size</span>';
    const verdict=c.last_verdict?` · ${esc(VERDICT[c.last_verdict]||c.last_verdict)}`:'';
    return `#${esc(c.number)} ${esc(c.status||'')}${verdict}`;
  }
  function causeRows(clusters,changes){
    return clusters.map(c=>{
      const le=lastEffect(changes,c.signature);
      const effect=le?`${num(le.effect.before)}→${num(le.effect.after)} /round (${esc(VERDICT[le.effect.verdict]||le.effect.verdict)})`:'<span class="mut">no change measured yet</span>';
      const turns=(c.round_turns||[]).map(t=>t.rate);
      return `<tr><td><b>${esc(c.label)}</b><div class="mut">${esc(c.suspect||'')}</div></td><td class="n">${esc(c.deaths)}</td>
        <td class="n">${num(c.rate_per_round)}</td><td class="n">${num(c.deaths_per_round,3)}</td><td>${bars(turns)} ${esc(c.trend||'')}</td>
        <td>${batch(c)}</td><td>${le?changeLabel(le.change):''}<div>${effect}</div></td></tr>`;
    }).join('');
  }
  function faultRows(faults,changes){
    return faults.filter(f=>!f.error).map(f=>{
      const le=lastEffect(changes,f.signature);
      return `<tr><td><b>${esc(f.label)}</b><div class="mut">${esc(f.suspect||'')}</div></td>
        <td class="n">${esc(f.marked_rounds)}/${esc(f.rounds)} (${num((f.share_of_rounds||0)*100,0)}%)</td><td class="n">${num(f.rate_per_round)}</td>
        <td>${bars((f.turns||[]).map(t=>t.rate))} ${esc(f.trend||'')}</td><td>${batch(f)}</td>
        <td>${le?`${changeLabel(le.change)}<div>${num(le.effect.before)}→${num(le.effect.after)} (${esc(VERDICT[le.effect.verdict]||le.effect.verdict)})</div>`:'<span class="mut">–</span>'}</td></tr>`;
    }).join('');
  }
  function tuning(t){
    const tu=t.tuner||{};
    const over=Object.entries(tu.overrides||{}).map(([stage,p])=>`<li><b>${esc(stage==='*'?'every stage':stage)}</b>: ${
      Object.entries(p).map(([k,v])=>`${esc(k.split('.').pop())}=${esc(v)}`).join(', ')}</li>`).join('');
    const trials=Object.entries(tu.trials||{}).map(([stage,x])=>`<li>${esc(stage==='*'?'every stage':stage)}: ${esc(String(x.param).split('.').pop())} ${esc(x.old??'shipped')}→${esc(x.new)} since ${esc(when(x.at))} (baseline ${num(x.baseline)} /round)</li>`).join('');
    const log=(tu.log||[]).slice(-6).reverse().map(l=>`<li>${esc(when(l.at))} · ${esc(VERDICT[l.status]||l.status)} · ${esc(String(l.param).split('.').pop())} ${esc(l.old??'shipped')}→${esc(l.new??'shipped')} · ${esc(l.reason||'')}</li>`).join('');
    const spots=Object.values(tu.avoid||{}).reduce((n,s)=>n+(s||[]).length,0);
    return `<div class="bl-tuning"><h4>Learned tuning (no code change)</h4>
      ${over?`<ul>${over}</ul>`:'<p class="mut">Shipped values everywhere.</p>'}${spots?`<p>${spots} learned dead-end spot(s) steer relocations.</p>`:''}
      ${trials?`<p>On trial:</p><ul>${trials}</ul>`:''}${log?`<p>Recent steps:</p><ul class="bl-log">${log}</ul>`:''}</div>`;
  }
  function changesList(changes){
    const code=(changes||[]).filter(c=>c.kind!=='tuning').slice(-6).reverse();
    if(!code.length)return '<p class="mut">No bot code change recorded yet (a hot reload or a restart of this title\'s modules).</p>';
    return `<ul class="bl-changes">${code.map(c=>{
      const eff=Object.values(c.effects||{}),better=eff.filter(e=>e.verdict==='improved').length,worse=eff.filter(e=>e.verdict==='worse').length;
      return `<li>${changeLabel(c)} · ${eff.length?`${better} cause(s) better, ${worse} worse`:'measuring'}</li>`;}).join('')}</ul>`;
  }
  function render(d,game=''){
    const titles=d.titles||{},clusters=d.clusters||[],faults=d.round_faults||[];
    const head=`<div class="bl-head"><label>Game <select data-bl-game>${GAMES.map(([v,l])=>`<option value="${v}" ${v===game?'selected':''}>${l}</option>`).join('')}</select></label>
      <button type="button" data-bl-refresh>Refresh</button><span class="mut">last pass ${esc(when((d.last_pass||{}).at))} · a fix must cut its cause ${num((d.target_drop||0.2)*100,0)}% within ${esc(d.effect_rounds||10)} rounds</span></div>`;
    const kills=(d.what_kills_him||[]).length?`<p class="bl-kills"><b>What kills him:</b> ${(d.what_kills_him||[]).slice(0,5).map(esc).join(' · ')}</p>`:'';
    const sections=Object.entries(titles).map(([title,t])=>{
      const mine=clusters.filter(c=>c.title===title),mineF=faults.filter(f=>f.title===title);
      return `<section class="bl-title"><h3>${esc(t.game||title)} <small class="mut">${esc(t.rounds_24h)} rounds in 24 h · ${num(t.deaths_per_round,3)} deaths per round</small></h3>
        ${mine.length?`<table class="bl-table"><thead><tr><th>Cause of his hits and deaths</th><th>Deaths</th><th>Episodes / round</th><th>Deaths / round</th><th>Per turn</th><th>Batch</th><th>Last change → effect</th></tr></thead><tbody>${causeRows(mine,t.changes)}</tbody></table>`:'<p class="mut">No damage recorded in the window.</p>'}
        ${mineF.length?`<table class="bl-table"><thead><tr><th>Round fault</th><th>Rounds</th><th>Per round</th><th>Per turn</th><th>Batch</th><th>Last change → effect</th></tr></thead><tbody>${faultRows(mineF,t.changes)}</tbody></table>`:''}
        <div class="bl-cols">${tuning(t)}<div><h4>Code changes that went live</h4>${changesList(t.changes)}</div></div></section>`;
    }).join('');
    return `<div class="bl">${head}${kills}${sections||'<p class="mut">No rounds or changes recorded yet: the learning pass runs on the Spark once a minute.</p>'}</div>`;
  }
  const STYLE=`.bl-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0}.bl-table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}
    .bl-table th,.bl-table td{border-bottom:1px solid rgba(128,128,128,.25);padding:4px 6px;text-align:left;vertical-align:top}.bl-table td.n{text-align:right;font-variant-numeric:tabular-nums}
    .bl-table .mut,.bl .mut{opacity:.7;font-size:12px}.bl-bars rect{fill:currentColor;opacity:.75}.bl-cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    .bl-title{margin:12px 0 18px}.bl-title h3{margin:6px 0}.bl h4{margin:6px 0}.bl ul{margin:4px 0;padding-left:18px}@media (max-width:760px){.bl-cols{grid-template-columns:1fr}}`;
  function mount({root,api,refreshMs=60000}){
    let game='',stopped=false,timer=null;
    if(root.ownerDocument&&!root.ownerDocument.getElementById('bl-style')){
      const s=root.ownerDocument.createElement('style');s.id='bl-style';s.textContent=STYLE;root.ownerDocument.head.appendChild(s);
    }
    async function load(){
      try{
        const d=await api('/api/mercs/learning'+(game?'?game='+encodeURIComponent(game):''));
        if(!stopped)root.innerHTML=render(d,game);
      }catch(e){if(!stopped)root.innerHTML=`<p class="mut">Bot learning unavailable: ${esc(e.message)}</p>`;}
    }
    const change=e=>{if(e.target&&e.target.matches&&e.target.matches('[data-bl-game]')){game=e.target.value;load();}};
    const click=e=>{const b=e.target&&e.target.closest&&e.target.closest('[data-bl-refresh]');if(b)load();};
    root.addEventListener('change',change);root.addEventListener('click',click);
    if(refreshMs>0&&typeof setInterval==='function')timer=setInterval(load,refreshMs);
    const ready=load();
    return {ready,load,dispose(){stopped=true;if(timer)clearInterval(timer);root.removeEventListener('change',change);root.removeEventListener('click',click);}};
  }
  return {render,mount,bars};
});
