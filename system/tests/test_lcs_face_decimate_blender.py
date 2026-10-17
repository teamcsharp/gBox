"""Integration test for the face-preserving decimation in PR #474 (gbox/decimate_gltf.py).

The plumbing tests (test_lcs_face_decimate.py) only prove the ``protect`` argument reaches
Blender's command line. This test runs the real Blender collapse that decimate_gltf.py relies on
(a DECIMATE/COLLAPSE modifier bound to a 'protect' vertex group with factor 1.0) and asserts the
two properties the fix actually depends on:

1. Low-weight (head/face, 0.5) vertices collapse AFTER high-weight (body, 1.0) vertices, so the
   face keeps ~2x the triangles of a uniform cut.
2. The vertex group does not stall the collapse above its target ratio, so the writer can still
   reach the deep (~94%) triangle cut the streamed LCS pedestrian slots force.

Skipped when Blender is not installed (CI without Blender keeps running the fast plumbing tests).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = r"""
import bpy

def run(ratio):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=4.0)
    o = bpy.context.active_object
    me = o.data
    g = o.vertex_groups.new(name="protect")
    head_idx = set()
    for v in me.vertices:
        x, y, _ = v.co
        is_head = (x >= 0.0 and y >= 0.0)
        g.add([v.index], 0.5 if is_head else 1.0, "REPLACE")
        if is_head:
            head_idx.add(v.index)
    n0 = sum(len(p.vertices) - 2 for p in me.polygons)
    d = o.modifiers.new("dec", "DECIMATE")
    d.decimate_type = "COLLAPSE"
    d.ratio = ratio
    d.use_collapse_triangulate = True
    d.vertex_group = "protect"
    d.vertex_group_factor = 1.0
    bpy.ops.object.modifier_apply(modifier=d.name)
    me = o.data
    head = body = 0
    for p in me.polygons:
        verts = [me.vertices[i].co for i in p.vertices]
        cx = sum(v.x for v in verts) / len(verts)
        cy = sum(v.y for v in verts) / len(verts)
        if cx >= 0.0 and cy >= 0.0:
            head += 1
        else:
            body += 1
    print(f"RESULT ratio={ratio} n0={n0} n1={head+body} head={head} body={body}", flush=True)

run(0.15)
run(0.06)
"""


def _blender() -> str | None:
    for cand in ("/usr/bin/blender", "/usr/local/bin/blender"):
        if Path(cand).exists():
            return cand
    return shutil.which("blender")


@pytest.mark.skipif(_blender() is None, reason="Blender not installed")
def test_protect_group_spares_face_and_reaches_target(tmp_path):
    blender = _blender()
    assert blender is not None  # guarded by skipif, keeps the type checker quiet
    script = tmp_path / "collapse_check.py"
    script.write_text(_SCRIPT)
    out = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", str(script)],
        capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0, (out.stdout + out.stderr)[-3000:]
    lines = [l for l in out.stdout.splitlines() if l.startswith("RESULT ")]
    assert len(lines) == 2, out.stdout
    r15 = lines[0]
    m = re.search(r"n0=(\d+) n1=(\d+) head=(\d+) body=(\d+)", r15)
    assert m, r15
    n0, n1, head, body = map(int, m.groups())
    # head is 1/4 of the grid -> 1/4 of n0 triangles; retention ratio should be ~2x.
    head0 = n0 // 4
    body0 = n0 - head0
    ratio = (head / max(head0, 1)) / (body / max(body0, 1))
    assert ratio > 1.5, f"face not spared: head/body retention ratio {ratio:.2f} ({r15})"
    # the vertex group must not stall the collapse above its target
    assert n1 <= n0 * 0.20, f"collapse stalled above target: {n0} -> {n1} ({r15})"
    # deep target (the ~94% LCS pedestrian cut) must still be reachable
    m2 = re.search(r"n0=(\d+) n1=(\d+)", lines[1])
    assert m2, lines[1]
    n0b, n1b = map(int, m2.groups())
    assert n1b <= n0b * 0.08, f"deep target unreachable: {n0b} -> {n1b} ({lines[1]})"
