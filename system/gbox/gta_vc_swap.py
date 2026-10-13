"""GTA: Vice City (classic RenderWare PC port) native character swap: a collection character replaces Tommy
(player.dff + player.txd), one ped (ped:<dff name>) or every ped that shares Tommy's skeleton (peds:all) in
models/gta3.img, keeping the ped's own bones so every animation, the controls and car entry/exit drive the new body.

Slots (characters op=use slot=...): `player` (Tommy), `ped:<name>` (one DFF, e.g. ped:male01), `peds:all` (every
skeleton-family ped except the player), `all` (player + peds:all).

Format work lives in gbox/gta_vc_models.py (IMG v1, HAnim, Skin, plain / D3D8 geometry, D3D8 rasters). This module:
  * retargets the character onto the ped's bone frames (gbox.re4gc_enemies.retarget: rigid per-limb fit, one bone per
    vertex) with the role map read from the clump's HAnim bone tags / frame names (gta_vc_models.role_map),
  * writes one smooth-skinned plain geometry (RW 3.4.0.3, Bin Mesh triangle list, Skin PLG with the original inverse
    bind matrices) into the ped's first skinned atomic; the material list stays, every triangle on material 0,
  * packs the character's textures into one atlas that replaces the raster material 0 draws with (32-bit 8888 with
    a mip chain when the original had one; the game accepts any raster format the TXD declares),
  * rebuilds gta3.img + gta3.dir (only the replaced entries change; every offset recomputed) into a filemods mod dir:
    a hard-link copy of the install with models/gta3.img and models/gta3.dir replaced. The install itself is never
    written. The operator plays it on this PC (gbox-deploy memory: mods swap in place on the operator's PC).

Owned install: the catalog's windows_native Vice City (1fd42f50b10252e6) launches the Definitive Edition (UE4), which
has no gta3.img; use() detects that (gta_vc_models.locate_install) and leaves the gap report instead of guessing.
Catalog entry 5eacc9f11d9a5956 points at the PS2 .chd under the same HyperSpin tree (also not this port).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import gta_rw as R
from . import gta_vc_models as M
from .gta_vc_models import Clump, ImgArchive, locate_install

GAME_IDS = dict(M.GAME_IDS)
MAX_TRIS = 8000                     # VC PC peds are 1-2k triangles; the D3D8 software skinner copes with far more
HEIGHT_MM = (1500.0, 1950.0)        # VC ped heights the retarget may scale the donor to
SLOT_RE = re.compile(r"^[a-z0-9_\-]{1,20}$")


# ------------------------------------------------------------------------------------------------------- slots
def parse_slot(slot: str) -> tuple[str, str | None]:
    """'player' -> ('player', None); 'ped:male01' / 'ped:male01.dff' -> ('ped', 'male01'); 'peds:all' -> ('peds', 'all');
    'all' -> ('all', None)."""
    s = (slot or "player").strip().lower()
    if s in ("player", "tommy"):
        return "player", None
    if s in ("peds:all", "peds", "pedestrians"):
        return "peds", "all"
    if s == "all":
        return "all", None
    if s.startswith("ped:"):
        name = s[4:].strip()
        name = name[:-4] if name.endswith(".dff") else name
        if not SLOT_RE.match(name):
            raise ValueError(f"slot {slot!r}: a ped slot is ped:<dff name> (letters, digits, _)")
        return "ped", name
    raise ValueError(f"slot {slot!r}: Vice City PC takes player | ped:<dff name> | peds:all | all")


def ped_txds(inst: dict) -> dict[str, str]:
    """model -> txd from the install's data/default.ide peds section (a ped's TXD usually shares its name)."""
    if not inst.get("ide"):
        return {}
    return {m.lower(): t for m, t in M.ide_peds(Path(inst["ide"]).read_text("utf-8", "replace"))}


def ped_family(img: ImgArchive, ide_text: str | None = None, reference: str = "player") -> list[str]:
    """Every ped DFF whose HAnim bone-tag set equals the reference's (the skeleton family Tommy's animations drive);
    the reference itself excluded. Candidates: the .ide peds when given, else every .dff in the archive."""
    ref = Clump(img.entry(f"{reference}.dff"))
    tags = frozenset(t for t in ref.hanim["ids"] if t is not None)
    cands = [m for m, _t in M.ide_peds(ide_text)] if ide_text else [n[:-4] for n in img.names(".dff")]
    out = []
    for m in cands:
        if m.lower() == reference.lower() or f"{m}.dff" not in img:
            continue
        try:
            c = Clump(img.entry(f"{m}.dff"))
        except (ValueError, StopIteration, struct.error, IndexError):
            continue
        if frozenset(t for t in c.hanim["ids"] if t is not None) == tags and c.skinned:
            out.append(m)
    return out


def slot_targets(img: ImgArchive, inst: dict, slot: str) -> list[tuple[str, str]]:
    """(dff name, txd name) per model the slot covers."""
    kind, target = parse_slot(slot)
    txds = ped_txds(inst)
    ide_text = Path(inst["ide"]).read_text("utf-8", "replace") if inst.get("ide") else None

    def pair(m):
        return m, txds.get(m.lower(), m)
    if kind == "player":
        return [pair("player")]
    if kind == "ped":
        if f"{target}.dff" not in img:
            raise ValueError(f"ped:{target}: no {target}.dff in gta3.img")
        return [pair(target)]
    peds = [pair(m) for m in ped_family(img, ide_text)]
    return ([pair("player")] if kind == "all" else []) + peds


# ---------------------------------------------------------------------------------------------------- retarget
def retarget(clump: Clump, src_model: Path, src_roles: dict) -> list[dict]:
    """Library glTF -> prims in GTA model space (metres, Z up), J[:,0] = frame index of the owning bone."""
    from .characters import rig_from_gltf
    from .re4gc_enemies import retarget as fit
    src = rig_from_gltf(Path(src_model), src_roles)
    prims = fit(src, clump, roles=clump.roles, height_range=HEIGHT_MM)
    inv = np.linalg.inv(R.GTA_TO_GLTF)[:3, :3]
    for p in prims:
        p["pos"] = (np.asarray(p["pos"], float) / 1000.0) @ inv.T
        p["nrm"] = np.asarray(p["nrm"], float) @ inv.T
    return prims


def _bone_of_frame(clump: Clump, fi: int) -> int:
    """The skin bone a frame drives (a frame without a bone rides its nearest boned ancestor; else bone 0)."""
    k = fi
    while k >= 0:
        if k in clump.frame_bone:
            return clump.frame_bone[k]
        k = clump.frames[k]["parent"]
    return 0


def _weld(pos, nrm, uv, bone, tris):
    key = np.round(np.c_[pos * 1e4, nrm * 1e3, uv * 1e5, bone * 1e6]).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return pos[first], nrm[first], uv[first], bone[first], inv.reshape(-1)[tris]


def skinned_geometry(clump: Clump, prims: list[dict], uvmaps: list[np.ndarray], atomic_frame: int):
    """Retargeted triangles -> one welded geometry in the atomic frame's space + per-vertex (bone idx, weight)."""
    P, N, U, B = [], [], [], []
    for p, uv in zip(prims, uvmaps):
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        J = np.asarray(p["J"])[:, 0] if np.ndim(p["J"]) > 1 else np.asarray(p["J"])
        P.append(np.asarray(p["pos"], float)[T].reshape(-1, 3))
        N.append(np.asarray(p["nrm"], float)[T].reshape(-1, 3))
        U.append(np.asarray(uv, float).reshape(-1, 2))
        B.append(np.array([_bone_of_frame(clump, int(f)) for f in J[T].reshape(-1)], np.int64))
    P, N, U, B = (np.concatenate(x) if x else np.zeros((0, 3)) for x in (P, N, U, B))
    if not len(P):
        raise ValueError("the character has no triangles")
    inv = np.linalg.inv(clump.frames[atomic_frame]["world"])
    P = (np.c_[P, np.ones(len(P))] @ inv.T)[:, :3]
    N = N @ inv[:3, :3].T
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    P, N, U, B, tris = _weld(P, N, U, B.reshape(-1), np.arange(len(P)).reshape(-1, 3))
    idx = np.c_[B, np.zeros((len(B), 3))].astype(np.uint8)
    w = np.c_[np.ones(len(B)), np.zeros((len(B), 3))].astype(np.float32)
    return R.Geom(P.astype(np.float32), N.astype(np.float32), U.astype(np.float32), tris), idx, w


