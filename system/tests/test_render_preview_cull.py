"""characters.render_preview(cull=True): the triangles facing away from the camera are dropped, the way a game that
culls back faces draws them, so a single-sided part seen from behind shows as a hole (#1748 offline checks)."""
import numpy as np
from PIL import Image

from gbox import characters as C, evidence_render as E


def _coverage(png) -> float:
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    return float((np.abs(a - np.array([38, 40, 48])).sum(2) > 24).mean())


def test_cull_hides_a_single_sided_quad_from_behind(tmp_path):
    # a quad facing +Z (counter-clockwise seen from the front) and a small cube behind it to frame the view
    quad = {"pos": np.array([[-1, 0, 0], [1, 0, 0], [1, 2, 0], [-1, 2, 0]], float),
            "tris": np.array([[0, 1, 2], [0, 2, 3]])}
    glb = E.prims_glb([quad], tmp_path / "quad.glb")
    front, back = tmp_path / "f.png", tmp_path / "b.png"
    C.render_preview(glb, front, size=96, yaw=0.0, cull=True)
    C.render_preview(glb, back, size=96, yaw=180.0, cull=True)
    assert _coverage(front) > 0.3 and _coverage(back) == 0.0
    # clockwise fronts (a game's own winding): the same quad is a back face from the front
    C.render_preview(glb, front, size=96, yaw=0.0, cull="cw")
    C.render_preview(glb, back, size=96, yaw=180.0, cull="cw")
    assert _coverage(front) == 0.0 and _coverage(back) > 0.3
    # without culling (the default) both sides are painted, as before
    C.render_preview(glb, back, size=96, yaw=180.0)
    assert _coverage(back) > 0.3
