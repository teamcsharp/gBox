"""RE6 Switch grenade ring (re6_switch_native.Controller.grenade_ring / grenade_kinds / grenade_ring_now) on a fake
guest laid out like the live 061D2A06 process: the real attach / mailbox / call / wait / detach code runs, and a
fake game thread answers the private mailbox the way the pinned native images do (the bootstrap, spawn_at and
detonate_at, whose own ARM64 ABI tests live beside their sources in gbox/mercs/native/re6_061d2a06)."""
import hashlib
import json
import math
import struct
import threading
import time

import pytest

from gbox.mercs import interventions as I
from gbox.mercs.titles import re5_switch_native as N5
from gbox.mercs.titles import re6_switch_native as N
from test_re6_switch import BASE, Guest

R = N.R
IDENTITY = (4242, 777)
CLASS_OF = {BASE + dti: BASE + vt for _item, dti, vt, _cls in N.GRENADES.values()}


def f32(bits):
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


class Game:
    """Guest memory + a game thread that consumes the controller's mailbox publications synchronously."""

    def __init__(self, carried=(0x113, 0x114, 0x115), hp=900, pos=(1000.0, 50.0, -2000.0)):
        self.g = g = Guest()
        self.calls, self.writes = [], []
        self.stall = False            # the next published call is never consumed (a stuck game thread)
        self.on_spawn = None          # hook(unit, index) after each spawn
        self.on_detonate = None       # hook(unit) before a detonation runs
        self.next_gen = 500
        gm = g.alloc(0x5000)
        g.q(BASE + R.S_GAMEMAN, gm)
        g.i32(gm + R.GM_PHASE, R.PHASE_PLAYING)
        self.gm = gm
        self.sp = g.alloc(0x100)
        g.q(BASE + R.S_PLAYER, self.sp)
        self.player = p = g.alloc(0x8000)
        g.q(self.sp + R.P_FIRST, p)
        g.f32(p + R.P_POS, *pos)
        g.put(p + R.P_HP, struct.pack("<hh", hp, 900))
        g.put(p + 0x1308, struct.pack("<I", 34))
        for i, item in enumerate(carried):           # live item-wheel slots: +0x8 in use, +0x9 index, +0xA type
            slot = p + R.P_SLOTS + R.SLOT_STRIDE * (7 + i)
            g.put(slot + 8, bytes([1, 7 + i]))
            g.put(slot + 0xA, struct.pack("<H", item))
            g.put(slot + 0xE, struct.pack("<h", 3))
        self.manager = p + 0x13A8
        g.put(BASE + N.VT, struct.pack("<11Q", *(BASE + x for x in N.VT_ENTRIES)))
        g.q(self.manager, BASE + N.VT)
        g.q(self.manager + 8, p)
        self.heap = None
        self.units = []

    # -- the adapter the controller talks to ------------------------------------------------------------------------
    address_mode = "direct"

    def read_memory(self, a, n):
        return self.g.rd(a, n)

    def write_memory(self, a, data):
        data = bytes(data)
        self.writes.append((a, data))
        self.g.put(a, data)
        if a == self.manager and data == struct.pack("<Q", BASE + N.TEMP):
            self._bootstrap()
        elif self.heap is not None and a == self.heap + 0xA8 and data == b"\1\0\0\0" and not self.stall:
            self._dispatch()
        return {"verified": True}

    def _guest(self):
        return IDENTITY[0], {"base": 0, "mapped": self.g.rows()}

    # -- the native side (call.S bootstrap/dispatcher, spawn_at.c, detonate_at.c) ---------------------------------
    def _bootstrap(self):
        h = self.heap = self.g.alloc(0x400)
        self.g.put(h, self.g.rd(BASE + N.VT, 0x58))
        self.g.q(h + 0x48, BASE + N.DISPATCH)
        self.g.q(h + 0x80, BASE + N.VT)
        self.g.q(h + 0x88, BASE + N.UPDATE)
        self.g.q(h + 0x90, self.player)
        self.g.put(h + 0x98, self.g.rd(self.player + 0x1308, 4))
        self.g.put(h + 0xA0, b"GBXNC001")
        self.g.q(self.manager, h)

    def u(self, a):
        return struct.unpack("<Q", self.g.rd(a, 8))[0]

    def w(self, a):
        return struct.unpack("<I", self.g.rd(a, 4))[0]

    def _dispatch(self):
        h = self.heap
        fn, *args = struct.unpack("<9Q", self.g.rd(h + 0xC0, 72))
        self.calls.append((fn - BASE, tuple(args)))
        self.g.put(h + 0xA8, b"\2\0\0\0")
        result = {BASE + N.SPAWN_AT: self._spawn_at, BASE + N.DETONATE_AT: self._detonate_at}[fn](*args)
        self.g.q(h + 0xB8, result)
        self.g.put(h + 0xA8, b"\3\0\0\0")

    def _spawn_at(self, player, dti, x, y, z, *_):
        if dti not in CLASS_OF:
            return 0
        unit = self.g.alloc(0x4000)
        action = self.g.alloc(0x80)
        self.g.q(action, BASE + N.THROW_VT)
        self.g.q(unit, CLASS_OF[dti])
        self.g.q(unit + 0x1300, player)
        self.g.put(unit + 0x1308, struct.pack("<I", self.next_gen))
        self.next_gen += 1
        self.g.put(unit + 0x60, struct.pack("<III", x, y, z))
        self.g.q(unit + 0x13A8, BASE + N.VT)
        self.g.q(unit + 0x13B0, unit)
        self.g.q(unit + 0x13F0, action)
        self.units.append(unit)
        if self.on_spawn:
            self.on_spawn(unit, len(self.units) - 1)
        return unit

    def _detonate_at(self, unit, player, generation, player_generation, vt, x, z, *_):
        if self.on_detonate:
            self.on_detonate(unit)
        if vt not in CLASS_OF.values() or self.u(unit) != vt or self.u(unit + 0x1300) != player:
            return 0
        if self.w(unit + 0x1308) != generation or self.w(player + 0x1308) != player_generation:
            return 0
        action = self.u(unit + 0x13F0)
        if self.u(action) == BASE + N.BOMB_VT:
            return 2
        if self.u(action) != BASE + N.THROW_VT:
            return 0
        self.g.put(unit + 0x60, struct.pack("<I", x))
        self.g.put(unit + 0x68, struct.pack("<I", z))
        self.g.q(action, BASE + N.BOMB_VT)
        return 1

    # -- helpers ----------------------------------------------------------------------------------------------------
    def spawns(self):
        return [args for fn, args in self.calls if fn == N.SPAWN_AT]

    def detonations(self):
        return [args for fn, args in self.calls if fn == N.DETONATE_AT]

    def new_life(self):
        self.g.put(self.player + 0x1308, struct.pack("<I", 35))


