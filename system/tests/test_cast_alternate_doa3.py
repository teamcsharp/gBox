"""Real-data integration for mapping=alternate: the DOA3 Sonic-vs-Mario cast.

Drives the alternate mapping with the actual DOA3 roster (doa3_inventory.ROSTER) and the actual
Sonic (SA1 + SA2) and Mario (SM64 + SM64 DS, best model per character) donor pools, so the request's
acceptance criteria are checked against the real game data, not synthetic fixtures:

* 16 target slots (15 selectable fighters + the Omega boss) all get a donor;
* the two pools alternate across the roster, keeping their slot counts within one of each other (8/8);
* each pool's distinct names are exhausted before any of them repeat (both pools have >= 8 distinct,
  so the first 8 of each pool are all distinct);
* the best Mario model per character is chosen (SM64 DS over SM64, HD over both);
* the plan is deterministic for the request's seed.
"""
from collections import Counter

import pytest

from gbox import cast_swap as CS
from gbox import characters as C
from gbox import doa3_inventory as d3

SEED = "doa3-three-casts-20261015-v1-sonic_vs_mario"


def _donor(slug: str, name: str, pool: str, title: str, platform: str, game_id: str = "") -> dict:
    return {"slug": slug, "name": name, "pool": pool,
            "source": {"game_title": title, "platform": platform, "game_id": game_id},
            "lead": False, "preferred": False,
            "name_key": CS.name_key({"slug": slug, "name": name}), "size": 1.0, "preview_url": None}


def _sonic_donors() -> list[dict]:
    """Every SA2 character (not the vehicles) plus the SA1 roster, tagged pool=sonic."""
    out = []
    for key, name, _aliases, kind in C.SA2_CHARS:
        if kind != "character":
            continue
        slug = "sonic" if key == "SONIC" else f"sa2_{key.lower()}"
        out.append(_donor(slug, name, "sonic", "Sonic Adventure 2 (USA)", "dreamcast"))
    sa1 = __import__("gbox.sa1_chars", fromlist=["x"]).roster()
    for e in sa1:
        out.append(_donor(e["slug"], e["name"], "sonic", "Sonic Adventure (USA)", "dreamcast"))
    return out


def _mario_donors() -> list[dict]:
    """SM64 (decomp) + SM64 DS rosters collapsed to the best model per character, tagged pool=mario."""
    out = []
    for e in __import__("gbox.sm64_decomp", fromlist=["x"]).roster():
        out.append(_donor(e["slug"], e["name"], "mario", "Super Mario 64", "n64"))
    for e in __import__("gbox.sm64ds_chars", fromlist=["x"]).roster():
        out.append(_donor(e["slug"], e["name"], "mario", "Super Mario 64 DS (USA)", "nds"))
    keep, _superseded = CS.best_per_character(out)
    return keep


def _doa3_slots() -> list[dict]:
    """The 15 selectable fighters plus Omega, each as a fighter slot."""
    return [{"slot": f"doa3_{i}", "name": name, "kind": "fighter", "size": 1.0}
            for i, name in enumerate(d3.ROSTER)]


def _pools(donors: list[dict], out: list[dict]) -> list[str]:
    by = {d["slug"]: d["pool"] for d in donors}
    return [by[r["character"]] for r in out]


def test_doa3_sonic_vs_mario_alternates_real_pools_within_one():
    slots, donors = _doa3_slots(), _sonic_donors() + _mario_donors()
    out = CS.assign(slots, donors, "alternate", SEED)
    assert len(out) == len(d3.ROSTER) == 16
    seq = _pools(donors, out)
    assert set(seq) == {"sonic", "mario"}
    counts = Counter(seq)
    assert counts["sonic"] == counts["mario"] == 8          # 16 slots split exactly
    assert all(a != b for a, b in zip(seq, seq[1:]))        # pools alternate across the roster


def test_doa3_sonic_vs_mario_exhausts_distinct_names_before_repeating():
    slots, donors = _doa3_slots(), _sonic_donors() + _mario_donors()
    out = CS.assign(slots, donors, "alternate", SEED)
    seq = _pools(donors, out)
    by_slug = {d["slug"]: d for d in donors}
    sonic = [by_slug[r["character"]]["name_key"] for r, p in zip(out, seq) if p == "sonic"]
    mario = [by_slug[r["character"]]["name_key"] for r, p in zip(out, seq) if p == "mario"]
    assert len(sonic) == len(mario) == 8
    assert len(set(sonic)) == 8                             # 14 distinct Sonic names >= 8: no name repeats
    assert len(set(mario)) == 8                             # 26 distinct Mario names >= 8: no name repeats


def test_doa3_sonic_vs_mario_uses_best_mario_model_per_character():
    donors = _mario_donors()
    by_char = {CS.character_key(d): d["slug"] for d in donors}
    assert by_char["mario"] == "sm64ds_mario"               # SM64 DS ranks above the SM64 decomp entry
    assert by_char["peach"] == "sm64ds_peach"
    assert by_char["bowser"] == "sm64ds_bowser"
    # every distinct character appears exactly once (best model kept, dupes superseded)
    keys = [CS.character_key(d) for d in donors]
    assert len(keys) == len(set(keys))


def test_doa3_sonic_vs_mario_plan_is_deterministic():
    slots, donors = _doa3_slots(), _sonic_donors() + _mario_donors()
    assert CS.assign(slots, donors, "alternate", SEED) == CS.assign(slots, donors, "alternate", SEED)


def test_doa3_sonic_vs_mario_covers_boss_slot():
    slots, donors = _doa3_slots(), _sonic_donors() + _mario_donors()
    out = CS.assign(slots, donors, "alternate", SEED)
    by_slot = {r["slot"]: r for r in out}
    assert by_slot["doa3_15"]["slot_name"] == "Omega"       # the boss/cameo slot is inventoried and assigned
    assert by_slot["doa3_15"]["character"]                  # Omega gets a real donor, not skipped
