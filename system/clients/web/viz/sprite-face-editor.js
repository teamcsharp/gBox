/* Original photo -> crop/mask controls -> preview decoded from the native patched ROM. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.GBoxSpriteFaceEditor=factory();})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  function mount(host,game,io){
    let photo='',candidate='',template=null,dead=false,revision=0,rectangles={},supported=false,timer=null,previewing=false,dirty=false;
    let layers=[{name:'Face layer',visible:true,rotation:0,scale:1,offset:[0,0],opacity:1,blend:'normal'}],active=0,viewers=[],viewRevision=0;
    const n64=['b7aecee966090bfa','66062703301f4969'].includes(game.game_id);
    const profileKey='gbox-face-profile-'+game.game_id;
    const q=s=>host.querySelector(s),mapping=()=>({crop:['l','t','r','b'].map(k=>+q(`[data-crop=${k}]`).value/100),
      flip:q('[data-flip]').checked,shape:q('[data-shape]').value,feather:+q('[data-feather]').value/100,
      opacity:+q('[data-opacity]').value/100,rectangles,layers,...(n64?{projection:Object.fromEntries([...host.querySelectorAll('[data-projection]')].map(e=>[e.dataset.projection,+e.value]))}:{})});
    host.innerHTML=`<details><summary>Face editor — layers, masks and native ROM preview</summary>
      <p><input type="file" accept="image/png,image/jpeg,image/webp" data-photo aria-label="Source face image"></p>
      <img data-source alt="Original source photo" style="max-width:150px;max-height:180px" hidden>
      <div data-native hidden><label>Native frame <select data-frame aria-label="Native sprite frame"></select></label>
      <p>Crop from photo (percent)</p><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">${[['l',12],['t',13],['r',70],['b',80]].map(([k,v])=>`<label>${k.toUpperCase()} <input type="number" data-crop="${k}" value="${v}" min="0" max="100" style="width:60px"></label>`).join('')}</div>
      <label><input type="checkbox" data-flip checked> Mirror photo to face right</label>
      <label>Mask <select data-shape><option value="ellipse">Ellipse</option><option value="rectangle">Rectangle</option></select></label>
      <label>Feather <input data-feather type="range" min="0" max="20" value="4"></label>
      <label>Opacity <input data-opacity type="range" min="1" max="100" value="100"></label>
      <fieldset><legend>Layers and transforms</legend><select data-layer aria-label="Active blend layer"></select>
      <button type="button" data-add-layer>Add layer</button> <button type="button" data-remove-layer>Remove</button>
      <button type="button" data-layer-up>Move up</button> <button type="button" data-layer-down>Move down</button>
      <label><input type="checkbox" data-layer-visible checked> Visible</label>
      <label>Translation X <input type="range" data-layer-x min="-100" max="100" value="0"></label>
      <label>Translation Y <input type="range" data-layer-y min="-100" max="100" value="0"></label>
      <label>Rotation <input type="range" data-layer-rotation min="-180" max="180" value="0"></label>
      <label>Scale <input type="range" data-layer-scale min="10" max="400" value="100"></label>
      <label>Layer opacity <input type="range" data-layer-opacity min="0" max="100" value="100"></label>
      <label>Blend <select data-layer-blend>${['normal','multiply','screen','overlay','darken','lighten'].map(b=>`<option>${b}</option>`).join('')}</select></label></fieldset>
      <label><input type="checkbox" data-live checked> Live native ROM preview while editing</label>
      ${n64?`<fieldset><legend>Gameplay head projection</legend>${[['yaw',0,-60,60],['pitch',0,-45,45],['width',250,80,500],['height',210,80,500],['center_x',0,-150,150],['center_y',97,-100,300]].map(([k,v,min,max])=>`<label>${k.replace('_',' ')} <input type="number" data-projection="${k}" value="${v}" min="${min}" max="${max}"></label>`).join('')}<p>Planar projection onto the original face triangles. Geometry and skeleton are preserved. Boot-screen Goddard head requires its own writer.</p></fieldset>`:''}
      <p>Face mask on this frame: drag to draw, or set the four edges below. Other frames use their native skin regions.</p>
      <canvas data-mask width="256" height="256" style="width:256px;max-width:100%;background:#111;image-rendering:pixelated;touch-action:none"></canvas>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">${['l','t','r','b'].map(k=>`<label>${k.toUpperCase()} <input type="number" data-edge="${k}" min="0" max="100" style="width:60px"></label>`).join('')}</div>
      <button type="button" data-reset>Use automatic face mask</button> <button type="button" data-preview disabled>Preview native ROM result</button>
      <div data-results hidden><p>Original → native ROM result</p><div style="display:flex;gap:12px"><img data-before alt="Original native sprite" style="width:45%;image-rendering:pixelated;object-fit:contain"><img data-after alt="Photo mapped into native ROM sprite" style="width:45%;image-rendering:pixelated;object-fit:contain"></div></div></div>
      <div data-models hidden><p>Original / patched gameplay mesh — drag to orbit, scroll to zoom</p><div style="display:flex;gap:8px"><div data-model-before style="width:50%;height:320px"></div><div data-model-after style="width:50%;height:320px"></div></div><p data-model-status></p></div>
      <p role="status" data-info>Choose an image. Your original pixels are used; no face is regenerated. Live preview does not alter your running game; request a build to play the edited ROM.</p></details>`;
    const info=t=>{if(!dead)q('[data-info]').textContent=t;};
    function schedule(){clearTimeout(timer);dirty=true;if(photo&&template&&q('[data-live]').checked)timer=setTimeout(preview,300);}
    function saveProfile(){try{localStorage.setItem(profileKey,JSON.stringify({photo,mapping:mapping()}));}catch{}}
    function invalidate(){candidate='';revision++;saveProfile();io.changed?.();schedule();}
    function showLayer(){const layer=layers[active];q('[data-layer]').innerHTML=layers.map((l,i)=>`<option value="${i}">${i+1}. ${l.name}</option>`).join('');q('[data-layer]').value=String(active);
      q('[data-layer-visible]').checked=layer.visible;for(const [key,value] of [['x',layer.offset[0]*100],['y',layer.offset[1]*100],['rotation',layer.rotation],['scale',layer.scale*100],['opacity',layer.opacity*100]])q('[data-layer-'+key+']').value=value;
      q('[data-layer-blend]').value=layer.blend;if(layer.crop)['l','t','r','b'].forEach((k,i)=>q('[data-crop='+k+']').value=layer.crop[i]*100);}
    try{const saved=JSON.parse(localStorage.getItem(profileKey)||'null');if(saved?.mapping){
      const m=saved.mapping;photo=/^[a-f0-9]{64}$/.test(saved.photo||'')?saved.photo:'';
      layers=m.layers?.length&&m.layers.length<=8?m.layers:layers;rectangles=m.rectangles||{};
      ['l','t','r','b'].forEach((k,i)=>q('[data-crop='+k+']').value=m.crop[i]*100);
      q('[data-flip]').checked=m.flip;q('[data-shape]').value=m.shape;q('[data-feather]').value=m.feather*100;q('[data-opacity]').value=m.opacity*100;
      for(const e of host.querySelectorAll('[data-projection]'))if(m.projection?.[e.dataset.projection]!==undefined)e.value=m.projection[e.dataset.projection];
      if(photo){q('[data-source]').src=io.url?io.url('/api/artifacts/'+photo):'/api/artifacts/'+photo;q('[data-source]').hidden=false;q('[data-preview]').disabled=false;}
    }}catch{}
    showLayer();q('[data-layer]').onchange=()=>{active=+q('[data-layer]').value;showLayer();};
    q('[data-add-layer]').onclick=()=>{if(layers.length>=8)return info('Up to eight layers per sprite profile.');layers.push({...layers[active],offset:[...layers[active].offset],name:'Face layer '+(layers.length+1)});active=layers.length-1;showLayer();invalidate();};
    q('[data-remove-layer]').onclick=()=>{if(layers.length===1)return;layers.splice(active,1);active=Math.min(active,layers.length-1);showLayer();invalidate();};
    for(const [attr,step] of [['up',1],['down',-1]])q('[data-layer-'+attr+']').onclick=()=>{const next=active+step;if(next<0||next>=layers.length)return;[layers[active],layers[next]]=[layers[next],layers[active]];active=next;showLayer();invalidate();};
    let image=null,frameRevision=0;
    function draw(){
      const c=q('[data-mask]'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!image||!template)return;
      ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0,c.width,c.height);
      const rect=rectangles[String(template.frame)]||template.rect;
      if(rect){ctx.strokeStyle='#72c8ff';ctx.lineWidth=2;ctx.strokeRect(rect[0]*c.width,rect[1]*c.height,(rect[2]-rect[0])*c.width,(rect[3]-rect[1])*c.height);
        ['l','t','r','b'].forEach((k,i)=>q(`[data-edge=${k}]`).value=Math.round(rect[i]*100));}
    }
    async function loadFrame(frame){
      const generation=++frameRevision;template=null;
      try{const t=await io.api(`/api/games/${game.game_id}/sprite-faces?frame=${frame}`);if(dead||generation!==frameRevision)return;
        supported=true;template=t;q('[data-native]').hidden=false;
        if(!q('[data-frame]').options.length)for(let i=0;i<t.count;i++)q('[data-frame]').add(new Option('Frame '+i,String(i)));
        q('[data-frame]').value=String(frame);image=new Image();image.onload=draw;image.src=t.image;schedule();
      }catch(e){if(generation===frameRevision)info('Native face template unavailable for this game. You can still attach this image to an engineering request. '+e.message);}
    }
    q('[data-frame]').onchange=()=>{invalidate();loadFrame(+q('[data-frame]').value);};
    q('[data-photo]').onchange=async()=>{
      const file=q('[data-photo]').files[0];if(!file)return;
      if(file.size>8*1024*1024)return info('Use an image no larger than 8 MiB.');
      invalidate();q('[data-preview]').disabled=true;
      try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});
        const r=await io.api('/api/photo-skins/photos',{data_url:data,source_kind:'selfie',label:file.name});if(dead)return;
        photo=photo||r.photo;layers[active].photo=r.photo;layers[active].crop=['l','t','r','b'].map(k=>+q('[data-crop='+k+']').value/100);
        q('[data-source]').src=data;q('[data-source]').hidden=false;q('[data-preview]').disabled=false;
        info('Photo attached. Adjust the crop and face mask; live preview uses the actual native palette result.');saveProfile();io.changed?.();schedule();
      }catch(e){info('Photo upload failed: '+e.message);}
    };
    host.addEventListener('input',e=>{
      if(e.target.matches('[data-crop]'))layers[active].crop=['l','t','r','b'].map(k=>+q('[data-crop='+k+']').value/100);
      if(e.target.matches('[data-layer-x],[data-layer-y],[data-layer-rotation],[data-layer-scale],[data-layer-opacity],[data-layer-visible],[data-layer-blend]')){
        layers[active]={...layers[active],offset:[+q('[data-layer-x]').value/100,+q('[data-layer-y]').value/100],rotation:+q('[data-layer-rotation]').value,scale:+q('[data-layer-scale]').value/100,
          opacity:+q('[data-layer-opacity]').value/100,visible:q('[data-layer-visible]').checked,blend:q('[data-layer-blend]').value};invalidate();}
      if(e.target.dataset.edge){const rect=['l','t','r','b'].map(k=>+q(`[data-edge=${k}]`).value/100);rectangles[String(template.frame)]=rect;draw();}
      if(e.target.matches('[data-crop],[data-edge],[data-flip],[data-shape],[data-feather],[data-opacity],[data-projection]'))invalidate();
    });
    host.addEventListener('change',e=>{if(e.target.matches('[data-flip],[data-shape]'))invalidate();if(e.target.matches('[data-live]'))schedule();});
    let start=null;
    const point=e=>{const r=q('[data-mask]').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
    q('[data-mask]').onpointerdown=e=>{if(!template)return;start=point(e);q('[data-mask]').setPointerCapture(e.pointerId);};
    q('[data-mask]').onpointermove=e=>{if(!start)return;const p=point(e);rectangles[String(template.frame)]=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];draw();};
    q('[data-mask]').onpointerup=()=>{if(start){start=null;invalidate();}};
    q('[data-reset]').onclick=()=>{delete rectangles[String(template.frame)];invalidate();draw();};
    async function preview(){
      clearTimeout(timer);if(!photo||!template||dead)return;if(previewing){dirty=true;return;}
      dirty=false;previewing=true;const version=revision;q('[data-preview]').disabled=true;info('Calculating the actual ROM pixels and shared-tile masks…');
      try{const r=await io.api(`/api/games/${game.game_id}/sprite-faces/preview`,{photo,mapping:mapping(),frame:template.frame});if(dead||version!==revision)return;
        candidate=r.id;q('[data-before]').src=r.before;q('[data-after]').src=r.after;q('[data-results]').hidden=false;
        info(`${r.report.changed_pixels} native pixels changed; ${r.report.shared_pixels_preserved} shared pixels preserved. ${n64?'Gameplay projection; boot head unchanged.':'Tiny sprites use the game\'s limited palette.'} Select “Photo face from preview” to request this result.`);io.changed?.();
        if(r.models)showModels(r.models);
      }catch(e){if(version===revision)info(e.message);}finally{previewing=false;if(!dead){q('[data-preview]').disabled=false;if(dirty&&q('[data-live]').checked)timer=setTimeout(preview,50);}}
    }
    q('[data-preview]').onclick=preview;
    async function showModels(models){
      const generation=++viewRevision;q('[data-models]').hidden=false;q('[data-model-status]').textContent='Loading native mesh previews…';
      try{const {createCharacterViewer}=await import('/viz/character-model.js');if(dead||generation!==viewRevision)return;
        const pose=viewers[1]?.getView();viewers.forEach(v=>v.dispose());viewers=[];
        for(const key of ['before','after']){const v=await createCharacterViewer(q('[data-model-'+key+']'),io.url?io.url(models[key]):models[key],{autoRotate:false,distance:1.1});
          if(dead||generation!==viewRevision){v.dispose();return;}if(pose)v.setView(pose);viewers.push(v);}
        q('[data-model-status]').textContent='Meshes decoded from the original and patched ROMs.';
      }catch(e){if(!dead)q('[data-model-status]').textContent='3D preview unavailable: '+e.message;}
    }
    loadFrame(game.game_id==='49b6a2f65aca26a2'||n64?0:1);
    return {selection:()=>({photo,mapping:candidate?{candidate}:mapping(),ready:!!candidate,supported}),dispose(){dead=true;viewRevision++;clearTimeout(timer);viewers.forEach(v=>v.dispose());}};
  }
  return {mount};
});
