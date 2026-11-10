"""Enemy portraits drawn from each title's own model archives (operator 2026-11-10: "I want to see profile pictures of
the enemies with names in the live map"), never copied from a wiki.

    python -m gbox.mercs.enemy_portraits render --title 010018100CD46000 --archives DIR [--classes uEm20 uEm22 ...]
                                               [--out gbox-data/mercs/enemy_portraits]

DIR holds the class archives as the RomFS names them (RE5 `uEm20.arc`, RE6 `uEm3200.arc`; a copy reduced to its
MOD / MRL / albedo entries is enough). Each class's own model (RE5 `pawn\\em\\em20\\model\\em2000`, RE6
`...\\em3200` - the archive's largest skinned MOD otherwise) is drawn on the CPU: LOD 0, the albedo each material binds
through its MRL, a flat directional shade, front view in the bind pose - the archive's bytes, not the game's shading,
animation or camera. The picture is cut to a head-and-shoulders square for a standing figure (a crawler, a dog or a
flyer keeps its whole body) and kept as `<out>/<title>/<class>.png` (PORTRAIT_PX square) beside an index.json
({class: {source, model, triangles, at}}).

Where no model can be drawn (RE4's Ganado packs are not wired here yet; a class whose MOD format the reader does not
decode) the live map's crop of a session frame stands in (gbox/tactical_map.Portraits: `mercs/portraits/<title>/
<class>.jpg`, captured while the bot's laser dot is on one). The control plane serves whichever exists
(GET /api/mercs/enemies/{title}/{class}.png - gbox/tactical_map.py).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
import zlib
from pathlib import Path

import numpy as np

PORTRAIT_PX = 256
CANVAS_PX = 640
BACKGROUND = (24, 26, 32)
LIGHT = np.array([0.25, 0.55, 0.80]) / np.linalg.norm([0.25, 0.55, 0.80])
TEXTURE_MAX = 512                     # albedos are sampled from at most this size (the portrait is 256 px)
MIN_TRIANGLES = 50                    # fewer drawn: a placeholder model (RE6 uEm3300 holds one triangle), no portrait
CLASS_RE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
TITLE_RE = re.compile(r"[A-Za-z0-9]{4,24}")
RE5, RE6, RE4 = "010018100CD46000", "01002A000CD48000", "010099A00BC1E000"


class PortraitError(ValueError):
    """Nothing in the archive can be drawn as this class's portrait."""


def default_root() -> Path:
    return Path(__file__).resolve().parents[2] / "gbox-data" / "mercs" / "enemy_portraits"


def _raw(entry) -> bytes:
    try:
        return zlib.decompress(entry.data)
    except zlib.error:
        return entry.data


# --- the model's pieces ------------------------------------------------------------------------------------------------
def _class_digits(cls: str) -> str:
    return str(cls)[3:].lower() if str(cls).lower().startswith("uem") else str(cls).lower()


def _pick_model(arc, cls: str) -> tuple[int, int | None]:
    """(MOD entry index, MRL entry index or None) of the class's own model: the MOD named em<id>00 / em<id> under a
    model folder, else the largest MOD that is not an effect, a LOD copy or a weapon."""
    digits = _class_digits(cls)
    mods, mrls = {}, {}
    for i, e in enumerate(arc.entries):
        magic = _raw(e)[:4]
        if magic == b"MOD\0":
            mods[e.name] = i
        elif magic == b"MRL\0":
            mrls[e.name] = i
    if not mods:
        raise PortraitError("the archive holds no MOD")
    leaf = {n: n.rsplit("\\", 1)[-1].lower() for n in mods}
    exact = [n for n in mods if leaf[n] in (f"em{digits}00", f"em{digits}")]
    usable = [n for n in mods if not n.lower().startswith("effect") and not leaf[n].endswith(("_low", "_mid"))
              and "\\wp" not in n.lower()]
    pool = exact or usable or list(mods)
    name = max(pool, key=lambda n: (n in exact, len(_raw(arc.entries[mods[n]]))))
    return mods[name], mrls.get(name)


