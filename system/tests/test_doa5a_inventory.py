"""Focused tests for gbox.doa5a_inventory (DOA5 Ultimate Arcade, RingEdge 2 / TeknoParrot)."""
import os
import random
import struct
import zlib

import pytest

from gbox import doa5a_inventory as inv


def _container(magic: bytes, children: list, hsize: int = 0x30) -> bytes:
    """Build a KT container: header, offset table, then children (None = empty slot)."""
    n = len(children)
    otab = hsize
    body_off = (otab + 4 * n + 15) & ~15
    offs, body = [], bytearray()
    for ch in children:
        if ch is None:
            offs.append(0)
            continue
        offs.append(body_off + len(body))
        body += ch
        body += b"\0" * (-len(body) % 16)
    size = body_off + len(body)
    head = bytearray(hsize)
    head[0:8] = magic.ljust(8, b"\0")
    struct.pack_into("<8I", head, 8, inv.KT_VERSION, hsize, size, n, n - children.count(None), 0, otab, 0)
    table = struct.pack(f"<{n}I", *offs).ljust(body_off - otab, b"\0")
    return bytes(head) + table + bytes(body)


def _tmc() -> bytes:
    geo = _container(b"MdlGeo", [b"\x11" * 32, b"\x22" * 32, b"\x33" * 32])
    tex = _container(b"TTDM", [b"\x44" * 16, b"\x55" * 16])
    raw = bytearray(_container(b"TMC", [geo, tex, None, b"rawbytes" * 4], hsize=0x140))
    # real TMC headers carry an id string at 0x50 inside the 0x140-byte header
    raw[0x50:0x60] = b"j8VDaFeNRCP5U4\0\0"
    return bytes(raw)


def test_kt_roundtrip_mixed_stored_and_zlib_records():
    rnd = random.Random(5)
    raw = bytes(rnd.getrandbits(8) for _ in range(0x4000)) + b"\0" * 0x4000 + b"tail" * 0x49
    enc = inv.kt_compress(raw)
    out, used, st = inv.kt_decode(enc)
    assert out == raw and used == len(enc)
    assert st == {"records": 3, "zlib": 2, "stored": 1, "fill": 0}


def test_kt_decode_odd_zlib_record_is_padded_to_four():
    # observed on HELENA_COS_001.tmc: word 0x85cb = zlib stream of 0x5cb bytes, then pad
    for k in range(64):
        rnd = random.Random(k)
        payload = bytes(rnd.choice(b"ACGT") for _ in range(0x4000 - k))
        a = zlib.compress(payload)
        if len(a) % 4:
            break
    assert len(a) % 4
    rec = struct.pack("<I", len(a) | inv.ZFLAG) + a + b"\0" * (-len(a) % 4)
    rec += struct.pack("<I", 0)                       # zero filler word
    rec += struct.pack("<I", 5) + b"BBBBB" + b"\0\0\0"
    data = struct.pack("<I", len(payload) + 5) + rec
    out, used, st = inv.kt_decode(data)
    assert out == payload + b"BBBBB" and used == len(data)
    assert st == {"records": 2, "zlib": 1, "stored": 1, "fill": 1}


@pytest.mark.parametrize("data", [
    b"\x10\0",                                            # no size field
    struct.pack("<I", 8) + struct.pack("<I", 4) + b"abc",  # truncated record
    struct.pack("<I", 4) + struct.pack("<I", 0x10004) + b"abcd",  # unknown flag bits
    struct.pack("<II", 2, 4) + b"abcd",                   # decodes past header total
])
def test_kt_decode_rejects_malformed(data):
    with pytest.raises(ValueError):
        inv.kt_decode(data)


def test_tmc_summary_lists_child_chunks():
    s = inv.tmc_summary(_tmc())
    assert s["chunks"] == [["MdlGeo", 3], ["TTDM", 2], [None, None]]
    assert s["chunk_count"] == 4 and s["valid"] == 3 and s["tmc_id"] == "j8VDaFeNRCP5U4"
    with pytest.raises(ValueError):
        inv.tmc_summary(_container(b"char_dat", [b"x" * 16]))


def test_parse_container_rejects_offsets_outside():
    bad = bytearray(_container(b"texch", [b"x" * 16, b"y" * 16]))
    struct.pack_into("<I", bad, 0x30, len(bad) + 64)
    with pytest.raises(ValueError):
        inv.parse_container(bytes(bad))


