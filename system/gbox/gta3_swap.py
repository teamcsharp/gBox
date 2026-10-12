"""GTA III (PS2) native player swap: a library character replaces Claude (player.dff + player.txd in MODELS/GTA3.IMG
and every byte-identical GTA3_n.IMG copy on the DVD), keeping his 17-frame rig so every ped animation, the
controls and the car entry/exit still drive the new body.

Format work lives in gbox/gta_rw.py (RW chunk tree, plain RW 3.1 geometry, PS2 8-bit rasters, IMG/DIR). This module:
  * retargets the character onto Claude's frames (gbox.re4gc_enemies.retarget: rigid per-limb fit, single bone),
  * writes one plain geometry per atomic in its frame's local space (material list and plugins of the original
    part kept, so the game's PS2 instancer handles it as it handles Claude),
  * packs the character's textures into PLAYER.TXD's own 8-bit raster (same size, every mip level rewritten),
  * patches a copy of the disc image; both files must fit their old IMG slots (decimated with Blender until they do).

Actor identity: GTA III's player ped always uses model index 0 (MI_PLAYER, special model "player"); a session check
reads the frame-selected actor through the gBox session (see identify()).
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from . import gta_rw as R

GAME_IDS = {"265819390074bb4e": "Grand Theft Auto III (USA, Canada)"}
SECTOR = R.SECTOR
# gbox body role -> GTA III ped frame (case-insensitive). GTA III has no neck/clavicle frames: the neck rides Shead.
GTA3_ROLES = {"pelvis": "swaist", "hip": "smid", "chest": "storso", "neck": "shead", "head": "shead",
              "l_upper": "supperarml", "l_fore": "slowerarml", "l_hand": "slhand",
              "r_upper": "supperarmr", "r_fore": "slowerarmr", "r_hand": "srhand",
              "l_thigh": "supperlegl", "l_shin": "slowerlegl", "l_foot": "sfootl",
              "r_thigh": "supperlegr", "r_shin": "slowerlegr", "r_foot": "sfootr"}
ENTRIES = ("player.dff", "player.txd")
# Claude's outfits are separate special-model skins in GTA3.IMG. The opening mission (Callahan Bridge, the Kuruma drive
# to the safehouse) runs with the prison skin: main.scm swaps the player to 'PLAYERP' and only later back to 'PLAYER'.
# A swap must write every skin, or the player keeps Claude's stock body there (#1311 live run: prison Claude on foot).
SKINS = ("player", "playerp", "playerx")


# --------------------------------------------------------------------------------------------------- disc image
def iso_from_rom(rom: Path, dst: Path, progress=None) -> Path:
    """The vanilla 2048-byte-sector image: .iso copied, .chd via chdman, .7z/.zip via 7z (the single .iso member)."""
    dst = Path(dst)
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part, suf = dst.with_suffix(".part"), Path(rom).suffix.lower()
    if progress:
        progress(5, f"Unpacking {Path(rom).name}")
    if suf == ".chd":
        cue = dst.with_suffix(".cue")
        r = subprocess.run(["chdman", "extractcd", "-i", str(rom), "-o", str(cue), "-ob", str(part), "-f"],
                           capture_output=True, text=True, timeout=3600)
        cue.unlink(missing_ok=True)
        if r.returncode or not part.exists():
            raise RuntimeError(f"chdman failed: {(r.stdout + r.stderr)[-800:]}")
    elif suf in (".7z", ".zip"):
        tmp = dst.parent / "_unpack"
        shutil.rmtree(tmp, ignore_errors=True)
        r = subprocess.run(["7z", "x", "-y", f"-o{tmp}", str(rom)], capture_output=True, text=True, timeout=3600)
        isos = sorted(tmp.rglob("*.iso")) if tmp.exists() else []
        if r.returncode or not isos:
            raise RuntimeError(f"7z failed or no .iso inside: {(r.stdout + r.stderr)[-800:]}")
        isos[0].replace(part)
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        shutil.copy2(rom, part)
    part.replace(dst)
    return dst


# ------------------------------------------------------------------------------------------------- the rig
class Rig:
    """Claude's clump: frames (world matrices, GTA Z up), atomics (frame, geometry) and the role -> frame map.
    Pass `roles` to adapt the same parser to another GTA ped (e.g. Vice City)."""

    def __init__(self, dff: bytes, roles: dict | None = None):
        self.raw = dff
        self.root, self.tail = R.parse(dff)
        self.frames = R.frames_read(self.root.first(R.FRAMELIST))
        self.geoms = self.root.first(R.GEOMLIST).find(R.GEOMETRY)
        self.atomics = [struct.unpack_from("<II", a.first(R.STRUCT).data) for a in self.root.find(R.ATOMIC)]
        names = [f["name"].lower() for f in self.frames]
        role_map = roles or GTA3_ROLES
        missing = [n for n in set(role_map.values()) if n not in names]
        if missing:
            raise ValueError(f"not a GTA III ped clump: frames {missing} missing (have {names})")
        self.roles = {r: names.index(n) for r, n in role_map.items()}

    # duck-typed re4gc template: bones (index, parent|0xFF), joint positions in mm, glTF axes
    @property
    def bones(self):
        return [(i, f["parent"] if f["parent"] >= 0 else 0xFF) for i, f in enumerate(self.frames)]

    def bone_world(self):
        return {i: (R.GTA_TO_GLTF @ f["world"])[:3, 3] * 1000.0 for i, f in enumerate(self.frames)}


def retarget(rig: Rig, src_model: Path, src_roles: dict) -> list[dict]:
    """Library glTF -> prims in GTA model space (metres, Z up), J[:,0] = Claude frame index."""
    from .characters import rig_from_gltf
    from .re4gc_enemies import retarget as fit
    src = rig_from_gltf(Path(src_model), src_roles)
    prims = fit(src, rig, roles=rig.roles, height_range=(1500.0, 1900.0))
    inv = np.linalg.inv(R.GTA_TO_GLTF)[:3, :3]
    for p in prims:
        p["pos"] = (np.asarray(p["pos"], float) / 1000.0) @ inv.T
        p["nrm"] = np.asarray(p["nrm"], float) @ inv.T
    return prims


def _weld(pos, nrm, uv, tris):
    key = np.round(np.c_[pos * 1e4, nrm * 1e3, uv * 1e5]).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return pos[first], nrm[first], uv[first], inv.reshape(-1)[tris]


def part_geometries(rig: Rig, prims: list[dict], uvmaps: list[np.ndarray]) -> dict[int, R.Geom]:
    """Group retargeted triangles by owning frame; each part in its frame's local space, welded."""
    acc: dict[int, list] = {}
    for p, uv in zip(prims, uvmaps):
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        J = np.asarray(p["J"])[:, 0] if np.ndim(p["J"]) > 1 else np.asarray(p["J"])
        owner = J[T[:, 0]]
        for fi in np.unique(owner):
            sel = owner == fi
            acc.setdefault(int(fi), []).append((p["pos"][T[sel]].reshape(-1, 3), p["nrm"][T[sel]].reshape(-1, 3),
                                                uv[sel].reshape(-1, 2)))
    out = {}
    for fi, parts in acc.items():
        P = np.concatenate([a for a, _, _ in parts])
        N = np.concatenate([b for _, b, _ in parts])
        U = np.concatenate([c for _, _, c in parts])
        inv = np.linalg.inv(rig.frames[fi]["world"])
        P = (np.c_[P, np.ones(len(P))] @ inv.T)[:, :3]
        N = N @ inv[:3, :3].T
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        P, N, U, tris = _weld(P, N, U, np.arange(len(P)).reshape(-1, 3))
        out[fi] = R.Geom(P.astype(np.float32), N.astype(np.float32), U.astype(np.float32), tris)
    return out


