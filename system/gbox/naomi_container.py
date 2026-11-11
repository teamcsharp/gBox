"""Reader for Sega NAOMI / NAOMI-2 ROM-board containers (IC1..ICn mask ROMs).

A NAOMI cart is a bank of 8 MB mask ROMs.  Chip 0 (IC1) opens with a 16-byte
ASCII title, a 12-entry little-endian u32 *physical* file table at 0x10, and
physical file 0 is a plain-text manifest ("rom.lst") naming every logical
asset the game expects, grouped into sections:

    rom.lst
    %rom_texture
    sprpal.thb
    ...
    %poly_hie
    chr0000.mtd
    chr0000.pl4
    chr0000.thb
    ...

Logical names are therefore offset by one relative to the physical table
(physical file 0 is the manifest itself).  Section markers tell us the role of
each group: %rom_texture = texture containers (.thb), %rom_poly = the encrypted
model blob (.enc), %poly_hie = character hierarchy + per-character model
(.mtd/.pl4/.thb), %rom_field = field layouts, %rom_sound = sound banks.

The .pl4 entries under %poly_hie are the character ("chr") geometry assets
that a native character replacement must retarget.
"""

from __future__ import annotations

import hashlib
import struct

TITLE_LEN = 16
TABLE_OFFSET = 0x10
MAX_TABLE_ENTRIES = 12

__all__ = [
    "sha256_stream",
    "is_naomi_container",
    "parse_file_table",
    "parse_manifest",
    "find_model_runs",
    "describe_container",
]


def sha256_stream(path, chunk=1 << 20):
    """SHA-256 of a file, streamed (never a copied reference hash)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def parse_file_table(data):
    """Physical file table of a NAOMI ROM-board chip as a list of dicts."""
    entries = struct.unpack_from("<%dI" % MAX_TABLE_ENTRIES, data, TABLE_OFFSET)
    out = []
    for i, start in enumerate(entries):
        end = entries[i + 1] if i + 1 < len(entries) else len(data)
        out.append({"index": i, "offset": start, "end": end, "size": end - start})
    return out


def is_naomi_container(data):
    """True when data starts with a plausible NAOMI ROM-board file table."""
    if len(data) < TABLE_OFFSET + 4 * MAX_TABLE_ENTRIES:
        return False
    entries = struct.unpack_from("<%dI" % MAX_TABLE_ENTRIES, data, TABLE_OFFSET)
    if any(entries[i] >= entries[i + 1] for i in range(len(entries) - 1)):
        return False
    return 0x100 <= entries[0] and entries[-1] <= len(data)


def parse_manifest(data, files=None):
    """Parse the rom.lst manifest stored in physical file 0.

    Returns dict with 'sections' (ordered list of {'name', 'files'}) and
    'order' (flat list of logical names).
    """
    files = files or parse_file_table(data)
    blob = data[files[0]["offset"]:files[0]["end"]]
    text = blob.decode("ascii", "replace")
    root = {"name": None, "files": []}
    cur = root
    sections = [root]
    order = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line == "*":
            continue
        if line.startswith("%"):
            cur = {"name": line, "files": []}
            sections.append(cur)
            continue
        cur["files"].append(line)
        order.append(line)
    names = [s["name"] for s in sections if s["name"]]
    return {"sections": sections, "section_names": names, "order": order, "root": root}


def find_model_runs(data, scan_fn):
    """Group scanned models into contiguous byte runs.

    scan_fn(data) must yield dicts with 'offset' and 'end_offset'.
    Returns (runs, models) where each run is
    {'start', 'end', 'bytes', 'models'}.
    """
    models = sorted(scan_fn(data), key=lambda m: m["offset"])
    runs = []
    for m in models:
        if runs and m["offset"] == runs[-1]["end"]:
            runs[-1]["end"] = m["end_offset"]
            runs[-1]["models"] += 1
        else:
            runs.append({"start": m["offset"], "end": m["end_offset"], "models": 1})
    for r in runs:
        r["bytes"] = r["end"] - r["start"]
    return runs, models


def describe_container(path, scan_fn=None):
    """Summarise a NAOMI ROM-board chip: hash, table, manifest, model runs."""
    with open(path, "rb") as fh:
        data = fh.read()
    files = parse_file_table(data)
    manifest = parse_manifest(data, files)
    out = {
        "path": str(path),
        "bytes": len(data),
        "title": data[:TITLE_LEN].decode("ascii", "replace").rstrip("\x00 "),
        "is_container": is_naomi_container(data),
        "files": files,
        "sections": [s["name"] for s in manifest["sections"] if s["name"]],
        "logical_names": manifest["order"],
    }
    if scan_fn is not None:
        runs, models = find_model_runs(data, scan_fn)
        out["model_count"] = len(models)
        out["model_runs"] = runs
        for r in runs:
            r["file"] = next(
                (f["index"] for f in files if f["offset"] <= r["start"] < f["end"]), None
            )
    return out