def controller(game, monkeypatch):
    monkeypatch.setattr(N, "process_identity", lambda pid: IDENTITY)
    ctl = N.Controller.__new__(N.Controller)
    ctl.ad, ctl.pid, ctl.identity = game, IDENTITY[0], IDENTITY
    ctl.lock = threading.RLock()
    ctl.base, ctl.heap, ctl.failed = BASE, None, False
    ctl.installed = []

    def install(at, data):                    # into zero padding only, as the real install() refuses otherwise
        before = game.g.rd(at, len(data))
        if before != data:
            assert not any(before), f"padding occupied at {at - BASE:#x}"
            game.g.put(at, data)
            ctl.installed.append(at - BASE)
    ctl.install = install
    ctl.stopped = lambda fn: fn()
    return ctl


@pytest.fixture
def game():
    return Game()


@pytest.fixture
def ctl(game, monkeypatch):
    return controller(game, monkeypatch)


def placed(game):
    return [(f32(x), f32(y), f32(z)) for _player, _dti, x, y, z, *_ in game.spawns()]


# --- the pinned images ---------------------------------------------------------------------------------------------

def test_ring_images_are_pinned_and_fit_the_padding_after_the_flash_images():
    spans = []
    for off, name, size, digest in N.CODE + N.RING_CODE:
        data = N.IMAGES[name]
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
        spans.append((off, off + size))
    spans.sort()
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))            # no overlap
    for off, _name, size, _digest in N.RING_CODE:
        assert 0x18F2AA8 <= off and off + size <= 0x18F3000                # zero padding up to the page end
    assert {kind: cls for kind, (_i, _d, _v, cls) in N.GRENADES.items()} == {
        "flash": "uWp1095", "hand": "uWp1091", "incendiary": "uWp1093"}


