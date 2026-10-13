"""Evidence pictures for pull requests (docs/pr-evidence.md): labelled panels, before/after pairs, model renders.

Two kinds of evidence, never mixed up in a caption:

* "in-game frame"  - a frame grabbed from a running emulator session (gbox.evidence_capture), and
* "offline render" - a headless render of a model file (characters.render_preview: no GPU, no emulator): the stock
                     slot model next to the fitted donor, or a writer's fit-event snapshot (gbox.fit_events).

Everything here is pure image work (Pillow + numpy) so the control plane can compose an in-game before/after pair
and the offline backfill script (scripts/evidence_offline.py) can build model pairs without a session.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np

BG = (38, 40, 48)                     # characters.render_preview's background
BAR = (24, 25, 31)
INK = (236, 238, 244)
MUTED = (160, 166, 180)
KIND_COLOURS = {"in-game frame": (92, 200, 120), "offline render": (110, 160, 255), "UI screenshot": (230, 180, 90)}
KINDS = tuple(KIND_COLOURS)
PALETTE = [(200, 200, 200), (143, 230, 168), (79, 140, 255), (255, 181, 107), (217, 153, 255), (242, 230, 128),
           (255, 120, 120), (120, 220, 230)]


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                  # Pillow < 10.1: the fixed bitmap font
        return ImageFont.load_default()


def _image(src):
    """A PIL image from a path, PNG/JPEG bytes or an image."""
    from PIL import Image
    if isinstance(src, Image.Image):
        return src.convert("RGB")
    if isinstance(src, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(src))).convert("RGB")
    return Image.open(src).convert("RGB")


def _text_w(draw, text: str, font) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:                             # very old Pillow
        return len(text) * 7


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines = []
    for para in str(text or "").split("\n"):
        cur = ""
        for word in para.split():
            nxt = f"{cur} {word}".strip()
            if cur and _text_w(draw, nxt, font) > width:
                lines.append(cur)
                cur = word
            else:
                cur = nxt
        lines.append(cur)
    return [ln for ln in lines if ln is not None]


def compose(panels: list[tuple], caption: str = "", kind: str = "offline render", out=None, height: int = 420,
            gap: int = 6):
    """Panels side by side, each under its own title, a caption and the evidence kind below.

    panels: [(image (path / bytes / PIL), title)].  -> PNG bytes (and written to *out* when given)."""
    from PIL import Image, ImageDraw
    if kind not in KIND_COLOURS:
        raise ValueError(f"evidence kind must be one of {KINDS}")
    if not panels:
        raise ValueError("no panels to compose")
    ims = []
    for src, title in panels:
        im = _image(src)
        w = max(1, round(im.width * height / max(1, im.height)))
        ims.append((im.resize((w, height), Image.LANCZOS), str(title or "")))
    width = sum(im.width for im, _ in ims) + gap * (len(ims) + 1)
    f_title, f_cap, f_tag = _font(18), _font(16), _font(14)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    cap_lines = _wrap(probe, caption, f_cap, width - 24) if caption else []
    head, foot = 30, 14 + 22 * len(cap_lines) + 26
    canvas = Image.new("RGB", (width, head + height + foot + gap), BAR)
    dr = ImageDraw.Draw(canvas)
    x = gap
    for im, title in ims:
        canvas.paste(im, (x, head))
        t = title if _text_w(dr, title, f_title) <= im.width - 8 else title[: max(4, im.width // 10)] + "..."
        dr.text((x + 4, 6), t, fill=INK, font=f_title)
        x += im.width + gap
    y = head + height + 10
    for ln in cap_lines:
        dr.text((12, y), ln, fill=INK, font=f_cap)
        y += 22
    tag = f"[{kind}]"
    dr.rectangle((10, y + 2, 18 + _text_w(dr, tag, f_tag), y + 22), fill=KIND_COLOURS[kind])
    dr.text((14, y + 4), tag, fill=BAR, font=f_tag)
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    if out is not None:
        Path(out).write_bytes(data)
    return data


def before_after(before, after, caption: str = "", kind: str = "offline render", before_title: str = "Before (stock)",
                 after_title: str = "After (mod)", out=None, height: int = 420):
    """The canonical pair: stock on the left, the mod on the right."""
    return compose([(before, before_title), (after, after_title)], caption, kind, out, height)


# ------------------------------------------------------------------------------------------------ models

def render_model(path, out, size: int = 512, yaw: float = -30.0) -> Path:
    """A glTF / GLB -> PNG with the headless preview renderer (characters.render_preview)."""
    from .characters import render_preview
    return render_preview(Path(path), Path(out), size=size, yaw=yaw)


def kmd_prims(data: bytes) -> list[dict]:
    """A PS1 MGS KMD (gbox.mgs_kmd) in bind pose -> one prim per object {pos (n,3) world, tris (m,3)}.

    KMD joints carry no rotation: an object's vertices sit at the sum of its parent chain's joint offsets. Quads are
    split in two triangles; degenerate corners (a triangle stored as a quad) are dropped."""
    from . import mgs_kmd
    model = mgs_kmd.loads(data)
    T = np.zeros((len(model.objects), 3))
    out = []
    for i, o in enumerate(model.objects):
        T[i] = (T[o.parent] if o.parent >= 0 else 0) + np.array(o.pos, float)
        if not o.vertices or not o.faces:
            continue
        P = np.array([v[:3] for v in o.vertices], float) + T[i]
        tris = []
        for f in o.faces:
            a, b, c, d = (int(k) for k in f[:4])
            for t in ((a, b, c), (b, d, c)):
                if len(set(t)) == 3 and max(t) < len(P):
                    tris.append(t)
        if tris:
            out.append({"pos": P, "tris": np.array(tris, np.int64), "object": i})
    if not out:
        raise ValueError("KMD has no faces")
    return out


def prims_glb(prims: list[dict], path, colours=None) -> Path:
    """Prims {pos, tris} -> a minimal GLB, one material per prim (render_preview shades by material colour), so the
    body parts read apart in an untextured render."""
    colours = colours or PALETTE
    blob, views, accs, mats, meshes, nodes = bytearray(), [], [], [], [], []

    def add(arr: np.ndarray, target: int, comp: int, typ: str, minmax: bool = False):
        b = arr.tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(b), "target": target})
        blob.extend(b + b"\0" * (-len(b) % 4))
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0] if typ != "SCALAR"
                                                                                else arr.size), "type": typ}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(acc)
        return len(accs) - 1

    for k, p in enumerate(prims):
        P = np.asarray(p["pos"], np.float32).reshape(-1, 3)
        F = np.asarray(p["tris"], np.uint32).reshape(-1)
        if not len(P) or not len(F):
            continue
        c = colours[k % len(colours)]
        mats.append({"pbrMetallicRoughness": {"baseColorFactor": [c[0] / 255, c[1] / 255, c[2] / 255, 1.0],
                                              "metallicFactor": 0, "roughnessFactor": 0.8}, "doubleSided": True})
        pa, ia = add(P, 34962, 5126, "VEC3", True), add(F, 34963, 5125, "SCALAR")
        meshes.append({"primitives": [{"attributes": {"POSITION": pa}, "indices": ia, "material": len(mats) - 1}]})
        nodes.append({"mesh": len(meshes) - 1, "name": f"part{k}"})
    if not nodes:
        raise ValueError("no geometry")
    gl = {"asset": {"version": "2.0", "generator": "gBox evidence_render"}, "scene": 0,
          "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes, "materials": mats,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob))
                           + struct.pack("<II", len(js), 0x4E4F534A) + js
                           + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return Path(path)


def snapshot_strip(items: list[tuple], caption: str, out=None, size: int = 300, work=None):
    """Fit-event snapshot GLBs (gbox.fit_events: the fitted geometry after each stage) rendered side by side.
    items: [(glb path, title)].  -> PNG bytes."""
    import tempfile
    panels = []
    with tempfile.TemporaryDirectory(dir=work) as t:
        for k, (glb, title) in enumerate(items):
            png = Path(t) / f"s{k}.png"
            render_model(glb, png, size=size)
            panels.append((png.read_bytes(), title))
        return compose(panels, caption, "offline render", out, height=size)


def fit_report_lines(events: list[dict], limit: int = 14) -> list[str]:
    """Fit events (fit_events.split of each progress line) -> short "model: stage k=v ..." lines for a caption."""
    lines = []
    for ev in events:
        if not ev.get("stage") or not isinstance(ev.get("data"), dict):
            continue
        d = ev["data"]
        nums = ", ".join(f"{k}={v}" for k, v in list(d.items())[:6] if isinstance(v, (int, float, str, bool)))
        lines.append(f"{ev.get('model', '?')}: {ev['stage']} ({ev.get('state', 'done')}) {nums}"[:180])
    return lines[-limit:]
