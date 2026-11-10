"""RE6 grenade classes as a spawn/detonate parameter (native/re6_061d2a06/classes.py).

No live game: the images are derived from the pinned, verified blobs and their two patched instructions checked
word for word; the controller runs against a fake emulator that records every native call and the class it was
handed.
"""
import hashlib
import struct
import threading

import pytest

from gbox.mercs.native.re6_061d2a06 import classes as C
from gbox.mercs.titles import re6_switch_native as N

R = N.R


# ---- the derived images ----------------------------------------------------------------------------------------------------

def test_the_parameterised_spawn_only_drops_the_two_instructions_that_built_the_dti():
    original = struct.unpack(f"<{len(C.IMAGES['spawn']) // 4}I", C.IMAGES["spawn"])
    patched = struct.unpack(f"<{len(C.SPAWN_CLASS_BYTES) // 4}I", C.SPAWN_CLASS_BYTES)
    assert patched[6] == patched[7] == C.NOP
    assert patched[:6] + patched[8:] == original[:6] + original[8:]
    assert len(C.SPAWN_CLASS_BYTES) == C.SPAWN_CLASS[2] == 256


def test_the_parameterised_detonate_moves_the_expected_class_into_x0():
    original = struct.unpack(f"<{len(C.IMAGES['detonate']) // 4}I", C.IMAGES["detonate"])
    patched = struct.unpack(f"<{len(C.DETONATE_CLASS_BYTES) // 4}I", C.DETONATE_CLASS_BYTES)
    assert patched[4] == C.MOV_X0_X4 and patched[5] == C.NOP
    assert patched[:4] + patched[6:] == original[:4] + original[6:]
    assert len(C.DETONATE_CLASS_BYTES) == C.DETONATE_CLASS[2] == 232


def test_a_changed_source_image_is_refused_instead_of_patched():
    broken = bytearray(C.IMAGES["spawn"])
    broken[24:28] = b"\x00\x00\x00\x00"
    original = C.IMAGES["spawn"]
    C.IMAGES["spawn"] = bytes(broken)
    try:
        with pytest.raises(ValueError, match="no longer builds the flash DTI"):
            C.spawn_with_class()
    finally:
        C.IMAGES["spawn"] = original


def test_the_pinned_class_images_carry_their_own_digests():
    assert C.SPAWN_CLASS[:3] == (0x18F2BC0, "spawn_class", 256)
    assert C.DETONATE_CLASS[:3] == (0x18F2CC0, "detonate_class", 232)
    assert C.SPAWN_CLASS[3] == hashlib.sha256(C.spawn_with_class()).hexdigest()
    assert C.DETONATE_CLASS[3] == hashlib.sha256(C.detonate_with_class()).hexdigest()
    # the verified originals keep their own pinned digests untouched
    assert hashlib.sha256(C.IMAGES["spawn"]).hexdigest() == \
        "5c5f9f0dca7ddbb01f1b7b1200ed99ffd49fa45db09e43c2bd6588b1ad97ae91"
    assert hashlib.sha256(C.IMAGES["detonate"]).hexdigest() == \
        "c7d90bc2a61aeaa6d617864b993278fabbd08230c02e6a4aa0c668d45c4fb941"


def test_image_bytes_serves_class_images_and_the_shipped_ones():
    assert C.image_bytes("spawn_class") == C.SPAWN_CLASS_BYTES
    assert C.image_bytes("detonate_class") == C.DETONATE_CLASS_BYTES
    assert C.image_bytes("spawn") == C.IMAGES["spawn"]
    assert C.image_bytes("spawn_bomb") == C.IMAGES["spawn_bomb"]


def test_the_class_table_matches_the_researched_dti_tree():
    assert set(C.CLASSES) == {"flash", "hand", "incendiary"}
    assert [(k, C.CLASSES[k].item) for k in ("flash", "hand", "incendiary")] == \
        [("flash", 0x115), ("hand", 0x113), ("incendiary", 0x114)]
    assert [C.CLASSES[k].dti for k in ("flash", "hand", "incendiary")] == \
        [0x2951500, 0x2951490, 0x29514C8]
    assert [C.CLASSES[k].vtable for k in ("flash", "hand", "incendiary")] == \
        [0x284AEB8, 0x284B788, 0x284B328]
    with pytest.raises(KeyError):
        C.class_for("nuke")


# ---- the controller path ---------------------------------------------------------------------------------------------------

