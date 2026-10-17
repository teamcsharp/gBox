/* Shared memory cards use Spark revisions; emulator operations remain pinned to one session. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.GBoxMemoryCards=factory();})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');
  function platformOf(session){const p=String(session.platform||'').toLowerCase().replace(/[^a-z0-9]/g,'');return p.includes('dreamcast')?'dreamcast':p.includes('gamecube')?'gamecube':p;}
  function uuid(){const b=new Uint8Array(16);crypto.getRandomValues(b);b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=[...b].map(v=>v.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
  function open(session,io){
    document.querySelector('#memory-card-manager')?.close();
    const d=document.createElement('dialog');d.id='memory-card-manager';d.setAttribute('aria-labelledby','memory-card-title');
    d.style.cssText='width:min(840px,92vw);max-height:88vh;overflow:auto;background:var(--card,#202027);color:var(--fg,#eee);border:1px solid var(--line,#555);border-radius:12px;padding:18px';
    const platform=platformOf(session),sid=session.sid||session.session_id||'',supported=['dreamcast','gamecube'].includes(platform),isPSO=/phantasy\s*star\s*online/i.test(session.title||'');
    d.innerHTML=`<style>
      #memory-card-manager .mc-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}#memory-card-manager h3{flex:1;margin:0}
      #memory-card-manager article{border:1px solid var(--line,#444);border-radius:7px;margin:10px 0;padding:12px}
      #memory-card-manager p{overflow-wrap:anywhere}#memory-card-manager [role=status]{white-space:pre-wrap;overflow-wrap:anywhere}
      #memory-card-manager .mc-meta{color:var(--mut,#b8b8c5);font-size:12px}#memory-card-manager .mc-warning{color:#ffcd86}
      #memory-card-manager progress{width:130px;height:10px}#memory-card-manager input{max-width:100%;box-sizing:border-box}
      #memory-card-manager ul{padding-left:20px}#memory-card-manager summary{cursor:pointer}#memory-card-manager button{cursor:pointer}
    </style><header class="mc-row"><h3 id="memory-card-title">Memory cards</h3><button type="button" data-refresh title="Refresh cards and emulator connection" aria-label="Refresh memory cards">&#8635;</button><button type="button" data-close aria-label="Close memory-card manager">&#10005;</button></header>
      <p data-context></p><p>Cards are saved to Spark and shared between PCs. A card in use has one writing session; other sessions keep their own changes if a sync conflicts.</p>
      <section aria-label="Inserted memory cards"><h4>Inserted in this session</h4><p data-connection role="status" aria-live="polite">Checking the emulator connection…</p><div data-slots></div>
        <div class="mc-row"><label>Slot <select data-slot aria-label="Memory-card slot"></select></label><button type="button" data-sync disabled>Sync now</button></div></section>
      <p data-operation role="status" aria-live="polite"></p><section aria-label="Spark memory cards"><h4>Spark cards</h4><p data-cloud role="status">Loading shared cards…</p><div data-cards></div></section>
      <section aria-label="Create a memory card"><h4>New card</h4><form class="mc-row"><label>Card name <input name="card_name" required maxlength="80" placeholder="My memory card" aria-label="New memory-card name"></label><button type="submit" data-create>Create blank card</button></form>
        ${isPSO?'<p><button type="button" data-pso>Create an empty PSO card</button></p><p class="mc-meta" data-pso-note></p>':''}<small class="mc-meta">Blank cards start empty; your existing characters and saves remain on their original card. Select a new card below to insert it into this session.</small></section>`;
    const q=s=>d.querySelector(s),defaultSlots=platform==='dreamcast'?['A1','A2','B1','B2','C1','C2','D1','D2']:platform==='gamecube'?['A','B']:[];
    let dead=false,busy=false,generation=0,listVersion=0,cloud={cards:[]},worker=null,selectedSlot=defaultSlots[0]||'',highlight='',loadError='',listed=false;
    const timers=new Set();
    q('[data-context]').textContent=(session.title||'Current game')+' · '+(platform==='dreamcast'?'Dreamcast VMU':platform==='gamecube'?'GameCube memory card':session.platform||'Unknown platform');
    const say=s=>{if(!dead)q('[data-operation]').textContent=s;};
    function bounded(promise,message,ms=12000){let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),ms);timers.add(timer);})]).finally(()=>{clearTimeout(timer);timers.delete(timer);});}
    function command(op,args={}){return bounded(io.api(`/api/sessions/${encodeURIComponent(sid)}/rpc`,{op:'memory_cards',args:{command_id:uuid(),expires:Date.now()/1000+8,input:{op,...args}}}),
      'The emulator did not answer in time. The outcome may be unknown; the operation was not retried. Refresh to inspect the current cards.');}
    function capacity(c){
      if(!c||!Number.isFinite(c.free_blocks)||!Number.isFinite(c.total_blocks))return '<span class="mc-meta">Free space not available</span>';
      const used=Math.max(0,c.total_blocks-c.free_blocks),warning=isPSO&&platform==='dreamcast'&&c.free_blocks<30;
      return `<span class="${warning?'mc-warning':'mc-meta'}">${esc(c.free_blocks)} / ${esc(c.total_blocks)} blocks free</span> <progress max="${esc(c.total_blocks||1)}" value="${esc(used)}" aria-label="Memory-card space used"></progress>${warning?'<p class="mc-warning">PSO needs 30 free blocks for a new guild members file. Choose another card or create a dedicated PSO card.</p>':''}`;
    }
    function files(c){return Array.isArray(c?.files)&&c.files.length?`<details><summary>${c.files.length} saved ${c.files.length===1?'file':'files'}</summary><ul>${c.files.map(f=>`<li>${esc(f.name||'Unnamed save')}${Number.isFinite(f.blocks)?' · '+esc(f.blocks)+' blocks':''}</li>`).join('')}</ul></details>`:'';}
    const leaseOwner=lease=>lease?.session_id||lease?.owner;
    function leaseText(card){const l=card.lease;if(!l)return 'Available';if(leaseOwner(l)===sid)return 'In use by this session';return 'In use on '+String(l.worker_id||'another PC')+' · '+String(leaseOwner(l)||'another session');}
    const leasedElsewhere=card=>!!card?.lease&&leaseOwner(card.lease)!==sid;
    function slotRecords(){return worker?.slots||[];}
    function pendingFor(slot){const current=slotRecords().find(s=>s.slot===slot),chosen=cloud.selection?.[slot]||current?.pending_card_id;return chosen&&chosen!==current?.card_id?chosen:'';}
    function refreshButtons(){
      if(dead)return;const slot=slotRecords().find(x=>x.slot===selectedSlot),available=supported&&!!sid;
      q('[data-create]').disabled=busy||!supported;q('[data-pso]')&&(q('[data-pso]').disabled=busy||!supported);
      q('[data-slot]').disabled=busy||!available;
      q('[data-sync]').disabled=busy||!available||worker?.supported!==true||!slot?.card_id;
      for(const b of d.querySelectorAll('[data-insert]'))b.disabled=busy||!available||worker?.supported!==true||leasedElsewhere(cloud.cards.find(c=>c.id===b.dataset.insert));
      if(q('[data-pso]')){
        q('[data-pso]').textContent=slot?.card_id?'Create PSO card (keep PSO saves)':'Create an empty PSO card';
        q('[data-pso-note]').textContent=slot?.card_id?(platform==='dreamcast'?'Copies only PSO files from the current card\'s last synced revision into a fresh VMU, leaving other games behind.':'Copies the current GameCube card\'s last synced revision, retaining its serial and PSO character identity.')+' Use Sync now first to include recent saves. Your original card stays intact.':'No current shared card is available to copy. This creates a blank card; existing characters remain on their original card.';
      }
    }
    function render(){
      if(dead)return;
      const slots=slotRecords(),names=[...new Set([...defaultSlots,...slots.map(x=>x.slot)])];
      if(!names.includes(selectedSlot))selectedSlot=names[0]||'';
      q('[data-slot]').innerHTML=names.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');q('[data-slot]').value=selectedSlot;
      const visibleSlots=[...slots,...names.filter(slot=>!slots.some(s=>s.slot===slot)&&pendingFor(slot)).map(slot=>({slot,name:worker?'No card inserted':'Current card not inspected'}))];
      q('[data-slots]').innerHTML=visibleSlots.map(s=>{const pending=pendingFor(s.slot);return `<article><div class="mc-row"><b>Slot ${esc(s.slot)} · ${esc(s.name||'Local card')}</b><span class="mc-meta">${esc(s.sync_state||'Sync state unavailable')}${s.revision!==undefined?' · revision '+esc(s.revision):''}</span></div><p>${capacity(s.capacity)}</p>${pending?`<p class="mc-warning">Selected for next launch: ${esc(cloud.cards.find(c=>c.id===pending)?.name||pending)}</p>`:''}${s.message?'<p>'+esc(s.message)+'</p>':''}${s.error?'<p class="mc-warning">'+esc(s.error)+'</p>':''}${files(s.capacity)}</article>`;}).join('');
      const cards=Array.isArray(cloud.cards)?cloud.cards:[];
      q('[data-cards]').innerHTML=cards.map(c=>{const active=slots.some(s=>s.slot===selectedSlot&&s.card_id===c.id),pending=pendingFor(selectedSlot)===c.id,leased=leasedElsewhere(c);
        return `<article${highlight===c.id?' style="border-color:#8e96ff"':''}><div class="mc-row"><b>${esc(c.name)}</b><span class="mc-meta">Revision ${esc(c.revision??0)} · ${esc(leaseText(c))}</span></div><p>${capacity(c.capacity)}</p>${files(c.capacity)}<p><button type="button" data-insert="${esc(c.id)}"${leased?' disabled':''}>${active?'Reinsert in slot '+esc(selectedSlot):pending?'Selected for next launch':'Insert in slot '+esc(selectedSlot)}</button></p></article>`;
      }).join('')||(listed?'<p>No shared cards yet. Create one or refresh to import this session\'s local card.</p>':'');
      q('[data-cloud]').textContent=loadError||(listed?`${cards.length} shared ${cards.length===1?'card':'cards'} on Spark`:'Loading shared cards…');
      refreshButtons();
    }
    async function loadCards(version){
      const request=++listVersion;
      try{const query=new URLSearchParams({platform});if(sid)query.set('session_id',sid);if(session.game_id)query.set('game_id',session.game_id);
        const value=await bounded(io.api('/api/memory-cards?'+query),'Spark did not answer. Refresh to try loading shared cards again.');if(dead||version!==generation||request!==listVersion)return;cloud=value||{cards:[]};if(!Array.isArray(cloud.cards))cloud.cards=[];loadError='';listed=true;render();
      }catch(e){if(!dead&&version===generation&&request===listVersion){loadError='Could not load Spark cards: '+e.message;render();}}
    }
    async function loadStatus(version){
      if(!supported||!sid){q('[data-connection]').textContent=!supported?'Memory-card management is available for Dreamcast and GameCube sessions.':'Open a game session to inspect or insert a memory card.';return;}
      worker=null;render();q('[data-connection]').textContent='Checking the emulator connection…';
      try{const result=await command('status');if(dead||version!==generation)return;worker=result;
        q('[data-connection]').textContent=result.reason||result.message||(result.supported===false?'This worker needs an update before it can manage cards.':result.live_switch?'Card changes can be applied to this running session.':'Card selections take effect on the next game launch.');render();
        // Status can import existing local cards into Spark; list those once inspection completes.
        await loadCards(version);
      }catch(e){if(!dead&&version===generation){worker=null;q('[data-connection]').textContent=e.message;refreshButtons();}}
    }
    function refresh(){const version=++generation;loadCards(version);loadStatus(version);}
    async function act(op,args){
      if(busy||dead||worker?.supported!==true)return;busy=true;refreshButtons();say(op==='sync'?'Synchronizing this card with Spark…':'Selecting this memory card…');
      try{const result=await command(op,args);if(dead)return;if(result.slots)worker=result;say(result.message||result.reason||(result.pending?'Card selected for the next launch.':'Memory-card operation completed.'));render();await loadCards(generation);
      }catch(e){say(e.message);}finally{busy=false;if(!dead)refreshButtons();}
    }
    async function create(name,dedicated){
      if(busy||dead||!supported)return;busy=true;refreshButtons();say('Creating a new shared card on Spark…');
      try{const body={name,platform};if(dedicated&&session.game_id)body.game_id=session.game_id;
        const source=dedicated?slotRecords().find(s=>s.slot===selectedSlot)?.card_id:null;if(source)body.clone_from=source;
        const answer=await bounded(io.api('/api/memory-cards',body),'The card creation response was not confirmed. Refresh before creating another card.');if(dead)return;
        const card=answer.card||answer;highlight=card.id||'';say(`${card.name||name} created${source?' with PSO saves from the source card\'s last synced revision':''}. Select Insert in slot ${selectedSlot||'A1'} to use it${dedicated?'; it is saved as this game\'s default card':''}.`);q('[name=card_name]').value='';await loadCards(generation);
      }catch(e){say(e.message);}finally{busy=false;if(!dead)refreshButtons();}
    }
    q('[data-close]').onclick=()=>d.close();q('[data-refresh]').onclick=()=>{if(!busy)refresh();};
    q('[data-slot]').onchange=()=>{selectedSlot=q('[data-slot]').value;render();};
    q('[data-sync]').onclick=()=>act('sync',{slot:selectedSlot});
    q('[data-cards]').onclick=e=>{const b=e.target.closest('[data-insert]');if(b&&!b.disabled)act('select',{slot:selectedSlot,card_id:b.dataset.insert});};
    q('form').onsubmit=e=>{e.preventDefault();if(q('form').reportValidity()){const name=q('[name=card_name]').value.trim();if(name)create(name,false);}};
    if(q('[data-pso]'))q('[data-pso]').onclick=()=>create('PSO · '+(platform==='dreamcast'?'Dreamcast':'GameCube'),true);
    d.onclose=()=>{dead=true;generation++;for(const timer of timers)clearTimeout(timer);timers.clear();d.remove();io.closed?.();};
    document.body.append(d);d.showModal();render();refresh();return {element:d,close:()=>d.close(),refresh};
  }
  return {open};
});
