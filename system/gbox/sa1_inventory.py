"""Sonic Adventure (Dreamcast) inventory: disc layout, character texture archives and the basic-model (NJS_MODEL)
character trees embedded in 1ST_READ.BIN.

SA1 predates the chunk models SA2 uses: its objects are the classic 0x34-byte NJS_OBJECT pointing to a 0x28-byte
"basic" NJS_MODEL (points, normals, nbPoint, meshsets, mats, nbMeshset, nbMat, center, r), whose 0x18-byte
NJS_MESHSETs reference 0x14-byte NJS_MATERIALs (texture id in the low bits of attr_texId). `gbox.ninja.NJ` only
walks chunk (NJCM) trees, so this module carries its own small basic-model walker.

Pointers inside 1ST_READ.BIN are absolute SH-4 addresses with the executable loaded at 0x8C010000. Character
textures ship as PRS-compressed PVM archives (SONIC.PRS, MILES.PRS, ...).

    python -m gbox.sa1_inventory DISC.gdi --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

KEY = 0x8C010000                     # 1ST_READ.BIN load address
OBJ_SIZE, MODEL_SIZE, MESHSET_SIZE, MAT_SIZE = 0x34, 0x28, 0x18, 0x14

# playable characters -> texture archive(s) on disc (SONICADV/<name>.PRS, PRS-compressed PVM)
CHARACTERS = {
    "sonic": ["SONIC"], "super_sonic": ["SUPERSONIC"], "tails": ["MILES"], "knuckles": ["KNUCKLES"],
    "amy": ["AMY"], "big": ["BIG"], "e102": ["E102"], "tikal": ["TIKAL"], "eggman": ["EGGMAN"],
}


def ip_info(sector0: bytes) -> dict:
    """Dreamcast IP.BIN header fields (first 256 bytes of the high-density area)."""
    f = lambda a, b: sector0[a:b].decode("latin-1").strip()
    return {"hardware": f(0, 16), "maker": f(16, 32), "device": f(32, 48), "area": f(48, 56),
            "peripherals": f(56, 64), "product": f(64, 74), "version": f(74, 80), "date": f(80, 96),
            "boot": f(96, 112), "company": f(112, 128), "title": f(128, 256)}


def classify(name: str) -> str:
    base = name.rsplit("/", 1)[-1].upper()
    stem, _, ext = base.rpartition(".")
    if base == "1ST_READ.BIN":
        return "executable"
    if ext == "PRS":
        return "prs"                 # PRS-compressed: PVM texture archives, level/object models
    if ext in ("ADX", "MLT", "WAV", "AIF", "SFD", "RAW"):
        return "audio_video"
    if ext in ("GIF", "JPG", "HTM", "PMT", "PMN", "IDX", "DAT", "DRV", "NB", "PB"):
        return "web_browser"         # the bundled Dreamarena browser
    if re.match(r"(SET|CAM)", stem):
        return "stage_layout"        # object SET / camera tables
    if re.match(r"(PL|SL)_?[0-9A-Z]{2,3}$", stem):
        return "stage_lighting"
    if ext == "BIN":
        return "binary"
    if ext == "PVR":
        return "texture"
    return "other"


# ------------------------------------------------------------------ basic-model tree scan in the executable

class Exe:
    def __init__(self, data: bytes, key: int = KEY):
        self.d, self.key = data, key

    def ok(self, p: int, size: int = 4, align: int = 4) -> bool:
        return self.key <= p and p + size <= self.key + len(self.d) and p % align == 0

    def u(self, fmt: str, p: int):
        return struct.unpack_from("<" + fmt, self.d, p - self.key)

    def model(self, p: int) -> dict | None:
        """Validate a basic NJS_MODEL at address p; None when it isn't one."""
        if not self.ok(p, MODEL_SIZE):
            return None
        pts, nrm, n, msets, mats, nms, nmat = self.u("IIiIIHH", p)
        r = self.u("f", p + 0x24)[0]
        if not (0 < n < 20000 and self.ok(pts, n * 12) and (nrm == 0 or self.ok(nrm, n * 12))):
            return None
        if not (0 < nms < 512 and self.ok(msets, nms * MESHSET_SIZE)) or nmat > 512:
            return None
        if nmat and not self.ok(mats, nmat * MAT_SIZE):
            return None
        if not (r == r and 0 <= r < 1e5):
            return None
        tex, tris = set(), 0
        for i in range(nms):
            tm, nmesh, meshes = self.u("HHI", msets + i * MESHSET_SIZE)
            mat, kind = tm & 0x3FFF, tm >> 14
            if nmat and mat < nmat:
                tex.add(self.u("I", mats + mat * MAT_SIZE + 12)[0] & 0x3FFF)
            tris += nmesh if kind in (0, 1) else 0
        return {"points": n, "meshsets": nms, "materials": nmat, "textures": sorted(tex), "radius": round(r, 3)}

    def obj(self, p: int) -> tuple | None:
        """(flags, model, child, sibling) when p looks like an NJS_OBJECT, else None."""
        if not self.ok(p, OBJ_SIZE):
            return None
        flags, model = self.u("II", p)
        pos, scl = self.u("3f", p + 8), self.u("3f", p + 0x20)
        child, sib = self.u("II", p + 0x2C)
        if flags & ~0xFF or any(v != v or abs(v) > 1e5 for v in pos + scl):
            return None
        for q in (model, child, sib):
            if q and not self.ok(q):
                return None
        if model and self.model(model) is None:
            return None
        return flags, model, child, sib

    def tree(self, root: int, limit: int = 512) -> list[dict] | None:
        """Depth-first node list [{addr, parent, model}] or None if any link fails validation."""
        out, stack, seen = [], [(root, -1)], set()
        while stack:
            p, parent = stack.pop()
            while p:
                if p in seen or len(out) >= limit:
                    return None
                o = self.obj(p)
                if o is None:
                    return None
                seen.add(p)
                me = len(out)
                out.append({"addr": p, "parent": parent, "model": o[1]})
                if o[3]:
                    stack.append((o[3], parent))
                p, parent = o[2], me
        return out


