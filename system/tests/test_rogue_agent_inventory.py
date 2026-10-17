"""Focused tests for gbox.rogue_agent_inventory (GoldenEye - Rogue Agent GC inventory).

The BIGF directory parser and the .viv directory walk are tested against synthetic
archives built from the layout measured on the owned disc; a disc-backed test runs
only when the owned .gcz is mounted at its hyperspin path.
"""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import refpack  # noqa: E402
from gbox.rogue_agent_inventory import parse_bigf, viv_entries, viv_header  # noqa: E402

SRC = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/GoldenEye - Rogue Agent (USA) (Disc 1).gcz"


def _bigf(names, sizes, data_start=0x80, align=0x80):
    """A BIGF archive whose members are 0x80-aligned (as measured on the disc)."""
    count = len(names)
    off = data_start
    entries = []
    payload = bytearray()
    for name, size in zip(names, sizes):
        payload += b"\0" * (off - len(payload))
        off += size
        payload += b"\0" * size
        off = (off + align - 1) & ~(align - 1)
        entries.append((name, len(payload) - size, size))
    # rebuild the directory with the real offsets
    dirb = bytearray()
    total = len(payload)
    for (name, o, s) in entries:
        dirb += struct.pack(">II", o, s) + name.encode("latin-1") + b"\0"
    hdr = b"BIGF" + struct.pack("<I", total) + struct.pack(">II", count, 0x5C)
    return bytes(hdr + dirb) + bytes(payload)


def test_parse_bigf_unpadded_names():
    buf = _bigf(["pgArt0.apt", "pgArt0.const", "pgArt0.o", "pgArt0.gsh"],
                [0x2EB0, 0x0D1E, 0x6678, 0x3441D0])
    extra, members = parse_bigf(buf)
    assert extra == 0x5C
    assert [m[0] for m in members] == ["pgArt0.apt", "pgArt0.const", "pgArt0.o", "pgArt0.gsh"]
    # offsets must be 0x80-aligned and in range
    for name, off, size in members:
        assert off % 0x80 == 0
        assert off + size <= len(buf)


def test_parse_bigf_rejects_overrun():
    buf = b"BIGF" + struct.pack("<I", 32) + struct.pack(">II", 1, 0x10) + \
          struct.pack(">II", 0x80, 0x100) + b"a.bin\0" + b"\0" * 0x80
    with pytest.raises(ValueError):
        parse_bigf(buf)


def test_viv_header_and_entries():
    names = [("NXD_Vault_Bars_Small_Refl.mvd", 0x1A0000, 0x0A82),
             ("NXD_Vault_Bars_Small.mvd", 0x24C000, 0x0A82),
             ("M_PVLW_tailEnd.mvd", 0x2F8000, 0x0A82)]
    buf = VIV_MAGIC = b"\xC0\xFB"
    buf += struct.pack(">IHI", 0x0F020092, len(names), 0x40000A82)
    for n, o, s in names:
        buf += n.encode("latin-1") + b"\0" + struct.pack(">IH", o, s)
    hdr = viv_header(buf)
    assert hdr["magic"] == "c0fb"
    assert hdr["count_06"] == len(names)
    got = viv_entries(buf)
    assert [g[0] for g in got] == [n[0] for n in names]
    assert [(g[1], g[2]) for g in got] == [(n[1], n[2]) for n in names]


def test_viv_entries_stops_on_binary():
    buf = b"\xC0\xFB" + struct.pack(">IHI", 0, 1, 0) + b"a.mvd\0" + struct.pack(">IH", 0, 1)
    buf += b"\xFF\xFE\xFD\xFC"  # binary tail that is not a name
    got = viv_entries(buf)
    assert [g[0] for g in got] == ["a.mvd"]


def test_refpack_big_roundtrip():
    # a .big is a RefPack stream; compress_literal is the all-literal encoder
    data = b"GoldenEye Rogue Agent BIGF payload " * 100
    assert refpack.decompress(refpack.compress_literal(data)) == data


@pytest.mark.skipif(not Path(SRC).exists(), reason="owned .gcz not mounted")
def test_disc_inventory_smoke():
    import json
    from gbox.rogue_agent_inventory import inventory
    m = inventory(SRC)
    assert m["disc_game_id"] == "GOYE69"
    assert m["source"]["sha256"] == "bb739812f55c1c0baf86f7a9a5b86496a677873d92edf849af3688b4f3cc9432"
    assert m["layout"]["big_archives"] == 172
    assert m["layout"]["viv_archives"] == 45
    assert set(m["executables"]) == {"GE2RDVD.ELF", "LOADRDVD.ELF", "STUBRDVD.ELF"}
    # every .big member that overruns would have raised in parse_bigf, so 0 errors = all in range
    assert not any("error" in r for r in m["big_archives"])
    assert m["bigf"]["total_members"] >= 600
    json.dumps(m)  # manifest must be JSON-serialisable


@pytest.mark.parametrize("size", range(2, 12))
def test_viv_header_rejects_truncation(size):
    with pytest.raises(ValueError):
        viv_header((b"\xc0\xfb" + bytes(10))[:size])


def test_bigf_rejects_negative_base():
    with pytest.raises(ValueError):
        parse_bigf(_bigf(["a.bin"], [4]), -4)
