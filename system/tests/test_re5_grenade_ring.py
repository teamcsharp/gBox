"""The RE5 grenade-ring: native controller ring geometry/kind gating and the grenade_ring op plumbing.

The ring reuses the live-verified flash spawn (0x118E820) and explode (0x118E9D0); only its per-grenade
position relocation and the 10x batch are new. These exercise the controller with a fake emulator (no live
calls) and the real durable queue / Pine live-controls validator.
"""
import math
import struct
import threading
import uuid
from types import SimpleNamespace

import pytest

from gbox.mercs import interventions as I
from gbox.mercs.titles import re5_switch_native as N
from gbox.store import Store

R = N.R
SPAWN, EXPLODE = 0x118E820, 0x118E9D0


def ring_controller(hp_after=1000, spawn_fail_at=None):
    """A fake RE5 native controller whose spawn/explode succeed, capturing every unit position write."""
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp = 0x200000000, 0x210000000
    ctl.generation = 0x100000002
    ctl.heap = 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.writes, ctl.spawns = {}, [], []
    hp_box = {"v": 1000}

    def put(at, data):
        ctl.mem.update({at + i: b for i, b in enumerate(data)})

    def read(at, n):
        if at == ctl.player + R.P_HP:
            return struct.pack("<h", hp_box["v"])
        return bytes(ctl.mem.get(at + i, 0) for i in range(n))

    def write(at, data):
        ctl.writes.append((at, bytes(data)))
        put(at, data)
    ctl.rd, ctl.write, ctl.put = read, write, put
    ctl.check = ctl.check_build = lambda: None
    ctl.attach = lambda: None
    ctl.detach_completed = lambda: None
    ctl.projectile = lambda unit, born: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.wait = lambda predicate, timeout=1.0: predicate()
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.player, struct.pack("<Q", ctl.base + 0x1C290C8))   # original vtable (Jill), read into self.original
    put(ctl.player + R.P_POS, struct.pack("<3f", 1000.0, 800.0, -2000.0))

    def call(off, *args):
        if off == SPAWN:
            n = len(ctl.spawns)
            if spawn_fail_at is not None and n == spawn_fail_at:
                return 0
            unit = 0x230000000 + n * 0x10000
            born = 5000 + n
            put(unit + 0x1A00, struct.pack("<Q", born))
            put(unit + 0x1B28, struct.pack("<I", 29))
            put(unit + 0x1B88, b"\x01")
            put(unit + 0x28A0, b"\x01")
            ctl.spawns.append(unit)
            hp_box["v"] = hp_after   # health reads back after the ring's blasts
            return unit
        return 1   # explode confirmed
    ctl.call = call
    return ctl


def unit_writes(ctl):
    """Position writes grouped per spawned unit: {unit: {offset: (x, y, z)}}."""
    out = {}
    for at, data in ctl.writes:
        for unit in ctl.spawns:
            if at in (unit + N.RING_UNIT_POS, unit + N.RING_UNIT_HOME):
                out.setdefault(unit, {})[at - unit] = struct.unpack("<3f", data)
    return out


def test_flash_ring_confirms_ten_evenly_spaced_expanding_grenades():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash")
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["op"] == "grenade_ring" and result["kind"] == "flash"
    assert result["requested"] == 10 and result["detonated"] == 10
    assert result["self_damage"] == 0 and result["hp_before"] == 1000 and result["hp_after"] == 1000
    assert len(result["grenades"]) == 10

    px, py, pz = 1000.0, 800.0, -2000.0
    placed = unit_writes(ctl)
    assert len(placed) == 10
    radii, angles = [], []
    for i, unit in enumerate(ctl.spawns):
        offs = placed[unit]
        # Both the live transform (+0x60) and the home copy (+0x2680) are relocated to the same point.
        assert offs[N.RING_UNIT_POS] == offs[N.RING_UNIT_HOME]
        x, y, z = offs[N.RING_UNIT_POS]
        assert y == pytest.approx(py)                         # the floor is kept
        radii.append(math.hypot(x - px, z - pz))
        angles.append(math.atan2(z - pz, x - px) % (2 * math.pi))
    # expand=True by default: the ring grows from the inner radius out to the final radius.
    assert radii[0] == pytest.approx(N.RING_INNER_DEFAULT_CM)
    assert radii[-1] == pytest.approx(N.RING_RADIUS_DEFAULT_CM)
    assert radii == sorted(radii)
    # evenly spaced around the circle
    for i, a in enumerate(angles):
        assert a == pytest.approx((2 * math.pi * i / 10) % (2 * math.pi), abs=1e-4)


