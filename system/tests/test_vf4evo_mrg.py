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
