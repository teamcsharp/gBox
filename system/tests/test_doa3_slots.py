"""DOA3 cast slot inventory: resolved display names, hidden/boss/story slots and exact
coverage gaps, consumed from a ``doa3_inventory`` manifest.

The 20 fighter families are the real loadfile.afs layout (nick, code, complete-costume
count) pinned from the owned build; the report must resolve 16 display names, leave exactly
hika/koryu/gokei/chin pending, classify tengu/bosnin as hidden and chin as story-only, and
list the roster names no family covers yet (the three pending display names plus Omega).
"""
import json
import os

import pytest

from gbox import doa3_inventory as d3

# (nick, code, complete_costume_count) -- the owned loadfile.afs layout.
FAMILIES = [
    ("zack", "zac", 3), ("tina", "tin", 3), ("janlee", "jan", 4), ("karate", "kte", 3),
    ("ryu", "ryu", 3), ("kasumi", "kas", 10), ("genfu", "gen", 2), ("hika", "hik", 3),
    ("bayman", "bay", 3), ("bass", "bas", 4), ("ninja", "nin", 3), ("leifang", "lei", 5),
    ("ayane", "aya", 3), ("koryu", "kor", 8), ("tengu", None, 0), ("bosnin", "bni", 2),
    ("suiken", "sui", 3), ("gokei", "gok", 3), ("chin", "chi", 1), ("sambo", "sam", 3),
]

REAL_MANIFEST = "/home/ehm_eckx/gBox_alt/gbox-cache/b8edf7040116f3aa/doa3_manifest.json"


def _manifest(families=FAMILIES) -> dict:
    ff = []
    for nick, code, n in families:
        code = code or (nick[:3] if nick != "tengu" else None)
        ff.append({
            "nick": nick,
            "code": code,
            "mot": [f"{nick}.mot", f"m_{nick}.mot"],
            "complete_costumes": [f"{code or nick[:3]}{i:02d}" for i in range(n)],
            # deliberately omit display/display_pending: the report recomputes them
        })
    return {"game_id": d3.GAME_ID, "title": d3.TITLE,
            "fighter_families": ff, "roster_expected": d3.ROSTER}


def test_slot_inventory_resolves_every_family_and_reports_exact_gaps():
    inv = d3.slot_inventory(_manifest())
    assert inv["slot_count"] == 20
    assert inv["costume_total"] == 69

    by_nick = {s["nick"]: s for s in inv["slots"]}
    assert set(inv["resolved_display"]) == set(d3.FIGHTER_DISPLAY.values())
    assert inv["display_pending"] == ["chin", "gokei", "koryu"]
    assert by_nick["kasumi"]["display_name"] == "Kasumi"
    assert by_nick["karate"]["display_name"] == "Ein"
    assert by_nick["bosnin"]["display_name"] == "Genra"
    assert by_nick["sambo"]["display_name"] == "Leon"
    assert by_nick["hika"]["display_name"] == "Helena" and not by_nick["hika"]["display_pending"]
    assert by_nick["koryu"]["display_name"] is None and by_nick["koryu"]["display_pending"]
    assert by_nick["chin"]["display_name"] is None and by_nick["chin"]["display_pending"]

    # classification
    assert {s["nick"] for s in inv["slots"] if s["hidden"]} == {"tengu", "bosnin"}
    assert {s["nick"] for s in inv["slots"] if s["story_only"]} == {"chin"}
    assert by_nick["tengu"]["costume_count"] == 0

    # exact gaps: 3 pending names, tengu has no costumes, and 3 roster names are uncovered
    kinds = {}
    for g in inv["coverage_gaps"]:
        kinds.setdefault(g["kind"], []).append(g["slot"])
    assert set(kinds["display_name_pending"]) == {"koryu", "gokei", "chin"}
    assert kinds["no_complete_costumes"] == ["tengu"]
    assert set(kinds["roster_not_covered"]) == {"Hitomi", "Christie", "Omega"}


def test_slot_inventory_matches_real_owned_manifest():
    if not os.path.isfile(REAL_MANIFEST):
        pytest.skip("owned DOA3 manifest not cached")
    manifest = json.load(open(REAL_MANIFEST))
    inv = d3.slot_inventory(manifest)
    assert inv["slot_count"] == 20
    assert inv["costume_total"] == manifest["counts"]["costumes"] == 69
    assert inv["display_pending"] == ["chin", "gokei", "koryu"]
    assert len(inv["resolved_display"]) == 17
    assert {g["kind"] for g in inv["coverage_gaps"]} == {
        "display_name_pending", "no_complete_costumes", "roster_not_covered"}


def test_slot_inventory_empty_manifest_reports_only_roster_gap():
    inv = d3.slot_inventory({"game_id": d3.GAME_ID, "title": d3.TITLE,
                             "fighter_families": [], "roster_expected": d3.ROSTER})
    assert inv["slot_count"] == 0
    assert [g["kind"] for g in inv["coverage_gaps"]] == ["roster_not_covered"] * len(d3.ROSTER)
