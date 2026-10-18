/* Provider outcome explorer. Uses retained evidence only; never dispatches work. */
(function(root) {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const CATEGORIES={resolved:['Request resolved','#78d4a8'],merged:['PR merged','#a6b6ff'],published:['PR published','#6ec6df'],active:['Active','#f1cc76'],failed:['Failed run','#e590a3'],ended:['Run ended; no verified delivery','#8998b2'],reported:['Reported; unverified','#c6a1d9'],unknown:['State unrecorded','#69768d']};
  const PAGE_SIZE=24;
  const isActive=r=>['running','claimed','queued','in_progress','waiting'].includes(r.state);
  const timestamp=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
  const link=v=>{try{const u=new URL(v);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch{return '';}};
  const linkLabel=v=>{const u=new URL(v), pr=u.hostname==='github.com'&&u.pathname.match(/^\/[^/]+\/[^/]+\/pull\/(\d+)\/?$/);return pr?'GitHub PR #'+pr[1]:'Open recorded evidence';};
  function category(record) {
    const verified=record.outcomes.filter(o=>o.verified===true);
    if(verified.some(o=>o.kind==='request_resolved'))return 'resolved';
    if(verified.some(o=>['pr_merged','pr_reviewed_merge'].includes(o.kind)))return 'merged';
    if(verified.some(o=>o.kind==='pr_published'))return 'published';
    if(isActive(record))return 'active';
    if(['failed','error'].includes(record.state))return 'failed';
    if(record.outcomes.some(o=>o.verified!==true))return 'reported';
    return ['completed','succeeded','done','cancelled','canceled'].includes(record.state)?'ended':'unknown';
  }
  function records(data,device) {
    const seen=new Set(), out=[];
    for(const r of data.runs||[]) {
      if(r.device_id!==device||seen.has('run:'+r.id))continue;
      seen.add('run:'+r.id);
      out.push({...r,key:'run:'+r.id,kind:'run',tickets:r.tickets||[],outcomes:r.outcomes||[],title:r.title||'Untitled run'});
    }
    for(const c of data.contributions||[]) {
      if(c.device_id!==device||c.run_id!=null||seen.has('contribution:'+c.id))continue;
      seen.add('contribution:'+c.id);
      out.push({...c,key:'contribution:'+c.id,kind:'contribution',state:'historical',tickets:c.ticket?[c.ticket]:[],outcomes:c.outcomes||[],
        title:c.ticket?.title?(c.ticket.number?'#'+c.ticket.number+': ':'')+c.ticket.title:c.outcomes?.[0]?.title||'Historical contribution'});
    }
    for(const r of out) {
      const times=[r.finished,r.started,r.published_at,...r.outcomes.filter(o=>o.kind!=='request_status').map(o=>o.observed_at)].map(timestamp).filter(v=>v!==null);
      r.at=times.length?Math.max(...times):null;r.category=category(r);
    }
    return out;
  }
  function ordered(rows,order='newest') {
    return [...rows].sort((a,b)=>a.at===null?(b.at===null?a.key.localeCompare(b.key):1):b.at===null?-1:
      (order==='oldest'?a.at-b.at:b.at-a.at)||a.key.localeCompare(b.key));
  }
  function distribution(rows) {
    return Object.entries(CATEGORIES).map(([key,[label,color]])=>({key,label,color,count:rows.filter(r=>r.category===key).length})).filter(r=>r.count);
  }
  function pie(rows) {
    const values=distribution(rows);let angle=-Math.PI/2;
    const paths=values.map(v=>{
      const next=angle+2*Math.PI*v.count/rows.length;
      const point=a=>`${100+82*Math.cos(a)},${100+82*Math.sin(a)}`;
      const shape=v.count===rows.length?'<circle cx="100" cy="100" r="82"/>':`<path d="M100,100 L${point(angle)} A82,82 0 ${next-angle>Math.PI?1:0} 1 ${point(next)} Z"/>`;
      angle=next;
      return `<g fill="${v.color}"><title>${esc(v.label)}: ${v.count}</title>${shape}</g>`;
    }).join('');
    return `<svg viewBox="0 0 200 200" role="img" aria-label="Observed entry outcomes: ${esc(values.map(v=>v.label+' '+v.count).join(', ')||'no attributed entries')}">${paths||'<circle cx="100" cy="100" r="82" fill="none" stroke="#46526b" stroke-width="2"/><text x="100" y="104" text-anchor="middle">No entries</text>'}</svg>`;
  }
  function bubble(rows,name,offset=0,selected=null) {
    const nodes=rows.map((r,i)=>{
      const ring=i<12?0:1,n=Math.min(12,rows.length-ring*12),angle=-Math.PI/2+2*Math.PI*(i%12)/Math.max(1,n)+(ring?Math.PI/12:0),radius=ring?165:105;
      return {r,i,x:220+radius*Math.cos(angle),y:200+radius*Math.sin(angle)};
    });
    return `<svg viewBox="0 0 440 400" role="group" aria-label="${esc(name)} task bubble graph, ${rows.length} entries on this page">
      ${nodes.map(n=>`<line x1="220" y1="200" x2="${n.x}" y2="${n.y}" stroke="#495670"/>`).join('')}
      <circle cx="220" cy="200" r="56" fill="#263657" stroke="#9fb8ff"/><text x="220" y="195" text-anchor="middle" class="dwo-center">${esc(name.length>19?name.slice(0,18)+'…':name)}</text><text x="220" y="214" text-anchor="middle">${rows.length} entries</text>
      ${nodes.map(({r,i,x,y})=>`<g role="button" tabindex="0" data-work-select="${esc(r.key)}" aria-label="${offset+i+1}. ${esc(r.title)}. ${esc(CATEGORIES[r.category][0])}" aria-pressed="${selected===r.key}" class="dwo-node${selected===r.key?' selected':''}"><title>${esc(r.title+' — '+CATEGORIES[r.category][0])}</title><circle cx="${x}" cy="${y}" r="20" fill="${CATEGORIES[r.category][1]}"/><text x="${x}" y="${y+4}" text-anchor="middle">${offset+i+1}</text></g>`).join('')}</svg>`;
  }
  function mount(host,options={}) {
    const state={device:null,name:'Provider',rows:[],query:'',category:'all',order:'newest',page:0,selected:null};
    host.classList.add('dwo');
    host.innerHTML=`<div class="dwo-intro"><h3>Outcomes for <span data-work-name></span></h3><p>Recorded runs and historical contributions. PR merges and completed requests are separate outcomes.</p></div><div class="dwo-charts"><section><h4>Task bubble graph</h4><div data-work-bubble></div><p>Bubble numbers match the table. Select an entry to inspect its evidence.</p></section><section><h4>Observed outcomes</h4><div data-work-pie></div><div data-work-legend></div><p>One entry per run or unlinked contribution. Counts describe retained evidence, not unique requests.</p></section></div>
      <div class="dwo-controls"><label>Find an entry<input type="search" data-work-search aria-label="Find an outcome entry" placeholder="Task, request, or PR"></label><label>Outcome<select data-work-category aria-label="Outcome category"><option value="all">All outcomes</option>${Object.entries(CATEGORIES).map(([k,[v]])=>`<option value="${k}">${esc(v)}</option>`).join('')}</select></label><label>Order<select data-work-order aria-label="Outcome order"><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label></div>
      <div class="dwo-paging"><button type="button" data-work-prev>Previous</button><span data-work-count role="status"></span><button type="button" data-work-next>Next</button></div><div class="dwo-table" role="region" aria-label="Chronological task outcomes" tabindex="0"><table><thead><tr><th># / last recorded time</th><th>Task / handling</th><th>State / outcomes</th><th>Requests / PRs</th></tr></thead><tbody></tbody></table></div><p class="dwo-empty" hidden></p>`;
    const $=s=>host.querySelector(s);
    function replace(el,html) {
      if(el.workHTML===html)return;
      const focused=el.contains(document.activeElement)?document.activeElement:null;
      const attr=['data-work-select','data-work-link','data-work-request','data-work-category-pick'].find(k=>focused?.hasAttribute(k));
      const key=attr?focused.getAttribute(attr):null;
      el.innerHTML=html;el.workHTML=html;
      if(attr)[...el.querySelectorAll('['+attr+']')].find(n=>n.getAttribute(attr)===key)?.focus({preventScroll:true});
    }
    function render() {
      const query=state.query.toLowerCase();
      const filtered=ordered(state.rows.filter(r=>(state.category==='all'||r.category===state.category)&&(!query||[r.title,r.current_action,r.request_id,...r.tickets.flatMap(t=>[t.title,t.number,t.id]),...r.outcomes.flatMap(o=>[o.title,o.url])].join(' ').toLowerCase().includes(query))),state.order);
      const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));state.page=Math.max(0,Math.min(state.page,pages-1));
      const offset=state.page*PAGE_SIZE,rows=filtered.slice(offset,offset+PAGE_SIZE);
      $('[data-work-name]').textContent=state.name;
      replace($('[data-work-bubble]'),bubble(rows,state.name,offset,state.selected));
      replace($('[data-work-pie]'),pie(state.rows));
      replace($('[data-work-legend]'),distribution(state.rows).map(v=>`<button type="button" data-work-category-pick="${v.key}" aria-pressed="${state.category===v.key}"><i style="background:${v.color}"></i>${esc(v.label)}<b>${v.count}</b><small>${(100*v.count/state.rows.length).toFixed(1)}%</small></button>`).join(''));
      $('[data-work-count]').textContent=filtered.length?`${offset+1}–${offset+rows.length} of ${filtered.length} entries · page ${state.page+1}/${pages}`:'No matching entries';
      $('[data-work-prev]').disabled=state.page===0;$('[data-work-next]').disabled=state.page+1>=pages;
      replace($('tbody'),rows.map((r,i)=>{
        const outcomes=r.outcomes.map(o=>`<div>${esc(options.outcomeLabel?.(o)||o.title||o.kind)} <small>${o.verified===true?'verified':'reported; attribution unverified'}</small></div>`).join('');
        const links=[...new Set(r.outcomes.map(o=>link(o.url)).filter(Boolean))];
        return `<tr${state.selected===r.key?' class="selected"':''}><td><b>${offset+i+1}</b><time>${r.at===null?'Time unrecorded':esc(new Date(r.at*1000).toLocaleString())}</time></td><td><button type="button" data-work-select="${esc(r.key)}">${esc(r.title)}</button><p>${esc(r.current_action||(r.kind==='contribution'?'Historical contribution; no linked run log.':'No final action recorded.'))}</p><small>${esc(r.attribution?.scope||r.attribution?.boundary||'Attribution details are available in the evidence panel.')}</small></td><td><span class="dwo-result" style="border-color:${CATEGORIES[r.category][1]}">${esc(CATEGORIES[r.category][0])}</span><p>${esc(r.kind==='contribution'?'Run timing unavailable':options.stateLabel?.(r)||r.state||'State unrecorded')}</p>${outcomes}</td><td>${r.tickets.map(t=>`<button type="button" data-work-request="${esc(t.id||r.request_id||'')}">${t.number?'#'+esc(t.number)+' ':''}${esc(t.title||'Open request')}</button>`).join('')}${links.map(u=>`<a href="${esc(u)}" data-work-link="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(linkLabel(u))}</a>`).join('')}${!r.tickets.length&&!links.length?'<small>No linked deliverable</small>':''}</td></tr>`;
      }).join(''));
      $('.dwo-empty').hidden=!!filtered.length;$('.dwo-empty').textContent=state.rows.length?'No entries match these filters.':'No attributed entries are available in the retained evidence for this provider and window.';
    }
    function activate(e) {
      const select=e.target.closest('[data-work-select]');
      if(select){e.preventDefault();const r=state.rows.find(r=>r.key===select.dataset.workSelect);if(r){state.selected=r.key;render();options.onSelect?.(r);}return;}
      const external=e.target.closest('[data-work-link]');if(external){e.preventDefault();options.onExternal?.(external.dataset.workLink);return;}
      const request=e.target.closest('[data-work-request]');if(request?.dataset.workRequest){options.onRequest?.(request.dataset.workRequest);return;}
      const pick=e.target.closest('[data-work-category-pick]');if(pick){state.category=state.category===pick.dataset.workCategoryPick?'all':pick.dataset.workCategoryPick;$('[data-work-category]').value=state.category;state.page=0;render();return;}
      if(e.target.closest('[data-work-prev]')){state.page--;render();}else if(e.target.closest('[data-work-next]')){state.page++;render();}
    }
    host.addEventListener('click',activate);
    host.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('g[data-work-select]'))activate(e);});
    $('[data-work-search]').addEventListener('input',e=>{state.query=e.target.value;state.page=0;render();});
    $('[data-work-category]').addEventListener('change',e=>{state.category=e.target.value;state.page=0;render();});
    $('[data-work-order]').addEventListener('change',e=>{state.order=e.target.value;state.page=0;render();});
    return {state,update(data,device,name,selected){if(device!==state.device){state.page=0;state.query='';state.category='all';$('[data-work-search]').value='';$('[data-work-category]').value='all';}state.device=device;state.name=name;state.rows=records(data,device);state.selected=selected;render();}};
  }
  const api={mount,records,ordered,category,distribution,pie,bubble,link,linkLabel,CATEGORIES,PAGE_SIZE};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.GBoxDeviceOutcomes=api;
})(typeof window==='undefined'?globalThis:window);
