"""Cross-reference data addresses in the owned 007 disc's ``Bond.elf``.

PowerPC materialises a 32-bit address in two instructions: a high half
(``lis``/``addis``, opcode 15) and a low half (``addi``, opcode 14, or
``ori``, opcode 26).  This module single-passes the executable sections,
tracks the registers those instructions write, and reports every address the
code forms that matches a requested target -- together with the enclosing
function and whether the access is a load (read) or a store (write).

The tracking is exact rather than heuristic: a reported hit is a real
high/low pair that computes the target address.

    python -m gbox.auf_xref <Bond.elf> --target 0x801ddfc0
    python -m gbox.auf_xref <Bond.elf> --target 0x801ddfc0 --json out.json

Read-only: the ELF, the disc, the saves and the running sessions are not
touched.
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess

from .auf_disasm import Elf

LOADS = {32, 33, 34, 35, 40, 41, 42}
STORES = {36, 37, 38, 39, 44, 45, 46, 47, 52, 53, 54, 55}
BRANCHES = {16, 17, 18, 19, 20}


def _sx16(value: int) -> int:
    """Sign-extend a 16-bit immediate."""
    return value - 0x10000 if value & 0x8000 else value


def _num(text: str) -> int:
    """Parse a readelf number (decimal, or hex with a 0x prefix)."""
    if text.startswith('0x'):
        return int(text, 16)
    try:
        return int(text, 10)
    except ValueError:
        return int(text, 16)


def functions(elf: Elf) -> list[tuple[int, int, str]]:
    """(start, end, name) for every FUNC symbol."""
    out = subprocess.run(['readelf', '-sW', elf.path],
                         capture_output=True, text=True).stdout
    funcs: list[tuple[int, int, str]] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].endswith(':'):
            continue
        if parts[3] != 'FUNC':
            continue
        try:
            value = _num(parts[1])
            size = _num(parts[2])
        except ValueError:
            continue
        if not size:
            continue
        funcs.append((value, value + size, ' '.join(parts[7:]).strip()))
    funcs.sort()
    return funcs


def owner(funcs: list[tuple[int, int, str]], addr: int) -> str:
    lo, hi = 0, len(funcs)
    while lo < hi:
        mid = (lo + hi) // 2
        if funcs[mid][0] <= addr:
            lo = mid + 1
        else:
            hi = mid
    if lo and funcs[lo - 1][0] <= addr < funcs[lo - 1][1]:
        return funcs[lo - 1][2]
    return '<no function>'


def _access(words: list[int], index: int, base_reg: int) -> str:
    """Classify the use of an address: load (read) or store (write)."""
    for step in range(1, 9):
        if index + step >= len(words):
            break
        word = words[index + step]
        opcode = (word >> 26) & 0x3F
        ra = (word >> 16) & 0x1F
        if opcode in LOADS and ra == base_reg:
            return 'read'
        if opcode in STORES and ra == base_reg:
            return 'write'
    return 'other'


def scan(elf: Elf, targets: list[int]) -> dict[int, list[dict]]:
    """One pass over the executable sections; every address formed is tested."""
    wanted = set(targets)
    found: dict[int, list[dict]] = {t: [] for t in targets}
    funcs = functions(elf)
    for name, vaddr, off, size in elf.sections:
        if name not in ('.text', '.init'):
            continue
        raw = elf.data[off:off + size]
        words = [struct.unpack('>I', raw[i:i + 4])[0] for i in range(0, len(raw) - 3, 4)]
        regs: dict[int, int | None] = {}
        for index, word in enumerate(words):
            opcode = (word >> 26) & 0x3F
            rd = (word >> 21) & 0x1F
            ra = (word >> 16) & 0x1F
            imm = word & 0xFFFF
            if opcode == 15:  # addis / lis
                base = 0 if ra == 0 else regs.get(ra, None)
                if base is None:
                    regs[rd] = None
                else:
                    regs[rd] = (base + ((_sx16(imm) << 16) & 0xFFFFFFFF)) & 0xFFFFFFFF
            elif opcode == 14:  # addi
                base = 0 if ra == 0 else regs.get(ra, None)
                if base is None:
                    regs[rd] = None
                    continue
                value = (base + _sx16(imm)) & 0xFFFFFFFF
                regs[rd] = value
                if value in wanted:
                    site = vaddr + index * 4
                    found[value].append({
                        'site': f'0x{site:08x}',
                        'kind': 'lis+addi',
                        'function': owner(funcs, site),
                        'access': _access(words, index, rd),
                    })
            elif opcode == 26:  # ori
                base = 0 if ra == 0 else regs.get(ra, None)
                if base is None:
                    regs[rd] = None
                    continue
                value = ((base & 0xFFFF0000) | imm) & 0xFFFFFFFF
                regs[rd] = value
                if value in wanted:
                    site = vaddr + index * 4
                    found[value].append({
                        'site': f'0x{site:08x}',
                        'kind': 'lis+ori',
                        'function': owner(funcs, site),
                        'access': _access(words, index, rd),
                    })
            elif opcode in BRANCHES:
                regs = {}
            elif rd in regs:
                regs[rd] = None
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('elf')
    ap.add_argument('--target', type=lambda s: int(s, 0), action='append', required=True)
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    elf = Elf(args.elf)
    found = scan(elf, args.target)
    for target, hits in found.items():
        print(f'== 0x{target:08x} ==')
        for hit in hits:
            print(f"  {hit['site']}  {hit['access']:5s} {hit['kind']:9s} {hit['function']}")
        print(f'  -- {len(hits)} reference(s) --')
    if args.json:
        payload = {f'0x{t:08x}': hits for t, hits in found.items()}
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
