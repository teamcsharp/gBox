"""Marvel vs. Capcom 2 (Dreamcast) owned-disc inventory: IP.BIN identity, the main executable, the per-character
file sets and the PLxx_DAT.BIN section table (#1315 inventory stage).

The USA GD-ROM (T-1212N V1.001, 2000-05-29) stores each fighter as a family of files named by its internal ID
0x00-0x3A (59 IDs, 56 playable: Abyss has three forms):

  PLxx_DAT.BIN   sprite/animation package: a u32 section-offset table whose first entry is the table size
                 (0x40 -> 16 slots, 0 = empty slot); section 0 at 0x40 is by far the largest block
  PLxx_FAC.BIN   portraits (a 3-entry offset table)
  PLxx_WIN.BIN   win-screen portrait; absent for 0x18-0x1A, the three Abyss boss forms
  PLxx_VOI.BIN   voice bank ("DTPK")
  S_PLxxA-F.BIN  six 14068-byte SH-4 code modules per ID (they start with function prologues, not image data)

Characters are 2D sprites; the 3D files (STGxxPOL/TEX stages, DMxx attract scenes, EFKY effects) are
backgrounds. `python -m gbox.mvc2_inventory DISC.gdi --source OWNED.7z --out manifest.json` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from collections import defaultdict
from pathlib import Path

from .gdrom import GDRom

# Internal IDs (community ID list). The disc corroborates it: the only IDs without a PLxx_WIN.BIN are 0x18-0x1A.
ROSTER = (
    "Ryu", "Zangief", "Guile", "Morrigan", "Anakaris", "Strider Hiryu", "Cyclops", "Wolverine", "Psylocke",
    "Iceman", "Rogue", "Captain America", "Spider-Man", "Hulk", "Venom", "Doctor Doom", "Tron Bonne",
    "Jill Valentine", "Hayato", "Ruby Heart", "SonSon", "Amingo", "Marrow", "Cable", "Abyss (form 1)",
    "Abyss (form 2)", "Abyss (form 3)", "Chun-Li", "Mega Man", "Roll", "Akuma", "B.B. Hood", "Felicia",
    "Charlie Nash", "Sakura", "Dan", "Cammy", "Dhalsim", "M. Bison", "Ken", "Gambit", "Juggernaut", "Storm",
    "Sabretooth", "Magneto", "Shuma-Gorath", "War Machine", "Silver Samurai", "Omega Red", "Spiral", "Colossus",
    "Iron Man", "Sentinel", "Blackheart", "Thanos", "Jin", "Captain Commando", "Wolverine (Bone Claw)", "Servbot",
)
CHAR_FILES = {"dat": "PL{id}_DAT.BIN", "face": "PL{id}_FAC.BIN", "win": "PL{id}_WIN.BIN", "voice": "PL{id}_VOI.BIN",
              **{f"code_{c}": f"S_PL{{id}}{c}.BIN" for c in "ABCDEF"}}
GROUPS = (  # (pattern, role) for the non-character files, first match wins
    (r"1ST_READ\.BIN$", "main SH-4 executable"), (r"STG..(TEX|POL)\.BIN$", "3D stage textures/polygons"),
    (r"DM..\w+\.BIN$", "attract/demo scene"), (r"EFKY(TEX|POL)\.BIN$", "3D effects"),
    (r"SEL\w+\.BIN$", "character/stage select"), (r"(ADX_\w+|SE_\w+)\.BIN$|\.AFS$|\.MLT$", "audio"),
    (r"^(DP|2_DP|SG_DPLDR|MAIGO)", "Dream Passport network client"), (r"\.PVR$", "PVR textures"),
)
_REGIONS = "JUE"
_REGION_NAMES = {"J": "Japan", "U": "USA", "E": "Europe"}


def ip_header(sector: bytes) -> dict:
    """Decode the IP.BIN meta block (sector 0 of the high-density area)."""
    if sector[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("not a Dreamcast IP.BIN")
    s = lambda a, b: sector[a:b].decode("ascii", "replace").strip()  # noqa: E731
    area = sector[0x30:0x38].decode("ascii", "replace")
    return {"hardware": s(0, 0x10), "maker": s(0x10, 0x20), "device": s(0x20, 0x30),
            "regions": [_REGION_NAMES[c] for i, c in enumerate(area[:3]) if c == _REGIONS[i]],
            "peripherals": s(0x38, 0x40), "product": s(0x40, 0x4A), "version": s(0x4A, 0x50),
            "date": s(0x50, 0x60), "boot": s(0x60, 0x70), "company": s(0x70, 0x80), "title": s(0x80, 0x100)}


def dat_sections(data: bytes) -> list[dict]:
    """PLxx_DAT.BIN section table -> [{slot, offset, size}] for the non-empty slots, each sized up to the next
    higher section offset (or EOF). Raises ValueError when the header isn't a sane offset table."""
    if len(data) < 8:
        raise ValueError("too short for a section table")
    n = struct.unpack_from("<I", data, 0)[0]
    if n % 4 or not 8 <= n <= 0x400 or n > len(data):
        raise ValueError(f"bad table size {n:#x}")
    offs = struct.unpack_from(f"<{n // 4}I", data, 0)
    used = sorted((o, i) for i, o in enumerate(offs) if o)
    if any(o < n or o > len(data) for o, _ in used):
        raise ValueError("section offset outside the file")
    ends = [o for o, _ in used[1:]] + [len(data)]
    return sorted(({"slot": i, "offset": o, "size": e - o} for (o, i), e in zip(used, ends)), key=lambda r: r["slot"])


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def inventory(gdi: str | Path, hash_files: bool = True) -> dict:
    """The disc manifest: identity, executable hash, every character's files (+ DAT sections) and file groups."""
    g = GDRom(gdi)
    hd = min((t for t in g.tracks if t[0] >= 45000), default=max(g.tracks))
    ip = ip_header(g.sector(hd[0]))
    boot = g.read(ip["boot"])
    chars, code_hashes = [], set()
    for cid, name in enumerate(ROSTER):
        hid = f"{cid:02X}"
        row = {"id": cid, "hex": hid, "name": name, "files": {}, "missing": []}
        for kind, pat in CHAR_FILES.items():
            fn = pat.format(id=hid)
            if fn not in g.files:
                row["missing"].append(fn)
                continue
            lba, size = g.files[fn]
            ent = {"name": fn, "lba": lba, "size": size}
            if hash_files or kind == "dat":
                data = g.read(fn)
                ent["sha256"] = _sha(data)
                if kind == "dat":
                    row["dat_sections"] = dat_sections(data)
                if kind.startswith("code_"):
                    code_hashes.add(ent["sha256"])
            row["files"][kind] = ent
        chars.append(row)
    char_names = {e["name"] for c in chars for e in c["files"].values()}
    groups = defaultdict(lambda: {"files": 0, "bytes": 0})
    for fn, (_, size) in g.files.items():
        role = "character" if fn in char_names else next((r for p, r in GROUPS if re.search(p, fn)), "other")
        groups[role]["files"] += 1
        groups[role]["bytes"] += size
    return {"ip": ip, "boot": {"name": ip["boot"], "size": len(boot), "sha256": _sha(boot)},
            "tracks": [{"lba": lba, "sector": ssz, "file": p.name} for lba, ssz, p in g.tracks],
            "file_count": len(g.files), "characters": chars, "groups": dict(groups),
            "code_modules_unique": len(code_hashes) if hash_files else None,
            "platform_check": "dreamcast" if ip["hardware"] == "SEGA SEGAKATANA" else "unknown"}