def set_material_texture(geom: R.Chunk, index: int, name: str):
    """Point material `index` of a Geometry at texture `name` (its first String chunk)."""
    m = geom.first(R.MATLIST).find(R.MATERIAL)[index]
    tx = m.find(R.TEXTURE)
    if tx:
        s = tx[0].find(R.STRING)[0]
        s.data = R.string_chunk(name, s.version).data
    else:
        t = R.Chunk(R.TEXTURE, geom.version, container=True)
        t.kids.append(R.Chunk(R.STRUCT, geom.version, struct.pack("<BBH", 2, 0x11, 0)))
        t.kids += [R.string_chunk(name, geom.version), R.string_chunk("", geom.version), R.Chunk(R.EXTENSION, geom.version, container=True)]
        m.kids.insert(1, t)
        st = bytearray(m.first(R.STRUCT).data)
        struct.pack_into("<I", st, 12, 1)
        m.first(R.STRUCT).data = bytes(st)


def _empty_skinned(template: R.Chunk, skin: M.Skin) -> R.Chunk:
    z = np.zeros((3, 3), np.float32)
    g = R.Geom(z, np.tile(np.array([0, 0, 1], np.float32), (3, 1)), np.zeros((3, 2), np.float32), np.array([[0, 1, 2]]))
    return M.geometry_chunk(g, template, skin)


