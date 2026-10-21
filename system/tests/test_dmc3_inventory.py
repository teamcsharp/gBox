import json
import os
import struct
from pathlib import Path

import pytest

from gbox import dmc3_inventory as d3

ISO = Path(os.environ.get("GBOX_DMC3SE_ISO", Path.home() / "gBox_alt/gbox-cache/ps2/251d9887eb0ccfb3/disc.iso"))


def pac(children, magic=b"PAC\0"):
    head = 8 + 4 * len(children)
    head += -head % 16
    offs, body = [], b""
    for c in children:
        if c is None:
            offs.append(0)
            continue
        offs.append(head + len(body))
        body += c + b"\0" * (-len(c) % 16)
    return magic + struct.pack("<I", len(children)) + struct.pack(f"<{len(children)}I", *offs) \
        + b"\0" * (head - 8 - 4 * len(children)) + body


def tim2(w=128, h=256, itype=5, colors=256):
    img, clut = w * h * {4: 1, 5: 1}.get(itype, 2) // (2 if itype == 4 else 1), colors * 4
    pic = struct.pack("<IIIHH", 0x30 + clut + img, clut, img, 0x30, colors) \
        + struct.pack("<BBBBHH", 0, 1, 3, itype, w, h) + b"\0" * 0x18
    return b"TIM2" + bytes([4, 0]) + struct.pack("<H", 1) + b"\0" * 8 + pic + b"\0" * (img + clut)


def mod(objects=17, bones=24):
    return b"MOD " + struct.pack("<f", 1.01) + b"\0" * 8 + struct.pack("<BBBBII", objects, bones, 3, 1, 0xD9, 0x2CAF0) \
        + b"\0" * 0x40


def motion():
    return b"P\0\0\0MOT\0" + b"\0" * 24


def texbank(*pics):
    head = struct.pack("<I", len(pics)) + b"\0" * 12
    return head + b"".join(p + b"\0" * (-len(p) % 16) for p in pics)


def test_pac_children_empty_slots_run_to_next_nonzero_offset():
    b = pac([b"A" * 20, None, b"B" * 5, None])
    ch = d3.pac_children(b)
    assert [z for _, z in ch] == [32, 0, len(b) - ch[2][0], 0]
    assert ch[1] == (0, 0) and ch[3] == (0, 0)
    assert b[ch[0][0]:ch[0][0] + 20] == b"A" * 20
    with pytest.raises(ValueError):
        d3.pac_children(b"PAC\0" + struct.pack("<II", 1, 0x999))
    with pytest.raises(ValueError):
        d3.pac_children(b"MOD " + b"\0" * 12)


def test_tim2_mod_and_kind():
    t = d3.tim2_info(tim2())
    assert t["pictures"] == [{"w": 128, "h": 256, "bpp": 8, "mipmaps": 1, "clut_colors": 256,
                              "image_bytes": 128 * 256, "clut_bytes": 1024}]
    bank = texbank(tim2(256, 256), tim2(128, 128, itype=4, colors=16))
    assert d3.kind(bank) == "texbank"
    assert [(p["w"], p["h"], p["bpp"]) for t in d3.tim2_scan(bank) for p in t["pictures"]] == [(256, 256, 8), (128, 128, 4)]
    m = d3.mod_info(mod(6, 33))
    assert (m["version"], m["objects"], m["bones"], m["section_offset"]) == (1.01, 6, 33, 0x2CAF0)
    assert d3.kind(motion()) == "motion" and d3.kind(b";pl000_02.clt\r\n") == "text"
    assert d3.kind(b"SHW " + b"\0" * 12) == "shadow" and d3.kind(pac([b"x"], b"PNST")) == "pnst"


def test_walk_nested_player_package():
    player = pac([texbank(tim2(256, 256), tim2(128, 256)), mod(), pac([motion(), None, motion()]),
                  b"SHW " + b"\0" * 12, mod(6, 33), b";pl000_02.clt\r\n", None])
    rows = []
    d3.walk(player, "GDATA.AFS:0", rows)
    s = d3.summarize(rows)
    assert rows[0]["slots"] == 7 and rows[0]["empty_slots"] == 1
    assert [(x["objects"], x["bones"]) for x in s["models"]] == [(17, 24), (6, 33)]
    assert [(t["w"], t["h"]) for t in s["textures"]] == [(256, 256), (128, 256)]
    assert s["motions"] == 2 and s["shadows"] == 1 and s["texts"] == [";pl000_02.clt"]
    assert {r["path"] for r in rows if r["kind"] == "motion"} == {"GDATA.AFS:0/2/0", "GDATA.AFS:0/2/2"}


def test_afs_read_name_directory(tmp_path):
    blobs = [b"PAC\0" + b"\1" * 60, b"x" * 100]
    n, first = len(blobs), d3.SECTOR
    offs, o = [], first
    for b in blobs:
        offs.append(o)
        o += len(b) + (-len(b) % d3.SECTOR)
    nd_off = o
    names = b"".join(nm.ljust(32, b"\0") + struct.pack("<6HI", 2005, 8, 5, 10, 7, 14, len(b))
                     for nm, b in zip([b"pl000.pac", b"st000.pac"], blobs))
    img = bytearray(nd_off + len(names))
    img[:8] = b"AFS\0" + struct.pack("<I", n)
    for i, (oo, b) in enumerate(zip(offs, blobs)):
        struct.pack_into("<II", img, 8 + 8 * i, oo, len(b))
        img[oo:oo + len(b)] = b
    struct.pack_into("<II", img, 8 + 8 * n, nd_off, len(names))
    img[nd_off:] = names
    p = tmp_path / "g.afs"
    p.write_bytes(bytes(img))
    with p.open("rb") as f:
        a = d3.afs_read(f, 0, len(img))
    assert a["names"] == ["pl000.pac", "st000.pac"] and a["name_size_agrees"] == 2
    assert a["dates"][0] == "2005-08-05 10:07:14" and a["entries"][1] == (offs[1], 100)


@pytest.mark.skipif(not ISO.exists(), reason="owned DMC3 SE disc image not staged")
def test_owned_disc_inventory(tmp_path):
    m = d3.inventory(ISO)
    assert m["serial"] == "SLUS_213.61" and m["flist"] == ["GData.afs", "MData1.afs", "MData2.afs", "SData.afs"]
    assert m["executable"]["sha256"] == "a538ac05f313f193fbf86d44aa6cf97764456ce1994a896cc6ef5aff17b11a2b"
    assert m["executable"]["afs_name_refs"] == {"GData.afs": 1, "pl%03d": 0, ".pac": 0}
    g = m["archives"]["GDATA.AFS"]
    assert g["entries"] == 3863 and g["name_size_agrees"] == 3863
    by = {p["name"]: p for p in m["players"]}
    assert len(by) == 20 and set(d3.COMMUNITY_LABELS) <= set(by)
    dante = by["pl000.pac"]
    assert dante["index"] == 0 and dante["size"] == 803232
    assert [(x["objects"], x["bones"]) for x in dante["models"]] == [(17, 24), (6, 33)]
    assert [(t["w"], t["h"], t["bpp"]) for t in dante["textures"]] == [(256, 256, 8), (128, 256, 8), (128, 128, 8)]
    assert dante["motions"] == 40 and dante["motion_banks"] == 32
    assert {k: len(v) for k, v in m["player_motion_banks"].items()} == {"pl000": 32, "pl001": 32, "pl021": 10, "pl002": 3}
    assert all(p["models"] and p["textures"] for p in m["players"])
    assert m["counts"]["weapons"] == 20 and m["counts"]["enemies"] == 24
    json.dumps(m)
