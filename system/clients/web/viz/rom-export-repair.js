(function(root){
 'use strict';
 async function open(item,io){
  const previous=document.activeElement,dialog=document.createElement('dialog');
  dialog.setAttribute('aria-label','Repair ROM export');dialog.style.cssText='width:min(720px,90vw);max-height:85vh;overflow:auto;background:var(--bg,#16161a);color:var(--fg,#eee);border:1px solid var(--line,#444);border-radius:12px;padding:20px';
  dialog.innerHTML='<div class="bar"><h2 style="flex:1">Review ROM export</h2><button class="act" data-close>Close</button></div><p role="status" data-status>Checking the failed export…</p><div data-details></div><div data-options></div><button class="act pri" data-export disabled>Export selected item</button>';
  document.body.append(dialog);dialog.showModal();
  const q=s=>dialog.querySelector(s),status=q('[data-status]');let closed=false,revision=0,plan,body={...(item.retry?.input||{}),game_id:item.retry?.input?.game_id||item.game_id||''};delete body.op;
  function close(){closed=true;revision++;dialog.close();dialog.remove();if(previous?.isConnected)previous.focus();}
  q('[data-close]').onclick=close;dialog.oncancel=e=>{e.preventDefault();close();};
  async function inspect(input){
   const rev=++revision;q('[data-export]').disabled=true;status.textContent='Checking the export selection…';
   try{
    const result=await io.api('/api/romexport/plan',input);if(closed||rev!==revision)return;plan=result;body=input;
    status.textContent=result.ready?'Selection is ready for an export attempt. Source bytes and rebuilt files will be checked during the build.':'Choose an export item or complete the repair below.';
    const details=q('[data-details]');details.replaceChildren();
    for(const issue of result.issues||[]){const p=document.createElement('p');p.textContent=issue.message+' '+issue.next_step;details.append(p);}
    const options=q('[data-options]');options.replaceChildren();
    if(result.options?.length){const label=document.createElement('label');label.textContent='Export selection ';const select=document.createElement('select');select.setAttribute('aria-label','Item to export');const empty=document.createElement('option');empty.textContent='Choose original game or a modification';empty.value='';select.append(empty);
     result.options.forEach((option,i)=>{const row=document.createElement('option');row.value=String(i);row.textContent=option.label;select.append(row);});
     select.onchange=()=>{if(select.value!==''){const chosen={...result.options[+select.value].input};delete chosen.op;inspect(chosen);}};label.append(select);options.append(label);
    }
    q('[data-export]').disabled=!result.ready;
   }catch(e){if(!closed&&rev===revision)status.textContent='Could not review this export: '+e.message;}
  }
  q('[data-export]').onclick=async()=>{
   if(!plan?.ready)return;q('[data-export]').disabled=true;status.textContent='Submitting the checked selection…';
   try{const job=await io.api('/api/romexport',body);if(!closed)status.textContent='Export queued: '+job.id+'. Follow its progress in Jobs.';}
   catch(e){if(!closed){status.textContent=e.message;q('[data-export]').disabled=false;}}
  };
  await inspect(body);return {close};
 }
 root.GBoxRomExportRepair={open};
})(typeof window==='undefined'?globalThis:window);

