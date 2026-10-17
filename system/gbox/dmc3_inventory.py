"""Devil May Cry 3 Special Edition (PS2, SLUS_213.61) owned-disc inventory (#1330).

Read-only.  The disc root holds four CRI AFS archives listed in ``0FLIST.DIR``:
GDATA.AFS (all game data), MDATA1/2.AFS (Sofdec ``.sfd`` movies) and SDATA.AFS
(``.adx`` music).  GDATA's CRI name directory is on disc (48-byte records:
name[32], six u16 date fields, u32 size at +44, which matches every entry's size).

Characters are ``plNNN.pac`` packages.  A PAC is ``"PAC\\0"``, u32 slot count, then
u32 child offsets; an offset of 0 is an empty slot, so a child's size runs to the
next larger non-zero offset (or the end of the package).  Inside a player PAC:

* a texture bank (u32 count, then TIM2 pictures),
* ``"MOD "`` models (f32 version 1.01 at +4, u8 object count at +0x10,
  u8 bone count at +0x11),
* ``"SHW "`` shadow models,
* nested PACs of ``"P\\0\\0\\0MOT\\0"`` motions,
* ``;``-prefixed text (``plNNN_NN.clt`` cloth setup) and raw tables.

Weapons are ``plwp_*.pac`` in a different ``"PNST"`` container (u32 count,
u32 offsets).  The SLUS references ``GData.afs`` by name but contains no
``pl%03d``/``.pac`` strings, so the game addresses GDATA entries by index: a
writer must keep every entry's AFS position and name.

``python -m gbox.dmc3_inventory disc.iso --out manifest.json`` writes the manifest.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import struct
from pathlib import Path

SECTOR = 2048
ARCHIVES = ("GDATA.AFS", "MDATA1.AFS", "MDATA2.AFS", "SDATA.AFS")
NAME_REC = 48
BOOT = "SLUS_213.61"
PLAYER_RE = re.compile(r"pl\d{3}\.pac")
MOTION_RE = re.compile(r"(pl\d{3})_(\d\d)_(\d+)\.pac")

# Costume labels published for the PC/HD build's identically named files.  They
# are a lead only: no PS2 runtime check has confirmed them yet.
COMMUNITY_LABELS = {
    "pl000.pac": "Dante, default costume (both sleeves)",
    "pl011.pac": "Dante, default costume, coatless",
    "pl013.pac": "Dante, default costume, ripped sleeve",
    "pl015.pac": "Dante, DMC1 costume",
    "pl016.pac": "Dante, DMC1 costume, coatless",
    "pl018.pac": "Dante, Legendary Dark Knight costume",
    "pl021.pac": "Vergil, default costume",
    "pl023.pac": "Vergil, default costume, coatless",
    "pl026.pac": "Vergil, Legendary Dark Knight costume",
}
LABEL_SOURCE = "community docs for the HD Collection's same-named GData.afs files; unverified on this PS2 build"

TIM2_BPP = {1: 16, 2: 24, 3: 32, 4: 4, 5: 8}


def afs_read(f, lba: int, size: int) -> dict:
    """Entries, name directory and per-entry names of an AFS archive at ``lba``."""
    base = lba * SECTOR
    f.seek(base)
    head = f.read(8)
    if head[:4] != b"AFS\0":
        raise ValueError(f"no AFS header at LBA {lba}")
    n = struct.unpack_from("<I", head, 4)[0]
    f.seek(base)
    tab = f.read(8 + 8 * n + 8)
    ent = [struct.unpack_from("<II", tab, 8 + 8 * i) for i in range(n)]
    nd = struct.unpack_from("<II", tab, 8 + 8 * n)
    if not nd[0]:
        f.seek(base + ent[0][0] - 8)
        nd = struct.unpack("<II", f.read(8))
    end = max(o + z for o, z in ent)
    if end > size:
        raise ValueError(f"AFS entries run to {end:#x}, past the file size {size:#x}")
    names, dates, agree = [], [], 0
    if nd[0] and nd[0] + nd[1] <= size and nd[1] >= NAME_REC * n:
        f.seek(base + nd[0])
        d = f.read(nd[1])
        for i in range(n):
            r = d[i * NAME_REC:(i + 1) * NAME_REC]
            names.append(r[:32].split(b"\0")[0].decode("ascii", "replace"))
            dates.append("%04d-%02d-%02d %02d:%02d:%02d" % struct.unpack_from("<6H", r, 32))
            agree += struct.unpack_from("<I", r, 44)[0] == ent[i][1]
    return {"base": base, "entries": ent, "names": names, "dates": dates,
            "name_dir": list(nd) if nd[0] else None, "name_size_agrees": agree}


def pac_children(b: bytes, magic: bytes = b"PAC\0") -> list[tuple[int, int]]:
    """(offset, size) per slot of a PAC/PNST container; empty slots are (0, 0)."""
    if b[:4] != magic or len(b) < 8:
        raise ValueError(f"not a {magic!r} container")
    c = struct.unpack_from("<I", b, 4)[0]
    if not 0 < c <= (len(b) - 8) // 4:
        raise ValueError(f"bad slot count {c}")
    offs = struct.unpack_from(f"<{c}I", b, 8)
    head = 8 + 4 * c
    nz = sorted({o for o in offs if o})
    if nz and (nz[0] < head or nz[-1] > len(b)):
        raise ValueError("child offset outside the container")
    stops = nz + [len(b)]
    nxt = {o: stops[i + 1] for i, o in enumerate(nz)}
    return [(o, nxt[o] - o) if o else (0, 0) for o in offs]


def tim2_info(b: bytes) -> dict | None:
    """TIM2 picture list: width, height, bits per pixel, mipmaps, palette colours."""
    if b[:4] != b"TIM2" or len(b) < 0x30:
        return None
    count = struct.unpack_from("<H", b, 6)[0]
    o, pics = 0x10 if b[5] == 0 else 0x80, []
    for _ in range(count):
        if o + 0x30 > len(b):
            break
        total, clut, img, hsize, colors = struct.unpack_from("<IIIHH", b, o)
        _fmt, mips, _ctype, itype, w, h = struct.unpack_from("<BBBBHH", b, o + 0x10)
        pics.append({"w": w, "h": h, "bpp": TIM2_BPP.get(itype, itype), "mipmaps": mips,
                     "clut_colors": colors, "image_bytes": img, "clut_bytes": clut})
        if not total:
            break
        o += total
    return {"pictures": pics, "bytes": o}


def tim2_scan(b: bytes) -> list[dict]:
    """Every TIM2 file inside a texture bank (16-byte aligned)."""
    out, i = [], b.find(b"TIM2")
    while i >= 0:
        if i % 16 == 0:
            t = tim2_info(b[i:])
            if t and t["pictures"]:
                out.append({"offset": i, **t})
                i += max(t["bytes"], 16)
                i = b.find(b"TIM2", i)
                continue
        i = b.find(b"TIM2", i + 4)
    return out


def mod_info(b: bytes) -> dict | None:
    """Header fields of a DMC3 ``MOD `` model."""
    if b[:4] != b"MOD " or len(b) < 0x20:
        return None
    ver = struct.unpack_from("<f", b, 4)[0]
    objects, bones, b12, b13, flags, sect = struct.unpack_from("<BBBBII", b, 0x10)
    return {"version": round(ver, 3), "objects": objects, "bones": bones, "u12": b12, "u13": b13,
            "u14": flags, "section_offset": sect, "size": len(b)}


def kind(b: bytes) -> str:
    m = b[:4]
    if m == b"PAC\0":
        return "pac"
    if m == b"PNST":
        return "pnst"
    if m == b"MOD ":
        return "mod"
    if m == b"SHW ":
        return "shadow"
    if m == b"TIM2":
        return "tim2"
    if b[4:8] == b"MOT\0":
        return "motion"
    if b[:1] == b";":
        return "text"
    if len(b) >= 16 and 0 < struct.unpack_from("<I", b, 0)[0] <= 64 and b.find(b"TIM2", 0, 0x4000) > 0:
        return "texbank"
    return "data" if b else "empty"


def walk(b: bytes, path: str, rows: list, depth: int = 0, keep_sha: bool = True) -> None:
    """Append one row per container child (recursively) to ``rows``."""
    k = kind(b)
    row = {"path": path, "kind": k, "size": len(b)}
    if keep_sha:
        row["sha256"] = hashlib.sha256(b).hexdigest()
    if k == "mod":
        row["model"] = mod_info(b)
    elif k == "texbank":
        row["textures"] = [p for t in tim2_scan(b) for p in t["pictures"]]
    elif k == "tim2":
        row["textures"] = (tim2_info(b) or {}).get("pictures", [])
    elif k == "text":
        row["text"] = b[:64].split(b"\r")[0].decode("ascii", "replace")
    rows.append(row)
    if k in ("pac", "pnst") and depth < 4:
        try:
            ch = pac_children(b, b"PAC\0" if k == "pac" else b"PNST")
        except ValueError as e:
            row["error"] = str(e)
            return
        row["slots"], row["empty_slots"] = len(ch), sum(1 for o, _ in ch if not o)
        for i, (o, z) in enumerate(ch):
            if o:
                walk(b[o:o + z], f"{path}/{i}", rows, depth + 1, keep_sha)


def summarize(rows: list) -> dict:
    kids = collections.Counter(r["kind"] for r in rows[1:])
    mods = [dict(r["model"], path=r["path"]) for r in rows if r["kind"] == "mod"]
    tex = [dict(p, path=r["path"]) for r in rows for p in r.get("textures", [])]
    return {"kinds": dict(kids), "models": mods, "textures": tex,
            "motions": kids.get("motion", 0), "shadows": kids.get("shadow", 0),
            "texts": [r["text"] for r in rows if r["kind"] == "text"]}


def inventory(iso: Path) -> dict:
    """Read-only inventory of the extracted DMC3 SE disc image."""
    from .gta_rw import iso_files
    iso = Path(iso)
    with iso.open("rb") as f:
        files = iso_files(f)
        disc = {}
        for name, (lba, size) in sorted(files.items()):
            entry: dict = {"lba": lba, "size": size}
            if size <= 64 << 20:
                f.seek(lba * SECTOR)
                entry["sha256"] = hashlib.sha256(f.read(size)).hexdigest()
            disc[name] = entry
        boot, flist = None, []
        if "SYSTEM.CNF" in files:
            f.seek(files["SYSTEM.CNF"][0] * SECTOR)
            for line in f.read(files["SYSTEM.CNF"][1]).decode("ascii", "replace").splitlines():
                if line.upper().startswith("BOOT2"):
                    boot = line.split("\\", 1)[-1].split(";")[0].strip()
        if "0FLIST.DIR" in files:
            f.seek(files["0FLIST.DIR"][0] * SECTOR)
            flist = f.read(files["0FLIST.DIR"][1]).decode("ascii", "replace").split()
        archives, gdata = {}, None
        for an in ARCHIVES:
            if an not in files:
                continue
            a = afs_read(f, *files[an])
            ext = collections.Counter(n.rsplit(".", 1)[-1].lower() for n in a["names"])
            archives[an] = {"entries": len(a["entries"]), "name_dir": a["name_dir"],
                            "name_size_agrees": a["name_size_agrees"], "extensions": dict(ext)}
            if an == "GDATA.AFS":
                gdata = a
        exe = None
        if boot and boot.upper() in files:
            lba, size = files[boot.upper()]
            f.seek(lba * SECTOR)
            elf = f.read(size)
            exe = {"name": boot, "size": size, "sha256": hashlib.sha256(elf).hexdigest(),
                   "elf": elf[:4] == b"\x7fELF", "entry": hex(struct.unpack_from("<I", elf, 0x18)[0]),
                   "afs_name_refs": {s: elf.count(s.encode()) for s in ("GData.afs", "pl%03d", ".pac")}}
        players, weapons, motions, enemies = [], [], {}, []
        top = collections.Counter()
        if gdata:
            for i, ((o, z), nm) in enumerate(zip(gdata["entries"], gdata["names"])):
                f.seek(gdata["base"] + o)
                deep = PLAYER_RE.fullmatch(nm) or nm.startswith(("plwp_", "em")) or MOTION_RE.fullmatch(nm)
                b = f.read(z if deep else min(z, 0x4000))
                top[kind(b)] += 1
                if not deep:
                    continue
                rows: list = []
                walk(b, f"GDATA.AFS:{i}", rows)
                s = {"index": i, "name": nm, "size": z, "sha256": rows[0]["sha256"],
                     "date": gdata["dates"][i], "container": rows[0]["kind"],
                     "slots": rows[0].get("slots"), **summarize(rows)}
                mm = MOTION_RE.fullmatch(nm)
                if PLAYER_RE.fullmatch(nm):
                    s["label"] = COMMUNITY_LABELS.get(nm)
                    players.append(s)
                elif mm:
                    motions.setdefault(mm.group(1), []).append(
                        {"index": i, "name": nm, "style": int(mm.group(2)), "bank": int(mm.group(3)),
                         "size": z, "motions": s["motions"], "sha256": s["sha256"]})
                elif nm.startswith("plwp_"):
                    weapons.append(s)
                else:
                    enemies.append(s)
    for p in players:
        p["motion_banks"] = len(motions.get(p["name"][:5], []))
    return {"serial": boot, "flist": flist, "disc": disc, "executable": exe, "archives": archives,
            "gdata_kinds": dict(top), "players": players, "player_motion_banks": motions,
            "weapons": weapons, "enemies": enemies, "label_source": LABEL_SOURCE,
            "counts": {"players": len(players),
                       "player_models": sum(len(p["models"]) for p in players),
                       "player_textures": sum(len(p["textures"]) for p in players),
                       "player_motions": sum(p["motions"] for p in players)
                       + sum(m["motions"] for v in motions.values() for m in v),
                       "weapons": len(weapons), "enemies": len(enemies)}}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="DMC3 SE PS2 disc inventory (read-only)")
    ap.add_argument("iso")
    ap.add_argument("--out", help="write the full manifest JSON here")
    a = ap.parse_args(argv)
    m = inventory(Path(a.iso))
    if a.out:
        Path(a.out).write_text(json.dumps(m, indent=1))
    print(json.dumps({"serial": m["serial"], "executable": m["executable"], "counts": m["counts"],
                      "players": [(p["name"], p["label"], [(x["objects"], x["bones"]) for x in p["models"]],
                                   len(p["textures"]), p["motion_banks"]) for p in m["players"]]}, indent=1))


if __name__ == "__main__":
    main()
