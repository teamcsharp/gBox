import struct

import numpy as np
import pytest

from gbox import doa2_geometry as G
from .. import acs_chain_vertices as V


def fixture(marker=0xffff):
    header = bytearray(80)
    struct.pack_into('<4I', header, 0, 0x8000002c, 0x83000000, 0x20282452, 0x08000000)
    struct.pack_into('<2i', header, 32, 0, 1)
    mesh = {'header': bytes(header),
            'vertices': [(0, 0, 0, 0, 0, 1, .1, .2), (1, 0, 0, 0, 0, 1, .3, .4), (0, 1, 0, 0, 0, 1, .5, .6)],
            'triangles': [(0, 1, 2)]}
    model = G.encode_model({'global_flags': (1, 1)}, [mesh], references=False)
    chr_data = bytearray(24) + model + bytes(8)
    table = len(chr_data)
    chr_data.extend(struct.pack('<I', 0x0c300000))
    texture_table = len(chr_data)
    chr_data.extend(struct.pack('<3I', 32 | (32 << 16), 0x101, 0x0d200000))
    struct.pack_into('<6I', chr_data, 0, 24, table, texture_table, 1, 1, 0)
    archive = G.decode_chr(chr_data)
    records = archive['models'][0]['meshes'][0]['records']
    relative = [r['offset'] - 24 for r in records]
    acs = bytearray(244)
    struct.pack_into('<4I', acs, 0, 1, 32, 255, 0)
    struct.pack_into('<4B', acs, 32, 1, 1, 0, 1)
    struct.pack_into('<3f', acs, 32 + 0x14, 10, 20, 30)
    struct.pack_into('<4I', acs, 32 + 0x44, 128, 144, 192, 208)
    struct.pack_into('<2H', acs, 128, marker, 0)
    struct.pack_into('<12f', acs, 144, 1, 0, 0, 0, 1, 0, 0, 0, 1, 999, 0, 0)
    struct.pack_into('<3I', acs, 192, *relative)
    struct.pack_into('<3If', acs, 208, 8, relative[0], 0x3f000000, 0)
    struct.pack_into('<4I', acs, 220, 40, relative[1], 0x3e800000, 0xffffffff)
    return bytes(chr_data), acs, relative


def bake(chr_data, acs):
    return V.bake_chain_positions(chr_data, acs, np.repeat(np.eye(4)[None], 17, axis=0),
                                  {32: [[0, -1, 0]]}, pose_evidence='synthetic observed unit chain')


def test_native_positions_and_bounding_spheres_preserve_unselected_bytes():
    chr_data, acs, relative = fixture()
    original_acs = bytes(acs)
    result = bake(chr_data, acs)
    changed = result['chr_data']
    np.testing.assert_allclose(struct.unpack_from('<3f', changed, 24 + relative[0]), [1, -1, 0], atol=1e-6)
    assert changed[24 + 8:24 + 20] == changed[24 + relative[0]:24 + relative[0] + 12]
    assert struct.unpack_from('<f', changed, 24 + 20)[0] == .5
    assert changed[24 + 40:24 + 52] == changed[24 + relative[1]:24 + relative[1] + 12]
    assert struct.unpack_from('<f', changed, 24 + 52)[0] == .25
    permitted = {i for offset in relative for i in range(24 + offset, 24 + offset + 12)}
    permitted.update(range(32, 48)); permitted.update(range(64, 80))
    assert all(a == b or i in permitted for i, (a, b) in enumerate(zip(chr_data, changed)))
    assert len(changed) == len(chr_data) and bytes(acs) == original_acs
    assert G.roundtrip_chr(G.decode_chr(changed)) == changed
    assert result['report']['native_chain_deformations'][0]['bounding_centres_updated'] == 2


def test_marker_fffe_applies_native_anchor_to_deformed_positions():
    chr_data, acs, relative = fixture(0xfffe)
    result = bake(chr_data, acs)
    np.testing.assert_allclose(struct.unpack_from('<3f', result['chr_data'], 24 + relative[0]), [11, 19, 30], atol=1e-6)
    assert result['models']=={} and result['instances']==[]


