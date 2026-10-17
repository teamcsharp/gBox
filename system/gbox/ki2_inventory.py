"""Killer Instinct 2 (Midway V-Unit, arcade) inventory.

The owned build is a two-part MAME set (torrentzipped parent zip + v5 CHD hard
disk image).  There is no filesystem on the disk: the R4600 boot ROM reads
sectors directly over the ATA/IDE interface (MAME maps it at 0x10000100), and
the game knows every asset by cylinder/head/sector.  This module hashes and
validates the owned artifacts against the MAME reference set, extracts the raw
image with chdman, and profiles the sector layout so later stages can locate
character data deterministically.

Usage:
    python -m gbox.ki2_inventory SRC --chd kinst2.chd --out manifest.json
where SRC is the kinst2.zip parent set.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

# MAME reference identities (src/mame/rare/kinst.cpp, GAME(1996, kinst2, ...)).
MAME_SET = "kinst2"
MAME_CHD_SHA1 = "e7c9291b4648eae0012ea0cc230731ed4987d1d5"
BOOT_ROM_SHA1 = {
    "ki2-l14.u98": "aa7a2a9d72a47dd0ea2ee7b2776b79288060b179",  # v1.4 (default BIOS)
    "ki2-l13.u98": "771d150fb4de0a2ceb279954b9545458e93e2405",  # v1.3
    "ki2-l11.u98": "fe447f4b1d29b524f57c5ba1890652ef6afff88a",  # v1.1
    "ki2-l10.u98": "756629cd1b51ae50f2b9818765dd3d277c3019b3",  # v1.0
    "ki2_l14p.u98": "85a009638f2eada4c63240fc30a9e7be59afab7f",  # v1.4 AnyIDE (unofficial)
}
SOUND_ROM_SHA1 = {
    "ki2_l1.u10": "acfc9460cd5df01403b7f00b2f68c2a8734ad6d3",
    "ki2_l1.u11": "fe7fc78f1c60b15f2bbdc4c455f55cdf30f48ed4",
    "ki2_l1.u12": "9997a83432cb720f65b40a8af46f31a5d0d16d8e",
    "ki2_l1.u13": "7ff164fc2f079d039921594be92208973d43aa03",
    "ki2_l1.u33": "0ab6dbfb76e9fa2db072e287864ad1f9d514dd9b",
    "ki2_l1.u34": "48456a7b6592c40bc9c664dcd2ee2cfd91942811",
    "ki2_l1.u35": "24a3ff009c8a7f5a0bfcb198b8dcb5df365770d3",
    "ki2_l1.u36": "0fca72c40067034939b984b4bf32972a5a6c26af",
}
ALL_ROM_SHA1 = {**BOOT_ROM_SHA1, **SOUND_ROM_SHA1}

PLATFORM = {
    "machine": "Midway V-Unit",
    "cpu": "MIPS R4600 (little-endian) @ 100 MHz",
    "sound": "Midway DCS-2 (ADSP-2104)",
    "video": "640x480 bitmap framebuffer, 2D pre-rendered sprites",
    "developer": "Rare / Nintendo (Midway license)",
    "year": 1996,
    "mame_set": MAME_SET,
    "core": "mame2016",
}

# The playable roster (sprites live on the CHD; per-character LBA runs are the
# analysis stage's job, the count is fixed by the game's select screen).
ROSTER = [
    "T.J. Combo", "Tusk", "Kim Wu", "Maya", "Jago",
    "Black Orchid", "Fulgore", "Spinal", "Glacius", "Sabrewulf", "Gargos",
]


@dataclass
class ZipAudit:
    path: str
    sha256: str
    missing: list[str]
    unknown: list[str]
    wrong_sha1: list[str]
    bios: dict[str, str]

    @property
    def complete(self) -> bool:
        return not (self.missing or self.wrong_sha1)


def audit_zip(zip_path: str | Path) -> ZipAudit:
    """Hash a kinst2 parent zip and check every member against MAME's set.

    A complete parent set has all 13 files (5 boot ROMs + 8 sound ROMs);
    HyperSpin bundles in the wild often only carry a subset, which still
    boots MAME because only the default BIOS and the sound ROMs are needed.
    """
    zip_path = Path(zip_path)
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    wrong, unknown, bios = [], [], {}
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for name in names:
            if name not in ALL_ROM_SHA1:
                unknown.append(name)
                continue
            h = hashlib.sha1(zf.read(name)).hexdigest()
            if h != ALL_ROM_SHA1[name]:
                wrong.append(f"{name} sha1={h}")
            if name in BOOT_ROM_SHA1:
                bios[name] = h
        missing = sorted(set(ALL_ROM_SHA1) - names)
    return ZipAudit(str(zip_path), sha256, sorted(missing), sorted(unknown), sorted(wrong), bios)


def chd_identity(chd_path: str | Path) -> dict:
    """Parse `chdman info` output for the authoritative CHD identity."""
    out = subprocess.run(
        ["chdman", "info", "-i", str(chd_path)], capture_output=True, text=True, check=True
    ).stdout
    info = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("SHA1:"):
            info["sha1"] = line.split(":", 1)[1].strip()
        elif line.startswith("Data SHA1:"):
            info["data_sha1"] = line.split(":", 1)[1].strip()
        elif line.startswith("Logical size:"):
            info["logical_size"] = int(line.split(":")[1].strip().replace(",", "").split()[0])
        elif line.startswith("Unit Size:"):
            info["unit_size"] = int(line.split(":")[1].strip().split()[0])
        elif line.startswith("File Version:"):
            info["version"] = int(line.split(":")[1].strip().split()[0])
    if "CYLS:" in out:
        # metadata line: CYLS:1463,HEADS:13,SECS:47,BPS:512.
        tail = out.split("CYLS:", 1)[1]
        for part in tail.split(","):
            k, _, v = part.partition(":")
            try:
                info[k.lower()] = int(v)
            except ValueError:
                pass
    return info


def extract_raw(chd_path: str | Path, raw_path: str | Path | None = None) -> Path:
    """Extract the raw hard-disk image (chdman extractraw); cached on disk."""
    chd_path = Path(chd_path)
    raw_path = Path(raw_path) if raw_path else chd_path.with_suffix(".raw")
    if not raw_path.exists():
        subprocess.run(
            ["chdman", "extractraw", "-i", str(chd_path), "-o", str(raw_path)],
            check=True,
            capture_output=True,
        )
    return raw_path


def disk_regions(raw_path: str | Path, min_run: int = 2) -> list[dict]:
    """Map contiguous non-zero sectors of the raw image into runs.

    The KI2 disk is addressed by CHS without a filesystem; the run map shows
    the data blocks (tables and per-character regions) and the padding that a
    writer must respect.
    """
    raw_path = Path(raw_path)
    sector = 512
    zero = bytes(sector)
    runs, start, n = [], None, 0
    with open(raw_path, "rb") as f:
        i = 0
        while True:
            buf = f.read(sector)
            if not buf:
                break
            nz = buf != zero
            if nz and start is None:
                start = i
            elif not nz and start is not None:
                if i - start >= min_run:
                    runs.append({"sectors": [start, i - 1], "bytes": [start * sector, i * sector - 1]})
                start = None
            i += 1
        if start is not None and i - start >= min_run:
            runs.append({"sectors": [start, i - 1], "bytes": [start * sector, i * sector - 1]})
    return runs


def first_sectors(raw_path: str | Path, count: int = 2) -> list[str]:
    """Hexdump of the first `count` sectors: sector 0/1 carry the disk header."""
    with open(raw_path, "rb") as f:
        data = f.read(512 * count)
    return [data[s * 512 : (s + 1) * 512].hex() for s in range(count)]


def inventory(src_zip: str | Path, chd: str | Path, out: str | Path | None = None,
              raw: str | Path | None = None) -> dict:
    """Full inventory: zip audit + CHD identity + raw extraction + run map."""
    audit = audit_zip(src_zip)
    info = chd_identity(chd)
    raw_path = extract_raw(chd, raw)
    manifest = {
        "game_id": "2e9b5e24e3b5d0bc",
        "title": "Killer Instinct 2",
        "platform": PLATFORM,
        "roster": ROSTER,
        "source": {
            "zip": audit.path,
            "zip_sha256": audit.sha256,
            "chd": str(chd),
            "chd_sha1": info.get("sha1"),
            "chd_data_sha1": info.get("data_sha1"),
            "chd_matches_mame": info.get("sha1") == MAME_CHD_SHA1,
            "raw": str(raw_path),
        },
        "zip_audit": {
            "complete_parent_set": audit.complete,
            "missing": audit.missing,
            "unknown": audit.unknown,
            "wrong_sha1": audit.wrong_sha1,
            "boot_roms": audit.bios,
        },
        "disk": {
            "geometry": {k: info.get(k) for k in ("cyls", "heads", "secs", "bps")},
            "logical_size": info.get("logical_size"),
            "sectors": (info.get("logical_size") or 0) // (info.get("bps") or 512),
            "sector0_hex": first_sectors(raw_path, 1)[0][:128],
            "nonzero_runs": disk_regions(raw_path),
        },
        "launch": {
            "requires_chd": True,
            "chd_location": "collections/Mame/roms/kinst2/kinst2.chd (sibling of the zip)",
            "core": "mame2016",
            "default_bios": "ki2-l14.u98 (v1.4)",
            "anyide_bios": "ki2_l14p.u98 (needed for non-Seagate ST9420AG media)",
            "note": "Catalog entry tracks only the zip; the CHD is a separate owned file "
                    "and must be staged alongside it (rompath/kinst2/kinst2.chd).",
        },
    }
    if out:
        Path(out).write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("src_zip")
    ap.add_argument("--chd", required=True)
    ap.add_argument("--out")
    ap.add_argument("--raw")
    args = ap.parse_args()
    inventory(args.src_zip, args.chd, args.out, args.raw)
    print(f"manifest written to {args.out}" if args.out else "done")


if __name__ == "__main__":
    main()