def _empty_geom() -> R.Geom:
    z = np.zeros((3, 3), np.float32)
    return R.Geom(z, np.tile(np.array([0, 0, 1], np.float32), (3, 1)), np.zeros((3, 2), np.float32), np.array([[0, 1, 2]]))


def build_dff(rig: Rig, parts: dict[int, R.Geom]) -> bytes:
    """Claude's clump with every atomic's geometry rebuilt (frames, atomics, materials, plugins kept). A frame the
    character has no triangles on gets one degenerate triangle (RW/PS2 instancing never sees an empty mesh)."""
    root, _ = R.parse(rig.raw)
    gl = root.first(R.GEOMLIST)
    geoms = gl.find(R.GEOMETRY)
    new = list(geoms)
    for fi, gi in rig.atomics:
        g = parts.get(fi) or _empty_geom()
        new[gi] = R.geometry_build(g, geoms[gi])
    it = iter(new)
    gl.kids = [next(it) if k.type == R.GEOMETRY else k for k in gl.kids]
    root.size_override = None
    return root.to_bytes() + rig.tail


def dff_parts(dff: bytes) -> dict:
    """Re-decode a written clump: triangles/vertices per frame (proves the writer's output parses)."""
    rig = Rig(dff)
    out = {}
    for fi, gi in rig.atomics:
        g = R.geometry_read(rig.geoms[gi])
        out[rig.frames[fi]["name"]] = {"vertices": len(g.pos), "triangles": len(g.tris)}
    return out


