import struct
import numpy as np
import pytest
from .. import actor_attachment_frame as A


def fixture():
    data=bytearray(96)
    struct.pack_into('<4I',data,0,4,32,255,0)
    struct.pack_into('<2BH',data,32,11,0,38)
    struct.pack_into('<3f',data,36,1,2,3)
    struct.pack_into('<3h',data,48,16384,0,0)
    world=np.eye(4)[None].repeat(17,0);world[11,:3,3]=[4,5,6]
    return data,world


def test_authored_controller_rotation_and_translation_are_under_joint11():
    data,world=fixture();frame=A.source_controller_frame(data,world,38)
    expected=np.eye(4);expected[:3,:3]=[[1,0,0],[0,0,-1],[0,1,0]];expected[:3,3]=[5,7,9]
    np.testing.assert_allclose(frame['world'],expected,atol=1e-12)
    assert frame['parent']==11 and frame['model']==38 and frame['scale']==1


def test_controller_does_not_guess_actor_root_or_missing_model():
    data,world=fixture();data[32]=15
    with pytest.raises(ValueError,match='verified core parent'):A.source_controller_frame(data,world,38)
    data,world=fixture()
    with pytest.raises(ValueError,match='exactly one'):A.source_controller_frame(data,world,0)


def test_controller_rejects_duplicate_mapping_and_nonfinite_anchor():
    data,world=fixture();data.extend(bytes(32));data[64:112]=data[32:80]
    struct.pack_into('<4I',data,8,4,64,255,0)
    with pytest.raises(ValueError,match='exactly one'):A.source_controller_frame(data,world,38)
    data,world=fixture();struct.pack_into('<f',data,36,float('nan'))
    with pytest.raises(ValueError,match='non-finite'):A.source_controller_frame(data,world,38)


def test_native_controller_unrelated_source_bytes_are_unchanged():
    data,world=fixture();data[90:96]=b'proof!';original=bytes(data);world_copy=world.copy()
    A.source_controller_frame(data,world,38)
    assert bytes(data)==original
    np.testing.assert_array_equal(world,world_copy)
