const {test}=require('node:test'),assert=require('node:assert/strict');
const L=require('../clients/web/viz/launch-mods.js')({});
const sha=n=>String(n).repeat(64),meta={slug:'leon_photo_a',name:'Bla on Leon',photo_skin_approval:{source_photo:sha(1),images:[{before:sha(2),after:sha(3)}],
  story:{geometry:'unchanged',frames:[0,.5,1].map((f,i)=>({kind:'texture_projection',fraction:f,label:`Photo ${f*100}%`,sha256:sha(i+4)}))}}};
test('approved selfie stories include source photo, actual mesh snapshots and texture-map endpoints',()=>{
 const story=L.selfieFrom(meta);assert.equal(story.source,'/api/artifacts/'+sha(1));assert.equal(story.frames.length,3);
 assert.equal(story.geometry,'unchanged');assert.match(story.notice,/mesh shape unchanged/);
 const html=L.selfieHTML(story,1);assert.match(html,/Source photo/);assert.match(html,/lm-face-next/);assert.match(html,/Original texture/);
 assert.match(L.selfieHTML(story,0,{reduced:true}),/Photo 100%/);
});
test('missing mesh snapshots show honest texture-map comparison; invalid artifact URLs are not used',()=>{
 const m=structuredClone(meta);delete m.photo_skin_approval.story;
 assert.equal(L.selfieFrom(m).frames[0].kind,'texture_map');m.photo_skin_approval.source_photo='https://bad.test/photo';assert.equal(L.selfieFrom(m),null);
});
test('loading reads photo metadata within the existing budget and includes its thumbnails',async()=>{
 const model=await L.load({gameId:'g',mod:'build',fetchJson:async p=>p.includes('/details')?{characters:[{donors:[meta.slug],donor:{name:'Bla'}}]}:
  p.startsWith('/api/characters/')?meta:{items:[]}});
 assert.equal(model.selfies.length,1);assert.ok(L.thumbsOf(model).includes('/api/artifacts/'+sha(1)));
});
test('a claimed deformation needs actual geometry snapshots',()=>{
 const m=structuredClone(meta);m.photo_skin_approval.story.geometry='deformed';
 assert.equal(L.selfieFrom(m).geometry,'unchanged');
 m.photo_skin_approval.story.frames[0].kind='geometry_snapshot';assert.equal(L.selfieFrom(m).geometry,'deformed');
});
test('photo metadata loads before a slow index and a late response cannot extend the deadline',async()=>{
 let expire,signal,release;const asked=[];
 const pending=L.load({gameId:'g',mod:'build',setTimeout:f=>{expire=f;return 1},clearTimeout:()=>{},
  fetchJson:(p,s)=>{asked.push(p);signal=s;
   if(p.includes('/details'))return Promise.resolve({characters:[{donors:[meta.slug]}]});
   if(p.startsWith('/api/characters/'))return new Promise(r=>release=r);
   return new Promise(()=>{});
  }});
 await new Promise(r=>setImmediate(r));
 assert.ok(asked.includes('/api/characters/'+meta.slug),'photo lookup begins while index is still outstanding');
 expire();const model=await pending;assert.equal(signal.aborted,true);assert.deepEqual(model.selfies,[]);
 release(meta);await new Promise(r=>setImmediate(r));assert.deepEqual(model.selfies,[],'late metadata stays discarded');
});
