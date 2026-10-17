"""Phantasy Star Online Episode I & II (Plus) (GameCube): a collection character as a player class or an enemy.

Writer half of gbox.pso_gc (docs/pso_gc.md). Both slots go through the shared Ninja retarget (gbox.ninja_swap.fit:
gbox.sm64_swap.retarget onto the native node tree's bind pose with the body-role map, Blender decimation to the PSO
budgets, rigid per-node geometry, one atlas) and report every stage to the fit pop-up (gbox.fit_events).

slot=class:<name> (humar .. fomar; also player / hucast ...): the donor replaces pl<X>bdy00.nj, loose and inside
  pl<X>nj.bml. Every node keeps its original (weighted) vertex chunks - the engine needs them (gbox.pso_player, the SA2
  rule) - and the role nodes add the donor's rigid vertices from a free cache slot plus new strips on texture 1. Head,
  hair and cap models become an invisible speck. The atlas is written into every texture of pl<X>tex.afs in that
  texture's own size and GX format, so whichever costume / colour the save picks shows the donor. On the Dreamcast
  this layout broke on the 11-sector file limit; GameCube files are re-placed by the disc builder
  (gbox.filemods.build_image -> gbox.romexport.gc_put_file moves a grown file into free space and fixes the FST;
  this disc is full to its last byte, so that is a junk-filled gap between files, gc_find_gap).
slot=enemy:<key> | enemies: the donor replaces an enemy body on its own tree (its .njm motions drive it) inside its
  BML pack; the pack is rebuilt (PRS, big-endian header) and written into EVERY GSL area archive that carries it
  (and the loose copy when the disc has one). The body's GVM gets the atlas in each texture's own size and format.

GPU safety (GX): every written texture keeps its GVRT header (format, size, flags) and exactly its texel byte count;
strips index only the vertex cache slots the node wrote; validate() re-reads every written file with the reader.
Nothing is written to the source image: the mod is a copy (cache/mods/<game>/<name>/).
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from . import ninja, pso_gc as G

GAME_IDS = G.GAME_IDS
PSO_BUDGETS = (900, 750, 600, 480, 400)


# ------------------------------------------------------------------------------------------------ GX textures

def _rgb565(px: np.ndarray) -> np.ndarray:
    p = px.astype(np.int32)
    return ((p[..., 0] >> 3) << 11) | ((p[..., 1] >> 2) << 5) | (p[..., 2] >> 3)


def _rgb5a3(px: np.ndarray) -> np.ndarray:
    p = px.astype(np.int32)
    opaque = (1 << 15) | ((p[..., 0] >> 3) << 10) | ((p[..., 1] >> 3) << 5) | (p[..., 2] >> 3)
    alpha = ((p[..., 3] >> 5) << 12) | ((p[..., 0] >> 4) << 8) | ((p[..., 1] >> 4) << 4) | (p[..., 2] >> 4)
    return np.where(p[..., 3] >= 224, opaque, alpha)


def _tiles16(v: np.ndarray) -> bytes:
    h, w = v.shape
    return v.reshape(h // 4, 4, w // 4, 4).transpose(0, 2, 1, 3).astype(">u2").tobytes()


def gx_encode(rgba: np.ndarray, fmt: int) -> bytes:
    """RGBA (h, w, 4) -> one GX level: CMPR, RGB565, RGB5A3 or I8."""
    from .auf_gcm import encode_cmpr, encode_texture
    a = np.asarray(rgba, np.uint8)
    if fmt == 14:
        return encode_cmpr(a)
    if fmt == 4:
        return _tiles16(_rgb565(a))
    if fmt == 5:
        return _tiles16(_rgb5a3(a))
    if fmt == 1:
        return encode_texture(a, 1, 1)
    raise ValueError(f"GX format {fmt} is not written by this encoder")


def gvr_like(chunk: bytes, img) -> bytes:
    """The GVR (GBIX + GVRT) with `img` (PIL / array) in its own size and format; same length, header untouched.
    Mipmapped or palette textures raise ValueError (the caller keeps the original)."""
    from PIL import Image
    from .melee_models import tex_size
    hd = G.gvr_header(chunk)
    if hd["flags"] & 0x1 or hd["fmt"] in (8, 9, 10):
        raise ValueError("mipmapped / palette GVR")
    w, h = hd["w"], hd["h"]
    im = img if isinstance(img, Image.Image) else Image.fromarray(np.asarray(img, np.uint8))
    px = np.asarray(im.convert("RGBA").resize((w, h)), np.uint8)
    data = gx_encode(px, hd["fmt"])
    n = tex_size(hd["fmt"], w, h)
    if len(data) != n:
        raise ValueError(f"encoded {len(data)} bytes, the texture holds {n}")
    out = bytearray(chunk)
    out[hd["data"]:hd["data"] + n] = data
    return bytes(out)


def afs_build(data: bytes, entries: list[bytes]) -> bytes:
    """An AFS with its entries replaced (same count); offsets re-laid 0x800-aligned after the original table area."""
    n = struct.unpack_from("<I", data, 4)[0]
    if len(entries) != n:
        raise ValueError(f"{len(entries)} entries for an AFS of {n}")
    tab = [struct.unpack_from("<II", data, 8 + 8 * i) for i in range(n)]
    start = min(o for o, _s in tab) if tab else 0x800
    head = bytearray(data[:start])
    body = bytearray()
    for i, e in enumerate(entries):
        struct.pack_into("<II", head, 8 + 8 * i, start + len(body), len(e))
        body += e + bytes((-len(e)) % 0x800)
    return bytes(head + body)


def afs_with_atlas(data: bytes, atlas) -> tuple[bytes, int]:
    """Every texture of a player bank re-drawn with the atlas in its own size and format -> (AFS, textures replaced)."""
    ents = G.afs(data)
    out, done = [], 0
    for e in ents:
        try:
            out.append(gvr_like(e, atlas))
            done += 1
        except ValueError:
            out.append(e)
    return afs_build(data, out), done


def gvm_with_atlas(gvm: bytes, atlas) -> tuple[bytes, int]:
    """A GVM with the atlas in every texture (own size / format), header and entry order kept."""
    head_end = 8 + struct.unpack_from("<I", gvm, 4)[0]
    out = bytearray(gvm[:head_end])
    done = 0
    for _name, chunk in G.gvm_entries(gvm):
        try:
            out += gvr_like(chunk, atlas)
            done += 1
        except ValueError:
            out += chunk
    out += gvm[len(out):] if len(gvm) > len(out) else b""
    return bytes(out), done


# ------------------------------------------------------------------------------------------------ Ninja (big-endian)

def render_state(data: bytes, nodes: list[dict]) -> tuple[bytes, int, int, int]:
    """The model's own first material chunk, tiny-chunk flags, texture flags and strip flags (big-endian lists)."""
    mat, tiny_fl, tex_fl, strip_fl = b"", 0x34, 0x4000, 0x12
    for nd in nodes:
        if not nd["model"]:
            continue
        o = struct.unpack_from(">I", data, nd["model"] + 4)[0]
        if not o:
            continue
        for _ in range(64):
            h = struct.unpack_from(">H", data, o)[0]
            t = h & 0xFF
            if t == 0xFF:
                break
            if 0x10 <= t <= 0x3A:
                mat = mat or data[o:o + 4 + struct.unpack_from(">H", data, o + 2)[0] * 2]
                o += 4 + struct.unpack_from(">H", data, o + 2)[0] * 2
            elif t in (8, 9):
                tiny_fl, tex_fl = h >> 8, struct.unpack_from(">H", data, o + 2)[0] & 0xE000
                o += 4
            elif 0x40 <= t <= 0x4B:
                strip_fl = (h >> 8) | 0x10
                break
            else:
                o += 2
        if mat:
            break
    return mat, tiny_fl, tex_fl, strip_fl


