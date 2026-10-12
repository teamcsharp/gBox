"""Killer Instinct (1994 arcade, Rare / Midway "Killer Instinct hardware") inventory.

The catalog files this title under Final Burn Alpha (``arcade_fbneo``), but
FinalBurn Neo has no ``kinst`` driver.  The game runs only on MAME's
``src/mame/rare/kinst.cpp`` (MIPS R4600 little-endian, ADSP-2105 DCS sound, IDE
hard disk).  The owned build is three files:

* ``collections/Final Burn Alpha/roms/kinst.zip``: the catalog source. It is a
  9-file MAME-format set: the default BIOS ki-l15d.u98 plus the 8 DCS sound ROMs.
* ``collections/Mame/roms/kinst.zip``: the full 13-file MAME parent set, with
  all five boot ROM revisions.
* ``collections/Mame/roms/kinst/kinst.chd``: the v5 CHD hard disk that holds the
  game code and every sprite.  Its sha256 is the stage source identity.

The disk has no filesystem.  Sector 0 is a 32-column ASCII banner, and the boot
ROM reads everything else by sector through the ATA registers at 0x10000100
(uncached 0xb0000100).  This module audits the ROM sets against MAME, checks
which emulator cores carry the driver, extracts the raw disk with chdman, and
profiles its layout so that the analysis stage can locate the sprite banks.

Usage::

    python -m gbox.kinst_inventory --fba-zip A --mame-zip B --chd C \
        --core fbneo=PATH --core mame=PATH --out manifest.json
"""

from __future__ import annotations

import collections
import hashlib
import io
import json
import math
import re
import struct
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

GAME_ID = "6d3a16492c9b09ee"
TITLE = "Killer Instinct"
MAME_SET = "kinst"

# MAME reference identities, copied from src/mame/rare/kinst.cpp ROM_START(kinst).
MAME_CHD_SHA1 = "81d833236e994528d1482979261401b198d1ca53"
DEFAULT_BIOS = "ki-l15d.u98"
BOOT_ROM_SHA1 = {
    "ki-l15d.u98": "607394d4ba1713f38c2cb5159303cace9cde991e",  # v1.5d (default BIOS)
    "ki-l14.u98": "07254f20707377f7195e64675eb6458e663c1a9a",  # v1.4
    "ki-l13.u98": "7f21620a512549db6821a0b4fa53681a767b7974",  # v1.3
    "ki-p47.u98": "501e69b3026394f69229a6e9866c1037502b86bb",  # proto v4.7
    "ki_l15di.u98": "f5f12311aae922d12f98d72ac8fdd77b7b084af2",  # v1.5d AnyIDE (unofficial)
}
SOUND_ROM_SHA1 = {
    "u10-l1": "810d455df8f385d76143e9d7d048f2b555ff8bf0",
    "u11-l1": "0595909cb667c38ac7c8c7bd0646b28899e27777",
    "u12-l1": "7a8ee405c118fd176b66353fa7bfab888cc63cd2",
    "u13-l1": "ea4d1f153eb284f1bcfc5295fbce316bba6083f4",
    "u33-l1": "b22e365bc8d58a80eaac226be14b4bb8d9a04844",
    "u34-l1": "ee439f5162a2b3379d3f802328017bb3c68547d2",
    "u35-l1": "48c4c954ac9db648f28ad64f9845e19ec432eec3",
    "u36-l1": "cc78070cc41701e9a91fde5cfbdc7e1e83354854",
}
MAME_ROMS = {**BOOT_ROM_SHA1, **SOUND_ROM_SHA1}
REQUIRED_FOR_DEFAULT_BIOS = (DEFAULT_BIOS, *SOUND_ROM_SHA1)

BOOT_ROM_BASE = 0xBFC00000  # MAME maps user1 at 0x1fc00000 (KSEG1 0xbfc00000)
IDE_KSEG1_HI = 0xB000  # lui rX, 0xb000 forms the ATA base 0xb0000100

