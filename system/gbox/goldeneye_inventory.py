"""Inventory the owned 007 - GoldenEye (Europe) N64 build.

GoldenEye stores its executable and all assets in one ROM image.  The
analysis stage (gbox.goldeneye_files) found the central file table inside
the rarezip-compressed data segment (ROM 0x1F850, VRAM 0x8001EC50; 771
entries at 0x8003EAC4), so asset offsets come from that table rather than
from hard-coded constants; they still differ between regional builds.  This
module therefore focuses on identifying the exact owned build, verifying
its integrity, recording the header/boot-code layout, and producing a
high-level region map that the analysis stage can use to pin the real
offsets for this GEP cartridge.

Usage: python -m gbox.goldeneye_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from gbox import n64_rom

BOOT_OFF = 0x1000
BOOT_SIZE = 0x100000  # IPL3 boot code lives in [0x1000, 0x101000)

# Known retail GoldenEye 007 cartridge IDs / region bytes.
# Verified from the ROM header: cart ID at 0x3C-0x3D, region at 0x3E.
VALID_CART_IDS = {b"GE"}
VALID_REGIONS = {
    0x45,  # E (USA)
    0x50,  # P (Europe)
    0x4A,  # J (Japan)
}

# Accepted retail ROM sizes.  GoldenEye shipped as a 96 Mbit (12 MiB) cart.
VALID_SIZES = {12 * 1024 * 1024, 16 * 1024 * 1024}

# From community documentation (GoldenEye Setup Editor / n64decomp).  These
# are USA/PAL/JPN-specific guesses and must be validated in the analysis
# stage; they are recorded here only as candidate landmarks.
CANDIDATE_LANDMARKS = {
    "model_block_usa": 0x10CBC0,
    "setup_table_usa": 0x24D9C0,
    "texture_table_usa": 0x2E93C0,
    "animation_table_usa": 0x42B0C0,
}


@dataclass
class Region:
    start: int
    end: int
    entropy: float
    zero_ratio: float
    label: str = ""


def crc6102(rom: bytes) -> tuple[int, int]:
    """CIC-NUS-6102 boot-code checksum over 0x1000..0x101000."""
    mask = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = 0xF8CA4DDC
    words = struct.unpack_from(">262144I", rom, BOOT_OFF)
    for d in words:
        t = (t6 + d) & mask
        if t < t6:
            t4 = (t4 + 1) & mask
        t6 = t
        t3 ^= d
        s = d & 0x1F
        r = ((d << s) | (d >> (32 - s))) & mask if s else d
        t5 = (t5 + r) & mask
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        t1 = (t1 + (t5 ^ d)) & mask
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def region_map(rom: bytes, window: int = 64 * 1024) -> list[Region]:
    """Return 64 KB (default) entropy/zero regions for the whole ROM."""
    regions: list[Region] = []
    for start in range(0, len(rom), window):
        chunk = rom[start : start + window]
        if not chunk:
            break
        zero_ratio = chunk.count(0) / len(chunk)
        # Rough labelling by entropy and zero ratio.
        if start < 0x1000:
            label = "header"
        elif start < BOOT_OFF + BOOT_SIZE:
            label = "boot_code"
        elif 6.8 <= _entropy(chunk) <= 8.1 and zero_ratio < 0.12:
            label = "packed_or_code"
        elif 5.0 <= _entropy(chunk) < 6.8 and zero_ratio < 0.45:
            label = "code_and_data"
        elif zero_ratio >= 0.45:
            label = "sparse_or_padding"
        else:
            label = "data"
        regions.append(Region(start, start + len(chunk), _entropy(chunk), zero_ratio, label))
    return regions


def validate(rom: bytes) -> dict:
    """Sanity-check the ROM header and boot checksum."""
    if rom[:4] != b"\x80\x37\x12\x40":
        raise ValueError("not a big-endian .z64 ROM")
    if len(rom) not in VALID_SIZES:
        raise ValueError(f"unexpected ROM size {len(rom)}; expected one of {VALID_SIZES}")

    hdr = rom[:0x40]
    title = hdr[0x20:0x34].split(b"\x00")[0].decode("ascii", "replace").strip()
    cart_id = hdr[0x3C:0x3E]
    region = hdr[0x3E]
    version = hdr[0x3F]
    if cart_id not in VALID_CART_IDS:
        raise ValueError(f"cart id {cart_id!r} is not a recognised GoldenEye ID")
    if region not in VALID_REGIONS:
        raise ValueError(f"region byte 0x{region:02X} is not a recognised GoldenEye region")
    if title != "GOLDENEYE":
        # Tolerate only the exact internal name; a mismatch means the ROM is
        # byteswapped or patched.
        raise ValueError(f"internal title {title!r} != GOLDENEYE")

    stored_crc1 = struct.unpack_from(">I", hdr, 0x10)[0]
    stored_crc2 = struct.unpack_from(">I", hdr, 0x14)[0]
    c1, c2 = crc6102(rom)
    if c1 != stored_crc1 or c2 != stored_crc2:
        raise ValueError(
            f"CIC-6102 checksum mismatch: computed {c1:08X}/{c2:08X}, "
            f"stored {stored_crc1:08X}/{stored_crc2:08X}"
        )

    return {
        "title": title,
        "cart_id": cart_id.decode("ascii"),
        "region_byte": region,
        "region": {"E": "USA", "P": "Europe", "J": "Japan"}.get(chr(region), "unknown"),
        "version_byte": version,
        "clock_rate": struct.unpack_from(">I", hdr, 0)[0],
        "entry_pc": f"0x{struct.unpack_from('>I', hdr, 8)[0]:08X}",
        "crc1": f"0x{c1:08X}",
        "crc2": f"0x{c2:08X}",
        "boot_checksum_ok": True,
    }


def inventory(rom: bytes) -> dict:
    header = validate(rom)
    rom_sha256 = hashlib.sha256(rom).hexdigest()
    rom_sha1 = hashlib.sha1(rom).hexdigest()
    rom_md5 = hashlib.md5(rom).hexdigest()

    regions = region_map(rom)
    region_summary: dict[str, list[dict]] = {}
    for r in regions:
        region_summary.setdefault(r.label, []).append(
            {"start": r.start, "end": r.end, "entropy": round(r.entropy, 3), "zero_ratio": round(r.zero_ratio, 3)}
        )

    # Count F3D display-list markers in the post-boot region as a coarse
    # indicator of 3D geometry density (not a precise asset boundary).
    f3d_markers = (0x01, 0x03, 0x05, 0x06, 0x07, 0xB8)
    geometry_markers = sum(rom[o] in f3d_markers for o in range(BOOT_OFF + BOOT_SIZE, len(rom)))

    # Boot code as a separate artifact.
    boot = rom[BOOT_OFF : BOOT_OFF + BOOT_SIZE]

    # Candidate asset landmarks for the analysis stage to verify.
    landmarks = {
        name: {"rom_offset": off, "status": "candidate", "verified": False}
        for name, off in CANDIDATE_LANDMARKS.items()
    }

    manifest = {
        "game": "007 - GoldenEye",
        "platform": "n64",
        "library": "hyperspin",
        "format": "zip -> .z64 (extracted member)",
        "rom_size": len(rom),
        "rom_sha256": rom_sha256,
        "rom_sha1": rom_sha1,
        "rom_md5": rom_md5,
        "header": header,
        "boot_code": {
            "rom_offset": BOOT_OFF,
            "size": BOOT_SIZE,
            "sha256": hashlib.sha256(boot).hexdigest(),
        },
        "region_map": region_summary,
        "coarse_geometry_markers": geometry_markers,
        "asset_landmarks": landmarks,
        "container_layout": {
            "kind": "flat_n64_rom",
            "filesystem": None,
            "note": "Assets are not stored in a file table; offsets are hard-coded in the executable and vary by region. "
                    "This inventory preserves the original zip and the normalized .z64; it does not modify the source ROM.",
        },
        "launch_prerequisites": {
            "core": "parallel_n64",
            "runtime": "retroarch/parallel_n64 (auto-install per catalog)",
            "windows_alternative": "rocketlauncher (windows-node)",
            "rom_format": "big-endian .z64, CIC-6102 checksum must match",
            "audio": "agent Windows tests use 2% audio",
        },
        "character_inventory": {
            "status": "catalogued_from_source_knowledge",
            "note": "Playable/AI characters (Bond, Natalya, Trevelyan, guards, soldiers, scientists, etc.) are stored as model/skeleton/animation triples "
                    "inside the model block and stage setups. Their exact IDs and offsets must be pinned in the analysis stage.",
            "known_cast_groups": [
                "bond",
                "allies",
                "guards",
                "soldiers",
                "scientists",
                "civilians",
                "bosses",
            ],
            "verified": False,
        },
        "texture_animation_inventory": {
            "status": "catalogued_from_source_knowledge",
            "note": "Textures use N64 RGBA16/CI8/I8/etc. formats referenced by display lists. Animations are key-framed against the character skeletons. "
                    "No verified offsets for this GEP build yet.",
            "verified": False,
        },
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out: Path | None = None
    if "--out" in argv:
        i = argv.index("--out")
        out = Path(argv[i + 1])
        del argv[i : i + 2]
    if len(argv) != 1:
        print("usage: python -m gbox.goldeneye_inventory SRC [--out manifest.json]", file=sys.stderr)
        return 2
    src = Path(argv[0])
    rom = n64_rom.read(src)
    data = inventory(rom)
    if src.is_file():
        st = src.stat()
        data["source_file"] = {
            "path": str(src.resolve()),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2))
        print(f"wrote {out}")
    print(
        f"GoldenEye {data['header']['region']} sha256={data['rom_sha256']} "
        f"boot_ok={data['header']['boot_checksum_ok']} "
        f"regions={list(data['region_map'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
