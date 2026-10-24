"""Focused tests for gbox.dmc1_iso (request #1856, Devil May Cry USA PS2).

Run: python -m pytest tests/test_dmc1_iso.py -q
Skips the big-image tests when the extracted raw image is absent; the header
parsing tests run on a synthetic ISO built in-process.
"""
import struct
from pathlib import Path

import pytest

from gbox.dmc1_iso import parse_pld_children, walk_dir, SECTOR

RAW = Path("/home/ehm_eckx/.hermes/cache/scratch/dmc1/dmc1_usa.bin")
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
