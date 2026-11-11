import struct
import zlib
import numpy as np
import pytest
from PIL import Image
from gbox import mt_arc, mt_model, re5_mesh_import as importer
from tests.test_mtf_mrl import fixture as material_fixture
from tests.test_mtf_tex import fixture as texture_fixture


def inputs(tmp_path,monkeypatch):
    mrl,raw,_=material_fixture()
    raw=bytearray(raw)
    start=mt_model.parse_mod(raw).header()['offsets']['bones']
    raw[start+1],raw[start+25]=255,0
    root=np.eye(4); root[3,1]=20
    child=np.eye(4); child[3,1]=10
    compression=np.diag([100.,100.,100.,1.]); compression[3,:3]=(-40.,0.,-40.)
    struct.pack_into('<32f',raw,start+2*24,*root.ravel(),*child.ravel())
    struct.pack_into('<32f',raw,start+2*88,*(compression@np.linalg.inv(root)).ravel(),
                     *(compression@np.linalg.inv(child@root)).ravel())
    contents=[('pawn\\body',bytes(raw)),('pawn\\body',mrl),('pawn\\body_BM',texture_fixture()),('untouched',b'preserved')]
    arc=mt_arc.build(mt_arc.Arc(7,[mt_arc.Entry(name,0x241F5DEB,len(data),0,0,zlib.compress(data)) for name,data in contents]))
    source=tmp_path/'source.glb';source.write_bytes(b'source fixture')
    gltf={'nodes':[{'name':'hip','children':[1]},{'name':'head'}]}
    world=[np.eye(4),np.eye(4)];world[1][1,3]=1.
    monkeypatch.setattr(importer.characters,'_load',lambda _: (gltf,None,None,world))
    def mesh(_,atlas_size):
        assert atlas_size==(32,32)
        vertices=[{'position':p,'normal':(0.,0.,1.),'uv':uv,'source_joints':[bone],'source_weights':[1.]}
                  for p,uv,bone in [((0.,0.,0.),(0.,0.),0),((1.,0.,0.),(1.,0.),0),((0.,1.,0.),(0.,1.),1)]]
        return vertices,[(0,1,2)],Image.new('RGBA',atlas_size,'blue'),{'materials':1}
    monkeypatch.setattr(importer.mtf_materials,'source_mesh',mesh)
    monkeypatch.setattr(importer.mtf_tex,'replace_image',lambda texture,image:texture)
    return arc,source


def test_source_proportions_pipeline_preserves_material_pair_and_complete_surface(tmp_path,monkeypatch):
    arc,source=inputs(tmp_path,monkeypatch)
    result,raw,atlas,receipt=importer.build_archive(arc,source,model_name='body',source_roles={'hip':'hip','head':'head'},
        target_roles={'hip':0,'head':1},segments={},scale=1.,pose_mode='source_proportions',height=50.)
    before,after=mt_arc.parse(arc),mt_arc.parse(result)
    assert all(a.data==b.data for a,b in zip(before.entries[1:],after.entries[1:]))
    model=mt_model.parse_mod(raw)
    points=model.positions(0)
    assert [min(p[i] for p in points) for i in range(3)]==pytest.approx((-25.,0.,-40.),abs=.004)
    assert [max(p[i] for p in points) for i in range(3)]==pytest.approx((25.,50.,-40.),abs=.004)
    assert model.bone_world()[0][1:]==pytest.approx((0.,20.,0.))
    assert model.bone_world()[1][1:]==pytest.approx((-25.,50.,-40.))
    assert receipt['bind_skeleton']['root_unchanged'] and not receipt['live_verified']
    assert atlas.size==(32,32) and receipt['triangles']==1 and receipt['envelope_count']==2


def test_source_proportions_refuses_ambiguous_model_or_unsupported_pose(tmp_path,monkeypatch):
    arc,source=inputs(tmp_path,monkeypatch)
    args=dict(model_name='body',source_roles={'hip':'hip','head':'head'},target_roles={'hip':0,'head':1},segments={},scale=1.)
    with pytest.raises(ValueError,match='pose mode'):
        importer.build_archive(arc,source,**args,pose_mode='guess')
    duplicate=mt_arc.parse(arc);duplicate.entries.append(duplicate.entries[0])
    with pytest.raises(ValueError,match='ambiguous'):
        importer.build_archive(mt_arc.build(duplicate),source,**args)


def test_centred_hip_keeps_floor_and_preserves_source_normals(tmp_path,monkeypatch):
    arc,source=inputs(tmp_path,monkeypatch)
    original=importer.mtf_materials.source_mesh
    def smooth(path,atlas_size):
        vertices,faces,atlas,report=original(path,atlas_size)
        return [v|{'normal':(0.,.6,.8)} for v in vertices],faces,atlas,report
    monkeypatch.setattr(importer.mtf_materials,'source_mesh',smooth)
    _,raw,_,receipt=importer.build_archive(arc,source,model_name='body',source_roles={'hip':'hip','head':'head'},
        target_roles={'hip':0,'head':1},segments={},scale=1.,pose_mode='source_proportions',height=50.,centre_hip=True)
    model=mt_model.parse_mod(raw)
    assert min(p[1] for p in model.positions(0))==pytest.approx(0.,abs=.004)
    assert model.bone_world()[1][1:]==pytest.approx((0.,50.,0.))
    assert model.normals(0)[0]==pytest.approx((0.,.6,.8),abs=.008)
    assert receipt['skin']['centre_hip']