# --------------------------------------------------------------------------------------------------- textures
def txd_rasters(txd: bytes) -> list[R.Ps2Raster]:
    root, _ = R.parse(txd)
    return [R.texnative_read(t) for t in root.find(R.TEXNATIVE)]


def mip_levels(r: R.Ps2Raster) -> list[tuple[int, int, int]]:
    """(data offset of the pixels, width, height) for every stored level of an 8-bit raster (GIF headers skipped)."""
    hdrs = bool(r.fmt & 0x20000)
    pix_bytes = struct.unpack_from("<I", r.header, 48)[0]
    out, o, w, h, gif = [], 0, r.width, r.height, (0x50 if hdrs else 0)
    while w >= 1 and h >= 1 and o + gif + w * h <= pix_bytes:      # each stored level: [GIF packet] + w*h bytes
        out.append((o + gif, w, h))
        o += gif + w * h
        w, h = w // 2, h // 2
    return out or [(gif, r.width, r.height)]


def raster_write(r: R.Ps2Raster, rgba: np.ndarray) -> R.Ps2Raster:
    """New image into an 8-bit raster: top level via gta_rw.raster_set_indexed (palette + swizzle), lower stored mip
    levels re-quantised to the same palette so distance LODs don't show the old texture."""
    from PIL import Image
    idx, pal = R.quantize(rgba)
    new = R.raster_set_indexed(r, idx, pal)
    levels = mip_levels(r)
    if len(levels) <= 1:
        return new
    data = bytearray(new.data)
    palimg = Image.new("P", (1, 1))
    palimg.putpalette(pal[:, :3].reshape(-1).tolist())
    for start, w, h in levels[1:]:
        sm = Image.fromarray(np.ascontiguousarray(rgba[..., :3])).resize((w, h), Image.LANCZOS)
        li = np.array(sm.quantize(palette=palimg, dither=Image.Dither.NONE), np.uint8)
        rw, rh = struct.unpack_from("<II", data, start - 0x50 + 0x20) if r.fmt & 0x20000 else (w, h)
        flat = li.reshape(-1)
        if rw * rh * 4 == w * h and w >= 16 and h >= 4:
            buf = np.empty_like(flat)
            buf[R._swz8_map(w, h)] = flat
            flat = buf
        data[start:start + flat.size] = flat.tobytes()
    return R.Ps2Raster(r.name, r.mask, r.width, r.height, r.depth, r.fmt, r.header, bytes(data))


