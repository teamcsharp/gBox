/* A shared camera and clock for two actual native poses. No writes or launches. */
(function(root){
  'use strict';
  const ROLES={0:'Hip',2:'Chest',4:'Head',6:'Right upper arm',7:'Right forearm',9:'Right hand',
    11:'Left upper arm',12:'Left forearm',14:'Left hand',16:'Right thigh',17:'Right shin',18:'Right foot',
    20:'Left thigh',21:'Left shin',22:'Left foot'};
  const WINDOW_FRAMES=60;
  const CHAINS=[[0,2,4],[2,6,7,9],[2,11,12,14],[0,16,17,18],[0,20,21,22]];
  function jointLabels(selected){return CHAINS.find(chain=>chain.slice(1).includes(Number(selected)))||CHAINS[0];}
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  const flat=values=>Array.isArray(values?.[0])?values.flat():values;
  const skeleton=(model,index)=>model.frames[index].skeleton||model.frames[index].joints||{};
  function frameNumbers(data){
    return data.frame_indices||data.frames||data.native.frames.map((row,i)=>row.frame??i);
  }
  function validate(data){
    if(!data||!data.native||!data.candidate)throw Error('Both models are needed for a comparison.');
    const counts=[data.native.frames?.length,data.candidate.frames?.length];
    if(!counts[0]||counts[0]!==counts[1]||counts[0]>WINDOW_FRAMES)throw Error('Both models must have the same sampled frames.');
    if(data.diagnostics?.unsupported_tracks?.length)throw Error('This animation has unsupported tracks; no approximate motion is shown.');
    for(const model of [data.native,data.candidate]){
      const count=flat(model.frames[0].positions)?.length;
      if(!count||count%3)throw Error('The comparison has invalid model positions.');
      const triangles=flat(model.triangles);
      if(!Array.isArray(triangles)||triangles.length%3||triangles.some(i=>!Number.isSafeInteger(i)||i<0||i>=count/3))
        throw Error('The comparison has invalid model triangles.');
      for(const row of model.frames){
        const positions=flat(row.positions);
        if(!Array.isArray(positions)||positions.length!==count||positions.some(v=>!Number.isFinite(v)))
          throw Error('Every pose must contain the same complete model.');
      }
    }
    const frames=frameNumbers(data);
    if(frames.length!==counts[0]||frames.some((n,i)=>!Number.isFinite(n)||n<0||(i&&n<=frames[i-1])))
      throw Error('The animation frame numbers must be increasing.');
    if(!Number.isFinite(data.fps)||data.fps<=0||data.fps>240)throw Error('The animation frame rate is invalid.');
    return data;
  }
  function frameAtTime(data,seconds){
    const frames=frameNumbers(data),frame=frames[0]+Math.max(0,seconds)*data.fps;
    let i=0;while(i+1<frames.length&&frames[i+1]<=frame+1e-7)i++;
    return i;
  }
  function jointDifference(data,index,animationId){
    const get=model=>{
      const sk=skeleton(model,index),ids=sk.anim_ids||model.anim_ids||[],bone=ids.indexOf(Number(animationId));
      return bone<0?null:{bone,position:sk.bones?.[bone],matrix:(sk.world_matrices||sk.matrices)?.[bone]};
    };
    const native=get(data.native),candidate=get(data.candidate);
    if(!native?.position||!candidate?.position)return null;
    const delta=candidate.position.map((v,i)=>v-native.position[i]);
    return {native,candidate,delta,distance:Math.hypot(...delta)};
  }
  function mount({api,title,arcPath,build='',animationEntry,onClose,THREE=root.THREE,document=root.document}={}){
    if(!THREE)throw Error('The 3D viewer is unavailable.');
    const dialog=document.createElement('dialog');dialog.className='model-compare';
    dialog.innerHTML=`<header><div><strong>Model comparison</strong><small>RE5 Chris (BSAA) slot · same animation, frame and camera</small></div><button data-close aria-label="Close model comparison">Close</button></header>
      <div class="compare-controls"><label>Candidate <select data-build><option value="">Choose a build</option></select></label>
      <button data-refresh>Refresh builds</button><label>Motion <select data-motion></select></label>
      <label>Pose / animation <select data-clip><option value="">Bind pose</option></select></label>
      <label><input type="checkbox" data-raw-fk> Animation preview without game IK</label>
      <label>Start frame <input data-start type="number" min="0" step="1" value="0" size="6"></label><button data-load>Load comparison</button></div>
      <p data-status role="status">Choose the candidate build to compare with the original Chris.</p>
      <p data-limitations hidden></p>
      <div class="compare-stage"><canvas data-canvas></canvas><div class="compare-label left">Original Chris (BSAA)</div><div data-candidate-label class="compare-label right">Candidate</div><div data-joints class="compare-joints"></div></div>
      <div class="compare-playback"><button data-play disabled>Play</button><button data-prev disabled aria-label="Previous frame">Previous frame</button>
        <input data-frame type="range" min="0" max="0" value="0" step="1" aria-label="Animation frame" disabled><button data-next disabled aria-label="Next frame">Next frame</button><output data-time>Bind pose</output>
        <label>Speed <select data-speed><option value="0.25">¼×</option><option value="0.5">½×</option><option value="1" selected>1×</option></select></label>
        <button data-earlier disabled>Earlier frames</button><button data-later disabled>Later frames</button></div>
      <div class="compare-controls"><button data-view="z">Front (+Z)</button><button data-view="-z">Back (−Z)</button><button data-view="x">Side (+X)</button><button data-view="-x">Side (−X)</button>
        <label><input type="checkbox" data-bones checked> Bones</label><label><input type="checkbox" data-labels checked> Joint names</label><label><input type="checkbox" data-wire> Wireframe</label>
        <label>Joint <select data-joint>${Object.entries(ROLES).map(([id,name])=>`<option value="${id}" ${id==='14'?'selected':''}>${name}</option>`).join('')}</select></label></div>
      <p data-difference>Choose a joint to compare its position.</p><p>Selected joint axes: X red, Y green, Z blue.</p><details><summary>Comparison details</summary><pre data-details></pre></details>`;
    document.body.append(dialog);dialog.showModal();
    const q=s=>dialog.querySelector(s),on=(s,event,fn)=>q(s).addEventListener(event,fn);
    const renderer=new THREE.WebGLRenderer({canvas:q('[data-canvas]'),antialias:true});
    renderer.setPixelRatio(Math.min(root.devicePixelRatio||1,2));renderer.setClearColor(0x111923);renderer.setScissorTest(true);
    const camera=new THREE.PerspectiveCamera(40,1,.1,10000),center=new THREE.Vector3();
    let data=null,views=[],dead=false,raf=0,sequence=0,frame=0,playing=false,seconds=0,last=0;
    let yaw=Math.PI/2,pitch=.12,distance=350,size=180,drag=null;
    function place(){camera.position.set(center.x+Math.cos(yaw)*Math.cos(pitch)*distance,center.y+Math.sin(pitch)*distance,center.z+Math.sin(yaw)*Math.cos(pitch)*distance);camera.lookAt(center);camera.updateMatrixWorld();}
    function disposeViews(){for(const v of views)v.scene.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});views=[];}
    function makeView(model){
      const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xffffff,0x405060,1.7));
      const light=new THREE.DirectionalLight(0xffffff,1.1);light.position.set(100,180,140);scene.add(light);
      const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(flat(model.frames[0].positions)),3));geometry.setIndex(flat(model.triangles));geometry.computeVertexNormals();
      const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0xa8bfd3,roughness:.8,metalness:0,side:THREE.DoubleSide}));scene.add(mesh);
      const lines=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffcd75,depthTest:false}));lines.renderOrder=2;scene.add(lines);
      const points=new THREE.Points(new THREE.BufferGeometry(),new THREE.PointsMaterial({color:0xffcd75,size:3,sizeAttenuation:false,depthTest:false}));points.renderOrder=3;scene.add(points);
      const axes=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({vertexColors:true,depthTest:false}));axes.renderOrder=4;scene.add(axes);
      return {scene,geometry,mesh,lines,points,axes,model};
    }
    function showFrame(index){
      if(!data)return;frame=Math.max(0,Math.min(data.native.frames.length-1,index));
      q('[data-frame]').value=String(frame);
      const actual=frameNumbers(data)[frame];q('[data-time]').textContent=data.clip?.animation_index==null?'Bind pose':`Frame ${actual} · ${(actual/data.fps).toFixed(3)} s`;
      const selected=Number(q('[data-joint]').value),difference=jointDifference(data,frame,selected);
      for(const v of views){
        v.geometry.attributes.position.array.set(flat(v.model.frames[frame].positions));v.geometry.attributes.position.needsUpdate=true;v.geometry.computeVertexNormals();v.geometry.computeBoundingSphere();
        const sk=skeleton(v.model,frame),bones=sk.bones||[],parents=sk.parents||v.model.parents||[],links=[];
        bones.forEach((p,i)=>{if(bones[parents[i]]&&parents[i]!==i)links.push(...bones[parents[i]],...p);});
        v.lines.geometry.setAttribute('position',new THREE.Float32BufferAttribute(links,3));v.points.geometry.setAttribute('position',new THREE.Float32BufferAttribute(bones.flat(),3));
        v.lines.visible=v.points.visible=q('[data-bones]').checked;v.mesh.material.wireframe=q('[data-wire]').checked;
        const id=(sk.anim_ids||v.model.anim_ids||[]).indexOf(selected),m=(sk.world_matrices||sk.matrices)?.[id],p=bones[id],axisPoints=[],colors=[];
        if(m&&p&&m.length===16){for(let a=0;a<3;a++){const axis=[m[a*4],m[a*4+1],m[a*4+2]],n=Math.hypot(...axis)||1;axisPoints.push(...p,...p.map((x,i)=>x+axis[i]/n*size*.06));const c=[0,0,0];c[a]=1;colors.push(...c,...c);}}
        v.axes.geometry.setAttribute('position',new THREE.Float32BufferAttribute(axisPoints,3));v.axes.geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));v.axes.visible=q('[data-bones]').checked;
      }
      q('[data-difference]').textContent=difference?`${ROLES[selected]||'Joint '+selected} difference: X ${difference.delta[0].toFixed(2)}, Y ${difference.delta[1].toFixed(2)}, Z ${difference.delta[2].toFixed(2)} · distance ${difference.distance.toFixed(2)} ${data.units||'model units'}`:'This joint is not present in both models.';
    }
    function setData(value){
      validate(value);disposeViews();data=value;views=[makeView(data.native),makeView(data.candidate)];
      const low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
      for(const model of [data.native,data.candidate])for(const row of model.frames){const p=flat(row.positions);for(let i=0;i<p.length;i++){const a=i%3;low[a]=Math.min(low[a],p[i]);high[a]=Math.max(high[a],p[i]);}}
      center.set(...low.map((v,i)=>(v+high[i])/2));size=Math.max(...low.map((v,i)=>high[i]-v),1);distance=size*2.5;camera.near=Math.max(.001,size/1000);camera.far=size*100;camera.updateProjectionMatrix();place();
      frame=0;seconds=0;playing=false;q('[data-play]').textContent='Play';
      q('[data-frame]').max=String(data.native.frames.length-1);
      for(const name of ['frame','play','prev','next'])q(`[data-${name}]`).disabled=data.native.frames.length<2;
      const numbers=frameNumbers(data);q('[data-earlier]').disabled=data.clip?.animation_index==null||numbers[0]===0;
      q('[data-later]').disabled=data.clip?.animation_index==null||numbers.at(-1)+1>=(data.clip?.frame_count||numbers.at(-1)+1);
      q('[data-details]').textContent=JSON.stringify({source:data.source,clip:data.clip,diagnostics:data.diagnostics,native:data.native.model_sha256||data.native.sha256,candidate:data.candidate.model_sha256||data.candidate.sha256},null,2);
      const limits=q('[data-limitations]');limits.hidden=data.clip?.animation_index==null;limits.textContent=data.evaluation_mode==='raw_fk_without_game_ik'?'Diagnostic animation preview: game IK is omitted. Feet and other constrained joints can differ from the game. Physics and layered motion are also omitted.':'Animation preview uses the native animation tracks. Game IK, physics and layered motion are not shown.';
      q('[data-status]').textContent=data.clip?.animation_index==null?'Bind pose. Drag either view to rotate both models.':`Frames ${numbers[0]}–${numbers.at(-1)} of ${data.clip?.frame_count??'the animation'}. Play or step together; use Earlier / Later frames to inspect the rest.`;
      if(data.source?.build)q('[data-candidate-label]').textContent='Candidate · '+data.source.build;
      showFrame(0);
    }
    async function call(body){return api('/api/decrypt-lab/model-compare',{title,arc_path:arcPath,...body},'POST');}
    async function catalog(animationEntry){
      const token=++sequence;playing=false;q('[data-status]').textContent='Reading models and animations…';
      try{const info=await call({op:'list',...(Number.isSafeInteger(animationEntry)?{animation_entry:animationEntry}:{})});if(dead||token!==sequence)return;
        const chosen=q('[data-build]').value||build;q('[data-build]').innerHTML='<option value="">Choose a build</option>'+info.builds.map(b=>`<option value="${esc(b.name)}">${esc(b.label||b.name)}</option>`).join('');q('[data-build]').value=chosen;
        q('[data-motion]').innerHTML=(info.motions||[]).map(m=>`<option value="${m.entry_index}">${esc(m.name)}</option>`).join('');if(info.selected_animation_entry!=null)q('[data-motion]').value=String(info.selected_animation_entry);dialog._compareCatalog=info;selectMotion();q('[data-status]').textContent='Choose a build and pose or animation. Loading only reads the models.';return info;
      }catch(error){if(!dead&&token===sequence)q('[data-status]').textContent=error.message;}
      finally{if(!dead&&token===sequence)q('[data-load]').disabled=false;}
    }
    function selectMotion(){const info=dialog._compareCatalog,motion=info?.motions?.find(m=>String(m.entry_index)===q('[data-motion]').value),raw=q('[data-raw-fk]').checked;q('[data-clip]').innerHTML='<option value="">Bind pose</option>'+(motion?.clips||[]).map(c=>{const available=c.supported!==false||(raw&&c.raw_fk_supported===true);return `<option value="${c.index}" ${available?'':'disabled'} title="${esc(c.reason||'')}">${esc(c.name||'Animation '+c.index)} · ${c.frame_count} frames${available?'':c.raw_fk_supported?' · needs preview without IK':' · unavailable'}</option>`;}).join('');}
    async function load(){
      const chosen=q('[data-build]').value;if(!chosen){q('[data-status]').textContent='Choose the candidate build first.';return;}
      const token=++sequence;playing=false;q('[data-load]').disabled=true;q('[data-status]').textContent='Loading the same native frames for both models…';
      try{const clip=q('[data-clip]').value,motion=q('[data-motion]').value;
        const start=Number(q('[data-start]').value);if(!Number.isSafeInteger(start)||start<0)throw Error('Start frame must be a nonnegative whole number.');
        const value=await call({op:'sample',build:chosen,...(motion!==''?{animation_entry:Number(motion),...(clip!==''?{animation_index:Number(clip),start_frame:start}:{})}:{}),frame_count:WINDOW_FRAMES,raw_fk:q('[data-raw-fk]').checked});
        if(dead||token!==sequence)return;setData(value);q('[data-candidate-label]').textContent='Candidate · '+chosen;
        const numbers=frameNumbers(value);q('[data-status]').textContent=clip===''?'Bind pose. Drag either view to rotate both models.':`Frames ${numbers[0]}–${numbers.at(-1)} of ${value.clip?.frame_count??'the animation'}. Play or step together; use Earlier / Later frames to inspect the rest.`;
      }catch(error){if(!dead&&token===sequence)q('[data-status]').textContent=error.message;}
      finally{if(!dead&&token===sequence)q('[data-load]').disabled=false;}
    }
    function labels(width,height){
      const host=q('[data-joints]');host.textContent='';if(!data||!q('[data-labels]').checked)return;
      const selected=Number(q('[data-joint]').value),visible=jointLabels(selected),paneWidth=width/2;
      views.forEach((v,side)=>{const sk=skeleton(v.model,frame),ids=sk.anim_ids||v.model.anim_ids||[];
        const projected=[];
        (sk.bones||[]).forEach((p,i)=>{const id=ids[i];if(!visible.includes(id))return;const point=new THREE.Vector3(...p).project(camera);if(point.z< -1||point.z>1||Math.abs(point.x)>1||Math.abs(point.y)>1)return;
          projected.push({id,x:(point.x+1)*paneWidth/2,y:(1-point.y)*height/2});});
        projected.sort((a,b)=>a.y-b.y);let bottom=36;
        for(let i=0;i<projected.length;i++){const p=projected[i],labelWidth=ROLES[p.id].length*6+16;
          const x=Math.max(8,Math.min(paneWidth-labelWidth-8,p.x+9)),y=Math.min(height-12-(projected.length-i-1)*23,Math.max(bottom,p.y));bottom=y+23;
          const label=document.createElement('span');label.textContent=ROLES[p.id];label.className=selected===p.id?'selected':'';label.style.left=`${side*paneWidth+x}px`;label.style.top=`${y}px`;
          const line=document.createElement('i'),dx=x-p.x,dy=y-p.y;line.style.left=`${side*paneWidth+p.x}px`;line.style.top=`${p.y}px`;line.style.width=`${Math.hypot(dx,dy)}px`;line.style.transform=`rotate(${Math.atan2(dy,dx)}rad)`;host.append(line,label);
        }});
    }
    function draw(time){
      if(dead)return;raf=root.requestAnimationFrame(draw);const dt=last?Math.min(.1,(time-last)/1000):0;last=time;
      if(playing&&data){seconds+=dt*Number(q('[data-speed]').value);const frames=frameNumbers(data),end=(frames.at(-1)-frames[0])/data.fps;
        if(seconds>end){seconds=0;}const next=frameAtTime(data,seconds);if(next!==frame)showFrame(next);}
      const stage=q('.compare-stage'),w=stage.clientWidth,h=stage.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/2/Math.max(1,h);camera.updateProjectionMatrix();
      views.forEach((v,i)=>{renderer.setViewport(i*w/2,0,w/2,h);renderer.setScissor(i*w/2,0,w/2,h);renderer.render(v.scene,camera);});labels(w,h);
    }
    const canvas=q('[data-canvas]');canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
    canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw-=(e.clientX-drag[0])*.008;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag[1])*.006));drag=[e.clientX,e.clientY];place();});
    canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(size*.4,Math.min(size*10,distance*Math.exp(e.deltaY*.001)));place();},{passive:false});
    on('[data-play]','click',()=>{playing=!playing;q('[data-play]').textContent=playing?'Pause':'Play';});
    function seek(index){playing=false;q('[data-play]').textContent='Play';showFrame(index);seconds=(frameNumbers(data)[frame]-frameNumbers(data)[0])/data.fps;}
    on('[data-frame]','input',()=>seek(Number(q('[data-frame]').value)));on('[data-prev]','click',()=>seek(frame-1));on('[data-next]','click',()=>seek(frame+1));
    on('[data-earlier]','click',()=>{q('[data-start]').value=Math.max(0,frameNumbers(data)[0]-WINDOW_FRAMES);load();});
    on('[data-later]','click',()=>{q('[data-start]').value=frameNumbers(data).at(-1)+1;load();});
    for(const key of ['bones','labels','wire','joint'])on(`[data-${key}]`,'change',()=>showFrame(frame));
    dialog.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{yaw={z:Math.PI/2,'-z':-Math.PI/2,x:0,'-x':Math.PI}[button.dataset.view];pitch=0;place();}));
    function changed(){sequence++;playing=false;q('[data-play]').textContent='Play';q('[data-load]').disabled=false;for(const name of ['frame','play','prev','next','earlier','later'])q(`[data-${name}]`).disabled=true;q('[data-status]').textContent='Selection changed. Load comparison to show the selected models and frames.';}
    on('[data-refresh]','click',()=>{changed();catalog(q('[data-motion]').value===''?undefined:Number(q('[data-motion]').value));});on('[data-motion]','change',()=>{const selected=Number(q('[data-motion]').value);q('[data-start]').value=0;changed();catalog(selected);});on('[data-load]','click',load);
    on('[data-raw-fk]','change',()=>{selectMotion();changed();});
    for(const name of ['build','clip','start'])on(`[data-${name}]`,'change',()=>{if(name==='clip')q('[data-start]').value=0;changed();});
    function close(){if(dead)return;dead=true;sequence++;root.cancelAnimationFrame(raf);disposeViews();renderer.dispose();dialog.close();dialog.remove();onClose?.();}
    on('[data-close]','click',close);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
    place();raf=root.requestAnimationFrame(draw);const ready=catalog(animationEntry);return {close,setData,load,dialog,ready};
  }
  const exported={mount,validate,frameNumbers,frameAtTime,jointDifference,jointLabels,ROLES,WINDOW_FRAMES};
  if(typeof module==='object'&&module.exports)module.exports=exported;else root.GBoxModelCompare=exported;
})(typeof window!=='undefined'?window:globalThis);
