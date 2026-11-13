"""RE5 grenade classes: the uWp06 / uWp07 / uWp08 DTIs, derived from the game's own static initialiser.

The item factory takes the class's DTI (`CREATE_ITEM(sItem, FLASH_DTI, ...)`, the second argument), and the flash's
is pinned at `main+0x1D71538` by the live-verified native flash (`docs/research/re5-native-flash.md`,
`native/re5_ebffdb22/build.sh`). The DTI objects live in `.bss` and are built at start-up by one long straight-line
MtDTI registration sequence, `main+0x848xx..0x84xxx`: for each class it sets the object (`adrp`/`add` into
`x0`), the id (`w4 = 0x07010000 + 0x100 * class`), the size (`w3`), the parent DTI (`x2`, `uWpBomb` at
`main+0x1D71180`) and the class-name string (`x1`), then calls `main+0xBD28D0`.

Read out of the operator's own image (build `EBFFDB22…`, verified): the class number *is* the item: uWp06 hand
(item 0x106), uWp07 incendiary (0x107), uWp08 flash (0x108) - and uWp08 lands exactly on the documented flash DTI,
which is what makes the whole block trustworthy. `derive()` re-runs that registration sequence with a tiny ARM64
emulator so the table can be checked against any copy of the image (`scripts/verify_re5_classes.py`).

Only the DTIs are needed by the controller: the detonation wrapper takes the class vtable the allocated unit
actually carries, exactly as RE6's parameterised pair does, so no per-class vtable is trusted from a table.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .code import IMAGES

#: The registration block and the MtDTI constructor it calls (main-relative, `main` image with its 0x100 header).
BLOCK = (0x84800, 0x86000)
CTOR = 0xBD28D0
ID_BASE = 0x07010000
DTI_BOMB_PARENT = 0x1D71180


@dataclass(frozen=True)
class GrenadeClass:
    kind: str
    name: str                   # the game's class name
    item: int                   # the item id the DTI id encodes (id = 0x07010000 + 0x100 * item)
    dti: int                    # the DTI object, main-relative (in .bss, built at start-up)
    size: int | None = None     # the class's DTI size, as the initialiser passes it
    verified: bool = False      # a live grenade of this class has been seen (flash only, today)


CLASSES = {
    "hand": GrenadeClass("hand", "uWp06", 0x106, 0x1D714C8, 0x28D0, False),
    "incendiary": GrenadeClass("incendiary", "uWp07", 0x107, 0x1D71500, 0x28D0, False),
    "flash": GrenadeClass("flash", "uWp08", 0x108, 0x1D71538, 0x28E0, True),
}
FLASH_VT = 0x1C5EF58           # the live-verified flash's unit class vtable (for reference only)


def _sxt(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _cstr(image: bytes, at: int) -> str | None:
    if not 0 <= at < len(image):
        return None
    end = image.find(b"\0", at, at + 64)
    if end < 0:
        return None
    try:
        text = image[at:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    return text if text and all(32 <= ord(c) < 127 for c in text) else None


def derive(image: bytes, *, block=BLOCK, ctor=CTOR) -> dict:
    """Run the MtDTI registration block: {class name: {dti, item, size, parent, id}}.

    `image` is `main` with its 0x100 NSO header kept (hactool `--uncompressed`), so a virtual address is at file
    offset `vaddr + 0x100`. Requires capstone (a research dependency; gbox itself never imports it).
    """
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG

    shift = 0x100
    start, end = block
    text = image[start + shift:end + shift]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    regs = {}
    calls = []
    mask = (1 << 64) - 1

    def reg_key(name):                     # w3 and x3 are one register; a w-write is 32-bit
        return "x" + name[1:] if name and name[0] in "wx" else name

    def read(name):
        if name in ("xzr", "wzr"):
            return 0
        return regs.get(reg_key(name))

    def write(name, value):
        if name in ("xzr", "wzr"):
            return
        if value is not None:
            value &= 0xFFFFFFFF if name[0] == "w" else mask
        regs[reg_key(name)] = value

    for ins in md.disasm(text, start):
        mnem, ops = ins.mnemonic, ins.operands
        try:
            if mnem == "adrp":
                write(md.reg_name(ops[0].reg), ops[1].imm)
            elif mnem in ("add", "sub") and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
                base = read(md.reg_name(ops[1].reg))
                imm = ops[2].imm
                if ops[2].shift.type:
                    imm <<= ops[2].shift.value
                write(md.reg_name(ops[0].reg), None if base is None else (base + imm if mnem == "add" else base - imm))
            elif mnem == "mov" and ops[1].type == ARM64_OP_IMM:
                write(md.reg_name(ops[0].reg), ops[1].imm)
            elif mnem == "mov" and ops[1].type == ARM64_OP_REG:
                write(md.reg_name(ops[0].reg), read(md.reg_name(ops[1].reg)))
            elif mnem == "movk":
                name = md.reg_name(ops[0].reg)
                shift_by = ops[1].shift.value if ops[1].shift.type else 0
                base = read(name)
                if base is not None:
                    width = 0xFFFFFFFF if name[0] == "w" else mask
                    write(name, (base & ~(0xFFFF << shift_by) & width) | (ops[1].imm << shift_by))
            elif mnem == "bl" and ops[0].type == ARM64_OP_IMM:
                if ops[0].imm == ctor:
                    calls.append({"dti": read("x0"), "name_at": read("x1"), "parent": read("x2"),
                                  "size": read("x3"), "id": read("x4")})
            elif ops and ops[0].type == ARM64_OP_REG:
                write(md.reg_name(ops[0].reg), None)
        except (IndexError, AttributeError):
            continue
    out = {}
    for call in calls:
        name = _cstr(image, call["name_at"] + shift) if call["name_at"] else None
        if not name or call["dti"] is None:
            continue
        out[name] = {"dti": call["dti"],
                     "item": ((call["id"] or 0) >> 8) & 0xFFFF,
                     "size": call["size"], "parent": call["parent"], "id": call["id"]}
    return out


def verify(image: bytes) -> dict:
    """Compare the pinned table with what this image's initialiser builds. -> {ok, derived, mismatches}."""
    derived = derive(image)
    mismatches = []
    for kind, spec in CLASSES.items():
        row = derived.get(spec.name)
        if row is None:
            mismatches.append({"kind": kind, "why": f"{spec.name} not registered in the block"})
            continue
        if row["dti"] != spec.dti:
            mismatches.append({"kind": kind, "why": "dti", "pinned": hex(spec.dti), "image": hex(row["dti"])})
        if spec.item and row["item"] != spec.item:
            mismatches.append({"kind": kind, "why": "item", "pinned": hex(spec.item), "image": hex(row["item"])})
        if spec.size is not None and row["size"] != spec.size:
            mismatches.append({"kind": kind, "why": "size", "pinned": hex(spec.size),
                               "image": None if row["size"] is None else hex(row["size"])})
    flash = derived.get("uWp08")
    if flash and flash["dti"] != 0x1D71538:
        mismatches.append({"kind": "flash", "why": "the documented flash DTI does not match uWp08"})
    return {"ok": not mismatches, "mismatches": mismatches,
            "derived": {k: {kk: (hex(vv) if isinstance(vv, int) else vv) for kk, vv in row.items()}
                        for k, row in sorted(derived.items()) if k.startswith("uWp")}}