def test_classes_match_the_items_their_ids_name():
    # uWpBomb's setup stores (DTI id >> 8) & 0xFFFF as the kind; ids are 0x07011100 + 0x201/0x301/0x401.
    ids = {"hand": 0x07011100 + 0x201, "incendiary": 0x07011100 + 0x301, "flash": 0x07011100 + 0x401}
    for kind, (item, *_rest) in N.GRENADES.items():
        assert (ids[kind] >> 8) & 0xFFFF == item
    assert {N.GRENADES[k][0] for k in ("hand", "incendiary", "flash")} == {
        R.NADE_TYPES["frag"], R.NADE_TYPES["fire"], R.NADE_TYPES["flash"]}


# --- geometry, receipts --------------------------------------------------------------------------------------------

def test_flash_ring_spawns_ten_blooming_out_then_sets_them_off(ctl, game):
    result = ctl.grenade_ring("flash")
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["op"] == "grenade_ring" and result["kind"] == "flash" and result["class"] == "uWp1095"
    assert result["requested"] == result["spawned"] == result["detonated"] == 10 and result["natural"] == 0
    assert result["centre"] == [1000.0, 50.0, -2000.0] and result["radius_cm"] == 600.0
    assert result["inner_cm"] == 150.0 and result["self_damage"] == 0 and result["elapsed_ms"] >= 0
    # every spawn precedes every explosion (the ring blooms out, then is set off), in the same order
    kinds = [fn for fn, _ in game.calls]
    assert kinds == [N.SPAWN_AT] * 10 + [N.DETONATE_AT] * 10
    assert [a[0] for a in game.detonations()] == game.units
    radii, angles = [], []
    for x, y, z in placed(game):
        assert y == pytest.approx(50.0)
        radii.append(math.hypot(x - 1000.0, z + 2000.0))
        angles.append(math.atan2(z + 2000.0, x - 1000.0) % (2 * math.pi))
    assert radii[0] == pytest.approx(150.0, abs=1e-3) and radii[-1] == pytest.approx(600.0, abs=1e-3)
    assert radii == sorted(radii)
    for i, a in enumerate(angles):
        assert a == pytest.approx(2 * math.pi * i / 10 % (2 * math.pi), abs=1e-4)
    # the class each call names: the flash DTI to spawn, its vtable to set off, the player and both generations
    for player, dti, *_ in game.spawns():
        assert player == game.player and dti == BASE + 0x2951500
    for unit, player, gen, pgen, vt, x, z, _ in game.detonations():
        assert player == game.player and pgen == 34 and vt == BASE + 0x284AEB8
        assert gen == struct.unpack("<I", game.g.rd(unit + 0x1308, 4))[0]
        assert (f32(x), f32(z)) == tuple(struct.unpack("<f", game.g.rd(unit + o, 4))[0] for o in (0x60, 0x68))
    assert [g["state"] for g in result["grenades"]] == ["detonated"] * 10
    # the ring images were installed into the padding; the manager's own table is restored afterwards
    assert set(ctl.installed) >= {N.SPAWN_AT, N.DETONATE_AT}
    assert game.u(game.manager) == BASE + N.VT and not ctl.failed
    assert len(json.dumps(result)) < 4096


def test_a_second_ring_reuses_the_mailbox_without_reinstalling(ctl, game):
    assert ctl.grenade_ring("flash", count=3)["state"] == "confirmed"
    installed = list(ctl.installed)
    heap = game.heap
    assert ctl.grenade_ring("flash", count=3)["state"] == "confirmed"
    assert ctl.installed == installed and game.heap == heap and len(game.units) == 6


@pytest.mark.parametrize("kind,dti,vt", [("hand", 0x2951490, 0x284B788), ("incendiary", 0x29514C8, 0x284B328)])
def test_explosive_kinds_use_their_class_and_keep_clear_of_him(ctl, game, kind, dti, vt):
    result = ctl.grenade_ring(kind, radius_cm=100.0, inner_cm=0.0, allow_unverified=True)
    assert result["state"] == "confirmed" and result["kind"] == kind
    assert result["radius_cm"] == result["inner_cm"] == N.RING_SELF_CLEAR_CM[kind]
    assert {a[1] for a in game.spawns()} == {BASE + dti}
    assert {a[4] for a in game.detonations()} == {BASE + vt}
    for x, _y, z in placed(game):
        assert math.hypot(x - 1000.0, z + 2000.0) >= N.RING_SELF_CLEAR_CM[kind] - 1e-3


