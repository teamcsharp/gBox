import struct
import os
from pathlib import Path

import numpy as np
import pytest

from gbox import doa2_components as C


def owned_fixture(name):
    configured=os.environ.get('GBOX_DOA2_FIXTURES')
    root=Path(configured) if configured else Path('gbox-data/doa2-re')
    candidates=[root/name,root/'geometry'/name,root/'rig'/name,root/'animation'/name]
    path=next((p for p in candidates if p.is_file()),None)
    if path is None: pytest.skip('Owned fixture absent: '+name+'; set GBOX_DOA2_FIXTURES')
    return path


def synthetic_wings():
    data=bytearray(256)
    struct.pack_into('<4I',data,0,5,32,255,0)
    struct.pack_into('<7I',data,32,2,64,82,94,106,120,132)
    struct.pack_into('<9h',data,64,0,0,0,0,0,0,0,0,0)
    struct.pack_into('<6H',data,120,1,2,3,4,5,6)
    struct.pack_into('<9f',data,132,1,2,3,0,0,4,0,0,5)
    return data


def test_actual_tengu_initial_native_six_joints():
    path=owned_fixture('TNG_A00.ACS')
    result=C.wing_attachments(path.read_bytes(),np.eye(4),model_count=90)
    assert result['models']=={14:17,15:18,16:19,32:20,33:21,34:22}
    assert result['parent']=={17:0,18:17,19:18,20:0,21:20,22:21}
    for world in result['world'].values():
        np.testing.assert_allclose(world[:3,:3].T@world[:3,:3],np.eye(3),atol=1e-12)
        assert np.linalg.det(world[:3,:3])==pytest.approx(1)
    mirror=np.diag([-1,1,1,1])
    for left,right in zip(range(17,20),range(20,23)):
        np.testing.assert_allclose(result['world'][right],mirror@result['world'][left]@mirror,atol=1e-12)


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


def test_actual_native_eye_vectors_are_relative_to_head():
    exe=owned_fixture('1ST_READ.BIN').read_bytes()
    head=np.eye(4);head[:3,3]=[0,.6,0]
    result=C.eye_attachments(exe,5,head)
    assert result['parent']=={15:1,16:1}
    np.testing.assert_allclose(result['world'][15][:3,3],[.03,.749,.0683],atol=1e-7)
    np.testing.assert_allclose(result['world'][16][:3,3],[-.03,.749,.0683],atol=1e-7)


def test_native_eye_inherits_head_basis_and_gaze_order():
    exe=owned_fixture('1ST_READ.BIN').read_bytes()
    head=C._rotation(2,16384)
    eye=C.eye_attachments(exe,5,head,gaze_angles=[[16384,0],[0,16384]])
    np.testing.assert_allclose(eye['world'][15][:3,2],[0,1,0],atol=1e-12)
    np.testing.assert_allclose(eye['world'][16][:3,2],[1,0,0],atol=1e-12)


def test_unverified_executable_cannot_create_eye_attachment():
    with pytest.raises(ValueError,match='verified'):
        C.eye_attachments(b'bad executable',5,np.eye(4))
