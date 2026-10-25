"""Verified native model centers for RE5 BLUS30491 app01.01; these are not damage hitboxes.

Pinned ELF SHA256 d901458f13beeb3d5bb0523eaac9c60102863a67f69b20905d8fa0c74e8be293.
uEm32's sphere getter copies +250..25C only when +A00 is nonzero; its vector getter independently
returns +250..258. This avoids imposing a humanoid chest height on the low Licker model.
"""
from __future__ import annotations

import math
import struct

LICKER_VT = 0x0158B7A8
MODEL_ACTIVE, BOUNDS = 0xA00, 0x250
SOURCE = "uEm32 native model bounds center; damage hitbox unverified"
VT_SLOTS = ((5, 0x016C0330, 0x0102D224), (11, 0x01708138, 0x00DFA434),
            (81, 0x016ED958, 0x00829704))
CODE = ((0x0102D224, bytes.fromhex("fbc1fff083c284e0807e8018ebc1fff04e800020")),
        (0x00DFA434, bytes.fromhex("80030a00392000002f800000419e0028c1a3025039200001d1a40000"
                                  "c0030254d0040004c1a30258d1a40008c003025cd004000c7d2307b44e800020")),
        (0x00829704, bytes.fromhex("7c691b78c5a4025078630020d1a90000c0040004d0090004"
                                  "c1a40008d1a900084e800020")))


def _u32(m, address):
    return struct.unpack(">I", m.rd(address, 4))[0]


def _bounded(point, radius, foot):
    """Broad corrupt/stale-data bounds only; radius never widens the firing tolerance."""
    return (len(point) == len(foot) == 3 and all(math.isfinite(x) and abs(x) < 1e7 for x in (*point, *foot))
            and math.isfinite(radius) and 0 < radius <= 2000. and math.dist(point, foot) <= 2. * radius)


def read(m, enemy) -> dict | None:
    """None means an unsupported class; a recognized but unverified Licker must not use a chest guess."""
    result = None
    try:
        actor = enemy.get("ptr")
        if type(actor) is not int or not 0x30000000 <= actor < 0x40000000:
            return None
        result = {"kind": "unknown", "verified": False, "requires_native_center": True,
                  "source": "actor type unreadable", "damage_hitbox_verified": False}
        if _u32(m, actor) != LICKER_VT:
            return None
        result.update(kind="uEm32", source=SOURCE)
        if any(_u32(m, LICKER_VT + slot * 4) != opd or _u32(m, opd) != entry
               for slot, opd, entry in VT_SLOTS) or any(m.rd(address, len(code)) != code for address, code in CODE):
            return result
        active = _u32(m, actor + MODEL_ACTIVE)
        if not active:
            return result
        raw = m.rd(actor + BOUNDS, 16)
        x, y, z, radius = struct.unpack(">4f", raw)
        point = (x, y, z)
        foot = struct.unpack(">3f", m.rd(actor + 0x30, 12))
        if not _bounded(point, radius, foot) or not _bounded(point, radius, tuple(enemy["pos"])):
            return result
        if (_u32(m, actor) != LICKER_VT or _u32(m, actor + MODEL_ACTIVE) != active
                or m.rd(actor + BOUNDS, 16) != raw):
            return result
        result.update(verified=True, point=list(point), radius_cm=radius)
        return result
    except (OSError, ValueError, TypeError, KeyError, struct.error):
        return result


def point(enemy):
    """Return the guarded snapshot point, or None when the supported native geometry is unavailable."""
    try:
        geometry = enemy.get("native_aim") or {}
        value = tuple(geometry.get("point") or ())
        radius = geometry.get("radius_cm")
        if geometry.get("kind") == "uEm32" and geometry.get("verified") is True \
                and geometry.get("source") == SOURCE and _bounded(value, radius, tuple(enemy["pos"])):
            return value
    except (TypeError, ValueError, KeyError, OverflowError):
        pass
    return None
