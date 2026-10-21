"""DOA3 on the fighting engine (gbox.fightbot.titles.doa3_xbox, gbox.doa3_bot): frames, holds, the playbook."""
import struct
from types import SimpleNamespace

from gbox import doa3_bot, doa3_pad, ram_map
from gbox.fightbot import vocab
from gbox.fightbot.titles import doa3_xbox as D
from gbox.fightbot.world import Attack, Fighter, World


class Ram:
    def __init__(self):
        self.ram = bytearray(0x900000)
        struct.pack_into("<Q", self.ram, D.QPC_HZ, 10_000_000)       # a 10 MHz performance counter

    def read(self, a, n):
        return bytes(self.ram[a:a + n])

    def write(self, a, data):
        self.ram[a:a + len(data)] = data

    def frames(self, n, ms=1000 / 60):
        """The main loop ran n more frames."""
        qpc, ring = struct.unpack_from("<Q", self.ram, D.QPC)[0], struct.unpack_from("<I", self.ram, D.RING)[0]
        struct.pack_into("<Q", self.ram, D.QPC, qpc + int(n * ms * 10_000))
        struct.pack_into("<I", self.ram, D.RING, (ring + n) & 7)


def test_the_map_loads_and_names_the_engine_vocabulary():
    m = ram_map.load(D.MAP_ID)
    assert m.spec["fight"]["title"] == "gbox.fightbot.titles.doa3_xbox"
    rep = vocab.check(m)
    assert rep["filled"]["p2.move"] == "p2.move" and "screen" in rep["driver"]
    assert ram_map.find({"game_id": "f03a801797a90506"}).id == D.MAP_ID      # the QuickSwap copy too


def test_frames_follow_the_ring_and_the_counter_when_it_wraps():
    ram, t = Ram(), D.Doa3()
    assert t.frame(ram) == 0
    assert t.frame(ram) == 0                                     # nothing ran
    ram.frames(1)
    assert t.frame(ram) == 1
    ram.frames(3)
    assert t.frame(ram) == 4                                     # three frames between two polls
    ram.frames(8)                                                # the ring is back where it was: no change seen
    assert t.frame(ram) == 4
    ram.frames(2)
    assert t.frame(ram) == 14                                    # the counter says 10 frames passed


def test_holds_go_back_from_the_side_p1_is_on_and_lead_with_the_signature_height():
    t = D.Doa3()
    w = World(frame=0, t=0, screen="fight", p1=Fighter(side=1), p2=Fighter(side=-1))
    names = [a.name for a in t.answers(Attack(height="low"), w)]
    assert names[0] == "hold_low" and set(names) == {"hold_high", "hold_mid", "hold_low", "hold_mid_kick"}
    hold = next(a for a in t.answers(Attack(), w) if a.name == "hold_high")
    assert hold.at(0) == ("left", "up", D.FREE)                  # directions first, back = left on the left side
    w.p1.side = -1
    hold = next(a for a in t.answers(Attack(), w) if a.name == "hold_high")
    assert hold.at(0) == ("right", "up", D.FREE)
    assert t.input_bits(hold, w) == 0x20 | 0x40 | 0x1            # the game's own bits for up, right, F
    assert [a.name for a in t.answers(Attack(kind="throw"), w)] == ["throw_escape"]


def test_punish_is_a_string():
    t = D.Doa3()
    p = t.punish(None, "held")
    assert p.kind == "punish" and p.length == 21
    assert [p.at(k) for k in (0, 3, 9, 18)] == [(D.PUNCH,), (), (D.PUNCH,), (D.KICK,)]


def test_the_playbook_matches_only_the_native_runner_and_claims_the_pad():
    assert doa3_bot.matches(SimpleNamespace(name="doa3_native"), {"game_id": "b8edf7040116f3aa"})
    assert not doa3_bot.matches(SimpleNamespace(name="cxbx"), {"game_id": "b8edf7040116f3aa"})
    assert not doa3_bot.matches(SimpleNamespace(name="doa3_native"), {"game_id": "1de2e7634f3161ff"})
    ram = Ram()
    ad = SimpleNamespace(pad=lambda: doa3_pad.VirtualPad(ram))
    assert doa3_bot.setup(ad) == []
    assert struct.unpack_from("<I", ram.ram, doa3_pad.HANDLE_AT)[0] == doa3_pad.SENTINEL
    struct.pack_into("<I", ram.ram, doa3_pad.HANDLE_AT, 0x58490004)
    assert "virtual pad" in doa3_bot.setup(ad)[0]                # a real 4th pad: reported, not taken
