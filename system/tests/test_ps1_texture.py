"""PS1 texture intensity profile (#1364): explains the dark VR Missions Snake from its embedded textures."""
import io
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gbox import ps1_texture as T

LIBRARY_GLB = Path(os.environ.get("GBOX_CHARACTERS", "/home/ehm_eckx/gbox-cache/characters")) / "mgs_vr_snake/mgs_vr_snake.glb"


def _glb(path: Path, images) -> Path:
    blob, views, imgs = b"", [], []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        data = buf.getvalue()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        imgs.append({"bufferView": len(views) - 1, "mimeType": "image/png"})
        blob += data + b"\0" * (-len(data) % 4)
    js = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(blob)}], "bufferViews": views,
                     "images": imgs}).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    return path


def _img(rgb, size=(4, 4)):
    return Image.fromarray(np.tile(np.array(rgb, np.uint8), (size[1], size[0], 1)))


def test_half_intensity_ps1_textures_are_detected(tmp_path):
    p = _glb(tmp_path / "a.glb", [_img((48, 48, 56)), _img((128, 88, 72))])
    prof = T.glb_profile(p)
    assert prof["images"] == 2 and prof["ps1_15bit"] and prof["half_intensity"]
    assert prof["max_rgb"] == [128, 88, 72] and prof["share_above_neutral"] == 0.0


def test_full_range_or_unquantized_textures_are_not_half_intensity(tmp_path):
    bright = T.glb_profile(_glb(tmp_path / "b.glb", [_img((248, 200, 160)), _img((48, 48, 56))]))
    assert bright["ps1_15bit"] and not bright["half_intensity"]
    smooth = T.glb_profile(_glb(tmp_path / "c.glb", [_img((47, 49, 55))]))
    assert not smooth["ps1_15bit"] and not smooth["half_intensity"]


def test_no_images_and_non_glb_inputs(tmp_path):
    assert T.glb_profile(_glb(tmp_path / "e.glb", []))["half_intensity"] is False
    (tmp_path / "x.glb").write_bytes(b"nope")
    with pytest.raises(ValueError):
        T.glb_profile(tmp_path / "x.glb")


@pytest.mark.skipif(not LIBRARY_GLB.is_file(), reason="no collected VR Missions Snake in the local library")
def test_collected_snake_textures_are_half_intensity_ps1():
    prof = T.glb_profile(LIBRARY_GLB)
    assert prof["images"] == 28 and prof["ps1_15bit"] and prof["half_intensity"]
    assert max(prof["max_rgb"]) <= 184 and max(prof["mean_rgb"]) < 80