def body_nj(file: bytes, geo: dict, texid: int) -> bytes:
    """A big-endian NJ (NJTL / POF0 prefix kept) with the donor geometry {node: (pos, nrm, tris)} drawn by its nodes.
    The tree keeps every node, flag and transform (the motions index nodes); every node keeps its original vertex
    chunks and loses its strips; geometry nodes add rigid vertices from a free cache slot and strips on `texid`."""
    prefix, data, _rest = G.njcm_payload(file)
    nodes = ninja.tree_nodes(data, 0, ">")
    nj = G.read_nj(file)
    vbase = (max(nj.vbuf) + 1 + 15) & ~15 if nj.vbuf else 0
    mat, tiny_fl, tex_fl, strip_fl = render_state(data, nodes)
    empty_pl = struct.pack(">HH", 0xFF, 0)
    models = {}
    for j, nd in enumerate(nodes):
        keep = b""
        if nd["model"]:
            vl = struct.unpack_from(">I", data, nd["model"])[0]
            keep = data[vl:vl + ninja.chunk_list_len(data, vl, "v", ">") - 4] if vl else b""
        if j in geo:
            P, N, T = geo[j]
            models[j] = ninja.cnk_model_lists(P, N, T, texid, mat, tiny_fl, tex_fl, strip_fl, ">", vbase, keep)
        elif nd["model"]:
            c_r = struct.unpack_from(">4f", data, nd["model"] + 8)
            models[j] = (keep + struct.pack(">I", 0xFF) if keep else b"", empty_pl, list(c_r[:3]), c_r[3])
    nn = [dict(nd) for nd in nodes]
    for j in geo:
        if j >= len(nn):
            raise ValueError(f"geometry for node {j}, the tree has {len(nn)} nodes")
        nn[j]["flags"] &= ~0x8
    d2, _root, ptrs = ninja.write_tree(nn, models, 0, ">")
    d2 += bytes((-len(d2)) % 4)
    return prefix + b"NJCM" + struct.pack("<I", len(d2)) + d2 + ninja.pof0(ptrs)


