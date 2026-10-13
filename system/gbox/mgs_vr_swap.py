"""Native player-model disc writer for the US PS1 Metal Gear Solid games.

The input KMD must already be rigged to the game's 16-bone player skeleton.
This writer keeps the original disc and original KMD size, then rebuilds the
PSX DAR/STG/DIR containers and fixes the changed raw-disc sectors' ECC.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import mgs_kmd, mgs_pcc, mgs_vr_tex, psxdisc

GAME_IDS = {"f55555ee6513391b", "afd2fc507bb69843"}
MOD_NAME = "mgs_vr_hucast_native"
DISC_NAME = "Metal Gear Solid - VR Missions (USA)"
PLAYER_KMD_SHA256 = "5dda0c64dfef4523675fee16af56d7d119b8c4ddab43c20f912f2de33f810254"
# Snake's 16 KMD objects = motion bones (left = +X, up = +Y, front = +Z, like sm64_swap's frame).
SNAKE_ROLES = {"hip": 0, "chest": 1, "neck": 5, "head": 6,
               "r_upper": 2, "r_fore": 3, "r_hand": 4, "l_upper": 7, "l_fore": 8, "l_hand": 9,
               "r_thigh": 10, "r_shin": 11, "r_foot": 12, "l_thigh": 13, "l_shin": 14, "l_foot": 15}
FIT_TEXTURE_OBJECT = 0   # untextured fit (fit_kmd): faces reuse Snake's waist texture/uv

# Character models of the US disc (docs/mgs_vr_decomp.md).  Names are GV_StrCode hashes; "16 objects" models share
# the 16-bone body layout.  Only "player" has a writer; the others are listed so requests can name them.
SLOTS = {
    "player": {"model": 39213, "name": "snake", "where": "init.stg 0_0.dar, every stage", "objects": 16,
               "motion": "snake (init 39213.oar)", "textures": "init.stg 1_0.dar, 28 slots in CLUTs 784,226 / 768,226",
               "loaded_by": "player actor 0x8005DDC0 (GCL param m, default GV_StrCode('snake')); no mission script "
                            "sets m, so Sneaking, Weapon, Advanced and special stages all use it",
               "writer": "mgs_vr_swap.fit_kmd_textured"},
    "vr_soldier": {"model": 38582, "bytes": 9936, "objects": 16, "motion": 0xA8A1,
                   "where": "a stage DAR of most mission stages (vr_*, vab_*, vcd_*, vefgh_*, vijkl_*)",
                   "loaded_by": "the soldier actor of each stage overlay (GM_InitObject at 0x800C5D7C in vr_sud03)",
                   "writer": None},
    "soldier_extra": {"model": 55267, "bytes": 6060, "objects": 16, "where": "most mission stages",
                      "loaded_by": "soldier actor when its GCL param y is 1 (0x800C5E0C in vr_sud03)", "writer": None},
    "stage_specific": {"models": {37617: "vcd_n01-03", 31475: "vcd_n05 (camera_def2)", 46243: "vijkl_01/03/06/10",
                                  37567: "vijkl_01/03/06/10", 26944: "vefgh_10"}, "objects": 16, "writer": None,
                       "note": "the Ninja missions' model is among these or loaded under a name not yet resolved"},
}


def snake_target(original: mgs_kmd.Kmd) -> dict:
    """sm64_swap.retarget's target dict for Snake's bind pose (KMD joints carry no rotation)."""
    import numpy as np
    T = np.zeros((len(original.objects), 3))
    for i, o in enumerate(original.objects):
        T[i] = (T[o.parent] if o.parent >= 0 else 0) + np.array(o.pos, float)
    world = np.array([[v[0] + T[i][0], v[1] + T[i][1], v[2] + T[i][2]]
                      for i, o in enumerate(original.objects) for v in o.vertices], float)
    head = np.array([v[:3] for v in original.objects[SNAKE_ROLES["head"]].vertices], float)
    ground = float(world[:, 1].min())
    return {"T": T, "ground": ground, "head_h": float(np.ptp(head[:, 1])) if len(head) else 200.0,
            "height": float(world[:, 1].max() - ground), "roles": SNAKE_ROLES}


def _object_mesh(pos, nrm, tris, cell: float):
    """Vertex-cluster one object's triangles on a *cell* grid -> (verts, normals, tris, source triangle index)."""
    import numpy as np
    if not len(tris):
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), int), np.zeros(0, int)
    key = np.round(pos / cell).astype(np.int64) if cell > 0 else np.arange(len(pos))[:, None]
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    n = inv.max() + 1
    vp = np.zeros((n, 3)); vn = np.zeros((n, 3)); cnt = np.zeros(n)
    np.add.at(vp, inv, pos); np.add.at(vn, inv, nrm); np.add.at(cnt, inv, 1)
    vp /= cnt[:, None]
    t = inv[tris]
    keep = np.nonzero((t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2]))[0]
    t = t[keep]
    if len(t):
        first = np.sort(np.unique(np.sort(t, 1), axis=0, return_index=True)[1])
        t, keep = t[first], keep[first]
    used = np.unique(t)
    remap = -np.ones(n, int); remap[used] = np.arange(len(used))
    return vp[used], vn[used], remap[t], keep


