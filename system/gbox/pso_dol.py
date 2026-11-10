"""Map `PsoV3.dol`: the addresses the game sees, and the pointers between them.

The standard GameCube DOL header is seven text and eleven data `(offset, address, size)` triples. **`PsoV3.dol` is not laid
out that way**, and this module records what it actually is (measured 2026-11-10, i9-NUC):

```
0000  00 00 01 00  00 00 26 20  00 00 00 00  00 00 00 00     code begins at file offset 0x100
0010  00 00 00 00  00 00 00 00  00 00 00 00  00 42 6e 00     ascending file offsets from 0x1c: 0x426e00, 0x427540, ...
0030  00 47 46 e0  00 4f 21 20  00 4f 44 c0  00 00 00 00
0048  80 00 c0 00  80 00 f7 40                               addresses: 0x8000c000, 0x8000f740
```

Two things fall out and they matter:

* **the image base is `0x8000c000`** -- which is exactly the `image_base` in the Ghidra program exported for this executable
  (`ghidra-pso-v3.json`, 25,981 functions). So the Ghidra map and the file agree on where the code lives, and a function
  address from that export can be read in this file.
* the file carries **no standard section table**, so the mapping used here is the flat one a loader would apply: file offset
  0x100 is the first code byte at the base, and everything after it is contiguous. That is an assumption, and it is the one
  this module makes explicit -- `is_flat()` says so rather than pretending to a section table it does not have.

The practical use is P2b's: turn a Ghidra function address into a file offset to look at its bytes, and find which words in
the image point at a given address (the string/table cross-reference trick) without a disassembler.
"""
from __future__ import annotations

import struct

CODE_START = 0x100                 # first code byte in the file
IMAGE_BASE = 0x8000C000            # matches ghidra-pso-v3.json's image_base
FLAT = True                        # no standard section table: see the module docstring


class DolError(ValueError):
    """The bytes are not the executable this module understands."""


def header(dol: bytes) -> dict:
    """The two values that are readable from the head of the file: the first code offset and the two addresses."""
    if len(dol) < 0x50:
        raise DolError(f"{len(dol)} bytes is smaller than the values this parser reads")
    first = struct.unpack_from(">I", dol, 0)[0]
    addrs = [struct.unpack_from(">I", dol, 0x48)[0], struct.unpack_from(">I", dol, 0x4C)[0]]
    return {"code_start": first or CODE_START, "image_base": addrs[0], "second_address": addrs[1],
            "flat": FLAT, "size": len(dol)}


def is_flat() -> bool:
    """True when this module is using the flat offset/address mapping rather than a section table."""
    return FLAT


def address_of(dol: bytes, offset: int) -> int:
    """The address the game sees the byte at ``offset`` at."""
    h = header(dol)
    if not 0 <= offset < len(dol):
        raise DolError(f"offset {offset:#x} is outside the file ({len(dol):#x} bytes)")
    return h["image_base"] + (offset - h["code_start"])


def offset_of(dol: bytes, address: int) -> int | None:
    """The file offset of an address in the loaded image, or None when it is not in this file."""
    h = header(dol)
    off = h["code_start"] + (address - h["image_base"])
    return off if 0 <= off < len(dol) else None


def find_string(dol: bytes, needle: str | bytes) -> dict | None:
    """The first occurrence of a string, with its file offset and the address the game sees."""
    want = needle.encode("ascii") if isinstance(needle, str) else needle
    i = dol.find(want)
    if i < 0:
        return None
    return {"offset": i, "address": address_of(dol, i)}


def find_pointers(dol: bytes, address: int) -> list[dict]:
    """Every place in the file holding ``address`` as a big-endian u32 -- the table/string cross-reference trick."""
    want = struct.pack(">I", address)
    out, start = [], 0
    while True:
        i = dol.find(want, start)
        if i < 0:
            return out
        out.append({"offset": i, "address": address_of(dol, i)})
        start = i + 1
