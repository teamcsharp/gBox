"""Sonic Adventure 2 (Dreamcast, US) character models -> UAP / glTF (skinned Ninja chunk model + PVM textures).

SONIC2/<CHAR>MDL.PRS (e.g. SONICMDL.PRS) decompresses (PRS, gbox.ninja) to a little-endian table of
{s32 id, u32 NJS_OBJECT offset} ended by id -1; every pointer inside is a file offset. Id 0 is the full in-game model
(Sonic: 62 nodes, ~1370 triangles, weighted chunk vertices), 1..3 / 31.. / 48.. are lower detail versions and parts.
SONIC2/<CHAR>TEX.PRS decompresses to the PVM whose order matches the model's Ninja texture ids.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from . import ninja, uap

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def mdl_table(data: bytes) -> dict[int, int]:
    out, o = {}, 0
    while True:
        i, p = struct.unpack_from("<iI", data, o)
        o += 8
        if i == -1:
            return out
        out[i] = p


# SA2 characters face -X with +Y up; this turns them to face +Z (RE4 Leon, glTF viewers): (x, y, z) -> (z, y, -x)
FACE_Z = [[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]]


def load_object(data: bytes, off: int, be: bool = False, root=IDENTITY) -> ninja.NJ:
    """Walk an NJS_OBJECT tree at a file offset. root = a matrix applied to the whole model (folded into the root
    bone, so the skeleton and the bind-pose vertices stay consistent)."""
    nj = ninja.NJ.__new__(ninja.NJ)
    nj.e, nj.d, nj.bones, nj.vbuf, nj.tris, nj.tex, nj.plcache = (">" if be else "<"), data, [], {}, {}, 0, {}
    nj._walk(off, None, root)
    for b in nj.bones:
        if b["parent"] is None:                            # root bones: local = world (includes `root`)
            b["t"], b["r"] = [b["m"][0][3], b["m"][1][3], b["m"][2][3]], ninja._quat(b["m"])
    return nj


def export(gdi: str, out_dir: str, char: str = "SONIC", model_id: int = 0) -> Path:
    from .gdrom import GDRom
    disc = GDRom(gdi)
    mdl = ninja.prs_decompress(disc.read(f"SONIC2/{char}MDL.PRS"))
    tex = ninja.prs_decompress(disc.read(f"SONIC2/{char}TEX.PRS"))
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    files = []
    for name, chunk in ninja.pvm(tex):
        try:
            w, h, rgba, _ = ninja.pvr_decode(chunk)
            (out / "textures" / f"{name}.png").write_bytes(ninja.png(w, h, rgba))
            files.append(f"textures/{name}.png")
        except ValueError:
            files.append(None)
    nj = load_object(mdl, mdl_table(mdl)[model_id], root=FACE_Z)
    name = f"sa2_{char.lower()}_{model_id}"
    m = ninja.to_manifest(nj, name, {"game": "Sonic Adventure 2 (DC, US)", "files": [f"SONIC2/{char}MDL.PRS",
                                     f"SONIC2/{char}TEX.PRS"], "model_id": model_id,
                                     "extraction_method": "gbox.sa2_chars"}, files)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


# ---------------------------------------------------------------- writer: a collection character as the player

GAME_IDS = {"d95ed7ed1e40552a": "Sonic Adventure 2 (USA)"}
# Player model files: the full model (id 0) and its two lower-detail copies (31, 48) share Sonic's 62-node tree;
# the character replaces all three. Roles = node indices (FACE_Z: the model faces +Z, left = +X). The head goes on
# node 44 (the head bone; 47 / 49 below it are head variants the game may hide), with its hide flag cleared.
PLAYERS = {
    "SONIC": {"ids": (0, 31, 48), "atlas_slot": 5, "head_nodes": set(range(44, 54)),
              "roles": {"hip": 2, "chest": 33, "head": 44, "l_upper": 37, "l_fore": 38, "l_hand": 39, "r_upper": 56,
                        "r_fore": 57, "r_hand": 58, "r_thigh": 7, "r_shin": 9, "r_foot": 13, "l_thigh": 17,
                        "l_shin": 19, "l_foot": 23}},
}
BUDGETS = (1400, 1150, 950, 800, 650, 500)


def _first_material(mdl: bytes, nodes: list[dict]) -> tuple[bytes, int, int, int]:
    """The original model's first material chunk, tiny-chunk flags, texture flags and strip flags (render state)."""
    for nd in nodes:
        if not nd["model"]:
            continue
        pl = struct.unpack_from("<I", mdl, nd["model"] + 4)[0]
        o, mat, tiny = pl, b"", None
        while pl:
            h = struct.unpack_from("<H", mdl, o)[0]
            t = h & 0xFF
            if t == 0xFF:
                break
            if t in (8, 9):
                tiny = (h >> 8, struct.unpack_from("<H", mdl, o + 2)[0] & 0xE000)
                o += 4
            elif 0x10 <= t <= 0x3A:
                if not mat:
                    mat = mdl[o:o + 4 + struct.unpack_from("<H", mdl, o + 2)[0] * 2]
                o += 4 + struct.unpack_from("<H", mdl, o + 2)[0] * 2
            elif 0x40 <= t <= 0x4B:
                if tiny and mat:
                    return mat, tiny[0], tiny[1], (h >> 8) | 0x10      # + double sided
                o += 4 + struct.unpack_from("<H", mdl, o + 2)[0] * 2
            else:
                o += 2
    return b"", 0x34, 0x4000, 0x12


