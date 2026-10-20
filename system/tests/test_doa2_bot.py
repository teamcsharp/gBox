"""DOA2 LE playbook (gbox.doa2_bot): RAM game state, jump states, menu route, safety net, hang detection."""
import struct

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
    assert downs[:5] == ["start", "start", "right", "b", "b"]


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