def scan_trees(data: bytes, key: int = KEY, min_nodes: int = 8) -> list[dict]:
    """Find root NJS_OBJECT trees: valid objects with scl 1,1,1 that are nobody's child/sibling."""
    ex = Exe(data, key)
    one = struct.pack("<3f", 1, 1, 1)
    cands, linked = [], set()
    i = data.find(one, 0x20)
    while i >= 0:
        p = key + i - 0x20
        if p % 4 == 0:
            o = ex.obj(p)
            if o:
                cands.append(p)
                linked.update(q for q in (o[2], o[3]) if q)
        i = data.find(one, i + 4)
    trees = []
    for p in cands:
        if p in linked:
            continue
        t = ex.tree(p)
        if not t or len(t) < min_nodes:
            continue
        models = [ex.model(n["model"]) for n in t if n["model"]]
        tex = sorted({x for m in models for x in m["textures"]})
        trees.append({"addr": f"0x{p:08X}", "file_offset": p - key, "nodes": len(t),
                      "models": len(models), "points": sum(m["points"] for m in models),
                      "meshsets": sum(m["meshsets"] for m in models), "textures": tex,
                      "parents": [n["parent"] for n in t]})
    trees.sort(key=lambda t: (-t["nodes"], t["file_offset"]))
    return trees


# ------------------------------------------------------------------ disc-level manifest

def texture_archive(raw: bytes) -> dict:
    from .ninja import prs_decompress, pvm
    body = prs_decompress(raw)
    out = {"compressed": len(raw), "size": len(body), "magic": body[:4].decode("latin-1")}
    if body[:4] == b"PVMH":
        names = [n for n, _ in pvm(body)]
        out.update(count=len(names), names=names)
    return out


def inventory(gdi: str | Path, source_sha256: str | None = None, scan: bool = True) -> dict:
    from .gdrom import GDRom
    g = GDRom(gdi)
    hd = min(t[0] for t in g.tracks if t[0] >= 45000)
    ip = ip_info(g.sector(hd))
    files = {}
    for name, (lba, size) in sorted(g.files.items()):
        files[name] = {"lba": lba, "size": size, "kind": classify(name)}
    counts: dict[str, int] = {}
    for f in files.values():
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    exe = g.read(ip["boot"] or "1ST_READ.BIN")
    chars = {}
    for slug, archives in CHARACTERS.items():
        chars[slug] = {}
        for a in archives:
            path = next((n for n in files if n.rsplit("/", 1)[-1].upper() == f"{a}.PRS"), None)
            if path:
                info = texture_archive(g.read(path))
                info["path"] = path
                info["sha256"] = hashlib.sha256(g.read(path)).hexdigest()
                chars[slug][a] = info
    man = {
        "game": "Sonic Adventure", "platform": "dreamcast", "source_sha256": source_sha256,
        "ip": ip, "tracks": [{"lba": s, "sector": z, "file": Path(p).name} for s, z, p in g.tracks],
        "file_count": len(files), "kinds": counts,
        "executable": {"name": ip["boot"], "size": len(exe), "sha256": hashlib.sha256(exe).hexdigest(),
                       "load_address": f"0x{KEY:08X}"},
        "characters": chars, "files": files,
    }
    if scan:
        trees = scan_trees(exe)
        counts = {a: i.get("count", 0) for c in chars.values() for a, i in c.items()}
        man["executable"]["basic_model_trees"] = [
            {**{k: v for k, v in t.items() if k != "parents"}, "texture_fits": texture_fits(t, counts)}
            for t in trees]
    return man


def texture_fits(tree: dict, counts: dict[str, int]) -> list[str]:
    """Character texture archives whose PVM is large enough for every texture id the tree uses. A necessary
    condition only: it narrows candidates, it does not identify the owner (that needs the code's texlist xref)."""
    top = max(tree["textures"], default=-1)
    return sorted(a for a, n in counts.items() if top < n)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--sha256", help="sha256 of the owned source (CHD) to record")
    ap.add_argument("--out")
    ap.add_argument("--no-scan", action="store_true")
    a = ap.parse_args(argv)
    man = inventory(a.gdi, a.sha256, scan=not a.no_scan)
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    sys.exit(main())
