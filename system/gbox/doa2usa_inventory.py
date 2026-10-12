"""Exact-build inventory for Dead or Alive 2 (USA), Dreamcast (game 5f08ad9a86ebcc9a).

Reads the unpacked GD-ROM (``disc.gdi`` made by ``chdman extractcd`` from the owned CHD)
read-only and writes a JSON manifest: source and track hashes, IP.BIN identity, the
1ST_READ.BIN hash, the container layout of ``DOA2/`` and the per-fighter character
inventory (CHR NaomiLib models + texture descriptors, BIN texture banks, SUP records,
APV/ACS companions, motion banks) together with each file's LBA room on the disc, which
bounds a same-size native writer.

    python -m gbox.doa2usa_inventory disc.gdi --chd OWNED.chd --out manifest.json

The USA build is T-3601N V1.100 (2000-03-06). It is a different executable than the
DOA2 Limited Edition (T3601M V1.002, game 1de2e7634f3161ff): the LE ``doa2_bindings``
part-script tables do not exist at the same addresses here, and the roster differs
(no SAM/Leon, no PDG variant). CHR/BIN/SUP/APV/ACS parsing in ``doa2_chars`` is
executable-independent and is reused as-is.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

GAME_ID = "5f08ad9a86ebcc9a"
TITLE = "Dead or Alive 2 (USA)"
# 1ST_READ.BIN of the owned T-3601N V1.100 disc (recorded here; the LE hash is
# 27a014ae... and its addresses must NOT be reused for this build).
FIRST_READ_SHA256 = "105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85"
PRODUCT = "T3601N"
SECTOR = 2048
NON_FIGHTER = ("STAGE", "EFC", "FIX", "DV")

# USA roster order matches the select screen: 12 regular + Tengu + Ein. Leon (SAM)
# and the PDG variant exist only on later/LE builds and must not be assumed here.
FIGHTERS = [
    ("KAS", "Kasumi"), ("AYA", "Ayane"), ("LEI", "Leifang"), ("TIN", "Tina"),
    ("BAS", "Bass"), ("JAN", "Jann Lee"), ("GEN", "Gen Fu"), ("BAY", "Bayman"),
    ("RYU", "Ryu Hayabusa"), ("ZAC", "Zack"), ("HIK", "Helena"), ("TNG", "Tengu"),
    ("KTE", "Ein"),
]
# single-costume story/variant families present on the USA disc (no PDG)
VARIANTS = ["LOR", "MAM", "WBA", "YTI"]
# .MOT banks by the character's nickname; Ein's bank is KARATE on this build.
MOT_FILES = {"KAS": "KASUMI", "AYA": "AYANE", "LEI": "LEIFAN", "TIN": "TINA",
             "BAS": "BASS", "JAN": "JANLEE", "GEN": "GENFU", "BAY": "BAYMAN",
             "RYU": "RYU", "ZAC": "ZACK", "HIK": "HIKA", "TNG": "TENGU",
             "KTE": "KARATE", "LOR": "LORAN", "MAM": "MAMA", "WBA": "WAKABS"}


def sha256_file(path: str | Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_ip(sector: bytes) -> dict:
    """Dreamcast IP.BIN meta block (first 0x100 bytes of the high-density data track)."""
    if sector[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("No Dreamcast IP.BIN at the start of the high-density area")
    f = lambda a, b: sector[a:b].decode("latin-1").strip()  # noqa: E731
    return {"hardware": f(0x00, 0x10), "maker": f(0x10, 0x20), "device": f(0x20, 0x30),
            "area": f(0x30, 0x38), "peripherals": f(0x38, 0x40), "product": f(0x40, 0x4A),
            "version": f(0x4A, 0x50), "date": f(0x50, 0x60), "boot": f(0x60, 0x70),
            "company": f(0x70, 0x80), "title": f(0x80, 0x100)}


def file_room(files: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Bytes each file may occupy without moving another file: up to the next file's LBA."""
    order = sorted(files.items(), key=lambda kv: (kv[1][0], kv[0]))
    room = {}
    for i, (name, (lba, size)) in enumerate(order):
        own = (size + SECTOR - 1) // SECTOR * SECTOR
        nxt = next((l for _, (l, _s) in order[i + 1:] if l > lba), None)
        room[name] = max(own, (nxt - lba) * SECTOR) if nxt is not None else own
    return room


