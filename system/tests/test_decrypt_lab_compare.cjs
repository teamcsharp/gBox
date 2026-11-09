const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../clients/desktop/decrypt-lab-compare.js');

function fixture(){
  const model=(offset,ids=[0,14])=>({triangles:[0,1,2],frames:[0,2,4].map(frame=>({frame,
    positions:[0,0,0,1,0,0,0,1+frame,0],skeleton:{anim_ids:ids,parents:[255,0],bones:[[0,0,0],[offset+frame,1,0]]}}))});
  return {fps:30,frame_indices:[0,2,4],clip:{animation_index:0,frame_count:90},native:model(0),candidate:model(1)};
}
module.exports={fixture};

test('both panes share exact sampled native frame numbers',()=>{
  const data=C.validate(fixture());
  assert.equal(C.frameAtTime(data,0),0);assert.equal(C.frameAtTime(data,2/30),1);assert.equal(C.frameAtTime(data,4/30),2);
  assert.equal(C.frameAtTime(data,100),2);
  assert.deepEqual(C.jointDifference(data,1,14).delta,[1,0,0]);
  const mismatch=fixture();mismatch.candidate.frames.pop();
  assert.throws(()=>C.validate(mismatch),/same sampled frames/);
});

test('malformed geometry and unsupported animation cannot be presented as a comparison',()=>{
  const bad=fixture();bad.candidate.triangles=[0,1,99];assert.throws(()=>C.validate(bad),/triangles/);
  const tracks=fixture();tracks.diagnostics={unsupported_tracks:[{codec:99}]};assert.throws(()=>C.validate(tracks),/unsupported tracks/);
  const positions=fixture();positions.native.frames[1].positions[0]=NaN;assert.throws(()=>C.validate(positions),/complete model/);
  const ordering=fixture();ordering.frame_indices=[0,4,2];assert.throws(()=>C.validate(ordering),/increasing/);
});

test('joint correspondence follows native animation ids, never array position',()=>{
  const data=fixture();for(const frame of data.candidate.frames){frame.skeleton.anim_ids.reverse();frame.skeleton.bones.reverse();}
  assert.deepEqual(C.jointDifference(data,2,14).delta,[1,0,0]);
  assert.equal(C.jointDifference(data,0,200),null);
});

test('joint labels follow the selected limb instead of hiding the model under all joint names',()=>{
  assert.deepEqual(C.jointLabels(14),[2,11,12,14]);
  assert.deepEqual(C.jointLabels(6),[2,6,7,9]);
  assert.deepEqual(C.jointLabels(18),[0,16,17,18]);
  assert.deepEqual(C.jointLabels(0),[0,2,4]);
  assert.equal(C.WINDOW_FRAMES,60);
});

test('joint focus centers corresponding joints independently and preserves absolute differences',()=>{
  const data=fixture(),before=C.jointDifference(data,1,14);
  assert.deepEqual(C.focusOffsets(data,1,14),{native:[-2,-1,-0],candidate:[-3,-1,-0],radius:25});
  assert.deepEqual(C.jointDifference(data,1,14),before);
  assert.equal(C.focusOffsets(data,0,200),null);
});

test('limb isolation follows skin ownership and descendants even when head and glove overlap',()=>{
  const positions=[0,0,0,1,0,0,0,1,0,0,0,0,1,0,0,0,1,0];
  const model={triangles:[0,1,2,3,4,5],skin_influences:[[[2,1]],[[2,1]],[[2,1]],[[1,.1],[1,.15],[3,.25],[1,-1],[0,.5]],[[0,1]],[[0,1]]],
    frames:[{positions,skeleton:{anim_ids:[0,14,4,100],parents:[255,0,0,1],bones:[[0,0,0],[0,0,0],[0,0,0],[0,0,0]]}}]};
  const result=C.limbSelection(model,0,14);
  assert.deepEqual([...result.bones],[1,3]);
  assert.deepEqual(result.triangles,[3,4,5]);
  assert.deepEqual(model.triangles,[0,1,2,3,4,5]);
  assert.equal(C.limbSelection({...model,skin_influences:undefined},0,14),null);
  const extended=structuredClone(model);extended.frames.push(structuredClone(extended.frames[0]));extended.frames[1].positions[9]=40;
  assert.equal(C.limbRadius({native:model,candidate:extended},14),40);
  assert.equal(C.limbRadius({native:model,candidate:model},14),25);
});
