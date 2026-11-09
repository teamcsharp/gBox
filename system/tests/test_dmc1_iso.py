"""Focused tests for gbox.dmc1_iso (request #1856, Devil May Cry USA PS2).

Run: python -m pytest tests/test_dmc1_iso.py -q
Skips the big-image tests when the extracted raw image is absent; the header
parsing tests run on a synthetic ISO built in-process.
"""
import struct
from pathlib import Path

import pytest

from gbox.dmc1_iso import parse_pld_children, walk_dir, SECTOR

RAW = Path("/home/ehm_eckx/gBox_alt/gbox-cache/modbase/d460ea70167416a2/Devil May Cry (USA).iso")
RAW_SHA = "9e4d87fa0bae06e7282c085bb58693f83cf857bede9803f4bd235e3dfcfe0726"


def _rec(name: str, ext: int, size: int, dir_flag: bool) -> bytes:
    nb = name.encode("latin1") + b";1"
    ln = 33 + len(nb)
    if ln % 2:
        ln += 1
    r = bytearray(ln)
    r[0] = ln
    struct.pack_into("<I", r, 2, ext)
    struct.pack_into("<I", r, 10, size)
    r[25] = 2 if dir_flag else 0
    r[32] = len(nb)
    r[33:33 + len(nb)] = nb
    return bytes(r)


def test_walk_dir_synthetic(tmp_path):
    img = tmp_path / "t.bin"
    body = _rec(".", 261, 2048, True) + _rec("..", 261, 2048, True) + \
           _rec("PL00.PLD;1", 100, 4096, False) + _rec("SUB;1", 300, 512, True)
    img.write_bytes(b"\x00" * (261 * SECTOR) + body.ljust(SECTOR, b"\x00"))
    with open(img, "rb") as f:
        files = walk_dir(f, 261, len(body))
    names = {n: (s, dr, e) for n, s, dr, e in files}
    assert names["PL00.PLD"] == (4096, False, 100)
    assert names["SUB"] == (512, True, 300)
    assert "." not in names and ".." not in names


def test_parse_pld_children_synthetic(tmp_path):
    offs = [48, 1000, 2000]
    head = struct.pack("<I", len(offs)) + struct.pack(f"<{len(offs)}I", *offs)
    blob = head + b"\x00" * (3000 - len(head))
    p = tmp_path / "pl.bin"
    p.write_bytes(blob)
    with open(p, "rb") as f:
        n, ch = parse_pld_children(f, 0, len(blob))
    assert n == 3
    assert ch == [(48, 952), (1000, 1000), (2000, 1000)]


@pytest.mark.skipif(not RAW.exists(), reason="raw image not extracted")
def test_real_pl00_dante_header():
    with open(RAW, "rb") as f:
        n, ch = parse_pld_children(f, 1043291, 1547616)
    assert n == 11
    assert ch[0] == (48, 228144)
    assert ch[-1] == (1540960, 6656)
    assert sum(len for _, len in ch) <= 1547616


@pytest.mark.skipif(not RAW.exists(), reason="raw image not extracted")
def test_real_groups_present():
    with open(RAW, "rb") as f:
        emd = [x for x in walk_dir(f, 264, 3498) if not x[2]]
        pld = [x for x in walk_dir(f, 274, 1082) if not x[2]]
    assert len(emd) == 178
    assert len(pld) == 80
    assert any(n == "PL00.PLD" and s == 1547616 and e == 1043291 for n, s, _, e in pld)


def test_parse_child_table_synthetic():
    import struct
    from gbox.dmc1_iso import parse_child_table
    blob = struct.pack("<I3I", 3, 0, 16, 20) + b"\0" * 32
    assert parse_child_table(blob) == [0, 16, 20]


def test_parse_child_table_rejects_bad():
    import struct, pytest
    from gbox.dmc1_iso import parse_child_table
    with pytest.raises(ValueError):
        parse_child_table(struct.pack("<I", 99) + b"\0" * 8)


def _child6_blob(count, offsets):
    import struct
    return bytearray(struct.pack("<I", count) + struct.pack("<%dI" % count, *offsets)
        + b"\x00" * (0x1000 - 4 - 4 * count))


def test_parse_child6_table_synthetic():
    """Structural path only; tag bytes left zero since the bit-field
    classification is not yet pinned (no GIF-tag layout verified)."""
    import struct
    from gbox.dmc1_iso import parse_child6_table
    blob = bytearray(struct.pack("<I", 3) + struct.pack("<3I", 0, 0x100, 0x200)
        + b"\x00" * (0x1000 - 4 - 4 * 3))
    recs = parse_child6_table(blob)
    assert len(recs) == 3
    assert [r["off"] for r in recs] == [0, 0x100, 0x200]
    assert all(r["kind"] == "data" for r in recs)  # zero tag -> nreg 0


def test_parse_child6_table_rejects_bad_sort():
    import pytest
    from gbox.dmc1_iso import parse_child6_table
    # even offsets 0, 0x200, 0x100 -> not strictly increasing
    blob = _child6_blob(5, [0, 0x100, 0x200, 0x200, 0x100])
    with pytest.raises(ValueError):
        parse_child6_table(blob)


@pytest.mark.skipif(not RAW.exists(), reason="raw image not extracted")
def test_parse_child6_table_real():
    """Verified table invariants on the real owned image only.

    The kind/GIF-tag classification is NOT yet pinned (bit-field brute force
    on 2026-11-06 found no GS GIF-tag layout decoding the pinned headers),
    so these assertions stop at table structure + pinned header bytes.
    """
    import struct
    from gbox.dmc1_iso import parse_child6_table
    with open(RAW, "rb") as f:
        n, ch = parse_pld_children(f, 1043291, 1547616)
        assert ch[6][1] == 1042640
        f.seek((1043291 * 2048) + ch[6][0])
        blob = f.read(ch[6][1])
    assert struct.unpack_from("<I", blob, 0)[0] == 215
    offs = list(struct.unpack_from("<215I", blob, 4))
    recs = parse_child6_table(blob)
    assert len(recs) == 215
    assert [r["off"] for r in recs] == offs
    assert all(o < len(blob) for o in offs)
    evens, odds = offs[0::2], offs[1::2]
    assert len(evens) == 108 and evens == sorted(evens) and len(set(evens)) == 108
    assert len(odds) == 107 and len(set(odds)) == 51  # shared odd sections
    assert recs[0]["off"] == 0                        # entry 0 = table itself
    # Pinned header evidence (hex verified 2026-11-06):
    assert blob[0x6C0:0x6D4] == bytes.fromhex("3e001fff80" + "0102030405060708090a0b0c0d0e0f")
    assert blob[0x2888:0x28A0] == bytes.fromhex(
        "3e002222000000004000000080000000c000000000010000")


@pytest.mark.skipif(not RAW.exists(), reason="raw image not extracted")
def test_decode_child6_sections_real():
    """Structure-only summary on the real image; kind split is provisional."""
    from gbox.dmc1_iso import decode_child6_sections
    with open(RAW, "rb") as f:
        n, ch = parse_pld_children(f, 1043291, 1547616)
        f.seek((1043291 * 2048) + ch[6][0])
        blob = f.read(ch[6][1])
    s = decode_child6_sections(blob)
    assert s["count"] == 215
    off_set = {r["off"] for r in s["sections"]}
    assert 0x6C0 in off_set and 0x2888 in off_set
    assert s["unique_palettes"] <= 51  # every odd offset maps to <= 51 sections
    assert all(r["off"] < len(blob) for r in s["sections"])
