"""Tests for gbox.nfl2k2_analysis - stage-2 format probes against the owned
NFL 2K2 (USA) GD-ROM (CHD 7d4b3c49..., unpacked to ~/gBox_alt/gbox-cache/dc/373a463aa1f96e35).

Every assertion encodes a fact OBSERVED on this build (see the module
docstring); these tests would fail if the disc cache is missing or if a
future run changes the validated hypotheses.
"""
import struct

import pytest

from gbox.nfl2k2_analysis import (
    analyze_disc, find_anim_records, gdfs_layout_probe, gdfs_record_ranges,
    scne_header, scne_type_tags, sprt_header, vqcb_header,
    SCNE_F12_DELTA, SCNE_F4_TAIL, SCNE_F8_CONST, SCNE_SNE2_COUNT,
    SPRT_F12_CONST,
)
from gbox.nfl2k2_inventory import CACHE_DIR, Disc, gd_dir

GDI = CACHE_DIR / "disc.gdi"


@pytest.fixture(scope="module")
def disc():
    if not GDI.exists():
        pytest.skip("disc cache not present")
    return Disc(GDI)


@pytest.fixture(scope="module")
def summary(disc):
    return analyze_disc(GDI)


@pytest.fixture(scope="module")
def pcg0(disc):
    lba, size = disc.g.files["PCG0.IFF"]
    return disc._read_range(lba, size)


# --- SCNE (player geometry) -------------------------------------------------

def test_scne_pcg_header_invariants(summary):
    assert len(summary["scne"]) == 10
    for h in summary["scne"]:
        assert h["magic"] == "SCNE"
        assert h["f8"] == SCNE_F8_CONST          # constant object-table marker
        assert h["f4_tail"] == SCNE_F4_TAIL      # TXTR block sits 472B before EOF
        assert h["f12_delta"] in SCNE_F12_DELTA  # f12 = fsize + 77511/77560
        assert h["sub"] == "SNE2"
        assert h["sne2_count"] == SCNE_SNE2_COUNT
        assert h["table_first"] < h["f4"]        # first data chunk precedes TXTR


def test_scne_pcg0_tail_txtr_block(pcg0, summary):
    h = summary["scne"][0]  # PCG0
    assert b"TXTR" in pcg0[h["f4"]:h["f4"] + 128]   # trailing block is TXTR
    assert b"players" in pcg0[h["f4"]:h["f4"] + 128]


def test_scne_pcg0_type_tables(pcg0, summary):
    h = summary["scne"][0]
    tags = scne_type_tags(pcg0, h["table_first"], h["f4"])
    doubles = [t for t in tags if t["tag"] == "DOUBLE"]
    assert len(doubles) >= 4
    # first chunk at table_first holds float-like mesh data, then type tables
    assert tags[0]["off"] > h["table_first"]


# --- gdFs .DIR/.DAT record semantics ----------------------------------------

def test_gdfs_layout_end_relative_wins(summary):
    # exact per-pair observations on this build; the few A-violations are the
    # chain-terminal/anomalous records reported via a_anomalies (reader stage
    # resolves them), while B would duplicate hundreds of GB across the DAT.
    expected_violations = {"PLAYERS": 2, "FACES": 1, "TEAMS": 1, "PORT": 1,
                           "CHAT": 1, "AUDIO": 1}
    expected_adj = {"PLAYERS": 3960, "FACES": 273, "TEAMS": 86, "PORT": 1907,
                    "CHAT": 1069, "AUDIO": 7945}
    for p in summary["gdfs"]:
        dat = p["dat_size"]
        assert p["A_end_relative"]["violations"] == expected_violations[p["pair"]]
        assert p["A_end_relative"]["total"] <= dat
        assert len(p["a_anomalies"]) == expected_violations[p["pair"]]
        if p["pair"] == "PLAYERS":
            assert p["B_off_start"]["total"] > 10 * dat
        adj = p["contiguous_ascending"] + p["contiguous_descending"]
        assert adj == expected_adj[p["pair"]]


def test_gdfs_players_geometry_records(summary, disc):
    p = next(x for x in summary["gdfs"] if x["pair"] == "PLAYERS")
    dirb = disc.read("PLAYERS.DIR")
    res = gd_dir(dirb)
    recs = res["records"]
    assert len(recs) == 5941
    assert p["dir_version"] == 2
    # every part size is a multiple of 32 (VQ/vertex-block granularity)
    assert all(r["x"] % 32 == 0 for r in recs)
    # 1980 players x 3 parts: the cumulative-end recurrence holds exactly
    assert p["contiguous_ascending"] == 3960
    ranges, violations = gdfs_record_ranges(recs, p["dat_size"])
    # exactly 2 records are group-terminal quirks (x > size); see a_anomalies
    assert violations == 2
    assert ranges[0] == (45785152 - 5408, 45785152)


def test_gdfs_faces_descending_pack(summary, disc):
    p = next(x for x in summary["gdfs"] if x["pair"] == "FACES")
    dirb = disc.read("FACES.DIR")
    recs = gd_dir(dirb)["records"]
    assert len(recs) == 274
    ranges, violations = gdfs_record_ranges(recs, p["dat_size"])
    # 273 records pack descending; the terminal record (size == 0) is the
    # chain's start marker -> the chain truly ends at [0, 3104]
    assert violations == 1
    assert recs[-1]["size"] == 0
    assert ranges[0] == (847392 - 3104, 847392)
    assert ranges[0][0] == ranges[1][1]