PLATFORM = {
    "catalog_label": "arcade_fbneo",
    "actual": "arcade_mame",
    "machine": "Killer Instinct hardware (Midway PCB 'KILLER INSTINCT V4.0' 5770-14397-03)",
    "cpu": "MIPS R4600, little-endian",
    "sound": "Midway DCS, ADSP-2105, 8 x 512 KiB sound ROMs",
    "storage": "IDE hard disk (MAME DISK_IMAGE 'kinst'), no filesystem",
    "video": "16-bit framebuffer in main RAM at 0x30000 (0x58000 when vram_control "
             "selects the other page), 640-byte rows; 2D pre-rendered sprites",
    "mame_driver": "src/mame/rare/kinst.cpp GAME(1994, kinst, ..., init_kinst)",
    "year": 1994,
}

# Playable fighters plus the boss.  The names are NOT stored as plain ASCII on the
# disk or in the boot ROM (``ascii_hits`` returns 0 for all of them), so native
# IDs and select-screen order are left to the analysis stage.
ROSTER = [
    "B. Orchid", "Chief Thunder", "Cinder", "Fulgore", "Glacius",
    "Jago", "Riptor", "Sabrewulf", "Spinal", "T.J. Combo",
]
BOSS = "Eyedol"
ROSTER_SEARCH = ["JAGO", "SABREWULF", "GLACIUS", "THUNDER", "ORCHID", "SPINAL",
                 "FULGORE", "COMBO", "CINDER", "RIPTOR", "EYEDOL"]

SECTOR = 512


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


@dataclass
class ZipAudit:
    path: str
    size: int
    sha256: str
    members: dict[str, str]
    missing: list[str]
    unknown: list[str]
    wrong_sha1: list[str]
    boots_default: bool
    complete_parent_set: bool


def audit_zip(path: str | Path, ref: dict[str, str] | None = None,
              required: tuple[str, ...] | None = None) -> ZipAudit:
    """Hash a ROM zip and check every member's SHA1 against the MAME set.

    ``boots_default`` is true when the default BIOS and every sound ROM match,
    which is all MAME needs (with the CHD) to run ``kinst``.
    ``complete_parent_set`` is true only when all 13 files are present and match.
    """
    ref = MAME_ROMS if ref is None else ref
    required = REQUIRED_FOR_DEFAULT_BIOS if required is None else tuple(required)
    data = Path(path).read_bytes()
    members: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if not info.is_dir():
                members[info.filename] = hashlib.sha1(zf.read(info)).hexdigest()
    missing = sorted(set(ref) - set(members))
    unknown = sorted(set(members) - set(ref))
    wrong = sorted(n for n, h in members.items() if n in ref and h != ref[n])
    good = {n for n, h in members.items() if ref.get(n) == h}
    return ZipAudit(
        path=str(path), size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        members=members, missing=missing, unknown=unknown, wrong_sha1=wrong,
        boots_default=all(n in good for n in required),
        complete_parent_set=not missing and not wrong,
    )


_CHD_INT_KEYS = {"logical size", "chd size", "hunk size", "total hunks", "unit size",
                 "total units", "file version"}


def parse_chdman_info(text: str) -> dict:
    """Parse ``chdman info`` output into the CHD identity and CHS geometry."""
    info: dict = {}
    for line in text.splitlines():
        key, sep, val = line.strip().partition(":")
        if not sep:
            continue
        k, val = key.strip().lower(), val.strip()
        if k == "sha1":
            info["sha1"] = val
        elif k == "data sha1":
            info["data_sha1"] = val
        elif k in _CHD_INT_KEYS and val:
            info[k.replace(" ", "_")] = int(val.split()[0].replace(",", ""))
    m = re.search(r"CYLS:(\d+),HEADS:(\d+),SECS:(\d+),BPS:(\d+)", text)
    if m:
        info.update(zip(("cyls", "heads", "secs", "bps"), map(int, m.groups())))
    return info


def chd_identity(chd: str | Path) -> dict:
    out = subprocess.run(["chdman", "info", "-i", str(chd)], capture_output=True,
                         text=True, check=True).stdout
    return parse_chdman_info(out)


