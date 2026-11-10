import struct
from pathlib import Path

import pytest

from gbox.fzgx_gma import FzgxFormatError
from gbox.fzgx_skl import parse_skl

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz")


def _bone(link, flags, name):
    n = name.encode() + b"\0"
    n += b"\0" * (-len(n) % 4)
    return struct.pack(">hH11f", link, flags, *range(11)) + n


def test_synthetic_padding():
    blob = struct.pack(">HH", 2, 0) + _bone(-1, 64, "root") + _bone(0, 2, "k_waki_l")
    b = parse_skl(blob)
    assert [(x.name, x.link) for x in b] == [("root", -1), ("k_waki_l", 0)]
    assert b[1].values[3] == 3.0


def test_empty_and_trailing():
    assert parse_skl(b"\0\0\0\0") == []
    with pytest.raises(FzgxFormatError):
        parse_skl(struct.pack(">HH", 1, 0) + _bone(-1, 0, "a") + b"\0\0\0\0")
    with pytest.raises(FzgxFormatError):
        parse_skl(struct.pack(">HH", 2, 0) + _bone(-1, 0, "a"))


@pytest.mark.skipif(not GCZ.exists(), reason="owned F-Zero GX GCZ not mounted")
def test_owned_skl_all():
    from gbox.gcdisc import GCDisc
    d = GCDisc(str(GCZ))
    a = parse_skl(d.read("motion/arrow.skl"))
    assert len(a) == 28 and a[0].name == "c_hara" and a[0].link == -1
    assert a[7].name == "c_kata_l" and a[7].link == 6
    names = [k for k in d.files if k.endswith(".skl")]
    assert len(names) == 306
    for n in names:
        for i, bn in enumerate(parse_skl(d.read(n))):
            assert -1 <= bn.link < i, (n, i)
