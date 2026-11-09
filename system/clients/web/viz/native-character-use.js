// The bounded RE5 library route selects an owned native Switch counterpart.
(function(root){
  'use strict';
  const GAME='52d15709be0fda1a';
  const SLOTS=['chris','sheva','jill','wesker','josh','excella','barry','rebecca'];
  const SLOT_LABELS={chris:'Chris (BSAA)',sheva:'Sheva (BSAA)',jill:'Jill (mapped costume)',wesker:'Wesker (mapped costume)'};
  const DONORS={re5ps3_chris_normal:'Chris (original PS3 collection)',re5ps3_sheva_normal:'Sheva (original PS3 collection)'};
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  const supports=(game,character)=>game===GAME&&Object.hasOwn(DONORS,character);
  function fields({donor=true}={}){
    return `<label>Target player <select data-native-slot><option value="">Choose the native player slot</option>`+
      SLOTS.map(s=>`<option value="${s}">${SLOT_LABELS[s]||s[0].toUpperCase()+s.slice(1)}</option>`).join('')+`</select></label>`+
      (donor?`<label>Collection character <select data-native-donor><option value="">Choose a library character</option>`+
        Object.entries(DONORS).map(([id,name])=>`<option value="${id}">${escape(name)}</option>`).join('')+`</select></label>`:'')+
      `<small>Uses the character's original Switch archive. The PS3 collection model is not imported. Restarts the title; visual verification is pending.</small>`;
  }
  function input({gameId=GAME,character,slot,sessionId=''}){
    if(!supports(gameId,character))throw Error('Choose an original RE5 Chris or Sheva collection entry for its native Switch counterpart.');
    if(!SLOTS.includes(slot))throw Error('Choose the named target player slot; the current random character is not guessed.');
    return {op:sessionId?'live_use':'use',game_id:gameId,character,slot,session_id:sessionId,launch:false};
  }
  async function waitJob(api,job,{sleep=ms=>new Promise(r=>setTimeout(r,ms)),progress=()=>{}}={}){
    for(let i=0;i<600&&['queued','assigned','running'].includes(job?.state);i++){
      if(job.progress?.msg)progress(job.progress.msg);
      await sleep(1000);
      job=await api('/api/jobs/'+encodeURIComponent(job.id),undefined,'GET');
    }
    if(job?.state!=='succeeded')throw Error(job?.error?.message||job?.error||job?.state||'The job did not finish.');
    return job;
  }
  function scopeText(scope){
    if(scope?.route!=='native_archive_counterpart')throw Error('The writer did not report a native counterpart receipt.');
    const base=s=>String(s||'').split(/[\\/]/).pop();
    return `${scope.requested_character?.name||'Collection character'}: ${base(scope.donor_archive)} replaces ${base(scope.target_archive)}. `+
      'Uses the owned Switch counterpart; the collection GLB is not imported. Visual verification is pending.';
  }
  async function apply(api,options,hooks={}){
    const body=input(options),sid=body.session_id;
    const current=()=>{if(sid&&hooks.currentSessionId&&hooks.currentSessionId()!==sid)
      throw Error('The displayed session changed. Reopen its character controls before applying.');};
    current();
    if(sid){
      const sessions=await api('/api/sessions?include_ended=false',undefined,'GET');
      if(!Array.isArray(sessions)||!sessions.some(s=>s.session_id===sid&&s.state==='running'&&s.game_id===body.game_id))
        throw Error('The selected RE5 session is no longer running. No replacement was submitted.');
    }
    current();
    hooks.progress?.('Building the native Switch counterpart...');
    const job=await waitJob(api,await api('/api/jobs',{tool:'characters',input:body,require_os:'linux'}),hooks);
    const result=job.output?.result||{};
    if(['failed','missing','unsupported'].includes(result.status)||!result.mod)
      throw Error(result.reason||result.message||'The character writer produced no replacement.');
    const scope=scopeText(result.replacement_scope);
    if(result.swap_job){
      hooks.progress?.('Build written. Waiting for the title restart...');
      let swap;
      try{swap=await waitJob(api,await api('/api/jobs/'+encodeURIComponent(result.swap_job),undefined,'GET'),hooks);}
      catch(error){throw Error(`Build ${result.mod} was written, but the title restart failed: ${error.message}`);}
      const session=swap.output?.session_id||swap.output?.result?.session_id;
      if(!session)throw Error(`Build ${result.mod} was written, but the restart reported no session.`);
      return {result,session_id:session,message:`${scope} Restart completed in session ${session}.`};
    }
    if(sid&&result.status==='restarting')throw Error(`Build ${result.mod} was written, but no restart job was reported.`);
    return {result,session_id:null,message:`${scope} ${result.status==='pending_restart'?'Saved pending restart.':'Build written for the next boot.'}`};
  }
  const api={GAME,SLOTS,DONORS,supports,fields,input,waitJob,scopeText,apply};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxNativeCharacterUse=api;
})(typeof window!=='undefined'?window:globalThis);
