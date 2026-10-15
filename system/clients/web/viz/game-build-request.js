/* Game-pinned build requests; closing the dialog never cancels submitted work. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.GBoxGameBuildRequest=factory();})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function uuid(){const b=new Uint8Array(16);crypto.getRandomValues(b);b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;const h=[...b].map(v=>v.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
  function open(game,io){
    document.querySelector('#game-build-request')?.close();
    const d=document.createElement('dialog');d.id='game-build-request';d.setAttribute('aria-labelledby','gbr-title');
    d.style.cssText='width:min(560px,90vw);max-height:85vh;overflow:auto;background:var(--card,#202027);color:var(--fg,#eee);border:1px solid var(--line,#555);border-radius:12px;padding:18px;z-index:100';
    d.innerHTML=`<div style="display:flex;align-items:center;gap:12px"><h3 id="gbr-title" style="flex:1;margin:0">👩 Request a custom build</h3><button type="button" data-close aria-label="Close build request">✕</button></div>
      <p data-game></p><form><label>Request type <select name="kind"><option value="build">New build</option><option value="modification">Modification to this game</option></select></label>
      <p><label>Build recipe <select name="recipe"><option value="agent">Let the system research this request</option>${game.game_id==='49b6a2f65aca26a2'?'<option value="sonic2_player">Sonic 2 sprites replace Mario</option>':''}<option value="photo_face">Photo face from preview</option></select></label></p>
      ${['b7aecee966090bfa','66062703301f4969'].includes(game.game_id)?'<p><label>Mario 64 projection target <select name="projection_scope"><option value="gameplay">Gameplay Mario</option><option value="boot">Boot-screen head (engineering request)</option><option value="both">Both targets (engineering request)</option></select></label></p><p>The boot-screen head has a separate format. The native preview below edits gameplay Mario only.</p>':''}
      <label style="display:block;margin-top:12px">What would you like changed?<textarea name="description" required minlength="3" maxlength="12000" rows="5" style="display:block;width:100%;box-sizing:border-box;margin:6px 0" placeholder="Replace Mario with Sonic using the sprites from Sonic the Hedgehog 2."></textarea></label><div data-face-editor></div>
      ${game.game_id==='49b6a2f65aca26a2'?'<p><button type="button" data-pair-open>Sprite-to-sprite animation editor</button> <small data-pair-status></small></p>':''}
      <small>Requests stay tied to this game and build. The system researches, builds and tests the change. Your running game is kept as it is.</small>
      <p><button type="submit" data-submit>Request build</button></p></form><p role="status" aria-live="polite" data-status></p>
      <h4>Requests for this game</h4><div data-list>Loading…</div>`;
    const q=s=>d.querySelector(s),key='gbox_build_request_'+game.game_id;
    q('[data-game]').textContent=game.title+(game.mod?' · based on '+game.mod:'');
    let clientId=null,signature='',busy=false,dead=false,timer=null,pairMapping={},pairWindow=null;
    try{const draft=JSON.parse(sessionStorage.getItem(key)||'null');if(draft){q('textarea').value=draft.description||'';q('select').value=draft.kind||'build';clientId=draft.clientId;signature=draft.signature||'';}}catch{}
    function draft(){try{sessionStorage.setItem(key,JSON.stringify({description:q('textarea').value,kind:q('select').value,clientId,signature}));}catch{}}
    q('form').oninput=draft;
    const face=globalThis.GBoxSpriteFaceEditor?.mount(q('[data-face-editor]'),game,{api:io.api,url:io.url,changed:()=>{draft();}});
    q('[data-face-editor] details')?.addEventListener('toggle',e=>{d.style.width=e.target.open?'min(1000px,92vw)':'min(560px,90vw)';});
    q('[name=recipe]').onchange=()=>{if(q('[name=recipe]').value==='sonic2_player'&&!q('textarea').value)q('textarea').value='Replace Mario with Sonic using the sprites from Sonic the Hedgehog 2.';draft();};
    if(q('[data-pair-open]'))q('[data-pair-open]').onclick=()=>{pairWindow=globalThis.GBoxSpritePairEditor?.open(game,{api:io.api,onCandidate:(mapping,build)=>{
      pairMapping=mapping;q('[name=recipe]').value='sonic2_player';q('[data-pair-status]').textContent='Edited ROM snapshot selected.';
      if(!q('textarea').value.trim())q('textarea').value='Build Sonic 2 in Mario Bros. using my edited animation crop, scale and frame mappings.';
      if(build)setTimeout(()=>{if(!dead)q('form').requestSubmit();},0);
    }});};
    const say=t=>{if(!dead)q('[data-status]').textContent=t;};
    async function refresh(){
      try{const r=await io.api(`/api/games/${encodeURIComponent(game.game_id)}/build-requests`);if(dead)return;
        q('[data-list]').innerHTML=r.items.map(x=>{
          const job=[...(x.jobs||[])].reverse().find(j=>['running','queued','succeeded','failed','invalid','rejected'].includes(j.state));
          const state=x.build?'Build available'+(x.build.verified?' · verified in game':' · gameplay verification pending'):job?job.state:x.status==='done'?'Build has not been published':x.status;
          return `<article style="border-top:1px solid var(--line,#555);padding:10px 0"><button type="button" data-request="${esc(x.id)}">#${esc(x.number)}</button> <b>${esc(state)}</b><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(x.description)}</p>
            ${job?.progress?`<progress max="100" value="${Number(job.progress.pct)||0}"></progress> ${esc(job.progress.msg)}`:''}
            ${job?.admission_wait?.reason?`<p>${esc(job.admission_wait.reason)}</p>`:''}
            ${job?.error?`<p>${esc(job.error)}</p>`:''}${x.dispatch_error?'<p>Saved; dispatch needs attention. The system can pick up this request from the inbox.</p>':''}
            ${x.build?`<div><button type="button" data-play="${esc(x.build.name)}">Play build</button> <button type="button" data-download="${esc(x.build.name)}">Download to this PC</button> <button type="button" data-builds>Open Builds</button></div>`:''}</article>`;
        }).join('')||'No build requests for this game yet.';
      }catch(e){if(!dead)q('[data-list]').textContent='Could not load requests: '+e.message;}
    }
    q('form').onsubmit=async e=>{
      e.preventDefault();if(busy||!q('form').reportValidity())return;
      const description=q('textarea').value.trim(),kind=q('select').value;
      if(description.length<3)return say('Describe the build you want.');
      const recipe=q('[name=recipe]').value,photo=face?.selection()||{photo:'',mapping:{}};
      if(recipe==='sonic2_player'){photo.photo='';photo.mapping=pairMapping;}
      const projection_scope=q('[name=projection_scope]')?.value||'gameplay';
      if(recipe==='photo_face'&&projection_scope!=='gameplay')return say('Choose the research recipe for a boot-screen or both-target request. The current native writer edits gameplay Mario only.');
      if(recipe==='photo_face'&&!photo.ready)return say('Upload the image, adjust the mapping, and preview the native ROM result first.');
      const next=JSON.stringify([description,kind,game.session_id||'',recipe,photo.photo,photo.mapping,projection_scope]);
      if(!clientId||next!==signature){clientId=uuid();signature=next;}draft();
      busy=true;q('[data-submit]').disabled=true;say('Saving your build request…');
      try{const r=await io.api(`/api/games/${encodeURIComponent(game.game_id)}/build-requests`,{client_id:clientId,session_id:game.session_id||'',kind,description,recipe,photo:photo.photo,mapping:photo.mapping,projection_scope});
        if(dead)return;say(`Request #${r.number} saved. ${r.dispatch_error?'Dispatch needs attention; your request is retained.':'You can close this window while the system works.'}`);
        q('textarea').value='';clientId=null;signature='';draft();await refresh();
      }catch(e){say('Request could not be confirmed: '+e.message+'. Retry uses the same request ID.');}
      finally{busy=false;if(!dead)q('[data-submit]').disabled=false;}
    };
    q('[data-list]').onclick=async e=>{
      const b=e.target.closest('button');if(!b||busy)return;
      if(b.dataset.request)return io.request?.(b.dataset.request);
      if(b.hasAttribute('data-builds')){d.close();return io.builds?.(game.game_id);}
      const name=b.dataset.play||b.dataset.download;if(!name)return;
      busy=true;b.disabled=true;
      try{if(b.dataset.play){d.close();await io.play(game.game_id,name);}else{await io.download(game.game_id,name);say('Download queued. Follow progress in Builds.');}}
      catch(error){say(error.message);}finally{busy=false;b.disabled=false;}
    };
    q('[data-close]').onclick=()=>d.close();
    d.onclose=()=>{dead=true;clearInterval(timer);face?.dispose();pairWindow?.close();draft();d.remove();io.closed?.();};
    document.body.append(d);d.showModal();q('textarea').focus();refresh();timer=setInterval(refresh,5000);
    return {element:d,close:()=>d.close()};
  }
  return {open};
});