def build_txd(txd: bytes, atlases: list[np.ndarray]) -> bytes:
    root, tail = R.parse(txd)
    tns = root.find(R.TEXNATIVE)
    for tn, a in zip(tns, atlases):
        R.texnative_replace_data(tn, raster_write(R.texnative_read(tn), a))
    return root.to_bytes() + tail


# ------------------------------------------------------------------------------------------------------ build
def swap_files(disc: R.GtaDisc, src_model: Path, src_roles: dict, work: Path, blender: str | None = None,
               progress=None, skin: str = "player", roles: dict | None = None) -> dict:
    """New <skin>.dff + <skin>.txd bytes that fit their IMG slots (skin = one of SKINS)."""
    dname, tname = f"{skin}.dff", f"{skin}.txd"
    from .gta_stories_models import pack_atlases
    progress = progress or (lambda p, m: None)
    dff, txd = disc.entry(dname), disc.entry(tname)
    rig = Rig(dff, roles=roles)
    rasters = [r for r in txd_rasters(txd)]
    if not rasters or any(r.depth != 8 for r in rasters):
        raise ValueError(f"{tname} rasters {[(r.name, r.depth) for r in rasters]}: only 8-bit is written")
    budget = disc.slot_sectors(dname) * SECTOR
    src, tried = Path(src_model), []
    for attempt in range(5):
        progress(20 + 12 * attempt, f"Fitting onto Claude's {len(rig.frames)} frames")
        prims = retarget(rig, src, src_roles)
        atlases, maps = pack_atlases(prims, [(r.width, r.height) for r in rasters])
        if len(rasters) > 1:          # one texture per material in Claude's parts: keep every triangle on atlas 0
            maps = [(0, uv) for a, uv in maps]
        parts = part_geometries(rig, prims, [uv for _a, uv in maps])
        new_dff = build_dff(rig, parts)
        tris = sum(len(g.tris) for g in parts.values())
        tried.append({"triangles": tris, "bytes": len(new_dff)})
        if len(new_dff) <= budget:
            break
        if not blender:
            raise ValueError(f"{dname} {len(new_dff)} bytes > its {budget}-byte slot and no Blender to decimate")
        target = int(tris * budget / len(new_dff) * 0.92)
        from .re4gc_enemies import decimate
        progress(22 + 12 * attempt, f"Too big ({len(new_dff)} > {budget}): decimating to ~{target} triangles (Blender)")
        src = decimate(Path(src_model), Path(work) / f"_gta3_{skin}_dec_{attempt}.glb", target, blender)
    else:
        raise ValueError(f"{dname} doesn't fit its {budget}-byte slot: {tried}")
    new_txd = build_txd(txd, atlases[:len(rasters)])
    if len(new_txd) > disc.slot_sectors(tname) * SECTOR:
        raise ValueError(f"{tname} grew past its slot")
    return {"dff": new_dff, "txd": new_txd, "tried": tried, "parts": dff_parts(new_dff), "atlas": atlases[0],
            "source": str(src), "rasters": [(r.name, r.width, r.height, len(mip_levels(r))) for r in rasters],
            "skin": skin, "orig_sha256": {dname: _sha(dff), tname: _sha(txd)}}