def test_self_damage_is_read_back(ctl, game):
    game.on_detonate = lambda unit: game.g.put(game.player + R.P_HP, struct.pack("<h", 850))
    result = ctl.grenade_ring("hand", count=2, allow_unverified=True)
    assert result["hp_before"] == 900 and result["hp_after"] == 850 and result["self_damage"] == 50


def test_count_radius_and_arguments_are_bounded(ctl, game):
    result = ctl.grenade_ring("flash", count=99, radius_cm=1e6, expand=False)
    assert result["requested"] == N.RING_COUNT_MAX == len(game.spawns())
    assert result["radius_cm"] == N.RING_RADIUS_MAX_CM
    for x, _y, z in placed(game):
        assert math.hypot(x - 1000.0, z + 2000.0) == pytest.approx(N.RING_RADIUS_MAX_CM, rel=1e-5)
    for bad in ({"count": 0}, {"count": True}, {"radius_cm": float("nan")}, {"radius_cm": "6"},
                {"ripple_ms": float("inf")}, {"deadline_s": "2"}):
        with pytest.raises(N.Unavailable):
            ctl.grenade_ring("flash", **bad)


# --- kind availability ---------------------------------------------------------------------------------------------

def test_kinds_offer_flash_only_when_carried_and_never_the_unverified_ones(monkeypatch):
    game = Game(carried=(0x113, 0x114, 0x115))
    rows = {r["kind"]: r for r in controller(game, monkeypatch).grenade_kinds()}
    assert list(rows) == ["flash", "hand", "incendiary"]
    assert rows["flash"] == {"kind": "flash", "available": True, "reason": ""}
    for kind in ("hand", "incendiary"):
        assert rows[kind]["available"] is False and "live-verified" in rows[kind]["reason"]
    game = Game(carried=(0x113,))
    rows = {r["kind"]: r for r in controller(game, monkeypatch).grenade_kinds()}
    assert rows["flash"]["available"] is False and "0x115" in rows["flash"]["reason"]
    assert not game.writes                                                  # read-only


def test_kind_rows_pass_the_claim_endpoint_shape(ctl):
    rows = ctl.grenade_kinds()
    assert len({r["kind"] for r in rows}) == len(rows) <= len(I.GRENADE_RING_KINDS)
    assert all(r["kind"] in I.GRENADE_RING_KINDS and type(r["available"]) is bool and len(r["reason"]) <= 300
               for r in rows)


def test_kinds_never_raise_outside_a_round(monkeypatch):
    game = Game()
    game.g.i32(game.gm + R.GM_PHASE, R.PHASE_OVER)
    rows = controller(game, monkeypatch).grenade_kinds()
    assert [r["available"] for r in rows] == [False] * 3 and all("Mercenaries round" in r["reason"] for r in rows)

    class Broken(Game):
        def read_memory(self, a, n):
            raise OSError("process gone")
    rows = controller(Broken(), monkeypatch).grenade_kinds()
    assert [r["available"] for r in rows] == [False] * 3 and all(r["reason"] for r in rows)


@pytest.mark.parametrize("kind,carried,allow,match", [
    ("hand", (0x113,), False, "live-verified"), ("incendiary", (0x114,), False, "live-verified"),
    ("flash", (0x113, 0x114), False, "0x115"), ("hand", (0x115,), True, "0x113"),
    ("remote", (0x116,), True, "unknown grenade kind"), (7, (), True, "unknown grenade kind")])
def test_unavailable_kinds_refuse_before_any_game_write(monkeypatch, kind, carried, allow, match):
    game = Game(carried=carried)
    with pytest.raises(N.Unavailable, match=match):
        controller(game, monkeypatch).grenade_ring(kind, allow_unverified=allow)
    assert not game.writes and not game.calls


def test_no_living_player_refuses(monkeypatch):
    game = Game()
    game.g.put(game.player + R.P_HP, struct.pack("<h", 0))
    with pytest.raises(N.Unavailable):
        controller(game, monkeypatch).grenade_ring("flash")
    assert not game.writes


