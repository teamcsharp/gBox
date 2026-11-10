"""Thrasher: Skate and Destroy (USA) PSX source inventory.

Rockstar Games / Z-Axis Games, 1999, SLUS-009.35. Owned source: PlayStation
disc image
``Thrasher - Skate and Destroy (USA)/Thrasher - Skate and Destroy (USA).bin``
(MODE2/2352 single data track, 367 MB; SHA256 below). Read it with
:class:`gbox.psxdisc.RawBin` (ISO9660 over MODE2/2352 sectors).

This game is built on the Z-Axis "libovr" runtime (the same engine family as
Dave Mirra Freestyle BMX). Its executable is mostly the PSX SDK runtime
(libgs/libcd/libsnd -- ``CdSearchFile``/``CD_newmedia``/``CD_cachefile``
strings confirm all disc access is *by file name* through the ISO9660
directory, not a hardcoded sector table) plus Z-Axis engine core
(``zactorSetMaxActors``, ``ZMEMDMM``, ``PsxMovie``, ``zge/psx/sound/psxchan.c``).
All game data lives in ``.ZAL`` (Z-Axis Labs) archive files under ``ASSETS/``.

Disc layout (62 files, from the PVD; see :func:`disc_layout`):

* Boot chain: ``SYSTEM.CNF`` -> ``SLUS_009.35`` (boot EXE) -> ``PLAYMOV.EXE``
  (STR movie player).
* ``ASSETS/*.ZAL`` archives: ``GEOMETRY.ZAL`` (meshes), ``MATERIAL.ZAL``
  (textures/materials, 653 KB), ``MOTION.ZAL`` (animations), ``TABLES.ZAL``
  (level/skater registry -- see below), ``MISCDATA.ZAL``, ``SYSTEM.ZAL``,
  ``REPLAY.ZAL``, ``RBINTART.ZAL`` (14 MB, intro art), plus one ``.ZAL`` per
  skate level (13 files: ``HM_INDUS``, ``IN_KOL``, ``IN_SOBA``, ``LA_COURT``,
  ``LA_RIVER``, ``LA_VEN``, ``NY_BROOK``, ``NY_SUB``, ``NY_WASH``, ``SF_CHINA``,
  ``SF_EMB``, ``SF_HILL``, ``RBINTART``).
* ``AUDIO/*.ZSD`` sound banks: ``MUSIC.ZSD`` (170 MB), ``SPEECH.ZSD`` (12 MB),
  ``SFXCOM.ZSD``, ``SFXGAME.ZSD``, ``SFXMENU.ZSD``, ``SFXCHR00..06.ZSD``
  (per-character banks), ``SFXLEV00..11.ZSD`` (per-level banks).
* ``MOVIE/*.STR`` PSX movies (INTRO, HOMETWN, LOSANG, NEWYORK, SANFRAN,
  ROCKSTR, OUTRO, INTER, ZAXIS).
* ``AISDATA.BIN``/``AITEXT.BIN``/``FRSDATA.BIN``/``FRTEXT.BIN``: skater AI and
  "freeskate" text/stat data. ``OPTIONS.TXT``: engine tune options (INI-style).
* ``PADDING.NUL`` (53 MB) pads the small data track to a full disc image.

``ZAL`` archive container (header confirmed on every ``.ZAL`` on this disc):

* u32 magic ``0x2A81511C`` (bytes ``1c 51 81 2a``), 12 zero bytes, then
  ``u16 version`` = 1 and ``u16 chunk_count``. The chunk table follows the
  20-byte header; each table entry is 8 bytes (``u32 offset``, ``u32 size``).
  Chunk payloads are IFF-style, starting with a 4CC tag (``ZMHD``, ``ZMAP``,
  ``FORM``, ...). The *exact* per-entry field semantics for level ``.ZAL``
  files (e.g. ``HM_INDUS``) still need a dedicated table decode; this module
  pins the header facts and the chunk walk so that decode is the next stage.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from . import psxdisc

# Owned disc identity (computed over the mastered .bin image).
DISK_BIN_SHA256 = "8f27d45bee0176ed90267cfaab966d4e466df978a4c6a2beba97764e0866d3c0"
EXE_SHA256 = "56333fe9cadc2de64dffc69d0898528d11b13206c87edf853bfd35cbcbf14dfe"

BOOT_EXE = "SLUS_009.35"
ZAL_MAGIC = 0x2A81511C

#: 13 on-disc level archives (TABLES.ZAL maps internal names -> these files).
LEVEL_ZALS = (
    "HM_INDUS", "IN_KOL", "IN_SOBA", "LA_COURT", "LA_RIVER", "LA_VEN",
    "NY_BROOK", "NY_SUB", "NY_WASH", "SF_CHINA", "SF_EMB", "SF_HILL",
)


def exe_header(b: bytes) -> dict:
    """Parse the PS-X EXE header of the boot EXE (standard 10-word layout)."""
    if len(b) < 0x800 or b[:8] != b"PS-X EXE":
        return {"magic": None, "size": len(b)}
    pc0, gp0, t_addr, t_size, d_addr, d_size, b_addr, b_size, s_addr, s_size = (
        struct.unpack_from("<10I", b, 0x10))
    region = b[0x4C:0x9C].split(b"\0")[0].decode("latin1", "replace")
    return {
        "magic": "PS-X EXE",
        "size": len(b),
        "pc0": pc0,
        "gp0": gp0,
        "t_addr": t_addr,
        "t_size": t_size,
        "d_addr": d_addr,
        "d_size": d_size,
        "b_addr": b_addr,
        "b_size": b_size,
        "s_addr": s_addr,
        "s_size": s_size,
        "region": region,
        "text_span": (t_addr, t_addr + t_size),
    }


def zal_header(b: bytes) -> dict:
    """Parse a ``.ZAL`` archive's 20-byte header.

    Confirmed on this disc: u32 magic ``0x2A81511C``, 12 zero bytes, then a
    ``u16`` whose *high bit* selects the archive kind:

    * ``version == 0x0001`` -> "table"/index archive (TABLES, GEOMETRY,
      MISCDATA, REPLAY, RBINTART). The low bit word is the version and the
      following ``u16`` is the (real) chunk count.
    * ``version == 0x8001`` -> "data" archive (MATERIAL, MOTION, SYSTEM and all
      13 level ``.ZAL`` files). Here the field after version is a large block
      count (16.5k..17k), not a per-chunk table of the same shape.

    Returns ``{"magic", "version", "kind", "count"}``; ``count`` is meaningful
    only for ``kind == "table"``.
    """
    if len(b) < 20 or struct.unpack_from("<I", b, 0)[0] != ZAL_MAGIC:
        raise ValueError("not a ZAL archive (bad magic)")
    version, count = struct.unpack_from("<HH", b, 16)
    kind = "data" if version >= 0x8000 else "table"
    return {
        "magic": ZAL_MAGIC,
        "version": version,
        "kind": kind,
        "count": count,
    }


def parse_tables_zal(b: bytes) -> list:
    """Decode ``TABLES.ZAL``'s level/skater name -> ``.ZAL`` references.

    ``TABLES.ZAL`` is a ``ZMHD`` + ``ZMAP`` chunk pair (IFF-style). Each row is
    a null-padded title (16 bytes) followed by a right-justified ``.ZAL``
    filename (12 bytes) and a ``.ZAL`` marker; rows sit at 100-byte strides.
    Confirmed on this disc: the level ``.ZAL`` names sit at 100-byte strides
    (``SF_CHINA``, ``HM_INDUS``, ... ``SF_HILL``).

    The filename is the ASCII ``[A-Za-z0-9_]`` run ending exactly at the
    ``.ZAL`` marker; the title is the last ASCII ``[A-Za-z0-9 ]`` run before
    that filename field (after stripping the null padding). This yields a clean
    ``name``/``zal`` split (e.g. ``"WASHINGTON SQUARE" -> "NY_WASH"``). The
    filename run is then resolved against :data:`LEVEL_ZALS` to pin any
    title-tail leak. Returns ``[{"name", "zal"}, ...]`` in table order.
    """
    import re

    records = []
    pos = 0
    while True:
        i = b.find(b".ZAL", pos)
        if i < 0:
            break
        # Filename: right-justified ASCII run ending at the marker.
        m = re.search(rb"[A-Za-z0-9_]+\Z", b[max(0, i - 32):i])
        raw = m.group(0).decode("latin1") if m else ""
        zal = _resolve_zal_name(raw)
        # Title: last ASCII run before the filename field (best effort).
        pre = b[max(0, i - 32):i - len(raw)].rstrip(b"\0")
        tm = re.search(rb"[A-Za-z0-9 ]+$", pre)
        name = tm.group(0).decode("latin1").strip() if tm else ""
        records.append({"name": name, "zal": zal})
        pos = i + 4
    return records


def _resolve_zal_name(raw: str) -> str:
    """Map an over-read filename run to its true on-disc ``.ZAL`` basename.

    Variable-width title fields mean a run like ``RENY_WASH`` (title tail
    ``RE`` + real name ``NY_WASH``) must be trimmed to the known basename.
    """
    if raw in LEVEL_ZALS:
        return raw
    for name in LEVEL_ZALS:
        if raw.endswith(name):
            return name
    # Test/skater Z_* and other names: strip a leaked title tail by preferring
    # the longest known level-name substring present in the run.
    for name in sorted(LEVEL_ZALS, key=len, reverse=True):
        if name in raw:
            return name
    return raw


def disc_layout(bin_path: str | Path) -> list[dict]:
    """List every file on the disc (name, LBA, byte size) from the PVD."""
    rb = psxdisc.RawBin(str(bin_path), writable=False)
    try:
        return [
            {"name": name, "lba": lba, "size": size}
            for name, (lba, size) in sorted(rb.files.items())
        ]
    finally:
        rb.close()


def _sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("bin_path")
    args = ap.parse_args()
    print(json.dumps(disc_layout(args.bin_path), indent=2))
