(function(root){
  'use strict';
  // The scheduler's playing run is authoritative even while its predecessor
  // remains running in the warm pool. Never adopt a prepared/loading title.
  function current(sid, sessions, hosts, worker=null) {
    if(!Array.isArray(sessions)||!Array.isArray(hosts))return null;
    const host=hosts.find(h=>h?.online===true && typeof h.id==='string' && h.id &&
      (worker ? h.id===worker || h.name===worker : typeof sid==='string' && sid.startsWith(h.id+'-')));
    const run=host?.current_run;
    if(!run || run.phase!=='playing' || typeof run.session_id!=='string' || !run.session_id.startsWith(host.id+'-'))return null;
    return sessions.find(s=>s?.session_id===run.session_id && s.state==='running' && !s.stopping && s.game_id===run.game_id)||null;
  }
  root.GBoxMercsCurrent={current};
  if(typeof module==='object'&&module.exports)module.exports={current};
})(typeof globalThis==='object'?globalThis:this);
