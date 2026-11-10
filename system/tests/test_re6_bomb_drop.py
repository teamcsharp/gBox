"""RE6 Switch (operator 2026-11-10 06:45-07:05): the remote bomb dropped already placed and armed (no throw, nothing in
his hand) and set off by the flag while his gun keeps firing; never the detonator in hand; 5x the grenades, 2x faster,
the grenade kept in hand through a burst; grenades only at the ground on his floor; the QTEs solved by RAM by default.

No live game: a fake native controller (as test_re6_grenade_ring) and test_re6_switch's synthetic guest."""
import hashlib
import math
import struct
import threading

import pytest

from gbox.mercs.titles import re6_switch as R
from gbox.mercs.titles import re6_switch_mods as M
from gbox.mercs.titles import re6_switch_native as N
from gbox.mercs.native.re6_061d2a06.code import IMAGES
from tests.test_re6_switch import BASE, Adapter, round_guest, run, struggle_guest   # noqa: F401
from tests.test_re6_switch_equip import NativeBridge
from tests.test_re6_bomb_mind import FakeMind, mind_bot


@pytest.fixture(autouse=True)
def _nades_back():
    was = R.NADES
    yield
    R.NADES = was


# --- the native drop ----------------------------------------------------------------------------------------------

def test_the_spawn_bomb_image_is_pinned_and_in_the_padding_after_detonate():
    at, name, size, digest = N.SPAWN_BOMB
    assert IMAGES[name] and len(IMAGES[name]) == size and hashlib.sha256(IMAGES[name]).hexdigest() == digest
    end_detonate = N.CODE[-1][0] + N.CODE[-1][2]
    assert end_detonate <= at and at + size <= 0x18F3000                   # zero padding, the executable page's end


def drop_controller(armed_after=True, refuse=False, action="cWpAction_wp_act_setting", position=(100.0, 50.0, -20.0)):
    ctl = N.Controller.__new__(N.Controller)
    ctl.base, ctl.pid, ctl.identity = 0x100000000, 1, (1, 1)
    ctl.player, ctl.sp, ctl.generation = 0x200000000, 0x210000000, 7
    ctl.manager, ctl.heap = ctl.player + 0x13A8, 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.calls = {}, []

    def put(at, data):
        ctl.mem.update({at + i: b for i, b in enumerate(data)})

    def read(at, n):
        return bytes(ctl.mem.get(at + i, 0) for i in range(n))

    ctl.rd, ctl.write, ctl.put = read, put, put
    ctl.q = lambda a: struct.unpack("<Q", read(a, 8))[0]
    ctl.w = lambda a: struct.unpack("<I", read(a, 4))[0]
    ctl.check = ctl.check_build = lambda: None
    ctl.attach = ctl.detach_completed = lambda: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.stopped = lambda fn: pytest.fail("the image is installed already: no stop")
    put(ctl.base + N.SPAWN_BOMB[0], IMAGES["spawn_bomb"])               # (installed earlier)
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.sp + R.P_FIRST, struct.pack("<Q", ctl.player))
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))
    put(ctl.player + R.P_HP, struct.pack("<h", 900))
    put(ctl.player + 0x1308, struct.pack("<I", ctl.generation))
    put(0x90000000 + R.GM_PHASE, struct.pack("<i", R.PHASE_PLAYING))

    def call(off, *args):
        ctl.calls.append((off, args))
        if off != N.SPAWN_BOMB[0] or refuse:
            return 0
        unit = 0x230000000
        put(unit, struct.pack("<Q", ctl.base + N.BOMB_VTABLE))
        put(unit + 0x1300, struct.pack("<Q", ctl.player))
        put(unit + 0x1308, struct.pack("<I", 4242))
        if armed_after:
            put(ctl.player + N.P_FLAGS_ARMED_BYTE, bytes([ctl.mem.get(ctl.player + N.P_FLAGS_ARMED_BYTE, 0) | 0x20]))
        return unit
    ctl.call = call
    return ctl


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(N, "process_identity", lambda pid: (1, 1))
    monkeypatch.setattr(N.R, "game_man", lambda m, base: 0x90000000)
    monkeypatch.setattr(N.R, "inventory_state", lambda m, p: (0, 7, {"count": 5, "out": False}))
    actions = {"name": "cWpAction_wp_act_setting"}
    monkeypatch.setattr(N.R, "unit_action", lambda m, unit: actions["name"])
    return actions


