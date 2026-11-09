import struct

import pytest

from gbox import mtf_motion, mtf_motion_edit


def fixture(shared=False):
    data = bytearray(280)
    struct.pack_into('<4sHHQ',data,0,b'LMT\0',67,1,16)
    struct.pack_into('<QIIi',data,16,112,2,5,0)
    for index,bone in enumerate((0,255)):
        bounds = 208 if shared else 208+index*32
        struct.pack_into('<4BfQQ4fQ',data,112+index*48,5,1,0,bone,1.,4,272+index*4,
                         3.,100.+index,7.,1.,bounds)
        struct.pack_into('<8f',data,208+index*32,2.,20.,3.,0.,1.,90.,4.,1.)
        struct.pack_into('<4B',data,272+index*4,20,127,40,1)
    return bytes(data)


def test_scale_only_root_y_references_and_quantized_bounds_not_key_bits_or_virtual_root():
    source = fixture()
    edited,receipt = mtf_motion_edit.scale_root_y(source,.5)
    _,_,before = mtf_motion._clip(source,16)
    _,_,after = mtf_motion._clip(edited,16)
    assert after[0].reference == pytest.approx((3.,50.,7.,1.))
    assert after[0].values[0] == pytest.approx(tuple(v*.5 if i==1 else v for i,v in enumerate(before[0].values[0])))
    assert after[1] == before[1]
    assert edited[272:] == source[272:]
    changed = {i for i,(a,b) in enumerate(zip(source,edited)) if a!=b}
    assert changed <= {i for word in (140,212,228) for i in range(word,word+4)}
    assert receipt['tracks']==1 and receipt['vertical_gait_scaled'] and receipt['virtual_root255_unchanged']


def test_root_height_writer_rejects_shared_bounds_and_unsupported_layouts():
    with pytest.raises(ValueError,match='shared'):
        mtf_motion_edit.scale_root_y(fixture(shared=True),.5)
    data=bytearray(fixture());data[112]=3
    with pytest.raises(ValueError,match='quantized'):
        mtf_motion_edit.scale_root_y(data,.5)
    for scale in (0,-1,float('inf'),True):
        with pytest.raises(ValueError,match='positive'):
            mtf_motion_edit.scale_root_y(fixture(),scale)


def test_reference_only_root_is_scaled_without_rewriting_other_fields():
    data=bytearray(fixture())
    data[112]=1
    struct.pack_into('<QQ',data,120,0,0)
    struct.pack_into('<Q',data,152,0)
    edited,receipt=mtf_motion_edit.scale_root_y(data,.25)
    assert struct.unpack_from('<f',edited,140)[0]==25.
    assert receipt['float_fields']==1
    assert edited[:140]==data[:140] and edited[144:]==data[144:]
