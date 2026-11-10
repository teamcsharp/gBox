"""Mega Man 64 (USA, NM6E rev0) native asset payloads: the 445-entry archive.

The main asset archive starts at ROM ``0x2CAC60`` and its 8-byte chained
directory (445 entries) lives at ROM ``0x99370``; both are pinned by code
constants (see :mod:`gbox.mm64_xref`).  Each flag-0x80 entry decodes with the
Okumura LZSS codec in :mod:`gbox.mm64_inventory` to a payload whose header is
``u32 section_count`` followed by ``section_count`` u32 absolute offsets into
the payload (first section data starts at ``4*(n+1)`` or later, last section
ends at the payload end).

Entry #0 (the identified native target asset) is a small RDP model:

* section @48   (144 B): setup/commands (ends in vertex-index groups).
* section @192  (48 B): 8 × 4-byte groups ``{cmd, a, b, c}`` (cmd 0x06/0x00) —
  indexed primitives (max index 0x36) followed by a 4-group command tail
  (0xDF000000 + zeros).  Counted primitives, not filename guesses.
* section @448  (240 B): 15 × 16-byte N64 RSP vertices — big-endian
  ``s16 x, y, z, w`` followed by 8 bytes colour/UV.  This corrects the earlier
  checkpoint that read this archive's vertex data as f32 floats.
* sections @240/@688: palette/texture-side data (unlabelled).

``repack`` reproduces a parsed payload byte-for-byte (no-op roundtrip), the
first writer prerequisite for a native cast_swap.
"""
from __future__ import annotations

import struct

from .mm64_inventory import load as load_rom, unpack_entry

ARCHIVE_BASE = 0x2CAC60
DIR_ROM = 0x99370
ENTRY_COUNT = 445
ROM_ZIP_SHA256 = "65b94d0bff869aa93b0a16e7d2dcdcc85724fb3df7ea7c394c88fc317ea03d3c"  # .zip container
ROM_IMAGE_SHA256 = "618d49bf62913b376e4858f1422a51a4352792b070fe6305860dd43e28353999"  # extracted BE .z64

RSP_VERTEX_SIZE = 16


def directory_entries(rom: bytes, dir_rom: int = DIR_ROM,
                      count: int = ENTRY_COUNT) -> list[tuple[int, int, int]]:
    """The archive's chained ``{offset, size, flag}`` entries."""
    out = []
    for i in range(count):
        a, b = struct.unpack_from(">II", rom, dir_rom + 8 * i)
        out.append((a, b & 0xFFFFFF, b >> 24))
    prev = None
    for off, size, _flag in out:
        if prev is not None and off != (prev + 3) & ~3:
            raise ValueError("directory chain broken at offset %#x" % off)
        prev = off + size
    return out


def unpack(rom: bytes, index: int, entries: list[tuple[int, int, int]] | None = None,
           base: int = ARCHIVE_BASE) -> bytes:
    """Decode one archive entry (LZSS when flagged)."""
    if entries is None:
        entries = directory_entries(rom)
    off, size, _flag = entries[index]
    data, facts = unpack_entry(rom, base, off, size)
    if data is None:
        raise ValueError("entry %d did not decode (raw/%s)" % (index, facts))
    return data


def sections(payload: bytes) -> list[bytes]:
    """Split a container payload on its header offsets."""
    n = struct.unpack_from(">I", payload, 0)[0]
    if not 1 <= n <= 512:
        raise ValueError("bad section count %d" % n)
    offs = list(struct.unpack_from(">%dI" % n, payload, 4))
    if offs[0] < 4 * (n + 1) or offs[-1] > len(payload) or offs != sorted(offs):
        raise ValueError("bad section offsets %r" % offs)
    bounds = offs + [len(payload)]
    return [payload[bounds[i]:bounds[i + 1]] for i in range(n)]


def repack(payload_sections: list[bytes], header_pad: bytes) -> bytes:
    """Inverse of :func:`sections`: re-emit header, pad, sections verbatim.

    ``header_pad`` is the bytes between the offset table and the first section
    (entry #0 keeps per-section metadata there); keeping it explicit makes the
    roundtrip exact instead of guessing what those fields mean.
    """
    n = len(payload_sections)
    offs, body = [], bytearray()
    cur = 4 * (n + 1) + len(header_pad)
    for s in payload_sections:
        offs.append(cur)
        body += s
        cur += len(s)
    return (struct.pack(">I", n) + struct.pack(">%dI" % n, *offs)
            + header_pad + bytes(body))


def rsp_vertices(section: bytes) -> list[dict]:
    """16-byte N64 RSP vertices: s16 x/y/z/w + colour/flag tail."""
    if len(section) % RSP_VERTEX_SIZE:
        raise ValueError("section size %d not a multiple of %d"
                         % (len(section), RSP_VERTEX_SIZE))
    out = []
    for i in range(len(section) // RSP_VERTEX_SIZE):
        x, y, z, w = struct.unpack_from(">hhhh", section, i * RSP_VERTEX_SIZE)
        out.append({"x": x, "y": y, "z": z, "w": w,
                    "tail": section[i * RSP_VERTEX_SIZE + 8:(i + 1) * RSP_VERTEX_SIZE]})
    return out


QUAD_CMD = 0x06


def index_groups(section: bytes) -> list[tuple[int, int, int, int]]:
    """4-byte ``{cmd, a, b, c}`` primitive groups (cmd 0x06 = indexed tri/quad)."""
    if len(section) % 4:
        raise ValueError("index section size %d not a multiple of 4" % len(section))
    return [struct.unpack_from(">BBBB", section, i) for i in range(0, len(section), 4)]
