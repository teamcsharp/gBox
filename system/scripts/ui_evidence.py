#!/usr/bin/env python3
"""PR evidence screenshots: the gBox UI rendered headless against FIXTURE data (no control plane, no game files).

    python scripts/ui_evidence.py --clients <checkout>/system/clients --fixtures tests/fixtures/ui_evidence/302.json \
        --out <dir> [--shots <spec.json>] [--only name,name] [--offline] [--serve]

A local HTTP server on 127.0.0.1 serves the clients tree the way the control plane does (/ = web/index.html, /viz/* =
web/viz, /live-poll.js = desktop/live-poll.js, /clients/* = the tree itself, e.g. /clients/desktop/index.html) and
answers /api/* from the fixture file; nothing is ever forwarded. Playwright's headless chromium then opens each shot,
runs its actions and saves <out>/<name>.png (clipped to a selector when the shot names one).

Fixture file (JSON):
  routes:  { "<path>[?query]" | "<glob with *>" | "POST <path>": value }   GET answers; "METHOD path" keys answer that
           method. Values are JSON, or a special form:
             {"$svg": "<svg…>"}                      an SVG image
             {"$placeholder": "label", "hue": 210, "style": "fit"|"scene"}   a generated SVG picture
             {"$glb": {"height": 1.7, "pose": "A", "color": [r,g,b]}}   a synthetic skinned humanoid (glTF binary)
             {"$file": "relative/path"}              a file next to the fixture file (synthetic assets only)
             {"$status": 404, "$body": {...}}        an error answer
             {"$by": "tool", "cases": {"pick_preview": {...}}, "$default": {...}}   POST: chosen by a body field (dot path)
             Strings "$now", "$now-300" (epoch seconds) and "$now-300ms" (epoch ms) become timestamps.
  include: ["_web_shell.json"]     fixture files merged underneath this one (routes, lists, local_storage, desktop and
                                   shared snippets such as "setup_js"; an included file's shots are not run)
  lists:   ["/api/sessions", …]   collection paths whose UNKNOWN answer is [] (everything else unknown answers {})
  local_storage: { key: value }   set before the page's scripts run
  desktop: { "settings": {...} }   the desktop app's window.gbox shim (pages under /clients/desktop/)
  shots:   [ { name, url, viewport: [w, h], actions: [...], clip?: selector, pad?: px, init_js?: js,
               reduced_motion?: "reduce" } ]
           actions: {"wait": ms} {"wait_for": sel} {"click": sel} {"right_click": sel} {"dblclick": sel} {"hover": sel}
                    {"eval": js} {"mouse": [x, y]} {"click_at": [x, y, "right"?]} {"press": key} {"select": [sel, value]}
                    {"fill": [sel, text]} {"viewport": [w, h]} (resize the window mid-shot); a value "$name" is the
                    fixture's top-level snippet "name"
Unknown GET /api paths that look like pictures (.png/.jpg/…, /preview, /frame.jpg, /mjpeg) answer a placeholder picture,
.glb paths a synthetic humanoid; every other unknown answer is empty JSON. Non-GET requests without a fixture answer
{"ok": true} and change nothing. The browser may reach only this server and the public CDNs the UI imports three.js
from (cdn.jsdelivr.net etc.; --offline blocks those too); every other host is aborted.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import mimetypes
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMAGE_HINT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", "/preview", "/frame.jpg", "/mjpeg", "/thumb", "/cover", "/image")
CDN_HOSTS = ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "esm.sh", "fonts.googleapis.com", "fonts.gstatic.com")
DEFAULT_LISTS = ("/api/sessions", "/api/workers", "/api/notify", "/api/jobs", "/api/characters", "/api/nodes")


# ---------------------------------------------------------------------------------------------------------------- pictures
def _figure(cx: float, top: float, hgt: float, fill: str, opacity: float = 1.0, arms: float = 0.0) -> str:
    """A simple standing figure (head, torso, arms at `arms` radians below horizontal, legs) as SVG shapes."""
    u = hgt / 8
    sx, sy = math.cos(arms), math.sin(arms)
    return (f'<g fill="{fill}" stroke="{fill}" stroke-linecap="round" opacity="{opacity}">'
            f'<circle cx="{cx}" cy="{top + u * 0.6}" r="{u * 0.6}" stroke="none"/>'
            f'<rect x="{cx - u * 0.75}" y="{top + u * 1.35}" width="{u * 1.5}" height="{u * 2.9}" rx="{u * 0.35}" stroke="none"/>'
            f'<path d="M{cx - u * 0.75} {top + u * 1.6} l{-u * 2.6 * sx} {u * 2.6 * sy} M{cx + u * 0.75} {top + u * 1.6} l{u * 2.6 * sx} {u * 2.6 * sy}" '
            f'stroke-width="{u * 0.42}" fill="none"/>'
            f'<path d="M{cx - u * 0.4} {top + u * 4.2} L{cx - u * 0.55} {top + hgt} M{cx + u * 0.4} {top + u * 4.2} L{cx + u * 0.55} {top + hgt}" '
            f'stroke-width="{u * 0.5}" fill="none"/></g>')


def placeholder_svg(label: str, hue: int | None = None, w: int = 640, h: int = 480, style: str = "") -> bytes:
    """A deterministic synthetic picture (gradient + label) for previews, covers and frames. style "fit": a fitting
    preview (the slot's skeleton in orange, the fitted donor over it); style "scene": a game frame with two figures."""
    if hue is None:
        hue = int(hashlib.sha1(label.encode()).hexdigest()[:4], 16) % 360
    text = (label or "")[:48].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if style == "fit":
        u = h * 0.68 / 8
        cx, top = w / 2, h * 0.1
        sk = "".join(f'<path d="M{cx + x0 * u} {top + y0 * u} L{cx + x1 * u} {top + y1 * u}"/>'
                     for x0, y0, x1, y1 in ((0, 0.6, 0, 4.2), (-2.4, 1.6, 2.4, 1.6), (0, 4.2, -0.6, 8), (0, 4.2, 0.6, 8)))
        joints = "".join(f'<circle cx="{cx + x * u}" cy="{top + y * u}" r="{u * 0.28}"/>' for x, y in
                         ((0, 0.6), (0, 1.6), (0, 4.2), (-1.2, 1.6), (1.2, 1.6), (-2.4, 1.6), (2.4, 1.6), (-0.3, 6.1), (0.3, 6.1),
                          (-0.6, 8), (0.6, 8)))
        grid = "".join(f'<path d="M0 {y} H{w}"/>' for y in range(0, h, 40))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#0d1017"/><g stroke="#2a3140" stroke-width="1">{grid}</g>'
                + _figure(cx, top, h * 0.68, f"hsl({hue},70%,58%)", 0.75, arms=0.0)
                + f'<g stroke="#ffb46b" stroke-width="{u * 0.12}" fill="none">{sk}</g><g fill="#ffd36b">{joints}</g>'
                f'<text x="16" y="{h - 18}" font-family="system-ui,sans-serif" font-size="{max(12, h // 22)}" fill="#dfe4ec">{text}</text>'
                f'<text x="{w - 16}" y="28" font-family="ui-monospace,monospace" font-size="{max(10, h // 30)}" fill="#7d8696" '
                f'text-anchor="end">fitting preview (synthetic)</text></svg>').encode()
    if style == "scene":
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl({hue},55%,55%)"/>'
                f'<stop offset="1" stop-color="hsl({hue},40%,80%)"/></linearGradient></defs>'
                f'<rect width="{w}" height="{h * 0.62}" fill="url(#sky)"/><rect y="{h * 0.62}" width="{w}" height="{h * 0.38}" fill="#3d6b35"/>'
                f'<rect x="{w * 0.05}" y="{h * 0.30}" width="{w * 0.16}" height="{h * 0.32}" fill="#8a8f99"/>'
                f'<rect x="{w * 0.78}" y="{h * 0.22}" width="{w * 0.17}" height="{h * 0.40}" fill="#7a7f8c"/>'
                + _figure(w * 0.42, h * 0.30, h * 0.48, "#d23b3b", arms=0.9)
                + _figure(w * 0.66, h * 0.36, h * 0.40, "#2f5fd0", arms=0.7)
                + f'<text x="12" y="{h - 12}" font-family="ui-monospace,monospace" font-size="{max(10, h // 34)}" fill="#ffffffaa">{text}</text></svg>').encode()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl({hue},45%,32%)"/>'
            f'<stop offset="1" stop-color="hsl({(hue + 40) % 360},50%,14%)"/></linearGradient></defs>'
            f'<rect width="{w}" height="{h}" fill="url(#g)"/>'
            f'<g fill="hsl({hue},70%,72%)" opacity=".85"><circle cx="{w / 2}" cy="{h * 0.30}" r="{h * 0.09}"/>'
            f'<rect x="{w / 2 - h * 0.11}" y="{h * 0.41}" width="{h * 0.22}" height="{h * 0.30}" rx="{h * 0.05}"/></g>'
            f'<text x="{w / 2}" y="{h * 0.88}" font-family="system-ui,sans-serif" font-size="{max(12, h // 16)}" fill="#fff" '
            f'text-anchor="middle" opacity=".9">{text}</text></svg>').encode()


