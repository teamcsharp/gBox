import struct

import pytest

from gbox import doa2_morphs as M


def apv():
    data=bytearray(struct.pack('<I9i',9,40,-1,-1,-1,-1,-1,-1,-1,-1))
    # One source-key frame and one original-vertex pointer followed by -1.
    data.extend(struct.pack('<4I',1,16,24,36))
    data.extend(struct.pack('<2I',128,0xffffffff))
    data.extend(struct.pack('<6f',1,2,3,4,5,6))
    return bytes(data)


def sup():
    data=bytearray(struct.pack('<2I',8,0))
    data.extend(struct.pack('<IBBBB',16,1,0,3,0))
    data.extend(bytes(160))
    return bytes(data)


def test_apv_disable_preserves_all_payload_and_file_size():
    before=apv()
    after,report=M.disable_apv(before)
    assert len(before)==len(after)
    assert after[:4]==before[:4] and after[40:]==before[40:]
    assert M.inspect_apv(after)['enabled_sections']==[]
    assert report['before']['enabled_sections']==[0]
    assert report['original_sha256']!=report['patched_sha256']
    assert M.disable_apv(after)[0]==after


def test_sup_disable_creates_empty_directory_preserving_original_body():
    before=sup()
    after,report=M.disable_sup(before)
    assert len(before)==len(after) and after[4:]==before[4:]
    assert M.inspect_sup(after)['seam_count']==0
    assert report['before']['seams'][0]['bone_a']==1
    assert report['before']['seams'][0]['bone_b']==0
    assert report['before']['seams'][0]['model_id']==3
    assert M.disable_sup(after)[0]==after


@pytest.mark.parametrize('bad', [b'',struct.pack('<I',9),struct.pack('<I9i',8,*([-1]*9)),struct.pack('<I9i',9,12,*([-1]*8))])
def test_malformed_apv_is_rejected(bad):
    with pytest.raises(ValueError):M.disable_apv(bad)


def test_apv_rejects_missing_vertex_list_terminator_and_out_of_bounds_pointer():
    bad=bytearray(apv());struct.pack_into('<I',bad,60,12)
    with pytest.raises(ValueError,match='terminator'):M.disable_apv(bytes(bad))
    bad=bytearray(apv());struct.pack_into('<I',bad,48,10000)
    with pytest.raises(ValueError,match='exceeds'):M.disable_apv(bytes(bad))


@pytest.mark.parametrize('bad',[b'',struct.pack('<I',20),struct.pack('<2I',8,7),struct.pack('<3I',12,8,0)])
def test_malformed_sup_is_rejected(bad):
    with pytest.raises(ValueError):M.disable_sup(bad)


def test_sup_rejects_unsupported_joint_and_bad_data_pointer():
    bad=bytearray(sup());bad[12]=44
    with pytest.raises(ValueError,match='joint'):M.disable_sup(bytes(bad))
    bad=bytearray(sup());struct.pack_into('<I',bad,8,20)
    with pytest.raises(ValueError,match='pointer'):M.disable_sup(bytes(bad))


def test_original_seven_section_empty_boss_apv_and_extended_wing_seams():
    absent=struct.pack('<I7i',7,*([-1]*7))
    assert M.disable_apv(absent)[0]==absent
    assert M.inspect_apv(absent)['enabled_sections']==[]
    extended=bytearray(sup());extended[12]=18;extended[13]=17
    result,report=M.disable_sup(bytes(extended))
    assert report['before']['seams'][0]['bone_a']==18
    assert report['before']['seams'][0]['bone_b']==17
    assert M.inspect_sup(result)['seam_count']==0
