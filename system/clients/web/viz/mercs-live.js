(function(root){
  'use strict';
  const query=new URLSearchParams(root.location.search),doc=root.document;
  const mapHost=doc.getElementById('map');
  let sid=query.get('session_id'),worker=query.get('worker'),map=null,actions=null,busy=false,dead=false,pip=null;
  // Same-origin authenticated API. Never forward credentials to another host.
  const hash=new URLSearchParams(root.location.hash.slice(1));
  let token=hash.get('token')||query.get('token')||'';
  if(!token)try{token=root.localStorage.getItem('gbox_tok')||'';}catch{}
  if(hash.has('token')||query.has('token')){
    hash.delete('token');query.delete('token');
    root.history.replaceState(null,'',root.location.pathname+(query.size?'?'+query:'')+(hash.size?'#'+hash:''));
  }
  const api=async(path,body)=>{
    const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',signal:AbortSignal.timeout(5000),
      headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body===undefined?{}:{'Content-Type':'application/json'})},
      body:body===undefined?undefined:JSON.stringify(body)});
    const out=await response.json();if(!response.ok)throw Error(out.detail||`HTTP ${response.status}`);return out;
  };
  async function refresh(){
    if(busy||dead)return;busy=true;
    try{
      const [sessions,rotation]=await Promise.all([api('/api/sessions?include_ended=false'),api('/api/mercmode')]);
      if(dead)return;
      const live=root.GBoxMercsCurrent.current(sid,sessions,rotation.hosts,worker);
      if(!live){doc.getElementById('status').textContent='Waiting for the selected computer’s active Mercenaries round.';return;}
      worker=live.worker_id||live.session_id.split('-')[0];
      if(!map||sid!==live.session_id){
        sid=live.session_id;map?.stop();root.GBoxTacticalMap.detach();actions?.dispose();
        mapHost.innerHTML=root.GBoxTacticalMap.html(sid);
        map=root.GBoxTacticalMap.mount(mapHost.ownerDocument,{sid,api});
        actions=root.GBoxStreamInterventions.mount(doc.getElementById('actions'),{sid:()=>sid,api});
      }
      doc.getElementById('title').textContent=live.title||'Live Mercenaries map';
      doc.getElementById('status').textContent='Following the active round';
    }catch(error){doc.getElementById('status').textContent=error.message;}finally{busy=false;}
  }
  doc.getElementById('pip').onclick=async()=>{
    try{
      if(!root.documentPictureInPicture)throw Error('Map PiP is unavailable in this browser. Use GBox’s always-on-top live map.');
      if(pip&&!pip.closed){pip.focus();return;}
      pip=await root.documentPictureInPicture.requestWindow({width:640,height:480});
      for(const sheet of doc.querySelectorAll('style,link[rel=stylesheet]'))pip.document.head.append(sheet.cloneNode(true));
      pip.document.body.append(mapHost);
      pip.addEventListener('pagehide',()=>doc.body.append(mapHost),{once:true});
    }catch(error){doc.getElementById('status').textContent=error.message;}
  };
  const timer=setInterval(refresh,1000);refresh();
  root.addEventListener('pagehide',()=>{dead=true;clearInterval(timer);map?.stop();actions?.dispose();pip?.close();},{once:true});
})(window);