# ------------------------------------------------------------------------------------------------- synthetic humanoid GLB
# Mixamo-style bone names (the retarget editor's guessRoles and the fixtures' rig_roles both map them)
_BONES = [  # name, parent, role
    ("Hips", None, "hip"), ("Spine", "Hips", "chest"), ("Neck", "Spine", "neck"), ("Head", "Neck", "head"),
    ("LeftShoulder", "Spine", "l_clav"), ("LeftArm", "LeftShoulder", "l_upper"), ("LeftForeArm", "LeftArm", "l_fore"),
    ("LeftHand", "LeftForeArm", "l_hand"), ("RightShoulder", "Spine", "r_clav"), ("RightArm", "RightShoulder", "r_upper"),
    ("RightForeArm", "RightArm", "r_fore"), ("RightHand", "RightForeArm", "r_hand"), ("LeftUpLeg", "Hips", "l_thigh"),
    ("LeftLeg", "LeftUpLeg", "l_shin"), ("LeftFoot", "LeftLeg", "l_foot"), ("RightUpLeg", "Hips", "r_thigh"),
    ("RightLeg", "RightUpLeg", "r_shin"), ("RightFoot", "RightLeg", "r_foot"),
]
RIG_ROLES = {role: name for name, _, role in _BONES}


def _joint_positions(height: float, pose: str, head: float, arms: float) -> dict[str, tuple[float, float, float]]:
    k = height / 1.7
    sh_y, sh_x = 1.42, 0.18
    # +x is the character's left (front view, facing +z)
    if pose.upper() == "T":
        down = 0.0
    else:                                                     # A-pose: arms 40 degrees down
        down = math.radians(40)
    u, f = 0.27 * arms, 0.25 * arms
    elbow = (sh_x + u * math.cos(down), sh_y - u * math.sin(down))
    wrist = (elbow[0] + f * math.cos(down), elbow[1] - f * math.sin(down))
    P = {"Hips": (0, 0.95, 0), "Spine": (0, 1.25, 0), "Neck": (0, 1.48, 0), "Head": (0, 1.48 + 0.10 * head, 0),
         "LeftShoulder": (0.06, 1.42, 0), "LeftArm": (sh_x, sh_y, 0), "LeftForeArm": (elbow[0], elbow[1], 0),
         "LeftHand": (wrist[0], wrist[1], 0), "LeftUpLeg": (0.1, 0.9, 0), "LeftLeg": (0.1, 0.5, 0.01), "LeftFoot": (0.1, 0.08, 0)}
    for n in list(P):
        if n.startswith("Left"):
            x, y, z = P[n]
            P["Right" + n[4:]] = (-x, y, z)
    return {n: (p[0] * k, p[1] * k, p[2] * k) for n, p in P.items()}


