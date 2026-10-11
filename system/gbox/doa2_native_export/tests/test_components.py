import struct
import numpy as np
import pytest
from .. import native_components as C


def synthetic_wings():
    data=bytearray(256)
    struct.pack_into('<4I',data,0,5,32,255,0)
    struct.pack_into('<7I',data,32,2,64,82,94,106,120,132)
    struct.pack_into('<9h',data,64,0,0,0,0,0,0,0,0,0)
    struct.pack_into('<6H',data,120,1,2,3,4,5,6)
    struct.pack_into('<9f',data,132,1,2,3,0,0,4,0,0,5)
    return data

def test_zero_angle_native_chain_is_cumulative():
    result=C.wing_attachments(synthetic_wings(),np.eye(4))
    np.testing.assert_allclose(result['world'][17][:3,3],[1,2,3])
    np.testing.assert_allclose(result['world'][18][:3,3],[1,2,7])
    np.testing.assert_allclose(result['world'][19][:3,3],[1,2,12])
    np.testing.assert_allclose(result['world'][22][:3,3],[-1,2,12])

def test_z_quarter_turn_then_local_translation():
    data=synthetic_wings()
    struct.pack_into('<h',data,68,16384)
    result=C.wing_attachments(data,np.eye(4))
    np.testing.assert_allclose(result['world'][17][:3,0],[0,1,0],atol=1e-12)
    np.testing.assert_allclose(result['world'][20][:3,0],[0,-1,0],atol=1e-12)

def test_frame_uses_recorded_native_channels():
    data=synthetic_wings()
    struct.pack_into('<3h',data,82+6,0,0,16384)
    result=C.wing_attachments(data,np.eye(4),frame=1)
    np.testing.assert_allclose(result['world'][17][:3,0],[0,1,0],atol=1e-12)
    with pytest.raises(ValueError,match='frame'):
        C.wing_attachments(data,np.eye(4),frame=2)

@pytest.mark.parametrize('word,value',[(1,1000),(5,1000),(6,1000)])
def test_invalid_descriptor_pointers_fail_before_conversion(word,value):
    data=synthetic_wings();struct.pack_into('<I',data,32+4*word,value)
    with pytest.raises(ValueError,match='bounds'):
        C.wing_attachments(data,np.eye(4))

def test_invalid_model_rejected_and_original_bytes_unchanged():
    data=synthetic_wings();before=bytes(data)
    with pytest.raises(ValueError,match='model ID'):
        C.wing_attachments(data,np.eye(4),model_count=3)
    assert bytes(data)==before

def test_empty_accessory_has_no_phantom_wings():
    result=C.wing_attachments(struct.pack('<II',255,0),np.eye(4))
    assert result['world']==result['models']=={}

def test_unverified_executable_cannot_create_eye_attachment():
    with pytest.raises(ValueError,match='verified'):
        C.eye_attachments(b'bad executable',5,np.eye(4))

def synthetic_chain(style=1):
    data=bytearray(180)
    struct.pack_into('<4I',data,0,1,32,255,0)
    struct.pack_into('<4B',data,32,3,1,0,style)
    struct.pack_into('<14f',data,36,.25,.1,1,.3,1,2,3,0,0,-1,.5,0,1,.05)
    struct.pack_into('<I',data,32+0x44,140)
    struct.pack_into('<3H',data,140,7,7,8)
    return data

def test_chain_preserves_duplicate_native_mesh_instances():
    result=C.accessory_attachments(synthetic_chain(),np.repeat(np.eye(4)[None],17,axis=0),model_count=9,
                                   chain_displacements={32:[[0,-.25,0]]*3})
    assert [i['model'] for i in result['instances']]==[7,7,8]
    np.testing.assert_allclose([i['world'][:3,3] for i in result['instances']],[[1,2,3],[1,1.75,3],[1,1.5,3]])
    assert all(i['parent']==1 for i in result['instances'])

def test_chain_direction_is_converted_from_world_to_parent_coordinates():
    pose=np.repeat(np.eye(4)[None],17,axis=0);pose[1]=C._rotation(2,16384)
    result=C.accessory_attachments(synthetic_chain(),pose,
                                   chain_displacements={32:[[.25,0,0]]*3})
    np.testing.assert_allclose(result['instances'][0]['world'][:3,1],[-1,0,0],atol=1e-12)
    np.testing.assert_allclose(result['instances'][1]['world'][:3,3],[-1.75,1,3],atol=1e-12)

def test_configured_chain_direction_decay_does_not_accumulate_gravity():
    result=C.accessory_attachments(synthetic_chain(),np.repeat(np.eye(4)[None],17,axis=0))
    direction=np.asarray(result['evidence'][0]['local_displacements'])
    np.testing.assert_allclose(direction[:,1]/direction[:,2],[.1,.2,.4],rtol=1e-6)
    assert 'collision is not simulated' in result['instances'][0]['pose']

def test_style_zero_can_draw_a_zero_length_static_native_model():
    data=synthetic_chain(0);struct.pack_into('<11f',data,36,*([0]*11))
    result=C.accessory_attachments(data,np.repeat(np.eye(4)[None],17,axis=0))
    assert len(result['instances'])==3
    for instance in result['instances']:np.testing.assert_allclose(instance['world'],np.eye(4))

def test_observed_chain_vectors_need_correct_shape_and_nonsingular_direction():
    pose=np.repeat(np.eye(4)[None],17,axis=0)
    with pytest.raises(ValueError,match='count or shape'):
        C.accessory_attachments(synthetic_chain(),pose,chain_displacements={32:[[0,-1,0]]})
    with pytest.raises(ValueError,match='singular'):
        C.accessory_attachments(synthetic_chain(),pose,chain_displacements={32:[[1,0,0]]*3})

def test_malformed_chain_tables_do_not_change_input():
    data=synthetic_chain();struct.pack_into('<I',data,32+0x44,179)
    original=bytes(data)
    with pytest.raises(ValueError,match='bounds'):
        C.accessory_attachments(data,np.repeat(np.eye(4)[None],17,axis=0))
    assert bytes(data)==original

def synthetic_prop(kind=1,parent=5):
    data=bytearray(96);struct.pack_into('<4I',data,0,0,32,255,0)
    struct.pack_into('<4B',data,32,kind,parent,0,0)
    struct.pack_into('<3f',data,32+0x1c,1,2,3)
    struct.pack_into('<3hH',data,32+0x28,0,0,16384,7)
    return data

def test_prop_translates_before_native_z_y_x_rotations():
    result=C.accessory_attachments(synthetic_prop(),np.repeat(np.eye(4)[None],17,axis=0),model_count=9)
    prop=result['instances'][0]
    assert prop['model']==7 and prop['parent']==5
    np.testing.assert_allclose(prop['world'][:3,3],[1,2,3])
    np.testing.assert_allclose(prop['world'][:3,0],[0,1,0],atol=1e-12)

def test_hidden_native_prop_kind_three_is_not_exported():
    result=C.accessory_attachments(synthetic_prop(kind=3),np.repeat(np.eye(4)[None],17,axis=0))
    assert result['instances']==[] and result['hidden'][0]['model']==7

def test_native_parent15_requires_separate_actor_world_transform():
    pose=np.repeat(np.eye(4)[None],17,axis=0)
    pose[15,:3,3]=[100,200,300]
    with pytest.raises(ValueError,match='base_world'):
        C.accessory_attachments(synthetic_prop(parent=15),pose)
    result=C.accessory_attachments(synthetic_prop(parent=15),pose,base_world=np.eye(4))
    np.testing.assert_allclose(result['instances'][0]['world'][:3,3],[1,2,3])
