"""Resident Evil Survivor 2 - Code: Veronica (PS2 Europe) owned-source inventory.

Reads the extracted PS2 CD image (2048-byte sectors) through gta_rw.iso_files, resolves the
SYSTEM.CNF boot executable, hashes it, classifies top-level containers and locates candidate
character/model/texture/animation assets. Writes a JSON manifest keyed by the owned CHD sha256.

Usage:
    python -m gbox.gs2_inventory DISC.ISO --chd-sha256 <hex> [--out m.json]

The owned source is the HyperSpin CHD (CD-type, cdlz/cdzl/cdfl) at
`collections/Sony Playstation 2/roms/Europe/Resident Evil Survivor 2 - Code - Veronica (Europe).chd`.
Stage it once with `chdman extractcd -i source.chd -o disc.cue -ob disc.iso`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from .gta_rw import iso_files

SECTOR = 2048

CONTAINER_MAGICS = {
    b"AFS\x00": "afs",
    b"PACK": "pack",          # generic Capcom pack header guess; refined below
    b"DAR\x00": "dar",
    b"\x00\x00\x00\x00": None,  # too generic to classify by magic alone
}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while (b := f.read(chunk)):
            h.update(b)
    return h.hexdigest()


def boot_name(cnf: str) -> str | None:
    """'BOOT2 = cdrom0:\\SLES_505.97;1' -> 'SLES_505.97' (upper case, no version)."""
    for line in cnf.splitlines():
        if line.strip().upper().startswith("BOOT2"):
            name = line.split("=", 1)[1].strip()
            name = name.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(":", 1)[-1]
            name = name.split(";", 1)[0].strip().upper()
            return name or None
    return None


def read_file(files: dict, name: str, fh) -> bytes:
    """Read a whole file from the ISO through an open file handle; files[name] = (lba, size)."""
    lba, size = files[name]
    fh.seek(lba * SECTOR)
    return fh.read(size)


def read_files(iso: Path, files: dict, names) -> dict[str, bytes]:
    with open(iso, "rb") as f:
        return {n: read_file(files, n, f) for n in names if n in files}


def classify(path: str, size: int) -> str:
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    by_ext = {
        "AFS": "afs", "DAT": "dat", "BIN": "bin", "PAK": "pak", "PAC": "pac",
        "TPL": "tpl", "TIM2": "tim2", "TIM": "tim", "PSS": "pss", "SFX": "sfx",
        "IRX": "irx", "IMG": "img", "IPU": "ipu", "PZZ": "pzz", "CNF": "cnf",
        "ELF": "elf", "SEG": "seg", "MDL": "mdl", "ANM": "anm", "MOT": "mot",
        "TEX": "tex", "VAG": "vag", "BD": "bd", "HD": "hd",
    }
    if ext in by_ext:
        return by_ext[ext]
    return "other"


def afs_pairs(head: bytes) -> list[tuple[int, int]]:
    """CRI-style AFS header: 'AFS\\0' (or 'AFS '), u32 N at +4, then N interleaved (offset, size)
    u32 pairs at +8 (this game's variant — NOT the two separate tables of stock AFS).
    Offsets are sorted ascending and extents stay inside the archive."""
    if head[:3] != b"AFS":
        raise ValueError("not an AFS archive")
    n = struct.unpack_from("<I", head, 4)[0]
    stream = struct.unpack_from("<%dI" % (2 * n), head, 8)
    pairs = [(stream[i], stream[i + 1]) for i in range(0, 2 * n, 2)]
    return pairs


def sniff(data: bytes) -> str:
    if data.startswith(b"TIM2"):
        return "tim2"
    if data.startswith(b"MPAC"):
        return "mpac"
    if data[4:7] == b"MDL":
        return "mdl"
    if data[8:12] == b"SKIN":
        return "skin"
    if data.startswith(b"dummy_data"):
        return "dummy"
    if not data.strip(b"\x00"):
        return "zero"
    return "other"


def mdl_header(data: bytes) -> dict | None:
    """MDL model header: u32 (varies), 'MDL', u16 0x10bc constant, u16 type 1..7."""
    if len(data) < 12 or data[4:7] != b"MDL":
        return None
    u32v = struct.unpack_from("<I", data, 0)[0]
    a, t = struct.unpack_from("<HH", data, 8)
    return {"u32": u32v, "const": a, "type": t}


def afs_inventory(iso: Path, files: dict) -> dict:
    """Per-archive entry classification, read straight from the disc image."""
    out = {}
    with open(iso, "rb") as f:
        for name, (lba, size) in sorted(files.items()):
            if not name.endswith(".AFS"):
                continue
            base = lba * SECTOR
            f.seek(base)
            head = f.read(0x4000)
            try:
                pairs = afs_pairs(head)
            except (ValueError, struct.error):
                out[name] = {"error": "no AFS header"}
                continue
            kinds: dict[str, int] = {}
            entries = []
            for i, (off, sz) in enumerate(pairs):
                f.seek(base + off)
                k = sniff(f.read(12))
                kinds[k] = kinds.get(k, 0) + 1
                entries.append({"i": i, "off": off, "size": sz, "kind": k})
            out[name] = {
                "entries": len(pairs),
                "kinds": kinds,
                "mdl": [e for e in entries if e["kind"] == "mdl"],
                "skin": [e for e in entries if e["kind"] == "skin"],
                "tim2": [e for e in entries if e["kind"] == "tim2"],
                "mpac": [e for e in entries if e["kind"] == "mpac"],
            }
    return out


def collect(iso: Path, chd_sha256: str) -> dict:
    if not iso.exists():
        raise FileNotFoundError(iso)
    iso_sha = sha256_of(iso)
    with open(iso, "rb") as f:
        files = iso_files(f)
        cnf = None
        boot = None
        if "SYSTEM.CNF" in files:
            cnf = read_file(files, "SYSTEM.CNF", f).decode("ascii", "replace").strip()
            boot = boot_name(cnf)
        boot_sha = None
        boot_size = None
        if boot and boot in files:
            b = read_file(files, boot, f)
            boot_sha = hashlib.sha256(b).hexdigest()
            boot_size = len(b)

        # top-level directory names (first path component before '/')
        tops: dict[str, list] = {}
        ext_counts: dict[str, int] = {}
        total = 0
        samples: dict[str, dict] = {}
        for p, (lba, size) in files.items():
            total += size
            top = p.split("/", 1)[0] if "/" in p else "(root)"
            tops.setdefault(top, []).append((p, lba, size))
            kind = classify(p, size)
            ext_counts[kind] = ext_counts.get(kind, 0) + 1
            if kind in ("afs", "pak", "pac", "dat") and size >= 0x800:
                samples.setdefault(kind, {})[p] = (lba, size)

    manifest = {
        "game_id": "5ec1d297cb44b3ea",
        "title": "Resident Evil Survivor 2 - Code: Veronica",
        "platform": "ps2",
        "region": "Europe",
        "source_chd_sha256": chd_sha256,
        "disc_iso_sha256": iso_sha,
        "disc_bytes": iso.stat().st_size,
        "file_count": len(files),
        "total_file_bytes": total,
        "boot": boot,
        "boot_sha256": boot_sha,
        "boot_size": boot_size,
        "system_cnf": cnf,
        "top_level": {k: {"files": len(v), "bytes": sum(s for _, _, s in v)} for k, v in sorted(tops.items())},
        "ext_counts": dict(sorted(ext_counts.items())),
        "containers": {k: {p: v for p, v in sorted(d.items())} for k, d in sorted(samples.items())},
        "afs": afs_inventory(iso, files),
    }
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iso", type=Path)
    ap.add_argument("--chd-sha256", required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    m = collect(args.iso, args.chd_sha256)
    text = json.dumps(m, indent=1)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