def test_load_listing_and_classify(tmp_path):
    lst = tmp_path / "l.tsv"
    lines = [
        "d\t0\t1\t.", "d\t0\t1\t./character", "d\t0\t1\t./character/AKIRA",
        "f\t115028\t1\t./character/AKIRA/akira.bin",
        "f\t115060\t1\t./character/AKIRA/akira_non_encrypt.bin",
        "f\t2032\t1\t./character/AKIRA/akira.phyd",
        "f\t1045332\t1\t./character/AKIRA/costume/COS_001/AKIRA_COS_001.tmc",
        "f\t4611780\t1\t./character/AKIRA/costume/COS_001/AKIRA_COS_001.tmcl",
        "f\t80\t1\t./character/AKIRA/costume/COS_001/AKIRA_COS_001.misc",
        "f\t80\t1\t./character/AKIRA/costume/COS_002/AKIRA_COS_002.misc",
        "f\t792020\t1\t./character/AKIRA/equipment/HAIR_001/AKIRA_HAIR_001.tmc",
        "f\t1486388\t1\t./character/AKIRA/equipment/FACE/AKIRA_FACE.tmc",
        "f\t2821248\t1\t./character/AKIRA/animation/INGAME/AKIRA_INGAME.mpm",
        "f\t881952\t1\t./character/AKIRA/rtm/DM002_MOT/AKIRA_DM002_MOT.mpm",
        "f\t73824\t1\t./character/AKIRA/tag_motion/KASUMI/AKIRA_KASUMI.mpm",
        "f\t14720\t1\t./character/AKIRA/camera/AKIRA_SELECT.cam",
        "f\t3\t1\t./steam_appid.txt",
    ]
    lst.write_text("\n".join(lines) + "\n")
    rows = inv.load_listing(str(lst))
    assert ("f", 3, "steam_appid.txt") in rows and all(r[2] != "." for r in rows)
    chars = inv.classify_character_files(rows)
    a = chars["AKIRA"]
    assert a["costumes"]["COS_001"] == {"tmc": 1045332, "tmcl": 4611780, "misc": 80}
    assert "tmc" not in a["costumes"]["COS_002"]
    assert a["bins"] == {"akira.bin": 115028, "akira_non_encrypt.bin": 115060}
    assert a["motion_files"] == {"rtm": 1, "tag_motion": 1}
    t = inv.totals(rows)
    assert t["by_ext"]["tmc"] == [3, 1045332 + 792020 + 1486388]


def _fake_pe(stamp: int) -> bytes:
    b = bytearray(0x400)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHI", b, 0x84, 0x14C, 1, stamp)
    struct.pack_into("<H", b, 0x80 + 20, 0xE0)
    opt = 0x80 + 24
    struct.pack_into("<H", b, opt, 0x10B)
    struct.pack_into("<I", b, opt + 28, 0x400000)
    s = opt + 0xE0
    b[s:s + 8] = b".text\0\0\0"
    struct.pack_into("<4I", b, s + 8, 0x200, 0x1000, 0x200, 0x200)
    b[0x200:0x21b] = b"character/%s/costume/%s.tmc"
    return bytes(b)


def test_build_inventory_on_synthetic_tree(tmp_path):
    root = tmp_path / "DOA5"
    cos = root / "character" / "HELENA" / "costume" / "COS_001"
    cos.mkdir(parents=True)
    exe = _fake_pe(0x52800000)
    (root / "DOA5A.exe").write_bytes(exe)
    orig = bytearray(exe)
    orig[0x300:0x304] = b"\x90\x90\x90\x90"
    (root / "DOA5A.exe.orig").write_bytes(bytes(orig))
    (root / "teknoparrot.ini").write_text("[General]\r\nDongleRegion=EXPORT\r\nFreePlay=1\r\n")
    (root / "steam_appid.txt").write_text("480")
    (root / "plugins").mkdir()
    (root / "plugins" / "not_top_level.dll").write_bytes(b"")
    raw = _tmc()
    (cos / "HELENA_COS_001.tmc").write_bytes(inv.kt_compress(raw))
    (cos / "HELENA_COS_001.tmcl").write_bytes(inv.kt_compress(b"\x01" * 300))
    man = inv.build_inventory(str(root), profile={"ExecutableName": "DOA5A.exe"})
    src = man["source"]
    assert src["exe"]["pe"]["machine"] == "0x14c" and src["exe"]["pe"]["pe32"]
    assert src["exe"]["asset_strings"] == ["character/%s/costume/%s.tmc"]
    assert src["patch_vs_orig"]["differing_bytes"] == 4
    assert src["patch_vs_orig"]["ranges"] == [[0x300, 4, hex(0x400000 + 0x1000 + 0x100)]]
    assert man["launch"]["teknoparrot.ini"]["General"]["DongleRegion"] == "EXPORT"
    assert man["launch"]["steam_appid.txt"] == "480"
    assert man["launch"]["runtime_dlls"] == ["DOA5A.exe"]   # walk() rows use '/' on every OS
    assert man["roster"][0]["name"] == "HELENA" and man["roster"][0]["costumes"] == 1
    d = man["deep_tmc"][0]
    assert d["raw_size"] == len(raw) and d["tmcl_raw_size"] == 300 and "error" not in d
    assert man["summary"]["chunk_tags"] == ["MdlGeo", "TTDM"]


REAL = os.environ.get("GBOX_DOA5A_ROOT")


@pytest.mark.skipif(not REAL, reason="set GBOX_DOA5A_ROOT to the owned DOA5 directory")
def test_real_helena_cos_001_tmc_decodes():
    data = open(os.path.join(REAL, "character/HELENA/costume/COS_001/HELENA_COS_001.tmc"), "rb").read()
    raw, used, st = inv.kt_decode(data)
    assert len(raw) == 0x1C01C0 and st["zlib"] == 113 and st["stored"] + st["fill"] == 177
    assert inv.parse_container(raw)["magic"] == "TMC"