def test_gdfs_audio_chat_id_fields(summary, disc):
    audio = next(x for x in summary["gdfs"] if x["pair"] == "AUDIO")
    chat = next(x for x in summary["gdfs"] if x["pair"] == "CHAT")
    assert audio["dir_version"] == 1
    recs = gd_dir(disc.read("AUDIO.DIR"))["records"]
    # 'off' is an opaque ID (10001..), not a byte offset
    assert recs[0]["off"] == 10001 and recs[1]["off"] == 10002
    assert chat["names"] == 1070  # v0 keeps the name block


# --- SPRT / VQCB ------------------------------------------------------------

def test_sprt_letters_codebook_layout(summary, disc):
    s = next(x for x in summary["sprt"] if x["file"] == "H00.IFF")
    assert s["name"] == "letters"
    # 16-byte-per-entry VQ codebook: table [0x28, f4), index stream at f4
    assert s["f4"] == 0x28 + 16 * s["f8"]
    assert s["f8"] % 2 == 1  # n*256+1 entry-count pattern
    assert s["f12"] == SPRT_F12_CONST
    data = disc.read("H00.IFF")
    codebook = data[0x28:s["f4"]]
    assert len(codebook) == 16 * s["f8"]
    # 16bpp-ish light pixels (0xFDDD) appear in the codebook words
    assert codebook.count(b"\xdd\xfd") >= 8


def test_sprt_uniform_banks_share_f12(summary):
    for s in summary["sprt"]:
        assert s["magic"] == "SPRT"
        assert s["f12"] == SPRT_F12_CONST  # constant across H00/A00/H05
        assert s["f8"] % 2 == 1


def test_vqcb_coach_header(summary, disc):
    v = summary["vqcb"][0]
    assert v == {"file": "C00.IFF", "magic": "VQCB", "f4": 0x7FE, "f8": 0xA02,
                 "f12": 0x808, "name": "c001555"}
    data = disc.read("C00.IFF")
    assert vqcb_header(data)["name"] == "c001555"
    assert sprt_header(b"SPRTxxxx") == {}  # magic guard


# --- motion container -------------------------------------------------------

def test_gamedata_anim_records(summary, disc):
    assert summary["gamedata"]["name"] == "catch"
    assert summary["gamedata"]["magic"] == "SCNE"
    anims = summary["anim"]
    assert len(anims) >= 5
    first = anims[0]
    assert first["tag"] == "ANIM"
    assert first["a"] == 0x4FC and first["b"] == 0xA02 and first["c"] == 0x8C0
    assert first["name"].startswith("actionreplay")
    # reproducible: same records re-derived from the raw bytes
    lba, size = disc.g.files["GAMEDATA.IFF"]
    again = find_anim_records(disc._read_range(lba, size))
    assert [a["off"] for a in again] == [a["off"] for a in anims]


def test_scne_header_guards():
    assert scne_header(b"") == {}
    assert scne_header(b"NOTS" + b"\x00" * 28) == {}


# --- synthetic (no disc needed) ---------------------------------------------

def test_synthetic_headers():
    scne = b"SCNE" + struct.pack("<3I", 0x100, SCNE_F8_CONST, 0x200) + b"pl\0\0\0\0\0\0" + b"SNE2"
    scne += struct.pack("<I", 1) + struct.pack("<I", 0x40)
    h = scne_header(scne)
    assert h["name"] == "pl" and h["sub"] == "SNE2" and h["sne2_count"] == 1 and h["table_first"] == 0x40
    assert scne_header(scne[:31]) == {}
    sp = b"SPRT" + struct.pack("<3I", 0x38, 1, SPRT_F12_CONST) + b"letters\0"
    assert sprt_header(sp) == {"magic": "SPRT", "f4": 0x38, "f8": 1, "f12": SPRT_F12_CONST, "name": "letters"}
    assert sprt_header(sp[:23]) == {}
    vq = b"VQCB" + struct.pack("<3I", 0x7FE, 0xA02, 0x808) + b"c001555\0"
    assert vqcb_header(vq)["name"] == "c001555" and vqcb_header(vq[:20]) == {}


def test_synthetic_gdfs_end_relative_layout():
    # ascending pack: three 32-byte parts ending at 32, 64, 96 in a 96-byte DAT
    recs = [{"off": 10001 + i, "x": 32, "size": 32 * (i + 1)} for i in range(3)]
    ranges, bad = gdfs_record_ranges(recs, 96)
    assert ranges == [(0, 32), (32, 64), (64, 96)] and bad == 0
    p = gdfs_layout_probe(recs, 96)
    assert p["A_end_relative"] == {"violations": 0, "total": 96}
    assert p["B_off_start"]["violations"] == 3 and p["contiguous_ascending"] == 2
    # a terminal record whose x exceeds its end is reported, not clamped
    ranges, bad = gdfs_record_ranges(recs + [{"off": 0, "x": 64, "size": 0}], 96)
    assert bad == 1 and ranges[-1] == (-1, -1)


def test_synthetic_anim_records_and_type_tags():
    blob = b"\0" * 8 + b"ANIM" + struct.pack("<3I", 0x4FC, 0xA02, 0x8C0) + b"actionreplay\0" + b"\0" * 20
    blob += b"DOUBLE" + b"ANIM"  # trailing ANIM too short for a record
    recs = find_anim_records(blob)
    assert len(recs) == 1 and recs[0]["off"] == 8 and recs[0]["name"] == "actionreplay"
    assert [t["tag"] for t in scne_type_tags(blob, 0, len(blob))] == ["ANIM", "DOUBLE", "ANIM"]
