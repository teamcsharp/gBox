import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gbox import nba_street_vol_2 as N  # noqa: E402


def make_elf(names):
    strtab = b"\0"
    offs = []
    for n in names:
        offs.append(len(strtab))
        strtab += n.encode() + b"\0"
    sym = b"\0" * 16 + b"".join(struct.pack("<IIIBBH", o, 0, 4, 0, 0, 1) for o in offs)
    data = b"__geoprimdata_0_" * 2
    body = data + strtab + sym
    shoff = 0x34 + len(body)
    hdr = b"\x7fELF\x01\x01\x01" + b"\0" * 9 + struct.pack(
        "<HHIIIIIHHHHHH", 1, 20, 1, 0, 0, shoff, 0, 0x34, 0, 0, 40, 4, 0)
    d0 = 0x34
    s0 = d0 + len(data)
    y0 = s0 + len(strtab)
    secs = [(0,) * 10, (0, 1, 3, 0, d0, len(data), 0, 0, 1, 0), (0, 3, 0, 0, s0, len(strtab), 0, 0, 1, 0),
            (0, 2, 0, 0, y0, len(sym), 2, 1, 4, 16)]
    return hdr + body + b"".join(struct.pack("<10I", *s) for s in secs)


def make_big(members):
    hdr_len = 16 + 9 * len(members)
    off = (hdr_len + 15) // 16 * 16
    ents = b""
    blob = b""
    for m in members:
        ents += struct.pack(">II", off + len(blob), len(m)) + b"\0"
        blob += m
    head = b"BIGF" + struct.pack(">III", off + len(blob), len(members), hdr_len)
    return head + ents + b"\0" * (off - hdr_len) + blob


def test_synthetic_archive_player_detection():
    parts = ["__EAGL::TAR:::tar_%s_%d" % (p, i) for i, p in enumerate(["head", "legs", "hand"])]
    player = make_elf(parts + ["__Model:::blit", "__BBOX:::blit"])
    other = make_elf(["__Model:::ball"])
    big = make_big([player, other, b"SHPGxxxx"])
    mem = N.parse_bigf(lambda o, s: big[o:o + s], 0, len(big))
    assert len(mem) == 3 and all(m["ok"] for m in mem)
    c = N.census((i, big[m["off"]:m["off"] + m["size"]]) for i, m in enumerate(mem))
    assert c == {"elf_members": 2, "model_symbols": 2, "player_like_objects": 1}
    d = N.describe_object(player)
    assert d["models"] == ["blit"] and d["geoprim"] == 2 and d["player_like"]


def test_truncated_elf_is_not_counted():
    assert N.elf_symbols(make_elf(["a"])[:60]) == []


ROM = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/NBA Street Vol. 2 (USA).gcz"


@pytest.mark.skipif(not os.path.exists(ROM), reason="owned disc not mounted")
def test_owned_build_blit_slot():
    from gbox.gcz import GCZ
    b = GCZ(ROM).read(1037182076, 197952)  # xf/xf000002 member 729, absolute disc offset
    assert hashlib.sha256(b).hexdigest() == "9f431529245dc0216fe79def25f7853066e655479bc05109466f0beaa10d0d06"
    d = N.describe_object(b)
    assert d["models"] == ["blit"] and d["player_like"] and d["geoprim"] == 61
