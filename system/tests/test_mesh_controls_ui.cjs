const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {withPage}=require('../scripts/browser_lifecycle.cjs');
const H=require('../clients/web/viz/retarget-handles.js');

test('shoe boundaries separate foot from shin without changing another side or the hands',()=>{
 const roles=['l_foot','l_foot','l_shin','r_foot','l_hand'];
 assert.deepEqual(H.shoeRoles([.1,.1,0,.1,.6,0,.1,.2,0,-.1,.6,0,.1,.1,0],roles,{shoe_tops:{l:.15}},0,2),['l_foot','l_shin','l_foot','r_foot','l_hand']);
 assert.deepEqual(H.normalize({shoe_tops:{l:2,r:-1},preserve_geometry:true}).shoe_tops,{l:.5,r:0});
 assert.equal(H.isIdentity({preserve_geometry:true}),false);
});

test('workspace download follows the same job and does not send emulator input',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/decimation-review.js'),'utf8'));
  const data=await evaluate(`(async()=>{
   const host=document.createElement('p');document.body.append(host);const calls=[];
   const env={assetUrl:u=>u,api:async(p,body,method)=>{calls.push({p,body,method});return body?{id:'workspace-job'}:{state:'succeeded',output:{result:{sha256:'a'.repeat(64)}}};}};
   await GBoxDecimationReview.workspace({source_job:'fit-job',model:'m'},env,host);
   const link=host.querySelector('a');const result={text:link.textContent,href:link.getAttribute('href'),download:link.download};
   await GBoxDecimationReview.workspace({source_job:'fit-job',model:'m'},env,host);
   return {calls,result};
  })()`);
  assert.equal(data.calls.filter(c=>c.body).length,1,'repeat follows the existing job');
  assert.equal(data.calls[0].body.tool,'mesh_workspace');
  assert.equal(data.result.href,'/api/artifacts/'+'a'.repeat(64));
  assert.equal(data.result.download,'geometry-review.blend');
  assert.equal(data.calls.some(c=>/sessions|launch|rebuild/.test(c.p)),false);
 });
});

test('topology workflows submit distinct jobs and name the resulting download',async()=>{
 await withPage(async evaluate=>{
  await evaluate(fs.readFileSync(path.join(__dirname,'../clients/web/viz/decimation-review.js'),'utf8'));
  const result=await evaluate(`(async()=>{
   const host=document.createElement('p');document.body.append(host);const calls=[];
   const env={assetUrl:u=>u,api:async(p,body)=>{if(body){calls.push(body);return {id:body.input.mode};}return {state:'succeeded',output:{result:{sha256:'b'.repeat(64),topology:{mode:p.split('/').at(-1)}}}};}};
   for(const mode of ['2d','3d','voxel_study'])await GBoxDecimationReview.workspace({character:'amy',mode},env,host,'hops_workspace');
   return {calls,text:host.textContent};
  })()`);
  assert.deepEqual(result.calls.map(c=>[c.tool,c.input.mode]),[['hops_workspace','2d'],['hops_workspace','3d'],['hops_workspace','voxel_study']]);
  assert.match(result.text,/voxel_study editable/);
 });
});