def class_for(kind: str) -> GrenadeClass:
    try:
        return CLASSES[(kind or "").lower()]
    except KeyError:
        raise KeyError(f"unknown grenade class {kind!r}") from None


# ---- the parameterised pair (2026-11-10) ------------------------------------------------------------------------------------
#
# `spawn.c` builds FLASH_DTI in x1 at words 12-13, but x1 already carries the caller's `generation`; x2 is free until
# word 14 overwrites w2 with the item line. So the class arrives in **x2** and the image moves it to x1.
# `explode.c` builds FLASH_VT in x4 at words 4-5 (x4 is free: the wrapper's arguments are x0..x3), and configures the
# hit volumes with the flash's item id as the immediate `movz w3, #0x108` at word 47. The parameterized wrapper preserves the extra arguments through its guards
# and native calls without increasing the image size - no compiler and no new code cave (RE5's .text tail has none left).

NOP = 0xD503201F
MOV_X1_X2 = 0xAA0203E1          # orr x1, xzr, x2  - the class DTI, from the caller's third argument
MOV_W3_W5 = 0x2A0503E3          # orr w3, wzr, w5  - the item id, from the caller's sixth argument
BLR_X6 = 0xD63F00C0             # blr x6          - the class's update function, from the caller's seventh argument

# The explosion wrapper's last call: the flash runs its own update (0x820E50, live-verified); the other uWpBomb
# classes run the bomb base update (0x806B80, "creates hit volumes, effects and sound and publishes +28A0" -
# docs/research/re5-native-flash.md). Both are main-relative; the controller passes one or the other.
FLASH_UPDATE_OFF = 0x820E50
BOMB_UPDATE_OFF = 0x806B80


