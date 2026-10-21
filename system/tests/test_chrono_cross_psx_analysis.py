"""Static-analysis evidence for Chrono Cross (USA) Disc 1 (request #2074).

The disc-backed checks re-read the owned image (header, hash, character profiles)
and skip on hosts that do not hold it; nothing derived from the game binary is
committed. They also assert that the unlock path is still unimplemented: no writer
may run for this game.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import chrono_cross_analysis as A
from gbox import game_unlocks as G

DISC = Path("/home/ehm_eckx/.hermes/cache/scratch/cc2074/disc1.bin")
EXE = Path("/home/ehm_eckx/.hermes/cache/scratch/cc2074/SLUS_010.41")
requires_disc = pytest.mark.skipif(not DISC.exists(), reason="owned Disc 1 bin not extracted on this host")
requires_exe = pytest.mark.skipif(not EXE.exists(), reason="owned SLUS_010.41 not extracted on this host")


def _synthetic_header(pc0=0x80010008, t_addr=0x80010000, t_size=0x100, s_addr=0x801FFFF0):
    import struct
    head = bytearray(0x800)
    head[:8] = b"PS-X EXE"
    struct.pack_into("<10I", head, 0x10, pc0, 0, t_addr, t_size, 0, 0, 0, 0, s_addr, 0)
    return bytes(head) + bytes(t_size)


def test_header_fields_are_read_at_their_format_offsets():
    h = A.parse_psx_exe_header(_synthetic_header())
    assert h["magic"] == "PS"
    assert (h["pc0"], h["taddr"], h["tsize"], h["saddr"]) == (0x80010008, 0x80010000, 0x100, 0x801FFFF0)


def test_header_rejects_bad_magic_short_image_and_oversized_text():
    with pytest.raises(ValueError):
        A.parse_psx_exe_header(b"PS" + bytes(0x100))
    with pytest.raises(ValueError):
        A.parse_psx_exe_header(b"XX-X EXE" + bytes(0x1000))
    with pytest.raises(ValueError):
        A.parse_psx_exe_header(_synthetic_header()[:0x800 + 0x10])


def test_pinned_header_constants():
    assert A.EXE_PC0 == 0x80010008
    assert A.EXE_TADDR == 0x80010000
    assert A.EXE_TSIZE == 0x00093800
    assert A.EXE_SADDR == 0x801FFFF0
    assert A.EXE_GP == 0x8006CE1C
    assert A.EXE_SHA256 == "9a5453bf09d7f5c71a6451d255471374fb2d7cc5f3dfb1ea51223a5c88cdda47"


@requires_exe
def test_owned_exe_matches_the_pinned_header():
    r = A.verify_exe(EXE.read_bytes())
    assert r["matches_owned"] is True
    assert r["size"] == A.EXE_SIZE


@requires_disc
def test_character_profile_inventory_from_owned_disc():
    live = A.character_profiles(DISC.read_bytes())
    names = [p["name"] for p in live]
    assert len(live) == A.CHARACTER_PROFILE_COUNT == 51
    assert names[0] == "Silent Protagonist"
    assert "Guinea Pig Experiment" in names and "Mysterious Traveler" in names
    assert live[0]["origin"] == "Arni"
    assert live[0]["age"].startswith("17")


def test_character_profiles_reads_a_synthetic_block():
    blob = b"\x00\x00Test Hero\x00Age: 20\x00Origin: Nowhere\x00Height: 5ft\x00Weight: 9st\x00"
    out = A.character_profiles(blob)
    assert len(out) == 1 and out[0]["name"] == "Test Hero"
    assert out[0]["age"] == "20" and out[0]["origin"] == "Nowhere"


def test_unlock_is_still_not_implemented():
    # No unlock writer may run for this game: the routine is unproven.
    game = {"game_id": A.GAME_ID, "platform": "playstation"}
    profile = G.profile_for(game)
    assert profile["verified"] is False
    res = G.pre_launch(game, SimpleNamespace())
    assert res["applied"] is False
