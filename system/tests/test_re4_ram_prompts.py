"""RE4 GameCube prompts from RAM (gbox.re4_ram_prompts): recorded RAM of live prompts decodes to what the screen showed,
the tables and edge cases on a built RAM image, and the Mercenaries playbook asking RAM before vision."""
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import re4_ram_prompts as R

FIXTURES = Path(__file__).parent / "fixtures" / "re4_ram_prompts.json"


class ReadsMem:
    """RAM recorded on the Spark (every read action_from_ram made, address -> bytes): serves those reads only."""

    def __init__(self, reads):
        self.regions = [(int(a, 16), bytes.fromhex(h)) for a, h in reads]

    def rd(self, a, n):
        for base, b in self.regions:
            if base <= a and a + n <= base + len(b):
                return b[a - base:a - base + n]
        raise AssertionError(f"read {a:#x}+{n:#x} was not recorded")


def recorded():
    return json.loads(FIXTURES.read_text())["cases"] if FIXTURES.is_file() else []


@pytest.mark.parametrize("case", recorded(), ids=lambda c: c["name"])
def test_recorded_ram_decodes_to_the_prompt_the_screen_showed(case):
    R._LABEL_CACHE.clear()
    a = R.action_from_ram(ReadsMem(case["reads"]), with_zones=case["zones"])
    for k, v in case["expect"].items():
        assert a[k] == v, k
    assert R.prompt_from_ram(ReadsMem(case["reads"])) == case["expect"]["button"]


class FakeMem:
    """MEM1 as a bytearray at 0x80000000 (only the first 4 MiB + a heap window at 0x81000000)."""

    def __init__(self):
        self.lo = bytearray(0x400000)
        self.hi = bytearray(0x100000)

    def _buf(self, a):
        if 0x81000000 <= a < 0x81100000:
            return self.hi, a - 0x81000000
        return self.lo, a - 0x80000000

    def rd(self, a, n):
        b, o = self._buf(a)
        return bytes(b[o:o + n])

    def wr(self, a, data):
        b, o = self._buf(a)
        b[o:o + len(data)] = data


BANK, AEVF, AEVS = 0x81000000, 0x81010000, 0x81010010


