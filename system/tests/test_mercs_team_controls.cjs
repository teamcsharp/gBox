const {test}=require('node:test'),assert=require('node:assert/strict');
const M=require('../clients/web/viz/re5-modifiers.js');
const SESSION={session_id:'owned-session',game_id:M.GAME,adapter:'rpcs3',state:'running'};
function rig(session=SESSION){
 const out={calls:[],sessions:[session],active:[],clock:0,team:{config:{role:'solo_p1',training_profile:'assisted',auto_reduce_mods:false,selected_route_id:null},phase:'active',control_player:1,
  capabilities:{teammate_p2:{available:false,reason:'Waiting for native actor and separate Player 2 input.'},prepare_player2:{available:true},unmodified_evaluation:{available:false,reason:'Original settings must be verified; current modifiers retained.'}}}};
 out.api=async(path,body,method)=>{
  out.calls.push({path,body,method});
  if(path.startsWith('/api/sessions'))return out.sessions;
  if(path.startsWith('/api/jobs?'))return out.active;
  if(path.startsWith('/api/jobs/'))return out.poll(path);
  assert.equal(path,'/api/jobs');
  let result;
  if(body.tool==='mercs_team'){
   if(body.input.op==='status')result={status:structuredClone(out.team)};
   else if(out.command)result=await out.command(body.input);
   else if(body.input.op==='configure'){
    const {session_id,op,...patch}=body.input;
    Object.assign(out.team.config,patch);out.team.phase=patch.role==='teammate_p2'?'waiting_p2':patch.role==='observe_human'?'observing_unverified':'active';
    if(patch.role==='teammate_p2'||patch.role==='observe_human')out.team.control_player=null;
    if(patch.training_profile==='unmodified_evaluation'){out.team.phase='waiting_evaluation';out.team.control_player=null;out.team.evaluation_pending=true;}
    result={configuration_verified:true};
   }else if(body.input.op==='prepare_player2'){
    out.team.player2_preparation={player:2,prepared:false,verified:false,requires_relaunch:true,reason:'Saved for next launch; current controller 1 unchanged.'};result={configuration_verified:true};
   }
  }else{
   assert.equal(body.tool,'re5_mods');assert.equal(body.input.op,'status');
   result={status:{infinite_ammo:true,fire_rate_x:80,capabilities:{}}};
  }
  return{id:'job',state:'succeeded',output:{result}};
 };
 out.ctl=M.create({session,api:out.api,teamControls:true,delay:async ms=>{out.clock+=ms;},now:()=>out.clock});
 out.commands=()=>out.calls.filter(c=>c.body&&c.body.input.op!=='status');return out;
}

test('requested P2 uses exact scoped operator job and fresh config without changing modifiers',async()=>{
 const r=rig();await r.ctl.refresh();await r.ctl.setTeam({role:'teammate_p2'});
 assert.deepEqual(r.commands()[0].body,{tool:'mercs_team',agent_use:false,require_worker:'owned',input:{session_id:'owned-session',op:'configure',role:'teammate_p2'}});
 assert.equal(r.ctl.state().team.control_player,null);assert.equal(r.ctl.state().team.phase,'waiting_p2');
 assert.match(r.ctl.state().message,/no Player 1 fallback/);assert.equal(r.ctl.state().status.fire_rate_x,80);
 assert.equal(r.commands().some(c=>c.body.tool==='re5_mods'),false);
});

test('evaluation intent pauses and preserves current assisted settings and opt-in default',async()=>{
 const r=rig();await r.ctl.refresh();await r.ctl.setTeam({training_profile:'unmodified_evaluation'});
 assert.equal(r.ctl.state().team.config.auto_reduce_mods,false);assert.equal(r.ctl.state().team.control_player,null);
 const html=M.html(r.ctl.state());assert.match(html,/Original settings must be verified/);assert.match(html,/Saving roles preserves current modifiers/);
 assert.equal(r.commands().length,1);
});

test('pending team job cannot optimistically claim P2 or dispatch duplicate changes',async()=>{
 const r=rig();await r.ctl.refresh();let done;
 r.command=()=>new Promise(resolve=>{done=()=>{r.team.config.role='teammate_p2';r.team.phase='waiting_p2';r.team.control_player=null;resolve({configuration_verified:true});};});
 const pending=r.ctl.setTeam({role:'teammate_p2'});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(r.ctl.state().team.config.role,'solo_p1');assert.equal(r.ctl.state().busy,true);
 await r.ctl.setTeam({role:'observe_human'});assert.equal(r.commands().length,1);done();await pending;
 assert.equal(r.ctl.state().team.phase,'waiting_p2');assert.equal(r.ctl.state().error,false);
});

