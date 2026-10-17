from types import SimpleNamespace
import pytest
from gbox import sm64_startup as S,n64_rom


def rom():
    data=bytearray(S.START+len(S.SIGNATURE)+16)
    data[:4]=bytes.fromhex('80371240');data[0x3b:0x3f]=b'NSMP'
    data[S.START:S.START+len(S.SIGNATURE)]=S.SIGNATURE
    return bytes(data)


def test_startup_changes_only_the_auto_options_flag_and_is_idempotent():
    original=rom();out,report=S.apply(original)
    assert [i for i,(a,b) in enumerate(zip(original,out)) if a!=b]==[S.PATCH+1]
    assert out[S.PATCH:S.PATCH+4]==bytes.fromhex('a2200000')
    assert report['saves_changed'] is False
    assert S.apply(out)[0]==out
    unknown=bytearray(original);unknown[S.START]^=1
    with pytest.raises(ValueError,match='fingerprint'):S.apply(bytes(unknown))
    unknown[0x3e]=ord('E');assert S.apply(bytes(unknown))[0]==bytes(unknown)


def test_launch_patch_uses_copy_with_same_save_basename(tmp_path,monkeypatch):
    original=rom();src=tmp_path/'My current Mario build.zip';src.write_bytes(b'owned archive remains untouched')
    monkeypatch.setattr(n64_rom,'read',lambda p:original)
    dest,report=S.prepare_launch(src,SimpleNamespace(cache=tmp_path/'cache'))
    assert dest.name=='My current Mario build.z64' and dest.read_bytes()==S.apply(original)[0]
    assert src.read_bytes()==b'owned archive remains untouched'
    assert S.prepare_launch(src,SimpleNamespace(cache=tmp_path/'cache'))[0]==dest