def _box(a, b, r, r2=None):
    """8 corners of a box from a to b (radius r across)."""
    r2 = r if r2 is None else r2
    d = [b[i] - a[i] for i in range(3)]
    ln = math.sqrt(sum(x * x for x in d)) or 1e-6
    d = [x / ln for x in d]
    up = (0, 0, 1) if abs(d[2]) < 0.9 else (1, 0, 0)
    s = [d[1] * up[2] - d[2] * up[1], d[2] * up[0] - d[0] * up[2], d[0] * up[1] - d[1] * up[0]]
    sl = math.sqrt(sum(x * x for x in s)) or 1
    s = [x / sl for x in s]
    t = [d[1] * s[2] - d[2] * s[1], d[2] * s[0] - d[0] * s[2], d[0] * s[1] - d[1] * s[0]]
    out = []
    for end, rad in ((a, r), (b, r2)):
        for i, j in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            out.append(tuple(end[k] + rad * (i * s[k] + j * t[k]) for k in range(3)))
    return out


_FACES = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]


def synthetic_glb(height: float = 1.7, pose: str = "A", color=(0.55, 0.62, 0.85), head: float = 1.0, arms: float = 1.0,
                  name: str = "synthetic") -> bytes:
    """A small skinned humanoid (18 bones, a box per limb segment, rigid weights) as glTF binary."""
    P = _joint_positions(height, pose, head, arms)
    names = [b[0] for b in _BONES]
    idx = {n: i for i, n in enumerate(names)}
    children = {n: [c for c, p, _ in _BONES if p == n] for n in names}
    k = height / 1.7
    segs = []  # (bone, a, b, r, r2)
    for n, p, _ in _BONES:
        kids = children[n]
        if n == "Head":
            a = P["Head"]
            segs.append((n, (a[0], a[1] - 0.02 * k, a[2]), (a[0], a[1] + 0.22 * k * head, a[2]), 0.09 * k * head, 0.085 * k * head))
        elif n == "Hips":
            segs.append((n, (0, 0.86 * k, 0), (0, 1.12 * k, 0), 0.15 * k, 0.14 * k))
        elif n == "Spine":
            segs.append((n, (0, 1.12 * k, 0), (0, 1.45 * k, 0), 0.15 * k, 0.17 * k))
        elif n in ("LeftHand", "RightHand"):
            a = P[n]; par = P[p]
            d = [a[i] - par[i] for i in range(3)]; ln = math.sqrt(sum(x * x for x in d)) or 1
            segs.append((n, a, tuple(a[i] + d[i] / ln * 0.12 * k for i in range(3)), 0.04 * k, 0.035 * k))
        elif n in ("LeftFoot", "RightFoot"):
            a = P[n]
            segs.append((n, (a[0], 0.0, a[2] - 0.04 * k), (a[0], 0.0, a[2] + 0.17 * k), 0.05 * k, 0.045 * k))
        elif n in ("LeftShoulder", "RightShoulder", "Neck"):
            c = kids[0] if kids else None
            if c:
                segs.append((n, P[n], P[c], 0.045 * k, 0.045 * k))
        elif kids:
            r = 0.07 if "Leg" in n or "UpLeg" in n else 0.05
            segs.append((n, P[n], P[kids[0]], r * k, r * 0.8 * k))
    pos, nrm, jnt = [], [], []
    for bone, a, b, r, r2 in segs:
        c = _box(a, b, r, r2)
        if bone in ("LeftFoot", "RightFoot"):              # a flat foot box sitting on the ground
            c = [(x, max(0.0, y) + (0.08 * k if i in (2, 3, 6, 7) else 0.0), z) for i, (x, y, z) in enumerate(_box(a, b, r, r2))]
        for f in _FACES:
            q = [c[i] for i in f]
            u = [q[1][i] - q[0][i] for i in range(3)]; v = [q[2][i] - q[0][i] for i in range(3)]
            n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            ln = math.sqrt(sum(x * x for x in n)) or 1
            n = [x / ln for x in n]
            for tri in ((0, 1, 2), (0, 2, 3)):
                for t in tri:
                    pos.append(q[t]); nrm.append(n); jnt.append(idx[bone])
    nv = len(pos)
    buf = bytearray()

    def add(data: bytes) -> tuple[int, int]:
        while len(buf) % 4:
            buf.append(0)
        off = len(buf); buf.extend(data)
        return off, len(data)

    views, accessors = [], []

    def accessor(data: bytes, ctype: int, count: int, typ: str, extra=None, target=None):
        off, ln = add(data)
        v = {"buffer": 0, "byteOffset": off, "byteLength": ln}
        if target:
            v["target"] = target
        views.append(v)
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": count, "type": typ}
        a.update(extra or {})
        accessors.append(a)
        return len(accessors) - 1

    mn = [min(p[i] for p in pos) for i in range(3)]; mx = [max(p[i] for p in pos) for i in range(3)]
    a_pos = accessor(b"".join(struct.pack("<3f", *p) for p in pos), 5126, nv, "VEC3", {"min": mn, "max": mx}, 34962)
    a_nrm = accessor(b"".join(struct.pack("<3f", *n) for n in nrm), 5126, nv, "VEC3", None, 34962)
    a_jnt = accessor(b"".join(struct.pack("<4H", j, 0, 0, 0) for j in jnt), 5123, nv, "VEC4", None, 34962)
    a_wgt = accessor(b"".join(struct.pack("<4f", 1, 0, 0, 0) for _ in jnt), 5126, nv, "VEC4", None, 34962)
    ibm = b""
    for n in names:                                        # inverse bind: translate by -world position (column-major)
        x, y, z = P[n]
        ibm += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1)
    a_ibm = accessor(ibm, 5126, len(names), "MAT4")
    nodes = []
    for n, p, _ in _BONES:
        w = P[n]; pw = P[p] if p else (0, 0, 0)
        node = {"name": n, "translation": [w[i] - pw[i] for i in range(3)]}
        if children[n]:
            node["children"] = [idx[c] for c in children[n]]
        nodes.append(node)
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gltf = {
        "asset": {"version": "2.0", "generator": "gbox ui_evidence (synthetic)"},
        "scene": 0, "scenes": [{"nodes": [0, len(nodes) - 1]}], "nodes": nodes,
        "skins": [{"joints": list(range(len(names))), "inverseBindMatrices": a_ibm, "skeleton": 0}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "JOINTS_0": a_jnt,
                                                                  "WEIGHTS_0": a_wgt}, "material": 0}]}],
        "materials": [{"name": "body", "pbrMetallicRoughness": {"baseColorFactor": [*color, 1.0], "metallicFactor": 0.0,
                                                                 "roughnessFactor": 0.7}}],
        "buffers": [{"byteLength": 0}], "bufferViews": views, "accessors": accessors,
    }
    while len(buf) % 4:
        buf.append(0)
    gltf["buffers"][0]["byteLength"] = len(buf)
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(buf)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(buf), b"BIN\x00") + bytes(buf))


