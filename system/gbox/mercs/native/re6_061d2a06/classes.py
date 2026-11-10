"""RE6 grenade classes as a parameter of the native spawn and explosion images.

`spawn.c` links the class's DTI into its second argument (`adrp x1, 0x2951000` / `add x1, x1, #0x500` =
uWp1095, the flash) and `detonate.c` links the unit's class vtable into its first check (`adrp x0, 0x284a000` /
`add x0, x0, #0xeb8` = the flash's vtable). Both are two instructions. This module derives, from those two
*verified* images and by replacing exactly those two instructions, a parameterised pair that takes the same values
from its caller:

    spawn_class(player, dti)                                    # x1 = DTI   (two NOPs)
    detonate_class(unit, player, generation, player_generation, class_vtable)   # x0 = x4

The derived images live in two caves this repository has not used before - zero runs at `main+0x18F2BC0` and
`main+0x18F2CC0`, inside the same never-executed padding tail as the existing four images (the pristine image's
`.text` is one zero run from `0x18F2630` to its end, and no B/BL/ADR/ADRP+ADD target and no 64-bit literal in
`.text`/`.rodata` points into them - checked by `tools/verify_re6_classes.py`). The original verified images stay
installed and in use for the flash path; these are only installed when a class that needs them is fired.

Classes (branch re6-bomb-mind, 2026-11-10; docs/research/re6-weapon-dti-tree.md, Hermes #9437):

    kind         item   DTI (main+)   class vtable (main+)
    flash        0x115  0x2951500     0x284AEB8
    hand         0x113  0x2951490     0x284B788
    incendiary   0x114  0x29514C8     0x284B328

The vtable is *not* needed as a table at detonation time: the controller reads the vtable the allocated unit
actually carries and passes it, so the wrapper checks "still the class we allocated", not "is a flash".
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .code import IMAGES

NOP = 0xD503201F
MOV_X0_X4 = 0xAA0403E0          # orr x0, xzr, x4


@dataclass(frozen=True)
class GrenadeClass:
    kind: str
    item: int                   # the inventory item id whose resources must be loaded
    dti: int                    # the class DTI object (main+offset) passed to the item factory
    vtable: int | None          # the class vtable (main+offset) when known; the controller reads the unit's own


CLASSES = {
    "flash": GrenadeClass("flash", 0x115, 0x2951500, 0x284AEB8),
    "hand": GrenadeClass("hand", 0x113, 0x2951490, 0x284B788),
    "incendiary": GrenadeClass("incendiary", 0x114, 0x29514C8, 0x284B328),
}


def _words(data: bytes) -> list:
    return list(struct.unpack(f"<{len(data) // 4}I", data[:len(data) // 4 * 4]))


def _pack(words) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


def spawn_with_class() -> bytes:
    """`spawn.c` with its two DTI-building instructions replaced by NOPs: x1 arrives from the caller."""
    words = _words(IMAGES["spawn"])
    if (words[6], words[7]) != (0xF00082E1, 0x91140021):     # adrp x1, 0x2951000 / add x1, x1, #0x500
        raise ValueError("the pinned spawn image no longer builds the flash DTI where it was verified")
    words[6] = words[7] = NOP
    return _pack(words)


def detonate_with_class() -> bytes:
    """`detonate.c` with its two FLASH_VT-building instructions replaced by `mov x0, x4` + NOP."""
    words = _words(IMAGES["detonate"])
    if (words[4], words[5]) != (0x90007AC0, 0x913AE000):      # adrp x0, 0x284a000 / add x0, x0, #0xeb8
        raise ValueError("the pinned detonate image no longer builds the flash vtable where it was verified")
    words[4], words[5] = MOV_X0_X4, NOP
    return _pack(words)


SPAWN_CLASS_BYTES = spawn_with_class()
DETONATE_CLASS_BYTES = detonate_with_class()
SPAWN_CLASS = (0x18F2BC0, "spawn_class", len(SPAWN_CLASS_BYTES),
               hashlib.sha256(SPAWN_CLASS_BYTES).hexdigest())
DETONATE_CLASS = (0x18F2CC0, "detonate_class", len(DETONATE_CLASS_BYTES),
                  hashlib.sha256(DETONATE_CLASS_BYTES).hexdigest())
IMAGES_CLASS = {"spawn_class": SPAWN_CLASS_BYTES, "detonate_class": DETONATE_CLASS_BYTES}


def image_bytes(name: str) -> bytes:
    """A pinned image by name: the derived class images first, then the shipped ones."""
    if name in IMAGES_CLASS:
        return IMAGES_CLASS[name]
    return IMAGES[name]


def class_for(kind: str) -> GrenadeClass:
    try:
        return CLASSES[(kind or "").lower()]
    except KeyError:
        raise KeyError(f"unknown grenade class {kind!r}") from None