WELD_RADIUS = 48.0   # KMD units (Snake is ~1800 tall): seam vertices this close to the parent are welded


def fit_kmd(original_bytes: bytes, glb: Path, roles: dict, budget: int | None = None,
            weld_radius: float = WELD_RADIUS) -> tuple[bytes, dict]:
    """fit_kmd_textured without textures: every face wears Snake's waist texture (the first fitted build)."""
    data, rep, _ = fit_kmd_textured(original_bytes, glb, roles, None, budget, weld_radius)
    return data, rep


def fit_kmd_textured(original_bytes: bytes, glb: Path, roles: dict, textures: dict | None,
                     budget: int | None = None, weld_radius: float = WELD_RADIUS) -> tuple[bytes, dict, dict]:
    """Rigidly retarget a skinned library GLB onto Snake's 16 KMD objects.

    Every vertex goes to the Snake joint sm64_swap.retarget assigns it; it is stored
    in that object's local frame (world - joint).  No welds are emitted, so no
    export flags are needed.  Objects are vertex-clustered until the KMD fits
    *budget* bytes (the disc allocation of the original) and the u8 vertex /
    7-bit normal indices.  With *weld_radius*, child vertices that lie that close
    to a parent vertex are welded to it (mgs_kmd.weld_seams) so joints stay shut.
    With *textures* ({"snake": {hash: Pcc}, "archive": {hash: pcc bytes}}) every face
    keeps the library model's own image and UVs, painted into Snake's texture slots
    (gbox.mgs_vr_tex); the repainted textures are the third value returned.
    """
    import numpy as np
    from . import sm64_swap as S
    original = mgs_kmd.loads(original_bytes)
    budget = budget or len(original_bytes)
    tgt = snake_target(original)
    rig = S.load_rig(Path(glb), roles)
    prims, rep = S.retarget(rig, tgt, None, jmap=SNAKE_ROLES)
    count = len(original.objects)
    per = {i: ([], [], []) for i in range(count)}
    attrs = {i: [] for i in range(count)}                 # per fitted triangle: (image key, image, uv (3,2), colour)
    base = {i: 0 for i in range(count)}
    for p in prims:
        if p.get("prop"):
            continue
        J = p["J"][:, 0]
        img = p.get("tex")
        key = id(img) if img is not None else None
        uvs = np.asarray(p["uv"] if p.get("uv") is not None else np.zeros((len(p["pos"]), 2)), float)
        for tri in np.asarray(p["tris"]).reshape(-1, 3):
            j = int(np.bincount(J[tri], minlength=count).argmax())
            P, N, F = per[j]
            P.extend((p["pos"][tri] - tgt["T"][j]).tolist())
            N.extend(p["nrm"][tri].tolist())
            F.append([base[j], base[j] + 1, base[j] + 2])
            attrs[j].append((key, img, uvs[tri], tuple(p.get("color") or (255, 255, 255))))
            base[j] += 3
    src = original.objects[FIT_TEXTURE_OBJECT]
    tex, uv = src.textures[0], src.uvs[0]
    painted, face_tex = {}, {i: None for i in range(count)}
    if textures:
        from . import mgs_vr_tex
        flat = [a for i in range(count) for a in attrs[i]]
        painted, per_face, tex_rep = mgs_vr_tex.paint(textures["snake"], textures["archive"], flat)
        k = 0
        for i in range(count):
            face_tex[i] = per_face[k:k + len(attrs[i])]
            k += len(attrs[i])
        rep["textures"] = tex_rep
    extent = float(np.ptp(np.concatenate([np.asarray(per[i][0]) for i in per if per[i][0]]), 0).max())
    for step in range(60):
        cell = 0.0 if step == 0 else extent * 0.004 * (1.12 ** step)
        objs = []
        ok = True
        for i, o in enumerate(original.objects):
            P, N, F = (np.asarray(a, float) for a in per[i])
            if not len(F):
                objs.append(mgs_kmd.KmdObject(o.flags, o.pos, o.parent, o.unknown, bbox=o.bbox))
                continue
            vp, vn, t, keep = _object_mesh(P, N, F.astype(int), cell)
            if len(vp) > 255 or not len(t):
                ok = ok and bool(len(t))
                if len(vp) > 255:
                    ok = False
                    break
            nq = np.round(vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-9) * 3) / 3
            nkeys, ninv = np.unique(nq, axis=0, return_inverse=True)
            ninv = ninv.reshape(-1)
            if len(nkeys) > 127:
                ok = False
                break
            nunit = nkeys / np.maximum(np.linalg.norm(nkeys, axis=1, keepdims=True), 1e-9)
            verts = [(int(round(x)), int(round(y)), int(round(z)), -1) for x, y, z in np.clip(vp, -32767, 32767)]
            normals = [(int(round(x * 4096)), int(round(y * 4096)), int(round(z * 4096)), 0) for x, y, z in nunit]
            faces = [(int(a), int(b), int(b), int(c)) for a, b, c in t]       # a triangle is a quad a,b,b,c
            fn = [(int(ninv[a]), int(ninv[b]), int(ninv[b]), int(ninv[c])) for a, b, c in t]
            if face_tex[i] is not None:
                ftex = [face_tex[i][int(s)][0] for s in keep]
                fuv = [face_tex[i][int(s)][1] for s in keep]
            else:
                ftex, fuv = [tex] * len(faces), [uv] * len(faces)
            ko = mgs_kmd.KmdObject(o.flags, o.pos, o.parent, o.unknown, verts, normals, faces, fn, fuv, ftex)
            ko.bbox = ko.computed_bbox()
            objs.append(ko)
        if not ok:
            continue
        model = mgs_kmd.Kmd(original.bones, original.bbox, objs)
        welds = 0
        if weld_radius:
            # welded child vertices follow the parent bone, so joints stay shut when Snake's motion plays
            model, welds = mgs_kmd.weld_seams(original, model, radius=weld_radius)
        data = mgs_kmd.dumps(model, recompute_bbox=True)
        if len(data) <= budget:
            issues = mgs_kmd.check_compatible(original, model, raw=data)
            if issues:
                raise ValueError("fitted KMD breaks the game contract: " + "; ".join(issues[:5]))
            rep.update({"kmd_bytes": len(data), "budget": budget, "cluster_cell": round(cell, 2),
                        "triangles": sum(len(o.faces) for o in objs), "welds": welds,
                        "per_object_triangles": [len(o.faces) for o in objs], "textured": bool(painted)})
            return data, rep, painted
    raise ValueError(f"could not fit the model into the {budget}-byte KMD allocation")


