'use strict';
// Connection state is presentation/routing only. No launch, controller or worker
// action is queued or repeated when a connection changes or returns.
function origin(value) { try { const u=new URL(value); return /^https?:$/.test(u.protocol)?u.origin:null; } catch { return null; } }
function create({localUrl,remoteUrl,mode='local',probe,readLocalToken,readRemoteToken,canSwitch=()=>true,
                 onChange=()=>{},now=Date.now,intervalMs=5000,schedule=setTimeout,cancel=clearTimeout}) {
  localUrl=origin(localUrl);remoteUrl=origin(remoteUrl);
  if(!localUrl||!remoteUrl)throw Error('Expected valid local and remote API origins');
  let active=mode==='remote'?'remote':'local',timer=null,pending=null,stopped=false,generation=0;
  const state={local:{ready:false,reason:'Local gBox is starting.'},remote:{ready:false,reason:'Checking remote connection.'}};
  let remoteMisses=0;
  const snapshot=()=>({mode:active,apiUrl:active==='local'?localUrl:remoteUrl,localUrl,remoteUrl,generation,
                       local:{...state.local},remote:{...state.remote}});
  async function check() {
    if(pending)return pending;
    pending=Promise.allSettled([['local',localUrl],['remote',remoteUrl]].map(async([kind,url])=>{
      try {
        const result=await probe(url,kind);
        if(kind==='remote')remoteMisses=0;
        state[kind]={ready:!!result?.ok,...result,checkedAt:now()};
      }
      catch(error){
        // A single slow health probe must not reject all coaching/input requests
        // before they even try the network. Only an established remote route gets
        // two missed probes of grace; actual requests keep their own deadlines.
        // Never grant initial readiness, mask an explicit failure response, or
        // weaken the local worker's process/installation identity checks.
        const retrying=kind==='remote'&&++remoteMisses<3&&state.remote.ready;
        state[kind]={ready:!!retrying,retrying:!!retrying,
          reason:error.message||'Connection unavailable',checkedAt:now()};
      }
      onChange(snapshot()); // local readiness never waits for a remote probe
    })).then(()=>{onChange(snapshot());return snapshot();}).finally(()=>{pending=null;});
    return pending;
  }
  function tick(){check().finally(()=>{if(!stopped)timer=schedule(tick,intervalMs);});}
  return {
    snapshot,check,
    start(){if(stopped)return;tick();},
    stop(){stopped=true;if(timer!==null)cancel(timer);},
    select(mode){
      if(!['local','remote'].includes(mode))throw Error('Choose this PC or the remote library');
      if(mode===active)return snapshot();
      if(!canSwitch())throw Error('Keep the current game in its own connection. Close its view before switching libraries; no game was stopped.');
      active=mode;generation++;onChange(snapshot());return snapshot();
    },
    async token(url=snapshot().apiUrl){
      const key=origin(url);
      if(key===localUrl)return readLocalToken();
      if(key===remoteUrl)return readRemoteToken();
      throw Error('Credentials belong to a different gBox authority');
    },
    ready(url=snapshot().apiUrl){const key=origin(url);return key===localUrl?state.local.ready:key===remoteUrl?state.remote.ready:false;}
  };
}

// A hung SMB read stays one asynchronous attempt, not a fresh libuv task on
// every UI poll. A deadline returns promptly without canceling its ownership.
function tokenReader({read,now=Date.now,deadlineMs=1200,cooldownMs=30000,schedule=setTimeout,cancel=clearTimeout}) {
  let value=null,pending=null,retryAt=0;
  return {
    reset(){value=null;retryAt=0;},
    async get(){
      if(value)return value;
      if(now()<retryAt)return null;
      if(!pending){
        pending=Promise.resolve().then(read).then(result=>{if(typeof result==='string'&&result.trim())value=result.trim();return value;},()=>null)
          .finally(()=>{pending=null;retryAt=now()+cooldownMs;});
      }
      let timer;
      try {return await Promise.race([pending,new Promise(resolve=>{timer=schedule(()=>resolve(null),deadlineMs);})]);}
      finally {if(timer!==undefined)cancel(timer);}
    }
  };
}
module.exports={create,tokenReader,origin};
