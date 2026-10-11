import struct
import numpy as np
import pytest
from .. import acs_cloth_grids as V
from .test_chain_vertices import fixture as chain_fixture


def fixture(parent=1,draw=0,flags=0):
    chr_data,_,offsets=chain_fixture()
    acs=bytearray(336)
    struct.pack_into('<4I',acs,0,2,32,255,0)
    struct.pack_into('<8B',acs,32,1,parent,draw,0,1,2,255,flags)
    struct.pack_into('<10f',acs,40,.1,.01,.7,.2,0,.02,.3,0,1,.05)
    struct.pack_into('<2f',acs,32+0x30,.1,.2)
    struct.pack_into('<i',acs,32+0x60,-1)
    struct.pack_into('<f',acs,32+0xa0,999)
    struct.pack_into('<3I',acs,32+0xe0,284,296,0)
    struct.pack_into('<3f',acs,284,.2,.3,.4)
    # First row aliases two vertices, second row targets a third.
    struct.pack_into('<3I',acs,296,offsets[0]|1,offsets[1],offsets[2])
    return chr_data,acs,offsets


def test_native_grid_world_to_parent_and_alias_write_preserves_other_bytes():
    original,acs,offsets=fixture();snapshot=bytes(acs)
    world=np.repeat(np.eye(4)[None],17,axis=0)
    world[1,:3,:3]=[[0,-2,0],[1,0,0],[0,0,3]]
    world[1,:3,3]=[4,5,6]
    local=np.array([[[0,0,0],[1,2,3],[4,5,6]]],float)
    observed=local@world[1,:3,:3].T+world[1,:3,3]
    result=V.bake_world_grids(original,acs,world,{32:observed},pose_evidence='synthetic affine regression')
    output=result['chr_data'];allowed=set()
    for i,offset in enumerate(offsets):
        position=local[0,1 if i<2 else 2]
        np.testing.assert_allclose(struct.unpack_from('<3f',output,24+offset),position,atol=1e-6)
        assert struct.unpack_from('<I',output,24+offset)[0]&1
        allowed.update(range(24+offset,24+offset+12))
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(original,output)))
    assert snapshot==bytes(acs) and len(output)==len(original)
    assert len(result['vertex_owners'])==3 and result['instances']==[]


@pytest.mark.parametrize('offset',[0,4,12,24,32,80,0xfffffff0])
def test_grid_destination_cannot_overwrite_native_headers_or_commands(offset):
    chr_data,acs,_=fixture();struct.pack_into('<I',acs,296,offset)
    with pytest.raises(ValueError,match='inline CHR vertex'):V.decode_grids(acs,chr_data)


@pytest.mark.parametrize('shape',[(1,2,3),(2,3,3),(1,3,2)])
def test_grid_pose_requires_exact_dimensions(shape):
    chr_data,acs,_=fixture()
    with pytest.raises(ValueError,match='invalid dimensions'):
        V.bake_world_grids(chr_data,acs,np.eye(4)[None].repeat(17,0),{32:np.zeros(shape)},pose_evidence='test')


def test_actor_root_uses_explicit_base_and_provenance():
    chr_data,acs,_=fixture(parent=15,draw=1)
    world=np.eye(4)[None].repeat(17,0);positions=np.zeros((1,3,3))
    with pytest.raises(ValueError,match='actor base_world'):
        V.bake_world_grids(chr_data,acs,world,{32:positions},pose_evidence='test')
    base=np.eye(4);base[1,3]=2
    result=V.bake_world_grids(chr_data,acs,world,{32:positions},pose_evidence='test',
                              base_world=base,base_evidence='explicit synthetic frame')
    assert len(result['instances'])==1
    np.testing.assert_array_equal(result['instances'][0]['world'],base)


def test_skip_row_and_missing_pose_or_nonfinite_controls_fail_closed():
    chr_data,acs,_=fixture();struct.pack_into('<I',acs,296,0xffffffff)
    # The next map word is even; no continuation aliases remain for skipped row.
    grids=V.decode_grids(acs,chr_data);assert grids[0]['mappings'][0][0]==[]
    with pytest.raises(ValueError,match='lacks native world rows'):
        V.bake_world_grids(chr_data,acs,np.eye(4)[None].repeat(17,0),{},pose_evidence='test')
    struct.pack_into('<f',acs,40,float('nan'))
    with pytest.raises(ValueError,match='invalid'):V.decode_grids(acs,chr_data)


def test_grid_alias_cannot_end_with_skipped_vertex():
    chr_data,acs,_=fixture();struct.pack_into('<I',acs,300,0xffffffff)
    with pytest.raises(ValueError,match='alias cannot end'):V.decode_grids(acs,chr_data)