def _mint(cfg) -> Path:
    candidates = [os.environ.get("GBOX_METAL_MINT"),
                  Path(cfg.cache).parent / "runtime" / "tools" / "metal_mint" / "MetalMintSolid.exe",
                  shutil.which("MetalMintSolid")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("MetalMintSolid is required to rebuild the MGS PS1 stage archive")


def _run(mint: Path, *args: str | Path) -> None:
    result = subprocess.run([str(mint), *(str(a) for a in args)], capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"MetalMintSolid {' '.join(map(str, args[:2]))}: {(result.stderr or result.stdout)[-1200:]}")


def base_bin(cfg, progress=lambda _p, _m: None) -> Path:
    """Unpack the operator's QuickSwap US disc once; both catalog entries use it."""
    archive = cfg.library("quickswap-root").root() / f"{DISC_NAME}.7z"
    if not archive.is_file():
        raise FileNotFoundError(f"VR Missions source archive is not reachable: {archive}")
    out = Path(cfg.cache) / "modbase" / "mgs_vr_us"
    image = out / f"{DISC_NAME}.bin"
    if image.is_file() and image.stat().st_size == 492487632:
        return image
    seven_zip = shutil.which("7z") or Path(r"C:\Program Files\7-Zip\7z.exe")
    if not seven_zip or not Path(seven_zip).is_file():
        raise FileNotFoundError("7-Zip is required to unpack the VR Missions source archive")
    out.mkdir(parents=True, exist_ok=True)
    progress(5, "Unpacking the original VR Missions disc")
    result = subprocess.run([str(seven_zip), "x", "-y", f"-o{out}", str(archive)],
                            capture_output=True, text=True, timeout=1800)
    if result.returncode or not image.is_file():
        raise RuntimeError(f"VR Missions archive extraction failed: {(result.stderr or result.stdout)[-1200:]}")
    return image


def decode_original_player(cfg, out_glb: Path, progress=lambda _p, _m: None) -> Path:
    """Read Snake's original VR Missions KMD and its PS1 textures into a textured GLB."""
    base = base_bin(cfg, progress)
    disc = psxdisc.RawBin(base, writable=False)
    try:
        stage_dir = disc.read("MGS/STAGE.DIR")
    finally:
        disc.close()
    if len(stage_dir) not in (72593408, 71892992):
        raise ValueError("this MGS PS1 disc has an unknown STAGE.DIR size")
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    mint = _mint(cfg)
    with tempfile.TemporaryDirectory(prefix="mgs_vr_read_", dir=out_glb.parent) as temp:
        work = Path(temp)
        (work / "stage.dir").write_bytes(stage_dir)
        for name in ("stage", "init", "models", "texture_archive", "textures"):
            (work / name).mkdir()
        progress(20, "Opening the VR Missions stage archive")
        _run(mint, "dir", "extract", work / "stage.dir", work / "stage")
        _run(mint, "stg", "extract", work / "stage" / "init.stg", work / "init")
        _run(mint, "dar", "extract", work / "init" / "0_0.dar", work / "models", "--platform", "Psx")
        original = work / "models" / "39213.kmd"
        if hashlib.sha256(original.read_bytes()).hexdigest() != PLAYER_KMD_SHA256:
            raise ValueError("Snake KMD differs from the known US VR Missions revision")
        progress(60, "Decoding Snake's PS1 texture archive")
        _run(mint, "dar", "extract", work / "init" / "1_0.dar", work / "texture_archive", "--platform", "Psx")
        _run(mint, "pcx", "batchdecode", work / "texture_archive", work / "textures")
        progress(80, "Converting the original Snake mesh and textures to glTF")
        _run(mint, "kmd", "decode", original, work / "snake.glb", "--textures", work / "textures")
        if (work / "snake.glb").read_bytes()[:4] != b"glTF":
            raise ValueError("MetalMintSolid did not produce a GLB model")
        shutil.copy2(work / "snake.glb", out_glb)
    progress(100, "Original Snake model and textures decoded")
    return out_glb


def build(base: Path, replacement_kmd: Path | None, out_bin: Path, mint: Path,
          progress=lambda _p, _m: None, fit=None, textures: bool = False) -> dict:
    """Build a bootable modded BIN/CUE from an owned raw disc and a fitted KMD.

    *fit*, when given, is called with the disc's own player KMD bytes and returns
    the replacement (see :func:`fit_kmd`); otherwise *replacement_kmd* is read.
    With *textures*, fit is called as fit(kmd, {"snake", "archive"}) and returns
    (kmd, {hash: repainted pcc}); the texture DAR (init.stg entry 1) is repacked to
    its original size and patched in as well (gbox.mgs_vr_tex).
    """
    original = psxdisc.RawBin(base, writable=False)
    try:
        stage_dir = original.read("MGS/STAGE.DIR")
    finally:
        original.close()
    if len(stage_dir) not in (72593408, 71892992):
        raise ValueError("this MGS PS1 disc has an unknown STAGE.DIR size")
    work_parent = out_bin.parent
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mgs_vr_", dir=work_parent) as temp:
        work = Path(temp)
        directory = work / "stage.dir"
        directory.write_bytes(stage_dir)
        progress(25, "Extracting the PS1 stage containers")
        # MetalMintSolid creates a relative directory when a requested output
        # directory does not exist, so create each absolute target first.
        for name in ("stage", "init", "dar"):
            (work / name).mkdir()
        _run(mint, "dir", "extract", directory, work / "stage")
        init = work / "stage" / "init.stg"
        if not init.is_file():
            raise ValueError("init.stg was absent from the stage directory")
        init_bytes = init.read_bytes()
        init_offset = stage_dir.find(init_bytes)
        if init_offset < 0 or init_offset % 2048 or stage_dir.find(init_bytes, init_offset + 1) >= 0:
            raise ValueError("init.stg does not have one aligned location in the stage directory")
        _run(mint, "stg", "extract", init, work / "init")
        _run(mint, "dar", "extract", work / "init" / "0_0.dar", work / "dar", "--platform", "Psx")
        model = work / "dar" / "39213.kmd"
        own_kmd = model.read_bytes()
        if hashlib.sha256(own_kmd).hexdigest() != PLAYER_KMD_SHA256:
            raise ValueError("player KMD differs from the verified US VR Missions revision")
        painted = {}
        tex_dar = (work / "init" / "1_0.dar").read_bytes() if (work / "init" / "1_0.dar").is_file() else b""
        if fit and textures:
            if not tex_dar:
                raise ValueError("init.stg has no texture archive (1_0.dar)")
            archive = {h: body for h, _e, body in mgs_vr_tex.parse_dar(tex_dar)}
            names = {t for o in mgs_kmd.loads(own_kmd).objects for t in o.textures}
            donor, painted = fit(own_kmd, {"snake": {h: mgs_pcc.loads(archive[h]) for h in names},
                                           "archive": archive})
        else:
            donor = fit(own_kmd) if fit else replacement_kmd.read_bytes()
        if fit:
            replacement_kmd = work / "replacement.kmd"
            replacement_kmd.write_bytes(donor)
        if not donor or len(donor) > len(own_kmd):
            raise ValueError(f"replacement KMD exceeds its {len(own_kmd)}-byte disc budget")
        if donor == own_kmd:
            raise ValueError("replacement KMD is identical to the original player model")
        # The game's own contract (gbox.mgs_kmd): same skeleton records, word-aligned
        # SVECTOR arrays, in-range welds and weld-export flags.  The first HUcast KMD
        # broke the alignment and flag rules and corrupted the whole frame (#848).
        try:
            issues = mgs_kmd.check_compatible(mgs_kmd.loads(own_kmd), mgs_kmd.loads(donor), raw=donor)
        except ValueError as exc:
            issues = [f"unreadable KMD: {exc}"]
        if issues:
            raise ValueError("replacement KMD would break the game: " + "; ".join(issues[:6]))
        # Structural validation: MetalMintSolid must be able to decode the donor as a PS1 KMD.
        # A malformed KMD passes the size check but will hang the game's loader (black screen / hung core).
        progress(33, "Validating replacement KMD structure")
        validate_glb = work / "validate.glb"
        try:
            _run(mint, "kmd", "decode", replacement_kmd, validate_glb)
        except RuntimeError as exc:
            raise ValueError(f"replacement KMD failed KMD decode validation: {exc}") from exc
        if not validate_glb.is_file() or validate_glb.read_bytes()[:4] != b"glTF":
            raise ValueError("replacement KMD decoded to an invalid GLB")
        model.write_bytes(donor.ljust(len(own_kmd), b"\0"))
        order = work / "dar" / "order.txt"
        if not order.is_file():
            raise ValueError("DAR extraction omitted its archive order")
        progress(45, "Rebuilding the player model archive")
        new_dar = work / "player.dar"
        _run(mint, "dar", "pack", work / "dar", new_dar, "--platform", "Psx", "--order", order)
        if new_dar.stat().st_size != (work / "init" / "0_0.dar").stat().st_size:
            raise ValueError("replacement DAR changed its stage allocation")
        new_init = work / "new_init.stg"
        _run(mint, "stg", "patch", new_dar, init, "0", new_init)
        if painted:
            progress(55, "Repainting Snake's texture slots with the character's own textures")
            entries = mgs_vr_tex.parse_dar(tex_dar)
            for h, body in painted.items():
                mgs_pcc.loads(body)                        # every repainted texture must decode
            new_tex = work / "textures.dar"
            new_tex.write_bytes(mgs_vr_tex.pack_dar([(h, e, painted.get(h, b)) for h, e, b in entries], len(tex_dar)))
            textured_init = work / "new_init_tex.stg"
            _run(mint, "stg", "patch", new_tex, new_init, "1", textured_init)
            new_init = textured_init
        patched_init = new_init.read_bytes()
        if len(patched_init) != len(init_bytes):
            raise ValueError("replacement init.stg changed its directory allocation")
        changed = bytearray(stage_dir)
        changed[init_offset:init_offset + len(init_bytes)] = patched_init
        progress(65, "Copying the original disc before the sector patch")
        part = out_bin.with_name(out_bin.name + ".part")
        shutil.copyfile(base, part)
        sectors = 0
        try:
            disc = psxdisc.RawBin(part)
            try:
                # Only changed 2 KiB sectors need new EDC/ECC (eight for HUcast).
                for off in range(0, len(stage_dir), 2048):
                    if changed[off:off + 2048] != stage_dir[off:off + 2048]:
                        sectors += disc.write_file("MGS/STAGE.DIR", off, changed[off:off + 2048])
            finally:
                disc.close()
            os.replace(part, out_bin)
        finally:
            part.unlink(missing_ok=True)
    out_bin.with_suffix(".cue").write_text(
        f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    progress(95, f"Bootable disc ready; {sectors} raw sectors patched")
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")),
            "sectors_written": sectors, "kmd_sha256": hashlib.sha256(donor).hexdigest(),
            "textures_repainted": sorted(painted)}


def _publish(ctx, folder: Path, gid: str, mod_name: str = MOD_NAME) -> None:
    """Send a newly built mod to the central collection, including same-size rebuilds."""
    import httpx

    if not ctx.server:
        return
    url = f"{ctx.server}/api/modfiles/{gid}/{mod_name}"
    response = httpx.get(url, headers=ctx.headers, timeout=60)
    if response.status_code not in (200, 404):
        response.raise_for_status()
    have = {f["path"]: f for f in response.json().get("files", [])} if response.status_code == 200 else {}
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name == ".gbox-mod.json")
    for file in files:
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        old = have.get(file.name) or {}
        if old.get("sha256") == digest and old.get("size") == file.stat().st_size:
            continue
        with file.open("rb") as stream:
            result = httpx.put(f"{url}/file/{file.name}", headers=ctx.headers,
                               content=stream, timeout=1200)
        result.raise_for_status()