def extract_raw(chd: str | Path, raw: str | Path) -> Path:
    """Extract the raw disk once (``chdman extractraw``); the CHD is never modified."""
    raw = Path(raw)
    if not raw.exists():
        part = raw.with_name(raw.name + ".part")
        part.unlink(missing_ok=True)
        subprocess.run(["chdman", "extractraw", "-i", str(chd), "-o", str(part)],
                       check=True, capture_output=True)
        part.rename(raw)
    return raw


def banner(sector0: bytes) -> list[str]:
    """Sector 0 is newline-separated, space-padded 32-column text lines."""
    text = sector0.split(b"\0", 1)[0].decode("latin-1")
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def disk_runs(raw: str | Path, sector: int = SECTOR) -> list[tuple[int, int]]:
    """Inclusive (first, last) sector ranges of non-zero sectors."""
    zero = bytes(sector)
    runs: list[tuple[int, int]] = []
    start = None
    i = 0
    with open(raw, "rb") as f:
        for blk in iter(lambda: f.read(sector * 2048), b""):
            for off in range(0, len(blk), sector):
                nz = blk[off:off + sector] != zero[: len(blk) - off]
                if nz and start is None:
                    start = i
                elif not nz and start is not None:
                    runs.append((start, i - 1))
                    start = None
                i += 1
    if start is not None:
        runs.append((start, i - 1))
    return runs


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(data).values())


def entropy_profile(raw: str | Path, block: int = 1 << 20) -> list[dict]:
    rows = []
    with open(raw, "rb") as f:
        for i, blk in enumerate(iter(lambda: f.read(block), b"")):
            rows.append({"block": i, "entropy": round(entropy(blk), 3),
                         "zero_frac": round(blk.count(0) / len(blk), 4)})
    return rows


def classify_regions(profile: list[dict], block: int = 1 << 20, high: float = 7.9) -> list[dict]:
    """Merge consecutive blocks into empty / structured / high_entropy regions.

    High-entropy blocks (>= 7.9 bits/byte) are compressed or packed data; a
    writer must decode them before it can change their contents.
    """
    regions: list[dict] = []
    for row in profile:
        if row["zero_frac"] >= 0.999:
            kind = "empty"
        elif row["entropy"] >= high:
            kind = "high_entropy"
        else:
            kind = "structured"
        if regions and regions[-1]["kind"] == kind:
            regions[-1]["end"] = (row["block"] + 1) * block
            regions[-1]["blocks"] += 1
        else:
            regions.append({"kind": kind, "start": row["block"] * block,
                            "end": (row["block"] + 1) * block, "blocks": 1})
    return regions


def decode_jump(word: int, pc: int) -> int | None:
    """Target of a MIPS ``j`` (opcode 2) at ``pc``, or None for other opcodes."""
    if word >> 26 != 2:
        return None
    return ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)


def lui_sites(rom: bytes, imm: int = IDE_KSEG1_HI, base: int = BOOT_ROM_BASE) -> list[dict]:
    """Every ``lui rt, imm`` in the ROM (the boot code's ATA register base loads)."""
    sites = []
    for off in range(0, len(rom) - 3, 4):
        w = struct.unpack_from("<I", rom, off)[0]
        if (w & 0xFFE0FFFF) == (0x3C000000 | imm):
            sites.append({"addr": hex(base + off), "rt": (w >> 16) & 31})
    return sites


def boot_rom_profile(rom: bytes, base: int = BOOT_ROM_BASE) -> dict:
    w0 = struct.unpack_from("<I", rom, 0)[0]
    target = decode_jump(w0, base)
    used = [o for o in range(0, len(rom), 4) if rom[o:o + 4] not in (b"\0" * 4, b"\xff" * 4)]
    end = used[-1] + 4 if used else 0
    return {
        "size": len(rom),
        "sha1": hashlib.sha1(rom).hexdigest(),
        "reset_word": hex(w0),
        "reset_jump": hex(target) if target is not None else None,
        "ide_lui_sites": lui_sites(rom, IDE_KSEG1_HI, base),
        "used_bytes": end,
        "entropy": round(entropy(rom[:end]), 3),
    }


def word_hits(data: bytes, name: bytes) -> int:
    return len(re.findall(rb"(?<![A-Za-z0-9_])" + re.escape(name) + rb"(?![A-Za-z0-9_])", data))