def speck_nj() -> bytes:
    """A one-node big-endian NJ with one zero-size triangle: a valid, invisible model (stands in for head / hair)."""
    vl, pl, _c, _r = ninja.cnk_model_lists(np.zeros((3, 3)), np.tile([0, 1.0, 0], (3, 1)), [((0, 1, 2), ((0, 0),) * 3)],
                                           0, b"", e=">")
    nd = [{"flags": 0x17, "trs": struct.pack(">3f3i3f", 0, 0, 0, 0, 0, 0, 1, 1, 1), "child": None, "sibling": None}]
    data, _root, ptrs = ninja.write_tree(nd, {0: (vl, pl, [0.0, 0.0, 0.0], 0.0)}, 0, ">")
    return b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs)


# ------------------------------------------------------------------------------------------------ slots

CLASS_SLOTS = {c.lower(): G.CLASS_LETTER[c] for c in G.CLASSES}


def parse_slot(slot: str | None) -> tuple[str, str]:
    """-> ("class", letter) | ("enemy", key) | ("enemies", "")."""
    s = (slot or "player").strip().lower()
    if s in ("enemies", "enemy", "enemy:all"):
        return "enemies", ""
    if s.startswith("enemy:"):
        k = s[6:].strip().replace(" ", "_").replace("-", "_")
        if k not in G.ENEMIES:
            raise ValueError(f"unknown PSO GC enemy {k!r} ({', '.join(G.ENEMIES)})")
        return "enemy", k
    s = s.removeprefix("class:")
    if s in ("player", ""):
        return "class", "A"
    if s in CLASS_SLOTS:
        return "class", CLASS_SLOTS[s]
    if len(s) == 1 and s.upper() in G.LETTERS:
        return "class", s.upper()
    raise ValueError(f"unknown PSO GC slot {slot!r} (class:<{'|'.join(CLASS_SLOTS)}>, enemy:<key>, enemies)")


def is_slot(slot: str | None) -> bool:
    try:
        parse_slot(slot)
        return True
    except ValueError:
        return False


def cast_slots() -> list[dict]:
    return [{"slot": f"class:{c.lower()}", "name": c, "kind": "player", "writer": "gbox.pso_gc_swap",
             "status": "unverified"} for c in G.CLASSES] + \
           [{"slot": f"enemy:{k}", "name": n, "kind": "enemy", "file": p, "entry": e, "writer": "gbox.pso_gc_swap",
             "status": "unverified"} for k, (p, e, n) in G.ENEMIES.items()]


def mod_name(slug: str, slot: str) -> str:
    kind, key = parse_slot(slot)
    tag = G.CLASSES[G.LETTERS.index(key)].lower() if kind == "class" else (key or "enemies")
    return f"psogc_{slug}_as_{tag}"


# ------------------------------------------------------------------------------------------------ builders

