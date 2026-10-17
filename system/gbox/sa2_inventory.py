"""Sonic Adventure 2 (Dreamcast, USA) inventory: GD-ROM layout, executable identity and the per-character
model / texture / motion files that a native character replacement has to touch.

Layout (owned CHD -> chdman extractcd -> disc.gdi, read with gbox.gdrom.GDRom):
  * IP.BIN at LBA 45000: MK-51117 V1.008 2001-05-29, boot file 1ST_READ.BIN (SH-4, loads at 0x8C010000).
  * SONIC2/<KEY>MDL.PRS  PRS -> table {s32 id, u32 NJS_OBJECT file offset} ended by id -1 (gbox.sa2_chars).
  * SONIC2/<KEY>TEX.PRS  PRS -> PVM; its order is the model's Ninja texture-id order.
  * SONIC2/<KEY>MTN.PRS  PRS -> table {s16 motion id, s16 node count, u32 NJS_MOTION file offset} ended by id -1.
    A motion only drives a model whose tree has the same node count, so `node count == model nodes` is the
    animation-mapping precondition for any donor written into that slot.
Variant model files (B*/H*/X*/PSO* prefixes) have no motion file of their own; they are reported with the base
character whose MTN they would have to share (`motion_key`), and the node-count check says whether they can.

    python -m gbox.sa2_inventory DISC.gdi --sha256 <owned CHD sha256> --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

from .sa1_inventory import classify as _sa1_classify, ip_info

KEY = 0x8C010000                       # 1ST_READ.BIN load address
GAME_ID = "d95ed7ed1e40552a"
PRODUCT, VERSION = "MK-51117", "V1.008"

# model key -> (name, motion key). Roster keys match gbox.characters.SA2_CHARS (the collection reader).
CHARACTERS = {
    "SONIC": ("Sonic", "SONIC"), "TERIOS": ("Shadow", "TERIOS"), "MILES": ("Tails", "MILES"),
    "KNUCK": ("Knuckles", "KNUCK"), "ROUGE": ("Rouge", "ROUGE"), "EGG": ("Dr. Eggman", "EGG"),
    "AMY": ("Amy Rose", "AMY"), "METALSONIC": ("Metal Sonic", "METALSONIC"), "TICAL": ("Tikal", "TICAL"),
    "CHAOS0": ("Chaos 0", "CHAOS0"), "SSONIC": ("Super Sonic", "SSONIC"), "SSHADOW": ("Super Shadow", "SSHADOW"),
    "TWALK": ("Cyclone (Tails walker)", "TWALK"), "EWALK": ("Egg Walker", "EWALK"),
    "CWALK": ("Chao walker", "CWALK"),
}
VARIANT_PREFIXES = ("PSO", "B", "H", "X")   # longest first
BASE_ALIAS = {"SHADOW": "TERIOS", "TWALK1": "TWALK", "EWALK1": "EWALK"}


def classify(name: str) -> str:
    base = name.rsplit("/", 1)[-1].upper()
    if base.endswith("MDL.PRS"):
        return "character_model"
    if base.endswith("MTN.PRS"):
        return "character_motion"
    if "/EVENT/" in name.upper():
        return "event"
    return _sa1_classify(name)


def model_key_family(stem: str) -> tuple[str, str | None]:
    """'HSONIC' -> ('SONIC', 'H'); 'PSOSHADOW' -> ('TERIOS', 'PSO'); 'SONIC' -> ('SONIC', None)."""
    if stem in CHARACTERS:
        return stem, None
    if stem in BASE_ALIAS:
        return BASE_ALIAS[stem], None
    for p in VARIANT_PREFIXES:
        if stem.startswith(p) and len(stem) > len(p):
            rest = BASE_ALIAS.get(stem[len(p):], stem[len(p):])
            if rest in CHARACTERS:
                return rest, p
    return stem, None


def id_table(data: bytes, fmt: str) -> list[tuple]:
    """Read a -1-terminated little-endian id table ('<iI' for MDL, '<hhI' for MTN)."""
    out, o, step = [], 0, struct.calcsize(fmt)
    while o + step <= len(data):
        row = struct.unpack_from(fmt, data, o)
        o += step
        if row[0] == -1:
            return out
        if not 0 <= row[-1] < len(data):
            raise ValueError(f"table entry {row[0]} points outside the file (0x{row[-1]:X} >= 0x{len(data):X})")
        out.append(row)
    raise ValueError("table has no -1 terminator")


def motion_table(data: bytes) -> dict[int, tuple[int, int]]:
    """{motion id: (node count, offset)}."""
    return {i: (n, p) for i, n, p in id_table(data, "<hhI")}


def model_summary(mdl: bytes) -> dict:
    """Full model = the most triangles among the first four ids (the rest are LODs / parts), as the collection
    reader picks it (gbox.characters._sa2_run)."""
    from . import sa2_chars
    table = dict(id_table(mdl, "<iI"))
    stats = {}
    for i in sorted(table)[:4]:
        try:
            nj = sa2_chars.load_object(mdl, table[i])
        except Exception:                                  # noqa: BLE001 - a part, not a tree
            continue
        stats[i] = {"nodes": len(nj.bones), "tris": sum(len(v) for v in nj.tris.values()),
                    "texture_ids": sorted(nj.tris)}
    full = max(stats, key=lambda i: stats[i]["tris"]) if stats else None
    return {"ids": sorted(table), "full_model_id": full, **(stats.get(full) or {})}


def _file(g, path: str) -> tuple[bytes, dict]:
    raw = g.read(path)
    return raw, {"path": path, "compressed": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def characters(g, files: dict) -> dict:
    from .ninja import prs_decompress, pvm
    stems = sorted(n[len("SONIC2/"):-len("MDL.PRS")] for n in files
                   if n.startswith("SONIC2/") and n.count("/") == 1 and n.endswith("MDL.PRS"))
    motions = {}
    out = {}
    for stem in stems:
        base, variant = model_key_family(stem)
        raw, mdl = _file(g, f"SONIC2/{stem}MDL.PRS")
        body = prs_decompress(raw)
        mdl.update(size=len(body), **model_summary(body))
        entry = {"name": CHARACTERS.get(base, (stem,))[0] + (f" ({variant} variant)" if variant else ""),
                 "base": base, "variant": variant, "model": mdl}
        tpath = f"SONIC2/{stem}TEX.PRS"
        if tpath in files:
            traw, tex = _file(g, tpath)
            tbody = prs_decompress(traw)
            names = [n for n, _ in pvm(tbody)] if tbody[:4] == b"PVMH" else []
            tex.update(size=len(tbody), magic=tbody[:4].decode("latin-1"), count=len(names), names=names)
            entry["textures"] = tex
        mkey = CHARACTERS.get(base, (None, None))[1]
        mpath = f"SONIC2/{mkey}MTN.PRS" if mkey else None
        if mpath and mpath in files:
            if mkey not in motions:
                mraw, mtn = _file(g, mpath)
                mbody = prs_decompress(mraw)
                t = motion_table(mbody)
                mtn.update(size=len(mbody), count=len(t), node_counts=sorted({n for n, _ in t.values()}))
                motions[mkey] = mtn
            entry["motion_key"] = mkey
            entry["motion"] = {"path": mpath, "node_counts": motions[mkey]["node_counts"],
                               "matches_model": mdl.get("nodes") in motions[mkey]["node_counts"]}
        out[stem] = entry
    return {"models": out, "motion_files": motions}


def inventory(gdi: str | Path, source_sha256: str | None = None) -> dict:
    from .gdrom import GDRom
    g = GDRom(gdi)
    hd = min(t[0] for t in g.tracks if t[0] >= 45000)
    ip = ip_info(g.sector(hd))
    files = {n: {"lba": lba, "size": size, "kind": classify(n)} for n, (lba, size) in sorted(g.files.items())}
    kinds: dict[str, int] = {}
    for f in files.values():
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    exe = g.read(ip["boot"] or "1ST_READ.BIN")
    chars = characters(g, files)
    plcom = files.get("SONIC2/PLCOMMTN.PRS")
    return {
        "game": "Sonic Adventure 2 (USA)", "game_id": GAME_ID, "platform": "dreamcast",
        "source_sha256": source_sha256, "ip": ip,
        "build_matches_writer": ip["product"] == PRODUCT and ip["version"] == VERSION,
        "tracks": [{"lba": s, "sector": z, "file": Path(p).name} for s, z, p in g.tracks],
        "file_count": len(files), "kinds": kinds,
        "executable": {"name": ip["boot"], "size": len(exe), "sha256": hashlib.sha256(exe).hexdigest(),
                       "load_address": f"0x{KEY:08X}"},
        "shared_motion": {"path": "SONIC2/PLCOMMTN.PRS", **plcom} if plcom else None,
        **chars, "files": files,
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--sha256", help="sha256 of the owned source (CHD) to record")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = json.dumps(inventory(a.gdi, a.sha256), indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