def ram(kind=0, label=None, nodes=(), valid=0, entries=(), inside=(), lang=1, pg_routine=b"\3\0\0\0"):
    """A RAM image laid out like G4BE08's: the prompt drawn (kind, slot 1 showing label), the manager's nodes
    [(label, kind, dispatch, data)], area events [(index, type, trigger, who, label)] and the indices Leon is in."""
    m = FakeMem()
    m.wr(0x80000000, b"G4BE08")
    # message bank 0: language table, then a block per language with ids 0..0x60 (message i at block + 0x200 + 0x10 i)
    m.wr(R.MES_BANKS, struct.pack(">II", lang, BANK))
    m.wr(BANK, struct.pack(">I", 2) + struct.pack(">II", 0x100, 0x800))
    for lo in (0x100, 0x800):
        blk = BANK + lo
        m.wr(blk, struct.pack(">II", 0x418CB241, 0x60) + struct.pack(">96I", *[0x200 + 0x10 * i for i in range(0x60)]))
    block = BANK + (0x100, 0x800)[lang]
    m.wr(R.ACT_KIND, bytes([kind]))
    act = bytearray(R.ACT_NODES + R.NODE * R.NODES)
    act[R.ACT_COUNT], act[R.ACT_VALID] = len(nodes), valid
    for i, (lb, kd, disp, data) in enumerate(nodes):
        struct.pack_into(">3I4B2I", act, R.ACT_NODES + i * R.NODE, 0xFFFFFFFF, 0x8013CE74, data, lb, 2, disp, kd,
                         0x810D3000, 0)
    m.wr(R.ACT_MGR, bytes(act))
    if label is not None:
        m.wr(R.MES_SLOT1 + R.SLOT_FLAGS, struct.pack(">I", 3))
        m.wr(R.MES_SLOT1 + R.SLOT_MSG, struct.pack(">I", block + 0x200 + 0x10 * (label + R.LABEL_BASE)))
    # the area events: AevMgr pointer, its AEV file / entries (all in priority list 0), the zones Leon is in
    m.wr(R.P_AEV_MGR, struct.pack(">I", R.AEV_MGR))
    m.wr(R.AEV_MGR, struct.pack(">4I", AEVF, AEVS, 0, 0))
    m.wr(AEVF, b"AEV\0" + struct.pack(">HH", 0x104, len(entries)))
    heads = [AEVS if entries else 0xFFFFFFFF] + [(R.AEV_MGR + 0x50 + 4 * (i - 1)) & 0x7FFFFFFF for i in range(1, 16)]
    m.wr(R.AEV_MGR + 0x50, struct.pack(">16I", *heads))
    for k, (index, typ, trig, who, lb) in enumerate(entries):
        e = bytearray(R.AEV_ENTRY)
        struct.pack_into(">I", e, 0, AEVS + (k + 1) * R.AEV_ENTRY if k + 1 < len(entries) else 0xFFFFFFFF)
        e[0x34], e[0x35], e[0x36], e[0x38], e[0x39], e[0x4A] = 1, typ, index, trig, who, lb
        struct.pack_into(">2f", e, 0x08, 0.0, 1000.0)
        struct.pack_into(">8f", e, 0x14, 0, 0, 100, 0, 100, 100, 0, 100)
        if typ == 1:
            struct.pack_into(">4f", e, 0x5C, 1.0, 2.0, 3.0, 0.5)
            e[0x6C], e[0x6D] = 4, 2
        m.wr(AEVS + k * R.AEV_ENTRY, bytes(e))
    bits = bytearray(0x20)
    for i in inside:
        struct.pack_into(">I", bits, 4 * (i >> 5), struct.unpack_from(">I", bits, 4 * (i >> 5))[0] | 0x80000000 >> (i & 31))
    m.wr(R.AEV_MGR + 0x10, bytes(bits))
    m.wr(0x802B2280, struct.pack(">I", 0x8027F7D0))
    m.wr(0x8027F7D0 + R.G_ROUTINE, pg_routine)
    m.wr(0x8027F7D0 + R.G_DEST, b"\x04\x02")
    m.wr(0x8027F7D0 + R.G_ROOM, struct.pack(">HxxH", 0x400, 0x400))
    m.wr(0x802B3044, struct.pack(">I", 0x810D3000))
    return m


@pytest.fixture(autouse=True)
def _fresh_labels():
    R._LABEL_CACHE.clear()


def test_no_prompt_is_none_not_unknown():
    m = ram()
    assert R.prompt_from_ram(m) is None
    a = R.action_from_ram(m)
    assert a["button"] is None and a["action"] is None and a["aev"] is None


def test_the_drawn_kind_is_the_button_and_slot_1_is_the_label():
    m = ram(kind=1, label=0x05, nodes=[(0x05, 1, 0, 0)], valid=1)
    a = R.action_from_ram(m)
    assert (a["button"], a["action"], a["label"]) == ("a", "JUMP OVER", 5)
    assert R.prompt_from_ram(m) == "a"


@pytest.mark.parametrize("kind,button", [(3, "l+r"), (4, "a+b"), (5, "b"), (0xB, "wiggle"), (0xE, "a")])
def test_qte_and_grab_kinds(kind, button):
    assert R.prompt_from_ram(ram(kind=kind, label=0x25, nodes=[(0x25, kind, 1, 0)])) == button


def test_a_kind_the_tables_do_not_know_is_unknown():
    with pytest.raises(R.Unknown):
        R.prompt_from_ram(ram(kind=9, label=0x25))


def test_another_game_is_unknown():
    m = ram(kind=1, label=5)
    m.wr(0x80000000, b"GZLE01")
    with pytest.raises(R.Unknown):
        R.prompt_from_ram(m)


def test_the_label_follows_the_language_block():
    a = R.action_from_ram(ram(kind=1, label=0x28, lang=0))
    assert a["action"] == "TAKE"