test('stale exact sessions and already pending team jobs refuse new requests',async()=>{
 for(const changed of [[],[{...SESSION,state:'ended'}],[{...SESSION,game_id:M.RE6,adapter:'xenia'}]]){
  const r=rig();await r.ctl.refresh();r.sessions=changed;await r.ctl.setTeam({role:'teammate_p2'});
  assert.equal(r.commands().length,0);assert.equal(r.ctl.state().error,true);
 }
 const r=rig();await r.ctl.refresh();r.active=[{id:'pending',tool:'mercs_team',input:{session_id:SESSION.session_id}}];
 await r.ctl.setTeam({role:'teammate_p2'});assert.equal(r.commands().length,0);assert.equal(r.ctl.state().pending,'pending');
});

test('saved config requires actual readback and rejects malformed client intent',async()=>{
 const r=rig();await r.ctl.refresh();
 for(const patch of [{},{role:'foreign'}, {auto_reduce_mods:'true'},{selected_route_id:'../../x'},{arbitrary_memory:1}])await r.ctl.setTeam(patch);
 assert.equal(r.commands().length,0);
 r.command=async()=>({configuration_verified:true});await r.ctl.setTeam({role:'teammate_p2'});
 assert.equal(r.ctl.state().error,true);assert.match(r.ctl.state().message,/fresh readback/);
});

test('RE6 PiP shows explicit missing P2 ownership and never dispatches RE5 modifiers',async()=>{
 const r=rig({...SESSION,game_id:M.RE6,adapter:'xenia'});
 r.team.capabilities.teammate_p2.reason='RE6 local Player 2 control and actor ownership are not verified in this runtime.';
 assert.equal(M.panelEligible(r.sessions[0]),true);assert.equal(M.eligible(r.sessions[0]),false);
 await r.ctl.refresh();const html=M.html(r.ctl.state());assert.match(html,/RE6 team and training/);assert.match(html,/RE6 local Player 2/);
 assert.doesNotMatch(html,/data-re5-mod="unlimited_health"/);assert.equal(r.calls.some(c=>c.body?.tool==='re5_mods'),false);
});

test('preparing P2 is an explicit future-launch action and never claims active control',async()=>{
 const r=rig();await r.ctl.refresh();await r.ctl.preparePlayer2();
 assert.deepEqual(r.commands()[0].body.input,{session_id:'owned-session',op:'prepare_player2'});
 assert.match(r.ctl.state().message,/next launch/);assert.equal(r.ctl.state().team.player2_preparation.verified,false);
 assert.equal(r.ctl.state().team.capabilities.teammate_p2.available,false);
});

test('mounted PiP team choices invoke the shared exact-session action',async()=>{
 const r=rig();const fields={'[data-re5-team-role]':{value:'observe_human'},'[data-re5-team-profile]':{value:'assisted'},'[data-re5-team-reduce]':{checked:false}};
 const host={innerHTML:'',querySelector:key=>fields[key]};const ctl=M.mount(host,{session:SESSION,api:r.api});
 await new Promise(resolve=>setImmediate(resolve));
 host.onclick({target:{disabled:false,closest:selector=>selector==='[data-re5-team-save]'?{}:null}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(r.commands()[0].body.input,{session_id:'owned-session',op:'configure',role:'observe_human',training_profile:'assisted',auto_reduce_mods:false});
 assert.match(host.innerHTML,/observing_unverified/);ctl.stop();
});

test('a revoked or completed selected route can be cleared without changing team or modifiers',async()=>{
 const r=rig();r.team.config.selected_route_id='a'.repeat(32);
 const host={innerHTML:'',querySelector:()=>null};const ctl=M.mount(host,{session:SESSION,api:r.api});
 await new Promise(resolve=>setImmediate(resolve));assert.match(host.innerHTML,/Clear selected demonstration/);
 host.onclick({target:{disabled:false,closest:selector=>selector==='[data-re5-team-clear-route]'?{}:null}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(r.commands()[0].body.input,{session_id:'owned-session',op:'configure',selected_route_id:null});
 assert.equal(ctl.state().team.config.role,'solo_p1');assert.equal(ctl.state().team.config.training_profile,'assisted');
 assert.doesNotMatch(host.innerHTML,/Clear selected demonstration/);ctl.stop();
});