def test_reposed_pipeline_rotates_surface_and_normals_but_retains_native_root(tmp_path,monkeypatch):
    arc,source=inputs(tmp_path,monkeypatch)
    _,raw,_,receipt=importer.build_archive(arc,source,model_name='body',source_roles={'hip':'hip','head':'head'},
        target_roles={'hip':0,'head':1},segments={'hip':'head'},scale=1.,pose_mode='source_reposed',height=50.,
        centre_hip=True,repose_frames={'hip':((0.,1.,0.),(0.,0.,1.),(0.,1.,0.),(-1.,0.,0.))})
    model=mt_model.parse_mod(raw)
    assert model.positions(0)[1]==pytest.approx((0.,0.,50.),abs=.004)
    assert model.normals(0)[0]==pytest.approx((-1.,0.,0.),abs=.008)
    assert model.bone_world()[0][1:]==pytest.approx((0.,20.,0.))
    assert model.bone_world()[1][1:]==pytest.approx((0.,50.,0.))
    assert receipt['skin']['rotation_determinants']==pytest.approx({'hip':1.,'head':1.})
    assert receipt['skin']['height']==50. and receipt['triangles']==1



def test_native_segments_options_address_entries_keep_normals_and_turn_clockwise_donors(tmp_path,monkeypatch):
    arc,source=inputs(tmp_path,monkeypatch)
    args=dict(model_name='body',source_roles={'hip':'hip','head':'head'},target_roles={'hip':0,'head':1},segments={},scale=1.)
    twice=mt_arc.parse(arc);twice.entries+=twice.entries[:2]
    doubled=mt_arc.build(twice)
    with pytest.raises(ValueError,match='ambiguous'):
        importer.build_archive(doubled,source,**args)
    result,raw,_,receipt=importer.build_archive(doubled,source,**args,model_entry=4,mrl_entry=5)
    before,after=mt_arc.parse(doubled),mt_arc.parse(result)
    assert [i for i,(a,b) in enumerate(zip(before.entries,after.entries)) if a.data!=b.data]==[4]
    assert (receipt['model_entry'],receipt['mrl_entry'],receipt['changed_entry_indices'])==(4,5,[4,2])
    for wrong in (dict(model_entry=4),dict(model_entry=5,mrl_entry=4),dict(model_entry=2,mrl_entry=5)):
        with pytest.raises(ValueError):
            importer.build_archive(doubled,source,**args,**wrong)
    original=importer.mtf_materials.source_mesh
    def tilted(path,atlas_size,**options):
        vertices,faces,atlas,report=original(path,atlas_size)
        return [v|{'normal':(0.,.6,.8)} for v in vertices],faces,atlas,report|{'face_normal_fallback_corners':0,'options':options}
    monkeypatch.setattr(importer.mtf_materials,'source_mesh',tilted)
    _,flat,_,recomputed=importer.build_archive(arc,source,**args)
    _,kept,_,carried=importer.build_archive(arc,source,**args,keep_source_normals=True,samplers_in_range=True)
    assert mt_model.parse_mod(flat).normals(0)[0]==pytest.approx((0.,0.,1.),abs=.008)
    assert mt_model.parse_mod(kept).normals(0)[0]==pytest.approx((0.,.6,.8),abs=.008)
    assert (recomputed['normals'],carried['normals'])==('recomputed per stored vertex','source')
    assert carried['appearance']['options']=={'strict_samplers':'in_range'} and recomputed['appearance']['options']=={}
    from gbox import mtf_author
    # normals that agree with the winding: a stale 'cw' survey flag must not turn it (that would draw it inside-out)
    _,kept_order,_,not_turned=importer.build_archive(arc,source,**args,keep_source_normals=True,reverse_winding=True)
    assert mtf_author.mesh_triangles(mt_model.parse_mod(kept_order),0)==[(0,1,2)]
    assert not not_turned['winding_reversed'] and not_turned['winding_reversal_requested']
    def clockwise(path,atlas_size,**options):
        vertices,faces,atlas,report=original(path,atlas_size)
        return [v|{'normal':(0.,-.6,-.8)} for v in vertices],faces,atlas,report|{'face_normal_fallback_corners':0}
    monkeypatch.setattr(importer.mtf_materials,'source_mesh',clockwise)
    _,turned,_,reversed_=importer.build_archive(arc,source,**args,keep_source_normals=True,reverse_winding=True)
    assert mtf_author.mesh_triangles(mt_model.parse_mod(kept),0)==[(0,1,2)]
    assert mtf_author.mesh_triangles(mt_model.parse_mod(turned),0)==[(0,2,1)] and reversed_['winding_reversed']
    with pytest.raises(ValueError,match='only the native_segments mode'):
        importer.build_archive(arc,source,**args,pose_mode='source_proportions',height=50.,keep_source_normals=True)
    monkeypatch.setattr(importer.mtf_materials,'source_mesh',lambda path,atlas_size:(
        [v|{'normal':(0.,0.,-1.)} for v in original(path,atlas_size)[0]],
        *original(path,atlas_size)[1:3],{'face_normal_fallback_corners':3}))
    with pytest.raises(ValueError,match='clockwise donor needs its own normals'):
        importer.build_archive(arc,source,**args,reverse_winding=True)