# --- fencing, partial outcomes, deadlines --------------------------------------------------------------------------

def test_a_new_player_life_mid_ring_stops_it_unreplayed(ctl, game):
    game.on_spawn = lambda unit, i: game.new_life() if i == 3 else None
    result = ctl.grenade_ring("flash")
    assert result["state"] == "uncertain" and result["verified"] is False
    # the 4th spawn ran natively, but its completion was read after the fence tripped: counted only as uncertain
    assert result["spawned"] == 3 and result["detonated"] == 0 and "player allocation changed" in result["reason"]
    assert len(game.spawns()) == 4 and not game.detonations()
    assert ctl.failed and ctl.recoverable                     # a new request only after the mailbox is verified done


def test_a_grenade_that_already_exploded_counts_and_is_never_requested_again(ctl, game):
    def early(unit, i):
        if i == 2:                                  # its own contact check set it off before we got to it
            game.g.q(game.u(unit + 0x13F0), BASE + N.BOMB_VT)
    game.on_spawn = early
    result = ctl.grenade_ring("flash", count=5)
    assert result["state"] == "confirmed" and result["detonated"] == 5 and result["natural"] == 1
    assert game.units[2] not in [a[0] for a in game.detonations()] and len(game.detonations()) == 4
    assert result["grenades"][2]["state"] == "exploding"


def test_a_lost_allocation_is_reported_uncertain(ctl, game):
    # the game reclaims grenade 1 (its allocation generation changes) while grenade 2 is being spawned
    game.on_spawn = lambda unit, i: game.g.put(game.units[1] + 0x1308, b"\0\0\0\0") if i == 2 else None
    result = ctl.grenade_ring("flash", count=4)
    assert result["state"] == "uncertain" and result["detonated"] == 3 and result["spawned"] == 4
    assert result["grenades"][1]["state"] == "lost" and len(game.detonations()) == 3
    assert not ctl.failed                                       # the mailbox itself completed every call


def test_a_refused_allocation_ends_the_spawning(ctl, game):
    real = game._spawn_at
    game._spawn_at = lambda *a: 0 if len(game.units) == 6 else real(*a)
    result = ctl.grenade_ring("flash")
    assert result["state"] == "uncertain" and result["spawned"] == 6 and result["detonated"] == 6
    assert "allocation refused" in result["reason"] and len(game.spawns()) == 7


def test_a_stuck_game_thread_ends_by_the_deadline_and_is_never_replayed(ctl, game):
    assert ctl.grenade_ring("flash", count=2)["state"] == "confirmed"   # bootstrapped
    game.stall = True
    t = time.monotonic()
    result = ctl.grenade_ring("flash", deadline_s=0.6)
    assert time.monotonic() - t < 0.6 + 0.25
    assert result["state"] == "uncertain" and result["spawned"] == 0 and "uncertain" in result["reason"]
    assert ctl.failed and ctl.recoverable
    calls = len(game.calls)
    # the pending call keeps the dispatcher attached and blocks every later op until it completes
    assert game.u(game.manager) == game.heap
    with pytest.raises(N.Unavailable, match="recovery"):
        ctl.grenade_ring("flash")
    game._re6_native_flash = ctl
    out = N.grenade_ring_now(game, "flash")
    assert out["state"] == "unavailable" and "recovery" in out["reason"]
    assert len(game.calls) == calls                       # nothing was replayed
    # the game thread finally runs the old call: the next request recovers and runs normally
    game.stall = False
    game._dispatch()
    assert ctl.grenade_ring("flash", count=2)["state"] == "confirmed"
    assert len(game.spawns()) == 2 + 1 + 2