def build_dff(clump: Clump, geom: R.Geom, idx: np.ndarray, w: np.ndarray, texture: str | None = None) -> bytes:
    """The ped's clump with the new body in its first skinned atomic (frames, HAnim, atomics, material lists and
    plugins kept; other skinned atomics become one degenerate triangle so nothing of the old body remains)."""
    root, _ = R.parse(clump.raw)
    gl = root.first(R.GEOMLIST)
    geoms = gl.find(R.GEOMETRY)
    new = list(geoms)
    main = clump.skinned[0][1]
    for _fi, gi in clump.skinned:
        skin = M.skin_read(geoms[gi], struct.unpack_from("<III", geoms[gi].first(R.STRUCT).data)[2])
        new[gi] = M.geometry_chunk(geom, geoms[gi], skin, idx, w) if gi == main else _empty_skinned(geoms[gi], skin)
    if texture:
        set_material_texture(new[main], 0, texture)
    it = iter(new)
    gl.kids = [next(it) if k.type == R.GEOMETRY else k for k in gl.kids]
    root.size_override = None
    return root.to_bytes() + clump.tail


def dff_parts(dff: bytes) -> dict:
    """Re-decode a written clump: triangles per bone frame (proves the writer's output parses and skins)."""
    c = Clump(dff)
    out = {}
    for _fi, gi in c.skinned:
        sg = c.geometry(gi)
        owner = sg.skin.idx[sg.geom.tris[:, 0], 0]
        for b in np.unique(owner):
            fi = c.bone_frames[int(b)] if int(b) < len(c.bone_frames) else -1
            nm = c.frames[fi]["name"] if fi >= 0 else f"bone{int(b)}"
            out[nm] = out.get(nm, 0) + int((owner == b).sum())
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# -------------------------------------------------------------------------------------------------------- build
def swap_files(img: ImgArchive, src_model: Path, src_roles: dict, work: Path, blender: str | None = None,
               progress=None, model: str = "player", txd_name: str | None = None) -> dict:
    """New <model>.dff + <txd>.txd bytes for one ped."""
    from .gta_stories_models import pack_atlases
    progress = progress or (lambda p, m: None)
    txd_name = txd_name or model
    dname, tname = f"{model}.dff", f"{txd_name}.txd"
    dff, txd = img.entry(dname), img.entry(tname)
    clump = Clump(dff)
    if not clump.skinned:
        raise ValueError(f"{dname}: no skinned atomic (not a VC ped clump)")
    frame, gi = clump.skinned[0]
    tex = next((t for t in M.material_textures(clump.geoms[gi]) if t), None)
    raster = M.main_raster(txd, tex)
    if raster is None:
        raise ValueError(f"{tname}: no rasters")
    size = (max(raster.width, 256), max(raster.height, 256))
    src = Path(src_model)
    progress(20, f"Fitting onto {model}'s {len(clump.hanim['nodes'])} bones")
    prims = retarget(clump, src, src_roles)
    tris = sum(len(np.asarray(p["tris"]).reshape(-1, 3)) for p in prims)
    note = None
    if tris > MAX_TRIS and blender:
        from .re4gc_enemies import decimate
        progress(30, f"{tris} triangles: decimating to ~{int(MAX_TRIS * 0.9)} (Blender)")
        src = decimate(src, Path(work) / f"_gtavc_{model}_dec.glb", int(MAX_TRIS * 0.9), blender)
        prims = retarget(clump, src, src_roles)
    elif tris > MAX_TRIS:
        note = f"{tris} triangles (> {MAX_TRIS}) and no Blender to decimate: written as is"
    atlases, maps = pack_atlases(prims, [size])
    maps = [(0, uv) for _a, uv in maps]
    geom, idx, w = skinned_geometry(clump, prims, [uv for _a, uv in maps], frame)
    new_dff = build_dff(clump, geom, idx, w, None if tex and tex.lower() == raster.name.lower() else raster.name)
    new_txd = M.txd_replace(txd, {raster.name: M.raster_8888(raster, atlases[0])})
    return {"model": model, "txd": txd_name, "dff": new_dff, "txd_bytes": new_txd, "atlas": atlases[0],
            "triangles": len(geom.tris), "vertices": len(geom.pos), "parts": dff_parts(new_dff), "note": note,
            "raster": raster.describe(), "source": str(src), "roles": {r: clump.frames[i]["name"] for r, i in clump.roles.items()},
            "orig_sha256": {dname: _sha(dff), tname: _sha(txd)}}


