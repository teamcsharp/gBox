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

from . import psxdisc

GAME_IDS = {"f55555ee6513391b", "afd2fc507bb69843"}
MOD_NAME = "mgs_vr_hucast_native"
DISC_NAME = "Metal Gear Solid - VR Missions (USA)"
PLAYER_KMD_SHA256 = "5dda0c64dfef4523675fee16af56d7d119b8c4ddab43c20f912f2de33f810254"


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


def build(base: Path, replacement_kmd: Path, out_bin: Path, mint: Path,
          progress=lambda _p, _m: None) -> dict:
    """Build a bootable modded BIN/CUE from an owned raw disc and a fitted KMD."""
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
        donor = replacement_kmd.read_bytes()
        if not donor or len(donor) > len(own_kmd):
            raise ValueError(f"replacement KMD exceeds its {len(own_kmd)}-byte disc budget")
        if donor == own_kmd:
            raise ValueError("replacement KMD is identical to the original player model")
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
            "sectors_written": sectors, "kmd_sha256": hashlib.sha256(donor).hexdigest()}


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


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use: rebuild HUcast on Windows, then make it a saved Play choice."""
    from . import characters as chars, filemods
    if meta["slug"] != "hucast":
        raise ValueError("This MGS VR writer currently has a verified HUcast KMD only")
    gid = game["game_id"]
    folder = filemods.mod_dir(ctx.config, gid, MOD_NAME)
    marker = folder / ".gbox-mod.json"
    report = None
    if inp.rebuild or not marker.is_file():
        if chars.HOST_OS != "windows":
            worker = next((w["id"] for w in chars._api(ctx, "GET", "/api/workers")
                           if w.get("os") == "windows" and w.get("online")), None)
            if not worker:
                raise RuntimeError("No online Windows worker can build the MGS VR disc")
            j = chars._job(ctx, "characters", {"op": "use", "character": "hucast", "game_id": gid,
                                              "rebuild": True, "launch": False}, worker, 3600)
            if j.get("state") != "succeeded":
                raise RuntimeError(f"Windows MGS VR build failed: {j.get('error') or j.get('state')}")
            report = (j.get("output") or {}).get("result")
        else:
            donor = chars._local_or_fetch(ctx, meta, "targets/mgs_vr_snake_hucast.kmd")
            source = base_bin(ctx.config, ctx.progress)
            report = build(source, donor, folder / f"{DISC_NAME}.bin", _mint(ctx.config), ctx.progress)
            marker.write_text(json.dumps({"name": MOD_NAME, "game_id": gid, "image": f"{DISC_NAME}.cue",
                                          "built": time.time(), "character": "hucast",
                                          "files": ["MGS/STAGE.DIR: init/39213.kmd"], "report": report}))
            _publish(ctx, folder, gid)
        chars._api(ctx, "POST", f"/api/characters/hucast/targets", json={"game_id": gid, "slot": "player",
                   "mod": MOD_NAME, "nodes": ["windows"],
                   "notes": "Native PS1 player KMD built; visual gameplay replacement still needs verification."})
        chars._api(ctx, "POST", "/api/mods", json={"title": "HUcast in Metal Gear Solid VR Missions (Sneaking Mode)",
                   "calls": [{"tool": "@launch", "input": {"mod": MOD_NAME}}], "game_id": gid,
                   "game_title": game["title"], "desc": "Experimental native PS1 player KMD. Gameplay appearance is unverified.",
                   "verified": False, "requests": [848]})
    launched = chars._launch(ctx, gid, MOD_NAME, "windows") if inp.launch else None
    return {"status": "built" if report else "ready", "mod": MOD_NAME, "build": report,
            "launch": launched, "message": "HUcast PS1 player model is selectable for VR Missions."}
