"""Offline tests for the `zelda` op skip_text (report #1119: skip to the end of any talking segment in OoT).

A fake N64 adapter serves word-swapped RDRAM like RetroArch/ParaLLEl (oot._rd un-swaps it), holds an OoT v1.2 save
marker and a player actor whose stateFlags1 TALKING/IN_CUTSCENE bits are driven by the controller input it receives.
The clock and sleep used by skip_text are replaced so the tests run instantly and deterministically.
"""
import struct

import pytest

from gbox import oot, zelda_tool

OOT_TITLE = "Legend of Zelda, The: Ocarina of Time (USA)"
MM_TITLE = "Legend of Zelda, The: Majora's Mask (USA)"
PLAYER = 0x80400000
FLAGS = PLAYER + 0x66C
TALKING, IN_CUTSCENE = 0x40, 0x20000000


class FakeN64:
    """RDRAM as a big-endian dict; read_memory returns 32-bit little-endian words like the real adapter."""

    def __init__(self, flags=0, boxes=0, reopen_on_settle=None):
        self.mem = {}
        self.events = []
        self.writes = 0
        self.boxes = boxes                      # A presses needed before the text state clears
        self.reopen_on_settle = list(reopen_on_settle or [])   # flags re-set during the settle wait (next box opens)
        self.put(oot.SAVE + 0x1C, b"ZELDAZ")
        self.put(oot.PLAY + 0x1C44, struct.pack(">I", PLAYER))
        self.set_flags(flags)

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def set_flags(self, v):
        self.put(FLAGS, struct.pack(">I", v))

    def flags(self):
        return struct.unpack(">I", bytes(self.mem.get(FLAGS + i, 0) for i in range(4)))[0]

    def read_memory(self, a, n):
        be = bytes(self.mem.get(a + i, 0) for i in range(n))
        return b"".join(be[i:i + 4][::-1] for i in range(0, n, 4))

    def write_memory(self, a, data):
        self.writes += 1

    def send_input(self, events):
        self.events.extend((e["key"], e["down"]) for e in events)
        for e in events:
            if e["key"] == "a" and e["down"] and self.boxes > 0:
                self.boxes -= 1
                if self.boxes == 0:
                    self.set_flags(0)
        return {"ok": True}

    def on_sleep(self, dt):
        if dt == pytest.approx(0.5) and self.reopen_on_settle and self.flags() == 0:
            self.set_flags(self.reopen_on_settle.pop(0))
            self.boxes = 1


class NoInput:
    def __init__(self):
        self.inner = FakeN64(flags=TALKING, boxes=1)

    def read_memory(self, a, n):
        return self.inner.read_memory(a, n)


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 0.0, "ad": None}

    def sleep(dt):
        t["now"] += dt
        if t["ad"] is not None:
            t["ad"].on_sleep(dt)

    monkeypatch.setattr(zelda_tool, "_clock", lambda: t["now"])
    monkeypatch.setattr(zelda_tool, "_sleep", sleep)
    return t


def _run(clock, ad, op="skip_text", count=0, title=OOT_TITLE):
    clock["ad"] = ad if isinstance(ad, FakeN64) else None
    return zelda_tool.run(ad, title, "n64", op, count=count)


@pytest.mark.parametrize("op", ["skip_text", "skip", "skip_talk", "talk", "text", "skip text", "SKIP", "skip_cutscene",
                                "skip_dialogue", "advance_text"])
def test_op_aliases_dispatch_to_skip_text(clock, op):
    ad = FakeN64(flags=TALKING, boxes=1)
    r = _run(clock, ad, op)
    assert r["op"] == "skip_text"
    assert r["skipped"] is True and r["presses"] == 1


def test_multi_box_dialogue_taps_a_until_text_ends(clock):
    ad = FakeN64(flags=TALKING, boxes=3)
    r = _run(clock, ad)
    assert r["in_text_before"] is True and r["in_text_after"] is False
    assert r["skipped"] is True and r["timed_out"] is False
    assert r["presses"] == 3 and r["buttons"] == ["a"]
    assert ad.events == [("a", True), ("a", False)] * 3      # A only: no Start (pause menu) / B presses
    assert r["changes"] == [] and ad.writes == 0             # input only, no memory writes
    assert ad.flags() == 0


def test_cutscene_flag_counts_as_text(clock):
    ad = FakeN64(flags=IN_CUTSCENE, boxes=2)
    r = _run(clock, ad)
    assert r["skipped"] is True and r["presses"] == 2


def test_next_box_opening_during_settle_keeps_pressing(clock):
    # text clears after the 1st press, the next box opens during the settle wait, one more press ends it
    ad = FakeN64(flags=TALKING, boxes=1, reopen_on_settle=[TALKING])
    r = _run(clock, ad)
    assert r["presses"] == 2 and r["skipped"] is True and r["in_text_after"] is False
    assert ad.events == [("a", True), ("a", False)] * 2


def test_free_gameplay_presses_nothing(clock):
    ad = FakeN64(flags=0)
    r = _run(clock, ad)
    assert r["in_text_before"] is False and r["skipped"] is False
    assert r["presses"] == 0 and ad.events == []
    assert "no text box" in r["note"]


def test_timeout_stops_and_releases_buttons(clock):
    ad = FakeN64(flags=IN_CUTSCENE, boxes=10 ** 6)          # an unskippable cutscene: never clears
    r = _run(clock, ad, count=3)
    assert r["timed_out"] is True and r["skipped"] is False and r["in_text_after"] is True
    assert r["max_s"] == 3.0
    assert 10 <= r["presses"] <= 16                          # 0.1 s hold + 0.1 s gap per tap within 3 s
    assert clock["now"] < 3.5
    downs = [d for _, d in ad.events]
    assert downs == [True, False] * r["presses"]              # every press released, none left held
    assert "still in text" in r["note"]


def test_default_and_capped_time_limit(clock):
    r = _run(clock, FakeN64(flags=TALKING, boxes=1))
    assert r["max_s"] == zelda_tool.SKIP_TEXT_DEFAULT_S
    r = _run(clock, FakeN64(flags=TALKING, boxes=1), count=10_000)
    assert r["max_s"] == zelda_tool.SKIP_TEXT_MAX_S < 120     # stays below the zelda tool's 120 s timeout


def test_button_released_even_if_sleep_fails(monkeypatch):
    ad = FakeN64(flags=TALKING, boxes=5)

    def boom(dt):
        raise KeyboardInterrupt

    monkeypatch.setattr(zelda_tool, "_sleep", boom)
    with pytest.raises(KeyboardInterrupt):
        zelda_tool._press(ad, "a")
    assert ad.events == [("a", True), ("a", False)]


def test_adapter_without_input_is_refused(clock):
    with pytest.raises(RuntimeError, match="cannot send controller input"):
        _run(clock, NoInput())


def test_game_without_detector_is_refused(clock):
    ad = FakeN64(flags=TALKING, boxes=1)
    ad.put(0x801EF670 + 0x24, b"ZELDA3")                     # a loaded Majora's Mask save
    with pytest.raises(RuntimeError, match="no text/cutscene detector"):
        _run(clock, ad, title=MM_TITLE)
    assert ad.events == []


def test_no_save_loaded_still_refused_before_input(clock):
    ad = FakeN64(flags=TALKING, boxes=1)
    ad.put(oot.SAVE + 0x1C, b"\0" * 6)
    with pytest.raises(RuntimeError, match="no OoT save loaded"):
        _run(clock, ad)
    assert ad.events == []
