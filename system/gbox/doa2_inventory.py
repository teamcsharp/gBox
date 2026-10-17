"""Exact-build inventory for Dead or Alive 2 - Limited Edition (Japan), Dreamcast.

Reads the unpacked GD-ROM (``disc.gdi`` made by ``chdman extractcd`` from the owned CHD)
read-only and writes a JSON manifest: source and track hashes, IP.BIN identity, the
1ST_READ.BIN hash, the container layout of ``DOA2/`` and the per-fighter character
inventory (CHR NaomiLib models + texture descriptors, BIN texture banks, SUP records,
APV/ACS companions, motion banks) together with each file's LBA room on the disc, which
bounds a same-size native writer.

    python -m gbox.doa2_inventory disc.gdi --chd OWNED.chd --out manifest.json

Nothing on the disc is modified. No skeleton facts are invented: CHR holds models and
texture descriptors only (see ``doa2_chars``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

GAME_ID = "1de2e7634f3161ff"
# 1ST_READ.BIN of the owned T3601M V1.002 disc (also recorded in doa2_chars).
FIRST_READ_SHA256 = "27a014aeda35983df749f7d575bbddbea3f1ffd1f7776194ef503108c20c97e1"
PRODUCT = "T3601M"
SECTOR = 2048
NON_FIGHTER = ("STAGE", "EFC", "FIX", "DV")


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
    """Bytes each file may occupy without moving another file: up to the next file's LBA.

    The last file (by LBA) is limited to its own sector-rounded size.
    """
    order = sorted(files.items(), key=lambda kv: (kv[1][0], kv[0]))
    room = {}
    for i, (name, (lba, size)) in enumerate(order):
        own = (size + SECTOR - 1) // SECTOR * SECTOR
        nxt = next((l for _, (l, _s) in order[i + 1:] if l > lba), None)
        room[name] = max(own, (nxt - lba) * SECTOR) if nxt is not None else own
    return room


def families(names) -> dict[str, list[str]]:
    fam: dict[str, set] = {}
    for n in names:
        m = re.match(r"^DOA2/([A-Z]+)(\d+)\.(?:CHR|SUP|BIN|APV|ACS|MDL)$", n)
        if m and m.group(1) not in NON_FIGHTER:
            fam.setdefault(m.group(1), set()).add(m.group(2))
    return {k: sorted(v, key=int) for k, v in fam.items()}


def _chr_facts(data: bytes) -> dict:
    from .doa2_chars import parse_chr
    try:
        c = parse_chr(data)
    except Exception as e:  # noqa: BLE001 - reported per file, never hidden
        return {"decoded": False, "error": f"{type(e).__name__}: {e}"}
    fmts: dict[str, int] = {}
    for t in c["textures"]:
        k = f"{t['width']}x{t['height']} px{t['pixel']} fmt{t['format']}"
        fmts[k] = fmts.get(k, 0) + 1
    return {"decoded": True, "models": c["n_models"], "textures": c["n_textures"],
            "pointer_base": c["ptr_base"], "model_table_offset": c["model_table_offset"],
            "texture_table_offset": c["texture_table_offset"], "texture_formats": fmts,
            "model_bytes": sum(c["sizes"])}


def _sup_facts(data: bytes) -> dict:
    from .doa2_chars import parse_sup
    try:
        return {"records": parse_sup(data)["n_records"]}
    except Exception as e:  # noqa: BLE001
        return {"records": None, "error": f"{type(e).__name__}: {e}"}


def _mot_facts(data: bytes) -> dict:
    from .doa2_chars import parse_mot_table
    return {"clips": parse_mot_table(data)["n_clips"]}


def build(gdi: str | Path, *, chd: str | Path | None = None, chd_sha256: str | None = None,
          hash_tracks: bool = True, deep: bool = True, progress=None) -> dict:
    """Inventory manifest for the disc at ``gdi`` (read-only)."""
    from .gdrom import GDRom
    from .doa2_chars import FIGHTERS, MOT_FILES, VARIANTS
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
                out.update(_chr_facts(data))
            elif kind == "SUP":
                out.update(_sup_facts(data))
            elif kind == "MOT":
                out.update(_mot_facts(data))
        return out

    fam = families(disc.files)
    roster = []
    for key, name, _aliases in FIGHTERS:
        roster.append({"key": key, "name": name, "kind": "character"})
    for key in VARIANTS:
        roster.append({"key": key, "name": f"{key} (variant)", "kind": "variant"})
    known = {r["key"] for r in roster}
    for key in sorted(set(fam) - known):
        roster.append({"key": key, "name": f"{key} (unmapped family)", "kind": "unmapped"})
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
            r["motion"] = [m for m in (entry(f"DOA2/{mot}.MOT", "MOT"), entry(f"DOA2/C_{mot}.MOT", "MOT")) if m]
    mot_names = sorted(n for n in disc.files if n.startswith("DOA2/") and n.endswith(".MOT"))
    stages = sorted(n for n in disc.files if re.match(r"^DOA2/STAGE\d+\.(?:CHR|BIN)$", n))
    return {
        "schema": "gbox.doa2_inventory/1",
        "game_id": GAME_ID,
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
                   f"{ip['area'] or '?'} (Japan) region; no disc encryption"},
        "layout": {"files": len(disc.files), "by_extension": dict(sorted(exts.items())),
                   "root": sorted(n for n in disc.files if "/" not in n)},
        "characters": roster,
        "motion_files": mot_names,
        "stages": stages,
        "notes": ["CHR = NaomiLib models + texture descriptors with absolute work-RAM pointers; "
                  "BIN = PVR texture bank; no skeleton in CHR (joint map comes from runtime/SUP).",
                  "'room' = bytes up to the next file's LBA: the in-place limit for a native writer.",
                  "DP*/ directories are the Limited Edition's bundled DreamPassport browser."],
    }


def summary(m: dict) -> dict:
    chars = [r for r in m["characters"] if r["kind"] != "unmapped"]
    chrs = [c["chr"] for r in m["characters"] for c in r["costumes"] if c.get("chr")]
    return {"product": m["ip"]["product"], "version": m["ip"]["version"], "date": m["ip"]["date"],
            "area": m["ip"]["area"], "executable_matches": m["executable"]["matches"],
            "files": m["layout"]["files"], "families": len(chars),
            "costumes": sum(len(r["costumes"]) for r in m["characters"]),
            "chr_files": len(chrs), "chr_decoded": sum(1 for c in chrs if c.get("decoded")),
            "models": sum(c.get("models", 0) for c in chrs),
            "motion_files": len(m["motion_files"]), "stages": len(m["stages"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--chd", help="owned CHD (hashed unless --chd-sha256 is given)")
    ap.add_argument("--chd-sha256")
    ap.add_argument("--no-track-hash", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sha = a.chd_sha256 or (sha256_file(a.chd) if a.chd else None)
    m = build(a.gdi, chd=a.chd, chd_sha256=sha, hash_tracks=not a.no_track_hash,
              progress=lambda s: print(s, file=sys.stderr))
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps(summary(m), indent=1))
    return 0 if m["build_matches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
