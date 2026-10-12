"""Resident Evil 4 GC (G4BE08 USA Disc 1) inventory: disc header, bounded UDAS/DAT directories, BIN/TPL headers,
pack summary and motion families; plus the owned-disc manifest when the unpacked ISO is cached."""
import os
import struct
from pathlib import Path

import pytest

from gbox import re4gc_inventory as ri

ISO = Path(os.environ.get("GBOX_RE4GC_ISO", Path.home() / "gbox-cache/modbase/78ab9efa2e310db4"
                          / "Resident Evil 4 (USA) (Disc 1).iso"))


def _head(magic=ri.GC_MAGIC, disc=0, region=1):
    h = bytearray(0x440)
    h[:6] = b"G4BE08"
    h[6], h[7] = disc, 0
    h[0x20:0x35] = b"resident evil 4 disc1"
    struct.pack_into(">I", h, 0x1C, magic)
    struct.pack_into(">III", h, 0x420, 0x20300, 0x231A00, 0x5B9C)
    bi2 = bytearray(0x20)
    struct.pack_into(">I", bi2, 0x18, region)
    return bytes(h), bytes(bi2)


def test_disc_header_identity_region_and_magic():
    h = ri.disc_header(*_head())
    assert (h["disc_id"], h["maker"], h["disc_number"], h["version"]) == ("G4BE08", "08", 1, 0)
    assert h["title"] == "resident evil 4 disc1" and h["region"] == "NTSC-U"
    assert (h["dol_offset"], h["fst_offset"], h["fst_size"]) == (0x20300, 0x231A00, 0x5B9C)
    assert ri.disc_header(*_head(disc=1, region=2))["disc_number"] == 2
    with pytest.raises(ValueError):
        ri.disc_header(*_head(magic=0))


def _udas(blobs, terminate=True):
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    off = 0x400
    for t, blob in blobs:
        hdr += struct.pack(">IIII", t, len(blob), 0, off) + bytes(16)
        off += len(blob)
    if terminate:
        hdr += b"\xff\xff\xff\xff"
    hdr += b"\xcc" * (0x400 - len(hdr))
    return bytes(hdr) + b"".join(b for _, b in blobs)


def _dat(items):
    n = len(items)
    head = 16 + 8 * n
    offs, body, at = [], b"", (head + 31) & -32
    for ext, blob in items:
        offs.append(at + len(body) if ext else 0)
        body += blob + bytes(-len(blob) % 32)
    return (struct.pack(">II8x", n, 0) + struct.pack(f">{n}I", *offs)
            + b"".join(e.encode().ljust(4, b"\0") for e, _ in items) + bytes(at - head) + body)


def _bin(bones=3, mats=2, npos=10, nnrm=11):
    b = bytearray(0x60 + 16 * bones + 64)
    struct.pack_into(">I", b, 0, 0x60)
    for at in (0x0C, 0x10, 0x14, 0x1C, 0x30, 0x34):
        struct.pack_into(">I", b, at, 0x60 + 16 * bones)
    b[0x18], b[0x19], b[0x28] = 2, bones, 4
    struct.pack_into(">H", b, 0x1A, mats)
    struct.pack_into(">HH", b, 0x38, npos, nnrm)
    return bytes(b)