def test_ring_radius_is_clamped_outward_for_self_safety():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash", radius_cm=10.0, expand=False)
    assert result["radius_cm"] == N.RING_SELF_CLEAR_CM
    px, py, pz = 1000.0, 800.0, -2000.0
    for offs in unit_writes(ctl).values():
        x, _y, z = offs[N.RING_UNIT_POS]
        assert math.hypot(x - px, z - pz) == pytest.approx(N.RING_SELF_CLEAR_CM)


@pytest.mark.parametrize("kind,match", [("hand", "not yet verified"), ("incendiary", "not yet verified"),
                                        ("bogus", "unknown grenade kind")])
def test_unverified_kinds_are_refused_and_never_substituted(kind, match):
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match=match):
        ctl.grenade_ring(kind)
    assert ctl.spawns == []   # nothing spawned


def test_partial_ring_is_uncertain_not_replayed_and_recoverable():
    ctl = ring_controller(spawn_fail_at=3)
    result = ctl.grenade_ring("flash", count=10)
    assert result["state"] == "uncertain" and result["verified"] is False
    assert result["detonated"] == 3 and result["requested"] == 10
    assert "refused" in result["reason"]
    assert ctl.failed and ctl.recoverable   # a new click is allowed; this one is never retried


def test_count_is_bounded():
    ctl = ring_controller()
    result = ctl.grenade_ring("flash", count=999)
    assert result["requested"] == N.RING_COUNT_MAX


def test_kind_options_mark_only_flash_available():
    rows = {r["kind"]: r for r in N.ring_kind_options()}
    assert rows["flash"]["available"] is True and not rows["flash"]["reason"]
    assert rows["hand"]["available"] is False and rows["hand"]["reason"]
    assert rows["incendiary"]["available"] is False


# ---- the durable queue op ----

@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    now = [100.0]
    q = I.Queue(store, lambda: now[0])
    q.claim("sid", "life-1", ["flash_now", "grenade_ring"])
    yield q, now
    store.db.close()


def test_grenade_ring_defaults_to_flash_and_keeps_kind(queue):
    q, _ = queue
    rid = str(uuid.uuid4())
    row = q.post("sid", "grenade_ring", rid, "viewer")
    assert row["args"] == {"kind": "flash"} and row["state"] == "queued"
    # a longer window than an ordinary flash: the ring runs ten spawn/explode pairs
    assert row["expires"] == 100.0 + I.GRENADE_RING_TTL
    row2 = q.post("sid", "grenade_ring", str(uuid.uuid4()), "viewer", {"kind": "hand"})
    assert row2["args"] == {"kind": "hand"}   # the queue carries the request; the controller refuses unverified kinds


def test_grenade_ring_rejects_bad_kind_and_fields_and_id_reuse(queue):
    q, _ = queue
    for args in ({"kind": "nuke"}, {"kind": "flash", "extra": 1}, {"item": 25}):
        with pytest.raises(ValueError):
            q.post("sid", "grenade_ring", str(uuid.uuid4()), "viewer", args)
    rid = str(uuid.uuid4())
    q.post("sid", "grenade_ring", rid, "viewer", {"kind": "flash"})
    with pytest.raises(ValueError, match="another operation"):
        q.post("sid", "grenade_ring", rid, "viewer", {"kind": "hand"})


def test_grenade_ring_claims_and_finishes_once(queue):
    q, _ = queue
    rid = str(uuid.uuid4())
    q.post("sid", "grenade_ring", rid, "viewer", {"kind": "flash"})
    claimed = q.claim("sid", "life-1", ["flash_now", "grenade_ring"])
    assert [r["id"] for r in claimed] == [rid]
    q.finish("sid", rid, claimed[0]["claim"],
             {"state": "confirmed", "verified": True, "op": "grenade_ring", "detonated": 10})
    assert q.status("sid")["requests"][0]["state"] == "confirmed"


# ---- Pine live-controls validation ----

def test_live_controls_validate_grenade_ring():
    from gbox import merc_live_controls as LC
    good = {"session_id": "s", "op": "grenade_ring", "request_id": str(uuid.uuid4()), "kind": "flash"}
    assert LC.validate_request(good) == "grenade_ring"
    assert LC.validate_request({"session_id": "s", "op": "grenade_ring", "request_id": str(uuid.uuid4())}) == "grenade_ring"
    with pytest.raises(ValueError, match="UUID"):
        LC.validate_request({"session_id": "s", "op": "grenade_ring", "request_id": "nope"})
    with pytest.raises(ValueError, match="kind"):
        LC.validate_request({"session_id": "s", "op": "grenade_ring", "request_id": str(uuid.uuid4()), "kind": "nuke"})
    with pytest.raises(ValueError):   # a stray field
        LC.validate_request({"session_id": "s", "op": "grenade_ring", "request_id": str(uuid.uuid4()), "item": 2})
