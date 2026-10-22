"""Read-only PowerPC disassembly helper for the owned 007 disc's ``Bond.elf``.

The disc ships a debug ELF: it keeps ``.symtab`` (17,636 symbols) and RAM-linked
addresses, so functions and data can be named and located exactly.  This module
turns that into a small, reviewable reader:

    python -m gbox.auf_disasm <Bond.elf> --sym G_GetMedalFlags
    python -m gbox.auf_disasm <Bond.elf> --addr 0x8011f704 --count 40

``binutils`` on the build hosts has no PowerPC disassembler (``objdump`` reports
"can't disassemble for architecture UNKNOWN"), so the instruction decode is done
here with capstone.  Nothing in this module writes to the disc, the ELF or a
save; it only reads bytes and prints them.
"""
from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

# Section -> (vaddr, file offset, size).  Read from readelf -S; the three
# loadable sections below are all this module needs to turn a RAM address into
# file bytes.  ``.bss``/``.sbss`` are NOBITS and carry no file bytes.
SECTION_RE = re.compile(r'^\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)')
# readelf -sW columns: Num: Value Size Type Bind Vis Ndx Name.  The symbol
# name may itself contain spaces and the sizes may be hex, so the row is
# tokenised: the first six whitespace-separated fields are the fixed
# columns, everything after them is the name.
SYMBOL_RE = re.compile(r'^\s*\d+:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$')


class Elf:
    """Minimal ELF reader: sections, symbols and address -> bytes."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.data = Path(self.path).read_bytes()
        self.sections: list[tuple[str, int, int, int]] = []
        self.symbols: dict[str, int] = {}
        self._read_sections()
        self._read_symbols()

    def _read_sections(self) -> None:
        out = subprocess.run(['readelf', '-S', '-W', self.path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = SECTION_RE.match(line)
            if not m:
                continue
            name, _typ, addr, off, size = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            self.sections.append((name, int(addr, 16), int(off, 16), int(size, 16)))

    def _read_symbols(self) -> None:
        out = subprocess.run(['readelf', '-sW', self.path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            m = SYMBOL_RE.match(line)
            if not m:
                continue
            # The last group is the symbol name (it may contain spaces); the
            # six before it are Value/Size/Type/Bind/Vis/Ndx.
            name = m.group(7).strip()
            value = m.group(1)
            if not name or name.startswith('$'):
                continue
            try:
                addr_value = int(value, 16)
            except ValueError:
                continue
            self.symbols.setdefault(name, addr_value)

    def section_for(self, addr: int) -> tuple[str, int, int, int] | None:
        for name, vaddr, off, size in self.sections:
            if size and vaddr <= addr < vaddr + size:
                return name, vaddr, off, size
        return None

    def bytes_at(self, addr: int, count: int) -> bytes:
        sec = self.section_for(addr)
        if sec is None:
            return b''
        name, vaddr, off, size = sec
        if name in ('.bss', '.sbss'):
            return b''
        start = off + (addr - vaddr)
        return self.data[start:start + count]

    def symbol_for(self, addr: int) -> str | None:
        best = None
        for name, value in self.symbols.items():
            if value == addr:
                return name
            if value <= addr and (best is None or value > best[0]):
                best = (value, name)
        return best[1] if best and addr - best[0] < 0x400 else None

    def string_at(self, addr: int, limit: int = 96) -> str | None:
        raw = self.bytes_at(addr, limit)
        if not raw:
            return None
        end = raw.find(b'\x00')
        if end < 0:
            return None
        try:
            return raw[:end].decode('ascii')
        except UnicodeDecodeError:
            return None


def disasm(elf: Elf, addr: int, count: int = 40) -> list[str]:
    from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
    raw = elf.bytes_at(addr, count * 4)
    if not raw:
        return []
    md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    md.detail = False
    lines = []
    for i in md.disasm(raw, addr):
        sym = elf.symbol_for(i.address)
        label = f' <{sym}>' if sym else ''
        lines.append(f'0x{i.address:08x}{label}:  {i.mnemonic}\t{i.op_str}')
        if len(lines) >= count:
            break
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('elf')
    ap.add_argument('--addr', type=lambda s: int(s, 0))
    ap.add_argument('--sym')
    ap.add_argument('--count', type=int, default=40)
    ap.add_argument('--string', type=lambda s: int(s, 0), help='print a NUL-terminated string at an address')
    args = ap.parse_args(argv)
    elf = Elf(args.elf)
    if args.string is not None:
        print(elf.string_at(args.string))
        return 0
    addr = args.addr
    if args.sym:
        if args.sym not in elf.symbols:
            print(f'symbol not found: {args.sym}', file=sys.stderr)
            return 1
        addr = elf.symbols[args.sym]
    if addr is None:
        print('need --addr or --sym', file=sys.stderr)
        return 1
    print(f'--- 0x{addr:08x} ---')
    for line in disasm(elf, addr, args.count):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
