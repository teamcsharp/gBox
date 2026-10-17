"""Render a 3D model (GLB) into sprite frames from a game's camera, with Blender.

    um render3d model.glb out/ --preset aoe2 --length 80 --anims idle:10:bob,walk:12:bob,attack:16:lunge,death:20:die --shadows
    um render3d model.glb out/ --preset side --canvas 128 --length 110            # platformer: facing right + left
    um render3d model.glb out/ --preset iso8 --canvas 256x256 --length 150 --engine eevee

This is how the AoE2 San Franciscans units were made: fal concept art -> `um fal model3d` (image-to-3D)
-> these renders -> the engine's sprite format. Rendering from 3D keeps every facing and frame consistent,
which per-frame image generation can't. Presets (camera elevation, headings, direction order):
  aoe2      ortho 30 deg, 16 headings clockwise from east (AoE2 DE / Genie unit order)
  iso8      ortho 30 deg (2:1 diamond tiles), 8 headings clockwise from east
  trueiso   ortho 35.264 deg, 8 headings
  topdown   ortho 90 deg, 8 headings (twin-stick / top-down shooters)
  side      ortho 0 deg, 2 headings: facing right, facing left (platformers, Terraria-style)
  turntable persp 20 deg, 24 headings (icons, previews, promo spins)
Needs Blender on PATH (or BLENDER=/path/to/blender). Frames: <out>/<anim>_<heading>_<frame>.png (+ _s shadow pass).
Pack them with `um sprite sheet`, or with an engine-specific writer (examples/aoe2-de-civ/sld.py).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import die, parse_size

PRESETS = {
    "aoe2": dict(type="ortho", elevation_deg=30, headings=16, start_deg=0, clockwise=True),
    "iso8": dict(type="ortho", elevation_deg=30, headings=8, start_deg=0, clockwise=True),
    "trueiso": dict(type="ortho", elevation_deg=35.264, headings=8, start_deg=0, clockwise=True),
    "topdown": dict(type="ortho", elevation_deg=89.9, headings=8, start_deg=0, clockwise=True),
    "side": dict(type="ortho", elevation_deg=0.01, headings=2, start_deg=0, clockwise=True),
    "turntable": dict(type="persp", elevation_deg=20, headings=24, start_deg=0, clockwise=False, fov_deg=30),
}
MOTIONS = {
    "bob": dict(kind="bob", amp=1.0, cycles=1), "walk": dict(kind="bob", amp=0.8, pitch=0.8, cycles=2),
    "lunge": dict(kind="lunge", dist=12, pitch=-3), "die": dict(kind="die", roll=80, sink=3), "wreck": dict(kind="wreck", roll=80, sink=3),
    "spin": dict(kind="spin", turns=1), "still": None,
}


def blender_bin() -> str:
    b = os.environ.get("BLENDER") or shutil.which("blender")
    if not b:
        for c in ("/Applications/Blender.app/Contents/MacOS/Blender", r"C:\Program Files\Blender Foundation\Blender\blender.exe"):
            if Path(c).exists():
                return c
        die("Blender not found: install it (blender.org, or `snap install blender --classic`) or set BLENDER=/path/to/blender")
    return b


def parse_anims(spec: str) -> dict:
    """'idle:10:bob,walk:12:walk,death:20:die' -> {name: {frames, motion}}"""
    out = {}
    for part in spec.split(","):
        bits = part.split(":")
        name, frames = bits[0], int(bits[1]) if len(bits) > 1 else 1
        motion = MOTIONS.get(bits[2] if len(bits) > 2 else "still", None)
        out[name] = dict(frames=frames, motion=motion)
    return out


def render(glb: str, out_dir: str, preset: str = "aoe2", canvas="200", length: float = 80, forward_yaw: float = 0, anims="idle:1",
           shadows=False, samples=40, engine="cycles", elevation=None, headings=None, sun=4.0, ambient=0.9, ground_y=None, measure="length",
           blender: str | None = None, timeout: float | None = None, max_images: int | None = None):
    # gBox: blender (which exe), timeout (seconds) and max_images (refuse oversized jobs) are added parameters
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cam = dict(PRESETS[preset])
    if elevation is not None:
        cam["elevation_deg"] = elevation
    if headings is not None:
        cam["headings"] = headings
    w, h = parse_size(str(canvas))
    cfg = dict(glb=str(Path(glb).resolve()), out_dir=str(out), canvas=[w, h], length_px=length, forward_yaw_deg=forward_yaw,
               camera=cam, anims=parse_anims(anims) if isinstance(anims, str) else anims, shadows=shadows, samples=samples,
               engine=engine.upper(), light=dict(sun=sun, ambient=ambient), measure=measure)
    if ground_y is None and preset == "side":
        ground_y = h * 0.92          # side view: stand on the bottom of the frame
    if ground_y is not None:
        cfg["ground_y"] = ground_y
    script = Path(__file__).parent / "blender" / "render_sprites.py"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
    n = sum(a["frames"] for a in cfg["anims"].values()) * cam["headings"] * (2 if shadows else 1)
    if max_images and n > max_images:
        die(f"{n} images requested; the limit is {max_images} (fewer headings, frames or anims)")
    print(f"rendering {n} images with Blender ({engine}, {samples} samples) -> {out}")
    try:
        r = subprocess.run([blender or blender_bin(), "-b", "--python", str(script), "--", f.name], capture_output=True, text=True,
                           timeout=timeout, **({"creationflags": 0x08000000} if os.name == "nt" else {}))   # gBox: no console window
    except subprocess.TimeoutExpired:
        die(f"Blender did not finish in {timeout:.0f} s")
    finally:
        Path(f.name).unlink(missing_ok=True)
    done = [l for l in r.stdout.splitlines() if l.startswith("UM_RENDER_DONE")]
    if r.returncode or not done:
        die("Blender failed:\n" + (r.stderr or r.stdout)[-3000:])
    print(done[-1].replace("UM_RENDER_DONE", "rendered"))
    return out


# gBox: the argparse CLI (main / register) is removed; gbox.universal_modder calls render().
