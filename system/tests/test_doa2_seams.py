import struct

import numpy as np
import pytest

from gbox import doa2_seams as S
from gbox import doa2_geometry as G


def coefficients():
    t = np.arange(16)/16
    return np.column_stack((1-3*t+2*t*t, 2*t*t-t, 4*t*(1-t)))


def fixture():
    header = bytearray(80)
    struct.pack_into('<4I',header,0,0x8000002c,0x83000000,0x20282452,0x08000000)
    struct.pack_into('<2i',header,32,0,1)
    mesh = {'header':bytes(header),'vertices':[(0,0,0,0,0,1,.1,.2),
           (1,0,0,0,0,1,.3,.4),(0,1,0,0,0,1,.5,.6)],'triangles':[(0,1,2)]}
    model = G.encode_model({'global_flags':(1,1)},[mesh],references=False)
    data = bytearray(24)+model+bytes(8)
    table = len(data);data.extend(struct.pack('<I',0x0c300000))
    texture_table = len(data);data.extend(struct.pack('<3I',32|(32<<16),0x101,0x0d200000))
    struct.pack_into('<6I',data,0,24,table,texture_table,1,1,0)
    archive = G.decode_chr(data)
    record_offsets = [r['offset'] for r in archive['models'][0]['meshes'][0]['records']]
    relative = [offset-24 for offset in record_offsets]
    sup = bytearray(struct.pack('<2I',8,0))
    sup.extend(struct.pack('<IBBBB',16,0,1,0,0))
    pairs = np.stack((np.eye(3),np.eye(3)),axis=1).ravel()
    sup.extend(struct.pack('<30f',*pairs,*np.zeros(12)))
    sup.extend(struct.pack('<II6fI',16,relative[0],1,2,3,0,0,1,0))
    sup.extend(struct.pack('<II6fIII',8,relative[1],1,2,3,0,0,1,relative[2]+1,0,0))
    return bytes(data),bytes(sup),record_offsets


def test_native_direct_group_curve_group_and_alias_preserve_uv_and_other_bytes():
    chr_data,sup,offsets = fixture()
    world = np.array([np.eye(4),np.eye(4)]);world[1,0,3]=10
    result = S.bake_chr(chr_data,sup,world,coefficients(),emulate_marker=False)
    data = result['chr_data']
    assert struct.unpack_from('<6f',data,offsets[0])==(11,2,3,0,0,1)
    assert struct.unpack_from('<6f',data,offsets[1])==(6,2,3,0,0,1)
    assert data[offsets[2]:offsets[2]+24]==data[offsets[1]:offsets[1]+24]
    permitted = {i for o in offsets for i in range(o,o+24)}
    assert all(a==b or i in permitted for i,(a,b) in enumerate(zip(chr_data,data)))
    assert G.roundtrip_chr(G.decode_chr(data))==data
    assert result['vertex_influences'][offsets[0]]['weights']==[0,1]
    assert result['vertex_influences'][offsets[2]]['weights']==[.5,.5]


def test_processed_marker_and_original_geometry_remain_separate():
    chr_data,sup,offsets = fixture()
    before=bytes(chr_data)
    world = np.array([np.eye(4),np.eye(4)])
    result = S.bake_chr(chr_data,sup,world,coefficients())
    assert struct.unpack_from('<I',result['chr_data'],offsets[0])[0]&1
    assert chr_data==before
    assert result['chr_data']!=before
    assert result['report']['emulate_processed_marker']


def test_curved_midpoint_translation_uses_both_controls_in_native_spaces():
    _,sup,_ = fixture();seam=S.decode_sup(sup)[0]
    seam['controls']=np.array([[99,0,0],[99,0,0],[2,4,6],[10,12,14]],float)
    relative=np.eye(4);relative[0,3]=20
    matrix=S.curve_matrix(seam,relative,8,coefficients())
    assert np.array_equal(matrix[:3,3],[16,8,10])
    assert np.allclose(matrix[:3,:3],np.eye(3))


def test_rotated_axis_interpolation_is_orthogonal_and_singular_pose_is_rejected():
    _,sup,_=fixture();seam=S.decode_sup(sup)[0]
    relative=np.eye(4);relative[:3,:3]=[[0,-1,0],[1,0,0],[0,0,1]]
    matrix=S.curve_matrix(seam,relative,5,coefficients())
    assert np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3))
    assert np.isclose(np.linalg.det(matrix[:3,:3]),1)
    relative[:3,:3]=np.diag([1,-1,-1])
    with pytest.raises(ValueError,match='singular'):S.curve_matrix(seam,relative,8,coefficients())


