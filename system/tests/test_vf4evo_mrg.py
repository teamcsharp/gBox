"""Focused tests for gbox.vf4evo_mrg: MRG manifest parser + MRG_GZ codec probe."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import vf4evo_mrg as m  # noqa: E402


def _manifest_blob() -> bytes:
    """Reproduce an observed 284-byte merge-manifest .MRG (AK2_KAHA_30 shape)."""
    manifest = (
        b"mrg.lst\r\n"
        b"..\\..\\files\\ch_aki\\AK2_KAHA_31.itm\r\n"
        b"..\\..\\files\\ch_aki\\AK2_KAHA_31.link\r\n"
        b"..\\..\\files\\ch_aki\\AK2_KAHA_31.tex\r\n"
        b"_\r\n"
        b"..\\..\\files\\ch_aki\\AK2_KAHA_31.mrg\x00"
    )
    header = struct.pack("<7I", 4, 0x20, 0xC0, 0xE0, 0x100, 0, 0)
    # name table: three 32-byte entries, u32 len + "jack_of_straw" + NUL + pad
    name_entry = struct.pack("<I", 13) + b"jack_of_straw\x00" + b"\x00" * 14
    return header + struct.pack("<I", len(manifest)) + manifest + name_entry * 3


def test_parse_mrg_lst_extracts_sources_and_names():
    parsed = m.parse_mrg_lst(_manifest_blob())
    assert parsed["header"] == [4, 0x20, 0xC0, 0xE0, 0x100, 0, 0]
    assert parsed["manifest"].startswith("mrg.lst\r\n")
    assert parsed["sources"] == [
        "..\\..\\files\\ch_aki\\AK2_KAHA_31.itm",
        "..\\..\\files\\ch_aki\\AK2_KAHA_31.link",
        "..\\..\\files\\ch_aki\\AK2_KAHA_31.tex",
        "..\\..\\files\\ch_aki\\AK2_KAHA_31.mrg",
    ]
    assert parsed["names"] == ["jack_of_straw"]


def test_parse_mrg_lst_rejects_non_manifest():
    with pytest.raises(ValueError):
        m.parse_mrg_lst(b"\x00" * 512)


def test_classify_mrg_lst():
    assert m.classify_mrg(_manifest_blob())["kind"] == "mrg_lst"


def test_classify_vertex_buffer():
    # 16-byte stride: 3x float32 position + one u32, e.g. 1.0f weight
    verts = struct.pack("<3fI", 0.1, 0.2, 0.3, 0x3F800000) * 32
    assert m.classify_mrg(verts) == {"kind": "vertex_buffer", "stride": 16, "head": verts[:16].hex(" ")}


def test_classify_opaque_high_entropy():
    blob = os.urandom(65536)
    out = m.classify_mrg(blob)
    assert out["kind"] == "opaque"
    assert out["entropy_bits"] > 7.0  # near-uniform random


def test_mrg_gz_codec_rules_out_standard_decompressors():
    probe = m.mrg_gz_codec(os.urandom(8192))
    for label in ("zlib", "raw-deflate", "gzip", "auto", "bz2", "lzma"):
        assert label in probe["ruled_out"]
    assert probe["entropy_bits"] > 7.0
    assert "zlut_inflate" in probe["verdict"]


def test_elf_vf4evo_tables_finds_character_table():
    elf = (
        b"\x7fELF" + b"\x00" * 20 + struct.pack("<I", 0x00100008) + b"\x00" * 200
        + b"zlut_inflate: inflateInit2 err %d\x00"
        + b"1.1.3\x00"
        + b"ch_aki/CH_AKI.mrg_gz\x00ch_sar/CH_SA2.mrg_gz\x00"
    )
    tables = m.elf_vf4evo_tables(elf)
    assert tables["entry"] == 0x00100008
    assert tables["zlut_inflate_strings"]
    assert tables["zlib_version_1_1_3"]
    assert tables["character_table_entries"] == [
        "ch_aki/CH_AKI.mrg_gz",
        "ch_sar/CH_SA2.mrg_gz",
    ]


def test_gz_member_roundtrip_and_mrg_offsets():
    import struct, zlib
    from gbox import vf4evo_mrg as m
    body = struct.pack("<3I", 2, 16, 20) + b"\x00" * 4 + b"ABCD" + b"EFGHIJ"
    co = zlib.compressobj(9, zlib.DEFLATED, 31)
    gz = co.compress(body) + co.flush()
    gz = gz[:3] + b"\x08" + gz[4:]  # set FNAME flag
    gz = gz[:10] + b"x.mrg\x00" + gz[10:]
    raw = b"junk" * 5 + b"%d CH_X.mrg\n" % len(body) + gz
    mem = list(m.iter_gz_members(raw))
    assert len(mem) == 1 and mem[0][2] == "CH_X.mrg"
    out = m.inflate_gz_member(raw, mem[0][3], mem[0][1])
    assert out == body
    info = m.parse_mrg_offsets(out)
    assert info["offsets"] == [16, 20] and info["sizes"] == [4, len(body) - 20]


def _tex2_blob():
    pal = bytes([10, 20, 30, 0x80]) * 16
    px4 = bytes([0x10] * 8)  # 4x4? use w=4,h=4 -> 8 bytes
    entry = struct.pack("<I", 0) + pal + px4 + b"\0" * 4  # 8 + 64 + 8
    off = 8 + 8
    return b"TEX2" + struct.pack("<I", 0x80000001) + struct.pack("<HHI", 4, 4, off) + entry


def test_parse_tex2_size_rule_and_decode():
    t = m.parse_tex2(_tex2_blob(), decode=True)[0]
    assert (t["w"], t["h"], t["bpp"], t["size_matches"]) == (4, 4, 4, True)
    assert t["rgba"][:4] == bytes([10, 20, 30, 255])  # alpha 0x80 -> 255
    assert t["rgba"][4:8] == bytes([10, 20, 30, 255])
    assert len(t["rgba"]) == 4 * 4 * 4


def test_parse_lnk0_meshes_and_names():
    base = 0x50
    gmb = b"GMB1" + struct.pack("<3I", 0x100, 3, 0x1C) + struct.pack("<2I", 0x40, 0x80)
    gmb = gmb.ljust(0x100, b"\0")
    d = b"LNK0" + struct.pack("<3I", 8, 0, 0) + struct.pack("<I", base)
    d = d.ljust(base, b"\0") + gmb
    names = [b"o_arm", b"o_face", b"t_kao_00_1"]
    strs, offs, cur = b"", [], 8 + 4 * 3
    for n in names:
        offs.append(cur + len(strs)); strs += n + b"\0"
    d += b"STR1" + struct.pack("<I", 3) + struct.pack("<3I", *offs) + strs
    p = m.parse_lnk0(d)
    assert p["mesh_count"] == 3 and p["names"] == ["o_arm", "o_face", "t_kao_00_1"]
    assert [x["off"] for x in p["meshes"]] == [base + 0x1C, base + 0x40, base + 0x80]


def test_parse_mrg_lst_bins_and_kind():
    sub0 = b"mrg.lst \r\na.bin\r\nb.bin\r\n_\r\nCH_X.mrg \r\n\0\0"
    assert m.parse_mrg_lst_bins(sub0) == ["a.bin", "b.bin"]
    assert m.mrg_subfile_kind(sub0) == "mrg.lst"
    assert m.mrg_subfile_kind(b"LNK0xxxx") == "LNK0"
    assert m.mrg_subfile_kind(b"TEX2xxxx") == "TEX2"


ISO = "/home/ehm_eckx/gBox_alt/gbox-cache/ps2/0b29e35386444551/disc.iso"


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned disc image not present")
def test_real_ch_aki_subfiles():
    import mmap
    with open(ISO, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for ho, us, name, go in m.iter_gz_members(mm):
            if name == "CH_AKI.mrg":
                body = m.inflate_gz_member(mm, go, us)
                break
    subs = m.split_mrg(body)
    assert [m.mrg_subfile_kind(s) for s in subs][:8] == [
        "mrg.lst", "LNK0", "TEX2", "LNK0", "TEX2", "LNK0", "LNK0", "TEX2"]
    assert m.parse_mrg_lst_bins(subs[0])[:3] == ["a.bin", "b.bin", "c.bin"]
    lnk = m.parse_lnk0(subs[1])
    assert lnk["mesh_count"] == 25 and lnk["names"][0] == "o_arm" and lnk["names"][-1] == "t_kao_03_1"
    tex = m.parse_tex2(subs[2])
    assert len(tex) == 27 and all(t["size_matches"] for t in tex[:26])
