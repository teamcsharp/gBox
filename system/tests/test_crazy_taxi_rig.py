"""Driver skeleton is code-driven in main.dol (GCTE51): translate constants, pose-array words and shape slots."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gbox.crazy_taxi as ct  # noqa: E402
from test_crazy_taxi_shape_tables import _dol, EV  # noqa: E402


def _near(a, b):
    return all(abs(x - y) < 1e-4 for x, y in zip(a, b))


def test_driver_rig_constants():
    d = _dol()
    ev = ct.driver_rig_from_dol(d)
    tr = [e["v"] for e in ev if e["op"] == "trans"]
    # left/right mirror in z; shoulder, elbow(forearm), wrist, hip, knee, ankle offsets
    assert _near(tr[0], (3.6611, 0.056, -1.7876)) and _near(tr[1], (2.508, 0.0, -1.7876))
    assert _near(tr[2], (2.5145, 0.0, -1.7876))
    mirrored = [(a, b) for a, b in zip(tr, tr[3:]) if abs(a[2] + b[2]) < 1e-4 and abs(a[2]) > 1]
    assert mirrored, "right side must mirror the left in z"
    assert any(_near(t, (1.1603, 0.1486, -1.1764)) for t in tr) and any(_near(t, (1.1603, 0.1486, 1.1764)) for t in tr)
    assert any(_near(t, (4.051, 0.0, -1.1764)) for t in tr) and any(_near(t, (4.2466, 0.0, 1.1764)) for t in tr)
    # pose-array words consumed by joint (r26): 0x14 l-shoulder, 0x1c l-elbow, 0x20/0x28 right arm, 0x2c.. legs
    pose = [e["v"] for e in ev if e["op"] == "pose"]
    assert pose[:3] == [0x14, 0x1C, 0x20] and 0x44 in pose
    slots = [e["v"] for e in ev if e["op"] == "slot"]
    # arm chain slots: kata 0x10/0x1c, ude 0xc/0x18, te 0x8/0x14 ; chest 0x3c ; legs 0x2c/0x28/0x24 and 0x38/0x34/0x30
    for s in (0x10, 0xC, 0x8, 0x1C, 0x18, 0x14, 0x3C, 0x2C, 0x28, 0x24, 0x38, 0x34, 0x30):
        assert s in slots


def test_variant_parts_drawn_by_index():
    """The B/C/D head & shoulder variants are drawn via registry indices 0x471+n by the same function family."""
    d = _dol()
    import struct
    names = EV["tables"]["0x80203d8c"]["plyrA_names"]
    i = names.index("MP_YH_plyrA_atamaB.shp")
    assert 0x471 + i == 0x472  # registry index == table position + 0x471
    o = ct.dol_va_to_offset(d, 0x8005d234)
    assert struct.unpack_from(">I", d, o)[0] == 0x38600472  # li r3,0x472 (atamaB) in the car-type switch


def test_driver_slot_tables_owner_0x8005cd1c():
    d = _dol()
    # prologue: mr r26,r3 ; mr r31,r4 ; lwzx r25,(0x801ddc70),r31*4
    o = ct.dol_va_to_offset(d, ct.DRIVER_POSE_FN)
    w = struct.unpack_from(">12I", d, o)
    assert w[0] >> 16 == 0x9421 and w[1] == 0x7c0802a6 and 0x7c7a1b78 in struct.unpack_from(">20I", d, o)  # mflr; mr r26,r3
    t = ct.driver_slot_tables_from_dol(d)
    assert len(t) == 54 and all(len(r) == 16 for r in t)
    assert t[0][1:4] == [0x462, 0x463, 0x464] and t[1][1] == 0x471 and t[2][1] == 0x4a7
    # variant tables are laid out 0x40 apart
    p0 = struct.unpack_from(">I", d, ct.dol_va_to_offset(d, ct.DRIVER_SLOT_PTRS_VA))[0]
    p1 = struct.unpack_from(">I", d, ct.dol_va_to_offset(d, ct.DRIVER_SLOT_PTRS_VA + 4))[0]
    assert p1 - p0 == 0x40
