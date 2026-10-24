import hashlib
import os
import struct

import pytest

from gbox.deadaim_fpk import parse_fpk, character_skeletons


def _fpk(name: bytes, files, base=0xC0):
    recs = b""
    payload = b""
    for ext, data in files:
        recs += struct.pack("<III4s", 0, len(payload), len(data), ext.ljust(4, b"\0"))
        payload += data
    head = bytearray(base)
    head[0:4] = b"fpk\0"
    struct.pack_into("<I", head, 0x28, base)
    struct.pack_into("<I", head, 0x2C, len(payload))
    head[0x40:0x40 + len(name)] = name
    head[0x80:0x80 + len(recs)] = recs
    return bytes(head) + payload


def test_nested_fpk_and_skeleton():
    inner = _fpk(b"mmodel.bin", [(b"fjc", b"CJFgPC01A\0" + b"x" * 20), (b"nib", b"zz")])
    outer = _fpk(b"pc01a.zone.bin", [(b"tsl", b"names"), (b"mmo", inner)])
    rd = lambda o, n: outer[o:o + n].ljust(n, b"\0")
    ents = parse_fpk(rd, 0)
    assert [e["ext"] for e in ents] == ["tsl", "mmo", "fjc", "nib"]
    sk = character_skeletons(rd, ents)
    assert len(sk) == 1 and sk[0]["name"] == "PC01A"


IMAGE = os.environ.get("DEADAIM_IMAGE_BIN", "")
IMAGE_SHA = "d2c2aa5cd11bb7036faf9e4a0bedf471a9e2651c8fa90d39b4cb355f99c21ba6"


@pytest.mark.skipif(not os.path.exists(IMAGE), reason="owned IMAGE.BIN not available")
def test_owned_image_bin_inventory():
    h = hashlib.sha256()
    with open(IMAGE, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    assert h.hexdigest() == IMAGE_SHA
    f = open(IMAGE, "rb")

    def rd(o, n):
        f.seek(o)
        return f.read(n)

    ents = parse_fpk(rd, 0)
    assert len(ents) == 3739
    assert sorted(s["name"] for s in character_skeletons(rd, ents) if s["name"].startswith("PC")) == ["PC01A", "PC02A"]
