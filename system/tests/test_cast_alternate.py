"""mapping=alternate for the cast swap: alternate comma-joined source pools (e.g. ``sonic, mario``) across the
target's slots, one donor per pool per pass, keeping each pool's slot count within one of the other and dealing
each pool's distinct names before any of them repeat."""
from collections import Counter

import pytest

from gbox import cast_swap as CS

ROLES = {r: f"j_{r}" for r in ("hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand",
                               "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}
DOA2 = {"game_id": next(iter(__import__("gbox.doa2_swap", fromlist=["x"]).GAME_IDS)), "title": "Dead or Alive 2",
        "platform": "dreamcast"}


def _slot(name: str) -> dict:
    return {"slot": name, "name": name, "kind": "slot", "size": 1.0}


def _donor(slug: str, pool: str, name: str | None = None) -> dict:
    return {"slug": slug, "name": name or slug, "source": pool, "source_game_id": pool, "pool": pool,
            "lead": False, "preferred": False, "name_key": slug, "size": 1.0, "preview_url": None}


def _pools(donors: list[dict], out: list[dict]) -> list[str]:
    by = {d["slug"]: d["pool"] for d in donors}
    return [by[r["character"]] for r in out]


def test_alternate_round_robins_pools_and_keeps_counts_within_one():
    slots = [_slot(f"s{i}") for i in range(7)]
    donors = [_donor("s1", "sonic"), _donor("s2", "sonic"), _donor("s3", "sonic"),
              _donor("m1", "mario"), _donor("m2", "mario")]
    seq = _pools(donors, CS.assign(slots, donors, "alternate", "seed"))
    assert seq[0] == "sonic" and seq[1] == "mario"          # pools keep first-seen order, then alternate
    assert all(a != b for a, b in zip(seq, seq[1:]))        # adjacent slots never share a pool
    counts = Counter(seq)
    assert abs(counts["sonic"] - counts["mario"]) <= 1


def test_alternate_deals_each_pools_distinct_names_before_repeating():
    slots = [_slot(f"s{i}") for i in range(7)]
    donors = [_donor("s1", "sonic"), _donor("s2", "sonic"), _donor("s3", "sonic"),
              _donor("m1", "mario"), _donor("m2", "mario")]
    out = CS.assign(slots, donors, "alternate", "seed")
    seq = _pools(donors, out)
    used = [r["character"] for r in out]
    sonic = [c for c, p in zip(used, seq) if p == "sonic"]
    mario = [c for c, p in zip(used, seq) if p == "mario"]
    assert len(set(sonic[:3])) == 3                         # s1/s2/s3 all dealt before any repeat
    assert sonic[3] in sonic[:3]                            # the fourth sonic slot repeats a name
    assert mario[0] != mario[1] and mario[2] in mario[:2]


def test_alternate_is_deterministic_for_a_seed():
    slots = [_slot(f"s{i}") for i in range(8)]
    donors = [_donor("s1", "sonic"), _donor("s2", "sonic"), _donor("m1", "mario"), _donor("m2", "mario")]
    assert CS.assign(slots, donors, "alternate", "k") == CS.assign(slots, donors, "alternate", "k")


def test_unknown_mapping_still_rejected():
    with pytest.raises(ValueError):
        CS.assign([_slot("p")], [_donor("d", "x")], "not_a_mapping", "")


def _entry(slug, name, title, plat, gid, group=None, quality=None):
    meta = {"slug": slug, "name": name, "kind": "character", "model": f"{slug}.glb", "aliases": [],
            "rig": {"roles": ROLES}, "stats": {"triangles": 500, "textures": 1},
            "readiness": {"status": "ready"},
            "source": {"game_title": title, "platform": plat, "game_id": gid}}
    if group:
        meta["donor_group"] = group
    if quality:
        meta["donor_quality"] = quality
    return meta


def _chars():
    return [
        _entry("sa2_sonic", "Sonic", "Sonic Adventure 2 (USA)", "dreamcast", "5a20000000000000"),
        _entry("sa2_shadow", "Shadow", "Sonic Adventure 2 (USA)", "dreamcast", "5a20000000000000"),
        _entry("sa2_knuckles", "Knuckles", "Sonic Adventure 2 (USA)", "dreamcast", "5a20000000000000"),
        _entry("mario_hd", "Mario (HD)", "Render96 ModelPack (Super Mario 64 HD models)", "", None,
               group="mario", quality="hd"),
        _entry("luigi_hd", "Luigi (HD)", "Render96 ModelPack (Super Mario 64 HD models)", "", None,
               group="mario", quality="hd"),
        _entry("sm64ds_mario", "Mario (DS)", "Super Mario 64 DS (USA)", "nds", "917483267d246594", group="mario"),
    ]


def test_plan_sonic_vs_mario_alternates_pools_and_uses_best_mario_models():
    p = CS.plan(DOA2, _chars(), "sonic, mario", mapping="alternate", seed="1")
    assert p["status"] == "planned"
    pool = {r["slug"]: r["pool"] for r in p["donors"]}
    assert set(pool.values()) == {"sonic", "mario"}
    used = {r["character"] for r in p["assignments"]}
    assert "mario_hd" in used and "sm64ds_mario" not in used       # best Mario model per character, not the DS one
    seq = [pool[r["character"]] for r in p["assignments"]]
    counts = Counter(seq)
    assert abs(counts["sonic"] - counts["mario"]) <= 1
    assert p == CS.plan(DOA2, _chars(), "sonic, mario", mapping="alternate", seed="1")   # deterministic