def _textures(arc, title: str = RE5) -> dict:
    """{entry name: RGB array} of every albedo TEX (`_BM`) the archive holds, at most TEXTURE_MAX wide (RE5 through
    mtf_tex, RE6 through its own TEX decoder, re6_stage_greybox._decoded)."""
    from PIL import Image
    out = {}
    for e in arc.entries:
        if "_BM" not in e.name:
            continue
        raw = _raw(e)
        im = None
        try:
            if title == RE6:
                from .. import re6_stage_greybox as G6
                im = G6._decoded(raw, TEXTURE_MAX)
            else:
                from .. import mtf_tex
                im = mtf_tex.decode(raw, 0)
        except Exception:                                   # noqa: BLE001 - an undecodable albedo: grey
            im = None
        if im is None:
            continue
        if not isinstance(im, Image.Image):
            im = Image.fromarray(np.asarray(im))
        im = im.convert("RGB")
        if im.width > TEXTURE_MAX:
            im = im.resize((TEXTURE_MAX, max(1, im.height * TEXTURE_MAX // im.width)))
        out[e.name] = np.asarray(im, np.uint8)
    return out


def _bindings(title: str, mod_raw: bytes, arc, mrl_index) -> list:
    """Per MOD material, the albedo path its MRL binds (empty strings where none can be read)."""
    if mrl_index is None:
        return []
    try:
        if title == RE6:
            from .. import re6_stage_greybox as G6
            return [row.get("albedo") or "" for row in G6.material_bindings(mod_raw, arc.entries[mrl_index])]
        from .. import re5_stage_greybox as G5
        return [row.get("albedo") or "" for row in G5.material_bindings(mod_raw, _raw(arc.entries[mrl_index]))]
    except Exception:                                       # noqa: BLE001 - no bindings: every part in grey
        return []


def pieces(title: str, archive: bytes, cls: str) -> tuple[list, dict]:
    """[(positions (n,3), normals (n,3) or None, uvs (n,2), triangles (m,3), texture)] of the class model's LOD-0
    parts, and what was drawn ({model, meshes, textured})."""
    from .. import mt_arc, mt_model, mtf_author
    arc = mt_arc.parse(archive)
    mod_index, mrl_index = _pick_model(arc, cls)
    mod_raw = _raw(arc.entries[mod_index])
    model = mt_model.parse_mod(mod_raw)
    textures = _textures(arc, title)
    albedo_of = _bindings(title, mod_raw, arc, mrl_index)
    grey = np.full((4, 4, 3), 150, np.uint8)
    out, textured = [], 0
    records = model.meshes()
    for k, rec in enumerate(records):
        lod = rec.get("level_of_detail", 1)
        if lod and not lod & 1:
            continue
        if rec.get("mesh_type", 0xFFFF) not in (0xFFFF, None) and title != RE6:
            continue
        try:
            pos = np.asarray(model.positions(k), np.float64)
            uvs = np.asarray(model.uvs(k), np.float64)
            tri = np.asarray(mtf_author.mesh_triangles(model, k), np.int64).reshape(-1, 3) - rec["vertex_index"]
        except Exception:                                   # noqa: BLE001 - a format the reader does not decode
            continue
        if not len(pos) or not len(tri) or tri.min() < 0 or tri.max() >= len(pos):
            continue
        if len(uvs) != len(pos):
            uvs = np.zeros((len(pos), 2))
        try:
            nrm = np.asarray(model.normals(k), np.float64)
            nrm = nrm if nrm.shape == pos.shape and np.isfinite(nrm).all() else None
        except Exception:                                   # noqa: BLE001
            nrm = None
        mi = rec.get("material_index", -1)
        albedo = albedo_of[mi] if 0 <= mi < len(albedo_of) else ""
        tex = textures.get(albedo)
        if tex is None and albedo:
            tex = next((t for n, t in textures.items() if n.lower() == albedo.lower()), None)
        textured += tex is not None
        if not np.isfinite(pos).all():
            continue
        out.append((pos, nrm, uvs, tri, tex if tex is not None else grey))
    if not out:
        raise PortraitError(f"{cls}: no drawable LOD-0 part")
    return out, {"model": arc.entries[mod_index].name, "meshes": len(out), "textured": textured}


# --- the picture -------------------------------------------------------------------------------------------------------
def _tri(canvas, zbuf, xy, depth, uv, tex, shade):
    h, w = zbuf.shape
    x0, y0 = int(max(0, math.floor(xy[:, 0].min()))), int(max(0, math.floor(xy[:, 1].min())))
    x1, y1 = int(min(w - 1, math.ceil(xy[:, 0].max()))), int(min(h - 1, math.ceil(xy[:, 1].max())))
    if x1 < x0 or y1 < y0:
        return 0
    (ax, ay), (bx, by), (cx, cy) = xy
    det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
    if abs(det) < 1e-9:
        return 0
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    px, py = xs + 0.5, ys + 0.5
    w1 = ((bx - px) * (cy - py) - (cx - px) * (by - py)) / det
    w2 = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) / det
    w3 = 1.0 - w1 - w2
    inside = (w1 >= -1e-6) & (w2 >= -1e-6) & (w3 >= -1e-6)
    if not inside.any():
        return 0
    z = w1 * depth[0] + w2 * depth[1] + w3 * depth[2]
    win = zbuf[y0:y1 + 1, x0:x1 + 1]
    hit = inside & (z < win)
    if not hit.any():
        return 0
    u = (w1 * uv[0, 0] + w2 * uv[1, 0] + w3 * uv[2, 0])[hit]
    v = (w1 * uv[0, 1] + w2 * uv[1, 1] + w3 * uv[2, 1])[hit]
    th, tw = tex.shape[:2]
    texel = tex[np.floor(v * th).astype(np.int64) % th, np.floor(u * tw).astype(np.int64) % tw]
    win[hit] = z[hit]
    canvas[y0:y1 + 1, x0:x1 + 1][hit] = np.clip(texel * shade, 0, 255).astype(np.uint8)
    return 1


def draw(parts: list, size: int = CANVAS_PX, yaw_deg: float = 15.0, pitch_deg: float = 6.0):
    """The parts drawn front-on (the model faces +z; yaw turns it toward the viewer's left), orthographic, fitted to a
    size x size RGB canvas. Returns (PIL image, triangles drawn)."""
    from PIL import Image
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    rot = rx @ ry
    turned = [(p @ rot.T, None if n is None else n @ rot.T, uv, t, tex) for p, n, uv, t, tex in parts]
    allp = np.concatenate([p for p, *_ in turned])
    lo, hi = np.percentile(allp, 0.2, axis=0), np.percentile(allp, 99.8, axis=0)
    span = max(hi[0] - lo[0], hi[1] - lo[1]) or 1.0
    scale = (size - 12) / span
    ox = 6 + ((span - (hi[0] - lo[0])) * scale) / 2
    oy = 6 + ((span - (hi[1] - lo[1])) * scale) / 2
    canvas = np.empty((size, size, 3), np.uint8)
    canvas[:] = BACKGROUND
    zbuf = np.full((size, size), np.inf)
    drawn = 0
    for p, n, uv, tris, tex in turned:
        xy = np.empty((len(p), 2))
        xy[:, 0] = (p[:, 0] - lo[0]) * scale + ox
        xy[:, 1] = (hi[1] - p[:, 1]) * scale + oy
        depth = -p[:, 2]
        a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
        face = np.cross(b - a, c - a)
        face /= np.maximum(np.linalg.norm(face, axis=1), 1e-9)[:, None]
        if n is not None:
            vn = n[tris].mean(1)
            vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-9)[:, None]
            face = np.where((np.linalg.norm(n[tris].mean(1), axis=1) > 0.2)[:, None], vn, face)
        shades = 0.45 + 0.55 * np.abs(face @ LIGHT)
        for t in range(len(tris)):
            tri = tris[t]
            drawn += _tri(canvas, zbuf, xy[tri], depth[tri], uv[tri], tex, float(shades[t]))
    return Image.fromarray(canvas, "RGB"), drawn


def crop_portrait(im, px: int = PORTRAIT_PX):
    """A square around the figure's head and shoulders when it stands (taller than 0.7 x its width), else around the
    whole figure, resized to px."""
    a = np.asarray(im)
    mask = np.abs(a.astype(np.int16) - np.array(BACKGROUND, np.int16)).sum(2) > 18
    if not mask.any():
        raise PortraitError("nothing drawn")
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    if h >= 0.7 * w:
        side = int(max(0.42 * h, 40))
        top = ys <= y0 + 0.12 * h                         # the head's columns: the topmost rows of the figure
        cx = int(np.median(xs[top])) if top.any() else (x0 + x1) // 2
        box = (cx - side // 2, max(0, y0 - side // 12), cx - side // 2 + side, max(0, y0 - side // 12) + side)
    else:
        side = int(max(h, w) * 1.08)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        box = (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)
    from PIL import Image
    out = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), BACKGROUND)
    out.paste(im.crop((max(0, box[0]), max(0, box[1]), min(im.width, box[2]), min(im.height, box[3]))),
              (max(0, -box[0]), max(0, -box[1])))
    return out.resize((px, px))


