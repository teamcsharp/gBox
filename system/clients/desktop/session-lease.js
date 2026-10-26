(function(root){
  'use strict';
  function cachedRead(fetcher,{authority=()=>'',...options}={}){
    const caches=new Map();
    const make=root.GBoxLivePoll?.cachedRead||(typeof require==='function'?require('./live-poll.js').cachedRead:null);
    function current(){
      const key=authority()||'pending';
      if(!caches.has(key))caches.set(key,make(async()=>{
        const value=await fetcher();
        if((authority()||'pending')!==key||(value?.authority&&value.authority!==key))
          return {ok:false,error:'The connection changed; the old response was not reused.'};
        return value;
      },options));
      return caches.get(key);
    }
    return {get:age=>current().get(age),peek:age=>current().peek(age),refresh:()=>current().refresh(),
      invalidate:()=>{for(const cache of caches.values())cache.invalidate();},age:()=>current().age()};
  }
  function create({probe,now=Date.now}){
    let current=null,lastProbe=-Infinity,pending=null;
    return {
      async resolve(authority,response,{worker,closed=new Set(),only=null}={}){
        if(current&&closed.has(current.session.session_id))current=null;
        // a game whose PC is offline (#2870 worker_online) is never adopted; a docked game stays while its process lives
        const found=response?.ok&&Array.isArray(response.data)?response.data.filter(s=>s.state==='running'&&s.worker_online!==false
          &&s.detail?.local_window&&s.detail.worker_name===worker&&!closed.has(s.session_id)
          &&(!only||s.session_id===only)).sort((a,b)=>(b.started||0)-(a.started||0))[0]:null;
        // Presentation may retain its known PID while unavailable. A different
        // authority's empty list cannot end or replace that session.
        if(found&&(!current||current.authority===authority)){
          current={authority,session:found};return {...current,retained:false};
        }
        if(!current)return null;
        if(now()-lastProbe>=1000&&!pending){
          const before=current;lastProbe=now();
          pending=Promise.resolve().then(()=>probe(before.session.detail.pid)).then(result=>{
            if(current===before&&result?.ok&&result.alive===false)current=null;
          },()=>{}).finally(()=>{pending=null;});
        }
        return current?{...current,retained:true}:null;
      },
      forget(){current=null;},
      current:()=>current
    };
  }
  const api={cachedRead,create};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.GBoxSessionLease=api;
})(typeof globalThis!=='undefined'?globalThis:this);