# ------------------------------------------------------------------------------------------------------- fixture routing
_NOW = re.compile(r"^\$now([+-]\d+(?:\.\d+)?)?(ms)?$")


def with_now(v, now: float | None = None):
    """"$now", "$now-300" (seconds) and "$now-300ms" (epoch milliseconds) become timestamps, so ages read naturally."""
    now = time.time() if now is None else now
    if isinstance(v, str):
        m = _NOW.match(v)
        if m:
            t = now + float(m.group(1) or 0)
            return int(t * 1000) if m.group(2) else round(t, 3)
        return v
    if isinstance(v, list):
        return [with_now(x, now) for x in v]
    if isinstance(v, dict):
        return {k: with_now(x, now) for k, x in v.items()}
    return v


class Fixtures:
    """Answers an /api request from the fixture file: (status, content-type, body bytes). Never forwards anything."""

    def __init__(self, data: dict | None = None, base: Path | None = None):
        data = data or {}
        self.routes: dict = data.get("routes", {})
        self.lists = tuple(data.get("lists", [])) + DEFAULT_LISTS
        self.base = base or Path.cwd()
        self.misses: list[str] = []
        self._glb_cache: dict[str, bytes] = {}

    @classmethod
    def load(cls, path: Path) -> "Fixtures":
        return cls(load_fixture_file(path), Path(path).resolve().parent)

    def _find(self, method: str, path: str, query: str):
        full = path + ("?" + query if query else "")
        keys = ([f"{method} {full}", f"{method} {path}"] + ([full, path] if method == "GET" else []))
        for k in keys:
            if k in self.routes:
                return True, self.routes[k]
        for k, v in self.routes.items():
            if "*" not in k:
                continue
            m, _, pat = k.partition(" ") if k.split(" ", 1)[0] in ("GET", "POST", "PUT", "PATCH", "DELETE") else ("GET", "", k)
            if m != method:
                continue
            if fnmatch.fnmatchcase(full, pat) or fnmatch.fnmatchcase(path, pat):
                return True, v
        return False, None

    def _render(self, v, body) -> tuple[int, str, bytes]:
        v = with_now(v)
        if isinstance(v, dict):
            if "$by" in v:
                key = None
                cur = body if isinstance(body, dict) else {}
                for part in str(v["$by"]).split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                key = cur
                cases = v.get("cases", {})
                chosen = cases.get(str(key)) if key is not None and str(key) in cases else v.get("$default", {"ok": True})
                return self._render(chosen, body)
            if "$svg" in v:
                return 200, "image/svg+xml", v["$svg"].encode()
            if "$placeholder" in v:
                return 200, "image/svg+xml", placeholder_svg(str(v["$placeholder"]), v.get("hue"), v.get("w", 640), v.get("h", 480),
                                                             v.get("style", ""))
            if "$glb" in v:
                opts = dict(v["$glb"] or {})
                key = json.dumps(opts, sort_keys=True)
                if key not in self._glb_cache:
                    if "color" in opts:
                        opts["color"] = tuple(opts["color"])
                    self._glb_cache[key] = synthetic_glb(**opts)
                return 200, "model/gltf-binary", self._glb_cache[key]
            if "$file" in v:
                f = (self.base / v["$file"]).resolve()
                if not f.is_file():
                    return 404, "application/json", b'{"detail":"fixture file missing"}'
                return 200, mimetypes.guess_type(f.name)[0] or "application/octet-stream", f.read_bytes()
            if "$status" in v:
                return int(v["$status"]), "application/json", json.dumps(v.get("$body", {"detail": "fixture error"})).encode()
        return 200, "application/json", json.dumps(v).encode()

    def answer(self, method: str, raw_path: str, body=None) -> tuple[int, str, bytes]:
        u = urlsplit(raw_path)
        path, query = unquote(u.path), u.query
        # drop the token the shells append; fixtures never see credentials
        query = "&".join(p for p in query.split("&") if p and not p.startswith("token=") and not p.startswith("t="))
        hit, v = self._find(method, path, query)
        if hit:
            return self._render(v, body)
        if method != "GET":
            return 200, "application/json", b'{"ok":true}'
        self.misses.append(path + ("?" + query if query else ""))
        low = path.lower()
        if low.endswith(".glb"):
            return self._render({"$glb": {}}, None)
        if any(low.endswith(h) or (h.startswith("/") and h + "/" in low) for h in IMAGE_HINT):
            return 200, "image/svg+xml", placeholder_svg(Path(path).parent.name or "picture")
        if path.rstrip("/") in self.lists:                 # a collection: an empty list, its members stay {}
            return 200, "application/json", b"[]"
        return 200, "application/json", b"{}"