def class_controller(unit_vtable=0x284B788, spawn_fail_at=None, position=(1000.0, 800.0, -2000.0)):
    """A fake RE6 controller: records every native call, installs nothing, and reports a unit of the given class."""
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp = 0x200000000, 0x210000000
    ctl.generation = 0x100000002
    ctl.manager = ctl.player + 0x13A8
    ctl.heap = 0x220000000
    ctl.lock = threading.RLock()
    ctl.failed = ctl.recoverable = False
    ctl.mem, ctl.writes, ctl.calls, ctl.ensured = {}, [], [], []
    ctl.pid, ctl.identity = 4242, (4242, 7)           # flash() checks the process identity before anything else
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
    ctl.q = lambda a: struct.unpack("<Q", read(a, 8))[0]
    ctl.w = lambda a: struct.unpack("<I", read(a, 4))[0]
    ctl.check = ctl.check_build = lambda: None
    ctl.attach = lambda: None
    ctl.detach_completed = lambda: None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.wait = lambda predicate, timeout=1.0: predicate()
    ctl._ensure_image = lambda image: ctl.ensured.append(image[1])
    put(ctl.base + R.S_PLAYER, struct.pack("<Q", ctl.sp))
    put(ctl.sp + R.P_FIRST, struct.pack("<Q", ctl.player))
    put(ctl.player, struct.pack("<Q", ctl.base + 0x2858318))
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))
    put(ctl.base + R.S_GAMEMAN, struct.pack("<Q", 0x90000000))
    put(0x90000000 + R.GM_PHASE, struct.pack("<i", R.PHASE_PLAYING))

    def call(off, *args):
        ctl.calls.append((off, args))
        if off in (0x18F2880, C.SPAWN_CLASS[0]):
            n = sum(1 for o, _a in ctl.calls if o in (0x18F2880, C.SPAWN_CLASS[0]))
            if spawn_fail_at is not None and n - 1 == spawn_fail_at:
                return 0
            unit = 0x230000000 + (n - 1) * 0x10000
            born = 5000 + n - 1
            put(unit, struct.pack("<Q", ctl.base + unit_vtable))
            put(unit + 0x1308, struct.pack("<I", born))
            put(unit + 0x1300, struct.pack("<Q", ctl.player))
            put(unit + 0x28A0, b"\x01")
            hp_box["v"] = 1000
            return unit
        return 1
    ctl.call = call
    return ctl


@pytest.fixture(autouse=True)
def _resources(monkeypatch):
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {0x113, 0x114, 0x115})
    monkeypatch.setattr(N.R, "unit_action", lambda m, unit: "cWpAction_wp_act_throw")
    monkeypatch.setattr(N.R, "game_man", lambda m, base: 0x90000000)
    monkeypatch.setattr(N, "process_identity", lambda pid: (pid, 7))
    yield


def test_a_hand_ring_spawns_the_hand_class_and_detonates_the_class_it_carries():
    ctl = class_controller(unit_vtable=C.CLASSES["hand"].vtable)
    result = ctl.grenade_ring("hand", allow_unverified=True, count=2, expand=False)
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["kind"] == "hand" and result["detonated"] == 2
    assert result["effect"] == "native_hand_ring"
    spawns = [c for c in ctl.calls if c[0] == C.SPAWN_CLASS[0]]
    assert len(spawns) == 2 and all(args == (ctl.player, 0x2951490) for _off, args in spawns)
    detonations = [c for c in ctl.calls if c[0] == C.DETONATE_CLASS[0]]
    assert len(detonations) == 2
    for _off, args in detonations:
        unit, player, born, generation, carried = args
        assert player == ctl.player and generation == ctl.generation
        assert carried == ctl.base + C.CLASSES["hand"].vtable
    assert set(ctl.ensured) == {"spawn_class", "detonate_class"}
    assert [g["class_vtable"] for g in result["grenades"]] == \
        [hex(ctl.base + C.CLASSES["hand"].vtable)] * 2


def test_the_flash_ring_still_uses_the_shipped_verified_pair():
    ctl = class_controller()
    result = ctl.grenade_ring("flash", count=1)
    assert result["state"] == "confirmed" and result["effect"] == "native_flash_ring"
    assert [c[0] for c in ctl.calls] == [0x18F2880, 0x18F29C0]
    assert ctl.ensured == []                         # nothing extra installed for the verified path