def test_the_deadline_stops_publishing_new_calls(ctl, game, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(N.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(N.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    game.on_spawn = lambda unit, i: clock.__setitem__(0, clock[0] + 0.3)        # each spawn: 0.3 s of game time
    result = ctl.grenade_ring("flash", deadline_s=1.0)
    assert result["state"] == "uncertain" and result["spawned"] == 3 and result["detonated"] == 0
    assert "deadline" in result["reason"] and not ctl.failed and result["deadline_s"] == 1.0


# --- the bot's entry point -----------------------------------------------------------------------------------------

def test_grenade_ring_now_shares_the_sessions_controller(ctl, game):
    game._re6_native_flash = ctl
    out = N.grenade_ring_now(game, "flash", radius_cm=800.0)
    assert out["state"] == "confirmed" and out["kind"] == "flash" and out["radius_cm"] == 800.0
    for key in ("spawned", "detonated", "elapsed_ms", "centre"):
        assert key in out
    out = N.grenade_ring_now(game)                                     # the bot's default: hand grenades
    assert out["state"] == "unavailable" and out["kind"] == "hand" and "live-verified" in out["reason"]
    assert out["spawned"] == 0 and out["detonated"] == 0 and "elapsed_ms" in out and out["centre"] is None


def test_grenade_ring_now_creates_the_controller_once_under_the_shared_lock(monkeypatch, game):
    made = []

    class Fake:
        def __init__(self, ad):
            made.append(ad)

        def grenade_ring(self, kind, **kw):
            assert N._CREATE_LOCK.acquire(blocking=False)            # the creation lock is not held while it runs
            N._CREATE_LOCK.release()
            return {"state": "confirmed", "verified": True, "kind": kind, **kw}
    monkeypatch.setattr(N, "Controller", Fake)
    assert N.grenade_ring_now(game, "flash")["state"] == "confirmed"
    assert N.grenade_ring_now(game, "flash")["state"] == "confirmed"
    assert made == [game] and isinstance(game._re6_native_flash, Fake)


def test_grenade_ring_now_never_raises(monkeypatch, game):
    def unsupported(ad):
        raise N.Unavailable("native flash currently requires Linux Switch NCE")
    monkeypatch.setattr(N, "Controller", unsupported)
    out = N.grenade_ring_now(game, "flash")
    assert out["state"] == "unavailable" and "Linux Switch NCE" in out["reason"]

    class Boom:
        def grenade_ring(self, *a, **kw):
            raise KeyError("bug")
    game._re6_native_flash = Boom()
    assert N.grenade_ring_now(game, "flash")["state"] == "failed"

    class Late:
        def grenade_ring(self, *a, **kw):
            raise N.Uncertain("native completion uncertain")
    game._re6_native_flash = Late()
    assert N.grenade_ring_now(game, "flash")["state"] == "uncertain"
    game._re6_native_flash = object()
    assert N.grenade_ring_now(game, "flash")["state"] == "unavailable"
    assert N.grenade_ring_now(game, "flash", deadline_s=float("nan"))["state"] == "unavailable"


def test_grenade_ring_now_gives_up_on_a_busy_controller_by_its_deadline(ctl, game):
    game._re6_native_flash = ctl
    held, release = threading.Event(), threading.Event()

    def ui_operation():                           # a viewer's flash or weapon change holding the native lock
        with ctl.lock:
            held.set()
            release.wait(5)
    t = threading.Thread(target=ui_operation)
    t.start()
    held.wait(5)
    try:
        started = time.monotonic()
        out = N.grenade_ring_now(game, "flash", deadline_s=0.5)
        assert time.monotonic() - started < 0.75
        assert out["state"] == "unavailable" and "busy" in out["reason"] and not game.calls
    finally:
        release.set()
        t.join()
    assert N.grenade_ring_now(game, "flash")["state"] == "confirmed"


def test_concurrent_bot_and_viewer_rings_serialize(ctl, game):
    game._re6_native_flash = ctl
    results = []
    threads = [threading.Thread(target=lambda: results.append(N.grenade_ring_now(game, "flash", count=4)))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r["state"] for r in results] == ["confirmed", "confirmed"]
    kinds = [fn for fn, _ in game.calls]
    assert kinds == ([N.SPAWN_AT] * 4 + [N.DETONATE_AT] * 4) * 2              # never interleaved


# --- the controller family -----------------------------------------------------------------------------------------

def test_re5_does_not_inherit_the_re6_chooser():
    assert N5.Controller.grenade_kinds is None and callable(N5.Controller.grenade_ring)


def test_the_worker_offers_the_ring_for_re6():
    assert callable(getattr(N.Controller, "grenade_ring", None)) and callable(N.Controller.grenade_kinds)
    assert set(N.RING_KINDS) <= set(I.GRENADE_RING_KINDS)