def render_class(title: str, archive: bytes, cls: str, size: int = CANVAS_PX) -> tuple[bytes, dict]:
    """(PNG bytes, receipt) of one class's portrait from its archive."""
    t0 = time.time()
    parts, info = pieces(title, archive, cls)
    full, drawn = draw(parts, size)
    if drawn < MIN_TRIANGLES:
        raise PortraitError(f"{cls}: only {drawn} triangles drawn ({info['model']}) - not a figure")
    pic = crop_portrait(full)
    buf = io.BytesIO()
    pic.save(buf, "PNG", optimize=True)
    return buf.getvalue(), dict(info, triangles=drawn, seconds=round(time.time() - t0, 1), source="model",
                                shows="the archive's LOD-0 model with its own albedos, bind pose, flat shade; "
                                      "not the game's shading or camera")


# --- the store ---------------------------------------------------------------------------------------------------------
class Store:
    """<root>/<title>/<class>.png and index.json - what GET /api/mercs/enemies serves."""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_root()

    def path(self, title, cls) -> Path | None:
        if not (isinstance(title, str) and TITLE_RE.fullmatch(title) and isinstance(cls, str)
                and CLASS_RE.fullmatch(cls)):
            return None
        return self.root / title / f"{cls}.png"

    def index(self, title) -> dict:
        if not (isinstance(title, str) and TITLE_RE.fullmatch(title)):
            return {}
        try:
            return json.loads((self.root / title / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def put(self, title, cls, png: bytes, info: dict) -> Path:
        path = self.path(title, cls)
        if path is None:
            raise PortraitError("bad title or class")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(png)
        tmp.replace(path)
        idx = self.index(title)
        idx[cls] = {k: info[k] for k in ("source", "model", "triangles", "textured", "seconds") if k in info} | \
            {"at": round(time.time(), 1)}
        ip = path.parent / "index.json"
        tmp = ip.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, sort_keys=True, indent=1), encoding="utf-8")
        tmp.replace(ip)
        return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.mercs.enemy_portraits", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="draw each class archive's model into the portrait store")
    r.add_argument("--title", required=True)
    r.add_argument("--archives", required=True, help="a folder of <class>.arc files")
    r.add_argument("--classes", nargs="*", help="only these classes (default: every <class>.arc in the folder)")
    r.add_argument("--out", help="the portrait store (default gbox-data/mercs/enemy_portraits)")
    r.add_argument("--size", type=int, default=CANVAS_PX)
    a = ap.parse_args(argv)
    store = Store(a.out)
    folder = Path(a.archives)
    classes = a.classes or sorted(p.stem for p in folder.glob("*.arc"))
    failed = 0
    for cls in classes:
        path = folder / f"{cls}.arc"
        try:
            png, info = render_class(a.title, path.read_bytes(), cls, a.size)
            out = store.put(a.title, cls, png, info)
            print(f"{cls}: {out} ({info['triangles']} triangles, {info['textured']}/{info['meshes']} textured, "
                  f"{info['seconds']} s, {info['model']})", flush=True)
        except Exception as e:                              # noqa: BLE001 - one class never stops the rest
            failed += 1
            print(f"{cls}: FAILED {type(e).__name__}: {e}", flush=True)
    return 1 if failed and failed == len(classes) else 0


if __name__ == "__main__":
    sys.exit(main())
