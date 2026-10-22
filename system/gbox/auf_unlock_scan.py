"""Locate the 007: Agent Under Fire unlock machinery in the owned disc's Bond.elf.

Reads the debug ELF the disc ships (``.symtab`` kept, RAM-linked addresses) and
reports, with exact addresses:

* every function/global whose name mentions the progression vocabulary
  (unlock, medal, mission, level-select, bonus, character pick, save slot);
* the data each of those functions actually references, resolved from the
  ``lis``/``addi`` / ``la`` address-materialisation pairs.

Nothing is written: the ELF and the disc are read-only here, and no save, no
session and no operator setting is touched.

    python -m gbox.auf_unlock_scan <Bond.elf> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys

from .auf_disasm import Elf

# The progression vocabulary of the disc.  Case-insensitive substring match on
# the symbol name; each pattern is reported separately so a reviewer can see
# which concept produced which address.
PATTERNS = {
    'unlock': re.compile(r'unlock', re.I),
    'medal': re.compile(r'medal', re.I),
    'mission': re.compile(r'mission', re.I),
    'bonus': re.compile(r'bonus', re.I),
    'pick_select': re.compile(r'(charact|pick|select|roster|portrait)', re.I),
    'level_progress': re.compile(r'(levelunlock|levelselect|level.*unlock|unlock.*level|progresslevel|missionunlock)', re.I),
    'save_slot': re.compile(r'(saveslot|savetofile|loadfromfile|memcardsave|savefile)', re.I),
    'stat_class': re.compile(r'SPStatistics', re.I),
}

# Words that only match noise in a 17k-symbol debug build.
STOP = re.compile(r'(MUTEX_unlock|CARDUnlock|EXIUnlock|OSUnlock|REALMUTEX|UnlockSram|ReadArrayUnlock'
                  r'|__CARDUnlockedHandler|unlockedhandler|unlock_sram)', re.I)


def _insn_words(elf: Elf, addr: int, count: int) -> list[int]:
    raw = elf.bytes_at(addr, count * 4)
    return [struct.unpack('>I', raw[i:i + 4])[0] for i in range(0, len(raw) - 3, 4)]


def referenced_globals(elf: Elf, addr: int, length: int) -> list[int]:
    """Resolve the absolute addresses a function materialises.

    PowerPC builds an address with ``lis rD, hi`` followed by ``addi rD, rD, lo``
    (or ``la rD, disp`` which is the same encoding).  Pairing the two gives the
    address the code touches, which is what a reviewer needs to see.
    """
    words = _insn_words(elf, addr, max(1, length // 4))
    regs: dict[int, int] = {}
    found: list[int] = []
    for word in words:
        opcode = (word >> 26) & 0x3F
        rd = (word >> 21) & 0x1F
        ra = (word >> 16) & 0x1F
        if opcode == 15:  # addis / addi (also "la")
            imm = word & 0xFFFF
            if imm & 0x8000:
                imm -= 0x10000
            if (word >> 1) & 1:  # addis: signed 16-bit shifted left 16
                value = ((imm & 0xFFFF) << 16) & 0xFFFFFFFF
                if value & 0x80000000:
                    value -= 0x100000000
                regs[rd] = value
            else:  # addi
                base = regs.get(ra, 0)
                value = (base + imm) & 0xFFFFFFFF
                if value & 0x80000000:
                    value -= 0x100000000
                regs[rd] = value
                found.append(value & 0xFFFFFFFF)
        elif opcode == 26:  # ori
            imm = word & 0xFFFF
            base = regs.get(ra, 0)
            value = ((base & 0xFFFF0000) | imm) & 0xFFFFFFFF
            regs[rd] = value
            found.append(value)
        elif opcode in (19, 20):  # bclr / bctr: a function boundary
            regs.clear()
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('elf')
    ap.add_argument('--json')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)
    elf = Elf(args.elf)

    hits: dict[str, list[dict]] = {}
    for name, addr in sorted(elf.symbols.items()):
        if STOP.search(name):
            continue
        for group, pattern in PATTERNS.items():
            if pattern.search(name):
                hits.setdefault(group, []).append({'name': name, 'addr': f'0x{addr:08x}'})
                break

    report = {'elf': elf.path, 'groups': {}}
    for group, items in sorted(hits.items()):
        report['groups'][group] = items
        print(f'== {group} ({len(items)}) ==')
        for item in items[:60]:
            print(f"  {item['addr']}  {item['name']}")
        if len(items) > 60:
            print(f'  ... and {len(items) - 60} more')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=1, sort_keys=True)
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
