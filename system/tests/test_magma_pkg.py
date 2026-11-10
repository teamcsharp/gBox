import struct
from gbox.formats import magma_pkg as mp


def _pkg(names):
    nt = b"".join(bytes([len(n)]) + n.encode() + b"\0" + struct.pack(">I", 7) for n in names)
    hdr = mp.TAG + struct.pack(">HHIIIIIIII", 127, 100, 0x70013, 1, len(names), 40, 0, 0, 0, 0)
    return hdr + nt


def test_iter_and_names():
    stream = b"junk\0../System/Foo.ugx\0" + _pkg(["None", "Mesh", "Sam"]) + b"tail"
    hs = list(mp.iter_packages(stream))
    assert len(hs) == 1
    assert hs[0].path == "../System/Foo.ugx"
    assert mp.read_names(stream, hs[0]) == ["None", "Mesh", "Sam"]


def test_bad_tag():
    import pytest
    with pytest.raises(ValueError):
        mp.parse_header(b"\0" * 64, 0)
