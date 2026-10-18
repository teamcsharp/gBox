/* Native inventory operations stay on the running session's worker. */
(function(root){
 'use strict';
 function supported(s){return root.GBoxRE2Inventory?.supported(s)||s?.platform==='ps2'&&['265819390074bb4e','82173dff3bf1ad6d'].includes(s.game_id);}
 function mount(host,session,io){
  if(!host||!supported(session))return null;
  if(root.GBoxRE2Inventory?.supported(session))return root.GBoxRE2Inventory.mount(host,session,io);
  const sid=session.session_id||session.sid,worker=sid.split('-')[0];let dead=false,busy=false,ready=false,uncertain=false;
  const d=document.createElement('details');d.dataset.dock='native-items';d.open=true;
  d.innerHTML='<summary>Weapon inventory</summary><p data-inventory-status role=status>Reading the native GTA III weapon slots...</p><label>Weapon <select data-weapon></select></label><label>Ammo <input data-ammo type=number min=1 max=99999 value=9999 style="width:75px"></label><div class="bar"><button class=act data-give disabled>Give weapon</button><button class=act data-all disabled>Give all 11 weapons</button><button class=act data-refresh title="Read the current inventory">&#8635;</button></div><div data-owned class=mut></div><p class=mut>Uses the game’s own weapon functions. Detonators and mission objects require their native game flows.</p>';
  host.append(d);const q=s=>d.querySelector(s),note=t=>{if(!dead)q('[data-inventory-status]').textContent=t;};
  function buttons(){if(dead)return;q('[data-give]').disabled=q('[data-all]').disabled=busy||!ready||uncertain;q('[data-refresh]').disabled=busy;}
  async function run(op){
   if(dead||busy||(op!=='list'&&(!ready||uncertain)))return;busy=true;buttons();
   let submitted=false;try{
    const input={session_id:sid,op};
    if(op!=='list'){const ammo=Number(q('[data-ammo]').value);if(!Number.isInteger(ammo)||ammo<1||ammo>99999)throw Error('Choose ammo between 1 and 99999.');input.ammo=ammo;if(op==='give')input.weapon=q('[data-weapon]').value;}
    submitted=true;let job=await io.api('/api/jobs',{tool:'gta3_items',require_worker:worker,input});
    const until=Date.now()+45000;
    while(['queued','running'].includes(job.state)&&Date.now()<until&&!dead){note('Native inventory '+job.state+'...');await new Promise(r=>setTimeout(r,400));if(!dead)job=await io.api('/api/jobs/'+encodeURIComponent(job.id));}
    if(dead)return;
    if(job.state!=='succeeded'){
     if(op!=='list')uncertain=true;
     throw Error((job.error||'The operation has not confirmed completion.')+(op==='list'?'':' No retry was sent. Refresh the inventory before issuing another command.'));
    }
    const result=job.output?.result;
    if(!result?.verified){if(op!=='list')uncertain=true;throw Error('Native inventory read-back was not confirmed. Refresh before issuing another command.');}
    if(op==='list'){
     q('[data-weapon]').replaceChildren();
     for(const row of result.weapons||[]){if(!row.id||row.id===12)continue;const o=document.createElement('option');o.value=String(row.id);o.textContent=row.name;q('[data-weapon]').append(o);}
     ready=true;uncertain=false;
    }
    q('[data-owned]').textContent=(result.inventory||[]).filter(r=>r.present&&r.slot!==0).map(r=>r.name+' ('+r.ammo+')').join(' · ')||'No carried weapons.';
    note(op==='list'?'Native inventory verified.':(op==='all_weapons'?'All 11 ordinary weapons added.':'Weapon added.')+' Native slots and ammunition verified.');
   }catch(e){if(op==='list')ready=false;else if(submitted)uncertain=true;note(e.message+(op!=='list'&&submitted?' Refresh before issuing another command.':''));}
   finally{busy=false;buttons();}
  }
  q('[data-give]').onclick=()=>run('give');q('[data-all]').onclick=()=>run('all_weapons');q('[data-refresh]').onclick=()=>run('list');
  run('list');return {dispose(){dead=true;d.remove();}};
 }
 root.GBoxNativeInventory={supported,mount};
})(typeof window==='undefined'?globalThis:window);
