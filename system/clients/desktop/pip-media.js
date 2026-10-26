/* PiP replay export (the corner button, F1) and live autobot state (F3 toggles the autobot through the control plane).
   No microphone or client-side audio mix. */
(function(root) {
  'use strict';
  const SECONDS = 180;
  const ARM_MS = 350, STATUS_JOB_MS = 30000;   // the icon answers only once shown; a status read never hangs the UI
  const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/><path d="M17 17h5m-2.5-2.5V22"/></svg>';
  const CSS = `.pip-media{position:fixed;inset:auto 0 0;z-index:110;pointer-events:none;height:50px;color:#fff;font:11px system-ui;-webkit-app-region:no-drag}
    .pip-media[hidden]{display:none!important}.pip-autobot{position:absolute;left:10px;bottom:8px;opacity:.5;text-shadow:0 1px 3px #000;animation:pip-autobot-pulse 3s ease-in-out infinite}
    .pip-autobot[hidden]{display:none}.pip-replay{position:absolute;right:8px;bottom:7px;width:32px;height:32px;display:grid;place-items:center;padding:5px;border:1px solid #ffffff50;border-radius:6px;background:#111a;color:#fff;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s;-webkit-app-region:no-drag}
    .pip-replay svg{width:22px;height:22px}.pip-corner{position:absolute;right:0;bottom:0;width:96px;height:72px;pointer-events:auto;-webkit-app-region:no-drag}.pip-corner:hover .pip-replay,.pip-replay:focus-visible{opacity:.85;pointer-events:auto}.pip-replay:disabled{cursor:progress}
    .pip-replay-status{position:absolute;right:46px;bottom:10px;max-width:calc(100vw - 125px);padding:3px 5px;border-radius:3px;background:#000b;font-size:10px;text-align:right;overflow-wrap:anywhere}.pip-replay-status:empty{display:none}
    .pip-media[data-error=true] .pip-replay-status{color:#ffb7b7}@keyframes pip-autobot-pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){.pip-autobot{animation:none}}`;
  const valid = sid => typeof sid === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(sid) && sid.includes('-');
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  // "409 {"detail":"lilspark ... is offline"}" (the desktop's API error) -> the detail the server wrote for the operator
  function readable(error) {
    const text = String(error?.message ?? error ?? '');
    const m = /^\d{3}\s+(\{[\s\S]*\})\s*$/.exec(text);
    if (m) try { const body = JSON.parse(m[1]); if (typeof body.detail === 'string') return body.detail; } catch {}
    return text || 'The request failed';
  }
  // The game a window shows, for F3 / F5 (operator 2026-10-26: "start the Autobot on any game session by pressing the F3
  // key, even if I'm on a different computer"): the PiP stream, else the session page open in the embedded gBox view (a
  // remote game watched there beats a game docked on this PC), else the game docked here, else what the view shows
  // otherwise (its own PiP). Never "a game somewhere": no shown game is null.
  function shownSession({compact = null, docked = null, guest = null} = {}) {
    const page = guest?.tab === 'Sessions' ? guest.session : null;
    for (const sid of [compact, page, docked, guest?.session, guest?.pip, guest?.playing, guest?.active]) if (valid(sid)) return sid;
    return null;
  }
  async function settle(api, job, {delay = wait, now = Date.now, limit = 150000, what = 'The autobot request'} = {}) {
    const deadline = now() + limit;
    while (['queued', 'running'].includes(job?.state)) {
      if (!job.id) throw Error(what + ' has no ID.');
      if (now() >= deadline) throw Error(what + ' is still running; check the task list.');
      await delay(700);
      job = await api('/api/jobs/' + encodeURIComponent(job.id), undefined, 'GET');
    }
    if (job?.state !== 'succeeded') throw Error(job?.error?.message || job?.error || what + ' failed.');
    return job;
  }
  // F3 through the control plane (POST /api/sessions/{sid}/autoplay, gbox/bot_control.py): it follows a replaced session
  // to the game running now and asks the PC that runs it, wherever this window is. The app's requests are the operator's.
  async function autobot(api, sid, body = {op: 'toggle', source: 'F3'}, options = {}) {
    if (!valid(sid)) throw Error('No game is shown here.');
    let job;
    try { job = await settle(api, await api('/api/sessions/' + encodeURIComponent(sid) + '/autoplay', body, 'POST'), options); }
    catch (error) { throw Error(readable(error)); }
    const out = job.output || {};
    return {ok: true, action: out.action, running: out.running, message: out.message || 'Autobot request done.', output: out, job: job.id};
  }
  function create({current, api, save, preferences = async () => ({}), render = () => {},
                   delay = ms => new Promise(resolve => setTimeout(resolve, ms)), now = Date.now,
                   fade = (fn, ms) => { const t = setTimeout(fn, ms); t?.unref?.(); }}) {
    let stopped = false, polling = false, toggling = false;
    const state = {sid:null,autobot:false,busy:false,progress:0,message:'',error:false};
    const paint = () => {if(!stopped)render({...state});};
    async function poll() {
      if(stopped)return;
      const sid = current();
      if(sid !== state.sid){state.sid=sid;state.autobot=false;paint();}
      if(stopped||polling||!valid(sid))return;
      polling=true;
      try {
        const telemetry=await api('/api/autoplay/telemetry/'+encodeURIComponent(sid),undefined,'GET');
        if(!stopped&&current()===sid){state.autobot=telemetry?.running===true&&Number.isFinite(telemetry.age_s)&&telemetry.age_s<15;paint();}
      } catch {if(!stopped&&current()===sid){state.autobot=false;paint();}}
      finally{polling=false;}
    }
    async function job(sid, input, tool='recording', limit=900000) {
      let result=await api('/api/jobs',{tool,agent_use:false,require_worker:sid.split('-')[0],input:{session_id:sid,...input}},'POST');
      const deadline=now()+limit;
      while(['queued','running'].includes(result?.state)){
        if(!result.id)throw Error('The recording job has no ID');
        state.progress=Number(result.progress?.pct)||0;
        state.message=result.progress?.msg||(tool==='recording'?'Preparing the replay…':'Asking the PC that runs this game…');paint();
        if(now()>=deadline)throw Error(input.op==='status'?'The recorder on that PC did not answer; no replay was started.':'Replay export is still running. Check the task list before trying again.');
        await delay(600);
        result=await api('/api/jobs/'+encodeURIComponent(result.id),undefined,'GET');
      }
      if(result?.state!=='succeeded')throw Error(result?.error?.message||result?.error||'Replay export failed');
      return result.output?.result||result.output||{};
    }
    // F3 on the shown game: one control-plane request (status, then start or stop on that game's PC); the answer is
    // shown here and returned for the shell's toast
    async function toggleAutobot(){
      const sid=current();if(stopped||toggling||!valid(sid))return null;
      toggling=true;state.error=false;state.message='Autobot: asking the PC that runs this game…';paint();
      let out;
      try{
        out=await autobot(api,sid,{op:'toggle',source:'F3'},{delay,now,limit:STATUS_JOB_MS*5});
        if(!stopped){state.message=out.message;paint();await poll();}
      }catch(error){out={ok:false,message:readable(error)};state.error=true;state.message=out.message;paint();}
      finally{
        toggling=false;const shown=state.message;
        fade(()=>{if(!toggling&&!state.busy&&state.message===shown){state.message='';state.error=false;paint();}},state.error?12000:6000);
      }
      return out;
    }
    async function exportLast(){
      const sid=current();if(stopped||state.busy||!valid(sid))return;
      state.busy=true;state.error=false;state.message='Preparing the last 3 minutes…';state.progress=0;paint();
      try{
        const status=await job(sid,{op:'status'},'recording',STATUS_JOB_MS);
        if(!(status.status?.av_span_s>=.5))throw Error(status.status?.audio_note||'Game audio is not being captured yet. Replay becomes available as the audio/video ring fills.');
        const options=await preferences(), target=Number(options?.targetMB);
        const result=await job(sid,{op:'export',in_s:SECONDS,out_s:0,target_mb:Number.isFinite(target)&&target>=1&&target<=100?target:20});
        const clip=result.clip;
        if(clip?.audio!==true||!(clip.seconds>=.5&&clip.seconds<=SECONDS+.5))throw Error('The worker did not confirm a three-minute audio/video replay.');
        state.message='Saving the compressed replay…';state.progress=95;paint();
        const saved=await save({...clip,openFolder:true});
        if(!saved?.file)throw Error('The desktop did not confirm a saved replay.');
        const partial=clip.seconds<SECONDS-1?` (${Math.round(clip.seconds)} seconds available)` : '';
        state.message=saved.warning||`Replay saved${partial}.${saved.folderOpened?' Folder opened.':''}`;
        state.error=!!saved.warning;state.progress=100;
      }catch(error){state.error=true;state.message=error.message||String(error);}
      finally{state.busy=false;paint();const shown=state.message;fade(()=>{if(!state.busy&&state.message===shown){state.message='';state.error=false;paint();}},state.error?12000:6000);}
    }
    return {poll,exportLast,toggleAutobot,state:()=>({...state}),stop:()=>{stopped=true;}};
  }
  function mount(host, options){
    host.classList.add('pip-media');host.innerHTML=`<span class="pip-autobot" hidden>autobot</span><span class="pip-replay-status" role="status" aria-live="polite"></span><span class="pip-corner"><button class="pip-replay" type="button" aria-label="Export last 3 minutes of gameplay with audio" title="Save last 3 minutes and open the export folder (F1)">${ICON}</button></span>`;
    const ctl=create({...options,render:state=>{
      host.dataset.busy=String(state.busy);host.dataset.error=String(state.error);
      host.querySelector('.pip-autobot').hidden=!state.autobot;
      host.querySelector('.pip-replay').disabled=state.busy;
      host.querySelector('.pip-replay-status').textContent=state.message;
    }});
    // Export only on a deliberate click of the shown icon (operator 2026-10-24: a stray click in the corner started
    // "Preparing the replay"): the corner arms the button ARM_MS after the pointer arrives; keyboard focus counts as shown.
    const corner=host.querySelector('.pip-corner'),button=host.querySelector('.pip-replay');let armTimer=null;
    corner.addEventListener('pointerenter',()=>{clearTimeout(armTimer);armTimer=setTimeout(()=>{corner.dataset.armed='true';},ARM_MS);});
    corner.addEventListener('pointerleave',()=>{clearTimeout(armTimer);delete corner.dataset.armed;});
    button.onclick=event=>{event.preventDefault();event.stopPropagation();
      if(corner.dataset.armed==='true'||event.detail===0)ctl.exportLast();};
    host.addEventListener('dblclick',event=>event.stopPropagation());
    const timer=setInterval(()=>ctl.poll(),2000);ctl.poll();
    return {...ctl,stop:()=>{clearInterval(timer);ctl.stop();}};
  }
  const api={SECONDS,ARM_MS,CSS,ICON,create,mount,autobot,settle,shownSession,readable};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.GBoxPipMedia=api;
})(globalThis);
