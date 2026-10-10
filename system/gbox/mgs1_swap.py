"""Native HUcast player-model disc writer for US Metal Gear Solid, disc 1."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import mgs_vr_swap as ps1_writer

GAME_IDS = {"f27552db74dffdeb", "b13795ef235edee3"}
MOD_NAME = "mgs1_hucast_native"
DISC_NAME = "Metal Gear Solid (USA) (Disc 1) (Rev 1)"
DISC_BYTES = 705614112


def base_bin(cfg, progress=lambda _p, _m: None) -> Path:
    archive = cfg.library("quickswap-ps1").root() / f"{DISC_NAME}.7z"
    if not archive.is_file():
        raise FileNotFoundError(f"MGS disc 1 source archive is not reachable: {archive}")
    out = Path(cfg.cache) / "modbase" / "mgs1_us"
    image = out / DISC_NAME / f"{DISC_NAME}.bin"
    if image.is_file() and image.stat().st_size == DISC_BYTES:
        return image
    seven_zip = shutil.which("7z") or Path(r"C:\Program Files\7-Zip\7z.exe")
    if not seven_zip or not Path(seven_zip).is_file():
        raise FileNotFoundError("7-Zip is required to unpack the MGS disc 1 archive")
    out.mkdir(parents=True, exist_ok=True)
    progress(5, "Unpacking the original Metal Gear Solid disc 1")
    result = subprocess.run([str(seven_zip), "x", "-y", f"-o{out}", str(archive)],
                            capture_output=True, text=True, timeout=1800)
    if result.returncode or not image.is_file() or image.stat().st_size != DISC_BYTES:
        raise RuntimeError(f"MGS disc 1 extraction failed: {(result.stderr or result.stdout)[-1200:]}")
    return image


def use(ctx, meta: dict, game: dict, inp) -> dict:
    from . import characters as chars, filemods
    if meta["slug"] != "hucast":
        raise ValueError("This MGS disc writer currently has a verified HUcast KMD only")
    gid = game["game_id"]
    folder = filemods.mod_dir(ctx.config, gid, MOD_NAME)
    marker = folder / ".gbox-mod.json"
    report = None
    if inp.rebuild or not marker.is_file():
        if chars.HOST_OS != "windows":
            workers = [w for w in chars._api(ctx, "GET", "/api/workers") if w.get("os") == "windows" and w.get("online")]
            worker = next((w["id"] for w in workers if w.get("name") == "JAYBUILTFINALE"),
                          workers[0]["id"] if workers else None)
            if not worker:
                raise RuntimeError("No online Windows worker can build the MGS disc")
            j = chars._job(ctx, "characters", {"op": "use", "character": "hucast", "game_id": gid,
                                              "rebuild": True, "launch": False}, worker, 3600)
            if j.get("state") != "succeeded":
                raise RuntimeError(f"Windows MGS disc build failed: {j.get('error') or j.get('state')}")
            report = (j.get("output") or {}).get("result")
        else:
            donor = chars._local_or_fetch(ctx, meta, "targets/mgs_vr_snake_hucast.kmd")
            source = base_bin(ctx.config, ctx.progress)
            report = ps1_writer.build(source, donor, folder / f"{DISC_NAME}.bin",
                                      ps1_writer._mint(ctx.config), ctx.progress)
            marker.write_text(json.dumps({"name": MOD_NAME, "game_id": gid, "image": f"{DISC_NAME}.cue",
                                          "built": time.time(), "character": "hucast",
                                          "files": ["MGS/STAGE.DIR: init/39213.kmd"], "report": report}))
            ps1_writer._publish(ctx, folder, gid, MOD_NAME)
        chars._api(ctx, "POST", "/api/characters/hucast/targets", json={"game_id": gid, "slot": "player",
                   "mod": MOD_NAME, "nodes": ["windows"],
                   "notes": "Experimental PS1 init/snake KMD patch; first dock scene did not show a visible player change."})
        chars._api(ctx, "POST", "/api/mods", json={"title": "Experimental HUcast in Metal Gear Solid (Disc 1)",
                   "calls": [{"tool": "@launch", "input": {"mod": MOD_NAME}}], "game_id": gid,
                   "game_title": game["title"], "desc": "Experimental Snake KMD disc patch. The first dock room still showed the original player in a gameplay comparison.",
                   "verified": False, "requests": [855]})
    launched = chars._launch(ctx, gid, MOD_NAME, "windows") if inp.launch else None
    return {"status": "built" if report else "ready", "mod": MOD_NAME, "build": report,
            "launch": launched, "message": "Experimental MGS disc patch is selectable, but a visible player swap is not verified."}