def core_has_driver(core: str | Path, short_name: str = MAME_SET) -> bool:
    """True when an emulator core binary contains the set's short name as a word.

    MAME/FBNeo cores store each driver's short name as a NUL-terminated string,
    so an absent word means the core cannot run the set.
    """
    return word_hits(Path(core).read_bytes(), short_name.encode()) > 0


def ascii_hits(data: bytes, names: list[str]) -> dict[str, int]:
    """Case-sensitive raw ASCII hit counts for each name, upper and title case."""
    out = {}
    for n in names:
        for v in (n, n.title()):
            out[v] = data.count(v.encode())
    return out


def inventory(fba_zip: str | Path, mame_zip: str | Path, chd: str | Path,
              cores: dict[str, str] | None = None, raw: str | Path | None = None,
              out: str | Path | None = None) -> dict:
    """Full inventory: ROM audits, core support, CHD identity, raw disk layout."""
    fba = audit_zip(fba_zip)
    mame = audit_zip(mame_zip)
    info = chd_identity(chd)
    raw_path = extract_raw(chd, raw or Path(chd).with_suffix(".raw"))
    disk = raw_path.read_bytes()
    with zipfile.ZipFile(fba_zip) as zf:
        rom = zf.read(DEFAULT_BIOS)
    runs = disk_runs(raw_path)
    profile = entropy_profile(raw_path)
    core_support = {name: core_has_driver(path) for name, path in (cores or {}).items()}
    chd_sha256 = sha256_file(chd)
    manifest = {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "source_sha256": chd_sha256,
        "roster": {"playable": ROSTER, "boss": BOSS,
                   "source": "select screen; native IDs and order are analysis-stage work",
                   "ascii_hits_disk": ascii_hits(disk, ROSTER_SEARCH),
                   "ascii_hits_boot_rom": ascii_hits(rom, ROSTER_SEARCH)},
        "source": {
            "catalog_zip": asdict(fba),
            "mame_zip": asdict(mame),
            "chd": {"path": str(chd), "sha256": chd_sha256, **info,
                    "matches_mame": info.get("sha1") == MAME_CHD_SHA1},
            "raw": {"path": str(raw_path), "size": len(disk),
                    "sha256": hashlib.sha256(disk).hexdigest()},
        },
        "cores": core_support,
        "boot_rom": {"name": DEFAULT_BIOS, **boot_rom_profile(rom)},
        "disk": {
            "geometry": {k: info.get(k) for k in ("cyls", "heads", "secs", "bps")},
            "sectors": len(disk) // SECTOR,
            "banner": banner(disk[:SECTOR]),
            "nonzero_runs": len(runs),
            "runs": runs,
            "last_nonzero_sector": runs[-1][1] if runs else None,
            "regions": classify_regions(profile),
            "entropy_profile": profile,
        },
        "launch": {
            "emulator": "MAME (mame_libretro) driver kinst; FinalBurn Neo cannot run it",
            "rompath": ["kinst.zip (either owned zip; default BIOS v1.5d)",
                        "kinst/kinst.chd (only in collections/Mame/roms/kinst/)"],
            "requires_chd": True,
            "default_bios": "v1.5d (ki-l15d.u98); v1.5d-anyide = ki_l15di.u98 for non-stock drives",
            "note": "The catalog tracks only the FBA zip; staging must add the MAME CHD.",
        },
    }
    if out:
        Path(out).write_text(json.dumps(manifest, indent=1))
    return manifest


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--fba-zip", required=True)
    ap.add_argument("--mame-zip", required=True)
    ap.add_argument("--chd", required=True)
    ap.add_argument("--raw")
    ap.add_argument("--core", action="append", default=[], help="name=path to a core binary")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    cores = dict(c.split("=", 1) for c in args.core)
    m = inventory(args.fba_zip, args.mame_zip, args.chd, cores, args.raw, args.out)
    print(json.dumps({"source_sha256": m["source_sha256"], "cores": m["cores"],
                      "chd_matches_mame": m["source"]["chd"]["matches_mame"],
                      "banner": m["disk"]["banner"]}, indent=1))


if __name__ == "__main__":
    main()