def spawn_with_class() -> bytes:
    """`spawn.c` with the flash DTI build replaced: the class's DTI arrives in x2 (the 3rd call argument)."""
    words = list(struct.unpack(f"<{len(IMAGES['spawn']) // 4}I", IMAGES["spawn"]))
    if (words[12], words[13]) != (0xF0005F01, 0x9114E021):      # adrp x1 / add x1, x1, #0x538 (FLASH_DTI)
        raise ValueError("the pinned spawn image no longer builds the flash DTI where it was verified")
    words[12], words[13] = MOV_X1_X2, NOP
    return struct.pack(f"<{len(words)}I", *words)


def explode_with_class() -> bytes:
    """`explode.c` with its three class-specific constants replaced.

    The class vtable arrives in **x4**, the item id in **w5** and the update
    function in **x6**. Preserve the latter two across register reuse and CONFIGURE - the flash keeps its own 0x820E50, the other uWpBomb classes get the bomb base 0x806B80.
    """
    words = list(struct.unpack(f"<{len(IMAGES['explode']) // 4}I", IMAGES["explode"]))
    if (words[4], words[5]) != (0x90005684, 0x913D6084):        # adrp x4 / add x4, x4, #0xf58 (FLASH_VT)
        raise ValueError("the pinned explode image no longer builds the flash vtable where it was verified")
    if words[47] != 0x52802103:                                  # movz w3, #0x108 (the flash item)
        raise ValueError("the pinned explode image no longer configures the flash item where it was verified")
    if words[55] != 0x97DA48E9:                                  # bl 0x820E50 (the flash update)
        raise ValueError("the pinned explode image no longer calls the flash update where it was verified")
    # x5 is overwritten by the wrapper's own vtable load, and CONFIGURE may
    # clobber x6 (AAPCS caller-saved). Preserve item in w7 until CONFIGURE and
    # unit/update on the stack across it. The two removed address instructions
    # supply the space; no executable image grows or overlaps its neighbour.
    if words[3] != 0xA9BE7BFD or words[14] != 0xA8C27BFD or words[52] != 0xAA1303E0:
        raise ValueError('the pinned explosion wrapper frame changed')
    words[3] = 0xA9BD7BFD       # stp x29, x30, [sp, #-0x30]!
    words[4] = 0x2A0503E7       # mov w7, w5
    words[5] = 0xA9021BE0       # stp x0, x6, [sp, #0x20]
    words[14] = 0xA8C37BFD      # ldp x29, x30, [sp], #0x30
    words[47] = 0x2A0703E3      # mov w3, w7
    words[52] = 0xA9421BE0      # ldp x0, x6, [sp, #0x20]
    words[55] = BLR_X6
    return struct.pack(f"<{len(words)}I", *words)


SPAWN_CLASS_BYTES = spawn_with_class()
EXPLODE_CLASS_BYTES = explode_with_class()
SPAWN_CLASS = (0x118E820, "spawn_class", len(SPAWN_CLASS_BYTES),
               hashlib.sha256(SPAWN_CLASS_BYTES).hexdigest())
EXPLODE_CLASS = (0x118E9D0, "explode_class", len(EXPLODE_CLASS_BYTES),
                 hashlib.sha256(EXPLODE_CLASS_BYTES).hexdigest())
IMAGES_CLASS = {"spawn_class": SPAWN_CLASS_BYTES, "explode_class": EXPLODE_CLASS_BYTES}


def image_bytes(name: str) -> bytes:
    """A pinned image by name: the parameterised pair first, then the shipped ones."""
    if name in IMAGES_CLASS:
        return IMAGES_CLASS[name]
    return IMAGES[name]
