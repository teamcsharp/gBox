"""Crazy Taxi 2 (USA) Dreamcast inventory for catalog game b5dfa0c44de0ba90 (request #1666).

Owned source: hyperspin `collections/Sega Dreamcast/roms/Crazy Taxi 2 (USA).chd` (CHD v5, 102394174 bytes,
sha256 8b06f741...d2ee). `gbox.chd` reads v4 only, so the disc is unpacked once with `chdman extractcd` to
`<cache>/dc/b5dfa0c44de0ba90/disc.gdi` (the same place `characters._dc_gdi` puts it) and read with gbox.gdrom.GDRom.

The fingerprint's nearest title is the QuickSwap2 CDI build (game 45e9455ca5487e7d, gbox.crazy_taxi2, #1482). This
module does not assume the two are the same build: it reads this disc's IP.BIN, hashes 1ST_READ.BIN and every model /
texture file, compares each against `crazy_taxi2.FILES_SHA256`, and walks every POL*.BIN with `crazy_taxi2.walk`
(which raises unless the file ends exactly after its last object). Driver identity comes from `crazy_taxi2.DRIVERS`
(1ST_READ.BIN name order); the per-file mapping is still inferred, not checked against a rendered frame.

The manifest is read-only evidence; nothing on the disc or the share is written.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import crazy_taxi2 as c2
from .doa2usa_inventory import file_room, parse_ip, sha256_file

GAME_ID = "b5dfa0c44de0ba90"
TITLE = "Crazy Taxi 2 (USA)"
CHD_REL = "collections/Sega Dreamcast/roms/Crazy Taxi 2 (USA).chd"
MODEL_RE = re.compile(r"^(POL|TEX)(P[PCS][A-Z0-9]*|PPL0|PSG0|PPTST|DC\d[A-Z]?)\.BIN$")
DRIVER_RE = re.compile(r"^POLPP([12][A-D])(H?)\.BIN$")
LAUNCH = ("Flycast (RetroArch core or standalone) with Dreamcast BIOS dc_boot.bin/dc_flash.bin in the system dir; "
          "boots from the 3-track GDI or the CHD directly; 1 player, VMU save optional.")


def driver_set(files) -> dict:
    """POLPP<key>[H].BIN + TEXPP<key>[H].BIN pairs -> {key: {driver, model, texture, high_model, high_texture}}."""
    out = {}
    for n in sorted(files):
        m = DRIVER_RE.match(n)
        if not m:
            continue
        key, hi = m.groups()
        row = out.setdefault(key, {"driver": c2.DRIVERS.get("PP" + key)})
        tex = f"TEXPP{key}{hi}.BIN"
        row["high_model" if hi else "model"] = n
        row["high_texture" if hi else "texture"] = tex if tex in files else None
    return out


def compare_known(hashes: dict[str, str]) -> dict:
    """This disc's file hashes against the CDI build's pinned ones (crazy_taxi2.FILES_SHA256)."""
    same = sorted(n for n, h in c2.FILES_SHA256.items() if hashes.get(n) == h)
    diff = sorted(n for n, h in c2.FILES_SHA256.items() if n in hashes and hashes[n] != h)
    missing = sorted(n for n in c2.FILES_SHA256 if n not in hashes)
    return {"identical": same, "different": diff, "missing": missing,
            "same_build": not diff and not missing}


def compare_disc(man: dict, other) -> dict:
    """Every model/texture bank of this manifest against another disc reader (e.g. the CDI build's CDIRom)."""
    same, diff, missing = [], [], []
    for m in man["models"]:
        n = m["file"]
        if n not in other.files:
            missing.append(n)
        elif hashlib.sha256(other.read(n)).hexdigest() == m["sha256"]:
            same.append(n)
        else:
            diff.append(n)
    first = other.read("1ST_READ.BIN")
    return {"banks": len(man["models"]), "identical": len(same), "different": diff, "missing": missing,
            "other_first_read": {"bytes": len(first), "sha256": hashlib.sha256(first).hexdigest()},
            "first_read_identical": hashlib.sha256(first).hexdigest() == man["first_read"]["sha256"],
            "other_files": len(other.files)}


def build(gdi: str | Path, *, chd: str | Path | None = None, chd_sha256: str | None = None,
          hash_tracks: bool = True, progress=None) -> dict:
    from .gdrom import GDRom
    gdi = Path(gdi)
    say = progress or (lambda *_: None)
    disc = GDRom(gdi)
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
    files = disc.files
    room = file_room(files)
    first = disc.read("1ST_READ.BIN")
    hashes = {"1ST_READ.BIN": hashlib.sha256(first).hexdigest()}
    models, failures = [], []
    for n in sorted(files):
        if not MODEL_RE.match(n):
            continue
        b = disc.read(n)
        hashes[n] = hashlib.sha256(b).hexdigest()
        row = {"file": n, "bytes": len(b), "lba": files[n][0], "room": room[n], "sha256": hashes[n]}
        if n.startswith("POL"):
            try:
                row |= {k: v for k, v in c2.summary(n, b).items() if k not in ("file", "bytes")}
            except ValueError as e:
                failures.append({"file": n, "error": str(e)})
                row["error"] = str(e)
        else:
            row["kind"] = "texture bank"
        models.append(row)
    exts: dict[str, dict] = {}
    for n, (_lba, size) in files.items():
        d, _, base = n.rpartition("/")
        e = exts.setdefault(f"{d or '.'}/*.{base.rsplit('.', 1)[-1]}", {"files": 0, "bytes": 0})
        e["files"] += 1
        e["bytes"] += size
    names = sorted({m.decode() for m in re.findall(rb"pol[Pp][Pp][12][A-D]H?\.bin", first, re.I)})
    drivers_named = [s.decode() for s in re.findall(rb"SLASH|ICEMAN|CINNAMON|HOT-D|AXEL|B\.D\.JOE|GENA|GUS", first)]
    pols = [m for m in models if m["file"].startswith("POL")]
    return {
        "game_id": GAME_ID, "title": TITLE,
        "source": {"file": str(chd) if chd else None, "format": "chd v5 (chdman extractcd -> gdi)",
                   "sha256": chd_sha256, "gdi": str(gdi)},
        "ip": ip, "tracks": tracks, "launch": LAUNCH,
        "first_read": {"bytes": len(first), "sha256": hashes["1ST_READ.BIN"],
                       "driver_file_names": names, "driver_names_in_order": drivers_named[:16]},
        "files": len(files), "extensions": dict(sorted(exts.items())),
        "models": models, "walk_failures": failures,
        "pol_files": len(pols), "pol_walked": len(pols) - len(failures),
        "triangles": sum(m.get("triangles", 0) for m in pols),
        "drivers": driver_set(files),
        "vs_cdi_build_45e9455ca5487e7d": compare_known(hashes),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Crazy Taxi 2 (USA) Dreamcast inventory")
    ap.add_argument("gdi")
    ap.add_argument("--chd")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-track-hash", action="store_true")
    ap.add_argument("--compare-cdi", help="also hash every bank of another (CDI) image of the game")
    a = ap.parse_args(argv)
    chd_sha = sha256_file(a.chd) if a.chd else None
    man = build(a.gdi, chd=a.chd, chd_sha256=chd_sha, hash_tracks=not a.no_track_hash)
    if a.compare_cdi:
        from .gdrom import CDIRom
        man["vs_cdi_disc"] = compare_disc(man, CDIRom(a.compare_cdi))
    text = json.dumps(man, indent=1, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n")
    print(json.dumps({k: man[k] for k in ("ip", "first_read", "pol_files", "pol_walked", "triangles",
                                          "vs_cdi_build_45e9455ca5487e7d")} | {"vs_cdi_disc": man.get("vs_cdi_disc")},
                     indent=1))
    return 0 if not man["walk_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