def load_fixture_file(path: Path) -> dict:
    """A fixture file with its "include" files merged underneath: routes, lists, local_storage, desktop and shared
    snippets (other top-level keys such as "setup_js"); an include's own shots and descriptions are not carried."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    merged: dict = {"routes": {}, "lists": [], "local_storage": {}, "desktop": {}}
    snippets: dict = {}
    for inc in data.get("include", []):
        base = load_fixture_file(path.resolve().parent / inc)
        snippets.update({k: v for k, v in base.items() if k not in merged and k not in ("shots", "include", "pr", "title", "branch", "about")})
        merged["routes"].update(base.get("routes", {}))
        merged["lists"] += base.get("lists", [])
        merged["local_storage"].update(base.get("local_storage", {}))
        merged["desktop"].update(base.get("desktop", {}))
    merged["routes"].update(data.get("routes", {}))
    merged["lists"] += data.get("lists", [])
    merged["local_storage"].update(data.get("local_storage", {}))
    merged["desktop"].update(data.get("desktop", {}))
    return {**snippets, **data, **merged}


# --------------------------------------------------------------------------------------------------------- static files
def static_file(clients: Path, path: str) -> Path | None:
    """The control plane's static routes over a clients tree (system/clients)."""
    clients = clients.resolve()
    path = unquote(urlsplit(path).path)
    if path in ("/", "/index.html"):
        f = clients / "web" / "index.html"
    elif path == "/live-poll.js":
        f = clients / "desktop" / "live-poll.js"
    elif path.startswith("/viz/"):
        f = clients / "web" / "viz" / path[5:]
    elif path.startswith("/clients/"):
        f = clients / path[len("/clients/"):]
    else:
        f = clients / "web" / path.lstrip("/")
    f = f.resolve()
    if clients not in f.parents or not f.is_file():
        return None
    return f


