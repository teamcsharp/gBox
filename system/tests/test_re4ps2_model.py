"""RE4 PS2 (#1321) analysis probe: SNR2 export table, setModel slot pairs, BIN/TPL headers, object DMA chains."""
import json
import os
import struct
from pathlib import Path

import pytest

from gbox import re4ps2_model as m

RE = Path(os.environ.get("GBOX_RE4PS2_RE", str(Path.home() / "gbox-cache/109d8ee7747a7dd8/re")))


def _bin(nb=3, nobj=1, ids=None):
    b = bytearray(b"\xcd" * 0x200)
    struct.pack_into("<HHI", b, 0, 0x30, 8, 0x50)
    b[8], b[9] = 4, nb
    struct.pack_into("<HI", b, 0xA, nobj, 0x100)
    struct.pack_into("<4I", b, 0x1C, 0x50 + 16 * nb, 0, 0, 0x30)
    struct.pack_into("<3f4x3f", b, 0x30, -1, -2, -3, 1, 2, 3)
    ids = ids or list(range(nb))
    for i, bid in enumerate(ids):
        struct.pack_into("<BB2x3f", b, 0x50 + 16 * i, bid, 0xFF if i == 0 else ids[i - 1], 0, i * 10.0, 0)
    for k in range(nobj):
        struct.pack_into("<12xI", b, 0x100 + 16 * k, 0x140)
    b[0x140:0x150] = bytes(range(16))                       # bone list header
    struct.pack_into("<4I", b, 0x150, 0x10000001, 0, 0x01000404, 0x6C018000)   # CNT qwc 1: STCYCL, UNPACK V4-32 n=1
    struct.pack_into("<4I", b, 0x170, 0x70000000, 0, 0, 0)                     # END
    return bytes(b)


def test_bin_header_bones_bbox_and_dma():
    h = m.bin_header(_bin())
    assert (h["bone_count"], h["object_count"], h["data_offset"], h["bbox"]) == (3, 1, 0x100, [[-1, -2, -3], [1, 2, 3]])
    assert [b["parent"] for b in h["bones"]] == [0xFF, 0, 1] and h["bone_ids_are_index"] and h["unused_cd_fill"]
    obj = m.bin_objects(_bin())[0]
    assert obj["packet"] == 0x140 and obj["bone_list"] == list(range(16))
    assert [(t["qwc"], t["id"]) for t in obj["dma"]] == [(1, 1), (0, 7)]
    assert obj["dma"][0]["vif"][0]["cmd"] == "STCYCL"
    assert obj["dma"][0]["vif"][1] == {"cmd": "UNPACK", "vn": 4, "vl": 32, "num": 1, "addr": 0, "flg": True,
                                       "usn": False}


def test_bin_header_accepts_offset_ids_rejects_orphans():
    assert not m.bin_header(_bin(ids=[2, 3, 4]))["bone_ids_are_index"]
    b = bytearray(_bin())
    b[0x50 + 16 * 2 + 1] = 9                                # parent never seen
    with pytest.raises(ValueError, match="parent-first"):
        m.bin_header(bytes(b))
    with pytest.raises(ValueError):
        m.bin_header(b"\0" * 0x40)


def test_tpl_header_formats():
    t = bytearray(0x200)
    struct.pack_into("<4I", t, 0, 0x1000, 2, 0x10, 0)
    struct.pack_into("<6H3I", t, 0x10, 256, 128, 8, 2, 0x40, 0, 0x400, 0, 0)
    struct.pack_into("<II", t, 0x30, 0x80, 0x180)
    struct.pack_into("<6H3I", t, 0x40, 128, 64, 9, 0, 0x20, 0, 0x100, 0, 0)
    struct.pack_into("<II", t, 0x60, 0x100, 0)
    h = m.tpl_header(bytes(t))
    assert h["count"] == 2 and not h["relocated"]
    assert [(x["w"], x["h"], x["format_name"], x["image_offset"]) for x in h["textures"]] == \
        [(256, 128, "C4", 0x80), (128, 64, "C8", 0x100)]
    with pytest.raises(ValueError):
        m.tpl_header(b"\0" * 64)


def test_probe_accepts_bin_bin_pair_for_non_leon_packs():
    """Ashley-style layouts bind two BIN slots; the second slot records tpl=None with a reason."""
    b, t = _bin(), bytearray(0x200)
    struct.pack_into("<4I", t, 0, 0x1000, 1, 0x10, 0)
    struct.pack_into("<6H3I", t, 0x10, 256, 128, 8, 2, 0x40, 0, 0x400, 0, 0)
    struct.pack_into("<II", t, 0x30, 0x80, 0x180)
    pack = bytearray(b"\0" * 0x20) + b + bytes(t)
    struct.pack_into("<2I", pack, 16, 0x20, 0x20 + len(b))
    pack[16 + 8:16 + 8 + 8] = b"BIN\0TPL\0"
    struct.pack_into("<I", pack, 0, 2)
    res = m.probe(bytes(pack), [{"call": 0, "callee": "modelInit", "bin_slot": 0, "tpl_slot": 1}])
    assert res[0]["tpl"]["count"] == 1 and res[0]["tpl_offset"] == 0x20 + len(b)
    res = m.probe(bytes(pack), [{"call": 0, "callee": "modelInit", "bin_slot": 0, "tpl_slot": 0}])
    assert res[0]["tpl"] is None and "not TPL" in res[0]["tpl_reason"]
    assert res[0]["bin"]["bone_count"] == 3 and len(res[0]["objects"]) == 1
    json.dumps(res)


