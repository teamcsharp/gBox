/* Explicit photo placement and review; never infers a face or starts a game. */
(function(root){
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>`&#${c.charCodeAt(0)};`);
  function mount(host,io,{slug,onPreview,onAccepted,onPending=()=>{}}){
    let dead=false,photo=null,review=null,maps=[],crop=[0,0,1,1],rect=[0,0,1,1],turn=0;
    host.innerHTML=`<details><summary>Photo / selfie skin</summary><p>Map a submitted photo onto this model's existing color maps. Geometry and rig stay unchanged. Drag a crop on the photo and a destination on the UV map, then preview in 3D.</p>
      <label>Name <input data-ps="name" maxlength="80" value="Photo character"></label>
      <label>Photo <input data-ps="file" type="file" accept="image/jpeg,image/png,image/webp"></label>
      <label>Source <select data-ps="source"><option value="selfie">Selfie</option><option value="photo">Photo</option><option value="generated">Generated image</option><option value="internet">Saved internet image</option></select></label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><figure style="margin:0"><canvas data-ps="photo" width="256" height="256" style="width:100%;touch-action:none;background:#222"></canvas><figcaption>Photo crop (drag)</figcaption></figure><figure style="margin:0"><canvas data-ps="uv" width="256" height="256" style="width:100%;touch-action:none;background:#222"></canvas><figcaption>Destination UV patch (drag)</figcaption></figure></div>
      <div data-ps="maps" style="max-height:160px;overflow:auto"></div><button type="button" data-ps="rotate">Rotate patch 90°</button>
      <label>Blend edge <input data-ps="feather" type="range" min="0" max=".2" step=".01" value=".04"></label>
      <button type="button" data-ps="prepare">Prepare photo preview</button><p data-ps="status" role="status"></p><div data-ps="result"></div>
      <div data-ps="decision" hidden><button type="button" data-ps="original">Original in 3D</button><button type="button" data-ps="candidate">Photo skin in 3D</button><button type="button" data-ps="accept">Accept as separate donor</button><button type="button" data-ps="reject">Reject</button></div></details>`;
    const q=k=>host.querySelector(`[data-ps="${k}"]`),note=t=>{if(!dead)q('status').textContent=t;};
    const images={};
    async function image(url){const im=new Image();im.src=io.url?io.url(url):url;await im.decode();return im;}
    function draw(kind){const c=q(kind);if(images[kind]){c.width=256;c.height=Math.round(256*images[kind].height/images[kind].width);}const ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(images[kind])ctx.drawImage(images[kind],0,0,c.width,c.height);const r=kind==='photo'?crop:rect;ctx.strokeStyle='#f59c66';ctx.lineWidth=2;ctx.strokeRect(r[0]*c.width,r[1]*c.height,(r[2]-r[0])*c.width,(r[3]-r[1])*c.height);}
    for(const kind of ['photo','uv']){
      let start=null;const c=q(kind),point=e=>{const r=c.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
      c.onpointerdown=e=>{if(review||e.button!==0)return;start=point(e);c.setPointerCapture(e.pointerId);};
      c.onpointermove=e=>{if(!start)return;const p=point(e),r=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];if(kind==='photo')crop=r;else rect=r;draw(kind);};
      c.onpointerup=()=>{start=null;};c.onpointercancel=()=>{start=null;};
    }
    async function loadMaps(){try{const d=await io.api('/api/characters/'+encodeURIComponent(slug)+'/texture-maps');if(dead)return;maps=d.maps||[];
      q('maps').innerHTML='<p>Select all matching face maps; click a map name to place its patch.</p>'+maps.map((m,i)=>`<label><input type="checkbox" data-ps-map="${m.index}" ${i===0?'checked':''}><button type="button" data-ps-show="${m.index}">${esc(m.name)} (${m.size.join(' × ')})</button></label>`).join('');
      if(maps[0]){images.uv=await image(maps[0].url);draw('uv');}
    }catch(e){note(e.message);}}
    host.querySelector('details').addEventListener('toggle',()=>{if(!maps.length&&host.querySelector('details').open)loadMaps();});
    q('file').onchange=async()=>{try{const f=q('file').files[0];if(!f)return;if(f.size>8*1024**2)throw Error('Photo must be at most 8 MiB');
      const data_url=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f);});
      const label=q('name').value.trim(),d=await io.api('/api/photo-skins/photos',{data_url,source_kind:q('source').value,label:label&&label!=='Photo character'?label:f.name.replace(/\.[^.]+$/,'').slice(0,80)});if(dead)return;photo=d.photo;images.photo=await image(d.url);crop=[0,0,1,1];draw('photo');note('Photo loaded. Select the face crop and matching UV region.');
    }catch(e){note(e.message);}};
    host.addEventListener('click',async e=>{const b=e.target.closest('[data-ps-show]');if(!b)return;try{images.uv=await image(maps.find(m=>m.index===+b.dataset.psShow).url);draw('uv');}catch(err){note(err.message);}});
    q('rotate').onclick=()=>{if(review)return;turn=(turn+1)%4;note('Patch rotation: '+turn*90+'°');};
    q('prepare').onclick=async()=>{if(review)return;try{if(!photo)throw Error('Choose a photo first');q('prepare').disabled=true;
      const [l,t,r,b]=rect,quad=[[l,t],[r,t],[r,b],[l,b]];for(let i=0;i<turn;i++)quad.push(quad.shift());
      const selected=[...host.querySelectorAll('[data-ps-map]:checked')].map(c=>+c.dataset.psMap);
      review=await io.api('/api/characters/'+encodeURIComponent(slug)+'/photo-skins',{name:q('name').value,photo,maps:selected,crop,quad,feather:+q('feather').value});if(dead)return;
      onPending(true);q('decision').hidden=false;q('result').innerHTML=review.images.map(m=>`<img alt="Photo skin candidate map" src="${esc(io.url?io.url('/api/artifacts/'+m.after):'/api/artifacts/'+m.after)}" style="max-width:180px">`).join('');note(review.notice);
    }catch(e){note(e.message);q('prepare').disabled=false;}};
    q('original').onclick=()=>onPreview?.(null);q('candidate').onclick=async()=>{try{await onPreview?.(review);}catch(e){note(e.message);}};
    async function decide(decision){if(!review)return;try{const d=await io.api('/api/photo-skins/'+review.id+'/decision',{decision});if(dead)return;review=null;onPending(false);q('decision').hidden=true;q('prepare').disabled=false;
      if(d.status==='accepted'){note('Separate photo donor created. Native builds still require gameplay verification.');onAccepted?.(d);}else{await onPreview?.(null);note('Rejected. Original model unchanged.');}
    }catch(e){note(e.message);}}
    q('accept').onclick=()=>decide('accept');q('reject').onclick=()=>decide('reject');
    return {dispose(){dead=true;}};
  }
  root.GBoxPhotoSkin={mount};if(typeof module!=='undefined')module.exports=root.GBoxPhotoSkin;
})(typeof window==='undefined'?globalThis:window);