def test_the_label_slot_holds_a_read_cursor_inside_the_message():
    m = ram(kind=1, label=0x28)
    msg = struct.unpack(">I", m.rd(R.MES_SLOT1 + R.SLOT_MSG, 4))[0]
    m.wr(R.MES_SLOT1 + R.SLOT_MSG, struct.pack(">I", msg + 0xC))     # after "TAKE" was drawn (seen live)
    assert R.action_from_ram(m)["action"] == "TAKE"


def test_a_torn_label_slot_falls_back_to_the_node():
    m = ram(kind=1, nodes=[(0x07, 1, 0, 0)])
    assert R.action_from_ram(m)["action"] == "KICK"


def test_an_area_event_prompt_names_its_event_and_leon_s_zones():
    door = 0x81010010 + R.AEV_ENTRY                   # the second entry: a door with OPEN
    m = ram(kind=1, label=0x10, nodes=[(0x10, 1, 2, door)], valid=1,
            entries=[(0, 4, 1, 3, 0), (5, 1, 8, 1, 0x10), (6, 0x10, 8, 2, 8)], inside=(0, 5, 6))
    a = R.action_from_ram(m)
    assert a["action"] == "OPEN" and a["aev"]["kind"] == "door" and a["aev"]["index"] == 5
    assert a["aev"]["to"] == {"pos": [1.0, 2.0, 3.0], "room": 0x402}
    assert [z["index"] for z in a["zones"]] == [0, 5]          # 6 is an enemies-only zone


def test_a_door_opening():
    m = ram(pg_routine=b"\4\0\0\0")                                 # an area-event door: the room change
    assert R.door_from_ram(m) == {"kind": "room change", "to_room": 0x402, "from_room": 0x400, "room": 0x400}
    assert R.door_from_ram(ram()) is None
    m = ram()                                                         # a door object: Leon's object action
    m.wr(0x810D3000 + R.PL_ROUTINE, b"\4\0\1\0")
    m.wr(0x810D3000 + R.PL_ACTION_OBJ, struct.pack(">I", 0x81050000))
    m.wr(0x81050000 + R.EM_ID, bytes([R.EM_DOOR]))
    m.wr(R.ACTION_FN, struct.pack(">I", 0x800DDA0C))
    assert R.door_from_ram(m) == {"kind": "door", "object": 0x81050000, "routine": 0x800DDA0C}
    assert R.leon_from_ram(m) == {"routine": "04000100", "object": 0x81050000, "object_em": 0x41, "fn": 0x800DDA0C}
    m.wr(0x81050000 + R.EM_ID, b"\x16")                               # a Ganado (a kick, a grab): not a door
    m.wr(R.ACTION_FN, struct.pack(">I", 0x8170C53C))
    assert R.door_from_ram(m) is None
    m.wr(0x810D3000 + R.PL_ROUTINE, b"\0\6\1\1")                      # back under the player's control
    assert R.leon_from_ram(m) == {"routine": "00060101"}


def test_source_reports_unknown_for_a_failed_read():
    class Broken:
        def rd(self, a, n):
            raise OSError("gone")
    with pytest.raises(R.Unknown):
        R.source(Broken())()
    stats = {}
    assert R.source(ram(kind=1, label=0x28), stats)() == "a" and stats["ram_action"] == "TAKE"


# -- the Mercenaries playbook: RAM first, vision after --

def merc(prompt_kind=None, label=None):
    """A Mercenaries round with no Ganados (every press is a prompt press) and, optionally, a prompt in RAM."""
    from gbox import re4_merc_bot as B
    m = ram(kind=prompt_kind or 0, label=label, nodes=[(label, prompt_kind, 0, 0)] if prompt_kind else ())
    pg, pl = 0x8027F7D0, 0x810D3000
    m.wr(B.P_GLOBAL, struct.pack(">I", pg))
    m.wr(pg + B.G_ROOM, struct.pack(">H", 0x400))
    m.wr(B.P_PLAYER, struct.pack(">I", pl))
    m.wr(B.EMMGR, struct.pack(">3I", 0x81020000, 1, 0xDE0))
    return B, m