def _tpl(w=64, h=32, fmt=14):
    b = bytearray(0x40 + w * h // 2)
    struct.pack_into(">III", b, 0, ri.TPL_MAGIC, 1, 0x0C)
    struct.pack_into(">II", b, 0x0C, 0x20, 0)
    struct.pack_into(">HHII", b, 0x20, h, w, fmt, 0x40)
    return bytes(b)


def test_udas_entries_bounded():
    pack = _udas([(0, b"A" * 64), (4, b"B" * 32)])
    assert ri.udas_entries(pack) == [{"type": 0, "size": 64, "offset": 0x400}, {"type": 4, "size": 32, "offset": 0x440}]
    with pytest.raises(ValueError):
        ri.udas_entries(_udas([(0, b"A" * 64)], terminate=False))   # no terminator inside 0x400 -> refused
    with pytest.raises(ValueError):
        ri.udas_entries(pack[:-1])                                   # last entry runs past the file


def test_dat_entries_keep_empty_slots():
    dat = _dat([("BIN", b"x" * 40), ("", b""), ("TPL", b"y" * 8)])
    rows = ri.dat_entries(dat)
    assert [r[0] for r in rows] == ["BIN", "", "TPL"]
    assert rows[1][2] == 0 and rows[0][2] == 64 and dat[rows[2][1]:rows[2][1] + 8] == b"y" * 8
    with pytest.raises(ValueError):
        ri.dat_entries(struct.pack(">II8x", 0, 0))


def test_bin_header_counts_and_refusals():
    h = ri.bin_header(_bin())
    assert h == {"skinned": True, "weights": 2, "bones": 3, "materials": 2, "pos_frac": 4, "positions": 10,
                 "normals": 11}
    bad = bytearray(_bin())
    struct.pack_into(">I", bad, 0, 0x50)
    with pytest.raises(ValueError):
        ri.bin_header(bytes(bad))                       # header size must be 0x40 or 0x60
    bad = bytearray(_bin())
    struct.pack_into(">I", bad, 0x30, len(bad) + 4)
    with pytest.raises(ValueError):
        ri.bin_header(bytes(bad))                       # table pointer outside the BIN
    with pytest.raises(ValueError):
        ri.bin_header(_bin(bones=200)[:0x60 + 16])      # bone table runs past the end


def test_tpl_images():
    assert ri.tpl_images(_tpl()) == [{"w": 64, "h": 32, "fmt": "CMPR"}]
    assert ri.tpl_images(_tpl(fmt=3))[0]["fmt"] == "IA8"
    with pytest.raises(ValueError):
        ri.tpl_images(b"\0" * 64)


def test_pack_summary_counts_meshes_textures_and_motion():
    dat = _dat([("BIN", _bin()), ("TPL", _tpl()), ("FCV", b"f" * 96), ("SEQ", b"s" * 32), ("", b""),
                ("EFF", b"e" * 32)])
    s = ri.pack_summary(_udas([(0, dat), (4, b"snd" * 11)]))
    assert s["slots"] == {"BIN": 1, "TPL": 1, "FCV": 1, "SEQ": 1, "empty": 1, "EFF": 1}
    assert [m["bones"] for m in s["meshes"]] == [3] and s["textures"][0]["images"][0]["fmt"] == "CMPR"
    assert s["motion_bytes"] == 96 + 32 and [u["type"] for u in s["udas"]] == [0, 4] and s["errors"] == []
    broken = _dat([("BIN", b"\0" * 0x40)])
    assert ri.pack_summary(_udas([(0, broken)]))["errors"]      # bad BIN is reported, not raised


def test_pack_kind_and_motion_families():
    assert [ri.pack_kind(n) for n in ("em/pl0a.drs", "em/em2d.drs", "em/wep40.drs", "em/obj.drs")] == \
        ["player/partner", "enemy/NPC", "weapon", "other"]
    rows = [{"file": f, "slots": {"FCV": c, "SEQ": q}, "motion_bytes": m} for f, c, q, m in
            [("em/pl08.drs", 66, 23, 444512), ("em/pl00.drs", 66, 23, 444512), ("em/pl01.drs", 86, 35, 483488)]]
    assert ri.motion_families(rows) == [["em/pl00.drs", "em/pl08.drs"], ["em/pl01.drs"]]


@pytest.mark.skipif(not ISO.is_file(), reason="owned RE4 GC disc image not unpacked on this node")
def test_owned_disc_manifest():
    m = ri.inventory(ISO)
    assert m["disc"]["disc_id"] == "G4BE08" and m["disc"]["region"] == "NTSC-U" and m["disc"]["disc_number"] == 1
    assert m["files"] == 1018 and m["totals"] == {"packs": 128, "errors": 0}
    assert m["dol"]["sha256"] == "f7cc1074b4cecc861b4b541d649c2bb644de248e62bed15f96b873bdb93ad4c2"
    assert len(m["characters"]) == 22 and m["other_pack_kinds"]["enemy/NPC"] > 0
    pl00 = m["characters"][0]
    assert pl00["file"] == "em/pl00.drs" and pl00["size"] == 2221088 and pl00["sha256"].startswith("9b24dbbffd3a")
    assert pl00["mesh_detail"][0] | {} == {"slot": 0, "size": 55520, "skinned": True, "weights": 107, "bones": 119,
                                          "materials": 14, "pos_frac": 4, "positions": 1484, "normals": 1489,
                                          "triangles": 2519}
    assert ["em/pl00.drs", "em/pl08.drs", "em/pl09.drs"] in [f[:3] for f in m["motion_families"]]
    assert "St3" not in m["layout"] and {"St1", "St2", "St4"} <= set(m["layout"])