def build_swap(gdi: str | Path, model: Path, roles: dict, work: Path, name: str, char: str = "SONIC",
               blender: str | None = None, progress=lambda p, m: None, scale: dict | None = None,
               lod_remap: bool = True) -> dict:
    """-> {files {disc path: bytes} (<CHAR>MDL.PRS, <CHAR>TEX.PRS), report, rigged, atlas}. Every file must fit its
    old sectors on the disc (gbox.gdrom.patch_gdi); the model is decimated until both do."""
    from .gdrom import GDRom
    from . import ninja_swap as NS
    pl = PLAYERS[char]
    disc = GDRom(gdi)
    mpath, tpath = f"SONIC2/{char}MDL.PRS", f"SONIC2/{char}TEX.PRS"
    mdl = ninja.prs_decompress(disc.read(mpath))
    tex = ninja.prs_decompress(disc.read(tpath))
    msec = (disc.files[mpath][1] + 2047) // 2048
    tsec = (disc.files[tpath][1] + 2047) // 2048
    tab = mdl_table(mdl)
    main = tab[pl["ids"][0]]
    nj = load_object(mdl, main, root=FACE_Z)
    tgt = NS.target_from_nj(nj, pl["roles"], pl["head_nodes"])
    nodes = ninja.tree_nodes(mdl, main)
    mat, tiny_fl, tex_fl, strip_fl = _first_material(mdl, nodes)
    # The other table entries point INTO this tree (sub-trees: hands, upper body, ...), so its nodes are edited in
    # place: each node's model pointer -> the new geometry (or none), and the old models' bytes that no node outside
    # this tree uses are zeroed (they compress to nothing).
    mine = {nd["off"] for nd in nodes}
    # the lower-detail trees (31, 48) have the same node order: every table entry into them (their sub-trees too)
    # moves to the same node of the main tree, so their bytes are freed as well
    remap = {}
    for k in pl["ids"][1:] if lod_remap else ():
        if k in tab:
            lod = ninja.tree_nodes(mdl, tab[k])
            if len(lod) == len(nodes):
                remap.update({nd["off"]: nodes[i]["off"] for i, nd in enumerate(lod)})
    gone = mine | set(remap)
    tab2 = {k: remap.get(off, off) for k, off in tab.items()}
    others = [nd for k, off in tab2.items() if off not in gone for nd in ninja.tree_nodes(mdl, off)
              if nd["off"] not in gone]
    def model_ranges(nds):
        rs = []
        for nd in nds:
            if nd["model"]:
                vl, pl_ = struct.unpack_from("<II", mdl, nd["model"])
                rs.append((nd["model"], nd["model"] + 24))
                if vl:
                    rs.append((vl, vl + ninja.chunk_list_len(mdl, vl, "v")))
                if pl_:
                    rs.append((pl_, pl_ + ninja.chunk_list_len(mdl, pl_, "p")))
        return rs
    body = bytearray(mdl)
    lods = [nd for k in pl["ids"][1:] if lod_remap and k in tab for nd in ninja.tree_nodes(mdl, tab[k])]
    for a_, b_ in model_ranges(nodes + lods) + [(nd["off"], nd["off"] + 52) for nd in lods]:
        body[a_:b_] = bytes(b_ - a_)
    for nd in others:                                       # nodes still in use keep their structs
        body[nd["off"]:nd["off"] + 52] = mdl[nd["off"]:nd["off"] + 52]
    for nd in nodes:                                        # the main tree's node structs stay (edited in place)
        body[nd["off"]:nd["off"] + 52] = mdl[nd["off"]:nd["off"] + 52]
    freed = np.frombuffer(bytes(body), np.uint8) != np.frombuffer(mdl, np.uint8)
    for a_, b_ in model_ranges(nodes + lods) + [(nd["off"], nd["off"] + 52) for nd in lods]:
        if not body[a_:b_].strip(b"\0"):
            freed[a_:b_] = True
    holes, i = [], 0                                        # the freed byte runs: the new models go there first,
    while i < len(freed):                                   # so the file (and the game's buffer) doesn't grow
        if freed[i]:
            j = i
            while j < len(freed) and freed[j]:
                j += 1
            st_ = (i + 3) & ~3
            if j - st_ >= 32:
                holes.append([st_, j])
            i = j
        else:
            i += 1
    for a_, b_ in model_ranges(others):                     # shared with a node outside the tree: keep
        body[a_:b_] = mdl[a_:b_]
    slot = pl["atlas_slot"]

    def orig_vlist(nd):                                     # the node's vertex chunks without the end chunk
        if not nd["model"]:
            return b""
        vl = struct.unpack_from("<I", mdl, nd["model"])[0]
        return mdl[vl:vl + ninja.chunk_list_len(mdl, vl, "v") - 4] if vl else b""
    vbase = (max(nj.vbuf) + 1 + 15) & ~15 if nj.vbuf else 0

    def encode(geo):
        out = bytearray(body)
        out += bytes((-len(out)) % 32)
        free = [h[:] for h in holes]

        def alloc(blob):                                    # best fit into a freed hole, else at the end
            size = (len(blob) + 3) & ~3
            fits = [h for h in free if h[1] - h[0] >= size]
            if fits:
                h = min(fits, key=lambda h: h[1] - h[0])
                o, h[0] = h[0], h[0] + size
            else:
                o = len(out)
                out.extend(bytes(size))
            out[o:o + len(blob)] = blob
            return o
        # The game reads the original vertex lists (weighted vertices; it hangs without them), so every node keeps
        # its vertex chunks (copied) and only its strips change: the character's vertices go after them, from cache
        # slot `vbase` on (past every slot the original chunks write), and its strips draw those.
        ep = None
        lists = {}
        for j in sorted(range(len(nodes)), key=lambda j: -len(geo[j][2]) if j in geo else 0):
            nd = nodes[j]
            keep = orig_vlist(nd)
            if j in geo:
                P, N, T = geo[j]
                vl, pl_, c, r = ninja.cnk_model_lists(P, N, T, slot, mat, tiny_fl, tex_fl, strip_fl, base=vbase,
                                                      keep_vlist=keep)
                lists[j] = (alloc(vl), alloc(pl_), c, r)
            elif nd["model"]:
                if ep is None:
                    ep = alloc(struct.pack("<HH", 0xFF, 0))
                c_r = struct.unpack_from("<4f", mdl, nd["model"] + 8)
                lists[j] = (alloc(keep + struct.pack("<I", 0xFF)) if keep else 0, ep, list(c_r[:3]), c_r[3])
        for j, nd in enumerate(nodes):
            mo = 0
            if j in lists:
                vo, po, c, r = lists[j]
                mo = alloc(struct.pack("<II4f", vo, po, *c, r))
            flags = nd["flags"] & ~0x8 if j in geo else nd["flags"]   # drawn: clear NJD_EVAL_HIDE
            struct.pack_into("<II", out, nd["off"], flags, mo)
        o = 0
        while True:                                         # the lower-detail copies use the same tree now
            i, _p = struct.unpack_from("<iI", out, o)
            if i == -1:
                break
            if _p in remap:
                struct.pack_into("<I", out, o + 4, remap[_p])
            o += 8
        z = ninja.prs_compress(bytes(out))
        if (len(z) + 2047) // 2048 > msec:
            raise ValueError(f"{mpath}: {len(z)} bytes compressed > {msec} sectors")
        return z
    progress(20, f"Fitting {name} to {char.title()}'s {len(nodes)} nodes")
    r = NS.fit(model, roles, tgt, work, name, BUDGETS, blender, encode, 256, scale, progress)
    progress(80, "Encoding the texture atlas (VQ)")
    ents = ninja.pvm(tex)
    chunk = ninja.pvr_vq(np.asarray(r["atlas"].convert("RGB")), ninja.pvm_entry_gbix(ents[slot][1]))
    tex2 = ninja.pvm_replace(tex, slot, chunk)
    tz = ninja.prs_compress(tex2)
    if (len(tz) + 2047) // 2048 > tsec:
        raise ValueError(f"{tpath}: {len(tz)} bytes compressed > {tsec} sectors")
    rep = r["report"] | {"model_bytes": len(r["data"]), "model_sectors": msec, "texture_bytes": len(tz),
                         "texture_sectors": tsec, "atlas": list(r["atlas"].size), "atlas_slot": slot}
    return {"files": {mpath: r["data"], tpath: tz}, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def build_mod(cfg, meta: dict, game: dict, gdi: Path, progress=lambda p, m: None, root: Path | None = None) -> dict:
    """On the control plane: sa2_<slug> = a copy of the GD-ROM image with Sonic's model + textures replaced."""
    import shutil
    import time
    from . import characters as C, filemods
    from .gdrom import patch_gdi
    root = root or C.library_root(cfg)
    gid, name = game["game_id"], f"sa2_{meta['slug']}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto Sonic's nodes")
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "sa2"
    shutil.rmtree(work, ignore_errors=True)
    b = build_swap(gdi, root / meta["slug"] / meta["model"], roles, work, meta["name"], "SONIC", C._blender(cfg),
                   progress, (meta.get("rig") or {}).get("scale"))
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b["rigged"], tdir / "sa2_sonic.gltf")
    b["atlas"].save(tdir / "sa2_atlas.png")
    C.render_preview(tdir / "sa2_sonic.gltf", tdir / "sa2_preview.png")
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    progress(85, "Writing the modded GD-ROM image")
    img = patch_gdi(gdi, d, f"sa2_{meta['slug']}", b["files"], progress)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, "image": img.name, "built": time.time(),
                                                  "files": sorted(b["files"]), "character": meta["slug"],
                                                  "report": json.loads(json.dumps(b["report"], default=str))}))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img.name, "report": b["report"], "rigged": str(tdir / "sa2_sonic.gltf")}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for SA2 (DC): build sa2_<slug> on the control plane (where the collection is), launch it."""
    from . import characters as C
    gid, name = game["game_id"], f"sa2_{meta['slug']}"
    if meta.get("source", {}).get("game_id") in GAME_IDS and meta["slug"] == "sonic":
        return {"status": "native", "message": "Sonic is Sonic Adventure 2's own player: launch the game without a mod."}
    from . import filemods
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if inp.rebuild or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("SA2 swaps are built on the control-plane node (the Spark): run this there")
        gdi = C._dc_gdi(ctx, game)
        built = build_mod(ctx.config, meta, game, gdi, ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces Sonic (his node tree and motions; {built['report']['triangles']} triangles, "
                              "one 256 px atlas); preview targets/sa2_preview.png"})
    out = {"mod": name, "build": built, "replaces": "Sonic (player model; his skeleton and motions stay)"}
    if not inp.launch:
        return out | {"status": "built" if built else "ready"}
    l = C._launch(ctx, gid, name, C.HOST_OS)
    return out | {"status": "built+launched" if built else "launched", "launch": l}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--char", default="SONIC")
    ap.add_argument("--model", type=int, default=0)
    a = ap.parse_args()
    print(export(a.gdi, a.out, a.char, a.model))