def unpack_7z(src: Path, dst: Path) -> Path:
    """Unpack an owned GD-ROM .7z once into `dst` (tracks flattened, the set's .gdi copied to disc.gdi, the
    convention `characters._dc_gdi` looks for). The source archive is only read."""
    if (dst / "disc.gdi").exists():
        return dst / "disc.gdi"
    tmp = dst.with_name(dst.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    subprocess.run(["7z", "x", "-y", f"-o{tmp}", str(src)], check=True, capture_output=True)
    for p in [p for p in tmp.rglob("*") if p.is_file() and p.parent != tmp]:
        p.rename(tmp / p.name)
    gdis = sorted(tmp.glob("*.gdi"))
    if not gdis:
        raise ValueError(f"{src.name}: no .gdi in the archive")
    shutil.copyfile(gdis[0], tmp / "disc.gdi")
    for d in sorted((p for p in tmp.rglob("*") if p.is_dir()), reverse=True):
        d.rmdir()
    shutil.rmtree(dst, ignore_errors=True)
    tmp.rename(dst)
    return dst / "disc.gdi"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "MVC2 inventory").splitlines()[0])
    ap.add_argument("gdi")
    ap.add_argument("--source", help="owned archive/image whose sha256 identifies the build")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    man = inventory(a.gdi)
    if a.source:
        man["source"] = {"path": a.source, "size": Path(a.source).stat().st_size, "sha256": file_sha256(Path(a.source))}
    text = json.dumps(man, indent=1)
    Path(a.out).write_text(text) if a.out else print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
