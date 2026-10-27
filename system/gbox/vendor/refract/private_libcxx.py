"""Refract issue #38, fixed when a game is installed for Refract Native: a game library that carries its own private
static libc++ keeps calling its own copies of those functions instead of a sibling library's.

Part of gBox's fork of Refract's Native installer (install_apk.py in this folder).

    Based on Refract: https://github.com/MIXIDtheSilly/Refract

Copyright (C) 2026 Refract contributors and the gBox authors.
This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version, together with Refract's additional term (GPL-3.0 Section 7(b), visible credit). See LICENSE and NOTICE in
this folder. This program is distributed WITHOUT ANY WARRANTY.

Written for gBox on 2026-10-27 from the analysis and the fix that HRVAT007 posted in
https://github.com/MIXIDtheSilly/Refract/issues/38 (open and unmerged as of Refract 1.0.3).

The problem: Resident Evil 4 VR's libovrplatformloader.so is built with a complete private static libc++ (no
libc++_shared.so in DT_NEEDED, no operator new/delete in .dynsym), but its libc++ definitions are weak with default
visibility, so its own calls to them go through its PLT. libUE4.so lists the loader in DT_NEEDED, so in that dlopen
group libUE4 is searched first, and libUE4 re-exports a libc++ backed by Unreal's FMallocBinned2. Some of the loader's
self-defined imports (std::string's destructor among them) therefore resolve into libUE4: the loader allocates with
bionic malloc and frees through FMallocBinned2::Free, which faults during dlopen (SIGSEGV, exit 139) on Refract
Native 1.0.2.

The fix points each such PLT stub straight at the library's own definition, which is the binding the library was
built to have: one 4-byte `b <definition>` over the stub's first instruction. Only libraries that define std::__ndk1
symbols and neither export nor import operator new/delete are touched. In the RE4 VR set that is exactly
libovrplatformloader.so; libUE4, libc++_shared, libOVRPlugin, libplaycore, libovraudio64 and Refract's own libraries
fail the test and are left alone. Within such a library only PLT imports of std::__ndk1 functions that the library
defines itself are rebound. Every stub is decoded before it changes: it must be the standard AArch64
`adrp x16 / ldr x17, [x16, #n] / add x16, x16, #n / br x17` that loads that symbol's GOT slot, and the definition must
lie in executable code within branch range. Anything else is skipped and listed in the report.

Only the extracted copy that Refract runs is changed, never the APK. This is a loader compatibility fix: it changes
which copy of libc++ the loader's own string and tree helpers run, not what the loader does. Entitlement answers still
come only from Refract's Platform SDK stand-in, which gBox enables only for a game the operator owns.

usage: python private_libcxx.py [--dry-run] LIB.so [LIB.so ...]     (prints a JSON report per library)
"""
from __future__ import annotations

import argparse
import json
import mmap
import struct
import sys
from pathlib import Path

ELFMAG = b"\x7fELF"
EM_AARCH64 = 183
ET_DYN = 3
SHT_RELA, SHT_DYNAMIC, SHT_DYNSYM = 4, 6, 11
SHF_EXECINSTR = 0x4
DT_NULL, DT_PLTGOT = 0, 3
STT_FUNC = 2
SHN_UNDEF, SHN_LORESERVE = 0, 0xFF00
R_AARCH64_JUMP_SLOT = 1026
PLT0_SIZE, PLT_ENTRY_SIZE, GOT_PLT_RESERVED = 0x20, 0x10, 0x18   # AArch64 ELF psABI: PLT0, PLTn, GOT[0..2]
NDK1 = b"St6__ndk1"                                               # std::__ndk1 in Itanium-mangled names
NDK1_FUNCTIONS = (b"_ZNSt6__ndk1", b"_ZNKSt6__ndk1")              # functions in namespace std::__ndk1 itself
OPERATOR_NEW_DELETE = frozenset({b"_Znwm", b"_Znam", b"_ZdlPv", b"_ZdaPv"})
BR_X17 = 0xD61F0220
REPORT_VERSION = 1


class NotApplicable(ValueError):
    """The file is not a 64-bit little-endian AArch64 shared library with section headers."""


