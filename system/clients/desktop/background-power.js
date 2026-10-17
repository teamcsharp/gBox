// Keep the physical display awake for an opted-in, idle workstation. This lives
// in the main process so minimizing the renderer cannot suspend the policy.
function create({powerSaveBlocker,status,now=Date.now,schedule=setTimeout,cancel=clearTimeout}) {
  let id=null,timer=null,busy=false,disposed=false,lastGood=null;
  let state={active:false,reason:'Waiting for workstation status',sampledAt:null,error:null};
  function release(reason) {
    if(id!==null){powerSaveBlocker.stop(id);id=null;}
    state={...state,active:false,reason};
  }
  async function poll() {
    if(disposed||busy)return;
    busy=true;
    try {
      const data=await status();
      if(disposed)return;
      lastGood=now();
      const idle=data.worker?.idle_seconds;
      const sessions=data.sessions||[];
      const working=(data.active||[]).length>0 || sessions.some(s=>s.agent_owned===true);
      const eligible=data.online===true && data.background_testing===true &&
        data.worker?.os==='windows' && (working || Number.isFinite(idle) && idle>=300) &&
        !sessions.some(s=>s.agent_owned!==true);
      state={...state,sampledAt:lastGood,error:null};
      if(!eligible)release('Normal display power policy: background work paused, PC active, or status unavailable');
      else {
        if(id===null)id=powerSaveBlocker.start('prevent-display-sleep');
        state={...state,active:powerSaveBlocker.isStarted(id),reason:'Display kept awake for gBox background work and its idle status display'};
      }
    } catch(error) {
      state={...state,error:String(error?.message||error)};
      // A brief control-plane outage must not blank an otherwise valid display.
      if(lastGood===null||now()-lastGood>=60000)release('Status unavailable for 60 seconds; normal display power policy restored');
    } finally {
      busy=false;
      if(!disposed)timer=schedule(poll,10000);
    }
  }
  return {poll,snapshot:()=>({...state}),start(){if(!disposed)timer=schedule(poll,0);},
    dispose(){disposed=true;cancel(timer);release('gBox closed');}};
}
module.exports={create};
