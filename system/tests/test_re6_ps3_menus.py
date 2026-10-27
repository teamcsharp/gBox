"""RE6 (PS3, RPCS3) Mercenaries menus interface (gbox.mercs.titles.re6_ps3): interface parity with re6_x360 —
blind stage / character picks the Navigator counts, out-of-round screens unnamed until the sPlayer singleton and
menu state are measured live, and the static EBOOT anchors this run actually verified (sPlayer class name in
.rodata at 0x1413668, profile ready:false until the runtime pin)."""
import importlib
import json
import random
from pathlib import Path

import pytest

from gbox.mercs.titles import re6_ps3 as R


class Mem:
    """Guest RAM stub: raises on every read (nothing is mapped: the sPlayer singleton is not pinned)."""

    def rd(self, addr, n):
        raise ValueError(f"guest address {addr:#x} is not mapped")


def test_out_of_round_is_unknown_until_measured():
    assert R.screen(Mem()) == {"where": "unknown", "cursor": None, "target": None}
    assert R.player(Mem()) is None                  # SPLAYER unpinned: no round named, no exception
    assert R.unlocked(Mem()) is None                # PS3 save masks unmeasured
    assert R.menu_state(Mem()) is None


def test_player_none_while_singleton_unpinned():
    # SPLAYER is None this milestone: player() must short-circuit, not read guest memory.
    assert R.SPLAYER is None
    assert R.player(Mem()) is None


def test_blind_stage_pick_counts_presses():
    R.STAGE_PICK.rng = random.Random(7)
    R.STAGE_PICK.left = None
    scr = {"where": "select_stage"}
    keys = [R.step(scr) for _ in range(10)]
    assert set(keys) <= {"dright", "cross"}
    # a cross ends the visit; the count never exceeds the stage list
    for k in keys:
        R.pressed(scr, k)
    assert R.STAGE_PICK.left is None or 0 <= R.STAGE_PICK.left <= R.STAGE_PICK.MAX_MOVES


def test_blind_roster_walks_to_target_then_cross():
    R.ROSTER.rng = random.Random(3)
    R.ROSTER.pick, R.ROSTER.left = None, None
    scr = {"where": "select_player", "cursor": None, "target": R.ROSTER.want()}
    tgt = scr["target"]
    seq = []
    while True:
        k = R.step(scr)
        if k is None:
            break
        seq.append(k)
        assert k is not None
        R.pressed(scr, k)
        if k == "cross":
            break
    assert seq.count("dright") == tgt
    assert seq[-1] == "cross"


def test_cursor_from_ram_beats_blind_walking():
    scr = {"where": "select_player", "cursor": 2, "target": 2}
    assert R.step(scr) == "cross"
    scr["cursor"] = 0
    assert R.step(scr) == "dright"


def test_steps_and_boot_key():
    assert R.BOOT_KEY == "start"                    # cross on the title would take Campaign
    assert R.STEPS["results"] == "start"
    assert R.STEPS["select_stage"] == "cross"
    assert R.step({"where": "results"}) == "start"
    assert R.step({"where": "unknown"}) is None


def test_wandered_names_the_left_mode():
    assert (R.wandered({"where": "campaign"}) or "").startswith("RE6 left")
    assert R.wandered({"where": "unknown"}) is None


def test_static_anchor_lives_in_the_elf_region():
    assert R.SPLAYER_NAME_VA == 0x1413668
    elf = next(r for r in json.load(open(Path(__file__).resolve().parents[1] / "profiles/gamedata/BLUS30855-ram.json"))["regions"] if r["name"] == "elf")
    assert int(elf["base"], 16) <= R.SPLAYER_NAME_VA < int(elf["base"], 16) + int(elf["size"], 16)


def test_ram_profile_declares_driver_and_pending_state():
    prof = json.load(open(Path(__file__).resolve().parents[1] / "profiles/gamedata/BLUS30855-ram.json"))
    assert prof["id"] == "BLUS30855" and prof["platform"] == "ps3"
    assert prof["match"]["memory"] == {"address": "0x01413668", "equals": "sPlayer"}
    mercs = prof["mercs"]
    assert mercs["driver"] == "gbox.mercs.titles.re6_ps3"
    assert mercs["menus"] == "gbox.mercs.titles.re6_ps3"
    assert mercs["ready"] is False                    # runtime pin pending: never drive blind into a round


def test_roster_and_stage_lists_match_the_disc_family():
    assert len(R.STAGES) == 3
    assert len(R.CHARACTERS) == 9 and R.CHARACTERS[0] == "Leon"