def build_mod(cfg, game: dict, rom: Path, src_model: Path, roles: dict, name: str, slot: str = "player",
              progress=None) -> dict:
    """The mod gtavc_<slug>[_<slot>]: a filemods copy of the classic install with models/gta3.img + gta3.dir rebuilt."""
    from . import filemods
    progress = progress or (lambda p, m: None)
    gid = game["game_id"]
    inst = locate_install(rom)
    if inst["kind"] != "classic":
        raise ValueError(f"{game['title']}: {inst['kind']} install at {inst['root']} has no models/gta3.img "
                         f"({inst.get('engine') or 'not the classic RenderWare port'})")
    work = Path(cfg.cache) / "characters_build" / name
    work.mkdir(parents=True, exist_ok=True)
    try:
        from .characters import _blender
        bl = _blender(cfg)
    except Exception:                    # noqa: BLE001 - decimation is optional
        bl = None
    img = ImgArchive(inst["img"], inst["dir"])
    targets = slot_targets(img, inst, slot)
    if not targets:
        raise ValueError(f"slot {slot}: no ped in gta3.img shares the player's skeleton")
    fits, skipped, rep = [], {}, {}
    for k, (model, txd) in enumerate(targets):
        progress(10 + 55 * k / len(targets), f"{model}.dff ({k + 1}/{len(targets)})")
        try:
            f = swap_files(img, Path(src_model), roles, work, bl, None, model, txd)
        except ValueError as e:
            if len(targets) == 1:
                raise
            skipped[model] = str(e)
            continue
        fits.append(f)
        rep[f"{model}.dff"] = f["dff"]
        rep[f"{txd}.txd"] = f["txd_bytes"]
    if not fits:
        raise ValueError(f"nothing written: {skipped}")
    progress(70, f"Rebuilding gta3.img ({Path(inst['img']).stat().st_size >> 20} MB, {len(rep)} entries replaced)")
    new_img = work / "gta3.img"
    new_dir = img.rebuild(new_img, rep)
    (work / "gta3.dir").write_bytes(new_dir)
    back = ImgArchive(new_img, work / "gta3.dir")
    bad = {n: (_sha(back.entry(n)[:len(b)]), _sha(b)) for n, b in rep.items() if _sha(back.entry(n)[:len(b)]) != _sha(b)}
    if bad or len(back.ents) != len(img.ents):
        raise RuntimeError(f"rebuilt IMG didn't read back the new files: {bad}")
    progress(78, "Copying the install (hard links; once per game)")
    r = filemods.build(cfg, gid, Path(inst["exe"]), name, {"models/gta3.img": {"from": new_img},
                                                           "models/gta3.dir": {"bytes": new_dir}}, progress)
    out = Path(r["dir"])
    want = {n: _sha(b) for n, b in rep.items()}
    orig = {n: h for f in fits for n, h in f["orig_sha256"].items()}
    meta = json.loads((out / ".gbox-mod.json").read_text())
    meta |= {"slot": slot, "entries": sorted(want), "models": [f["model"] for f in fits], "skipped": skipped,
             "source_sha256": orig, "new_sha256": want, "install_kind": "classic", "exe": Path(inst["exe"]).name,
             "built": time.time(), "launch": f"run {out / Path(inst['exe']).name} (attract-mode catalog entries launch "
             "through RocketLauncher, which does not take a mod; a windows_native entry with launch.path does)"}
    (out / ".gbox-mod.json").write_text(json.dumps(meta))
    try:
        from PIL import Image
        Image.fromarray(fits[0]["atlas"]).save(work / "atlas.png")
        M.clump_to_gltf(fits[0]["dff"], work / "preview.glb", fits[0]["atlas"], name)
    except Exception:                    # noqa: BLE001 - previews are informational
        pass
    shutil.rmtree(work / "_tmp", ignore_errors=True)
    return {"mod": name, "dir": str(out), "slot": slot, "models": [f["model"] for f in fits], "skipped": skipped,
            "triangles": {f["model"]: f["triangles"] for f in fits}, "parts": fits[0]["parts"], "roles": fits[0]["roles"],
            "rasters": {f["model"]: f["raster"] for f in fits}, "notes": [f["note"] for f in fits if f["note"]],
            "source_sha256": orig, "new_sha256": want, "img_bytes": new_img.stat().st_size, "launch": meta["launch"]}