def test_drop_bomb_places_an_armed_bomb_at_his_feet_with_nothing_in_his_hand(native):
    ctl = drop_controller()
    out = ctl.drop_bomb()
    assert out["state"] == "confirmed" and out["verified"] and out["armed"] and out["unit"] == 0x230000000
    (off, args), = ctl.calls
    assert off == N.SPAWN_BOMB[0] and args[0] == ctl.player
    assert [struct.unpack("<f", struct.pack("<I", b))[0] for b in args[1:]] == [100.0, 50.0, -20.0]   # his feet
    assert out["pos"] == [100.0, 50.0, -20.0]


def test_drop_bomb_is_uncertain_when_the_flag_or_the_placed_action_does_not_show(native):
    with pytest.raises(N.Uncertain, match="flag"):
        drop_controller(armed_after=False).drop_bomb()
    native["name"] = "cWpAction_wp_act_throw"
    with pytest.raises(N.Uncertain, match="placed action"):
        drop_controller().drop_bomb(wait_s=0.02)


def test_drop_bomb_refuses_without_the_bombs_resources_and_on_an_allocation_refusal(native, monkeypatch):
    with pytest.raises(N.Unavailable, match="refused"):
        drop_controller(refuse=True).drop_bomb()
    monkeypatch.setattr(N.R, "inventory_state", lambda m, p: (0, 7, None))
    with pytest.raises(N.Unavailable, match="resources"):
        drop_controller().drop_bomb()


def test_bomb_drop_now_never_raises():
    class Ad:
        address_mode = "direct"

        def _guest(self):
            raise OSError("no emulator")
    out = N.bomb_drop_now(Ad())
    assert out["state"] in ("unavailable", "failed") and not out["verified"] and out["reason"]


# --- the bot: drop, fight, the flag ---------------------------------------------------------------------------------

class DropMind(FakeMind):
    def __init__(self, ok=True, drop_ok=True):
        super().__init__(ok)
        self.drops = []
        self.drop_ok = drop_ok

    def drop_ready(self, stats=None):
        return True

    def drop(self, p=None, at=None):
        self.drops.append(p.get("pos") if p else at)
        return ({"verified": True, "state": "confirmed", "pos": list(p["pos"]), "elapsed_ms": 30.0} if self.drop_ok
                else {"verified": False, "state": "unavailable", "reason": "no NCE"})


def drop_bot(enemies, mind=None):
    clock = [100.0]
    bridge, mind = NativeBridge(), mind or DropMind()
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge, mind=mind)
    snap = R.snapshot(round_guest(enemies=enemies))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False, "armed": False},
                          guns={0x107: 0, 0x104: 1}, gun_ammo={0: 7, 1: 8})
    bot.held = lambda p, now: False
    bot.bomb_last = -1e9
    return bot, bridge, mind, clock, snap


def test_a_bomb_goes_down_by_the_instant_drop_and_off_by_the_flag_with_the_gun_in_hand(monkeypatch):
    monkeypatch.setattr(R, "BOMB_MIND", True)
    stand = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700), (0.0, 0.0, 900.0, 700))
    bot, bridge, mind, clock, snap = drop_bot(stand)
    acts = run(bot, snap, clock, 2)
    assert bot.stats["bombs_instant_dropped"] == 1 and bot.bomb_dropped and mind.drops
    assert R.BOMB_INDEX not in bridge.targets                                 # the remote never asked for
    assert all(not ({a.get("tap")} | set(a.get("hold") or ())) & R.DPAD_KEYS for a in acts)
    snap["player"]["bomb"] = {"count": 5, "out": False, "armed": True}      # the drop armed the flag
    snap["player"]["pos"] = (0.0, 0.0, -bot.book.safe - 100.0)               # he walked off it
    for e in snap["enemies"]:
        e["pos"] = (30.0, 0.0, 40.0)                                         # they came onto it
    run(bot, snap, clock, 1)
    assert mind.calls and bot.stats["bombs_flag_detonated"] == 1 and bot.bomb_phase == "mind"
    assert snap["player"]["equipped"] == 0                                   # the gun stayed in his hand
    snap["player"]["bomb"] = {"count": 5, "out": False, "armed": False}     # the blast
    run(bot, snap, clock, 1)
    assert bot.stats["bombs_detonated"] == 1 and not bot.bomb_dropped and bot.stats["detonator_in_hand_s"] == 0


