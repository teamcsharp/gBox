const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),fsp=fs.promises,path=require('node:path'),os=require('node:os'),vm=require('node:vm');
const {spawnSync,spawn}=require('node:child_process');
const R=require('../clients/desktop/recording-export.cjs');
const fixture=async fn=>{const root=await fsp.mkdtemp(path.join(os.tmpdir(),'gbox-record-export-'));try{await fn(root);}finally{await fsp.rm(root,{recursive:true,force:true});}};

test('new per-instance preferences capture gameplay and preserve originals',()=>{
 assert.equal(R.preferences().capture,'gameplay');assert.equal(R.preferences().keep,true);
 assert.equal(R.preferences({capture:'app',keep:false}).capture,'app');
 assert.equal(R.preferences({capture:'unknown'}).capture,'gameplay');
 assert.throws(()=>R.preferences({exportDir:'relative/folder'}),/absolute/);
});
test('verified export keeps the original and avoids another instance filename',async()=>fixture(async root=>{
 const original=path.join(root,'original.mp4'),candidate=path.join(root,'original-20MB.mp4'),destination=path.join(root,'share');
 await fsp.writeFile(original,'full-size original');await fsp.writeFile(candidate,'compressed video');await fsp.mkdir(destination);
 await fsp.writeFile(path.join(destination,path.basename(candidate)),'other instance video');
 const out=await R.finish({original,candidate,exportDir:destination,keep:true,originalStamp:await R.fingerprint(original)});
 assert.equal(out.exported,true);assert.equal(await fsp.readFile(out.file,'utf8'),'compressed video');
 assert.equal(await fsp.readFile(original,'utf8'),'full-size original');
 assert.equal(await fsp.readFile(path.join(destination,path.basename(candidate)),'utf8'),'other instance video');
 assert.equal(fs.existsSync(candidate),false);assert.equal(out.originalDeleted,false);
 assert.equal((await fsp.readdir(destination)).some(n=>n.endsWith('.partial')),false);
}));
test('failed network-style export retains both local videos even when deletion is requested',async()=>fixture(async root=>{
 const original=path.join(root,'original.mp4'),candidate=path.join(root,'compressed.mp4'),blocked=path.join(root,'not-a-folder');
 await fsp.writeFile(original,'full-size');await fsp.writeFile(candidate,'compressed');await fsp.writeFile(blocked,'blocked');
 await assert.rejects(R.finish({original,candidate,exportDir:path.join(blocked,'share'),keep:false,originalStamp:await R.fingerprint(original)}),/Original retained.*local video retained/);
 assert.equal(await fsp.readFile(original,'utf8'),'full-size');assert.equal(await fsp.readFile(candidate,'utf8'),'compressed');
}));
test('optional deletion happens after export and never removes a changed original',async()=>fixture(async root=>{
 const original=path.join(root,'original.mp4'),candidate=path.join(root,'compressed.mp4'),destination=path.join(root,'share');
 await fsp.writeFile(original,'full-size');await fsp.writeFile(candidate,'compressed');
 let out=await R.finish({original,candidate,exportDir:destination,keep:false,originalStamp:await R.fingerprint(original)});
 assert.equal(out.originalDeleted,true);assert.equal(fs.existsSync(original),false);assert.equal(await fsp.readFile(out.file,'utf8'),'compressed');
 await fsp.writeFile(original,'first original');const stamp=await R.fingerprint(original);
 await fsp.writeFile(original,'changed original during encoding');await fsp.writeFile(candidate,'second compressed');
 out=await R.finish({original,candidate,exportDir:destination,keep:false,originalStamp:stamp});
 assert.equal(out.originalDeleted,false);assert.match(out.warning,/changed/);assert.equal(await fsp.readFile(original,'utf8'),'changed original during encoding');
}));
test('already-small clips export and an empty destination never deletes the only original',async()=>fixture(async root=>{
 const original=path.join(root,'original.webm');await fsp.writeFile(original,'small');
 const stamp=await R.fingerprint(original);
 const same=await R.finish({original,candidate:original,exportDir:'',keep:false,originalStamp:stamp});
 assert.equal(same.originalDeleted,false);assert.equal(fs.existsSync(original),true);
 const out=await R.finish({original,candidate:original,exportDir:path.join(root,'share'),keep:true,originalStamp:stamp});
 assert.equal(await fsp.readFile(out.file,'utf8'),'small');assert.equal(fs.existsSync(original),true);
}));
test('processing refuses an unrelated video outside the local recordings folder',async()=>fixture(async root=>{
 const folder=path.join(root,'recordings');await fsp.mkdir(folder);const other=path.join(root,'other.mp4');await fsp.writeFile(other,'outside');
 await assert.rejects(R.ownedOriginal(other,folder),/Only a local/);
}));

test('real production compression handler exports playable video and audio',{skip:!process.env.GBOX_TEST_FFMPEG},async()=>fixture(async root=>{
 const ff=process.env.GBOX_TEST_FFMPEG,original=path.join(root,'synthetic-recording.mp4'),destination=path.join(root,'exports');
 const made=spawnSync(ff,['-v','error','-y','-f','lavfi','-i','testsrc2=size=320x240:rate=30','-f','lavfi','-i','sine=frequency=660:sample_rate=44100','-t','3','-c:v','libx264','-preset','ultrafast','-crf','12','-c:a','aac',original],{windowsHide:true});
 assert.equal(made.status,0,String(made.stderr));const before=await fsp.readFile(original),handlers={};
 const main=fs.readFileSync(path.join(__dirname,'../clients/desktop/main.js'),'utf8');
 vm.runInNewContext(main.slice(main.indexOf('let recFitBusy = false;'),main.indexOf('// chat export:')),
  {ipcMain:{handle:(name,fn)=>handlers[name]=fn},recordingExport:R,RECORDING_DEFAULTS:R.DEFAULTS,settings:()=>({}),fs,path,REC_DIR:root,require,
   findExe:name=>name==='ffmpeg.exe'?ff:null,send:()=>{},runExe:(exe,args)=>new Promise((resolve,reject)=>{
    const p=spawn(exe,args,{windowsHide:true});let errors='';p.stdout.resume();p.stderr.on('data',d=>errors+=d);p.on('error',reject);p.on('close',n=>n===0?resolve():reject(Error(errors)));
   })});
 const out=await handlers['rec:fit']({},original,{targetMB:.15,seconds:3,speed:'fast',keep:true,exportDir:destination});
 assert.equal(out.compressed,true);assert.equal(out.exported,true);assert.ok(out.bytes<=.15*1048576);assert.deepEqual(await fsp.readFile(original),before);
 const decoded=spawnSync(ff,['-v','error','-i',out.file,'-map','0:v:0','-map','0:a:0','-f','null','-'],{windowsHide:true});
 assert.equal(decoded.status,0,String(decoded.stderr));
 if(process.env.GBOX_RECORDING_EVIDENCE){await fsp.mkdir(process.env.GBOX_RECORDING_EVIDENCE,{recursive:true});await fsp.copyFile(out.file,path.join(process.env.GBOX_RECORDING_EVIDENCE,'compressed-test.mp4'));}
}));
