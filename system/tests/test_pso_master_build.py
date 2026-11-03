"""Master-build layer: codes are real 3-byte items, templates/mag distribution are
valid, and the entry point is fail-soft (never raises) and idempotent on live RAM."""
import struct

import pytest

from gbox import pso_master_build as MB
from gbox import pso_gc_live as G
from test_pso_gc_live import RAM


def test_item_codes_are_well_formed_three_byte_codes():
    assert all(MB._is_hex3(c) for c in MB.WEAPON_CODES)
    assert all(MB._is_hex3(c) for c in MB.UNIT_CODES)
    assert MB._is_hex3(MB.FRAME_CODE) and MB._is_hex3(MB.MAG_CODE)
    # family prefixes match gbox.psoitems: weapon 00, frame 0101, unit 0103, mag 02
    assert all(c.startswith("00") for c in MB.WEAPON_CODES)
    assert MB.FRAME_CODE.startswith("0101")
    assert all(c.startswith("0103") for c in MB.UNIT_CODES)
    assert MB.MAG_CODE.startswith("02")
    assert len(MB.WEAPON_CODES) >= 4 and len(MB.UNIT_CODES) >= MB.UNIT_SLOTS


def test_frame_template_carries_code_slots_and_id():
    item = MB.frame_template("010100", 4, 0x00F00042)
    assert len(item) == 20
    assert item[:3] == bytes.fromhex("010100")
    assert item[4] == 4                                   # four unit slots (data1[4])
    assert struct.unpack_from(">I", item, 12)[0] == 0x00F00042
    # a lower slot request is honoured and bounded to a byte
    assert MB.frame_template("010100", 1, 0)[4] == 1


def test_mag_distribution_is_maxed_random_and_within_caps():
    import random
    for seed in range(20):
        ch = MB.mag_max_changes(random.Random(seed))
        assert ch["def"] + ch["pow"] + ch["dex"] + ch["mind"] == MB.MAG_TOTAL
        assert all(0 <= ch[k] <= 200 for k in ("def", "pow", "dex", "mind"))
        assert ch["iq"] == 200 and ch["synchro"] == MB.MAG_SYNCHRO
        assert 0 <= ch["color"] < MB.MAG_COLORS
    # the distribution actually varies between seeds (it is random, not fixed)
    a = MB.mag_max_changes(random.Random(1))
    b = MB.mag_max_changes(random.Random(2))
    assert (a["def"], a["pow"], a["dex"], a["mind"]) != (b["def"], b["pow"], b["dex"], b["mind"])


def test_apply_is_fail_soft_on_a_blank_or_wrong_game_and_never_writes():
    class Blank:
        def __init__(self):
            self.writes = []

        def read_memory(self, address, length):
            return b"\0" * length

        def write_memory(self, address, data):
            self.writes.append((address, data))
    ad = Blank()
    report = MB.apply_master_build(ad)                    # wrong disc -> every feature fails soft
    assert isinstance(report, dict)
    assert report["ok"] is False
    assert report["errors"]                               # at least the player/accuracy guards tripped
    assert ad.writes == []                                # nothing poked into a non-PSO game


def test_apply_does_not_raise_when_globals_apply_but_player_build_cannot(monkeypatch):
    # A correctly fingerprinted, hooked game with accuracy guards present, but the
    # native command queue is faked out, so the real item/stat work no-ops safely.
    from gbox import pso_accuracy as A, pso_gc_extras as E, pso_gc_adventure as D
    ram = RAM()
    for a, b in A.GUARDS.items():
        ram.put(a, b)
    for a, _, _, original in A.SITES:
        ram.put(a, original)
    for a, b in E.EXTRA_GUARDS.items():
        ram.put(a, b)
    ram.query_runtime = lambda: {"state": "RUNNING"}
    # the local player must look initialised for check()
    ram.word(ram.player + 0x1C, 0)
    monkeypatch.setattr(G.GC, "call", lambda self, calls, timeout=2: [0] * len(calls))
    report = MB.apply_master_build(ram)
    assert isinstance(report, dict) and "errors" in report
    # never-miss and equip-anything are player-independent and should have applied
    assert report.get("never_miss") is True
    assert report.get("equip_any") is True


def test_state_is_tracked_per_player_and_apply_all_covers_both():
    # On a wrong-disc adapter every player fails soft before any state is created.
    class Blank:
        def read_memory(self, address, length):
            return b"\0" * length

        def write_memory(self, address, data):
            pass
    ad = Blank()
    out = MB.apply_master_build_all(ad)
    assert set(out) == {0, 1}
    assert out[0]["player_index"] == 0 and out[1]["player_index"] == 1
    assert out[0]["ok"] is False and out[1]["ok"] is False
    assert getattr(ad, "_master_build_state", {}) == {}      # no state for a non-PSO game

    # The per-player state helper keys independently once a player is valid.
    class Live:
        def read_memory(self, address, length):
            return b"\0" * length
    live = Live()
    MB._state(live, 0)["weapon_id"] = 0xF00001
    MB._state(live, 1)["weapon_id"] = 0xF00002
    assert MB._state(live, 0)["weapon_id"] != MB._state(live, 1)["weapon_id"]


def test_notes_document_the_outstanding_re_work():
    for key in ("never_miss", "crit_rate", "crit_always_todo", "attack_speed_todo"):
        assert key in MB.MASTER_BUILD_NOTES and MB.MASTER_BUILD_NOTES[key]
    # never-miss now covers both players; the P1-only caveat is gone.
    assert "slot 1" in MB.MASTER_BUILD_NOTES["never_miss"]