def make_server(clients: Path, fixtures: Fixtures, port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status: int, ctype: str, body: bytes):
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass                                   # the page went away mid-answer (a shot finished)

        def _handle(self):
            body = None
            n = int(self.headers.get("content-length") or 0)
            if n:
                raw = self.rfile.read(n)
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
            path = self.path
            if path.startswith("/api/") or path == "/api":
                self._send(*fixtures.answer("GET" if self.command == "HEAD" else self.command, path, body))
                return
            if self.command not in ("GET", "HEAD"):
                self._send(200, "application/json", b'{"ok":true}')
                return
            low = urlsplit(path).path.lower()
            if low.startswith("/brand/") or low == "/favicon.ico":
                self._send(200, "image/svg+xml", placeholder_svg("", 220, 32, 32))
                return
            f = static_file(clients, path)
            if not f:
                self._send(404, "text/plain", b"not found")
                return
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if f.suffix in (".js", ".mjs", ".cjs"):
                ctype = "text/javascript"
            self._send(200, ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""), f.read_bytes())

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    return ThreadingHTTPServer((host, port), H)


# --------------------------------------------------------------------------------------------------------- the browser
GBOX_SHIM = """
(() => {
  const SETTINGS = Object.assign({ apiUrl: location.origin }, %s);
  const call = async (p, body, method) => {
    const r = await fetch(p, { method: method || (body ? "POST" : "GET"), headers: { "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined });
    const t = await r.text(); let d; try { d = JSON.parse(t); } catch { d = t; }
    return r.ok ? { ok: true, data: d } : { ok: false, error: r.status + " " + t };
  };
  const base = {
    api: (p, body) => call(p, body), apiTagged: async p => { const r = await call(p); return r.ok ? { ok: true, etag: null, data: r.data } : r; },
    settings: async () => SETTINGS, saveSettings: async s => Object.assign(SETTINGS, s), token: async () => "fixture-token",
    taskSnapshot: async () => [], padDevices: async () => [], sparkStatus: async () => ({ ssh: true, service: "active", api: true }),
    updatePending: async () => false, consoleTail: async () => "",
  };
  window.gbox = new Proxy(base, { get(t, k) { if (k in t) return t[k]; if (typeof k === "string" && /^on[A-Z]/.test(k)) return () => {};
    return async () => ({}); } });
})();
"""