def _sha(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def build_mod(cfg, game: dict, rom: Path, src_model: Path, roles: dict, name: str, progress=None, mod_roles: dict | None = None) -> dict:
    """The disc-image mod gta3_<slug>: a copy of the vanilla image with player.dff/.txd replaced in every IMG copy."""
    from . import filemods
    progress = progress or (lambda p, m: None)
    gid = game["game_id"]
    base = iso_from_rom(rom, filemods.base_dir(cfg, gid) / (Path(rom).stem + ".iso"), progress)
    work = Path(cfg.cache) / "characters_build" / name
    work.mkdir(parents=True, exist_ok=True)
    try:
        from .characters import _blender
        bl = _blender(cfg)
    except Exception:                    # noqa: BLE001 - decimation is optional
        bl = None
    disc = R.GtaDisc(base)
    fits, skipped = [], {}
    try:
        for skin in SKINS:
            if f"{skin}.dff" not in disc.index or f"{skin}.txd" not in disc.index:
                continue
            try:
                fits.append(swap_files(disc, Path(src_model), roles, work, bl, progress, skin=skin, roles=mod_roles))
            except ValueError as e:
                if skin == "player":
                    raise
                skipped[skin] = str(e)
    finally:
        disc.close()
    r = fits[0]
    out = filemods.mod_dir(cfg, gid, name)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    image = Path(base).name
    progress(75, f"Copying the disc image ({Path(base).stat().st_size >> 20} MB)")
    shutil.copyfile(base, out / image)
    d = R.GtaDisc(out / image, writable=True)
    try:
        writes = [w for f in fits for w in (d.replace(f"{f['skin']}.dff", f["dff"]), d.replace(f"{f['skin']}.txd", f["txd"]))]
    finally:
        d.close()
    chk = R.GtaDisc(out / image)
    try:
        back = {f"{f['skin']}.{k}": [_sha(chk.entry(f"{f['skin']}.{k}", c)[:len(f[k])]) for c in range(len(chk.imgs))]
                for f in fits for k in ("dff", "txd")}
    finally:
        chk.close()
    want = {f"{f['skin']}.{k}": _sha(f[k]) for f in fits for k in ("dff", "txd")}
    orig = {n: h for f in fits for n, h in f["orig_sha256"].items()}
    bad = {n: v for n, v in back.items() if set(v) != {want[n]}}
    if bad:
        raise RuntimeError(f"IMG copies didn't read back the new files: {bad}")
    (out / ".gbox-mod.json").write_text(json.dumps({
        "name": name, "game_id": gid, "image": image, "built": time.time(), "files": ["MODELS/GTA3.IMG", "MODELS/GTA3.DIR"],
        "entries": list(want), "source_sha256": orig, "new_sha256": want, "skins": [f["skin"] for f in fits],
        "skipped_skins": skipped}))
    try:
        from PIL import Image
        Image.fromarray(r["atlas"]).save(work / "atlas.png")
        R.clump_to_gltf(r["dff"], work / "preview.glb", None, name)
    except Exception:                    # noqa: BLE001 - previews are informational
        pass
    return {"mod": name, "image": image, "dir": str(out), "writes": writes, "tried": r["tried"], "parts": r["parts"],
            "rasters": r["rasters"], "source_sha256": orig, "new_sha256": want, "skins": [f["skin"] for f in fits],
            "skin_tried": {f["skin"]: f["tried"] for f in fits}, "skipped_skins": skipped}


# ------------------------------------------------------------------------------------------------ characters op=use
def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for GTA III PS2 slot=player: build gta3_<slug> (on the node holding the collection) unless
    it exists, record the target, launch it on the requesting session's node."""
    from . import characters as C
    from . import filemods
    gid, name = game["game_id"], f"gta3_{meta['slug']}"
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    have = name in {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = None
    if inp.rebuild or not have:
        roles = meta.get("rig", {}).get("roles")
        if not roles:
            raise ValueError(f"{meta['name']} has no body roles (rig.roles): can't fit it to Claude's frames")
        built = build_mod(ctx.config, game, C._rom(ctx, game), C._local_or_fetch(ctx, meta, meta["model"]), roles, name,
                          progress=ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                     "notes": "replaces Claude (player + prison playerp skins, .dff/.txd in every GTA3.IMG copy; his 17 frames and animations stay)"})
    res = {"mod": name, "build": built, "replaces": "Claude, the GTA III player (model 0, special model 'player')"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    return res | {"status": "launching", "launch_job": lj.get("id"), "node": node,
                  "message": f"GTA III mod {name} is launching; start a new game (a save state restores Claude from RAM)."}
