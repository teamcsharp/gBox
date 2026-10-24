"""Kirby: Canvas Curse (USA, NDS, game code ATKE, header title "TOUCH!KIRBY") - owned-build inventory probe.

Scope: INVENTORY only. Identifies the cartridge, walks NitroFS through gbox.formats.nitro.NitroROM and classifies the
per-character animation bundles. No sprite/tile/palette decoding and no writer exists yet.

Observed on the owned ROM (sha256 c416113d3300029354780c0f1c1cb0aff5b71a567d55b196349f2f27aaa73ca0, 67108864 bytes,
extracted from "Kirby - Canvas Curse (USA).7z"); little-endian, offsets relative to the start of each NitroFS member:

  * 2178 NitroFS members (2177 ``romdir/bank*bin/*.bin`` + ``romdir/sound_data.sdat``), ARM9 at 0x4000 (ram 0x02000000,
    875384 bytes), ARM7 at 0x1AE800 (146604 bytes), a 288-byte ARM9 overlay table at 0xD9C00.
  * Most bank members start with a 3-word header ``kind, count, size``. kind 5 / 6 are the two leading kinds seen
    (301 and 212 members). ``kbynml_*`` (normal Kirby ball), ``kbyndl_*`` (needle) etc. are kind 6.
  * HYPOTHESIS (holds for every kind-6 member that matches below, not independently proven): a kind-6 member is
    ``len == size + 4 * count + 4``, i.e. a ``count``-entry frame/animation table after the payload. Fields beyond the
    first 12 bytes are unproven.
  * 899 members parse as LZ10 (type byte 0x10); LZ77-wrapped members are not used by this title.
"""
from __future__ import annotations

import hashlib
import struct

from .nitro import NitroROM

GAME_CODE = "ATKE"
HEADER_TITLE = "TOUCH!KIRBY"
SOURCE_SHA256 = "c416113d3300029354780c0f1c1cb0aff5b71a567d55b196349f2f27aaa73ca0"  # owned-build identity, not a gate
CHARACTER_PREFIXES = ("kby", "dede")  # Kirby / King Dedede bundles; other prefixes are unclassified


def identify(rom: NitroROM) -> dict:
    return {"title": rom.title, "gamecode": rom.gamecode, "is_canvas_curse": rom.gamecode == GAME_CODE and rom.title == HEADER_TITLE,
            "arm9": {"offset": rom.arm9_off, "entry": rom.arm9_entry, "ram": rom.arm9_ram, "size": rom.arm9_size},
            "members": len(rom.names)}


def bundle_header(blob: bytes) -> dict | None:
    """Parse the 3-word member header; None when too short. Never reads past the blob."""
    if len(blob) < 12:
        return None
    kind, count, size = struct.unpack_from("<3I", blob)
    return {"kind": kind, "count": count, "size": size,
            "table_hypothesis_ok": kind == 6 and count <= 0xFFFF and len(blob) == size + 4 * count + 4}


def inventory(data: bytes) -> dict:
    rom = NitroROM(data)
    ident = identify(rom)
    chars: dict[str, dict] = {}
    kinds: dict[int | str, int] = {}
    for fid, path in sorted(rom.names.items()):
        h = bundle_header(rom.file(fid))
        if h is None:
            continue
        k = h["kind"] if h["kind"] in (5, 6) else "other"
        kinds[k] = kinds.get(k, 0) + 1
        base = path.rsplit("/", 1)[-1]
        if base.startswith(CHARACTER_PREFIXES) and h["kind"] == 6:
            chars[path] = {"file_id": fid, **h}
    return {**ident, "sha256": hashlib.sha256(data).hexdigest(), "kind_census": kinds, "character_bundles": chars}
