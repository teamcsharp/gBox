"""DOA2 LE JP character asset readers (gbox.doa2_chars): CHR/SUP/MOT container facts.

The fixture is synthetic (hash-anchored constants from the owned disc's DOA2/KAS00.CHR,
sha256 63a67aa37da73d09e795c7e14b6ad39ed533ef6adeb7cd17787d749c7ae5dcee) so the test runs without
the disc; export() against the real GDI is exercised on the control-plane node.
"""
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import doa2_chars


def synth_chr(n_obj=3, n_bone=2, base=0x0C300000, scale=(0.18116, 0.01111, 0.1796)):
    """A minimal CHR with the verified layout. Object 0 begins at file offset 0 (the 24-byte
    header is object 0's leading words, as on the real disc), objects 1.. follow."""
    tail_off = 24 + 200                       # header + objects 1,2 bodies
    a_off = tail_off + 12 * n_bone
    objs = [0, 24 + 40, 24 + 104]             # file offsets: object 0 at 0
    total = a_off + 4 * n_obj
    b = bytearray(total)
    struct.pack_into("<9I", b, 0, 24, a_off, tail_off, n_obj, n_bone, 0, 1, 1, 0)
    struct.pack_into("<3f", b, 0x24, *scale)
    for i in (1, 2):
        struct.pack_into("<I", b, objs[i], 0x11 * i)                  # object body marker
    for i, o in enumerate(objs):
        struct.pack_into("<I", b, a_off + 4 * i, base + o)            # absolute SH-4 pointers
    for i in range(n_bone):
        struct.pack_into("<3f", b, tail_off + 12 * i, 0.1 * i, 0.0, 0.05 * i)
    return bytes(b)


def synth_sup():
    b = bytearray(68)
    struct.pack_into("<II", b, 0, 44, 60)
    struct.pack_into("<6f", b, 44, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    struct.pack_into("<2f", b, 60, 0.5, 0.25)                         # last record runs to EOF
    return bytes(b)


def synth_mot():
    offs = [0x1898, 0x1c5c, 0x1898]
    b = bytearray(0x40)
    struct.pack_into("<3I", b, 0, *offs)
    return bytes(b) + b"\0" * 0x2000


class TestParseChr:
    def test_kasumi_like_header(self):
        r = doa2_chars.parse_chr(synth_chr())
        assert r["n_objects"] == 3 and r["n_bones"] == 2
        assert r["ptr_base"] == 0x0C300000
        assert r["objects"] == [0, 64, 128]                            # object 0 = the header itself
        assert r["header_floats"] == pytest.approx([0.18116, 0.01111, 0.1796], abs=1e-4)
        assert r["tail"][1] == pytest.approx((0.1, 0.0, 0.05), abs=1e-4)

    def test_system_chr_base(self):
        r = doa2_chars.parse_chr(synth_chr(base=0x0C400000))
        assert r["ptr_base"] == 0x0C400000

    def test_rejects_bad_header(self):
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(b"\x00" * 64)
        bad = bytearray(synth_chr())
        struct.pack_into("<I", bad, 0, 32)                    # header size must be 24
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(bytes(bad))
        bad = bytearray(synth_chr())
        struct.pack_into("<I", bad, 12, 0x9999)               # implausible object count
        with pytest.raises(ValueError):
            doa2_chars.parse_chr(bytes(bad))

    def test_real_disc_anchors(self):
        # disc-anchored regression: the real KAS00.CHR header words (offsets 0..0x2c)
        hdr = struct.unpack("<12I", bytes.fromhex(
            "18000000" "d8790400" "b87a0400" "38000000" "37000000" "00000000"
            "01000000" "01000000" "00000000" "4283393e" "f4f5353c" "40e8373e"))
        assert hdr[0] == 24 and hdr[3] == 56 and hdr[4] == 55      # Kasumi: 56 objects, 55 bones
        assert hdr[1] == 0x479D8 and hdr[2] == 0x47AB8


class TestParseSupMot:
    def test_sup_records(self):
        r = doa2_chars.parse_sup(synth_sup())
        assert r["n_records"] == 2
        assert r["records"][0][:3] == pytest.approx([0.0, 0.0, 1.0])
        assert r["records"][1] == pytest.approx([0.5, 0.25])

    def test_mot_table(self):
        r = doa2_chars.parse_mot_table(synth_mot())
        assert r["n_clips"] == 3
        assert r["offsets"][0] == 0x1898 and r["offsets"][2] == 0x1898   # shared clip


class TestRoster:
    def test_static_roster_shape(self):
        r = doa2_chars.roster()
        kas = next(e for e in r if e["key"] == "KAS")
        assert kas["name"] == "Kasumi" and kas["slug"] == "doa2_kas"
        assert {e["key"] for e in r} >= {"KAS", "AYA", "TIN", "RYU", "TNG"}

    def test_disc_listing_costumes(self):
        files = {"DOA2/KAS00.CHR": 1, "DOA2/KAS09.CHR": 1, "DOA2/AYA00.CHR": 1, "DOA2/STAGE01.CHR": 1,
                 "DOA2/EFC0.CHR": 1, "DOA2/KAS00.SUP": 1, "DOA2/KAS00.BIN": 1}
        r = doa2_chars.roster(files)
        kas = next(e for e in r if e["key"] == "KAS")
        assert kas["costumes"] == ["00", "09"]                       # disc zero-padded costume ids
        aya = next(e for e in r if e["key"] == "AYA")
        assert aya["costumes"] == ["00"]
        assert not any(e["key"] == "STAGE" for e in r)


class TestGameIds:
    def test_routes_only_doa2le(self):
        assert "1de2e7634f3161ff" in doa2_chars.GAME_IDS
        assert len(doa2_chars.GAME_IDS) == 1


def test_module_documented_facts():
    doc = doa2_chars.__doc__ or ""
    assert "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1" in doc   # 1ST_READ hash
    assert "0x0C300000" in doc and "0x0C400000" in doc                                # pointer bases
