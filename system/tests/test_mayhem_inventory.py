"""WCW Mayhem (Europe) N64 inventory (#1512): RefPack codec, BIGF walker, KCHR roster, owned-ROM pins."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import mayhem_inventory as M
from gbox import refpack

SOURCE_SHA256 = "f89bb1e5b450b2aa88464367c320a9d57f308f0899c391e8f50ba765b9bcfaa5"
Z64_SHA256 = "d8c97d05f5050636a5756ddac73d1983ab636544f996a6a5d3dd5d15a14339b2"


def _src():
    p = os.environ.get("GBOX_MAYHEM_EU_SOURCE") or str(Path.home() / "gbox-cache" / M.GAME_ID / "source.zip")
    return Path(p) if Path(p).is_file() else None


def test_refpack_backrefs_and_literals():
    # 10FB, size 10; literal block "abcd" (0xE0), then 2-byte cmd lit=2 "ef" len=3 off=6 -> "abc"; then 0xFD + "z".
    stream = bytes([0x10, 0xFB, 0, 0, 10, 0xE0]) + b"abcd" + bytes([0x02, 0x05]) + b"ef" + bytes([0xFD]) + b"z"
    assert refpack.decompress(stream) == b"abcdefabcz"
    # 3-byte form: lit=1 ("q") then len=4 off=1 (overlapping run-length copy), then stop 0xFC
    s3 = bytes([0x10, 0xFB, 0, 0, 5, 0x80, 0x40, 0x00]) + b"q" + bytes([0xFC])
    assert refpack.decompress(s3) == b"qqqqq"


def test_refpack_literal_roundtrip_and_errors():
    for n in (0, 1, 3, 4, 111, 112, 113, 5000):
        data = bytes((i * 7) & 0xFF for i in range(n))
        assert refpack.decompress(refpack.compress_literal(data)) == data
    with pytest.raises(ValueError):
        refpack.decompress(bytes([0x10, 0xFB, 0, 0, 9, 0xFC]))          # size mismatch
    with pytest.raises(ValueError):
        refpack.decompress(bytes([0x10, 0xFB, 0, 0, 3, 0x00, 0x05]))    # back-ref before start
    assert not refpack.is_refpack(b"BIGF\0\0\0\0")


def _bigf(members):
    hdr = sum(8 + len(n) + 1 for n, _ in members) + 16
    hdr = (hdr + 7) & ~7
    body, dirs, off = b"", b"", hdr
    for n, d in members:
        dirs += struct.pack(">II", off, len(d)) + n.encode() + b"\0"
        body += d; off += len(d)
    return b"BIGF" + struct.pack(">III", off, len(members), hdr) + dirs.ljust(hdr - 16, b"\0") + body


def test_bigf_nested_walk_and_roster():
    nch = bytearray(b"KCHR" + struct.pack(">II", 0x10, 4) + bytes(4) + b"\x01X\0\x05" * 9 + bytes(3))
    people = [("STING", "STING"), ("RIC FLAIR", "NATURE BOY")] + [(f"W{i}", f"R{i}") for i in range(8)]
    for full, ring in people:
        nch += full.encode() + b"\0" + ring.encode() + b"\0Default\0" + bytes([7]) * 56
    inner = _bigf([("wrestler.nch", refpack.compress_literal(bytes(nch))), ("ST_n64.n3o", refpack.compress_literal(b"x" * 9))])
    rom = bytes(64) + _bigf([("data.big", inner), ("game.ovr", b"raw!")])
    rows = M.walk(rom, 64)
    assert [(r["archive"], r["name"], r["refpack"]) for r in rows] == [
        ("data.big", "wrestler.nch", True), ("data.big", "ST_n64.n3o", True), ("data.big", "game.ovr", False)]
    assert rows[1]["unpacked"] == 9 and rows[1]["slack"] == 0
    names = M.roster(M.member(rom, rows, "wrestler.nch"))
    assert len(names) == 10 and [(n["name"], n["ring_name"], n["costume"]) for n in names[:2]] == [
        ("STING", "STING", "Default"), ("RIC FLAIR", "NATURE BOY", "Default")]


def test_owned_europe_rom_inventory():
    src = _src()
    if src is None:
        pytest.skip("owned WCW Mayhem (Europe) zip not cached")
    if hashlib.sha256(src.read_bytes()).hexdigest() != SOURCE_SHA256:
        pytest.skip("different source build")
    from gbox import n64_rom
    rom = n64_rom.read(src)
    assert hashlib.sha256(rom).hexdigest() == Z64_SHA256
    m = M.inventory(rom, src)
    assert m["header"]["code"] == "NWMP" and m["header"]["region"] == "Europe"
    assert m["source"]["members"][0]["byte_order"].startswith("v64")
    assert m["layout"]["master_members"] == 34 and len(m["layout"]["nested_archives"]) == 16
    assert m["refpack"] == {"members": 2026, "exact": 2026, "raw_members": 591}
    assert m["roster"]["count"] == 56 and m["roster"]["kchr_stride"] == 0x1FC
    names = [w["name"] for w in m["roster"]["wrestlers"]]
    assert names[0] == '"MEAN" GENE OKERLUND' and names[-1] == "WRATH" and "GOLDBERG" in names and "STING" in names
    assert m["models"]["count"] == 176 and m["animations"]["count"] == 573
    assert {"ST", "GO", "WS"} <= set(m["models"]["wrestler_codes"])


def test_truncated_inputs_raise_valueerror():
    good = refpack.compress_literal(b"hello world, refpack")
    for n in range(len(good)):
        with pytest.raises(ValueError):
            refpack.decompress(good[:n])
    two = bytes([0x10, 0xFB, 0, 0, 10, 0xE0]) + b"abcd" + bytes([0x02, 0x05]) + b"ef" + bytes([0xFD]) + b"z"
    for n in range(len(two)):
        with pytest.raises(ValueError):
            refpack.decompress(two[:n])
    arc = _bigf([("a.bin", b"1234"), ("b.bin", b"56")])
    for n in range(len(arc)):
        with pytest.raises(ValueError):
            M.parse_bigf(arc[:n])
    for n in range(12):
        with pytest.raises(ValueError):
            M.roster(b"KCHR" + bytes(8)[:max(0, n - 4)])
