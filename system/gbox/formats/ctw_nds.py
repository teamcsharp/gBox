"""Owned-build inventory helpers for Grand Theft Auto: Chinatown Wars (NDS).

The owned Nintendo DS build does not keep its assets as plain NitroFS files.
`gbox.formats.nitro` reads the NitroFS container, and this module adds the
CTW-specific view on top of it:

  * the Rockstar container members named by the NitroFS directory
    (ROM.TOC / ROM.WAD / game.pak / dwc/utility.bin) with byte-exact FAT ranges,
  * the full NitroFS FAT table, which for this build enumerates every
    addressable payload range of the ROM,
  * a streaming sha256 of the owned source, so the build identity is recorded
    by hashing the actual bytes rather than copying a reference digest.

Scope note: this stops at the container boundary.  The internal record layout
of ROM.TOC / ROM.WAD / game.pak is not established yet, so nothing here claims
to read a character, mesh, skeleton or texture.
"""

from __future__ import annotations

import hashlib
import json
import os

from . import nitro

# Container members named by the NitroFS directory of the owned build.
MEMBERS = ("ROM.TOC", "ROM.WAD", "game.pak", "dwc/utility.bin")

ROM_HEADER_SIZE = 0x200


def sha256_stream(path, chunk_size=1 << 20):
    """Hash a file by streaming its bytes; never loads the whole file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value):
    """Normalise a ROM header string field to bytes without NUL padding."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value.rstrip(b"\x00")
    return str(value).encode("latin-1").rstrip(b"\x00")


def _field(rom, *names):
    """Return the first present attribute of ``rom`` among ``names``."""
    for name in names:
        value = getattr(rom, name, None)
        if value is not None:
            return value
    return None


def fat_entries(rom):
    """Return every NitroFS FAT entry as an ordered list of dicts.

    The owned CTW build names four files in the NitroFS directory but the FAT
    carries one entry per addressable payload range, so this table is the
    authoritative owned-build manifest of the ROM payload.
    """
    entries = []
    for file_id, (start, end) in enumerate(rom.fat):
        entries.append({"file_id": file_id, "start": start, "end": end,
                        "size": end - start})
    return entries


def member_table(rom):
    """Return the named CTW container members with byte-exact FAT ranges."""
    members = []
    for name in MEMBERS:
        file_id = rom.ids[name.lower()]
        start, end = rom.fat[file_id]
        members.append({"name": name, "file_id": file_id, "start": start,
                        "end": end, "size": end - start})
    members.sort(key=lambda m: m["start"])
    return members


def overlaps(ranges):
    """Return every pair of ranges that share bytes.

    ``ranges`` is a list of dicts with ``start``/``end`` keys and an optional
    ``name``.  All pairs are checked, so the result does not depend on the
    order of the input table.
    """
    found = []
    for index, first in enumerate(ranges):
        for second in ranges[index + 1:]:
            if first["start"] < second["end"] and second["start"] < first["end"]:
                found.append([first.get("name", first["file_id"]),
                              second.get("name", second["file_id"])])
    return found


def manifest(path):
    """Build the authoritative manifest of the owned build at ``path``."""
    with open(path, "rb") as handle:
        data = handle.read()
    rom = nitro.NitroROM(data)
    entries = fat_entries(rom)
    members = member_table(rom)
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return {
        "source_path": os.path.abspath(path),
        "source_size": len(data),
        "source_sha256": sha256_stream(path),
        "rom_title": _text(rom.title).decode("latin-1"),
        "rom_gamecode": _text(rom.gamecode).decode("latin-1"),
        "arm9": {"offset": rom.arm9_off, "entry": rom.arm9_entry,
                 "ram": rom.arm9_ram, "size": rom.arm9_size},
        "arm7": {"offset": _field(rom, "arm7_off", "arm7_rom_off"),
                 "entry": _field(rom, "arm7_entry"),
                 "ram": _field(rom, "arm7_ram"),
                 "size": _field(rom, "arm7_size")},
        "nitrofs": {"fnt_offset": rom.fnt_off, "fnt_size": rom.fnt_size,
                    "fat_offset": rom.fat_off, "fat_size": rom.fat_size,
                    "fat_entries": len(rom.fat)},
        "members": members,
        "member_overlaps": overlaps(members),
        "fat_overlaps": overlaps(entries),
        "out_of_bounds_fat_entries": [e for e in entries
                                      if e["start"] < 0 or e["end"] > len(data)
                                      or e["end"] < e["start"]],
        "fat_manifest_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "fat_manifest": entries,
    }
