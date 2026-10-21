"""DOA2 LE playbook (gbox.doa2_bot): RAM game state, jump states, menu route, safety net, hang detection."""
import struct
import time

from gbox import doa2_bot as B


class FakeDC:
    def __init__(self):
        self.ram = bytearray(0x400000)
        self.saves = self.loads = 0
        self.tick = 0
        self.on_load = None

    def _o(self, a):
        return a - 0x8C000000

    def read_memory(self, a, n):
        if a == B.WATCH[0]:                               # fighter data keeps changing while the game runs
            self.tick += 1
            self.ram[self._o(a)] = self.tick & 0xFF
        o = self._o(a)
        return bytes(self.ram[o:o + n])

    def write_memory(self, a, data):
        o = self._o(a)
        self.ram[o:o + len(data)] = data

    def set(self, demo, p1, p2):
        self.ram[self._o(B.DEMO)] = demo
        self.write_memory(B.P1_HP, struct.pack("<H", p1))
        self.write_memory(B.P2_HP, struct.pack("<H", p2))

    def save_state(self):
        self.saves += 1

    def load_state(self):
        self.loads += 1
        if self.on_load:
            self.on_load()


def run(ad, script, limit=200):
    now = [0.0]
    sent = []
    steps = iter(script)

    def stopped():
        try:
            fn = next(steps)
        except StopIteration:
            return True
        fn(now[0])
        return False

    def sleep(s):
        now[0] += s
    stats = B.play(ad, sent.append, stopped, clock=lambda: now[0], sleep=sleep)
    return stats, sent


def test_state_tells_the_demo_from_a_fight():
    ad = FakeDC()
    rd = lambda a, n: ad.read_memory(a, n)
    ad.set(1, 320, 320)
    assert not B.state(rd)["fighting"]                   # attract demo: flag 1, demo health 320
    ad.set(0, 200, 180)
    assert B.state(rd)["fighting"]
    ad.set(0, 0, 180)
    assert not B.state(rd)["fighting"]                   # a KO ends the fight


def test_saves_a_jump_state_in_a_fight_and_jumps_back_after_it():
    ad = FakeDC()
    ad.set(0, 200, 200)
    ad.on_load = lambda: ad.set(0, 240, 240)            # the jump state is a fight
    script = [lambda t: None] * 30 + [lambda t: ad.set(1, 320, 320)] + [lambda t: None] * 30
    stats, sent = run(ad, script)
    assert ad.saves == 1 and stats["saves"] == 1         # saved once, 6 s into the confirmed fight
    assert ad.loads >= 1 and stats["jumps"] >= 1         # the demo came back: straight back into a fight
    assert stats["routes"] == 0                          # no menu walking once a jump state exists


def test_without_a_jump_state_it_presses_through_the_menus():
    ad = FakeDC()
    ad.set(1, 320, 320)
    stats, sent = run(ad, [lambda t: None] * 40)
    assert stats["routes"] >= 1
    downs = [r[0]["key"] for r in sent if r[0]["down"]]
    assert downs[:6] == ["start", "start", "right", "right", "b", "b"]          # title -> Survival -> fighter


def test_p1_never_drops_below_the_safety_line():
    ad = FakeDC()
    ad.set(0, 40, 200)
    stats, _ = run(ad, [lambda t: None] * 3)
    assert stats["safety"] >= 1
    assert struct.unpack("<H", ad.read_memory(B.P1_HP, 2))[0] == B.HP_MAX


def test_frozen_ram_reports_a_hang():
    ad = FakeDC()
    ad.set(0, 200, 200)
    ad.read_memory = lambda a, n, _r=ad.ram: bytes(_r[a - 0x8C000000:a - 0x8C000000 + n])   # nothing changes
    stats, _ = run(ad, [lambda t: None] * 100)
    assert stats["hung"] is True


def test_live_stats_fill_the_callers_dict():
    ad = FakeDC()
    ad.set(0, 200, 150)
    live = {}
    now = [0.0]
    B.play(ad, lambda r: None, iter([False, False, True]).__next__, clock=lambda: now[0],
           sleep=lambda s: now.__setitem__(0, now[0] + s), stats=live)
    assert live["fighting"] is True and live["p1_hp"] == 200 and live["p2_hp"] == 150 and "jumps" in live