def families(files: dict[str, tuple[int, int]]) -> dict[str, list[str]]:
    fam: dict[str, set] = {}
    for n in files:
        m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN|APV|ACS|MDL)$", n)
        if m and m.group(1) not in NON_FIGHTER:
            fam.setdefault(m.group(1), set()).add(m.group(2))
    return {k: sorted(v, key=int) for k, v in fam.items()}


def build(gdi: str | Path, *, chd: str | Path | None = None, chd_sha256: str | None = None,
          hash_tracks: bool = True, deep: bool = True, progress=None) -> dict:
    """Inventory manifest for the disc at ``gdi`` (read-only)."""
    from .gdrom import GDRom
    from .doa2_chars import parse_chr, parse_sup, parse_mot_table
    gdi = Path(gdi)
    disc = GDRom(gdi)
    say = progress or (lambda *_: None)
    hd = min(t for t in disc.tracks if t[0] >= 45000)
    ip = parse_ip(disc.sector(hd[0]))
    tracks = []
    for line in gdi.read_text().split("\n")[1:]:
        p = line.split()
        if len(p) >= 6:
            path = gdi.parent / p[4].strip('"')
            t = {"track": int(p[0]), "lba": int(p[1]), "type": "data" if p[2] == "4" else "audio",
                 "sector_size": int(p[3]), "file": p[4].strip('"'),
                 "bytes": path.stat().st_size if path.exists() else None}
            if hash_tracks and path.exists():
                say(f"hashing {t['file']}")
                t["sha256"] = sha256_file(path)
            tracks.append(t)
    first = disc.read("1ST_READ.BIN")
    first_sha = hashlib.sha256(first).hexdigest()
    room = file_room(disc.files)
    exts: dict[str, dict] = {}
    for n, (_lba, size) in disc.files.items():
        d, _, base = n.rpartition("/")
        k = f"{d or '.'}/*.{base.rsplit('.', 1)[-1]}"
        e = exts.setdefault(k, {"files": 0, "bytes": 0})
        e["files"] += 1
        e["bytes"] += size

    def entry(name: str, kind: str) -> dict | None:
        if name not in disc.files:
            return None
        lba, size = disc.files[name]
        out = {"file": name, "lba": lba, "bytes": size, "room": room[name]}
        if deep:
            data = disc.read(name)
            out["sha256"] = hashlib.sha256(data).hexdigest()
            if kind == "CHR":
                try:
                    c = parse_chr(data)
                except Exception as e:  # noqa: BLE001
                    out["decoded"] = False
                    out["error"] = f"{type(e).__name__}: {e}"
                else:
                    fmts: dict[str, int] = {}
                    for t in c["textures"]:
                        k = f"{t['width']}x{t['height']} px{t['pixel']} fmt{t['format']}"
                        fmts[k] = fmts.get(k, 0) + 1
                    out.update({"decoded": True, "models": c["n_models"],
                                "textures": c["n_textures"], "pointer_base": c["ptr_base"],
                                "model_table_offset": c["model_table_offset"],
                                "texture_table_offset": c["texture_table_offset"],
                                "texture_formats": fmts, "model_bytes": sum(c["sizes"])})
            elif kind == "SUP":
                try:
                    out["records"] = parse_sup(data)["n_records"]
                except Exception as e:  # noqa: BLE001
                    out["records"] = None
                    out["error"] = f"{type(e).__name__}: {e}"
            elif kind == "MOT":
                out["clips"] = parse_mot_table(data)["n_clips"]
        return out

    fam = families(disc.files)
    roster = []
    for key, name in FIGHTERS:
        roster.append({"key": key, "name": name, "kind": "character",
                       "on_disc": key in fam})
    for key in VARIANTS:
        roster.append({"key": key, "name": f"{key} (variant)", "kind": "variant",
                       "on_disc": key in fam})
    known = {r["key"] for r in roster}
    for key in sorted(set(fam) - known):
        roster.append({"key": key, "name": f"{key} (unmapped family)", "kind": "unmapped",
                       "on_disc": True})
    for r in roster:
        say(f"inventory {r['key']}")
        costumes = []
        for c in fam.get(r["key"], []):
            stem = f"DOA2/{r['key']}{c}"
            costumes.append({"costume": c, **{k.lower(): entry(f"{stem}.{k}", k)
                                              for k in ("CHR", "BIN", "SUP", "APV", "ACS", "MDL")
                                              if f"{stem}.{k}" in disc.files}})
        r["costumes"] = costumes
        mot = MOT_FILES.get(r["key"])
        if mot:
            r["motion"] = [m for m in (entry(f"DOA2/{mot}.MOT", "MOT"),
                                       entry(f"DOA2/C_{mot}.MOT", "MOT")) if m]
    mot_names = sorted(n for n in disc.files if n.startswith("DOA2/") and n.endswith(".MOT"))
    stages = sorted(n for n in disc.files if re.match(r"^DOA2/STAGE\d+\.(?:CHR|BIN)$", n))
    return {
        "schema": "gbox.doa2usa_inventory/1",
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "dreamcast",
        "source": {"chd": str(chd) if chd else None,
                   "chd_bytes": Path(chd).stat().st_size if chd and Path(chd).exists() else None,
                   "chd_sha256": chd_sha256, "gdi": str(gdi), "tracks": tracks},
        "ip": ip,
        "build_matches": ip["product"] == PRODUCT and first_sha == FIRST_READ_SHA256,
        "executable": {"file": "1ST_READ.BIN", "bytes": len(first), "sha256": first_sha,
                       "load_address": "0x8c010000", "expected_sha256": FIRST_READ_SHA256,
                       "matches": first_sha == FIRST_READ_SHA256},
        "launch": {"core": "flycast (RetroArch)", "bios": "Dreamcast BIOS dc_boot.bin + dc_flash.bin "
                   "in the RetroArch system/dc folder", "media": "GD-ROM image (CHD or GDI); area "
                   f"{ip['area'] or '?'} (USA) region; no disc encryption"},
        "layout": {"files": len(disc.files), "by_extension": dict(sorted(exts.items())),
                   "root": sorted(n for n in disc.files if "/" not in n)},
        "characters": roster,
        "motion_files": mot_names,
        "stages": stages,
        "notes": [
            "USA T-3601N V1.100 build; 1ST_READ.BIN differs from DOA2 LE (T3601M V1.002). "
            "The LE part-script addresses in doa2_bindings are NOT valid here - locating the "
            "USA tables is the analysis stage's first task.",
            "No SAM (Leon) or PDG files on this disc: they exist on the LE build only.",
            "CHR = NaomiLib models + texture descriptors with absolute work-RAM pointers; "
            "BIN = PVR texture bank; no skeleton in CHR (joint map comes from runtime/SUP).",
            "'room' = bytes up to the next file's LBA: the in-place limit for a native writer.",
            "KAS04.MDL duplicates the Kasumi C4 model as a loose NaomiLib MDL file.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DOA2 (USA) Dreamcast exact-build inventory")
    ap.add_argument("gdi", help="unpacked disc.gdi (chdman extractcd)")
    ap.add_argument("--chd", help="owned source CHD path")
    ap.add_argument("--out", default="doa2usa_manifest.json")
    ap.add_argument("--no-deep", action="store_true", help="skip per-file decode/hashing")
    args = ap.parse_args(argv)
    chd_sha = sha256_file(args.chd) if args.chd else None
    manifest = build(args.gdi, chd=args.chd, chd_sha256=chd_sha,
                     deep=not args.no_deep, progress=lambda *a: print(*a, file=sys.stderr))
    with open(args.out, "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"wrote {args.out}")
    return 0 if manifest["build_matches"] else 2


if __name__ == "__main__":
    sys.exit(main())