def test_a_drop_that_fails_falls_back_to_the_throw():
    stand = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700), (0.0, 0.0, 900.0, 700))
    bot, bridge, mind, clock, snap = drop_bot(stand, DropMind(drop_ok=False))
    run(bot, snap, clock, 2)
    assert bot.stats["bomb_drop_failures"] == 1 and bot.bomb_phase in ("equip", "face", "aim")
    assert R.BOMB_INDEX in bridge.targets                                     # the remote by the hook, not the wheel


def test_the_detonator_in_his_hand_goes_back_the_same_tick():
    bot, bridge, mind, clock, snap = drop_bot(((0.0, 0.0, 2500.0, 700),))
    snap["player"]["equipped"] = R.BOMB_INDEX                                 # the game put it in his hand
    out = run(bot, snap, clock, 1)[0]
    assert bridge.targets and bridge.targets[-1] == 0                        # the magnum, this tick
    assert not {"zl", "zr"} & set(out.get("hold") or ())                      # no trigger with it in hand
    assert bot.stats["detonator_gun_backs"] >= 1 and bot.stats["detonator_in_hand_s"] == pytest.approx(R.TICK_S)


def test_run_routes_the_bomb_drop_op(monkeypatch):
    seen = []
    monkeypatch.setattr(N, "bomb_drop_now", lambda ad, at=None: seen.append(at) or {"verified": True, "unit": 1})
    g = round_guest()
    out = M.run(Adapter(g), "bomb_drop")
    assert out["verified"] and seen == [None]


# --- grenades: the in-hand burst, 2x faster, on the ground ----------------------------------------------------------

def nade_bot(enemies, cam_yaw=0.0):
    R.NADES = True                                                            # (the profile's bot_options nades=)
    clock = [100.0]
    bridge = NativeBridge()
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge)
    snap = R.snapshot(round_guest(enemies=enemies, cam_yaw=cam_yaw))
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5)}, guns={0x107: 0}, gun_ammo={0: 7})
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = 1e9
    return bot, bridge, clock, snap


def drive(bot, bridge, clock, snap, seconds):
    """The hook's equip answered at once (the bridge's last target in his hand), `seconds` of ticks."""
    acts = []
    for _ in range(int(seconds / 0.05)):
        clock[0] += 0.05
        acts.append(bot.tick(snap))
        if bridge.targets:
            snap["player"]["equipped"] = bridge.targets[-1]
    return acts


def test_one_grenade_in_hand_is_thrown_five_times_then_the_gun_comes_back():
    foes = ((0.0, 0.0, 700.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 900.0, 700))
    bot, bridge, clock, snap = nade_bot(foes)
    drive(bot, bridge, clock, snap, 4.0)
    assert bot.stats["nade_burst_throws"] >= R.NADE_BURST_N - 1
    assert bot.stats["frags"] + bot.stats["fires"] >= R.NADE_BURST_N
    grenade_requests = [t for t in bridge.targets if t in (9, 10)]
    assert grenade_requests[:1] == [9] and bridge.targets.count(9) == 1      # equipped once for the whole burst
    assert snap["player"]["equipped"] == 0                                    # the gun back by the hook after it


def test_never_into_the_void_off_his_floor_or_past_a_drop():
    below = ((0.0, -200.0, 700.0, 700),)                                      # two metres below: past a drop
    bot, bridge, clock, snap = nade_bot(below)
    drive(bot, bridge, clock, snap, 2.0)
    assert bot.nade is None and bot.stats["frags"] == 0 and bot.stats["nade_void_skips"] >= 1
    bot, bridge, clock, snap = nade_bot(())                                   # a frag in hand, nobody on his ground
    snap["player"]["equipped"] = 9
    out = run(bot, snap, clock, 1)[0]
    assert bot.stats["frags"] == 0 and bridge.targets == [0] and not {"zl", "zr"} & set(out.get("hold") or ())


