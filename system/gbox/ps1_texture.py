"""PS1 texture intensity profile for decoded models (#1364, VR Missions Snake).

The PS1 GPU multiplies a texel by the primitive colour / 128 and saturates. Primitive colour 0x80 leaves a texel
unchanged, and 0xFF nearly doubles it. Many PS1 games therefore author textures around half intensity and let
lighting brighten them. A decoded GLB with unlit materials then looks darker than the game does, and so does a
cross-game swap whose writer multiplies the texture by its own shading (SM64: TEXEL0 * SHADE). This module measures
that from the embedded images. A writer can then choose a display gain from evidence instead of a guess. It never
edits the model.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

NEUTRAL = 128           # PS1 GPU modulation: primitive colour 0x80 = texel x 1.0
HALF_INTENSITY_SHARE = 0.05


def glb_images(path: Path) -> list[Image.Image]:
    """The images embedded in a binary glTF, decoded to RGB."""
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{path} is not a binary glTF")
    jl = struct.unpack_from("<I", data, 12)[0]
    gl = json.loads(data[20:20 + jl])
    off = 20 + jl
    blob = data[off + 8: off + 8 + struct.unpack_from("<I", data, off)[0]]
    out = []
    for im in gl.get("images", []):
        if "bufferView" not in im:
            raise ValueError("external glTF images are not embedded texture data")
        v = gl["bufferViews"][im["bufferView"]]
        o = v.get("byteOffset", 0)
        out.append(Image.open(io.BytesIO(blob[o:o + v["byteLength"]])).convert("RGB"))
    return out


def profile(images) -> dict:
    """ps1_15bit: every channel is a 5-bit PS1 level (a multiple of 8). half_intensity: those textures also stay at or
    below the GPU's neutral 128 almost everywhere (< 5% of channel values above it), so the game's light colour, not
    the texel, sets the displayed brightness."""
    arrays = [np.asarray(i.convert("RGB"), dtype=np.uint8).reshape(-1, 3) for i in images]
    px = np.concatenate(arrays) if arrays else np.zeros((0, 3), np.uint8)
    if not len(px):
        return {"images": 0, "pixels": 0, "ps1_15bit": False, "share_above_neutral": 0.0,
                "max_rgb": [0, 0, 0], "mean_rgb": [0.0, 0.0, 0.0], "half_intensity": False}
    quantized = bool((px % 8 == 0).all())
    share = float((px > NEUTRAL).mean())
    return {"images": len(arrays), "pixels": int(len(px)), "ps1_15bit": quantized,
            "share_above_neutral": round(share, 4), "max_rgb": [int(x) for x in px.max(0)],
            "mean_rgb": [round(float(x), 1) for x in px.mean(0)],
            "half_intensity": quantized and share < HALF_INTENSITY_SHARE}


def glb_profile(path: Path) -> dict:
    return profile(glb_images(path))


if __name__ == "__main__":      # python -m gbox.ps1_texture model.glb
    import sys
    print(json.dumps(glb_profile(Path(sys.argv[1])), indent=1))