@pytest.mark.parametrize("kind", ["hand", "incendiary"])
def test_an_unverified_kind_is_refused_without_the_probe_flag(kind):
    ctl = class_controller()
    with pytest.raises(N.Unavailable, match="not yet verified"):
        ctl.grenade_ring(kind)
    assert ctl.calls == []


def test_an_unknown_kind_is_refused_before_any_native_call():
    ctl = class_controller()
    with pytest.raises(N.Unavailable, match="unknown grenade kind"):
        ctl.grenade_ring("nuke", allow_unverified=True)
    assert ctl.calls == []


@pytest.mark.parametrize("kind,item", [("hand", 0x113), ("incendiary", 0x114)])
def test_a_class_whose_resources_are_not_loaded_is_refused(monkeypatch, kind, item):
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {0x115})
    ctl = class_controller()
    with pytest.raises(N.Unavailable, match=f"{kind} resources"):
        ctl.grenade_ring(kind, allow_unverified=True)
    assert ctl.calls == []


def test_only_the_verified_kinds_are_advertised():
    rows = {r["kind"]: r for r in N.Controller.grenade_kinds(class_controller())}
    assert rows["flash"]["available"] is True
    for kind in ("hand", "incendiary"):
        assert rows[kind]["available"] is False and rows[kind]["reason"]
    assert set(N.RING_IMPLEMENTED_KINDS) == {"flash", "hand", "incendiary"}


def test_the_single_flash_op_keeps_its_own_guard_and_verified_pair():
    ctl = class_controller()
    result = ctl.flash()
    assert result["state"] == "confirmed" and result["effect"] == "native_flash_explosion"
    assert [c[0] for c in ctl.calls] == [0x18F2880, 0x18F29C0]
    assert ctl.ensured == []


def test_the_single_flash_op_refuses_without_its_resources(monkeypatch):
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: set())
    ctl = class_controller()
    with pytest.raises(N.Unavailable, match="flash resources"):
        ctl.flash()
    assert ctl.calls == []


def test_an_explicit_class_in_the_barrage_is_the_receipt_probe():
    ctl = class_controller(unit_vtable=C.CLASSES["hand"].vtable)
    result = ctl.grenade_scatter("hand", count=2, toward=[(1500.0, -2000.0)])
    assert result["state"] == "confirmed" and result["kind"] == "hand"
    assert result["probe"] is True and result["kinds"] == ["hand"]
    assert [c[0] for c in ctl.calls if c[0] == C.SPAWN_CLASS[0]]
    detonations = [c for c in ctl.calls if c[0] == C.DETONATE_CLASS[0]]
    assert all(args[4] == ctl.base + C.CLASSES["hand"].vtable for _o, args in detonations)


def test_the_default_barrage_stays_on_the_verified_kind_and_is_not_a_probe():
    ctl = class_controller()
    result = ctl.grenade_scatter("random", count=2, toward=[(1500.0, -2000.0)])
    assert result["state"] == "confirmed" and result["kinds"] == ["flash"]
    assert "probe" not in result
    assert ctl.ensured == []

# ---- the cave vetting tool -------------------------------------------------------------------------------------------------

def _load_tool():
    import importlib.util
    from pathlib import Path
    path = Path(N.__file__).resolve().parents[3] / "tools" / "verify_re6_classes.py"
    spec = importlib.util.spec_from_file_location("verify_re6_classes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_cave_scanner_finds_a_hole_and_a_reference_into_it():
    tool = _load_tool()
    size = tool.TEXT_END + 0x1000
    image = bytearray(size)
    ranges = [(C.SPAWN_CLASS[0], C.SPAWN_CLASS[2], "spawn_class")]
    clean = tool.scan(bytes(image), ranges)
    assert clean["holes"] == {"spawn_class": True} and clean["references"] == []
    # one B instruction into the cave must be seen (and the hole is then not installable)
    pc = 0x1000
    delta = (C.SPAWN_CLASS[0] - pc) // 4
    struct.pack_into("<I", image, pc, 0x14000000 | (delta & 0x3FFFFFF))
    caught = tool.scan(bytes(image), ranges)
    assert caught["holes"] == {"spawn_class": True}
    assert [(r["cave"], r["kind"], r["target"]) for r in caught["references"]] == \
        [("spawn_class", "instruction", hex(C.SPAWN_CLASS[0]))]
    # a non-zero byte in the cave is not a hole
    image[C.SPAWN_CLASS[0]] = 0x01
    assert tool.scan(bytes(image), ranges)["holes"] == {"spawn_class": False}