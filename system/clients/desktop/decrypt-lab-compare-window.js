'use strict';
(async()=>{
  const status=document.getElementById('comparison-opening');
  try{
    const info=await window.decryptLab.info();
    const panel=window.GBoxModelCompare.mount({api:window.decryptLab.api,title:info.title,arcPath:info.arcPath,
      build:info.build,animationEntry:info.animationEntry,onClose:()=>window.close()});
    status.hidden=true;
    if(!await panel.ready)return;
    if(info.animationIndex!=null){
      const clip=panel.dialog.querySelector('[data-clip]'),choice=[...clip.options].find(row=>row.value===String(info.animationIndex));
      if(!choice||choice.disabled){panel.dialog.querySelector('[data-status]').textContent='The requested animation is unavailable for ordinary preview. Choose an available animation or explicitly enable preview without game IK.';return;}
      clip.value=String(info.animationIndex);
    }
    if(info.build)await panel.load();
  }catch(error){status.hidden=false;status.textContent=error.message;}
})();