def run_play(B, m, steps=30, **kw):
    now, sent = [0.0], []
    it = iter(range(steps))

    def stopped():
        n = next(it, None)
        m.wr(B.MERC_TIMER, struct.pack(">I", int((100 - now[0]) * 30)))
        for off in (0x94, 0x1C0):                                     # running freely: no stuck taps
            m.wr(0x810D3000 + off, struct.pack(">3f", 0.0, 0.0, 300.0 * (n or 0)))
        return n is None
    B.play(None, lambda rows: sent.append(rows), stopped, sleep=lambda s: now.__setitem__(0, now[0] + s), m=m,
           clock=lambda: now[0], **kw)
    return sent


def test_play_takes_ram_over_vision():
    B, m = merc()                                                     # RAM: no prompt up
    sent = run_play(B, m, prompt=lambda: "a")                         # vision sees an "A" (a false positive)
    assert {"key": "a", "down": True} not in [r for rows in sent for r in rows]


def test_play_asks_vision_when_ram_cannot_tell():
    B, m = merc()
    stats = {}
    sent = run_play(B, m, prompt=lambda: "a", ram_prompt=lambda: (_ for _ in ()).throw(R.Unknown("x")), stats=stats)
    assert [{"key": "a", "down": True}] in sent and stats["prompt_source"] == "vision"


def test_play_presses_a_qte_pair_together_and_wiggles_out_of_a_grab():
    B, m = merc(prompt_kind=4, label=0x25)                           # DODGE: A+B
    stats = {}
    sent = run_play(B, m, stats=stats)
    assert [{"key": "a", "down": True}, {"key": "b", "down": True}] in sent
    assert stats["prompt_source"] == "ram" and stats["ram_action"] == "DODGE"
    B, m = merc(prompt_kind=0xB, label=0x2B)                         # SHAKE OFF: the stick, both ways
    sent = run_play(B, m)
    flat = [r for rows in sent for r in rows if r["down"]]
    assert {"key": "left", "down": True} in flat and {"key": "right", "down": True} in flat


def test_autoplay_hands_the_merc_playbook_a_ram_prompt_source(monkeypatch):
    import threading
    from gbox import tools, autoplay as apmod

    class D:
        def __init__(self, *a, **k):
            self.stopped, self.trace = False, []
    monkeypatch.setattr(apmod, "Driver", D)
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(json=lambda: []))
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {}, text=""))
    mem = ram(kind=1, label=0x05)
    ad = SimpleNamespace(name="dolphin", supported={"send_input"}, send_input=lambda rows: None,
                         read_memory=lambda a, n: mem.rd(a, n), write_memory=lambda a, d: None)
    monkeypatch.setitem(tools.SESSIONS, "s7", (ad, {"platform": "gamecube", "title": "RE4"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    from gbox import re4_merc_bot as B
    monkeypatch.setattr(B, "ShmMem", lambda *a, **k: (_ for _ in ()).throw(OSError("no shm")))
    got, done = {}, threading.Event()

    def play(ad, send, stopped, prompt=None, ram_prompt=None):
        got["button"] = ram_prompt() if ram_prompt else None
        done.set()
        return {}
    pb = SimpleNamespace(__name__="gbox.re4_merc_bot", __doc__="RE4 bot.", setup=lambda ad: [], play=play)
    tools._start_playbook(pb, tools.AutoplayIn(session_id="s7", op="start", mode="playbook"), D(), ad, 0.0)
    assert done.wait(5) and got["button"] == "a"                    # JUMP OVER from RAM

    got.clear()
    done.clear()
    other = SimpleNamespace(__name__="gbox.doa2_bot", __doc__="DOA2 bot.", setup=lambda ad: [], play=play)
    tools._start_playbook(other, tools.AutoplayIn(session_id="s7", op="start", mode="playbook"), D(), ad, 0.0)
    assert done.wait(5) and got["button"] is None                    # other playbooks: no RAM source
