/* RE2 GameCube inventory edits use only the running session's worker. */
(function(root){
 'use strict';
 function supported(s){return s?.platform==='gamecube'&&s.game_id==='c6adbfa00c20aaf9';}
 function mount(host,session,io){
  if(!host||!supported(session))return null;
  const sid=session.session_id||session.sid,worker=sid.split('-')[0];
  let dead=false,busy=false,uncertain=false,available=false,current=null;
  const d=document.createElement('details');d.dataset.dock='native-items';d.open=true;
  d.innerHTML='<summary>Inventory &amp; equipment</summary><p data-re2-status role=status>Reading inventory...</p><p class=mut>Open the game inventory, select an item, and close any action menu before editing. Applying a change closes the inventory and loads the selected equipment.</p><label>Storage <select data-re2-region><option value=inventory>Carried items</option><option value=box>Item box</option></select></label><label>Slot <select data-re2-slot></select></label><label>Item <select data-re2-item></select></label><label>Quantity <input data-re2-qty type=number min=0 max=255 value=1 style="width:75px"></label><div class=bar><button class=act data-re2-set disabled>Replace item</button><button class=act data-re2-equip disabled>Equip slot</button><button class=act data-re2-unequip disabled>Unequip</button><button class=act data-re2-refresh>Refresh</button></div><div data-re2-owned class=mut></div>';
  host.append(d);const q=s=>d.querySelector(s),note=t=>{if(!dead)q('[data-re2-status]').textContent=t;};
  function row(){const rows=q('[data-re2-region]').value==='box'?current?.item_box:current?.inventory;return rows?.find(r=>r.slot===Number(q('[data-re2-slot]').value));}
  function buttons(){
   if(dead)return;const blocked=busy||uncertain||!available||!current?.editable,r=row();
   q('[data-re2-set]').disabled=q('[data-re2-unequip]').disabled=blocked;
   q('[data-re2-equip]').disabled=blocked||q('[data-re2-region]').value!=='inventory'||!current?.weapons?.some(w=>w.id===r?.item_id&&w.id>0);
   q('[data-re2-refresh]').disabled=busy;
   for(const key of ['region','slot','item','qty'])q('[data-re2-'+key+']').disabled=busy;
  }
  function selected(){const r=row();if(r){q('[data-re2-item]').value=String(r.item_id);q('[data-re2-qty]').value=String(r.quantity);}buttons();}
  function slots(){
   const box=q('[data-re2-region]').value==='box',previous=q('[data-re2-slot]').value;
   q('[data-re2-slot]').replaceChildren();
   for(const r of (box?current?.item_box:current?.inventory)||[]){
    if(!box&&r.slot>=current.capacity)continue;
    const o=document.createElement('option');o.value=String(r.slot);o.textContent=(r.slot+1)+': '+r.name+' ('+r.quantity+')'+(r.size_marker===2?' - second slot':'')+(r.equipped?' - equipped':'');q('[data-re2-slot]').append(o);
   }
   if([...q('[data-re2-slot]').options].some(o=>o.value===previous))q('[data-re2-slot]').value=previous;
   selected();
  }
  function display(result){
   current=result;q('[data-re2-item]').replaceChildren();
   for(const r of result.items||[]){const o=document.createElement('option');o.value=String(r.id);o.textContent='0x'+r.id.toString(16).toUpperCase().padStart(2,'0')+' - '+r.name;q('[data-re2-item]').append(o);}
   slots();q('[data-re2-owned]').textContent='Equipped: '+((result.items||[]).find(r=>r.id===result.equipped?.item_id)?.name||'None')+'. '+result.capacity+' carried slots.';
  }
  async function run(op){
   if(dead||busy||(op!=='list'&&(uncertain||!available||!current?.editable)))return;
   busy=true;buttons();let submitted=false;
   try{
    available=false;
    const workers=await io.api('/api/workers'),owner=Array.isArray(workers)?workers.find(w=>w.id===worker):null;
    if(dead)return;
    if(!owner||!owner.online)throw Error('The game session worker is unavailable. Refresh when it reconnects.');
    if(owner.os!=='windows')throw Error('RE2 inventory controls require Windows Dolphin. They are unavailable for this '+(owner.os||'unknown')+' session.');
    if(!owner.tools?.includes('re2gc_items'))throw Error(owner.unavailable?.re2gc_items||'This game session worker has not loaded the RE2 inventory tool. Refresh after its update completes.');
    if(session.adapter!=='dolphin'||!['dolphin','dolphin (Windows)'].includes(session.detail?.emulator))throw Error(session.adapter||session.detail?.emulator?'RE2 inventory controls require a verified standalone Dolphin session.':'The session emulator is not verified yet. Refresh the session before using RE2 inventory controls.');
    available=true;
    const input={session_id:sid,op};
    if(op!=='list'){
     input.expected_inventory_sha256=current.inventory_sha256;input.region=q('[data-re2-region]').value;input.slot=Number(q('[data-re2-slot]').value);
     if(op==='set'){
      input.item_id=Number(q('[data-re2-item]').value);input.quantity=Number(q('[data-re2-qty]').value);
      if(!Number.isInteger(input.item_id)||input.item_id<0||input.item_id>103)throw Error('Choose a listed item.');
      if(!Number.isInteger(input.quantity)||input.quantity<0||input.quantity>255)throw Error('Choose a quantity from 0 through 255.');
      if(input.item_id===0)input.quantity=0;
     }
    }
    submitted=true;let job=await io.api('/api/jobs',{tool:'re2gc_items',require_worker:worker,input});
    const until=Date.now()+95000;
    while(['queued','running'].includes(job.state)&&Date.now()<until&&!dead){note('Inventory '+job.state+'...');await new Promise(r=>setTimeout(r,400));if(!dead)job=await io.api('/api/jobs/'+encodeURIComponent(job.id));}
    if(dead)return;
    if(job.state!=='succeeded')throw Error(job.error||'The operation has not confirmed completion.');
    const result=job.output?.result;
    if(!result?.verified)throw Error(result?.error||'Inventory completion was not confirmed.');
    display(result);uncertain=false;
    note(op==='list'?(result.editable?'Inventory ready.':(result.requirements||[]).join(' ')):
     (result.changed?'Change verified after the game loaded its equipment. Open the inventory again to make another change.':'No change was needed.'));
   }catch(e){
    if(op==='list')current=null;else if(submitted)uncertain=true;
    note(e.message+(op!=='list'&&submitted?' No retry was sent. Refresh and inspect the game before editing again.':''));
   }finally{busy=false;buttons();}
  }
  q('[data-re2-region]').onchange=slots;q('[data-re2-slot]').onchange=selected;
  q('[data-re2-item]').onchange=()=>{const id=Number(q('[data-re2-item]').value);if(!id)q('[data-re2-qty]').value='0';else if(Number(q('[data-re2-qty]').value)===0)q('[data-re2-qty]').value='1';};
  for(const op of ['set','equip','unequip'])q('[data-re2-'+op+']').onclick=()=>run(op);
  q('[data-re2-refresh]').onclick=()=>run('list');run('list');
  return {dispose(){dead=true;d.remove();}};
 }
 root.GBoxRE2Inventory={supported,mount};
})(typeof window==='undefined'?globalThis:window);
