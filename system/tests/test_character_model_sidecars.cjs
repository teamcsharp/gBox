const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../clients/web/viz/character-model.js'),'utf8').replace(/^import[^\n]*\n/gm,'').replace(/^export /gm,'');
const context={};vm.createContext(context);vm.runInContext(source+';this.resolve=resolveCharacterResource;this.parse=parseModel;',context);
const fileUrl=rel=>'/api/characters/owned/file/'+rel.split('/').map(encodeURIComponent).join('/')+'?token=fixture';

test('glTF sidecars preserve model folders, URI encoding and authenticated file routes',()=>{
 const options={fileUrl,model:'fits/player/model.gltf'};
 assert.equal(context.resolve('mesh.bin',options),'/api/characters/owned/file/fits/player/mesh.bin?token=fixture');
 assert.equal(context.resolve('../textures/face%20map.png',options),'/api/characters/owned/file/fits/textures/face%20map.png?token=fixture');
 assert.equal(context.resolve('./normal.png?v=2#sample',options),'/api/characters/owned/file/fits/player/normal.png?token=fixture&v=2#sample');
 assert.equal(context.resolve('mesh.bin',options,'animations/run.gltf'),'/api/characters/owned/file/animations/mesh.bin?token=fixture');
 assert.throws(()=>context.resolve('../../../escape.bin',options),/escapes/);
 assert.throws(()=>context.resolve('bad%2Ffile.bin',options),/Invalid/);
});

test('embedded images, object URLs and absolute resources remain unchanged',()=>{
 for(const uri of ['data:image/png;base64,fixture','blob:https://gbox.test/fixture','https://cdn.test/face.png','http://lan.test/mesh.bin','/api/artifacts/fixture','//cdn.test/mesh.bin'])assert.equal(context.resolve(uri,{fileUrl,model:'model.glb'}),uri);
 assert.equal(context.resolve('mesh.bin',{}),'mesh.bin');
});

test('the actual loader registers the collection URL modifier for glTF buffers and images',async()=>{
 const requests=[];context.THREE={LoadingManager:class{setURLModifier(fn){this.modify=fn;return this;}}};
 context.GLTFLoader=class{constructor(manager){this.manager=manager;}async parseAsync(bytes,base){
  assert.equal(base,'');const gltf=JSON.parse(new TextDecoder().decode(bytes));
  for(const r of [...gltf.buffers,...gltf.images])requests.push(this.manager.modify(r.uri));return {scene:'loaded'};
 }};
 const bytes=new TextEncoder().encode(JSON.stringify({asset:{version:'2.0'},buffers:[{uri:'mesh.bin'}],images:[{uri:'../textures/albedo.png'},{uri:'data:image/png;base64,fixture'}]}));
 const result=await context.parse(bytes,{fileUrl,model:'models/model.gltf'},'models/model.gltf');
 assert.equal(result.scene,'loaded');assert.deepEqual(requests,['/api/characters/owned/file/models/mesh.bin?token=fixture','/api/characters/owned/file/textures/albedo.png?token=fixture','data:image/png;base64,fixture']);
});
