/* Photo-layer deformation only. Native encoded previews remain the build authority.
 * mount(host, {reference, layer, coverage?, respectAlpha?, deformation?,
 *   onEditStart?(recipe, {tool}), onChange?(recipe, {reason}), onCommit?(recipe)}).
 * Images accept URLs or CanvasImageSource; coverage uses its fixed alpha channel.
 * ready/update load images safely; getDeformation returns a cloned version-1 recipe.
 * View opacity, zoom, and layer toggles are comparison aids, not baked recipe settings.
 */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.GBoxFaceWarpEditor=factory();})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const copy=v=>JSON.parse(JSON.stringify(v)), clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const finite=v=>typeof v==='number'&&Number.isFinite(v), empty=()=>({version:1,lattice:null,strokes:[]});
  function identity(columns=5,rows=columns){return {columns,rows,points:Array.from({length:columns*rows},(_,i)=>({x:(i%columns)/(columns-1),y:Math.floor(i/columns)/(rows-1)}))};}
  const area=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
  function triangles(grid){const out=[];for(let y=0;y<grid.rows-1;y++)for(let x=0;x<grid.columns-1;x++){
    const a=y*grid.columns+x,b=a+1,c=a+grid.columns,d=c+1;
    out.push([a,b,d],[a,d,c]);
  }return out;}
  function normalize(value){
    if(value==null||(typeof value==='object'&&!Array.isArray(value)&&!Object.keys(value).length))return empty();
    if(typeof value!=='object'||Array.isArray(value)||value.version!==1)throw Error('Unsupported deformation version.');
    if(Object.keys(value).some(k=>!['version','lattice','strokes'].includes(k)))throw Error('Unknown deformation setting.');
    const out=empty();
    if(value.lattice!=null){
      const g=value.lattice;
      if(typeof g!=='object'||Array.isArray(g)||Object.keys(g).some(k=>!['columns','rows','points'].includes(k)))throw Error('Unknown lattice setting.');
      if(!Number.isInteger(g.columns)||!Number.isInteger(g.rows)||g.columns<2||g.columns>9||g.rows<2||g.rows>9||!Array.isArray(g.points)||g.points.length!==g.columns*g.rows)throw Error('Lattice must contain a 2–9 by 2–9 grid.');
      out.lattice={columns:g.columns,rows:g.rows,points:g.points.map(p=>{
        if(!p||Object.keys(p).some(k=>!['x','y'].includes(k))||!finite(p.x)||!finite(p.y)||p.x<-.5||p.x>1.5||p.y<-.5||p.y>1.5)throw Error('Lattice point is outside the editing area.');
        return {x:p.x,y:p.y};
      })};
      if(triangles(out.lattice).some(t=>area(...t.map(i=>out.lattice.points[i]))<=1e-8))throw Error('Lattice cells cannot cross or fold.');
      // Positive cells and a simple outer boundary prevent ambiguous inverse mappings.
      const boundary=[];
      for(let x=0;x<g.columns;x++)boundary.push(x);
      for(let y=1;y<g.rows;y++)boundary.push(y*g.columns+g.columns-1);
      for(let x=g.columns-2;x>=0;x--)boundary.push((g.rows-1)*g.columns+x);
      for(let y=g.rows-2;y>0;y--)boundary.push(y*g.columns);
      const points=out.lattice.points, n=boundary.length;
      for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
        if(j===i+1||(i===0&&j===n-1))continue;
        const a=points[boundary[i]],b=points[boundary[(i+1)%n]],c=points[boundary[j]],d=points[boundary[(j+1)%n]];
        if(area(a,b,c)*area(a,b,d)<=0&&area(c,d,a)*area(c,d,b)<=0&&Math.max(a.x,b.x)>=Math.min(c.x,d.x)&&Math.max(c.x,d.x)>=Math.min(a.x,b.x)&&Math.max(a.y,b.y)>=Math.min(c.y,d.y)&&Math.max(c.y,d.y)>=Math.min(a.y,b.y))throw Error('Lattice boundary cannot cross itself.');
      }
    }
    if(Object.hasOwn(value,'strokes')){
      if(!Array.isArray(value.strokes)||value.strokes.length>256)throw Error('A face supports up to 256 liquify strokes.');
      out.strokes=value.strokes.map(s=>{
        if(!s||Object.keys(s).some(k=>!['x','y','dx','dy','radius'].includes(k))||!['x','y','dx','dy','radius'].every(k=>finite(s[k]))||s.x<0||s.x>1||s.y<0||s.y>1||s.radius<.005||s.radius>1||Math.hypot(s.dx,s.dy)>s.radius*.25+1e-12)throw Error('Liquify stroke is outside the supported range.');
        return {x:s.x,y:s.y,dx:s.dx,dy:s.dy,radius:s.radius};
      });
    }
    return out;
  }
  function inverseStroke(q,s){
    if((q.x-s.x)**2+(q.y-s.y)**2>s.outer2)return q;
    let x=q.x,y=q.y;
    for(let i=0;i<16;i++){const f=Math.max(0,1-((x-s.x)**2+(y-s.y)**2)*s.inverseR2)**2;x=q.x-s.dx*f;y=q.y-s.dy*f;}
    return {x,y};
  }
  function makeInverse(value){
    const d=normalize(value), g=d.lattice, native=g&&identity(g.columns,g.rows).points;
    const strokes=d.strokes.map(s=>({...s,inverseR2:1/(s.radius*s.radius),outer2:(s.radius+Math.hypot(s.dx,s.dy))**2}));
    const cells=g?triangles(g).map(t=>{const p=t.map(i=>g.points[i]);return {p,n:t.map(i=>native[i]),den:area(...p),left:Math.min(...p.map(v=>v.x)),right:Math.max(...p.map(v=>v.x)),top:Math.min(...p.map(v=>v.y)),bottom:Math.max(...p.map(v=>v.y))};}):null;
    return q=>{
      for(let i=strokes.length-1;i>=0;i--)q=inverseStroke(q,strokes[i]);
      if(!cells)return q;
      for(const c of cells){
        if(q.x<c.left-1e-8||q.x>c.right+1e-8||q.y<c.top-1e-8||q.y>c.bottom+1e-8)continue;
        const a=area(c.p[1],c.p[2],q)/c.den,b=area(c.p[2],c.p[0],q)/c.den,k=1-a-b;
        if(a>=-1e-8&&b>=-1e-8&&k>=-1e-8)return {x:clamp(a*c.n[0].x+b*c.n[1].x+k*c.n[2].x,0,1),y:clamp(a*c.n[0].y+b*c.n[1].y+k*c.n[2].y,0,1)};
      }
      return null;
    };
  }
  function warpPixels(source,width,height,value){
    const d=normalize(value), out=new Uint8ClampedArray(width*height*4);
    const trivial=d.strokes.every(s=>s.dx===0&&s.dy===0)&&(!d.lattice||d.lattice.points.every((p,i)=>Math.abs(p.x-(i%d.lattice.columns)/(d.lattice.columns-1))<1e-12&&Math.abs(p.y-Math.floor(i/d.lattice.columns)/(d.lattice.rows-1))<1e-12));
    if(trivial){out.set(source);return out;}
    const inverse=makeInverse(d);
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      const uv=inverse({x:(x+.5)/width,y:(y+.5)/height});
      if(!uv||uv.x<0||uv.y<0||uv.x>1||uv.y>1)continue;
      const sx=clamp(uv.x*width-.5,0,width-1),sy=clamp(uv.y*height-.5,0,height-1),ix=Math.floor(sx),iy=Math.floor(sy),fx=sx-ix,fy=sy-iy;
      const indices=[(iy*width+ix)*4,(iy*width+Math.min(ix+1,width-1))*4,(Math.min(iy+1,height-1)*width+ix)*4,(Math.min(iy+1,height-1)*width+Math.min(ix+1,width-1))*4];
      const weights=[(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy];
      // Premultiplied interpolation avoids dark fringes around the photo mask.
      let alpha=0;for(let i=0;i<4;i++)alpha+=source[indices[i]+3]*weights[i];
      const offset=(y*width+x)*4;out[offset+3]=alpha;
      if(alpha>0)for(let c=0;c<3;c++){let sum=0;for(let i=0;i<4;i++)sum+=source[indices[i]+c]*source[indices[i]+3]*weights[i];out[offset+c]=sum/alpha;}
    }
    return out;
  }
  function mount(host,options={}){
    const token={};host._faceWarpEditor=token;
    let dead=false,serial=0,frame=0,loading=false,reference=null,layer=null,coverage=null,clipPixels=null,referencePixels=null,pixels=null,photoCanvas=null,drag=null;
    let lowPixels=null,lowClipPixels=null,lowReferencePixels=null,lowPhotoCanvas=null;
    let cachedKey='',cachedPixels=null;
    let deformation=normalize(options.deformation), undoStack=[],redoStack=[],tool='liquify',hover=null,compare=false;
    const q=s=>host.querySelector(s), current=()=>!dead&&host._faceWarpEditor===token&&host.isConnected!==false;
    host.innerHTML=`<style>.fw-editor{font:13px system-ui;color:var(--fg,#eee);background:var(--bg,#191c23);padding:10px;border:1px solid var(--line,#454955);border-radius:7px}.fw-row{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:7px 0}.fw-row label{display:inline-flex;gap:5px;align-items:center}.fw-row input[type=range]{width:110px}.fw-stage{overflow:auto;max-height:65vh;min-height:220px;background:repeating-conic-gradient(#242832 0% 25%,#303540 0% 50%) 0/20px 20px;border:1px solid #555;padding:18px}.fw-stage canvas{display:block;touch-action:none;image-rendering:pixelated;cursor:crosshair}.fw-editor button[aria-pressed=true]{outline:2px solid #8995ff}.fw-editor [role=status]{min-height:2.5em;color:var(--mut,#bac2d0);margin-bottom:0}.fw-editor [hidden]{display:none}</style>
      <div class="fw-editor"><div class="fw-row"><button type="button" data-fw-tool="liquify" aria-pressed="true">Liquify / push</button><button type="button" data-fw-tool="lattice" aria-pressed="false">Lattice</button>
      <label>Grid <select data-fw-grid aria-label="Lattice grid size">${[2,3,4,5,6,7,8,9].map(v=>`<option value="${v}"${v===5?' selected':''}>${v} × ${v}</option>`).join('')}</select></label></div>
      <div class="fw-row"><label>Brush radius <input data-fw-radius aria-label="Liquify brush radius" type="range" min="1" max="50" value="18"><output data-fw-radius-label>18%</output></label><label>Strength <input data-fw-strength aria-label="Liquify strength" type="range" min="5" max="100" value="70"><output data-fw-strength-label>70%</output></label></div>
      <div class="fw-row"><label><input type="checkbox" data-fw-reference checked> Original texture</label><label><input type="checkbox" data-fw-layer checked> Photo layer</label><label>Overlay opacity (preview) <input type="range" data-fw-opacity aria-label="Photo preview opacity" min="0" max="100" value="70"></label><label>Zoom <select data-fw-zoom aria-label="Texture zoom">${[1,2,4,8].map(v=>`<option value="${v}"${v===2?' selected':''}>${v}×</option>`).join('')}</select></label><button type="button" data-fw-compare aria-pressed="false">Show original</button></div>
      <div class="fw-stage"><canvas data-fw-canvas width="256" height="256" tabindex="0" aria-label="Face texture deformation canvas. Drag to push the photo layer or move lattice points."></canvas></div>
      <div class="fw-row"><button type="button" data-fw-undo disabled>Undo</button><button type="button" data-fw-redo disabled>Redo</button><button type="button" data-fw-reset>Reset this face</button><button type="button" data-fw-commit>Preview native encoding</button></div><p role="status" aria-live="polite">Loading face layers…</p></div>`;
    const canvas=q('[data-fw-canvas]'),ctx=canvas.getContext('2d'), listeners=[];
    function on(el,event,fn){el.addEventListener(event,fn);listeners.push(()=>el.removeEventListener(event,fn));}
    const say=text=>{if(current())q('[role=status]').textContent=text;};
    function buttons(){q('[data-fw-undo]').disabled=loading||!undoStack.length;q('[data-fw-redo]').disabled=loading||!redoStack.length;q('[data-fw-commit]').disabled=loading||!pixels;}
    function changed(reason){options.onChange?.(copy(deformation),{reason});}
    function remember(before,reason){if(JSON.stringify(before)===JSON.stringify(deformation))return;undoStack.push(before);if(undoStack.length>40)undoStack.shift();redoStack=[];buttons();changed(reason);}
    function schedule(){if(!current()||frame)return;frame=requestAnimationFrame(()=>{frame=0;draw();});}
    function draw(){
      if(!current())return;
      ctx.clearRect(0,0,canvas.width,canvas.height);ctx.imageSmoothingEnabled=false;
      if(reference&&(compare||q('[data-fw-reference]').checked))ctx.drawImage(reference,0,0,canvas.width,canvas.height);
      if(pixels&&!compare&&q('[data-fw-layer]').checked){
        // Smaller rasters keep pointer drags responsive; release restores the full local texture.
        const reduced=drag&&lowPixels,activePixels=reduced?lowPixels:pixels,activeClip=reduced?lowClipPixels:clipPixels,activeBase=reduced?lowReferencePixels:referencePixels,activeCanvas=reduced?lowPhotoCanvas:photoCanvas;
        const key=JSON.stringify(deformation);
        if(cachedKey!==key||cachedPixels!==activePixels){
          const data=warpPixels(activePixels.data,activePixels.width,activePixels.height,deformation);
          if(activeClip)for(let i=0;i<data.length;i+=4){data[i+3]=data[i+3]*activeClip[i+3]/255;if(data[i+3]===0)data[i]=data[i+1]=data[i+2]=0;}
          if(options.respectAlpha&&activeBase)for(let i=0;i<data.length;i+=4)data[i+3]=data[i+3]*activeBase[i+3]/255;
          activeCanvas.getContext('2d').putImageData(new ImageData(data,activePixels.width,activePixels.height),0,0);cachedKey=key;cachedPixels=activePixels;
        }
        if(options.respectAlpha&&reference&&q('[data-fw-reference]').checked)ctx.globalCompositeOperation='source-atop';
        ctx.globalAlpha=+q('[data-fw-opacity]').value/100;ctx.drawImage(activeCanvas,0,0,canvas.width,canvas.height);ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
      }
      if(!compare&&tool==='lattice'&&pixels){
        const g=deformation.lattice||identity(+q('[data-fw-grid]').value),p=g.points;
        ctx.strokeStyle='#77daff';ctx.lineWidth=1;
        for(let y=0;y<g.rows;y++)for(let x=0;x<g.columns;x++){const i=y*g.columns+x;for(const j of [x+1<g.columns?i+1:-1,y+1<g.rows?i+g.columns:-1])if(j>=0){ctx.beginPath();ctx.moveTo(p[i].x*canvas.width,p[i].y*canvas.height);ctx.lineTo(p[j].x*canvas.width,p[j].y*canvas.height);ctx.stroke();}}
        for(let i=0;i<p.length;i++){ctx.beginPath();ctx.arc(p[i].x*canvas.width,p[i].y*canvas.height,4,0,Math.PI*2);ctx.fillStyle=drag?.index===i?'#fff':'#2579a7';ctx.fill();ctx.stroke();}
      }
      if(!compare&&tool==='liquify'&&hover){ctx.strokeStyle='#fff';ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(hover.x*canvas.width,hover.y*canvas.height,+q('[data-fw-radius]').value/100*canvas.width,+q('[data-fw-radius]').value/100*canvas.height,0,0,Math.PI*2);ctx.stroke();}
    }
    function point(event){const b=canvas.getBoundingClientRect();return {x:(event.clientX-b.left)/b.width,y:(event.clientY-b.top)/b.height};}
    function finish(cancel=false){
      if(!drag)return;const old=drag;drag=null;
      try{if(canvas.hasPointerCapture(old.id))canvas.releasePointerCapture(old.id);}catch{}
      if(cancel){deformation=old.before;say('Gesture cancelled. Previous alignment restored.');}else{remember(old.before,old.index==null?'liquify':'lattice');say(deformation.strokes.length>=256?'This face reached 256 liquify strokes. Undo or reset before adding more.':'Local photo preview updated. Preview native encoding before accepting this face.');}
      schedule();
    }
    on(canvas,'pointerdown',event=>{
      if(event.button!==0||loading||!pixels||compare||!q('[data-fw-layer]').checked||drag)return;
      const p=point(event);if(p.x<0||p.x>1||p.y<0||p.y>1)return;
      const before=copy(deformation);let index;
      if(tool==='lattice'){
        const g=deformation.lattice||identity(+q('[data-fw-grid]').value),b=canvas.getBoundingClientRect();let distance=18;
        g.points.forEach((v,i)=>{const d=Math.hypot((p.x-v.x)*b.width,(p.y-v.y)*b.height);if(d<distance){index=i;distance=d;}});
        if(index==null){say('Drag a blue lattice point to reshape the photo layer.');return;}
        options.onEditStart?.(copy(before),{tool});deformation.lattice=g;
      }
      else options.onEditStart?.(copy(before),{tool});
      drag={id:event.pointerId,last:p,before,index};canvas.setPointerCapture(event.pointerId);event.preventDefault();schedule();
    });
    on(canvas,'pointermove',event=>{
      const p=point(event);hover=p;
      if(!drag||drag.id!==event.pointerId){schedule();return;}
      if(tool==='lattice'){
        const previous=deformation.lattice.points[drag.index];deformation.lattice.points[drag.index]={x:clamp(p.x,-.5,1.5),y:clamp(p.y,-.5,1.5)};
        try{normalize(deformation);}catch{deformation.lattice.points[drag.index]=previous;say('This move would fold the lattice. Move nearby points first.');}
      }else{
        const next={x:clamp(p.x,0,1),y:clamp(p.y,0,1)},r=+q('[data-fw-radius]').value/100,strength=+q('[data-fw-strength]').value/100;
        const dx=(next.x-drag.last.x)*strength,dy=(next.y-drag.last.y)*strength,n=Math.max(1,Math.ceil(Math.hypot(dx,dy)/(r*.249)));
        if(Math.hypot(dx,dy)<1e-8){drag.last=next;schedule();return;}
        if(deformation.strokes.length+n<=256){
          for(let i=0;i<n;i++)deformation.strokes.push({x:clamp(drag.last.x+(next.x-drag.last.x)*i/n,0,1),y:clamp(drag.last.y+(next.y-drag.last.y)*i/n,0,1),dx:dx/n,dy:dy/n,radius:r});
        }else say('This face reached 256 liquify strokes. Undo or reset before adding more.');
        drag.last=next;
      }
      event.preventDefault();schedule();
    });
    on(canvas,'pointerup',event=>{if(drag?.id===event.pointerId)finish();});
    on(canvas,'pointercancel',event=>{if(drag?.id===event.pointerId)finish(true);});
    on(canvas,'lostpointercapture',event=>{if(drag?.id===event.pointerId)finish(true);});
    on(canvas,'pointerleave',()=>{if(!drag){hover=null;schedule();}});
    on(canvas,'keydown',event=>{if(event.key==='Escape'&&drag){finish(true);event.preventDefault();}else if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();if(event.shiftKey)redo();else undo();}});
    for(const el of host.querySelectorAll('[data-fw-tool]'))on(el,'click',()=>{finish(true);tool=el.dataset.fwTool;for(const b of host.querySelectorAll('[data-fw-tool]'))b.setAttribute('aria-pressed',String(b===el));schedule();});
    for(const name of ['radius','strength'])on(q('[data-fw-'+name+']'),'input',()=>{q('[data-fw-'+name+'-label]').textContent=q('[data-fw-'+name+']').value+'%';schedule();});
    for(const name of ['opacity','reference','layer'])on(q('[data-fw-'+name+']'),'input',schedule);
    on(q('[data-fw-grid]'),'change',()=>{
      finish(true);if(deformation.lattice){const before=copy(deformation),g=identity(+q('[data-fw-grid]').value),old=deformation.lattice,native=identity(old.columns,old.rows);
        // Resample the existing forward displacement; changing grid size keeps the edit.
        for(const p of g.points){const x=p.x*(old.columns-1),y=p.y*(old.rows-1),ix=Math.min(Math.floor(x),old.columns-2),iy=Math.min(Math.floor(y),old.rows-2),fx=x-ix,fy=y-iy,a=iy*old.columns+ix;
          const ids=fy<=fx?[a,a+1,a+old.columns+1]:[a,a+old.columns+1,a+old.columns],weights=fy<=fx?[1-fx,fx-fy,fy]:[1-fy,fx,fy-fx];let dx=0,dy=0;
          ids.forEach((id,i)=>{dx+=(old.points[id].x-native.points[id].x)*weights[i];dy+=(old.points[id].y-native.points[id].y)*weights[i];});p.x+=dx;p.y+=dy;}
        const next={...deformation,lattice:g};try{deformation=normalize(next);remember(before,'grid');}catch{q('[data-fw-grid]').value=String(old.columns);say('That grid would fold the current edit. Keep this grid or reset first.');}}
      schedule();
    });
    on(q('[data-fw-zoom]'),'change',()=>{zoom();schedule();});
    on(q('[data-fw-compare]'),'click',()=>{finish(true);compare=!compare;q('[data-fw-compare]').setAttribute('aria-pressed',String(compare));q('[data-fw-compare]').textContent=compare?'Return to edited face':'Show original';schedule();});
    function zoom(){const scale=+q('[data-fw-zoom]').value;canvas.style.width=(canvas.width*scale)+'px';canvas.style.height=(canvas.height*scale)+'px';}
    function undo(){if(!current())return;finish(true);if(!undoStack.length)return;redoStack.push(copy(deformation));deformation=undoStack.pop();buttons();schedule();changed('undo');}
    function redo(){if(!current())return;finish(true);if(!redoStack.length)return;undoStack.push(copy(deformation));deformation=redoStack.pop();buttons();schedule();changed('redo');}
    function reset(){if(!current())return;finish(true);const before=copy(deformation);deformation=empty();remember(before,'reset');schedule();}
    on(q('[data-fw-undo]'),'click',undo);on(q('[data-fw-redo]'),'click',redo);on(q('[data-fw-reset]'),'click',reset);
    on(q('[data-fw-commit]'),'click',()=>{finish();options.onCommit?.(copy(deformation));});
    async function image(source){
      if(!source)return null;if(typeof source!=='string')return source;
      return new Promise((yes,no)=>{const img=new Image();img.crossOrigin='anonymous';img.onload=()=>yes(img);img.onerror=()=>no(Error('Face image could not be loaded.'));img.src=source;});
    }
    async function update(next={}){
      if(!current())return false;finish(true);const n=++serial,edited=Object.hasOwn(next,'deformation')?normalize(next.deformation):null;
      const replacesImages=Object.hasOwn(next,'reference')||Object.hasOwn(next,'layer')||Object.hasOwn(next,'coverage');
      if(!replacesImages){if(edited){deformation=edited;undoStack=[];redoStack=[];}buttons();schedule();return true;}
      loading=true;buttons();say('Loading face layers…');
      try{
        const [r,l,c]=await Promise.all([Object.hasOwn(next,'reference')?image(next.reference):reference,Object.hasOwn(next,'layer')?image(next.layer):layer,Object.hasOwn(next,'coverage')?image(next.coverage):coverage]);
        if(!current()||n!==serial)return false;
        const source=r||l;if(!source)throw Error('Choose an original texture and projected photo layer.');
        const w=source.naturalWidth||source.width,h=source.naturalHeight||source.height;if(!w||!h)throw Error('Face image has no pixels.');
        const limit=clamp(options.maxPreviewSize||256,32,512),ratio=Math.min(1,limit/Math.max(w,h));canvas.width=Math.max(1,Math.round(w*ratio));canvas.height=Math.max(1,Math.round(h*ratio));
        const pc=document.createElement('canvas');pc.width=canvas.width;pc.height=canvas.height;
        if(l)pc.getContext('2d').drawImage(l,0,0,pc.width,pc.height);
        const data=l?pc.getContext('2d').getImageData(0,0,pc.width,pc.height):null;
        let mask=null;if(c){const mc=document.createElement('canvas');mc.width=pc.width;mc.height=pc.height;const mctx=mc.getContext('2d');mctx.imageSmoothingEnabled=false;mctx.drawImage(c,0,0,mc.width,mc.height);mask=mctx.getImageData(0,0,mc.width,mc.height).data;}
        let basePixels=null;if(r&&options.respectAlpha){const rc=document.createElement('canvas');rc.width=pc.width;rc.height=pc.height;rc.getContext('2d').drawImage(r,0,0,rc.width,rc.height);basePixels=rc.getContext('2d').getImageData(0,0,rc.width,rc.height).data;}
        reference=r;layer=l;coverage=c;clipPixels=mask;referencePixels=basePixels;photoCanvas=pc;pixels=data;
        lowPixels=null;lowClipPixels=null;lowReferencePixels=null;lowPhotoCanvas=null;
        if(data&&Math.max(pc.width,pc.height)>128){
          const scale=128/Math.max(pc.width,pc.height),lw=Math.max(1,Math.round(pc.width*scale)),lh=Math.max(1,Math.round(pc.height*scale));
          const resize=(rgba,nearest=false)=>{if(!rgba)return null;const src=document.createElement('canvas'),dst=document.createElement('canvas');src.width=pc.width;src.height=pc.height;src.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(rgba),pc.width,pc.height),0,0);dst.width=lw;dst.height=lh;const dc=dst.getContext('2d');dc.imageSmoothingEnabled=!nearest;dc.drawImage(src,0,0,lw,lh);return dc.getImageData(0,0,lw,lh);};
          lowPixels=resize(data.data);lowClipPixels=resize(mask,true)?.data||null;lowReferencePixels=resize(basePixels)?.data||null;lowPhotoCanvas=document.createElement('canvas');lowPhotoCanvas.width=lw;lowPhotoCanvas.height=lh;
        }
        if(edited)deformation=edited;else if(replacesImages)deformation=empty();
        undoStack=[];redoStack=[];if(deformation.lattice)q('[data-fw-grid]').value=String(deformation.lattice.columns);zoom();
        say('Drag to align the photo with the original face. Changes stay local until native preview and approval.');return true;
      }catch(error){if(current()&&n===serial){pixels=null;reference=null;layer=null;coverage=null;clipPixels=null;referencePixels=null;lowPixels=null;lowClipPixels=null;lowReferencePixels=null;lowPhotoCanvas=null;say(error.message);}return false;}
      finally{if(current()&&n===serial){loading=false;buttons();schedule();}}
    }
    const api={ready:null,update,getDeformation:()=>copy(deformation),undo,redo,reset,dispose(){if(dead)return;finish(true);dead=true;serial++;if(frame)cancelAnimationFrame(frame);frame=0;listeners.forEach(off=>off());if(host._faceWarpEditor===token){delete host._faceWarpEditor;host.innerHTML='';}}};
    api.ready=update(options);return api;
  }
  return {mount,normalize,identity,makeInverse,warpPixels};
});