# ---------------------------------------------------------------------------------------------- characters op=use
def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Vice City PC: build gtavc_<slug>[_<slot>] unless it exists, record the target, launch it
    when the catalog entry can take a mod. A Definitive Edition install gets the overlay fallback + gap report."""
    from . import char_coverage
    from . import characters as C
    from . import filemods
    gid = game["game_id"]
    kind, target = parse_slot(inp.slot)
    rom = C._rom(ctx, game)
    inst = locate_install(rom)
    if inst["kind"] != "classic":
        need = {"target": "Tommy (SK_player) / the peds (SK_<ped>) of the Definitive Edition" if inst["kind"] == "definitive"
                else "Tommy / the peds (models/gta3.img) of the classic port",
                "format": "Unreal Engine 4 cooked SkeletalMesh + Skeleton uassets in Gameface/Content/Paks/gta.pak "
                          "(pak v11, Oodle); mods load from Gameface/Content/Paks/~mods" if inst["kind"] == "definitive"
                else "unknown install layout",
                "steps": ["read SK_player.uasset/.uexp + SK_player_skel (UE 4.26 cooked SkeletalMesh, Oodle-compressed pak entries)",
                          "retarget onto its reference skeleton (same bone names as the classic ped: the DE kept Rockstar's rigs)",
                          "write a cooked SkeletalMesh uasset + a ~mods .pak"],
                "have": "gbox/gta_vc_swap.py: the classic RenderWare PC port (player, ped:<dff>, peds:all), not usable on "
                        f"this install ({inst['kind']}: {inst.get('engine') or inst['root']})", "install": inst}
        return char_coverage.no_writer(ctx, C._api, meta, game, need, inp) | {"install": inst, "writer": "gbox.gta_vc_swap"}
    name = f"gtavc_{meta['slug']}" + {"player": "", "ped": f"_{target}", "peds": "_peds", "all": "_all"}[kind]
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        roles = meta.get("rig", {}).get("roles")
        if not roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't fit it to Tommy's bones")
        built = build_mod(ctx.config, game, rom, C._local_or_fetch(ctx, meta, meta["model"]), roles, name, inp.slot,
                          progress=ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": inp.slot, "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces {', '.join(built['models'])} (.dff/.txd in a rebuilt models/gta3.img; bones and animations stay)"})
    what = {"player": "Tommy Vercetti (player.dff)", "ped": f"the {target} ped", "peds": "every ped on Tommy's skeleton",
            "all": "Tommy and every ped on his skeleton"}[kind]
    res = {"mod": name, "build": built, "replaces": what, "install": inst}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    if (game.get("launch") or {}).get("kind") == "attract":
        mod = filemods.mod_dir(ctx.config, gid, name) / Path(inst["exe"]).name
        return res | {"status": "built", "launch": None,
                      "message": f"{name} is built; start it with {mod} (this HyperSpin entry launches through "
                                 "RocketLauncher, which does not take a mod)."}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    return res | {"status": "launching", "launch_job": lj.get("id"), "node": node,
                  "message": f"Vice City mod {name} is launching; start a new game or load a save (peds stream from the new gta3.img)."}
