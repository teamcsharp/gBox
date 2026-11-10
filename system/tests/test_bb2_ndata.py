import os
import re
import struct
from pathlib import Path

import pytest

from gbox.formats import bb2_ndata as b

SCRATCH = Path(os.environ.get("BB2_FILES", Path.home() / ".hermes/cache/scratch/bb2/files"))


def _synthetic():
    base = 0x80010000 - 0x800
    exe = bytearray(0x1000)
    exe[:8] = b"PS-X EXE"
    struct.pack_into("<I", exe, 0x18, 0x80010000)
    names = [b"DATA0\\M000.DAT\0", b"DATA2\\S00.DAT\0"]
    pos = 0x400
    ptrs = []
    for n in names:
        exe[pos:pos + len(n)] = n
        ptrs.append(base + pos)
        pos += 32
    return exe, ptrs


def test_name_table_and_inf_synthetic():
    exe, ptrs = _synthetic()
    struct.pack_into("<2I", exe, 0x800, *ptrs)
    assert b.parse_name_table(bytes(exe), 2, 0x800) == ["DATA0\\M000.DAT", "DATA2\\S00.DAT"]
    inf = struct.pack("<HHHH", 0, 3, 0xFFFF, 0xFFFF)
    recs = b.parse_inf(inf, 2)
    assert recs == [(0, 3), None]
    with pytest.raises(ValueError):
        b.parse_inf(struct.pack("<HHHH", 5, 3, 2, 1), 2)


def test_section_table_synthetic():
    blob = struct.pack("<4I", 2, 16, 24, 40) + b"\0" * 32
    assert b.parse_section_table(blob) == [16, 24, 40]
    with pytest.raises(ValueError):
        b.parse_section_table(struct.pack("<4I", 2, 24, 16, 40) + b"\0" * 32)


@pytest.mark.skipif(not (SCRATCH / "NDATA.DAT").exists(), reason="owned BB2 files not present")
def test_real_disc_character_banks():
    inf = (SCRATCH / "NDATA" / "NDATA.INF").read_bytes()
    exe = (SCRATCH / "SLUS_006.63").read_bytes()
    slots = b.build_slots(inf, exe)
    assert len(slots) == 899
    assert sum(s.present for s in slots) == 760
    chars = [s for s in slots if re.fullmatch(r"DATA0\\M\d{3}\.DAT", s.name)]
    assert len(chars) == 37 and all(s.present for s in chars)
    assert slots[0].name == "DATA0\\M000.DAT" and (slots[0].sector, slots[0].nsectors) == (0, 73)
    end = max((s.sector or 0) + (s.nsectors or 0) for s in slots)
    assert end * 2048 == (SCRATCH / "NDATA.DAT").stat().st_size
    with open(SCRATCH / "NDATA.DAT", "rb") as dat:
        for s in chars:
            offs = b.parse_section_table(b.read_slot(dat, s))
            assert len(offs) in (6, 7)
