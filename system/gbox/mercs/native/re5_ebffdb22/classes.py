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
emulator so the table can be checked against any copy of the image (`tools/verify_re5_classes.py`).

Only the DTIs are needed by the controller: the detonation wrapper takes the class vtable the allocated unit
actually carries, exactly as RE6's parameterised pair does, so no per-class vtable is trusted from a table.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

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