@pytest.mark.parametrize('destination', [0, 4, 12, 24, 32, 44, 80, 0xfffffff0])
def test_alias_cannot_overwrite_header_commands_or_radius_as_position(destination):
    chr_data, acs, _ = fixture()
    struct.pack_into('<I', acs, 208, destination)
    with pytest.raises(ValueError, match='verified vertex or bounding'):
        bake(chr_data, acs)


def test_bad_source_or_missing_pose_rejected_before_writing():
    chr_data, acs, _ = fixture()
    struct.pack_into('<I', acs, 212, 8)
    with pytest.raises(ValueError, match='verified vertex or bounding'):
        V.decode_chains(acs, chr_data)
    chr_data, acs, _ = fixture()
    with pytest.raises(ValueError, match='lacks observed'):
        V.bake_chain_positions(chr_data, acs, np.repeat(np.eye(4)[None], 17, axis=0), {}, pose_evidence='test')
    with pytest.raises(ValueError, match='provenance'):
        V.bake_chain_positions(chr_data, acs, np.repeat(np.eye(4)[None], 17, axis=0), {32: [[0, -1, 0]]}, pose_evidence='')


def test_nonfinite_payload_and_alias_without_terminator_fail():
    chr_data, acs, _ = fixture()
    struct.pack_into('<f', acs, 144, float('nan'))
    with pytest.raises(ValueError, match='non-finite'):
        V.decode_chains(acs, chr_data)
    chr_data, acs, _ = fixture()
    with pytest.raises(ValueError, match='bounds'):
        V.decode_chains(acs[:232], chr_data)


def test_native_shared_model_draws_have_separate_snapshot_and_anchor():
    chr_data, acs, relative = fixture()
    acs.extend(bytes(120))
    acs[244:340]=acs[32:128]
    struct.pack_into('<3f',acs,244+0x14,-10,20,30)
    struct.pack_into('<6I',acs,0,1,32,1,244,255,0)
    result=V.bake_chain_positions(chr_data,acs,np.repeat(np.eye(4)[None],17,axis=0),
                                 {32:[[0,-1,0]],244:[[0,-1,1]]},pose_evidence='native simultaneous descriptor fixture')
    assert len(result['instances'])==2 and result['models']=={}
    assert result['report']['shared_models']==[0]
    np.testing.assert_allclose(result['instances'][0]['world'][:3,3],[10,20,30])
    np.testing.assert_allclose(result['instances'][1]['world'][:3,3],[-10,20,30])
    first,second=[r['chr_data'] for r in result['instances']]
    assert first!=second and second==result['chr_data']
    np.testing.assert_allclose(struct.unpack_from('<3f',first,24+relative[0]),[1,-1,0],atol=1e-6)


def test_zero_link_deferred_root_alias_has_no_phantom_actor_transform():
    chr_data,acs,_=fixture(0xfffe)
    struct.pack_into('<2B',acs,32,0,15)
    result=V.bake_chain_positions(chr_data,acs,np.repeat(np.eye(4)[None],17,axis=0),{},pose_evidence='native zero-link directory')
    assert result['models']=={} and result['instances']==[]
    assert result['report']['written_positions']==2


def test_drawn_root_attachment_requires_base_transform_and_provenance():
    chr_data,acs,_=fixture()
    struct.pack_into('<B',acs,33,15)
    pose=np.repeat(np.eye(4)[None],17,axis=0)
    with pytest.raises(ValueError,match='base_world'):
        V.bake_chain_positions(chr_data,acs,pose,{32:[[0,-1,0]]},pose_evidence='fixture')
    with pytest.raises(ValueError,match='provenance'):
        V.bake_chain_positions(chr_data,acs,pose,{32:[[0,-1,0]]},pose_evidence='fixture',base_world=np.eye(4))
    result=V.bake_chain_positions(chr_data,acs,pose,{32:[[0,-1,0]]},pose_evidence='fixture',
                                 base_world=np.eye(4),base_evidence='explicit observed actor frame')
    assert len(result['instances'])==1