def _init_script(fx_data: dict, desktop: bool) -> str:
    ls = json.dumps(fx_data.get("local_storage", {}))
    js = f"try {{ const o = {ls}; for (const [k, v] of Object.entries(o)) localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); }} catch (e) {{}}\n"
    if desktop:
        js += GBOX_SHIM % json.dumps((fx_data.get("desktop") or {}).get("settings", {}))
    return js


def run_shots(base_url: str, fx_data: dict, shots: list[dict], out: Path, offline: bool = False, log=print) -> list[Path]:
    from playwright.sync_api import sync_playwright
    try:
        from browser_lifecycle import BrowserLease
    except ModuleNotFoundError:
        from scripts.browser_lifecycle import BrowserLease

    out.mkdir(parents=True, exist_ok=True)
    made, local = [], urlsplit(base_url).netloc
    with sync_playwright() as pw:
        # Reuse one managed browser for the batch; each shot gets an isolated context.
        import os
        with BrowserLease(os.environ.get("GBOX_CHROME") or pw.chromium.executable_path, software_gl=True) as lease:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{lease['port']}")
            try:
                for shot in shots:
                    vw, vh = shot.get("viewport", [1280, 800])
                    ctx = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=shot.get("scale", 1),
                                              color_scheme=shot.get("color_scheme", "dark"),
                                              reduced_motion=shot.get("reduced_motion", "no-preference"))
                    try:
                        def route(r):                                  # (one parameter: playwright passes the request to a second)
                            host = urlsplit(r.request.url).netloc
                            if host == local or (not offline and host in CDN_HOSTS):
                                return r.continue_()
                            return r.abort()                       # nothing else: no control plane, no LAN, no telemetry
                        ctx.route("**/*", route)
                        ctx.add_init_script(_init_script(fx_data, shot["url"].lstrip("/").startswith("clients/desktop/")))
                        if shot.get("init_js"):
                            ctx.add_init_script(shot["init_js"])
                        page = ctx.new_page()
                        errors = []
                        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                        page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
                        page.on("dialog", lambda d: d.accept())
                        page.goto(base_url.rstrip("/") + "/" + shot["url"].lstrip("/"), wait_until="load")
                        page.wait_for_timeout(shot.get("settle", 600))
                        for a in shot.get("actions", []):
                            (k, v), = a.items()
                            if isinstance(v, str) and v.startswith("$") and v[1:] in fx_data:   # "$setup_js": a shared snippet
                                v = fx_data[v[1:]]
                            if k == "wait":
                                page.wait_for_timeout(v)
                            elif k == "wait_for":
                                page.wait_for_selector(v, timeout=15000)
                            elif k == "click":
                                page.click(v)
                            elif k == "dblclick":
                                page.dblclick(v)
                            elif k == "right_click":
                                page.click(v, button="right")
                            elif k == "hover":
                                page.hover(v)
                            elif k == "eval":
                                page.evaluate(v)
                            elif k == "mouse":
                                page.mouse.move(v[0], v[1], steps=4)
                            elif k == "click_at":                  # [x, y] or [x, y, "right"]
                                page.mouse.click(v[0], v[1], button=v[2] if len(v) > 2 else "left")
                            elif k == "press":
                                page.keyboard.press(v)
                            elif k == "select":
                                page.select_option(v[0], v[1])
                            elif k == "fill":
                                page.fill(v[0], v[1])
                            elif k == "viewport":                  # resize the window: pages lay their pop-ups out again
                                vw, vh = v
                                page.set_viewport_size({"width": vw, "height": vh})
                            else:
                                raise ValueError(f"unknown action {k!r}")
                        dest = out / f"{shot['name']}.png"
                        if shot.get("clip"):
                            box = page.locator(shot["clip"]).first.bounding_box()
                            if not box:
                                raise RuntimeError(f"{shot['name']}: {shot['clip']} is not on screen")
                            pad = shot.get("pad", 8)
                            x, y = max(0, box["x"] - pad), max(0, box["y"] - pad)
                            clip = {"x": x, "y": y, "width": min(vw - x, box["width"] + 2 * pad), "height": min(vh - y, box["height"] + 2 * pad)}
                            page.screenshot(path=str(dest), clip=clip)
                        else:
                            page.screenshot(path=str(dest))
                        size = dest.stat().st_size
                        log(f"{dest} ({size // 1024} KB){'  WARNING: over 1 MB' if size > 1_000_000 else ''}")
                        for e in errors[:8]:
                            log(f"  page error: {e[:300]}")
                        made.append(dest)
                    finally:
                        ctx.close()
            finally:
                browser.close()
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clients", required=True, type=Path, help="a checkout's system/clients directory")
    ap.add_argument("--fixtures", required=True, type=Path, help="fixture JSON (routes, lists, local_storage, desktop, shots)")
    ap.add_argument("--shots", type=Path, help="shot spec JSON (a list, or {shots: [...]}); default: the fixture file's shots")
    ap.add_argument("--out", type=Path, help="where the PNGs go")
    ap.add_argument("--only", default="", help="comma-separated shot names")
    ap.add_argument("--offline", action="store_true", help="block the public CDNs too (three.js views stay empty)")
    ap.add_argument("--serve", action="store_true", help="only serve the fixtures (prints the URL) until Ctrl+C")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--misses", action="store_true", help="list the /api paths no fixture answered")
    a = ap.parse_args(argv)
    fx_data = load_fixture_file(a.fixtures)
    fixtures = Fixtures(fx_data, a.fixtures.resolve().parent)
    shots = fx_data.get("shots", [])
    if a.shots:
        s = json.loads(a.shots.read_text(encoding="utf-8"))
        shots = s.get("shots", []) if isinstance(s, dict) else s
    if a.only:
        want = set(a.only.split(","))
        shots = [s for s in shots if s["name"] in want]
    srv = make_server(a.clients, fixtures, a.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        if a.serve:
            print(url, flush=True)
            threading.Event().wait()
        if not a.out:
            ap.error("--out is required unless --serve")
        run_shots(url, fx_data, shots, a.out, a.offline)
        if a.misses:
            for m in sorted(set(fixtures.misses)):
                print("  unanswered:", m)
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