def mod_name(slug: str) -> str:
    """The fitted build gets its own name; the old hand-made HUcast KMD build stays rollback-only."""
    return f"mgs_vr_{slug}_fit"


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use: retarget the library model onto Snake's KMD, rebuild the disc, offer it as Play."""
    from . import characters as chars, filemods, oot_swap
    slug = meta["slug"]
    name = mod_name(slug)
    gid = game["game_id"]
    folder = filemods.mod_dir(ctx.config, gid, name)
    marker = folder / ".gbox-mod.json"
    report = None
    try:
        textured = marker.is_file() and bool(json.loads(marker.read_text()).get("textured"))
    except ValueError:
        textured = False
    if inp.rebuild or not textured:                       # builds before #848's textures wore Snake's waist texture
        if chars.HOST_OS != "windows" and not os.environ.get("GBOX_METAL_MINT"):
            worker = next((w["id"] for w in chars._api(ctx, "GET", "/api/workers")
                           if w.get("os") == "windows" and w.get("online")), None)
            if not worker:
                raise RuntimeError("No online Windows worker can build the MGS VR disc")
            j = chars._job(ctx, "characters", {"op": "use", "character": slug, "game_id": gid,
                                              "rebuild": True, "launch": False}, worker, 3600)
            if j.get("state") != "succeeded":
                raise RuntimeError(f"Windows MGS VR build failed: {j.get('error') or j.get('state')}")
            report = (j.get("output") or {}).get("result")
        else:
            glb = chars._local_or_fetch(ctx, meta, meta["model"])
            roles = oot_swap.roles_of(meta, glb)
            fit_report = {}

            def fit(own: bytes, tex: dict):
                data, rep, painted = fit_kmd_textured(own, glb, roles, tex)
                fit_report.update(rep)
                return data, painted
            source = base_bin(ctx.config, ctx.progress)
            report = build(source, None, folder / f"{DISC_NAME}.bin", _mint(ctx.config), ctx.progress, fit=fit,
                           textures=True)
            report["fit"] = fit_report
            marker.write_text(json.dumps({"name": name, "game_id": gid, "image": f"{DISC_NAME}.cue",
                                          "built": time.time(), "character": slug, "textured": True,
                                          "files": ["MGS/STAGE.DIR: init/39213.kmd",
                                                    "MGS/STAGE.DIR: init/1_0.dar (Snake's texture slots)"],
                                          "report": report}, default=str))
            _publish(ctx, folder, gid, name)
        chars._api(ctx, "POST", f"/api/characters/{slug}/targets", json={"game_id": gid, "slot": "player",
                   "mod": name, "nodes": ["windows"],
                   "notes": "Native PS1 player KMD fitted onto Snake's 16 bones, its own textures repainted into Snake's texture slots; gameplay verification pending."})
        chars._api(ctx, "POST", "/api/mods", json={"title": f"{meta.get('name', slug)} in Metal Gear Solid VR Missions",
                   "calls": [{"tool": "@launch", "input": {"mod": name}}], "game_id": gid,
                   "game_title": game["title"], "desc": "Native PS1 player KMD retargeted onto Snake's skeleton.",
                   "verified": False, "requests": [848]})
    launched = chars._launch(ctx, gid, name, "windows") if inp.launch else None
    return {"status": "built" if report else "ready", "mod": name, "build": report,
            "launch": launched, "message": f"{meta.get('name', slug)} PS1 player model is selectable for VR Missions."}
