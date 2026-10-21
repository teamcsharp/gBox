"""Power Stone 2 (USA) DC inventory: CONNECT table parsing, name table and the real-disc manifest.

The disc test needs the unpacked owned GD-ROM (``GBOX_PSTONE2_GDI`` or the default cache path)
and is skipped without it; the container tests use synthetic bytes.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import pstone2_inventory as inv

GDI = Path(os.environ.get("GBOX_PSTONE2_GDI",
                          Path.home() / "gBox_alt/gbox-cache/dc/690a402443c15668/disc.gdi"))


def _connect(blobs, stale=()):
    """Build a CONNECT file: 16 (offset,size) slots, payloads at 32-byte-aligned offsets."""
    out = bytearray(0x80)
    slots = []
    for b in blobs:
        off = (len(out) + 31) & ~31
        out.extend(b"\0" * (off - len(out)))
        slots.append((off, len(b)))
        out.extend(b)
    for i, (o, s) in enumerate((slots + list(stale))[:16]):
        struct.pack_into("<II", out, 8 * i, o, s)
    return bytes(out)


def test_connect_table_stops_at_stale_slots_and_keeps_empty_placeholders():
    model = b"\xff\xff\xff\xff" + struct.pack("<3I", 2, 0x830, 5) + b"\0" * 20
    tex = b"\x01\x00\x08\x10" + b"\x11" * 13
    data = _connect([model, tex, b"", b"\x10\0\0\0\x10\x20\0\0" + b"\0" * 8],
                    stale=[(0x79340, 0x15430), (0x8e780, 0x28214)])
    t = inv.connect_table(data)
    assert [s for _, s in t] == [len(model), len(tex), 0, 16]
    assert t[2][0] == t[3][0]                        # empty slot shares the next offset
    kinds, prev = [], None
    for o, s in t:
        c = inv.classify(data[o:o + s], prev)
        kinds.append(c["kind"])
        prev = c["kind"]
    assert kinds == ["model", "texture_pack", "empty", "motion"]


def test_connect_table_rejects_bad_header():
    with pytest.raises(ValueError):
        inv.connect_table(b"\x40\0\0\0" + b"\0" * 0x7c)


def test_name_table_and_compare():
    exe = b"\0" * 8 + b"CMN_MOT.BIN\0" + b"PL00_CONNECT.BIN\0\0\0\0" + b"S01.GIF\0" + b"\x01\x02"
    names = inv.name_table(exe, at=8)
    assert names == ["CMN_MOT.BIN", "PL00_CONNECT.BIN", "S01.GIF"]
    cmp = inv.compare_names(names + ["DUMMY.BIN"], {"CMN_MOT.BIN": (1, 1), "PL00_CONNECT.BIN": (2, 1),
                                                     "DPSS/S01.GIF": (3, 1), "1ST_READ.BIN": (4, 1)})
    assert cmp["missing_on_disc"] == ["DUMMY.BIN"] and cmp["not_in_table"] == ["1ST_READ.BIN"]
    assert cmp["load_id"]["PL00_CONNECT.BIN"] == 1


@pytest.mark.skipif(not GDI.exists(), reason="owned Power Stone 2 (USA) GD-ROM not unpacked")
def test_real_disc_manifest():
    m = inv.inventory(GDI, hash_tracks=False)
    assert m["ip"]["product"] == "T1211N" and m["ip"]["version"] == "V1.000" and m["ip"]["area"] == "U"
    assert m["first_read"]["sha256"] == inv.FIRST_READ_SHA256
    nt = m["first_read"]["name_table"]
    assert nt["count"] == 497 and nt["missing_on_disc"] == ["DM22_CONNECT.BIN", "DUMMY.BIN"]
    assert nt["not_in_table"] == ["0GDTEX.PVR", "1ST_READ.BIN"]
    r = {e["pl"]: e for e in m["roster"]}
    assert len(r) == 18 and all(e["layout_ok"] for e in r.values())
    assert r["00"]["key"] == "FOKKER" and r["E0"]["key"] == "MERU" and r["F0"]["key"] == "PAPA"
    assert r["00"]["models"] == 3 and r["E0"]["models"] == 1
    assert r["00"]["sound_banks"]["1P"] == "FOKKER_1P.BIN"
    # PL12/PL72 are Ryoma/Rouge alternates: same motion bank (and Rouge's model) as the base file
    assert r["12"]["variant_of"] == "PL10_CONNECT.BIN" and "motion_bank" in r["12"]["shared_with_base"]
    assert "body_model" in r["72"]["shared_with_base"]
    c = m["containers"]["PL00_CONNECT.BIN"]
    assert c["load_id"] == 3 and c["room"] >= c["size"]
    assert [e["role"] for e in c["entries"]][:5] == ["body_model", "body_textures", "power_change_model",
                                                     "power_change_textures", "motion_bank"]