def test_alias_without_unique_payload_and_unknown_group_are_rejected():
    _,sup,_=fixture();data=bytearray(sup)
    struct.pack_into('<I',data,140,113)
    with pytest.raises(ValueError,match='preceding'):S.decode_sup(bytes(data))
    data=bytearray(sup);struct.pack_into('<I',data,136,17)
    with pytest.raises(ValueError,match='initial direct'):S.decode_sup(bytes(data))


def test_vertex_write_outside_inline_records_is_rejected():
    chr_data,sup,_=fixture();data=bytearray(sup)
    struct.pack_into('<I',data,140,4)
    with pytest.raises(ValueError,match='inline'):S.bake_chr(chr_data,bytes(data),np.array([np.eye(4)]*2),coefficients())


def test_missing_joints_non_affine_pose_and_wrong_executable_are_rejected():
    chr_data,sup,_=fixture()
    with pytest.raises(ValueError,match='absent joint'):S.bake_chr(chr_data,sup,np.array([np.eye(4)]),coefficients())
    world=np.array([np.eye(4)]*2);world[0,3,0]=1
    with pytest.raises(ValueError,match='affine'):S.bake_chr(chr_data,sup,world,coefficients())
    with pytest.raises(ValueError,match='different executable'):S.native_coefficients(bytes(100))


def test_assembled_seam_mesh_retains_native_texture_uvs_and_both_joint_weights():
    chr_data,sup,_=fixture()
    world=np.array([np.eye(4)]*2);world[0,2,3]=5;world[1,0,3]=10;world[1,2,3]=5
    result=S.assemble_core(chr_data,sup,bytes([255])*2048,world,{0:0},coefficients())
    primitive=result['prims'][0]
    assert np.allclose(primitive['pos'],[[11,2,8],[6,2,8],[6,2,8]])
    assert np.allclose(primitive['uv'],[[.1,.2],[.3,.4],[.5,.6]])
    assert primitive['tex'].shape==(32,32,4) and np.all(primitive['tex']==255)
    assert primitive['J'].tolist()==[[0,1,0,0]]*3
    assert np.allclose(primitive['W'],[[0,1,0,0],[.5,.5,0,0],[.5,.5,0,0]])
    assert result['report']['triangles']==1
    with pytest.raises(ValueError,match='conflict'):
        S.assemble_core(chr_data,sup,bytes([255])*2048,world,{0:1},coefficients())


@pytest.mark.parametrize('cut',[4,135,145,-4])
def test_truncated_sup_tables_and_payloads_fail(cut):
    _,sup,_=fixture()
    with pytest.raises(ValueError):S.decode_sup(sup[:cut])


def test_core_export_preserves_rotated_joint_inverse_binds(tmp_path):
    from gbox import re4gc_models as R
    world = np.repeat(np.eye(4)[None], 15, axis=0)
    world[0,:3,:3] = [[0,-1,0],[1,0,0],[0,0,1]]
    world[0,:3,3] = [1,2,3]
    profile = {'world': world.tolist(), 'parent': [-1]+[0]*14,
               'roles': {f'role{j}': j for j in range(15)}}
    primitive = {'pos':np.array([[0.,0,0],[1.,0,0],[0.,1,0]]),
                 'nrm':np.tile([0.,0,1],(3,1)), 'uv':np.zeros((3,2)),
                 'tris':np.array([[0,1,2]]), 'J':np.zeros((3,4),np.uint16),
                 'W':np.tile([1.,0,0,0],(3,1)), 'tex':np.full((8,8,4),255,np.uint8), 'wrap':(33071,33648)}
    path = S.write_core(tmp_path/'core.gltf', {'prims':[primitive],'report':{}}, profile, 'test')
    gl, acc, _ = R._gltf_load(path)
    actual = R._node_world(gl)
    inverse = acc(gl['skins'][0]['inverseBindMatrices']).reshape(15,4,4).transpose(0,2,1)
    assert np.allclose(actual[:15],world)
    assert np.allclose(actual[:15] @ inverse,np.eye(4),atol=1e-6)
    texture=gl['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index']
    sampler=gl['samplers'][gl['textures'][texture]['sampler']]
    assert (sampler['wrapS'],sampler['wrapT'])==(33071,33648)
    from gbox.sm64_swap import load_rig
    loaded=load_rig(path,{'hip':'role0','head':'role1'})
    assert loaded['prims'][0]['wrap']==(33071,33648)
