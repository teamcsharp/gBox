"""Virtua Fighter 4 - Evolution (PS2) MRG / MRG_GZ format probe.

Analysis-stage deliverable for the VF4 Evo favorite (game 0b29e35386444551).

The inventory stage (``gbox/vf4evo_inventory.py``) established that the disc's
``vf4files.cvm`` holds two families of model files:

* plain ``*.MRG`` files (1817 of them) — the character *parts*
  (``<CODE>_ATAM/FACE/JOHA/KAHA_NN.MRG``), motion banks (``MOTMRG_<CODE>.MRG``),
  selection-screen models (``OTHER/SEL_CHA_*.MRG``) and 2D item/win textures;
* ``*.MRG_GZ`` files (146) — the compressed character *body* archives
  (``CH_<CODE>.MRG_GZ``) and stage archives (``EVOPS2_ST_*`` / ``PS2_*``).

This module encodes what the analysis stage pinned down, each finding a small
actionable probe rather than a bulk dump:

1. ``parse_mrg_lst``  — the 284-byte placeholder ``.MRG`` files are *merge
   manifests*: a 7-word header, a length-prefixed ``mrg.lst`` build list that
   names the merged source files (``.itm``/``.link``/``.tex``/``.mrg``) and a
   padded name table (bone names such as ``jack_of_straw``).
2. ``classify_mrg``   — a blob is a manifest, a raw float-vertex buffer
   (16-byte vertex = 3x float32 + u32), or an opaque ``MRG_GZ`` payload.
3. ``mrg_gz_codec``   — the ``.MRG_GZ`` payload is **not** gzip/zlib/raw-deflate
   (ruled out with exact errors); the executable links zlib 1.1.3 through a
   ``zlut_inflate`` wrapper, so the codec is zlib-family with a non-standard
   wrapper/transform that still needs disassembly to reproduce byte-for-byte.
4. ``elf_vf4evo_tables`` — static breadcrumbs in ``SLUS_000.00``: the character
   file table (``ch_<code>/CH_<CODE>.mrg_gz``) and the ``zlut_inflate`` string
   offsets, the anchors for the next (Ghidra) step.

Everything here is read-only; nothing re-encodes game data yet.
"""
from __future__ import annotations

import math
import re
import struct
import zlib

MRG_LST_MAGIC = b"mrg.lst"
OSGT_MAGIC = b"OSGT"


# ------------------------------------------------------------------------
# 1. merge-manifest parser (the 284-byte placeholder .MRG files)

def parse_mrg_lst(data: bytes) -> dict:
    """Parse a VF4 Evo merge-manifest .MRG (contains a ``mrg.lst`` build list).

    Layout (observed on the 284-byte ``*_40``/``*_30``/``*_31`` placeholders)::

        0x00  7 x u32 header words (values vary; word[1] == 0x20 == name stride)
        0x1c  u32 length of the following manifest string
        0x20  manifest string:  "mrg.lst\\r\\n<src>.itm\\r\\n<src>.link\\r\\n..."
               ... terminated by a NUL
        then  name table:  repeated  {u32 name_len, name bytes, NUL, padding}
    """
    if MRG_LST_MAGIC not in data:
        raise ValueError("not an mrg.lst merge manifest")
    i = data.find(MRG_LST_MAGIC)
    header = list(struct.unpack("<7I", data[0:28])) if i >= 28 else None
    length = struct.unpack_from("<I", data, i - 4)[0] if i >= 4 else 0
    manifest = data[i:i + length]
    # Source files are the CRLF lines that carry a relative path ("..\\..\\files\\...").
    sources = [
        ln.decode("latin-1").rstrip("\x00")
        for ln in manifest.split(b"\r\n")
        if b".." in ln
    ]
    # Name table: u32-length-prefixed names after the manifest. SEGA pads each
    # entry to a 32-byte stride (word[1] == 0x20) and NUL-terminates the
    # manifest separately, so skip a leading NUL terminator and inter-entry
    # padding instead of assuming a fixed offset.
    names: list[str] = []
    o = i + length
    if o < len(data) and data[o] == 0:          # manifest NUL terminator
        o += 1
    while o + 5 <= len(data):
        n = struct.unpack_from("<I", data, o)[0]
        if not (1 <= n <= 64):
            break
        candidate = data[o + 4:o + 4 + n]
        if o + 4 + n >= len(data) or data[o + 4 + n] != 0:
            break
        if all(32 <= c < 127 for c in candidate):
            names.append(candidate.decode("latin-1"))
        o += 4 + n + 1
        while o < len(data) and data[o] == 0:   # skip padding to the next entry
            o += 1
    return {
        "header": header,
        "manifest_len": length,
        "manifest": manifest.decode("latin-1", "replace"),
        "sources": sources,
        "names": list(dict.fromkeys(names)),
    }


