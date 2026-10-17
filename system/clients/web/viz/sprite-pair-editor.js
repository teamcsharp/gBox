/* Native donor/target animation alignment. Display layers never alter the original ROM. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.GBoxSpritePairEditor=factory();})(typeof window==='undefined'?globalThis:window,function(){
 'use strict';
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');
 const defaults=()=>({clip:'',frame:0,crop:[0,0,1,1],mask:[0,0,1,1],x:0,y:0,scale:1,rotation:0,flip:false});
 function open(game,io){
  document.querySelector('#sprite-pair-editor')?.close();
  const d=document.createElement('dialog');d.id='sprite-pair-editor';d.setAttribute('aria-label','One-to-one sprite animation editor');
  d.style.cssText='width:min(1080px,94vw);max-height:90vh;overflow:auto;background:#191c25;color:#eee;border:1px solid #59657e;border-radius:12px;padding:16px';
  d.innerHTML=`<header style="display:flex;align-items:center;gap:12px"><h3 style="flex:1;margin:0">Sonic 2 → Mario Bros. · sprite animation editor</h3><button data-close type="button" aria-label="Close sprite animation editor">✕</button></header>
   <p>Align donor frames against the original sprites at native 16 × 32 pixels. Live results are decoded from the patched ROM. Your running game stays in place.</p>
   <div style="display:flex;gap:16px;flex-wrap:wrap"><section style="flex:1;min-width:260px">
    <label>Target animation <select data-group></select></label> <label>Frame <select data-row></select></label>
    <p><label><input data-animate type="checkbox" checked> Play animation</label> <label>Speed <input data-speed type="range" min="50" max="600" value="160"></label></p>
    <div style="display:flex;flex-wrap:wrap;gap:8px"><label><input data-layer="reference" type="checkbox" checked> Mario reference</label><label><input data-layer="donor" type="checkbox" checked> Sonic overlay</label><label><input data-layer="result" type="checkbox"> Native ROM result</label></div>
    <p><label>Overlay opacity <input data-mix type="range" min="0" max="100" value="55"></label> <button data-toggle type="button">Toggle reference / result</button></p>
    <canvas data-stage width="384" height="768" style="display:block;width:min(100%,384px,30vh);height:auto;background:repeating-conic-gradient(#252a35 0% 25%,#303746 0% 50%) 0/24px 24px;image-rendering:pixelated;touch-action:none"></canvas>
    <small>Drag the overlay to translate it. Blue line: native ground. Cyan: native sprite bounds.</small>
   </section><aside style="width:300px;max-width:100%">
    <label>Source animation <select data-clip><option value="">Automatic native mapping</option></select></label>
    <label>Source frame <input data-source-frame type="number" min="0" value="0" style="width:65px"></label>
    <p><label><input data-group-edit type="checkbox" checked> Apply transforms across this animation</label></p>
    <canvas data-source width="256" height="256" style="width:200px;max-width:100%;height:auto;background:#111;image-rendering:pixelated;touch-action:none"></canvas>
    <small>Drag on the source sprite to crop it.</small>
    <fieldset><legend>Source crop (%)</legend>${['left','top','right','bottom'].map((k,i)=>`<label style="display:inline-block;width:48%">${k} <input data-crop="${i}" type="number" min="0" max="100" value="${i<2?0:100}" style="width:60px"></label>`).join('')}</fieldset>
    <fieldset><legend>Native alignment</legend>${[['x',0,-32,32,.25],['y',0,-32,32,.25],['scale',1,.1,4,.05],['rotation',0,-180,180,1]].map(([k,v,min,max,step])=>`<label style="display:block">${k} <input data-transform="${k}" type="number" value="${v}" min="${min}" max="${max}" step="${step}" style="width:80px"></label>`).join('')}
    <label><input data-flip type="checkbox"> Mirror Sonic</label></fieldset>
    <fieldset><legend>Target mask (%)</legend>${['left','top','right','bottom'].map((k,i)=>`<label style="display:inline-block;width:48%">${k} <input data-mask="${i}" type="number" min="0" max="100" value="${i<2?0:100}" style="width:60px"></label>`).join('')}</fieldset>
    <button data-reset type="button">Reset selected animation</button>
    <p><label><input data-live type="checkbox" checked> Rebuild native preview while editing</label></p><button data-preview type="button">Update ROM preview</button>
    <p data-info role="status" aria-live="polite">Loading owned source and target sprites…</p>
    <p><button data-use type="button" disabled>Use this mapping</button> <button data-build type="button" disabled>Build edited ROM</button></p>
   </aside></div>`;
  const q=s=>d.querySelector(s),key='gbox-sprite-pair-'+game.game_id;
  let profile={frames:{}},data=null,clips={},group=0,row=0,result=[],candidate='',revision=0,dead=false,timer=null,busy=false,dirty=false,animation=null,phase=0,lastStep=0;
  const images=new Map();
  try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved?.frames)profile=saved;}catch{}
  const rows=()=>data?.groups[group]?.rows||[row];
  const settings=()=>profile.frames[String(row)]||defaults();
  function info(text){if(!dead)q('[data-info]').textContent=text;}
  function ready(value){q('[data-use]').disabled=q('[data-build]').disabled=!value;}
  function picture(url){if(!url)return null;if(!images.has(url)){const im=new Image();im.onload=draw;im.src=url;images.set(url,im);}const im=images.get(url);return im.complete&&im.naturalWidth?im:null;}
  function donorFor(index){const s=profile.frames[String(index)]||defaults();return s.clip?clips[s.clip]?.frames[s.frame]:data?.default_sources[index];}
  function showSettings(){const s=settings();q('[data-clip]').value=s.clip;q('[data-source-frame]').value=s.frame;
   for(const k of ['x','y','scale','rotation'])q('[data-transform='+k+']').value=s[k];
   for(const type of ['crop','mask'])s[type].forEach((v,i)=>q('[data-'+type+'="'+i+'"]').value=v*100);
   q('[data-flip]').checked=s.flip;
  }
  function readSettings(){return {clip:q('[data-clip]').value,frame:+q('[data-source-frame]').value,
   crop:[0,1,2,3].map(i=>+q('[data-crop="'+i+'"]').value/100),mask:[0,1,2,3].map(i=>+q('[data-mask="'+i+'"]').value/100),
   x:+q('[data-transform=x]').value,y:+q('[data-transform=y]').value,scale:+q('[data-transform=scale]').value,rotation:+q('[data-transform=rotation]').value,flip:q('[data-flip]').checked};}
  function invalidate(){candidate='';ready(false);revision++;dirty=true;clearTimeout(timer);try{localStorage.setItem(key,JSON.stringify(profile));}catch{}
   draw();if(q('[data-live]').checked)timer=setTimeout(preview,220);}
  function change(){const s=readSettings(),targets=q('[data-group-edit]').checked?rows():[row];
   for(const target of targets){const count=clips[s.clip]?.frames.length||1,offset=rows().indexOf(target)-rows().indexOf(row);
    profile.frames[String(target)]={...s,crop:[...s.crop],mask:[...s.mask],frame:s.clip?(s.frame+offset+count)%count:0};}
   invalidate();}
  async function loadClip(name){if(!name||clips[name])return;const answer=await io.api('/api/games/'+game.game_id+'/sprite-pairs?animation='+encodeURIComponent(name));if(dead)return;clips[name]=answer.donor;}
  function chooseGroup(){group=+q('[data-group]').value;const list=rows();row=list[0];phase=0;q('[data-row]').innerHTML=list.map(i=>`<option value="${i}">${i}</option>`).join('');showSettings();draw();}
  function aligned(index){const im=picture(donorFor(index));if(!im||!data)return null;
   const s=profile.frames[String(index)]||defaults(),crop=document.createElement('canvas');
   const [l,t,r,b]=s.crop;crop.width=Math.max(1,Math.round((r-l)*im.width));crop.height=Math.max(1,Math.round((b-t)*im.height));
   const cx=crop.getContext('2d');cx.imageSmoothingEnabled=false;cx.drawImage(im,l*im.width,t*im.height,(r-l)*im.width,(b-t)*im.height,0,0,crop.width,crop.height);
   const a=cx.getImageData(0,0,crop.width,crop.height).data;let x0=crop.width,y0=crop.height,x1=0,y1=0;
   for(let y=0;y<crop.height;y++)for(let x=0;x<crop.width;x++)if(a[(y*crop.width+x)*4+3]){x0=Math.min(x0,x);x1=Math.max(x1,x+1);y0=Math.min(y0,y);y1=Math.max(y1,y+1);}
   if(x1<=x0||y1<=y0)return null;const top=data.target_top[index],height=32-top,factor=Math.min(16/(x1-x0),height/(y1-y0));
   const fit=document.createElement('canvas');fit.width=16;fit.height=height;const fx=fit.getContext('2d');fx.imageSmoothingEnabled=false;
   const fw=Math.max(1,Math.round((x1-x0)*factor)),fh=Math.max(1,Math.round((y1-y0)*factor));
   if(s.flip){fx.translate(16,0);fx.scale(-1,1);}fx.drawImage(crop,x0,y0,x1-x0,y1-y0,Math.floor((16-fw)/2),height-fh,fw,fh);
   const out=document.createElement('canvas');out.width=16;out.height=32;const ctx=out.getContext('2d');ctx.imageSmoothingEnabled=false;
   const [ml,mt,mr,mb]=s.mask;ctx.beginPath();ctx.rect(ml*16,Math.max(top,mt*32),(mr-ml)*16,mb*32-Math.max(top,mt*32));ctx.clip();
   const angle=s.rotation*Math.PI/180,rotatedHeight=Math.abs(16*s.scale*Math.sin(angle))+Math.abs(height*s.scale*Math.cos(angle));
   ctx.translate(8+s.x,32-rotatedHeight/2+s.y);ctx.rotate(-angle);ctx.scale(s.scale,s.scale);ctx.drawImage(fit,-8,-height/2);return out;
  }
  function draw(){if(!data||dead)return;const current=q('[data-animate]').checked?rows()[phase%rows().length]:row;
   const canvas=q('[data-stage]'),ctx=canvas.getContext('2d');ctx.setTransform(24,0,0,24,0,0);ctx.clearRect(0,0,16,32);ctx.imageSmoothingEnabled=false;
   if(q('[data-layer=reference]').checked){const im=picture(data.target_frames[current]);if(im){ctx.globalAlpha=.6;ctx.drawImage(im,0,0,16,32);}}
   if(q('[data-layer=donor]').checked){const im=aligned(current);if(im){ctx.globalAlpha=+q('[data-mix]').value/100;ctx.drawImage(im,0,0);}}
   if(q('[data-layer=result]').checked){const im=picture(result[current]);if(im){ctx.globalAlpha=1;ctx.drawImage(im,0,0,16,32);}}
   ctx.globalAlpha=1;ctx.strokeStyle='#63c8ff';ctx.lineWidth=1/24;ctx.strokeRect(.05,data.target_top[current]+.05,15.9,31.9-data.target_top[current]);ctx.beginPath();ctx.moveTo(0,31.95);ctx.lineTo(16,31.95);ctx.stroke();
   const src=picture(donorFor(row));if(src){const c=q('[data-source]');c.width=256;c.height=Math.round(256*src.height/src.width);const x=c.getContext('2d');x.imageSmoothingEnabled=false;x.drawImage(src,0,0,c.width,c.height);const r=settings().crop;x.strokeStyle='#63c8ff';x.lineWidth=2;x.strokeRect(r[0]*c.width,r[1]*c.height,(r[2]-r[0])*c.width,(r[3]-r[1])*c.height);}
  }
  async function preview(){clearTimeout(timer);if(dead||!data)return;if(busy){dirty=true;return;}busy=true;dirty=false;const version=revision;
   info('Compiling native NES tiles and checking the complete 26-frame budget…');
   try{const answer=await io.api('/api/games/'+game.game_id+'/sprite-pairs/preview',{profile:JSON.parse(JSON.stringify(profile))});if(dead||version!==revision)return;
    result=answer.frames;candidate=answer.id;ready(true);info(`${answer.report.tiles_used}/${answer.report.tile_budget} native tiles · exact ROM preview ready. Layer toggles affect comparison only.`);draw();
   }catch(e){if(!dead&&version===revision)info(e.message);}finally{busy=false;if(dirty&&!dead&&q('[data-live]').checked)timer=setTimeout(preview,50);}
  }
  q('[data-group]').onchange=chooseGroup;q('[data-row]').onchange=()=>{row=+q('[data-row]').value;showSettings();loadClip(settings().clip).then(draw).catch(e=>info(e.message));draw();};
  q('[data-clip]').onchange=async()=>{try{await loadClip(q('[data-clip]').value);if(dead)return;q('[data-source-frame]').value=0;change();}catch(e){info(e.message);}};
  d.addEventListener('input',e=>{if(e.target.matches('[data-crop],[data-mask],[data-transform],[data-source-frame],[data-flip]'))change();else draw();});
  d.addEventListener('change',e=>{if(e.target.matches('[data-flip]'))change();if(e.target.matches('[data-live]')&&e.target.checked)invalidate();draw();});
  q('[data-toggle]').onclick=()=>{const on=!q('[data-layer=result]').checked;q('[data-layer=result]').checked=on;q('[data-layer=reference]').checked=!on;q('[data-layer=donor]').checked=false;draw();};
  q('[data-reset]').onclick=()=>{for(const i of q('[data-group-edit]').checked?rows():[row])delete profile.frames[String(i)];showSettings();invalidate();};q('[data-preview]').onclick=preview;
  let drag=null;
  q('[data-stage]').onpointerdown=e=>{if(!data)return;const r=e.currentTarget.getBoundingClientRect();drag={x:e.clientX,y:e.clientY,rect:r,settings:readSettings()};e.currentTarget.setPointerCapture(e.pointerId);};
  q('[data-stage]').onpointermove=e=>{if(!drag)return;q('[data-transform=x]').value=(drag.settings.x+(e.clientX-drag.x)*16/drag.rect.width).toFixed(2);q('[data-transform=y]').value=(drag.settings.y+(e.clientY-drag.y)*32/drag.rect.height).toFixed(2);change();};
  q('[data-stage]').onpointerup=q('[data-stage]').onpointercancel=()=>{drag=null;};
  let cropStart=null;
  const point=e=>{const r=e.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
  q('[data-source]').onpointerdown=e=>{cropStart=point(e);e.currentTarget.setPointerCapture(e.pointerId);};
  q('[data-source]').onpointermove=e=>{if(!cropStart)return;const p=point(e),r=[Math.min(p[0],cropStart[0]),Math.min(p[1],cropStart[1]),Math.max(p[0],cropStart[0]),Math.max(p[1],cropStart[1])];if(r[2]-r[0]<.01||r[3]-r[1]<.01)return;r.forEach((v,i)=>q('[data-crop="'+i+'"]').value=(v*100).toFixed(1));change();};
  q('[data-source]').onpointerup=q('[data-source]').onpointercancel=()=>{cropStart=null;};
  for(const [attr,build] of [['use',false],['build',true]])q('[data-'+attr+']').onclick=()=>{if(!candidate)return;const selected=candidate;d.close();io.onCandidate?.({candidate:selected},build);};
  q('[data-close]').onclick=()=>d.close();d.onclose=()=>{dead=true;clearTimeout(timer);cancelAnimationFrame(animation);d.remove();io.closed?.();};
  function tick(now){if(dead)return;if(now-lastStep>+q('[data-speed]').value){lastStep=now;phase++;draw();}animation=requestAnimationFrame(tick);}
  document.body.append(d);d.showModal();animation=requestAnimationFrame(tick);
  io.api('/api/games/'+game.game_id+'/sprite-pairs').then(async answer=>{if(dead)return;data=answer;clips[answer.donor.animation]=answer.donor;
   q('[data-group]').innerHTML=answer.groups.map((g,i)=>`<option value="${i}">${esc(g.name)}</option>`).join('');
   q('[data-clip]').innerHTML='<option value="">Automatic native mapping</option>'+answer.donor.clips.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
   for(const n of [...new Set(Object.values(profile.frames).map(s=>s.clip).filter(Boolean))])await loadClip(n);
   if(dead)return;chooseGroup();invalidate();
  }).catch(e=>info('Native sprite editor unavailable: '+e.message));
  return {element:d,close:()=>d.close()};
 }
 return {open};
});
