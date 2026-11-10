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
`.text`/`.rodata` points into them - checked by `scripts/verify_re6_classes.py`). The original verified images stay
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


# --- the launcher rounds (hand-off lane B item 2) ---------------------------------------------------------------------------
#
# The grenade launcher uWp1080 (item 0x112) fires the round classes uWp1302/1303/1304 (items 0x133-0x135), subclasses of
# uWpShellLauncher -> uWpShell -> uWeapon (docs/research/re6-weapon-dti-tree.md, Hermes #9437). Their DTIs are pinned
# here so the barrage can name them; they are **not** wired into the ring yet, and the reason is in the disassembly of
# our own detonation wrapper (`detonate` image, 0x18F29C0+):
#
#   word 30-36  ldr x0, [x19, #0x13F0] / cbz / ldr x1, [x0] / cmp x1, 0x288C9A0   <- the unit's *action* object must be
#               the bomb's own class; a shell carries the launcher's, so the wrapper returns 0 (refused, not a crash)
#   word 52-56  the same shape against 0x288C868 before reporting the explosion
#
# So a shell cannot be detonated by parameterising this wrapper: it needs the launcher's own fire/explode path (the
# round is a projectile the weapon spawns with a velocity, not an item thrown by the player). The table is here so that
# path has its addresses and ids; `grenade_scatter` deliberately refuses `kind="shell*"` until then rather than firing
# a round that cannot explode.

@dataclass(frozen=True)
class ShellClass:
    name: str
    item: int
    dti: int
    parent: str
    size: int


SHELLS = {
    "uWp1302": ShellClass("uWp1302", 0x133, 0x2952098, "uWpShellLauncher", 0xE5C),
    "uWp1303": ShellClass("uWp1303", 0x134, 0x29520D0, "uWpShellLauncher", 0xE5C),
    "uWp1304": ShellClass("uWp1304", 0x135, 0x2952108, "uWpShellLauncher", 0xE5C),
}

SHELL_FAMILY = {
    "uWpShell": (0x2950B60, None, 0xE58),
    "uWpShellLauncher": (0x2950B98, None, 0xE5C),
    "uWpShellBowgun": (0x2950BD0, None, 0xE78),
    "uWpShellHoming": (0x2950C40, None, 0xE64),
    "uWpShellRifle": (0x2950DC8, 0x138, 0xE5C),
}

LAUNCHERS = {
    "uWp1080": (0x2951260, 0x112, 0xE28),      # Grenade Launcher
    "uWp1120": (0x2951458, 0x11B, 0xE2C),      # Rocket Launcher
}

#: class name -> the round it fires (what "real launcher rounds in the barrage" means)
LAUNCHER_ROUNDS = {"uWp1080": ("uWp1302", "uWp1303", "uWp1304"), "uWp1120": ("uWp1304",)}


def shell_for_item(item: int) -> ShellClass | None:
    """The launcher round class for an inventory item id (0x133-0x135), or None."""
    for shell in SHELLS.values():
        if shell.item == item:
            return shell
    return None


def shell_rounds(launcher: str = "uWp1080") -> tuple:
    """The round classes a launcher fires, by name (default the grenade launcher)."""
    return tuple(SHELLS[name] for name in LAUNCHER_ROUNDS.get(launcher, ()))