def test_reflex_holds_on_the_attack_edge_and_learns_what_pays():
    import random
    ad = FakeDC()
    ad.set(0, 200, 200)
    sent, stats = [], {}
    rx = B.Reflex(lambda a, n: ad.read_memory(a, n), sent.append, stats, rng=random.Random(1))
    paying = ("up", "right")

    def attack(t0):
        ad.ram[B.WARN - 0x8C000000] = 1
        rx.step(t0)
        h = tuple(r["key"] for r in sent[-1] if r["key"] != B.FREE)
        assert sent[-1][0] == {"key": B.FREE, "down": True}
        ad.ram[B.WARN - 0x8C000000] = 0
        rx.step(t0 + 0.05)
        rx.step(t0 + B.HOLD_S)                               # released after HOLD_S
        assert all(not r["down"] for r in sent[-1])
        p1, p2 = (struct.unpack("<H", ad.read_memory(a, 2))[0] for a in (B.P1_HP, B.P2_HP))
        if h == paying:
            ad.set(0, p1, max(1, p2 - 30))                  # the hold landed: P2 takes the counter
        else:
            ad.set(0, max(1, p1 - 20), p2)                  # wrong hold: P1 is hit
        rx.step(t0 + B.JUDGE_S)
        ad.set(0, 200, 200)
        return h
    tried = [attack(i * 2.0) for i in range(len(B.HOLDS))]
    assert sorted(tried) == sorted(B.HOLDS)                 # every direction tried once first
    later = [attack(100 + i * 2.0) for i in range(20)]
    assert later.count(paying) >= 14                        # then mostly the one that paid
    assert stats["holds"] == 26 and stats["hold_best"] == "up+right" and stats["hold_dealt"] >= 30


def test_reflex_waits_for_a_new_edge():
    ad = FakeDC()
    ad.set(0, 200, 200)
    sent = []
    rx = B.Reflex(lambda a, n: ad.read_memory(a, n), sent.append, {})
    ad.ram[B.WARN - 0x8C000000] = 1
    for i in range(5):
        rx.step(i * 0.01)
    assert len(sent) == 1                                   # held input is not re-fired every poll



def test_after_a_ko_the_game_brings_the_next_opponent_without_a_jump():
    ad = FakeDC()
    ad.set(0, 200, 200)
    ad.on_load = lambda: ad.set(0, 240, 240)
    ko = [lambda t: ad.set(0, 200, 0)] + [lambda t: None] * 10           # a KO: out of the fight for ~3 s
    script = [lambda t: None] * 30 + ko + [lambda t: ad.set(0, 240, 240)] + [lambda t: None] * 10
    stats, _ = run(ad, script)
    assert stats["saves"] >= 1 and stats["jumps"] == 0 and stats["routes"] == 0   # no cut back to the old fight


def test_jumps_that_never_land_in_a_fight_drop_the_jump_state():
    ad = FakeDC()
    ad.set(0, 200, 200)
    ad.on_load = lambda: ad.set(1, 320, 320)                              # the jump state is broken: lands on the title
    script = [lambda t: None] * 30 + [lambda t: ad.set(1, 320, 320)] + [lambda t: None] * 200
    stats, _ = run(ad, script)
    assert stats["jumps"] == 2 and stats["jumps_dropped"] == 1           # two misses, then no more jumps
    assert stats["routes"] >= 1                                           # the menus instead


def test_still_ram_gets_a_nudge_before_it_counts_as_a_hang():
    ad = FakeDC()
    ad.set(0, 200, 200)                                                   # a fight, so no menu route runs meanwhile
    now, sent, moving = [0.0], [], {"on": False, "n": 0}
    real = ad.read_memory

    def read(a, n):
        if a == B.WATCH[0]:
            if not moving["on"]:
                return bytes(n)                                           # still until something is pressed
            moving["n"] += 1
            return bytes([moving["n"] & 0xFF]) + bytes(n - 1)
        return real(a, n)
    ad.read_memory = read

    def send(rows):
        sent.append(rows)
        if rows[0]["key"] == "start" and rows[0]["down"]:
            moving["on"] = True                                           # the nudge moved the screen on
    steps = iter([None] * 120)
    stats = B.play(ad, send, lambda: next(steps, 1) is not None, clock=lambda: now[0],
                   sleep=lambda x: now.__setitem__(0, now[0] + x))
    assert stats["nudges"] == 1 and stats["hung"] is False



def test_real_time_play_with_the_hold_reflex_presses_without_deadlocking():
    """Live 2026-10-20: send_locked called itself through the rebound send, so the first press (the memory-card prompt's
    Start) deadlocked the playbook for good. Real time (holds on) must still walk the menus."""
    import threading
    ad = FakeDC()
    ad.set(1, 320, 320)                                    # the title: no jump state yet, so the menu route runs
    sent, done = [], {}
    stop = threading.Event()

    def go():
        done["stats"] = B.play(ad, sent.append, stop.is_set, sleep=lambda x: time.sleep(min(x, 0.01)))
    th = threading.Thread(target=go, daemon=True)
    th.start()
    deadline = time.time() + 20
    while time.time() < deadline and not any(r[0]["key"] == "right" for r in sent):
        time.sleep(0.05)
    stop.set()
    th.join(5)
    assert not th.is_alive(), "the playbook deadlocked"
    assert any(r[0]["key"] == "start" and r[0]["down"] for r in sent)