def _elf_with(code: list[int], syms: dict[str, int]):
    """Tiny ELF: one PT_LOAD at 0x100000 holding `code` at 0x100100 and an SNR2 table at SNDATA_VADDR-style offset."""
    base, sn = 0x100000, 0x101000
    img = bytearray(0x3000)
    for i, w in enumerate(code):
        struct.pack_into("<I", img, 0x100 + 4 * i, w)
    names = list(syms)
    strs, table = sn + 0x40, sn + 0x400
    struct.pack_into("<5I", img, sn - base, 0x32524E53, table, 0, table, len(names) + 1)
    p = strs
    img[p - base] = 0
    p += 1
    for i, n in enumerate(names):
        img[p - base:p - base + len(n) + 1] = n.encode() + b"\0"
        struct.pack_into("<3I", img, table - base + 12 * (i + 1), p, syms[n], 0)
        p += len(n) + 1
    hdr = bytearray(0x1000)
    hdr[:4] = b"\x7fELF"
    hdr[4], hdr[5] = 1, 1
    struct.pack_into("<H", hdr, 18, 8)
    struct.pack_into("<I", hdr, 28, 0x34)
    struct.pack_into("<H", hdr, 44, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, 0x1000, base, base, len(img), len(img), 7, 16)
    return bytes(hdr + img), sn


def _lw(rt, imm, rs=2):
    return (0x23 << 26) | (rs << 21) | (rt << 16) | imm


def _jal(t):
    return (3 << 26) | ((t >> 2) & 0x3FFFFFF)


def test_set_model_pairs_from_code_and_symbols():
    syms = {"setModel__7cPlLeon": 0x100100, "modelInit__6cModelUiUi": 0x100200, "create__11cModInfoMgrUiUi": 0x100300,
            "zz_next": 0x100180}
    code = [_lw(2, 0x58), _lw(5, 0x10), _lw(6, 0x14), _jal(0x100200), 0,
            _lw(2, 0x58), _lw(5, 0x18), _lw(6, 0x1C), _jal(0x100300), 0,
            _lw(6, 0x58, 3), _lw(5, 0x40, 6), _lw(2, 0x14, 6), _jal(0x100300), 0]
    elf, sn = _elf_with(code, syms)
    s = m.exe_symbols(elf, sn)
    assert s == syms
    pairs = m.set_model_pairs(elf, syms=s)
    assert [(p["callee"], p["bin_slot"], p["tpl_slot"]) for p in pairs] == \
        [("modelInit", 0, 1), ("create", 2, 3), ("create", 12, 1)]


@pytest.mark.skipif(not (RE / "SLUS_211.34").exists() or not (RE / "pl00.dat").exists(),
                    reason="owned RE4 PS2 ELF / pl00.dat not staged")
def test_owned_leon_set_model_probe():
    import hashlib
    elf = (RE / "SLUS_211.34").read_bytes()
    assert hashlib.sha256(elf).hexdigest() == m.ELF_SHA256
    syms = m.exe_symbols(elf)
    assert len(syms) == 7408 and syms["setModel__7cPlLeon"] == 0x159BB0
    assert syms["init__10cModelInfoUiUi"] == 0x22DCC8 and syms["Assign__6PS2TEXP10TEXPalette"] == 0x2510F0
    pairs = m.set_model_pairs(elf, syms=syms)
    assert [(p["bin_slot"], p["tpl_slot"]) for p in pairs] == [(0, 1), (6, 1), (9, 1), (4, 3), (2, 3), (5, 3), (12, 1)]
    res = m.probe((RE / "pl00.dat").read_bytes(), pairs)
    body = res[0]
    assert (body["bin_offset"], body["tpl_offset"]) == (0x440, 0x15F80)
    assert (body["bin"]["bone_count"], body["bin"]["object_count"], body["bin"]["data_offset"]) == (119, 7, 0x800)
    assert [o["packet"] for o in body["objects"]] == [0x870, 0x3070, 0xB090, 0x11030, 0x117A0, 0x13600, 0x156A0]
    first = body["objects"][0]["dma"][0]
    assert (first["qwc"], first["id"], first["vif"][1]["cmd"], first["vif"][1]["num"]) == (0x18, 1, "UNPACK", 0x18)
    assert body["tpl"]["count"] == 8 and {t["format_name"] for t in body["tpl"]["textures"]} == {"C4"}
    assert (res[3]["tpl"]["count"], res[3]["bin"]["bone_count"], res[3]["root_bones"]) == (3, 16, [2])
    json.dumps(res)
