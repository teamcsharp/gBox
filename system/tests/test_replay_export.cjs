const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),fsp=fs.promises,path=require('node:path'),os=require('node:os'),crypto=require('node:crypto'),vm=require('node:vm');
const R=require('../clients/desktop/recording-export.cjs');
const data=Buffer.from('test replay bytes'),clip={name:'replay-test.mp4',bytes:data.length,sha256:crypto.createHash('sha256').update(data).digest('hex')};
const fixture=async fn=>{const root=await fsp.mkdtemp(path.join(os.tmpdir(),'gbox-replay-export-'));try{await fn(root);}finally{await fsp.rm(root,{recursive:true,force:true});}};
const options=root=>({clip,directory:path.join(root,'local'),exportDir:path.join(root,'chosen'),fetchArtifact:async()=>new Response(data)});

test('replay is streamed and verified into the chosen folder, never overwriting another instance',async()=>fixture(async root=>{
 const o=options(root);await fsp.mkdir(o.exportDir);await fsp.writeFile(path.join(o.exportDir,clip.name),'another instance');
 const result=await R.saveReplay(o);assert.equal(path.dirname(result.file),o.exportDir);assert.equal(result.exported,true);
 assert.deepEqual(await fsp.readFile(result.file),data);assert.equal(await fsp.readFile(path.join(o.exportDir,clip.name),'utf8'),'another instance');
 assert.deepEqual(await fsp.readdir(o.directory),[]);assert.ok(!(await fsp.readdir(o.exportDir)).some(n=>n.endsWith('.partial')));
}));
test('an empty export preference saves replay in local recordings',async()=>fixture(async root=>{
 const o=options(root),r=await R.saveReplay({...o,exportDir:''});assert.equal(path.dirname(r.file),o.directory);assert.equal(r.exported,false);
 assert.deepEqual(await fsp.readdir(o.directory),[clip.name]);
}));
test('a failed destination reports failure and retains a verified local clip',async()=>fixture(async root=>{
 const o=options(root);await fsp.writeFile(o.exportDir,'not a directory');
 await assert.rejects(R.saveReplay(o),/Clip retained locally at .*Spark artifact is also retained/);
 const files=await fsp.readdir(o.directory);assert.equal(files.length,1);assert.deepEqual(await fsp.readFile(path.join(o.directory,files[0])),data);
}));
for(const [label,body] of [['digest mismatch',Buffer.from('bad replay bytes!')],['truncated',data.subarray(0,4)],['oversized',Buffer.concat([data,data])]]){
 test(`${label} downloads are discarded without publishing`,async()=>fixture(async root=>{
  const o=options(root);await assert.rejects(R.saveReplay({...o,fetchArtifact:async()=>new Response(body)}),/did not verify|exceeded/);
  assert.deepEqual(await fsp.readdir(o.directory),[]);assert.equal(fs.existsSync(o.exportDir),false);
 }));
}
test('HTTP failure and unsafe clip references cannot publish files',async()=>fixture(async root=>{
 const o=options(root);await assert.rejects(R.saveReplay({...o,fetchArtifact:async()=>new Response('missing',{status:404})}),/404/);
 for(const patch of [{sha256:'https://bad.test/video'},{name:'../escape.mp4'},{name:'C:\\escape.mp4'},{bytes:300*1048576}]){
  await assert.rejects(R.saveReplay({...o,clip:{...clip,...patch},fetchArtifact:()=>{throw Error('Must not fetch');}}),/Invalid/);
 }
 assert.deepEqual(await fsp.readdir(o.directory),[]);
}));
test('production IPC reads current per-instance folder and fetches only the authenticated artifact route',async()=>fixture(async root=>{
 const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8'),handlers={},requests=[];
 let current={recording:{exportDir:path.join(root,'first')}};
 const start=main.indexOf("ipcMain.handle('rec:save-clip'"),end=main.indexOf('// chat export:',start);
 vm.runInNewContext(main.slice(start,end),{ipcMain:{handle:(key,fn)=>handlers[key]=fn},recordingExport:R,RECORDING_DEFAULTS:R.DEFAULTS,
  REC_DIR:path.join(root,'local'),settings:()=>({...current,apiUrl:'http://configured-spark:8765'}),token:async()=>'private-test-token',AbortSignal,
  fetch:async(url,opts)=>{requests.push({url,opts});return new Response(data);}});
 let out=await handlers['rec:save-clip']({},clip);assert.equal(path.dirname(out.file),current.recording.exportDir);
 current={recording:{exportDir:path.join(root,'second')}};
 out=await handlers['rec:save-clip']({},clip);assert.equal(path.dirname(out.file),current.recording.exportDir);
 assert.equal(requests[0].url,'http://configured-spark:8765/api/artifacts/'+clip.sha256);
 assert.equal(requests[0].opts.headers.authorization,'Bearer private-test-token');assert.equal(requests[0].opts.redirect,'error');
}));
