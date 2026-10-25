"""Focused unit tests for the DOA2 parry reflex layer (gbox.fightbot.titles.doa2_dc.ParryReflex).

Verifies that each attack class maps to the correct HOLDS key sequence for both P1-on-left and
P1-on-right, that unknown classes fall back to the book, and that the full step() lifecycle
(press → hold → release → judge → record) works with a mock rd/send.
"""
import struct

import pytest

from gbox.fightbot.titles.doa2_dc import (
    PARRY_HIGH, PARRY_LOW, PARRY_MID_K, PARRY_MID_P,
    HOLDS, ParryReflex, parry_holds,
)


def _mock_rd(warn_val, hp1, hp2):
    """Return a callable rd(address, length) that returns warn for the warn address
    and packed HP values for the HP addresses."""
    def rd(addr, length):
        if addr == 0x8C23A37D:
            return bytes([warn_val])
        if addr == 0x8C2376D8:
            return struct.pack("<H", hp1)
        if addr == 0x8C237740:
            return struct.pack("<H", hp2)
        return bytes(length)
    return rd


def _make_reflex(warn_val=1, hp1=200, hp2=200, side=1, cls=None):
    """Build a ParryReflex with mock rd/send, optionally setting the attack class."""
    sent = []
    def send(rows):
        sent.append(rows)
    stats = {}
    r = ParryReflex(_mock_rd(warn_val, hp1, hp2), send, stats, side=side)
    r.sent = sent
    if cls is not None:
        r.set_attack_class(cls)
    return r


def test_parry_table_left_side():
    """P1 on the left: back = left; high → up+left, mid punch → left, mid kick → right, low → down+left."""
    table = parry_holds(side=1)
    assert table[PARRY_HIGH] == ("up", "left")
    assert table[PARRY_MID_P] == ("left",)
    assert table[PARRY_MID_K] == ("right",)
    assert table[PARRY_LOW] == ("down", "left")


def test_parry_table_right_side():
    """P1 on the right: back = right; horizontal mirrors."""
    table = parry_holds(side=2)
    assert table[PARRY_HIGH] == ("up", "right")
    assert table[PARRY_MID_P] == ("right",)
    assert table[PARRY_MID_K] == ("left",)
    assert table[PARRY_LOW] == ("down", "right")


def test_parry_table_entries_are_valid_holds():
    """Every parry-table entry must be a tuple present in HOLDS."""
    for side in (1, 2):
        table = parry_holds(side=side)
        for cls, hold in table.items():
            assert hold in HOLDS, f"side={side} cls={cls} hold={hold} not in HOLDS"


def test_high_parry_sends_up_and_back():
    """On the warn edge with class=high, the reflex sends guard+up+back (left side)."""
    r = _make_reflex(warn_val=1, cls=PARRY_HIGH)
    # Edge: warn=1, prev=0 → press
    r.step(0.0)
    assert r.sent, "no keys sent on warn edge"
    down = {row["key"]: row["down"] for row in r.sent[0]}
    # guard (Free = "a"), up, left all down
    assert down.get("a") is True
    assert down.get("up") is True
    assert down.get("left") is True


def test_mid_punch_parry_sends_back():
    """On the warn edge with class=mid_punch, the reflex sends guard+back only (left side)."""
    r = _make_reflex(warn_val=1, cls=PARRY_MID_P)
    r.step(0.0)
    assert r.sent
    down = {row["key"]: row["down"] for row in r.sent[0]}
    assert down.get("a") is True
    assert down.get("left") is True
    assert down.get("right") is not True
    assert down.get("up") is not True
    assert down.get("down") is not True


def test_mid_kick_parry_sends_forward():
    """On the warn edge with class=mid_kick, the reflex sends guard+forward only (left side)."""
    r = _make_reflex(warn_val=1, cls=PARRY_MID_K)
    r.step(0.0)
    assert r.sent
    down = {row["key"]: row["down"] for row in r.sent[0]}
    assert down.get("a") is True
    assert down.get("right") is True
    assert down.get("left") is not True


