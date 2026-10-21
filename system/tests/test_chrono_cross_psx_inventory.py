"""Pinned source-inventory tests for Chrono Cross (USA) Disc 1 (request #2074).

These pin the owned-disc evidence only. No unlock write path exists for this
game yet and none of these tests may create one.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gbox import chrono_cross_psx as CC
from gbox import game_unlocks as G

BIN = Path("/home/ehm_eckx/.hermes/cache/scratch/cc2074/disc1.bin")

pytestmark = pytest.mark.skipif(not BIN.exists(),
                                reason="owned Disc 1 bin not extracted on this host")


def _exe_bytes():
    from gbox.psxdisc import RawBin
    rb = RawBin(str(BIN), writable=False)
    try:
        return rb.read(CC.EXE_NAME)
    finally:
        rb.close()


def test_pinned_exe_hash_matches_owned_disc():
    result = CC.verify_exe(_exe_bytes())
    assert result["matches_owned"] is True
    assert result["sha256"] == CC.EXE_SHA256
    assert result["size"] == CC.EXE_SIZE
    # Real PS-X EXE header fields.
    assert result["pc0"] == 0x80010008      # entry point
    assert result["taddr"] == 0x80010000   # text load address
    assert result["tsize"] == 0x00093800   # text length (604160 bytes)
    assert result["saddr"] == 0x801FFFF0   # stack top
    assert result["gp"] == 0x8006CE1C      # $gp recovered from the crt0


def test_inventory_manifest_shape():
    man = CC.inventory(str(BIN))
    assert man["game_id"] == "357b4ff44f7a2a68"
    assert man["chd_sha256"] == CC.CHD_SHA256
    assert man["iso9660"]["count"] == 2
    assert man["iso9660"]["boot"] == "SLUS_010.41"
    assert {e["name"] for e in man["iso9660"]["entries"]} == {"SLUS_010.41", "SYSTEM.CNF"}
    assert man["exe"]["matches_owned"] is True


def test_rejects_truncated_exe():
    with pytest.raises(ValueError):
        CC.verify_exe(b"PS" + bytes(0x100))
    from gbox.psxdisc import RawBin
    rb = RawBin(str(BIN), writable=False)
    try:
        exe = bytearray(rb.read(CC.EXE_NAME))
    finally:
        rb.close()
    exe[0:2] = b"XX"
    with pytest.raises(ValueError):
        CC.verify_exe(bytes(exe))


def test_profile_stays_research_pending_and_hook_never_writes(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("unlock writer must not run for research_pending game")
    from gbox import re6_tool
    monkeypatch.setattr(re6_tool, "pre_launch", fail)
    game = {"game_id": "357b4ff44f7a2a68", "platform": "playstation"}
    profile = G.profile_for(game)
    assert profile["verified"] is False and profile["status"] == "unsupported"
    from types import SimpleNamespace
    result = G.pre_launch(game, SimpleNamespace())
    assert result["applied"] is False and result["state"] == "research_pending"
