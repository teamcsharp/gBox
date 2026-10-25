"""Focused check for the THPS4 (GameCube) unlock research artifact.

Proves the recorded finding is reproducible and self-consistent:
  * the owned THPS4 ISO really is a GameCube image with game id GT4E,
  * the mirrored Gecko database (the source Dolphin 'Download Codes' uses) has no
    THPS4 code list, while the sibling THPS3 list is served by the same endpoint,
  * the local cheatdb mirror carries no THPS4 entry either.

Read-only: opens the owned ISO header and the probe artifact, never writes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parent.parent / "research" / "thps4-gecko-probe.json"
ISO = Path("/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Tony Hawk's Pro Skater 4 (USA).nkit.iso")
GECKO_DB = Path("/home/ehm_eckx/gBox/system/gbox-data/cheatdb/gecko")


@pytest.fixture(scope="module")
def probe() -> dict:
    return json.loads(PROBE.read_text(encoding="utf-8"))


def test_probe_artifact_shape(probe: dict) -> None:
    assert probe["request"].startswith("#2287")
    assert probe["status"] == "research_pending"
    assert probe["verified"] is False
    assert probe["game"]["game_id"] == "GT4E"
    assert probe["game"]["platform"] == "gamecube"
    assert probe["blocker"] and probe["next_acceptance_step"]


def test_owned_iso_is_gamecube_gt4e() -> None:
    if not ISO.exists():
        pytest.skip(f"owned ISO not mounted: {ISO}")
    head = ISO.open("rb").read(0x60)
    assert head[0x1C:0x20] == bytes.fromhex("c2339f3d"), "GameCube ISO magic"
    assert head[0:4] == b"GT4E", "game id"
    assert b"Tony Hawk" in head[0x20:0x60], "volume title"


def test_no_thps4_gecko_list_in_mirror(probe: dict) -> None:
    """Every probed THPS4 disc id is a miss; the THPS3 control is a hit."""
    thps4 = probe["probes"]["thps4_disc_ids"]
    assert thps4, "no THPS4 disc id probed"
    for entry in thps4:
        assert entry["gid"].startswith("GT4E")
        assert entry["http"] == 404, f"{entry['gid']} unexpectedly served"
    control = probe["probes"]["control_thps3"]
    assert control["gid"] == "GT3E52"
    assert control["http"] == 200
    assert control["bytes"] > 0


def test_local_cheatdb_has_no_thps4_entry() -> None:
    if not GECKO_DB.is_dir():
        pytest.skip(f"cheatdb mirror not mounted: {GECKO_DB}")
    names = {p.name for p in GECKO_DB.glob("*.txt")}
    assert "GT3E52.txt" in names, "sibling THPS3 list missing from the mirror"
    assert not [n for n in names if n.startswith("GT4E")], "unexpected THPS4 gecko list"