# ------------------------------------------------------------------------
# 2. blob classifier

def _shannon(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def classify_mrg(data: bytes) -> dict:
    """Classify a VF4 Evo ``.MRG`` / ``.MRG_GZ`` blob by structure."""
    head = data[:16].hex(" ")
    if MRG_LST_MAGIC in data[:512]:
        return {"kind": "mrg_lst", "head": head}
    # Raw vertex buffers observed on ATAM/FACE/JOHA/KAHA parts: 16-byte
    # stride, 3x float32 position + one u32 (bone weight / index / colour).
    if len(data) >= 16 and len(data) % 16 == 0:
        try:
            xs = struct.unpack_from("<3f", data, 0)
            if all(-1e4 <= x <= 1e4 for x in xs):
                return {"kind": "vertex_buffer", "stride": 16, "head": head}
        except struct.error:
            pass
    return {"kind": "opaque", "entropy_bits": round(_shannon(data[:65536]), 4), "head": head}


# ------------------------------------------------------------------------
# 3. .MRG_GZ codec probe

def mrg_gz_codec(data: bytes) -> dict:
    """Probe the ``.MRG_GZ`` codec and rule out the standard decompressors.

    The executable links zlib 1.1.3 via a ``zlut_inflate`` wrapper (see
    ``elf_vf4evo_tables``); the payload has no gzip/zlib/raw-deflate header at
    any offset, so the wrapper applies a transform that still needs the
    decompressor disassembled (next step: Ghidra on ``SLUS_000.00``).
    """
    ruled_out: dict[str, str] = {}
    for label, wb in (("zlib", 15), ("raw-deflate", -15), ("gzip", 31), ("auto", 47)):
        try:
            zlib.decompress(data, wb)
            ruled_out[label] = "decoded unexpectedly"
        except Exception as e:  # noqa: BLE001 — recording the exact reason
            ruled_out[label] = str(e)
    for label, fn in (("bz2", __import__("bz2").decompress), ("lzma", __import__("lzma").decompress)):
        try:
            fn(data)
            ruled_out[label] = "decoded unexpectedly"
        except Exception as e:  # noqa: BLE001
            ruled_out[label] = type(e).__name__
    return {
        "size": len(data),
        "entropy_bits": round(_shannon(data[:65536]), 4),
        "first_bytes": data[:16].hex(" "),
        "ruled_out": ruled_out,
        "verdict": "zlib-family via zlut_inflate wrapper; transform undetermined without disassembly",
    }


# ------------------------------------------------------------------------
# 4. executable breadcrumbs for the Ghidra step

_CHAR_TABLE_RE = re.compile(rb"ch_[a-z0-9]+/CH_[A-Z0-9_]+\.mrg_gz")


def elf_vf4evo_tables(elf: bytes) -> dict:
    """Static-analysis anchors inside ``SLUS_000.00`` (PS2 EE ELF).

    Returns the file offsets of the zlib wrapper strings and the parsed
    character file table, which the next (Ghidra) step uses to reach the
    ``zlut_inflate`` decompressor and the per-character loader.
    """
    def offsets(needle: bytes) -> list[int]:
        return [m.start() for m in re.finditer(re.escape(needle), elf)]

    chars = sorted({m.group().decode("latin-1") for m in _CHAR_TABLE_RE.finditer(elf)})
    return {
        "elf_size": len(elf),
        "entry": struct.unpack_from("<I", elf, 24)[0] if elf[:4] == b"\x7fELF" else None,
        "zlut_inflate_strings": offsets(b"zlut_inflate"),
        "zlib_version_1_1_3": offsets(b"1.1.3"),
        "character_table_entries": chars,
    }
