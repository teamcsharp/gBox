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
        # Require the first 16 vertices (not just one) to be plausible floats,
        # otherwise ~17% of random blobs pass a single-vertex check.
        n = min(16, len(data) // 16)
        ok = True
        for i in range(n):
            xs = struct.unpack_from("<3f", data, i * 16)
            if not all(abs(x) <= 1e4 for x in xs):  # NaN fails this too
                ok = False
                break
        if ok and _shannon(data[:65536]) < 7.5:
            return {"kind": "vertex_buffer", "stride": 16, "head": head}
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


# --- MRG_GZ container (resolved from zlut_check_header/read_gz_file in SLUS_000.00) ---
# Each member is "<decimal usize> <name>\n" followed by a stock gzip stream
# (1f 8b 08 08, FNAME flag, deflate).  zlut_inflate is plain zlib inflate
# (inflateInit2(-15)) behind that header; no scrambling.  In vf4files.cvm the
# member header sits 2042 bytes BEFORE (base + entry_lba*2048) for every one of
# the 146 *.MRG_GZ entries (measured), so the entry start is not the payload.
MRG_GZ_ENTRY_SKEW = -2042
_GZ_MEMBER = re.compile(rb"(\d{1,10}) ([A-Za-z0-9_.]{1,64})\n(?=\x1f\x8b\x08\x08)")


def iter_gz_members(raw: bytes, start: int = 0, end: int | None = None):
    """Yield (header_offset, usize, name, gzip_offset) for each member."""
    end = len(raw) if end is None else end
    for m in _GZ_MEMBER.finditer(raw, start, end):
        yield m.start(), int(m.group(1)), m.group(2).decode("ascii"), m.end()


def inflate_gz_member(raw: bytes, gz_offset: int, usize: int) -> bytes:
    """Inflate one member and verify the declared size and stream end."""
    d = zlib.decompressobj(31)
    out = d.decompress(raw[gz_offset:gz_offset + max(usize, 1) * 2 + 65536])
    if not d.eof or len(out) != usize:
        raise ValueError(f"gz member size/eof mismatch: {len(out)} != {usize}")
    return out


def parse_mrg_offsets(body: bytes) -> dict:
    """Decoded .mrg body: u32 count, then count ascending u32 sub-file offsets."""
    if len(body) < 8:
        raise ValueError("too short")
    n = struct.unpack_from("<I", body, 0)[0]
    if not 0 < n <= 4096 or 4 + 4 * n > len(body):
        raise ValueError("bad count")
    offs = list(struct.unpack_from(f"<{n}I", body, 4))
    if any(b < a for a, b in zip(offs, offs[1:])) or offs[-1] > len(body):
        raise ValueError("offsets not ascending/in range")
    sizes = [(offs[i + 1] if i + 1 < n else len(body)) - o for i, o in enumerate(offs)]
    return {"count": n, "offsets": offs, "sizes": sizes}


# ---------------------------------------------------------------------------
# Reader stage (request #1319): sub-file formats inside decoded CH_<id>.mrg.
# Evidence: CH_AKI.mrg (sha256 of body f3283b4b..., identical in both
# vf4files.cvm copies), 11 sub-files.  Sub-file 0 is an "mrg.lst" text list
# naming a.bin,b.bin,... for sub-files 1..N-1 (letters skip h,i,l).  Field
# meanings below are measured; anything marked HYPOTHESIS is unproven.
# ---------------------------------------------------------------------------


def split_mrg(body: bytes) -> list:
    info = parse_mrg_offsets(body)
    return [body[o:o + s] for o, s in zip(info["offsets"], info["sizes"])]


def mrg_subfile_kind(sub: bytes) -> str:
    magic = sub[:4]
    if magic == b"LNK0":
        return "LNK0"
    if magic == b"TEX2":
        return "TEX2"
    if sub.startswith(b"mrg.lst"):
        return "mrg.lst"
    return "table"  # name/bone/motion tables: u32 offset-table led, unparsed


def parse_tex2(d: bytes, decode: bool = False) -> list:
    """TEX2: 'TEX2', u32 (0x80000000|count), count x (u16 w, u16 h, u32 off),
    then textures.  Entry = u32 type (0 -> 4bpp/16-colour, 1 -> 8bpp/256-colour),
    RGBA8 palette (alpha 0x80 == opaque), linear pixels (no GS swizzle, no CSM1
    palette swap: neighbour-pixel difference 2.4 vs 8.4 swapped vs 60.8
    shuffled), 4 bytes pad.  entry size == 8 + palette + w*h*bpp/8 (all 27 of
    CH_AKI sub-file 1 verified); the last entry may carry trailing bytes."""
    if d[:4] != b"TEX2":
        raise ValueError("not TEX2")
    n = struct.unpack_from("<I", d, 4)[0] & 0xFFFF
    ents = [struct.unpack_from("<HHI", d, 8 + 8 * i) for i in range(n)]
    offs = [e[2] for e in ents] + [len(d)]
    out = []
    for i, (w, h, o) in enumerate(ents):
        typ = struct.unpack_from("<I", d, o)[0]
        bpp = 8 if typ == 1 else 4
        pal_n = 256 if bpp == 8 else 16
        need = 8 + pal_n * 4 + w * h * bpp // 8
        e = {"w": w, "h": h, "type": typ, "bpp": bpp, "offset": o,
             "size": offs[i + 1] - o, "size_matches": offs[i + 1] - o == need}
        if decode:
            pal = d[o + 4:o + 4 + pal_n * 4]
            px = d[o + 4 + pal_n * 4:o + 4 + pal_n * 4 + w * h * bpp // 8]
            if bpp == 4:
                px = bytes(v for x in px for v in (x & 15, x >> 4))
            cols = [(pal[k], pal[k + 1], pal[k + 2], min(255, pal[k + 3] * 2))
                    for k in range(0, len(pal), 4)]
            e["rgba"] = b"".join(bytes(cols[i]) for i in px)
        out.append(e)
    return out


def parse_lnk0(d: bytes) -> dict:
    """LNK0 container: header u32 magic, ver 8, dir at 0x10 = 0x50 (GMB1 off)
    + other chunk offsets.  GMB1 @0x50: 'GMB1', u32 size, u32 count N, u32
    0x70 (first mesh), then N-1 ascending mesh offsets relative to 0x50.
    STR1 chunk: 'STR1', u32 count, count u32 name offsets (relative to the
    STR1 tag), NUL strings -- names of the N meshes in order (o_arm, o_body_a,
    o_face, t_kao_00_1, ...).  Mesh header: u32 0x54 then 4 section offsets
    (HYPOTHESIS: vertex/index streams) and float bbox data."""
    if d[:4] != b"LNK0":
        raise ValueError("not LNK0")
    base = struct.unpack_from("<I", d, 0x10)[0]
    if d[base:base + 4] != b"GMB1":
        raise ValueError("no GMB1 chunk")
    size, count, first = struct.unpack_from("<3I", d, base + 4)
    offs = [first] + list(struct.unpack_from(f"<{count - 1}I", d, base + 0x10))
    if any(b <= a for a, b in zip(offs, offs[1:])):
        raise ValueError("mesh offsets not ascending")
    names = []
    s = d.find(b"STR1", base + size)
    if s >= 0:
        n = struct.unpack_from("<I", d, s + 4)[0]
        for k in range(n):
            o = struct.unpack_from("<I", d, s + 8 + 4 * k)[0]
            names.append(d[s + o:d.index(b"\0", s + o)].decode("latin1"))
    ends = offs[1:] + [size]
    return {"base": base, "gmb_size": size, "mesh_count": count,
            "meshes": [{"off": base + a, "size": b - a,
                        "name": names[i] if i < len(names) else None}
                       for i, (a, b) in enumerate(zip(offs, ends))],
            "names": names}


def parse_mrg_lst_bins(sub0: bytes) -> list:
    """Names listed in sub-file 0 ('mrg.lst' text), e.g. ['a.bin', ..., 'm.bin']."""
    txt = sub0.split(b"\0", 1)[0].decode("latin1")
    return [l.strip() for l in txt.splitlines() if l.strip().endswith(".bin")]
