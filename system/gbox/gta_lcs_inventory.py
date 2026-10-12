"""GTA Liberty City Stories (PS2): owned-source inventory for native character replacement.

Builds a reproducible manifest of the exact owned build: the catalog CHD and the plain ISO the writer patches,
their hashes, the boot executable (SYSTEM.CNF BOOT2 -> SLUS_214.23), the disc container layout, the
special-model directory in GAME.DTZ (player, outfits, cutscene and story characters, props), every ped model
info with its TXD and streaming position in MODELS/GTA3PS2.IMG, and the cutscene animation directory.

Each special-model chunk is hashed and parsed with the existing reader (gbox.gta_stories_models.read_ped), so
the manifest records which entries are skinned peds (bones, strips, vertices, triangles, texture names) and
which are rigid objects. Nothing on the disc is modified.

    python -m gbox.gta_lcs_inventory DISC.iso [--rom ROM.chd] [--out manifest.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

from .gta_stories_models import (MDL_IDENT, OUTFITS, SECTOR, LcsDisc, Reloc, read_chk, read_ped,
                                 strip_triangles, txd_for)

EXPECTED_BOOT = "SLUS_214.23"
DIR_ENTRY = 32
MIN_PED_BONES = 20


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def parse_system_cnf(text: str) -> dict:
    """SYSTEM.CNF -> {boot, executable, ver, vmode}. BOOT2 = cdrom0:\\SLUS_214.23;1."""
    out = {}
    for line in text.replace("\r", "").split("\n"):
        if "=" in line:
            k, v = (s.strip() for s in line.split("=", 1))
            out[k.lower()] = v
    boot = out.get("boot2", "")
    m = re.match(r"cdrom0:\\+([^;]+)", boot, re.I)
    return {"boot": boot, "executable": m.group(1).upper() if m else "", "ver": out.get("ver", ""),
            "vmode": out.get("vmode", "")}


def parse_dir(b: bytes) -> list[dict]:
    """A GTA Stories CDirectory blob: 32-byte {u32 sector, u32 sectors, char name[24]} entries."""
    out = []
    for k in range(0, len(b) - DIR_ENTRY + 1, DIR_ENTRY):
        s, n = struct.unpack_from("<II", b, k)
        name = b[k + 8:k + 32].split(b"\0")[0]
        if not name or not all(32 < c < 127 for c in name):
            break
        out.append({"name": name.decode("ascii"), "sector": s, "sectors": n})
    return out


def classify_special(name: str) -> str:
    """Role of a special-model directory name. Outfits load into model slot 0 (the player)."""
    n = name.lower()
    if n == "player":
        return "player_base"
    if n in OUTFITS or re.fullmatch(r"plr\d*", n):
        return "player_outfit"
    if re.fullmatch(r"player\d+", n) or re.fullmatch(r"toni_[a-z]\d", n):
        return "player_alt"
    if re.fullmatch(r"cs(plr|player)\d*", n) or n.startswith("cstoni"):
        return "cutscene_player"
    if n.startswith("cs"):
        return "cutscene"
    return "story"


def ped_stats(chunk: bytes) -> dict:
    """Parse a special-model chunk: skinned ped stats, or why it is not a ped."""
    r = Reloc(chunk)
    if r.ident != MDL_IDENT:
        return {"kind": "unknown", "ident": f"0x{r.ident:08x}"}
    try:
        m = read_ped(chunk)
    except Exception as e:                       # rigid props have no element group / skin
        return {"kind": "object", "reason": f"{type(e).__name__}: {e}"[:120]}
    verts = sum(len(s.pos) for s in m.strips)
    tris = sum(len(strip_triangles(len(s.pos))) for s in m.strips)
    layout = "clump" if r.u32(0x20) == 2 else "ped_mdl"       # cutscene chunks: bare element group at 0x20
    # gameplay peds have 24 hierarchy nodes, cutscene peds 53 (face bones); 2-3 bone chunks are animated props
    return {"kind": "ped" if len(m.hier) >= MIN_PED_BONES else "skinned_object", "layout": layout,
            "nodes": len(m.nodes), "bones": len(m.hier), "strips": len(m.strips), "vertices": verts,
            "triangles": tris, "materials": len(m.materials),
            "textures": sorted({x["texture"] for x in m.materials if x["texture"]}),
            "geo_flags": m.geo_flags, "skinned": m.strips[0].J is not None if m.strips else False}


def special_inventory(disc: LcsDisc, parse: bool = True) -> list[dict]:
    out = []
    for e in disc.special_dir():
        row = {"name": e["name"], "role": classify_special(e["name"]), "sector": e["sector"],
               "sectors": e["sectors"], "dir_offset": e["dir_offset"]}
        if parse:
            b = disc.file_at(e["sector"])
            row["size"] = len(b)
            row["sha256"] = hashlib.sha256(b).hexdigest()
            row.update(ped_stats(b))
            try:
                ts, tn = txd_for(disc, e["name"])
                t = disc.img_read(ts, tn)
                t = t[:struct.unpack_from("<I", t, 8)[0]]
                texs = read_chk(t)
                row["txd"] = {"sector": ts, "sectors": tn, "sha256": hashlib.sha256(t).hexdigest(),
                              "textures": [{"name": x.name, "size": [x.width, x.height], "depth": x.depth}
                                           for x in texs]}
            except KeyError:
                row["txd"] = None
            except Exception as ex:
                row["txd"] = {"error": f"{type(ex).__name__}: {ex}"[:120]}
        out.append(row)
    return out


def ped_model_infos(disc: LcsDisc) -> list[dict]:
    g = disc.game
    out = []
    for i in range(g.u32(0x20 + 0x18)):
        mi = disc.model_info(i)
        if not mi or mi["type"] != 7:
            continue
        s, n = disc.streaming(i)
        row = dict(mi, model_sector=s, model_sectors=n)
        if mi["txd_slot"] >= 0:
            row["txd_sector"], row["txd_sectors"] = disc.streaming(4900 + mi["txd_slot"])
        out.append(row)
    return out


def containers(files: dict[str, tuple[int, int]]) -> dict:
    groups: dict[str, dict] = {}
    for path, (lba, size) in files.items():
        top = path.split("/")[0] if "/" in path else "/"
        g = groups.setdefault(top, {"files": 0, "bytes": 0})
        g["files"] += 1
        g["bytes"] += size
    key = {p: {"lba": l, "size": s} for p, (l, s) in sorted(files.items())
           if p.endswith((".IMG", ".DIR", ".DTZ", ".LVZ", ".CNF", ".GXT", ".SCM")) or re.fullmatch(r"S[LC][UE]S_\d+\.\d+", p)}
    return {"file_count": len(files), "groups": groups, "key_files": key}


def inventory(iso: Path, rom: Path | None = None, rom_sha256: str | None = None, iso_sha256: str | None = None,
              hash_images: bool = True, parse: bool = True) -> dict:
    iso = Path(iso)
    disc = LcsDisc(iso)
    with open(iso, "rb") as f:
        def read(path):
            lba, size = disc.files[path]
            f.seek(lba * SECTOR)
            return f.read(size)
        cnf = parse_system_cnf(read("SYSTEM.CNF").decode("latin-1"))
        exe_name = cnf["executable"]
        exe = read(exe_name) if exe_name in disc.files else b""
        cuts = parse_dir(read("ANIM/CUTS.DIR")) if "ANIM/CUTS.DIR" in disc.files else []
    if rom and hash_images and not rom_sha256:
        rom_sha256 = sha256_file(Path(rom))
    if hash_images and not iso_sha256:
        iso_sha256 = sha256_file(iso)
    specials = special_inventory(disc, parse)
    peds = ped_model_infos(disc)
    roles = Counter(s["role"] for s in specials)
    kinds = Counter(s.get("kind", "unparsed") for s in specials)
    cut_ext = Counter(c["name"].rsplit(".", 1)[-1].lower() for c in cuts)
    blockers = []
    if exe_name != EXPECTED_BOOT:
        blockers.append(f"boot executable {exe_name!r} is not {EXPECTED_BOOT} (the build gBox's LIVE addresses target)")
    if not exe:
        blockers.append("boot executable missing from the disc")
    return {
        "schema": "gbox.gta_lcs_inventory/1",
        "title": "Grand Theft Auto - Liberty City Stories (USA)",
        "platform": "ps2",
        "source": {"rom": str(rom) if rom else None, "rom_sha256": rom_sha256, "iso": str(iso),
                   "iso_size": iso.stat().st_size, "iso_sha256": iso_sha256,
                   "iso_sectors": iso.stat().st_size // SECTOR},
        "boot": dict(cnf, executable_sha256=hashlib.sha256(exe).hexdigest() if exe else None,
                     executable_size=len(exe)),
        "game_dtz": {"lba": disc.files["CHK/PS2/GAME.DTZ"][0], "size": len(disc.dtz),
                     "sha256": hashlib.sha256(disc.dtz).hexdigest(), "gtag_size": len(disc.game.b),
                     "model_infos": disc.game.u32(0x20 + 0x18)},
        "img": {"path": "MODELS/GTA3PS2.IMG", "lba": disc.img_lba, "size": disc.img_size},
        "containers": containers(disc.files),
        "special_models": {"count": len(specials), "roles": dict(roles), "kinds": dict(kinds), "entries": specials},
        "ped_model_infos": {"count": len(peds), "entries": peds},
        "cutscene_anims": {"dir": "ANIM/CUTS.DIR", "img": "ANIM/CUTS.IMG", "count": len(cuts),
                           "by_extension": dict(cut_ext), "entries": cuts},
        "replacement_target": {"slot": "player (model index 0)", "loaded_from": "special-model directory by name",
                               "story_start_outfit": "plr3", "writer": "gbox.gta_stories_models.build_mod"},
        "launch": {"core": "retroarch/pcsx2", "requires": ["PS2 BIOS on the worker", "plain 2048-byte ISO "
                   "(chdman extractcd of the CHD, MODE1 single track)"], "vmode": cnf["vmode"]},
        "blockers": blockers,
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("iso")
    ap.add_argument("--rom")
    ap.add_argument("--out")
    ap.add_argument("--no-hash", action="store_true")
    a = ap.parse_args(argv)
    m = inventory(Path(a.iso), Path(a.rom) if a.rom else None, hash_images=not a.no_hash)
    text = json.dumps(m, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
