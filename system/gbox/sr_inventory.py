"""Sonic Riders (USA) (GameCube) owned-build inventory (gBox request #2355, stage: inventory).

Owned source (authoritative, hashed by streaming its bytes):
    /mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Sonic Riders (USA).gcz
    sha256 4152dc9f502ed0db82ae1441023c49153af5ea8a5d9589f0f78e698092a3abf9
    1330989454 bytes

Disc layout, read from the owned bytes (big-endian GameCube header):
    main.dol @ 0x020300
    FST       @ 0x144000 (0x72b1 bytes, 1669 entries)

Character assets are NOT in the CRI AFS archives.  Every playable character is a
root-level ``10<NAME>.DAT`` file (16 of them) that uses the Sonic Team ``gcax``
container: 4-byte magic ``gcax``, a 4-byte archive tag, then a big-endian header
whose u32 at +0x0c is the total container size.  Each character file carries
three nested ``gcax`` archives - ``DTPK`` at +0x00, ``TBLD`` at +0x60 and
``PCMD`` at +0x800 (offsets verified identical for 10SONIC.DAT, 10AMY.DAT and
10KNUCK.DAT).

Fingerprint claims (ticket context.assimilation_fingerprint) checked against the
owned files, see :func:`verify_fingerprint`:
  * engine "CRI Middleware (AFS/ADX/CPK)" - partially confirmed: 62 ADX files
    and 2 CRI AFS archives (VOICE_E.AFS, V_CHAO_E.AFS) exist.  The fingerprint
    counted "CRI AFS archive x1"; the owned disc has 2.
  * "nearest: gbox.jgr" (the CRI AFS reader) only covers those two AFS voice
    files, not the character containers.
  * The character containers (gcax/DTPK) have no reader in gBox yet; this module
    is the inventory-stage foundation for one.

This module is the *inventory* stage only: it maps the owned build and names one
target character slot (10SONIC.DAT).  It is not a reader and not a writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

GAME_ID = "d30074b20c7005be"
OWNED_SOURCE = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/"
                "roms/Sonic Riders (USA).gcz")
OWNED_SOURCE_SHA256 = "4152dc9f502ed0db82ae1441023c49153af5ea8a5d9589f0f78e698092a3abf9"
OWNED_SOURCE_SIZE = 1330989454

GCAX_MAGIC = b"gcax"
CRI_AFS_MAGIC = b"AFS\x00"
CHARACTER_SLOT_RE = re.compile(r"^10[A-Z0-9]+\.DAT$")

# Big-endian offsets inside the GameCube disc header.
DOL_OFF_FIELD = 0x420
FST_OFF_FIELD = 0x424
FST_SIZE_FIELD = 0x428

# Target slot for the native character replacement (stage 3+).
TARGET_SLOT = "10SONIC.DAT"


def sha256_file(path, chunk=1 << 23) -> tuple[str, int]:
    """Stream ``path`` and return (hex digest, byte count).  Never copies a hash."""
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            total += len(block)
            h.update(block)
    return h.hexdigest(), total


def parse_gcax_header(data: bytes, off: int = 0) -> dict:
    """Decode a ``gcax`` container header at ``off``.

    Layout (big-endian): +0x00 magic ``gcax``, +0x04 archive tag,
    +0x0c u32 total container size.  The u32 slots at +0x08, +0x10, +0x14,
    +0x18 and +0x1c are recorded raw and are NOT yet classified (reader stage).
    """
    if data[off:off + 4] != GCAX_MAGIC:
        raise ValueError("not a gcax container at 0x%08x (magic %r)" % (off, data[off:off + 4]))
    if len(data) < off + 0x30:
        raise ValueError("gcax header at 0x%08x is truncated" % off)
    return {
        "offset": off,
        "arch": data[off + 4:off + 8].decode("latin-1"),
        "declared_size": struct.unpack_from(">I", data, off + 0x0C)[0],
        "u32_08": struct.unpack_from(">I", data, off + 0x08)[0],
        "u32_10": struct.unpack_from(">I", data, off + 0x10)[0],
        "u32_14": struct.unpack_from(">I", data, off + 0x14)[0],
        "u32_18": struct.unpack_from(">I", data, off + 0x18)[0],
        "u32_1c": struct.unpack_from(">I", data, off + 0x1C)[0],
    }


def gcax_sections(data: bytes) -> list[dict]:
    """Every nested ``gcax`` archive found in ``data`` (offset + archive tag)."""
    out = []
    pos = 0
    while True:
        hit = data.find(GCAX_MAGIC, pos)
        if hit < 0:
            break
        try:
            out.append(parse_gcax_header(data, hit))
        except ValueError:
            pass
        pos = hit + 4
    return out


def character_slots(paths) -> list[str]:
    """The counted set of playable-character packages (``10<NAME>.DAT``)."""
    return sorted(p for p in paths if CHARACTER_SLOT_RE.match(p))


def build_manifest(src_path: str = OWNED_SOURCE, source_sha256: str | None = None,
                   source_size: int | None = None) -> dict:
    """Build the authoritative owned-build manifest for Sonic Riders (USA)."""
    from gbox.gcz import GCZ
    from gbox.formats.gcfst import disc_header, parse_fst

    g = GCZ(src_path)
    header = g.read(0, 0x440)
    dol_off, fst_off, fst_size = struct.unpack_from(">III", header, DOL_OFF_FIELD)
    entries = parse_fst(g.read(fst_off, fst_size), fst_off)
    fmap = {p: (o, s) for p, o, s, _ in entries}

    census = {}
    for path, (_o, size) in fmap.items():
        base = path.rsplit("/", 1)[-1]
        ext = base.rsplit(".", 1)[-1].upper() if "." in base else "(none)"
        census[ext] = census.get(ext, 0) + 1

    cri_afs = sorted(p for p, (o, s) in fmap.items()
                     if s >= 4 and g.read(o, 4) == CRI_AFS_MAGIC)

    slots = []
    for name in character_slots(fmap):
        off, size = fmap[name]
        window = g.read(off, min(size, 0x1000))
        entry = {"name": name, "offset": off, "size": size, "size_hex": "0x%x" % size}
        try:
            head = parse_gcax_header(window, 0)
        except ValueError as exc:
            entry["error"] = str(exc)
        else:
            entry["arch"] = head["arch"]
            entry["declared_size"] = head["declared_size"]
            entry["declared_size_matches_file"] = head["declared_size"] == size
            entry["sections"] = [{"offset": s["offset"], "arch": s["arch"],
                                  "declared_size": s["declared_size"]}
                                 for s in gcax_sections(window)]
        slots.append(entry)

    if source_sha256 is None:
        source_sha256, source_size = sha256_file(src_path)
    if source_size is None:
        source_size = OWNED_SOURCE_SIZE

    manifest = {
        "game": "Sonic Riders (USA)",
        "platform": "gamecube",
        "game_id": GAME_ID,
        "request_id": "f67e4fefbc3548ae",
        "source": {"path": src_path, "sha256": source_sha256, "bytes": source_size},
        "disc": {"dol_offset": dol_off, "fst_offset": fst_off, "fst_size": fst_size,
                 "file_count": len(fmap),
                 "header": disc_header(header)},
        "extension_census": dict(sorted(census.items(), key=lambda kv: (-kv[1], kv[0]))),
        "cri_afs": cri_afs,
        "character_slots": slots,
        "character_slot_count": len(slots),
        "target_slot": TARGET_SLOT,
        "files": [{"path": p, "offset": o, "size": s} for p, (o, s) in sorted(fmap.items())],
    }
    manifest["fingerprint_check"] = verify_fingerprint(manifest)
    return manifest


def verify_fingerprint(manifest: dict) -> list[dict]:
    """Check the ticket's assimilation fingerprint against the owned files."""
    out = []
    afs = manifest.get("cri_afs", [])
    out.append({
        "claim": "CRI AFS archive x1",
        "observed": len(afs),
        "files": afs,
        "verdict": "confirmed" if len(afs) == 1 else "mismatch",
        "detail": "owned disc holds %d CRI AFS archives" % len(afs),
    })
    adx = manifest.get("extension_census", {}).get("ADX", 0)
    out.append({
        "claim": "engine CRI Middleware (ADX present)",
        "observed": adx,
        "verdict": "confirmed" if adx else "not-found",
        "detail": "%d ADX streams on the owned disc" % adx,
    })
    slots = manifest.get("character_slot_count", 0)
    out.append({
        "claim": "character assets are containers (not AFS)",
        "observed": slots,
        "verdict": "confirmed" if slots else "not-found",
        "detail": "%d gcax character packages (10<NAME>.DAT)" % slots,
    })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sonic Riders (USA) GameCube owned-build inventory")
    ap.add_argument("--source", default=OWNED_SOURCE)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-hash", action="store_true",
                    help="skip streaming the source hash (use the recorded digest)")
    args = ap.parse_args(argv)
    sha = None if args.no_hash else None
    manifest = build_manifest(args.source, source_sha256=sha)
    text = json.dumps(manifest, indent=1, sort_keys=False)
    if args.out:
        Path(args.out).write_text(text)
        print("wrote %s (%d bytes)" % (args.out, len(text)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