def test_low_parry_sends_down_and_back():
    """On the warn edge with class=low, the reflex sends guard+down+back (left side)."""
    r = _make_reflex(warn_val=1, cls=PARRY_LOW)
    r.step(0.0)
    assert r.sent
    down = {row["key"]: row["down"] for row in r.sent[0]}
    assert down.get("a") is True
    assert down.get("down") is True
    assert down.get("left") is True


def test_right_side_high_parry_mirrors():
    """P1 on the right: high parry sends up+right (not up+left)."""
    r = _make_reflex(warn_val=1, cls=PARRY_HIGH, side=2)
    r.step(0.0)
    assert r.sent
    down = {row["key"]: row["down"] for row in r.sent[0]}
    assert down.get("a") is True
    assert down.get("up") is True
    assert down.get("right") is True
    assert down.get("left") is not True


def test_no_warn_sends_nothing():
    """No warn edge → no keys sent."""
    r = _make_reflex(warn_val=0, cls=PARRY_HIGH)
    r.step(0.0)
    assert not r.sent, "keys sent despite no warn"


def test_holds_released_after_hold_s():
    """After the hold expires, the reflex releases the keys."""
    r = _make_reflex(warn_val=1, cls=PARRY_HIGH)
    r.step(0.0)       # press at t=0, hold_s=0.1
    assert r.sent and r.sent[0][0]["down"] is True
    # Step well past hold_s (0.1 s) → release
    r2 = _make_reflex(warn_val=0, cls=PARRY_HIGH)  # warn drops
    r2.set_attack_class(PARRY_HIGH)
    # Reconstruct: press, then release
    sent = []
    def send2(rows):
        sent.append(rows)
    stats = {}
    # Use a custom rd that returns warn=1 then warn=0
    call_count = {"n": 0}
    def rd_seq(addr, length):
        call_count["n"] += 1
        if addr == 0x8C23A37D:
            return bytes([1 if call_count["n"] == 1 else 0])
        if addr == 0x8C2376D8:
            return struct.pack("<H", 200)
        if addr == 0x8C237740:
            return struct.pack("<H", 200)
        return bytes(length)
    r3 = ParryReflex(rd_seq, send2, stats, side=1)
    r3.set_attack_class(PARRY_HIGH)
    r3.step(0.0)       # press (warn=1)
    press_rows = sent[0]
    assert any(row["down"] for row in press_rows), "press not sent"
    r3.step(0.2)       # release (warn=0, past hold_s)
    assert len(sent) >= 2, "no release sent"
    release_rows = sent[1]
    assert all(row["down"] is False for row in release_rows), f"release not all up: {release_rows}"


def test_unknown_class_falls_back_to_book():
    """When the attack class is unknown (not in the parry table), the book is used."""
    r = _make_reflex(warn_val=1, cls="unknown_class")
    r.step(0.0)
    # Should still send something (book.choose picks one)
    assert r.sent, "no keys sent for unknown class"
    # The hold should be one of the HOLDS options
    down = {row["key"]: row["down"] for row in r.sent[0]}
    assert down.get("a") is True


def test_judge_records_outcome():
    """After judge_s, the book records the outcome (dealt - taken)."""
    sent = []
    stats = {}
    hp1_before, hp2_before = 200, 200
    hp1_after, hp2_after = 190, 180  # P1 took 10, P2 dealt 20 → net +10
    call_count = {"n": 0}
    def rd_seq(addr, length):
        call_count["n"] += 1
        if addr == 0x8C23A37D:
            return bytes([1 if call_count["n"] <= 2 else 0])
        if addr == 0x8C2376D8:
            return struct.pack("<H", hp1_before if call_count["n"] <= 2 else hp1_after)
        if addr == 0x8C237740:
            return struct.pack("<H", hp2_before if call_count["n"] <= 2 else hp2_after)
        return bytes(length)
    r = ParryReflex(rd_seq, sent.append, stats, side=1)
    r.set_attack_class(PARRY_HIGH)
    r.step(0.0)       # press
    assert sent, "no press sent"
    r.step(0.2)       # release (past hold_s=0.1)
    r.step(0.9)       # judge (past judge_s=0.8)
    assert sent[1][0]["down"] is False  # release
    # Book should have a record
    best = r.book.best("warn")
    assert best is not None, "no book record after judge"
    assert stats.get("hold_dealt", 0) >= 0
    assert stats.get("hold_taken", 0) >= 0