def test_a_target_past_a_wall_or_a_drop_on_the_mesh_is_refused():
    class Mesh:
        C = [(0.0, 0.0, 0.0)]

        def locate(self, pt):
            return 0

        def clear(self, a, b):
            return False                                                      # a drop / wall between them
    bot, bridge, clock, snap = nade_bot(((0.0, 0.0, 700.0, 700),))
    snap["navmesh"] = Mesh()
    assert not bot._nade_ground_ok(snap["player"], snap["enemies"][0], snap, 0.0)


def test_the_grenade_is_pitched_down_at_their_feet_not_the_horizon():
    bot, bridge, clock, snap = nade_bot(((0.0, 0.0, 700.0, 700),))
    snap["camera"] = {"pos": (0.0, 180.0, -200.0), "target": (0.0, 180.0, 100.0), "yaw": 0.0, "pitch": 0.0}
    n = {"to": (0.0, 700.0), "to_y": 0.0}
    keys = set()
    for _ in range(3):
        keys |= set(bot._nade_aim_keys(snap["player"], n, snap))
    assert "rdown" in keys and "rup" not in keys and bot.stats["nade_ground_aims"] >= 1


def test_the_repeats_hold_half_the_first_throw_and_the_game_throws_twice_as_fast():
    assert R.NADE_REPEAT_THROW_S == R.NADE_THROW_S / 2 and R.NADE_REPEAT_AIM_S < R.NADE_AIM_S
    assert R.BURST_COOLDOWN_S == 36.0 and R.BURST_THROW_SPEED_X == 10.0
    assert M.fire_interval(0x13, 5.0, None, 10.0) == pytest.approx(M.FIRE_ORIGINAL[0x13] / 10)
    assert M.THROW_FIRE_MAX == 10.0


def cadence(seconds=60.0):
    """Throws a minute against a pack 7-9 m off that never thins (the hook answers at once; infinite grenades)."""
    foes = ((0.0, 0.0, 700.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 900.0, 700))
    bot, bridge, clock, snap = nade_bot(foes)
    drive(bot, bridge, clock, snap, seconds)
    return bot.stats["frags"] + bot.stats["fires"] + bot.stats["flashes"]


def test_the_cadence_against_a_pack_that_does_not_thin():
    n = cadence()
    assert n >= 40, n                                                        # main's code: 6 a minute here (10 s gap)


# --- QTEs by RAM, by default ----------------------------------------------------------------------------------------

def test_ensure_qte_turns_both_on_and_reads_back_and_keeps_an_operators_off():
    g = round_guest()
    from gbox import re6_switch_unlock as U
    ad = Adapter(g)
    M.ORIG.clear()
    info = g.alloc(0xAA28)
    import types
    orig = U.system_info
    U.system_info = lambda m, base: info
    try:
        out = M.ensure_qte(ad, clock=lambda: 10.0)
        assert out["verified"] and out["auto_qte"] and out["auto_qte_ram"]
        assert all(struct.unpack("<I", g.rd(info + off, 4))[0] == 1 for off in M.AUTO_QTE)
        M.run(ad, "auto_qte", on=False)                                       # the operator's off
        out = M.ensure_qte(ad, clock=lambda: 100.0)
        assert "operator" in out["reason"] and struct.unpack("<I", g.rd(info + M.AUTO_QTE[0], 4))[0] == 0
    finally:
        U.system_info = orig
        M.ORIG.clear()


def test_a_qte_prompt_is_pressed_the_tick_it_shows_in_a_crowd_and_counted():
    crowd = tuple((60.0 * i, 0.0, 200.0 + 20 * i, 700) for i in range(5))
    clock = [100.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=NativeBridge())
    snap = R.snapshot(round_guest(enemies=crowd))
    snap["player"].update(equipped=0)
    snap["prompts"] = [{"type": 1, "button": 8, "pad": 0x200, "key": "zr", "ab": 0x7000}]
    out = run(bot, snap, clock, 1)[0]
    assert bot.stats["qte_seen"] == 1 and bot.stats["qte_pressed"] == 1 and "zr" in ({out.get("tap")} | set(out.get("hold") or ()))
    snap["prompts"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["qte_failed"] == 0
    snap["prompts"] = [{"type": 2, "button": 8, "pad": 0x200, "key": "a", "ab": 0x7100}]
    R.PROMPTS = False                                                         # (no press this time)
    try:
        run(bot, snap, clock, 1)
    finally:
        R.PROMPTS = True
    snap["prompts"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["qte_failed"] == 1                                       # gone with neither press nor RAM
