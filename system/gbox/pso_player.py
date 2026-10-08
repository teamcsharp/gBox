"""Phantasy Star Online Ver.2 (Dreamcast) player characters -> one skinned model (body + head) with its colour textures.

Disc layout (US 2OEF, found by gBox): per class a letter A..I (class id 0..8: HUmar, HUnewearl, HUcast, RAmar, RAcast,
RAcaseal, FOmarl, FOnewm, FOnewearl): PSO/PL<x>NJ.BML (plXbdy00.nj body + plXhedNN.nj heads; the same models also lie
loose as PSO/PL<x>BDY00.NJ, PL<x>HEDNN.NJ) and PSO/PL<x>TEX.AFS (PVR textures, no names).

The body is one weighted Ninja chunk model (64 nodes for HUcast). Its polygon lists are cached (chunk bits 4) and drawn
from a later node (bits 5) once every bone has written its share of the weighted vertices; gbox.ninja handles that.
Heads are separate one-node models drawn at the neck mount node (HUcast: node 59, identity rotation at the neck).

HUcast (PLC) texture layout in PLCTEX.AFS (110 PVRs), matched by drawing each texture id's UV layout over the images:
  0..44   9 colours x 5: torso, legs/upper parts, limbs, hands (64x64), glow (32x32)
          colours: 0 red, 1 blue, 2 yellow, 3 green, 4 purple, 5 black, 6 white, 7 navy, 8 brown
          body Ninja tex ids: 0 = section ID emblem quad (AFS 99 + section id), 1..4 = AFS 5 * colour + 0..3
  45..62  head 0: 9 colours x 2 (head tex 0 = head, tex 1 = visor glow)
  63..71, 72..80, 81..89  heads 1..3: one texture per colour (63 + 9 * (head - 1) + colour); 90..98 head 4 (unverified)
  99..108 section ID emblems (Viridia .. Whitill), 109 blank
The appearance in a character save (newserv PlayerVisualConfig): class u8 +0x31, costume u16 +0x38, skin +0x3A,
face +0x3C, head +0x3E, hair +0x40 (TObjPlayer + 0xC24 holds this block live on DC, after the 0x24-byte stats).
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import ninja, uap

CLASSES = ["HUmar", "HUnewearl", "HUcast", "RAmar", "RAcast", "RAcaseal", "FOmarl", "FOnewm", "FOnewearl"]
HUCAST_COLOURS = ["red", "blue", "yellow", "green", "purple", "black", "white", "navy", "brown"]
HEAD_MOUNT = {"C": 59}


def afs(data: bytes) -> list[bytes]:
    n = struct.unpack_from("<I", data, 4)[0]
    return [data[o:o + s] for o, s in (struct.unpack_from("<II", data, 8 + 8 * i) for i in range(n))]


SECTION_IDS = ["Viridia", "Greenill", "Skyly", "Bluefull", "Purplenum", "Pinkal", "Redria", "Oran", "Yellowboze", "Whitill"]


def hucast_textures(colour: int, head: int, section_id: int = 7) -> tuple[list[int], list[int]]:
    """AFS entry per Ninja texture id: (body ids 0..4, head ids)."""
    body = [99 + section_id] + [5 * colour + t for t in range(4)]
    if head == 0:
        hd = [45 + 2 * colour, 46 + 2 * colour]
    elif head in (1, 2, 3):
        hd = [63 + 9 * (head - 1) + colour, 5 * colour + 4]
    else:
        hd = [90 + colour, 5 * colour + 4]
    return body, hd


def _mat_point(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3)]


def _mat_dir(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] for i in range(3)]


def build(disc, cls: str = "C", head: int = 0, colour: int = 0, out_dir: Path | None = None, name: str | None = None,
          section_id: int = 7):
    """-> uap.Manifest (textures written as PNGs under out_dir/textures). disc: a gbox.gdrom.GDRom."""
    cls = cls.upper()
    body_nj = ninja.NJ(disc.read(f"PSO/PL{cls}BDY00.NJ"))
    head_nj = ninja.NJ(disc.read(f"PSO/PL{cls}HED{head:02d}.NJ"))
    mount = HEAD_MOUNT.get(cls, 59)
    mw = body_nj.bones[mount]["m"]
    # put the head's triangles into the body as extra texture ids (100 + id), moved to the mount, weighted to it
    for tex, tris in head_nj.tris.items():
        out = body_nj.tris.setdefault(100 + tex, [])
        for tri in tris:
            c2 = []
            for vi, t, *snap in tri:
                v = snap[0] if snap and snap[0] else head_nj.vbuf.get(vi)
                if v is None:
                    break
                c2.append((vi, t, {"pos": _mat_point(mw, v["pos"]), "nrm": _mat_dir(mw, v["nrm"]) if v["nrm"] else None,
                                   "joints": [(mount, 1.0)]}))
            else:
                out.append(tuple(c2))
    name = name or f"pso_{CLASSES['ABCDEFGHI'.index(cls)].lower()}_h{head}_c{colour}"
    tex_files: list[str | None] = [None] * 102
    if out_dir is not None:
        ents = afs(disc.read(f"PSO/PL{cls}TEX.AFS"))
        if cls == "C":
            b_ids, h_ids = hucast_textures(colour, head, section_id)
        else:                                               # ponytail: other classes' AFS layouts not mapped yet
            b_ids, h_ids = list(range(5)), []
        (Path(out_dir) / "textures").mkdir(parents=True, exist_ok=True)
        for slot, idx in [(t, i) for t, i in enumerate(b_ids)] + [(100 + t, i) for t, i in enumerate(h_ids)]:
            w, h, rgba, _ = ninja.pvr_decode(ents[idx])
            rel = f"textures/afs{idx:03d}.png"
            (Path(out_dir) / rel).write_bytes(ninja.png(w, h, rgba))
            tex_files[slot] = rel
    m = ninja.to_manifest(body_nj, name, {"game": "Phantasy Star Online Ver.2 (DC, US)", "class": cls, "head": head,
                                          "colour": colour, "section_id": section_id, "files": [f"PSO/PL{cls}BDY00.NJ", f"PSO/PL{cls}HED{head:02d}.NJ",
                                                                      f"PSO/PL{cls}TEX.AFS"],
                                          "extraction_method": "gbox.pso_player"}, tex_files)
    m.unit_scale_m = 0.1
    return m


def export(gdi: str, out_dir: str, cls: str = "C", head: int = 0, colour: int = 0, section_id: int = 7) -> Path:
    from .gdrom import GDRom
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = build(GDRom(gdi), cls, head, colour, out, section_id=section_id)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{m.name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


# ---------------------------------------------------------------- writer: a collection character as the player's class

GAME_IDS = {"daba7a3b195dcf6b": "Phantasy Star Online Ver. 2 (USA)"}
# Body roles per class letter = node indices of PL<x>BDY00.NJ (HUcast and HUmar share the 64-node layout). The
# character replaces the body; the head, hair and cap files (PL<x>HED / HAI / CAP*.NJ, loose and in PL<x>NJ.BML)
# become an invisible speck so the class head doesn't sit on top. Its textures are one atlas, written into EVERY
# texture of PL<x>TEX.AFS in that texture's own size and format (which AFS entry the game binds depends on the
# costume / colour, mapped for HUcast only), so the AFS keeps its layout.
_HU_ROLES = {"hip": 2, "chest": 25, "head": 56, "l_upper": 28, "l_fore": 29, "l_hand": 34, "r_upper": 41,
                     "r_fore": 42, "r_hand": 47, "l_thigh": 4, "l_shin": 5, "l_foot": 8, "r_thigh": 13, "r_shin": 14,
                     "r_foot": 17}
CLASS_ROLES = {"A": _HU_ROLES, "C": _HU_ROLES}
PSO_BUDGETS = (900, 750, 600, 480, 400)


def bml_files(data: bytes) -> list[dict]:
    """BML entries with their header fields: [{name, raw (compressed), fields (5 x u32), tex_raw}]."""
    n = struct.unpack_from("<I", data, 4)[0]
    out, off = [], 0x800
    for i in range(n):
        h = 0x40 + 0x40 * i
        csize, f1, dsize, cgvm, dgvm = struct.unpack_from("<5I", data, h + 0x20)
        raw = data[off:off + csize]
        off = (off + csize + 0x1F) & ~0x1F
        tex = None
        if cgvm:
            tex = data[off:off + cgvm]
            off = (off + cgvm + 0x1F) & ~0x1F
        out.append({"name": data[h:h + 0x20], "raw": raw, "fields": [csize, f1, dsize, cgvm, dgvm], "tex": tex})
    return out


def bml_build(data: bytes, replace: dict[str, bytes]) -> bytes:
    """The BML with entries {lower-case name: new decompressed file} recompressed (PRS); the rest kept as is."""
    ents = bml_files(data)
    head = bytearray(data[:0x800])
    body = bytearray()
    for i, e in enumerate(ents):
        nm = e["name"].split(b"\0")[0].decode("latin-1").lower()
        raw, f = e["raw"], list(e["fields"])
        if nm in replace:
            raw = ninja.prs_compress(replace[nm])
            f[0], f[2] = len(raw), len(replace[nm])
        struct.pack_into("<5I", head, 0x40 + 0x40 * i + 0x20, *f)
        body += raw + bytes((-len(raw)) % 0x20)
        if e["tex"] is not None:
            body += e["tex"] + bytes((-len(e["tex"])) % 0x20)
    return bytes(head + body)


def nj_file(data: bytes, ptrs: list[int]) -> bytes:
    return b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs)


def speck_nj() -> bytes:
    """A one-node NJ with one zero-size triangle: a valid, invisible model (stands in for the class head)."""
    import numpy as np
    vl, pl, c, r = ninja.cnk_model_lists(np.zeros((3, 3)), np.tile([0, 1.0, 0], (3, 1)), [((0, 1, 2), ((0, 0),) * 3)],
                                         0, b"")
    nd = [{"flags": 0x17, "trs": struct.pack("<3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": None}]
    data, _root, ptrs = ninja.write_tree(nd, {0: (vl, pl, c, r)}, 0)
    return nj_file(data, ptrs)


def build_swap(disc, model: Path, roles: dict, work: Path, name: str, cls: str = "C", blender: str | None = None,
               progress=lambda p, m: None, scale: dict | None = None) -> dict:
    """disc: a gbox.gdrom.GDRom. -> {files {disc path: bytes}, report, rigged, atlas}."""
    import numpy as np
    from . import ninja_swap as NS
    cls = cls.upper()
    if cls not in CLASS_ROLES:
        raise ValueError(f"class {CLASSES['ABCDEFGHI'.index(cls)]} has no body roles yet (HUmar, HUcast)")
    bpath, mpath, tpath = f"PSO/PL{cls}BDY00.NJ", f"PSO/PL{cls}NJ.BML", f"PSO/PL{cls}TEX.AFS"
    body_file = disc.read(bpath)
    data = body_file[8:8 + struct.unpack_from("<I", body_file, 4)[0]]
    nodes = ninja.tree_nodes(data, 0)
    nj = ninja.NJ(body_file)
    tgt = NS.target_from_nj(nj, CLASS_ROLES[cls], set(range(CLASS_ROLES[cls]["head"], len(nodes))))
    mat, tiny_fl, tex_fl, strip_fl = b"", 0x34, 0x4000, 0x12
    for nd in nodes:                                         # the body's own render state (first material + texture)
        if nd["model"] and struct.unpack_from("<I", data, nd["model"] + 4)[0]:
            o = struct.unpack_from("<I", data, nd["model"] + 4)[0]
            for _ in range(64):
                h = struct.unpack_from("<H", data, o)[0]
                t = h & 0xFF
                if t == 0xFF:
                    break
                if 0x10 <= t <= 0x3A:
                    mat = mat or data[o:o + 4 + struct.unpack_from("<H", data, o + 2)[0] * 2]
                    o += 4 + struct.unpack_from("<H", data, o + 2)[0] * 2
                elif t in (8, 9):
                    tiny_fl, tex_fl = h >> 8, struct.unpack_from("<H", data, o + 2)[0] & 0xE000
                    o += 4
                elif 0x40 <= t <= 0x4B:
                    strip_fl = (h >> 8) | 0x10
                    break
                else:
                    o += 2
            if mat:
                break
    bml = disc.read(mpath)
    extras_bml = [n for n in (e["name"].split(b"\0")[0].decode("latin-1").lower() for e in bml_files(bml))
                  if n[3:6] in ("hed", "hai", "cap")]
    bml_sec = (disc.files[mpath][1] + 2047) // 2048
    nj_sec = (disc.files[bpath][1] + 2047) // 2048

    vbase = (max(nj.vbuf) + 1 + 15) & ~15 if nj.vbuf else 0

    def keep_vl(nd):                                         # the node's original vertex chunks, end chunk dropped
        if not nd["model"]:
            return b""
        vl = struct.unpack_from("<I", data, nd["model"])[0]
        return data[vl:vl + ninja.chunk_list_len(data, vl, "v") - 4] if vl else b""

    def encode(geo):
        # Like SA2 (gbox.sa2_chars), the game needs the body's original (weighted) vertex chunks: without them it
        # draws garbage. Every node keeps its vertex chunks, the character's vertices follow from cache slot vbase,
        # and only the strips change.
        models = {}
        empty_pl = struct.pack("<HH", 0xFF, 0)
        for j, nd in enumerate(nodes):
            keep = keep_vl(nd)
            if j in geo:
                P, N, T = geo[j]
                models[j] = ninja.cnk_model_lists(P, N, T, 1, mat, tiny_fl, tex_fl, strip_fl, base=vbase, keep_vlist=keep)
            elif nd["model"]:
                c_r = struct.unpack_from("<4f", data, nd["model"] + 8)
                models[j] = (keep + struct.pack("<I", 0xFF) if keep else b"", empty_pl, list(c_r[:3]), c_r[3])
        nn = [dict(nd) for nd in nodes]
        for j in geo:
            nn[j]["flags"] &= ~0x8
        d2, _root, ptrs = ninja.write_tree(nn, models, 0)
        f = nj_file(d2, ptrs)
        if len(f) > 64 * 2048:                               # patch_gdi moves it after the last file if it grew
            raise ValueError(f"{bpath}: {len(f)} bytes")
        b2 = bml_build(bml, {f"pl{cls.lower()}bdy00.nj": f} | {n: speck_nj() for n in extras_bml})
        if len(b2) > 64 * 2048:
            raise ValueError(f"{mpath}: {len(b2)} bytes")
        return f, b2
    progress(20, f"Fitting {name} to the {CLASSES['ABCDEFGHI'.index(cls)]} body ({len(nodes)} nodes)")
    r = NS.fit(model, roles, tgt, work, name, PSO_BUDGETS, blender, encode, 128, scale, progress)
    body_nj, bml2 = r["data"]
    afs_data = bytearray(disc.read(tpath))
    n = struct.unpack_from("<I", afs_data, 4)[0]
    tab = [struct.unpack_from("<II", afs_data, 8 + 8 * i) for i in range(n)]
    progress(85, f"Writing the atlas into {n} class textures")
    done = 0
    for k, (off, size) in enumerate(tab):                    # every texture, in its own size and format
        try:
            chunk = ninja.pvr_like(bytes(afs_data[off:off + size]), r["atlas"])
        except ValueError:
            continue
        if len(chunk) <= size:
            afs_data[off:off + size] = chunk + bytes(size - len(chunk))
            done += 1
    files = {bpath: body_nj, mpath: bml2, tpath: bytes(afs_data)}
    for hp in disc.files:
        if hp.startswith(f"PSO/PL{cls}") and hp[7:10] in ("HED", "HAI", "CAP") and hp.endswith(".NJ"):
            files[hp] = speck_nj()
    rep = r["report"] | {"body_bytes": len(body_nj), "bml_bytes": len(bml2), "atlas": list(r["atlas"].size),
                         "textures_replaced": done}
    return {"files": files, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def build_mod(cfg, meta: dict, game: dict, gdi: Path, cls: str = "A", progress=lambda p, m: None,
              root: Path | None = None, name: str | None = None) -> dict:
    import json
    import shutil
    import time
    from . import characters as C, filemods
    from .gdrom import GDRom, patch_gdi
    root = root or C.library_root(cfg)
    gid, name = game["game_id"], name or f"pso_{meta['slug']}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json)")
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "pso"
    shutil.rmtree(work, ignore_errors=True)
    b = build_swap(GDRom(gdi), root / meta["slug"] / meta["model"], roles, work, meta["name"], cls, C._blender(cfg),
                   progress, (meta.get("rig") or {}).get("scale"))
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b["rigged"], tdir / f"pso_{cls.lower()}.gltf")
    b["atlas"].save(tdir / "pso_atlas.png")
    C.render_preview(tdir / f"pso_{cls.lower()}.gltf", tdir / "pso_preview.png")
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    img = patch_gdi(gdi, d, name, b["files"], progress)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, "image": img.name, "built": time.time(),
                                                  "files": sorted(b["files"]), "character": meta["slug"], "class": cls,
                                                  "report": json.loads(json.dumps(b["report"], default=str))}))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img.name, "report": b["report"]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for PSO Ver.2 (DC): the character replaces the body of the operator's class (HUmar: their
    character GBOX; slot=hucast for HUcast), offline play only; built on the control plane (pso_<slug>), launched."""
    from . import characters as C, filemods
    if not getattr(inp, "rebuild", False) or (inp.slot or "") != "experimental":
        return {"status": "not_working", "mod": None,
                "message": "The PSO Ver.2 writer (gbox.pso_player.build_swap) builds the files, but the game doesn't draw "
                           "them yet: with the class body's weighted vertex chunks replaced by rigid ones it draws garbage "
                           "(menus) or nothing (Pioneer 2), and keeping the original chunks makes PL<x>BDY00.NJ too big "
                           "for its 11 sectors (moved files crash Flycast). See docs/model_swaps.md (PSO). "
                           "characters op=overlay draws the character over the player instead.",
                "class": "HUmar (the operator's character GBOX)"}
    cls = "C" if (inp.slot or "").lower() in ("hucast", "c") else "A"
    gid, name = game["game_id"], f"pso_{meta['slug']}" + ("_hucast" if cls == "C" else "")
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if inp.rebuild or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("PSO swaps are built on the control-plane node (the Spark): run this there")
        built = build_mod(ctx.config, meta, game, C._dc_gdi(ctx, game), cls, ctx.progress, name=name)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces the {CLASSES['ABCDEFGHI'.index(cls)]} body (every costume; "
                              f"{built['report']['triangles']} triangles); offline play only; preview targets/pso_preview.png"})
    out = {"mod": name, "build": built, "replaces": f"the {CLASSES['ABCDEFGHI'.index(cls)]} class body (offline play only)"}
    if not inp.launch:
        return out | {"status": "built" if built else "ready"}
    l = C._launch(ctx, gid, name, C.HOST_OS)
    return out | {"status": "built+launched" if built else "launched", "launch": l}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--cls", default="C")
    ap.add_argument("--head", type=int, default=0)
    ap.add_argument("--colour", type=int, default=0)
    ap.add_argument("--section", type=int, default=7)
    a = ap.parse_args()
    print(export(a.gdi, a.out, a.cls, a.head, a.colour, a.section))
