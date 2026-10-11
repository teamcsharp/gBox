"""Synthetic regressions for native snapshot composition and GLTF skin frames."""
import base64,json,struct
from pathlib import Path
import numpy as np
import pytest
from .. import complete as E
from .. import actor_attachment_frame as A
from .test_chain_vertices import fixture
from .fixtures import synthetic_prop,synthetic_chain


def test_actor_root_is_authored_prop_frame_and_follows_actual_parent():
    acs=synthetic_prop(parent=1);acs[34]=1
    world=np.repeat(np.eye(4)[None],17,axis=0);world[1,:3,3]=[4,5,6]
    world[15,:3,3]=[100,200,300]
    frames=A.source_held_prop_frames(acs,world)
    assert len(frames)==1 and frames[0]['parent']==1 and frames[0]['model']==7
    np.testing.assert_allclose(frames[0]['world'][:3,3],[5,7,9])
    np.testing.assert_allclose(frames[0]['world'][:3,0],[0,1,0],atol=1e-12)
    adjusted=E._remap_actor({'parent':15,'descriptor':80},frames[0])
    assert adjusted['parent']==1 and adjusted['actor_publisher']==32


def test_hidden_prop_does_not_publish_actor_frame():
    acs=synthetic_prop(kind=3);acs[34]=1
    assert A.source_held_prop_frames(acs,np.repeat(np.eye(4)[None],17,axis=0))==[]
    with pytest.raises(ValueError,match='authored source publisher'):
        E._remap_actor({'parent':15},None)


def test_root_prop_cannot_be_recursively_attached_to_eye15():
    acs=synthetic_prop(parent=15);acs[34]=1
    with pytest.raises(ValueError,match='verified core parent'):
        A.source_held_prop_frames(acs,np.repeat(np.eye(4)[None],17,axis=0))


def test_selected_chain_bake_preserves_other_descriptor_snapshot():
    original,acs,relative=fixture();acs.extend(bytes(120));acs[244:340]=acs[32:128]
    struct.pack_into('<3f',acs,244+0x14,-10,20,30)
    struct.pack_into('<6I',acs,0,1,32,1,244,255,0)
    world=np.repeat(np.eye(4)[None],17,axis=0)
    first=E.V.bake_chain_positions(original,acs,world,{32:[[0,-1,0]]},
                                    pose_evidence='synthetic observed',descriptor_offsets={32})
    later=E.V.bake_chain_positions(first['chr_data'],acs,world,{244:[[0,-1,1]]},
                                    pose_evidence='synthetic observed',descriptor_offsets={244})
    assert len(first['instances'])==len(later['instances'])==1
    assert first['instances'][0]['chr_data']!=later['instances'][0]['chr_data']
    np.testing.assert_allclose(struct.unpack_from('<3f',first['chr_data'],24+relative[0]),[1,-1,0],atol=1e-6)
    a=E.C.assemble_instances(first['chr_data'],bytes(2048),first['instances'])
    b=E.C.assemble_instances(later['chr_data'],bytes(2048),later['instances'])
    prims=E._mark(a['prims'],'deformed_chain','32_0')+E._mark(b['prims'],'deformed_chain','244_0')
    E._validate_primitives(prims,17)
    assert sum(len(p['tris']) for p in prims)==2
    assert [p['native_model'] for p in prims]==[0,0]
    assert not np.allclose(prims[0]['pos'],prims[1]['pos'])


def test_selected_rigid_descriptor_preserves_every_repeated_native_model():
    acs=synthetic_chain();world=np.repeat(np.eye(4)[None],17,axis=0)
    result=E.C.accessory_attachments(acs,world,descriptor_offsets={32})
    assert [i['model'] for i in result['instances']]==[7,7,8]
    with pytest.raises(ValueError,match='absent'):
        E.C.accessory_attachments(acs,world,descriptor_offsets={12345})


def test_configured_chain_uses_world_gravity_and_per_link_carry():
    acs=synthetic_chain();world=np.repeat(np.eye(4)[None],17,axis=0)
    vectors=E.configured_displacements(acs,32,world,3,1)
    np.testing.assert_allclose(np.linalg.norm(vectors,axis=1),.25)
    np.testing.assert_allclose(vectors[:,1]/vectors[:,2],[.1,.2,.4],rtol=1e-6)
    struct.pack_into('<f',acs,36,0)
    np.testing.assert_allclose(E.configured_displacements(acs,32,world,3,1),0)


def test_exported_bind_matrices_keep_rotations_and_non_topological_joint_ids(tmp_path):
    original,acs,_=fixture()
    world=np.repeat(np.eye(4)[None],17,axis=0)
    world[2]=E.C._rotation(1,16384);world[2,:3,3]=[3,4,5]
    world[0]=world[2]@E.C._rotation(2,16384);world[0,:3,3]=[6,7,8]
    result=E.C.assemble_instances(original,bytes(2048),[{'descriptor':32,'link':0,'model':0,'parent':1,'world':world[1]}])
    full={'world':world,'parent':E.CORE_PARENTS,'prims':result['prims'],'report':{'stem':'synthetic'}}
    path=E.write_complete(tmp_path/'source.gltf',full)
    gl=json.loads(path.read_text());local=np.array(gl['nodes'][0]['matrix']).reshape(4,4).T
    np.testing.assert_allclose(world[2]@local,world[0],atol=1e-7)
    assert gl['nodes'][2]['name']=='hip' and gl['nodes'][1]['name']=='head'
    accessor=gl['accessors'][gl['skins'][0]['inverseBindMatrices']]
    view=gl['bufferViews'][accessor['bufferView']];offset=view.get('byteOffset',0)+accessor.get('byteOffset',0)
    blob=base64.b64decode(gl['buffers'][0]['uri'].split(',',1)[1])
    matrices=np.frombuffer(blob[offset:offset+17*64],dtype='<f4').reshape(17,4,4).transpose(0,2,1)
    np.testing.assert_allclose(world[2]@matrices[2],np.eye(4),atol=1e-7)


@pytest.mark.parametrize('field',('J','W','tris','pos'))
def test_invalid_source_geometry_or_skin_is_rejected(field):
    original,acs,_=fixture()
    prims=E.C.assemble_instances(original,bytes(2048),[{'descriptor':32,'link':0,'model':0,'parent':1,'world':np.eye(4)}])['prims']
    if field=='J':prims[0]['J'][0,0]=99
    elif field=='W':prims[0]['W'][0,0]=.5
    elif field=='tris':prims[0]['tris'][0,0]=99
    else:prims[0]['pos'][0,0]=np.nan
    with pytest.raises(ValueError):E._validate_primitives(prims,17)