def build_class(disc, model: Path, roles: dict, work: Path, name: str, cls: str = "A", blender: str | None = None,
                progress=lambda p, m: None, scale: dict | None = None) -> dict:
    """-> {files {disc path: bytes}, report, rigged, atlas} for the donor as class `cls`."""
    from . import fit_events as FE, ninja_swap as NS
    L = G.letter(cls)
    bpath, mpath, tpath = f"pl{L}bdy00.nj", f"pl{L}nj.bml", f"pl{L}tex.afs"
    body_file = disc.read(bpath)
    class_roles = G.class_roles(body_file, L)
    tgt_roles = {r: j for r, j in class_roles.items() if r not in ("neck", "l_clav", "r_clav")}  # the drawn nodes
    nj = G.read_nj(body_file)
    nodes = G.tree(body_file)
    tgt = NS.target_from_nj(nj, tgt_roles, set(range(tgt_roles["head"], len(nodes))))
    bml = disc.read(mpath)
    extras = [n for n in (e["name"].split(b"\0")[0].decode("latin-1").lower() for e in G.bml_files(bml))
              if n[3:6] in ("hed", "hai", "cap")]

    def encode(geo):
        f = body_nj(body_file, geo, 1)
        G.read_nj(f)                                       # the reader must take what we wrote
        b2 = G.bml_build(bml, {bpath.lower(): f} | {n: speck_nj() for n in extras})
        return f, b2
    progress(20, f"Fitting {name} to the {G.CLASSES[G.LETTERS.index(L)]} body ({len(nodes)} nodes)")
    r = NS.fit(model, roles, tgt, work, name, PSO_BUDGETS, blender, encode, 256, scale, progress)
    body, bml2 = r["data"]
    progress(85, f"Writing the atlas into {tpath}")
    afs2, done = afs_with_atlas(disc.read(tpath), r["atlas"])
    files = {bpath: body, mpath: bml2, tpath: afs2}
    for p in disc.files:
        if p.lower().startswith(f"pl{L.lower()}") and p[3:6].lower() in ("hed", "hai", "cap") and p.lower().endswith(".nj"):
            files[p] = speck_nj()
    FE.stage("write", data={"files": sorted(files), "textures_replaced": done, "body_bytes": len(body)})
    rep = r["report"] | {"body_bytes": len(body), "bml_bytes": len(bml2), "textures_replaced": done, "class": L}
    return {"files": files, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def build_enemy(disc, model: Path, roles: dict, work: Path, name: str, key: str, blender: str | None = None,
                progress=lambda p, m: None, scale: dict | None = None) -> dict:
    """-> {files {disc path: bytes}, report, rigged, atlas} for the donor as one enemy body (its pack rebuilt, every
    GSL that carries the pack rewritten)."""
    from . import fit_events as FE, ninja_swap as NS, pso_enemy
    pack, entry, ename = G.ENEMIES[key]
    bml = G.read_pack(disc, pack)
    raw, gvm = G.bml_entry(bml, entry)
    nj = G.read_nj(raw)
    er, ec, eh = G.enemy_roles(key, raw)
    if "hip" not in er or "chest" not in er:
        raise ValueError(f"{entry}: no hip / chest on its tree, can't fit a body")
    tgt = pso_enemy.enemy_target(nj, er, ec, eh)
    progress(15, f"Fitting {name} to {ename} ({len(nj.bones)} nodes)")
    r = NS.fit(model, roles, tgt, work, name, PSO_BUDGETS, blender, lambda geo: body_nj(raw, geo, 0), 256, scale,
               progress)
    textures = {}
    if gvm is not None:
        textures[entry.lower()], done = gvm_with_atlas(gvm, r["atlas"])
    else:
        done = 0
    pack2 = G.bml_build(bml, {entry.lower(): r["data"]}, textures)
    files = {}
    homes = G.pack_homes(disc).get(pack, [])
    for g in homes:
        if g == "":
            files[pack] = pack2
        else:
            files[g] = G.gsl_build(disc.read(g), {pack: pack2})
    FE.stage("write", data={"enemy": ename, "pack": pack, "archives": sorted(files), "pack_bytes": len(pack2),
                            "textures_replaced": done})
    rep = r["report"] | {"enemy": ename, "pack": pack, "entry": entry, "archives": sorted(files),
                         "roles": {k: int(v) for k, v in tgt["roles"].items()}, "textures_replaced": done,
                         "body_bytes": len(r["data"]), "pack_bytes": len(pack2)}
    return {"files": files, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def validate(files: dict[str, bytes]) -> list[str]:
    """Re-read every written file with the reader (GSL -> BML -> NJ / GVM; AFS -> GVR); [] = all parse. The GX
    safety rules: every GVR keeps a GVRT header whose texel bytes match its format and size."""
    from .melee_models import tex_size
    bad = []

    def gvr_ok(where, chunk):
        hd = G.gvr_header(chunk)
        if hd["fmt"] not in (8, 9, 10) and not hd["flags"] & 1 and \
                len(chunk) - hd["data"] < tex_size(hd["fmt"], hd["w"], hd["h"]):
            bad.append(f"{where}: {len(chunk) - hd['data']} texel bytes for a {hd['w']}x{hd['h']} format {hd['fmt']}")

    def bml_ok(where, data):
        for e in G.bml_files(data):
            nm = e["name"].split(b"\0")[0].decode("latin-1")
            body, tex = G.bml_entry(data, nm)
            if nm.lower().endswith(".nj"):
                G.read_nj(body)
            if tex is not None:
                for tn, c in G.gvm_entries(tex):
                    gvr_ok(f"{where}:{nm}:{tn}", c)
    for path, data in files.items():
        try:
            low = path.lower()
            if low.endswith(".gsl"):
                for n, blob in G.gsl_files(data).items():
                    if n.lower().endswith(".bml"):
                        bml_ok(f"{path}:{n}", blob)
            elif low.endswith(".bml"):
                bml_ok(path, data)
            elif low.endswith(".nj"):
                G.read_nj(data)
            elif low.endswith(".afs"):
                for i, c in enumerate(G.afs(data)):
                    gvr_ok(f"{path}[{i}]", c)
        except Exception as e:                             # noqa: BLE001 - reported, never written
            bad.append(f"{path}: {type(e).__name__}: {e}")
    return bad


class Overlay:
    """A disc view with written files laid over it (the reader reads the mod exactly as the game would)."""

    def __init__(self, disc, files: dict[str, bytes]):
        self.disc, self.over = disc, dict(files)
        self.files = dict(disc.files) | {p: (0, len(d)) for p, d in files.items()}
        self.f = disc.f
        self.game_id = disc.game_id

    def read(self, name: str) -> bytes:
        return self.over[name] if name in self.over else self.disc.read(name)


def readback(disc, files: dict[str, bytes], slot: str, out_dir: Path) -> Path:
    """The written slot decoded by the reader (gbox.pso_gc) from the new files -> GLB path (the 'after' model)."""
    kind, key = parse_slot(slot)
    G._PACK_HOME.clear()
    view = Overlay(disc, files)
    if kind == "class":
        return G.export_player(view, key, out_dir)[0]
    return G.export_enemy(view, key, out_dir)[0]


def build_mod(cfg, meta: dict, game: dict, image: Path, slot: str, progress=lambda p, m: None, root: Path | None = None,
              name: str | None = None) -> dict:
    """The mod dir cache/mods/<game>/<name>: a copy of the disc (GCZ unpacked) with the files rewritten."""
    import shutil
    from . import characters as C, filemods
    root = Path(root or C.library_root(cfg))
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json)")
    kind, key = parse_slot(slot)
    name = name or mod_name(meta["slug"], slot)
    disc = G.open_disc(image)
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "pso_gc"
    shutil.rmtree(work, ignore_errors=True)
    model = root / meta["slug"] / meta["model"]
    scale = (meta.get("rig") or {}).get("scale")
    if kind == "class":
        builds = [build_class(disc, model, roles, work, meta["name"], key, C._blender(cfg), progress, scale)]
    else:
        keys = list(G.ENEMIES) if kind == "enemies" else [key]
        builds, files = [], {}
        for k in keys:
            b = build_enemy(disc, model, roles, work / k, meta["name"], k, C._blender(cfg), progress, scale)
            for p, data in b["files"].items():            # two bodies of one pack: rebuild on the newest archive
                if p in files:
                    raise ValueError("slot=enemies builds one pack per body; use enemy:<key> per body")
                files[p] = data
            builds.append(b)
    files = {p: d for b in builds for p, d in b["files"].items()}
    bad = validate(files)
    if bad:
        raise ValueError("written files don't read back: " + "; ".join(bad[:5]))
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    tag = name.split("_as_")[-1]
    shutil.copy2(builds[0]["rigged"], tdir / f"psogc_{tag}.gltf")
    builds[0]["atlas"].save(tdir / f"psogc_{tag}_atlas.png")
    try:
        C.render_preview(tdir / f"psogc_{tag}.gltf", tdir / f"psogc_{tag}_preview.png")
    except Exception as e:                                 # noqa: BLE001 - a preview never blocks the build
        progress(90, f"preview skipped: {e}")
    progress(92, f"Writing the disc copy ({len(files)} files)")
    res = filemods.build_image(cfg, game["game_id"], Path(image), name, {p: {"bytes": d} for p, d in files.items()},
                               progress)
    marker = Path(res["dir"]) / ".gbox-mod.json"
    rec = json.loads(marker.read_text())
    rec.update({"character": meta["slug"], "slot": slot, "writer": "gbox.pso_gc_swap", "verified": False,
                "report": json.loads(json.dumps([b["report"] for b in builds], default=str))})
    marker.write_text(json.dumps(rec))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": Path(res["image"]).name, "files": sorted(files),
            "report": [b["report"] for b in builds]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for PSO Ep I&II (GC): slot=class:<name> (default HUmar) | enemy:<key>. Built on the
    control plane as psogc_<slug>_as_<slot> (a disc copy), launched on request. Unverified in game."""
    from . import characters as C, filemods, fit_events as FE
    slot = inp.slot or "class:humar"
    kind, key = parse_slot(slot)
    gid, name = game["game_id"], mod_name(meta["slug"], slot)
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if getattr(inp, "rebuild", False) or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("PSO GC swaps are built on the control-plane node (the Spark): run this there")
        FE.plan([(slot, meta["slug"], f"{meta.get('name') or meta['slug']} -> {slot}")])
        FE.model(slot)
        built = build_mod(ctx.config, meta, game, G.disc_path(ctx, game), slot, ctx.progress, name=name)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces {slot} (gbox.pso_gc_swap); unverified in game; preview targets/psogc_*_preview.png"})
    out = {"mod": name, "build": built, "slot": slot, "verification": "unverified in game (docs/pso_gc.md)"}
    if not getattr(inp, "launch", False):
        return out | {"status": "built" if built else "ready"}
    return out | {"status": "built+launched" if built else "launched", "launch": C._launch(ctx, gid, name, C.HOST_OS)}


def main(argv=None) -> int:
    """Offline build: python -m gbox.pso_gc_swap <image> <donor dir (meta.json)> <out dir> --slot class:humar"""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("donor", help="a collection entry directory (meta.json + model)")
    ap.add_argument("out")
    ap.add_argument("--slot", default="class:humar")
    ap.add_argument("--blender")
    a = ap.parse_args(argv)
    meta = json.loads((Path(a.donor) / "meta.json").read_text())
    kind, key = parse_slot(a.slot)
    disc = G.open_disc(a.image)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    model, roles = Path(a.donor) / meta["model"], meta["rig"]["roles"]
    from .re4gc_enemies import blender_exe
    blender = a.blender or blender_exe()
    if kind == "class":
        b = build_class(disc, model, roles, out / "work", meta["name"], key, blender)
    else:
        b = build_enemy(disc, model, roles, out / "work", meta["name"], key, blender)
    bad = validate(b["files"])
    for p, d in b["files"].items():
        (out / "files").mkdir(exist_ok=True)
        (out / "files" / p.replace("/", "_")).write_bytes(d)
    b["atlas"].save(out / "atlas.png")
    from . import characters as C                         # before (the stock slot) / after (the written files, re-read)
    before = G.export_player(disc, key, out / "before")[0] if kind == "class" else G.export_enemy(disc, key, out / "before")[0]
    after = readback(disc, b["files"], a.slot, out / "after")
    for tag, glb in (("before", before), ("after", after)):
        C.render_preview(glb, out / f"{tag}.png")
    print(json.dumps({"files": sorted(b["files"]), "invalid": bad, "before": str(out / "before.png"),
                      "after": str(out / "after.png"), "report": b["report"]}, default=str, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
