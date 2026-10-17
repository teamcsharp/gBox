"""Killer Instinct (1994 arcade) boot ROM / bootstrap-loader analysis.

The default BIOS ``ki-l15d.u98`` is *not* an IDE disk reader. It is a 64-bit
MIPS (R4600, little-endian) security bootstrap: it checks a serial magic, then
decompresses a second-stage program from its own image into the second RAM bank
and jumps to it. The IDE/ATA sector reads live in that second stage, so the
main-program LBA and load address must be found there, not in the boot ROM.

Memory map (MAME ``src/mame/rare/kinst.cpp`` ``kinst_map``)::

    RAM   0x00000000-0x0007ffff   (512 KiB)  m_rambase  (framebuffer at 0x30000)
    RAM2  0x08000000-0x087fffff   (8 MiB)    m_rambase2
    dev   0x10000080-0x10000173              control regs + IDE task file
    ROM   0x1fc00000-0x1fc7ffff   (512 KiB)  boot ROM (KSEG1 0xbfc00000)

KSEG0/KSEG1 are ``addr & 0x1fffffff`` for ``0x80000000-0xbfffffff``, so the
uncached IDE task file at physical ``0x10000100`` is accessed as ``0xb0000100``.

Bootstrap layout (ROM offset ``0xfd0`` == ``0xbfc00fd0``, the compressed stream)::

    +0x00  u16  serial magic 0x7262 (compared at 0xbfc006e4; syscall if wrong)
    +0x02  u8   block count N
    +0x03  u8   0x00 (sentinel, syscall if nonzero)
    +0x04  u32  block[0] byte size
    +0x08  u32  block[0] load address (sign-extended; RAM2 KSEG0 base 0x88000000)
    ... then N blocks, each led by 24 16-bit VLC-table deltas and a bit-packed
    payload (decompressed by the bit reader at 0xbfc00d5c, the table-walk VLC
    decoder at 0xbfc00dec, and the bit-field assembler at 0xbfc00788..0xbfc00c70).

The entry point is the FIRST block's load address (register s6), reached via
``j 0xbfc005ac`` which zeroes every GPR/FPR and ``jr ra``. The header fields
above are byte-aligned in the stream, so the raw little-endian bytes are exactly
the values the boot ROM reads; only the deltas and payload use the bit reader.
"""

from __future__ import annotations

import struct

BOOT_ROM_BASE = 0xBFC00000
BOOT_ROM_SIZE = 0x80000  # 512 KiB

RAM = (0x00000000, 0x00080000)
RAM2 = (0x08000000, 0x08800000)
ROM = (0x1FC00000, 0x1FC80000)
DEVICES = (0x10000000, 0x10001000)

# MAME: map(0x10000100, 0x1000013f).rw(ide_r, ide_w)  -> cs0_r/cs0_w(offset/2)
#       map(0x10000170, 0x10000173).rw(ide_extra_r, ide_extra_w) -> cs1_r/cs1_w(6)
IDE_CS0 = (0x10000100, 0x10000140)
IDE_CS1 = (0x10000170, 0x10000174)
VRAM_CONTROL = 0x10000080
DSW = 0x100000A0

STREAM_OFFSET = 0xFD0
SERIAL_MAGIC = 0x7262
SECOND_STAGE_ENTRY = 0x88000000  # RAM2 KSEG0 base (physical 0x08000000)


def kseg1(phys: int) -> int:
    """Uncached KSEG1 alias of a physical address (boot code's 0xb000xxxx)."""
    return 0xA0000000 | (phys & 0x1FFFFFFF)


def bootstrap_header(rom: bytes, offset: int = STREAM_OFFSET) -> dict:
    """Parse the byte-aligned header of the compressed bootstrap stream.

    Returns the serial magic, block count, sentinel, and the first block's size
    and load address (which is also the second-stage entry point).
    """
    if offset + 12 > len(rom):
        raise ValueError("rom too small for bootstrap header")
    magic, = struct.unpack_from("<H", rom, offset)
    count, zero = rom[offset + 2], rom[offset + 3]
    size, = struct.unpack_from("<I", rom, offset + 4)
    load, = struct.unpack_from("<I", rom, offset + 8)
    return {
        "serial_magic": magic,
        "block_count": count,
        "sentinel": zero,
        "first_block_size": size,
        "first_block_load": load,
        "entry_point": load,
        "load_phys": load & 0x1FFFFFFF,
    }


def device_write_is_ide(phys: int) -> bool:
    """True when a device write target is the IDE task file (not a control reg)."""
    return IDE_CS0[0] <= phys < IDE_CS0[1] or IDE_CS1[0] <= phys < IDE_CS1[1]
