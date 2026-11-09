const {test}=require('node:test');
const assert=require('node:assert/strict');
const {request}=require('../clients/desktop/decrypt-lab.cjs');
const base={title:'re5_switch',arc_path:'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc'};

test('model reads forward validated bodies without recursion and retain vertex budget',()=>{
  for(const path of ['/api/decrypt-lab/model-info','/api/decrypt-lab/model-geometry']){
    const body={...base,entry:'pawn\\pl\\pl00\\model\\pl0000',max_points:12000};
    assert.deepEqual(request({path,body}),{path,method:'POST',body});
  }
  for(const arc_path of ['../outside.arc','C:/outside.arc','/outside.arc'])
    assert.throws(()=>request({path:'/api/decrypt-lab/model-geometry',body:{...base,arc_path}}),/Invalid/);
});

test('archive swap bridge keeps explicit zero-based duplicate-name indices',()=>{
  const path='/api/decrypt-lab/arc-swap';
  const body={...base,entry:'same',donor_arc:'donor.arc',donor_entry:'same',entry_index:0,donor_index:17};
  assert.deepEqual(request({path,body}).body,{...body,build:'gbox-lab'});
  assert.throws(()=>request({path,body:{...body,donor_index:1.5}}),/entry index/);
});

test('comparison bridge allows only bounded read-only clip requests',()=>{
  const path='/api/decrypt-lab/model-compare';
  const body={...base,build:'candidate',animation_entry:115,animation_index:0,frame_count:60,frame_step:2};
  assert.deepEqual(request({path,body}).body,{...body,op:'sample',model_name:'pl0000'});
  assert.equal(request({path,body:{...body,raw_fk:true}}).body.raw_fk,true);
  for(const update of [{frame_count:61},{frame_step:0},{animation_index:-1},{build:'../escape'},{op:'apply'},{raw_fk:'true'}])
    assert.throws(()=>request({path,body:{...body,...update}}),/Invalid comparison/);
});
