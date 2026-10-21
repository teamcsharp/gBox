"""NFL 2K2 (USA) Dreamcast inventory.

Owned source: hyperspin CHD ``collections/Sega Dreamcast/roms/NFL 2K2 (USA).chd``
(game 373a463aa1f96e35). This module unpacks it once with chdman, walks the
ISO9660 volume of the multi-session GD-ROM, classifies the Visual Concepts
2K-series containers and writes an inventory manifest.

Usage:  python -m gbox.nfl2k2_inventory [--chd PATH] [--out m.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path
from .side_dirs import side_dir

GAME_ID = "373a463aa1f96e35"
TITLE = "NFL 2K2 (USA)"
CHD_REL = "collections/Sega Dreamcast/roms/NFL 2K2 (USA).chd"
CACHE_DIR = side_dir("gbox-cache") / "dc" / GAME_ID

# IFF type tags observed on this disc (4 ASCII chars at offset 0).
IFF_TYPES = {
    "SCNE": "scene / 3D mesh container (VC serialized; 'DOUBLE'/'SINGLE' type tables)",
    "SPRT": "sprite / texture bank (VC VQ textures, not standard PVR)",
    "VQCB": "vector-quantization colour book",
    "SOUN": "sound bank (VCSD chunks inside)",
    "TXTR": "text strings",
    "ROST": "roster data",
    "SMLT": "stream playlist",
}

GD_DIR_NAMELESS = (1, 2, 3)  # .DIR versions whose records carry no name block


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unpack_disc(chd: Path, dest: Path = CACHE_DIR) -> Path:
    """Extract the GD-ROM once with chdman; returns the disc.gdi path."""
    dest.mkdir(parents=True, exist_ok=True)
    gdi = dest / "disc.gdi"
    if gdi.exists():
        return gdi
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    subprocess.run(["chdman", "extractcd", "-f", "-i", str(chd), "-o", str(tmp / "disc.gdi")],
                   check=True, capture_output=True, timeout=1800)
    for p in tmp.iterdir():
        shutil.move(str(p), dest / p.name)
    tmp.rmdir()
    return gdi


def ip_bin_info(data: bytes) -> dict:
    """Parse the 32 KB IP.BIN bootstrap. This disc uses a Visual Concepts
    variant: the 16-byte hardware field is absent, so every standard field
    sits 16 bytes earlier ('SEGA ENTERPRISES' at 0x00 instead of 0x10)."""

    def field(off: int, ln: int) -> str:
        return data[off:off + ln].decode("latin-1").split("\x00", 1)[0].strip()

    shift = -16 if data[:16].startswith(b"SEGA ENTERPRISES") else 0
    at = lambda off: off + shift  # noqa: E731
    out = {
        "hardware_id": field(0x00, 16) if not shift else
                       next((m.group(0).decode() for m in re.finditer(rb"SEGA SEGAKATANA", data)), None),
        "maker_id": field(at(0x10), 16),
        "device_info": field(at(0x20), 16),
        "area_symbols": field(at(0x30), 8).replace(" ", ""),
        "peripherals": field(at(0x38), 8),
        "product_number": field(at(0x40), 10),
        "product_version": field(at(0x4A), 6),
        "release_date": field(at(0x50), 8),
        "boot_file": field(at(0x60), 16).split()[0] if field(at(0x60), 16) else "",
        "title": field(at(0x80), 64).split()[0] if field(at(0x80), 64) else "",
        "layout": "vc-shifted" if shift else "standard",
    }
    return out


def iff_kind(data: bytes) -> str | None:
    tag = data[:4]
    if tag.isascii() and tag.decode("latin-1", "replace") in IFF_TYPES:
        return tag.decode("latin-1")
    return None


def iff_header(data: bytes) -> dict | None:
    kind = iff_kind(data)
    if not kind:
        return None
    fields = struct.unpack_from("<3I", data, 4) if len(data) >= 16 else (0, 0, 0)
    return {"kind": kind, "desc": IFF_TYPES[kind], "h0": fields[0], "h1": fields[1], "h2": fields[2]}


def gd_dir(data: bytes) -> dict:
    """Decode a gBox/gdFs .DIR table: {u32 version, u32 count, 12-byte records, names}.

    Record = {off, x, size}; name block (NUL-terminated strings) only for v0.
    """
    version, count = struct.unpack_from("<2I", data, 0)
    records = []
    for i in range(count):
        off, x, size = struct.unpack_from("<3I", data, 8 + 12 * i)
        records.append({"off": off, "x": x, "size": size})
    names: list[str] = []
    if version not in GD_DIR_NAMELESS:
        tail = data[8 + 12 * count:]
        names = [s.decode("latin-1") for s in re.split(rb"\x00+", tail) if s]
    return {"version": version, "count": count, "records": records, "names": names}


class Disc:
    """Reads the unpacked GD-ROM through gbox.gdrom.GDRom, with a fast path
    for large files (single contiguous read per track, no per-sector seeks)."""

    def __init__(self, gdi: Path):
        from gbox.gdrom import GDRom  # local import: reusable engine-family reader
        self.g = GDRom(gdi)
        self.gdi = gdi

    def read(self, name: str) -> bytes:
        lba, size = self.g.files[name]
        return self._read_range(lba, size)

    def _read_range(self, lba: int, size: int) -> bytes:
        """Bulk-read `size` bytes starting at `lba`. Raw 2352-byte tracks hold
        2048 data bytes per sector with a 16-byte header, so the read strides
        per sector and skips headers (GDRom.sector does the same, one seek each)."""
        tracks = sorted(self.g.tracks)
        starts = [t[0] for t in tracks]
        out = bytearray()
        cur = lba
        remaining = size
        while remaining > 0:
            i = len(tracks) - 1
            while i > 0 and cur < tracks[i][0]:
                i -= 1
            start, sector_size, path = tracks[i]
            n = (remaining + 2047) // 2048
            if i + 1 < len(starts):
                n = min(n, starts[i + 1] - cur)
            skip = 16 if sector_size == 2352 else 0
            f = self.g._fh.get(path) or self.g._fh.setdefault(path, open(path, "rb"))
            f.seek((cur - start) * sector_size + skip)
            blob = f.read(n * sector_size)
            for k in range(n):
                out += blob[k * sector_size:k * sector_size + 2048]
            cur += n
            remaining -= n * 2048
        return bytes(out[:size])


    def ip_bin(self) -> bytes:
        """IP.BIN is the 32 KB bootstrap area (sectors 0-15 of the first
        high-density data track), not an ISO9660 file."""
        hd = min((t for t in self.g.tracks if t[0] >= 45000), default=min(self.g.tracks))
        return self._read_range(hd[0], 32768)


def classify_file(name: str, data: bytes) -> dict:
    kind = iff_kind(data)
    if kind:
        return {"role": "iff", "iff": iff_header(data)}
    if name.endswith(".DIR"):
        return {"role": "gdfs_dir", "dir": gd_dir(data)}
    if name.endswith(".DAT"):
        return {"role": "gdfs_blob"}
    if name in ("1ST_READ.BIN", "MAIN.BIN"):
        return {"role": "sh4_binary"}
    return {"role": "other"}


def inventory(gdi: Path, chd: Path | None = None, chd_sha256: str | None = None,
              full_hashes: bool = False) -> dict:
    disc = Disc(gdi)
    names = sorted(disc.g.files)
    files = []
    groups: dict[str, dict] = {}
    ip = ip_bin_info(disc.ip_bin())

    def note(group: str, name: str, lba: int, size: int, cls: dict):
        files.append({"name": name, "lba": lba, "size": size, **cls})
        g = groups.setdefault(group, {"count": 0, "bytes": 0})
        g["count"] += 1
        g["bytes"] += size

    for name in names:
        lba, size = disc.g.files[name]
        small = size <= 4_000_000
        data = disc.read(name) if small else b""
        cls = classify_file(name, data)
        if name.startswith("S") and name.endswith(".IFF") and not name.startswith(("SL", "STREAM", "SUPER")):
            note("stadiums", name, lba, size, cls)
        elif name.startswith(("HS", "AS")):
            note("sounds", name, lba, size, cls)
        elif name[:1] in ("H", "A") and name.endswith(".IFF"):
            note("uniforms", name, lba, size, cls)
        elif name.startswith("C") and name[1:3].isdigit() and name.endswith(".IFF"):
            note("coaches", name, lba, size, cls)
        elif name.startswith("PCG"):
            note("player_geometry", name, lba, size, cls)
        elif name.startswith("QB"):
            note("qb_challenge", name, lba, size, cls)
        elif name.endswith((".DAT", ".DIR")):
            note("gdfs_pair_" + name.split(".")[0], name, lba, size, cls)
        elif name == "1ST_READ.BIN":
            note("executables", name, lba, size, cls)
            files[-1]["sha256"] = hashlib.sha256(disc.read(name)).hexdigest()
        elif name == "MAIN.BIN":
            note("executables", name, lba, size, cls)
            files[-1]["sha256"] = hashlib.sha256(disc.read(name)).hexdigest()
        else:
            note("misc", name, lba, size, cls)

    manifest = {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "dreamcast",
        "source": {
            "library": "hyperspin",
            "rel_path": CHD_REL,
            "format": "chd",
            "size": chd.stat().st_size if chd and chd.exists() else None,
            "sha256": chd_sha256 or (sha256_file(chd) if chd and chd.exists() else None),
        },
        "unpacked": str(gdi),
        "tracks": [{"lba": t[0], "sector_size": t[1], "file": t[2].name} for t in disc.g.tracks],
        "ip_bin": ip,
        "launch": {
            "core": "flycast",
            "runtimes": ["retroarch/flycast (auto-install)", "rocketlauncher (windows-node)"],
            "note": "playable straight from the CHD; the extracted GDI is for asset work",
        },
        "file_count": len(files),
        "groups": {k: v for k, v in groups.items()},
        "files": files,
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{TITLE} Dreamcast inventory")
    ap.add_argument("--chd", type=Path, default=None, help="owned CHD (default: hyperspin mount)")
    ap.add_argument("--out", type=Path, default=None, help="manifest output path")
    ap.add_argument("--sha256", default=None, help="known CHD sha256 (skips hashing)")
    args = ap.parse_args(argv)

    chd = args.chd
    if chd is None:
        for root in (Path("/mnt/gbox/hyperspin/Arcade"), Path("/mnt/gbox/hyperspin")):
            p = root / CHD_REL
            if p.exists():
                chd = p
                break
    if chd is None or not chd.exists():
        raise SystemExit(f"owned CHD not found (looked for {CHD_REL})")
    gdi = unpack_disc(chd)
    m = inventory(gdi, chd=chd, chd_sha256=args.sha256)
    out = args.out or (CACHE_DIR / "manifest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, indent=2))
    print(f"manifest: {out}")
    print(f"source sha256: {m['source']['sha256']}")
    print(f"files: {m['file_count']}")
    for k, v in m["groups"].items():
        print(f"  {k}: {v['count']} files, {v['bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