def _unpack(fmt: str, data, offset: int) -> tuple:
    if offset < 0 or offset + struct.calcsize(fmt) > len(data):
        raise NotApplicable("truncated ELF file")
    return struct.unpack_from(fmt, data, offset)


def _cstr(data, offset: int) -> bytes:
    if not 0 <= offset < len(data):
        raise NotApplicable("string table offset out of range")
    end = data.find(b"\0", offset)
    return bytes(data[offset:end if end >= 0 else len(data)])


def sections(data) -> list[dict]:
    if len(data) < 64 or bytes(data[:4]) != ELFMAG:
        raise NotApplicable("not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise NotApplicable("not a 64-bit little-endian ELF file")
    e_type, e_machine = _unpack("<HH", data, 16)
    (e_shoff,) = _unpack("<Q", data, 40)
    e_shentsize, e_shnum, e_shstrndx = _unpack("<HHH", data, 58)
    if e_machine != EM_AARCH64:
        raise NotApplicable("not an AArch64 library")
    if e_type != ET_DYN:
        raise NotApplicable("not a shared library")
    if not e_shoff or e_shentsize < 64 or not e_shnum or e_shstrndx >= e_shnum:
        raise NotApplicable("no section headers")
    rows = []
    for i in range(e_shnum):
        name, sh_type, flags, addr, offset, size, link, _info, _align, entsize = _unpack(
            "<IIQQQQIIQQ", data, e_shoff + i * e_shentsize)
        rows.append({"name_off": name, "type": sh_type, "flags": flags, "addr": addr, "offset": offset,
                     "size": size, "link": link, "entsize": entsize})
    names = rows[e_shstrndx]
    for row in rows:
        row["name"] = _cstr(data, names["offset"] + row["name_off"]).decode("ascii", "replace")
    return rows


def symbols(data, dynsym: dict, dynstr: dict) -> list[dict]:
    out = []
    for offset in range(dynsym["offset"], dynsym["offset"] + dynsym["size"] - 23, 24):
        st_name, st_info, _other, st_shndx, st_value, _size = _unpack("<IBBHQQ", data, offset)
        out.append({"name": _cstr(data, dynstr["offset"] + st_name) if st_name else b"", "type": st_info & 0xF,
                    "shndx": st_shndx, "value": st_value})
    return out


def pltgot(data, rows: list[dict]) -> int | None:
    dynamic = next((s for s in rows if s["type"] == SHT_DYNAMIC), None)
    if dynamic is None:
        return None
    for offset in range(dynamic["offset"], dynamic["offset"] + dynamic["size"] - 15, 16):
        tag, value = _unpack("<qQ", data, offset)
        if tag == DT_NULL:
            break
        if tag == DT_PLTGOT:
            return value
    return None


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def stub_slot(pc: int, insns: tuple[int, int, int, int]) -> int | None:
    """The GOT slot a standard AArch64 PLT entry at `pc` jumps through, or None when it is not that sequence."""
    adrp, ldr, add, br = insns
    if adrp & 0x9F00001F != 0x90000010:                                  # adrp x16, page
        return None
    page = (pc & ~0xFFF) + (_signed(((adrp >> 5) & 0x7FFFF) << 2 | (adrp >> 29) & 0x3, 21) << 12)
    if ldr & 0xFFC003FF != 0xF9400211:                                   # ldr x17, [x16, #lo12]
        return None
    lo12 = ((ldr >> 10) & 0xFFF) * 8
    if add & 0xFFC003FF != 0x91000210 or (add >> 10) & 0xFFF != lo12:    # add x16, x16, #lo12
        return None
    if br != BR_X17:                                                     # br x17
        return None
    return page + lo12


def branch(pc: int, target: int) -> int | None:
    """`b target` placed at pc, or None when target is out of range or misaligned."""
    delta = target - pc
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        return None
    return 0x14000000 | ((delta >> 2) & 0x3FFFFFF)


def plan(data) -> dict:
    """What rebinding would change in this library: {eligible, reason?, patches, already, skipped}."""
    rows = sections(data)
    dynsym = next((s for s in rows if s["type"] == SHT_DYNSYM), None)
    if dynsym is None or dynsym["link"] >= len(rows):
        return {"eligible": False, "reason": "no dynamic symbol table"}
    syms = symbols(data, dynsym, rows[dynsym["link"]])
    if not any(s["shndx"] != SHN_UNDEF and NDK1 in s["name"] for s in syms):
        return {"eligible": False, "reason": "defines no std::__ndk1 symbols"}
    new_delete = sorted({s["name"].decode() for s in syms if s["name"] in OPERATOR_NEW_DELETE})
    if new_delete:
        return {"eligible": False, "reason": "exports or imports operator new/delete: " + ", ".join(new_delete)}
    byname = {s["name"]: s for s in rows}
    rela, plt, got = byname.get(".rela.plt"), byname.get(".plt"), pltgot(data, rows)
    out = {"eligible": True, "patches": [], "already": [], "skipped": []}
    if rela is None or plt is None or got is None or rela["type"] != SHT_RELA:
        out["reason"] = "no PLT to rebind"
        return out
    code = [(s["addr"], s["addr"] + s["size"]) for s in rows if s["flags"] & SHF_EXECINSTR and s["size"]]
    for offset in range(rela["offset"], rela["offset"] + rela["size"] - 23, 24):
        r_offset, r_info, _addend = _unpack("<QQq", data, offset)
        index = r_info >> 32
        if r_info & 0xFFFFFFFF != R_AARCH64_JUMP_SLOT or index >= len(syms):
            continue
        sym = syms[index]
        if sym["shndx"] == SHN_UNDEF or sym["shndx"] >= SHN_LORESERVE or not sym["value"] \
                or not sym["name"].startswith(NDK1_FUNCTIONS):
            continue                                                     # imported from elsewhere, or not libc++
        row = {"symbol": sym["name"].decode("ascii", "replace"), "got": hex(r_offset), "target": hex(sym["value"])}
        if sym["type"] != STT_FUNC:
            out["skipped"].append(row | {"reason": "not a function symbol"})
            continue
        slot, rem = divmod(r_offset - (got + GOT_PLT_RESERVED), 8)
        stub = plt["addr"] + PLT0_SIZE + slot * PLT_ENTRY_SIZE
        row["stub"] = hex(stub)
        if rem or slot < 0 or stub + PLT_ENTRY_SIZE > plt["addr"] + plt["size"]:
            out["skipped"].append(row | {"reason": "GOT slot outside the PLT's range"})
            continue
        file_offset = plt["offset"] + stub - plt["addr"]
        insns = _unpack("<4I", data, file_offset)
        new = branch(stub, sym["value"])
        if new is not None and insns[0] == new:
            out["already"].append(row)
            continue
        if stub_slot(stub, insns) != r_offset:
            out["skipped"].append(row | {"reason": "PLT entry is not the expected adrp/ldr/add/br for this GOT slot"})
            continue
        if not any(lo <= sym["value"] < hi for lo, hi in code):
            out["skipped"].append(row | {"reason": "definition is not in executable code"})
            continue
        if new is None:
            out["skipped"].append(row | {"reason": "definition is out of branch range"})
            continue
        out["patches"].append(row | {"file_offset": file_offset, "old": f"{insns[0]:08x}", "new": f"{new:08x}"})
    return out


def rebind(path: Path, dry_run: bool = False) -> dict:
    """Rebind one library in place (the installer's extracted copy). The report says what changed."""
    path = Path(path)
    report = {"library": path.name, "version": REPORT_VERSION}
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            report |= plan(data)
    except (NotApplicable, ValueError, OSError) as e:                     # mmap of an empty file is a ValueError
        return report | {"eligible": False, "reason": str(e), "applied": 0}
    patches = report.get("patches") or []
    if patches and not dry_run:
        with open(path, "r+b") as f:
            for patch in patches:
                f.seek(patch["file_offset"])
                f.write(struct.pack("<I", int(patch["new"], 16)))
    report["applied"] = 0 if dry_run else len(patches)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rebind private-libc++ PLT stubs (Refract issue #38).")
    ap.add_argument("libraries", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    args = ap.parse_args(argv)
    print(json.dumps([rebind(p, args.dry_run) for p in args.libraries], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
