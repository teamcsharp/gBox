"""Super Mario 64 characters in the decomp's data layout -> rigged, smooth-shaded, textured glTF donors.

One reader for two sources of the same layout (n64decomp/sm64: actors/<name>/{geo.inc.c, model.inc.c, anims}):

  ROM   the operator's own Super Mario 64 (N64, US or EU): the level scripts' segment loads (LOAD_MIO0 / LOAD_RAW) are
        found by scanning, actor banks are recognised by their animation tables, geo layouts and F3D display lists are
        read from the segments (RomSource). Mario, Peach, Toad, Yoshi and Bowser (ROM_CAST).
  C     a pack in the decomp's source format, e.g. the Render96 HD model pack (github.com/Render96/ModelPack, branch
        models_vanilla: Render96/actors/<name>/): Vtx / Gfx / Lights1 / GeoLayout C arrays plus PNG textures (CSource).
        The files are parsed as text only; nothing in them is compiled or run.

Pipeline (both sources): geo layout -> node tree with SM64's own GEO_OPEN_NODE / GEO_CLOSE_NODE semantics (branches
inlined, switch nodes take case 0, render ranges take the nearest LOD, wing-cap and held-object nodes skipped) ->
every GEO_ANIMATED_PART is a joint, posed by one frame of the character's own animation (SM64 limbs are modelled
pointing along +X; the game always animates them) -> display lists run in SM64's draw order (per layer, in tree
order) with ONE vertex cache, so a Fast64 "skinned" seam (vertices loaded under the parent joint's matrix, used by the
child's triangles) stays one continuous mesh: each vertex is transformed when it is loaded and keeps that joint ->
lit vertices keep their own normals (smooth shading); texture-generated (matcap) materials of HD packs become their
matcap's base colour; decal textures (eyes, emblem, buttons) stay textures.

Donor shape: +Y up, facing +Z, the character's left on +X, metres (SM64 units x 0.01, after the geo scale). Joints
are named j<NN>[_<role>]; gbox_role extras on the role joints (gbox.blender_roundtrip reads them), so the GLB goes
through `characters op=add` (the Blender round trip) as a ready donor. rig_spec() maps the 18 body roles per
skeleton; where the game skeleton has no such bone the reader adds one without moving any vertex (a neck / head
split, clavicles pulled in from the shoulder pivots) or, for Peach's dress, two legs whose weights blend the skirt.

  python -m gbox.sm64_decomp rom <rom.z64|.zip> <out dir> [--only mario,peach,toad,yoshi,bowser]
  python -m gbox.sm64_decomp pack <Render96/actors dir> <out dir> --rom <rom> [--only mario,luigi,wario,...]
  (scripts/mario_donors.py builds both sets and imports them: local library or the Spark API)
"""
from __future__ import annotations

import io
import json
import re
import struct
from pathlib import Path

import numpy as np

READER_VERSION = 1
UNIT = 0.01                                                  # SM64 world units -> metres (Mario ~1.6 m)
LAYERS = 8                                                   # LAYER_FORCE .. LAYER_TRANSPARENT_INTER

# ================================================================ geo layout -> tree

GEO_SIZE = {0x01: 4, 0x03: 4, 0x04: 4, 0x05: 4, 0x06: 4, 0x07: 4, 0x08: 12, 0x09: 4, 0x0B: 4, 0x0C: 4, 0x0D: 8,
            0x0E: 8, 0x0F: 0x14, 0x16: 8, 0x17: 4, 0x18: 8, 0x19: 8, 0x1A: 8, 0x1C: 12, 0x1E: 8, 0x1F: 16, 0x20: 4}


def build_tree(cmds: list[tuple]) -> dict:
    """Flat geo commands (branches already inlined) -> {kind: root, children}. SM64's semantics: a node is a child
    of the node list's entry one level up; GEO_OPEN_NODE opens the last node registered at the current level (also
    after a GEO_CLOSE_NODE: Yoshi's head reopens that way)."""
    root = {"kind": "root", "children": []}
    lst, i = [root, root], 1
    for c in cmds:
        if c[0] == "open":
            if i + 1 >= len(lst):
                lst.append(lst[i])
            else:
                lst[i + 1] = lst[i]
            i += 1
        elif c[0] == "close":
            i = max(1, i - 1)
        else:
            node = dict(c[1], kind=c[0], children=[])
            lst[i - 1]["children"].append(node)
            lst[i] = node
    return root


# ---------------------------------------------------------------- binary (ROM)

class SegMem:
    """Segmented memory: {segment number: bytes}."""

    def __init__(self, segs: dict[int, bytes]):
        self.seg = dict(segs)

    def at(self, addr: int, n: int) -> bytes:
        s, o = (addr >> 24) & 0x1F, addr & 0xFFFFFF
        if s not in self.seg:
            raise KeyError(f"segment {s:#x} not loaded (address {addr:#010x})")
        return self.seg[s][o:o + n]

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.at(a, 4))[0]


def geo_cmds_rom(mem: SegMem, addr: int) -> list[tuple]:
    """Binary geo layout at a segmented address -> flat commands, branches inlined."""
    out, ret, a = [], [], addr
    for _guard in range(200000):
        b = mem.at(a, 24)
        cmd = b[0]
        if cmd == 0x00:                                     # branch and link
            ret.append(a + 8)
            a = struct.unpack_from(">I", b, 4)[0]
            continue
        if cmd == 0x02:                                     # branch (b[1] = 1: and link)
            if b[1]:
                ret.append(a + 8)
            a = struct.unpack_from(">I", b, 4)[0]
            continue
        if cmd in (0x01, 0x03):                             # end / return
            if not ret:
                break
            a = ret.pop()
            continue
        if cmd == 0x04:
            out.append(("open",))
            a += 4
            continue
        if cmd == 0x05:
            out.append(("close",))
            a += 4
            continue
        if cmd == 0x13:                                     # animated part: layer, x, y, z, dl
            out.append(("part", {"layer": b[1] & 0x0F, "t": struct.unpack_from(">3h", b, 2),
                                 "dl": struct.unpack_from(">I", b, 8)[0] or None}))
            a += 12
        elif cmd == 0x15:                                   # display list
            out.append(("dl", {"layer": b[1] & 0x0F, "dl": struct.unpack_from(">I", b, 4)[0] or None}))
            a += 8
        elif cmd == 0x0E:                                   # switch case
            out.append(("switch", {"n": struct.unpack_from(">h", b, 2)[0], "fn": struct.unpack_from(">I", b, 4)[0]}))
            a += 8
        elif cmd == 0x0D:                                   # render range
            out.append(("range", {"lo": struct.unpack_from(">h", b, 4)[0], "hi": struct.unpack_from(">h", b, 6)[0]}))
            a += 8
        elif cmd == 0x1D:                                   # scale (+ dl)
            dl = struct.unpack_from(">I", b, 8)[0] if b[1] & 0x80 else None
            out.append(("scale", {"layer": b[1] & 0x0F, "s": struct.unpack_from(">I", b, 4)[0] / 65536.0, "dl": dl}))
            a += 12 if b[1] & 0x80 else 8
        elif cmd == 0x10:                                   # translate / rotate (+ dl)
            kind = (b[1] >> 4) & 7
            size = {0: 16, 1: 8, 2: 8, 3: 4}[kind] + (4 if b[1] & 0x80 else 0)
            t = struct.unpack_from(">3h", b, 4 if kind == 0 else 2) if kind in (0, 1) else (0, 0, 0)
            r = struct.unpack_from(">3h", b, 10) if kind == 0 else (struct.unpack_from(">3h", b, 2) if kind == 2 else (0, 0, 0))
            out.append(("trs", {"layer": b[1] & 0x0F, "t": t, "r": r,
                                "dl": struct.unpack_from(">I", b, size - 4)[0] if b[1] & 0x80 else None}))
            a += size
        elif cmd in (0x11, 0x12):                           # translate / rotate node (+ dl)
            dl = struct.unpack_from(">I", b, 8)[0] if b[1] & 0x80 else None
            v = struct.unpack_from(">3h", b, 2)
            out.append(("trs", {"layer": b[1] & 0x0F, "t": v if cmd == 0x11 else (0, 0, 0),
                                "r": v if cmd == 0x12 else (0, 0, 0), "dl": dl}))
            a += 8 + (4 if b[1] & 0x80 else 0)
        elif cmd == 0x14:                                   # billboard (+ dl)
            dl = struct.unpack_from(">I", b, 8)[0] if b[1] & 0x80 else None
            out.append(("group", {"layer": b[1] & 0x0F, "dl": dl}))
            a += 8 + (4 if b[1] & 0x80 else 0)
        elif cmd == 0x1C:                                   # held object
            out.append(("held", {}))
            a += 12
        elif cmd == 0x0A:
            out.append(("group", {}))
            a += 8 + (4 if b[1] else 0)
        else:
            if cmd not in GEO_SIZE:
                raise ValueError(f"unknown geo command {cmd:#04x} at {a:#010x}")
            out.append(("group", {"asm": cmd == 0x18}))
            a += GEO_SIZE[cmd]
    return out


# ---------------------------------------------------------------- C (decomp source format)

_DEFINES = {"VERSION_US", "VERSION_EU"}


def _preprocess(text: str) -> str:
    """Strip comments and resolve #ifdef VERSION_* blocks (US); other directives are kept for the parsers."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"(?m)//.*$", "", text)
    out, keep = [], [True]
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"#\s*(ifdef|ifndef|if|elif|else|endif)\b\s*(.*)", s)
        if m:
            d, arg = m.groups()
            if d in ("ifdef", "ifndef"):
                on = (arg.strip() in _DEFINES) == (d == "ifdef")
                keep.append(keep[-1] and on)
            elif d == "if":
                keep.append(keep[-1] and bool(re.search(r"defined\(\s*VERSION_(US|EU)\s*\)", arg)))
            elif d in ("else", "elif") and len(keep) > 1:
                keep[-1] = keep[-2] and not keep[-1]
            elif d == "endif" and len(keep) > 1:
                keep.pop()
            continue
        if keep[-1]:
            out.append(line)
    return "\n".join(out)


def _statements(text: str):
    """Top-level `type name[...] = body;` declarations -> (type words, name, body)."""
    depth, start, in_str = 0, 0, False
    for k, ch in enumerate(text):
        if in_str:
            if ch == '"' and text[k - 1] != "\\":
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        elif ch == ";" and depth == 0:
            st = text[start:k].strip()
            start = k + 1
            m = re.match(r"(?s)^((?:[A-Za-z_]\w*\s+|\*\s*)+?)\s*(?:\*\s*(?:const\s+)?)?([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*=\s*(.*)$",
                         re.sub(r"^(?:[ \t]*#[^\n]*\n|\s+)+", "", st))
            if m:
                yield m.group(1).split(), m.group(2), m.group(4).strip()


_CALL = re.compile(r"([A-Za-z_]\w*)\s*\(")


def _calls(body: str) -> list[tuple[str, list[str]]]:
    """'{ gsX(a, b(c)), gsY() }' -> [(gsX, ['a', 'b(c)']), (gsY, [])]: macro calls with top-level comma args."""
    out, k = [], 0
    while True:
        m = _CALL.search(body, k)
        if not m:
            break
        depth, j, args, cur = 1, m.end(), [], []
        while j < len(body) and depth:
            ch = body[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            if ch == "," and depth == 1:
                args.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
            j += 1
        tail = "".join(cur).strip()
        if tail or args:
            args.append(tail)
        out.append((m.group(1), args))
        k = j + 1
    return out


_CONST = {"G_TX_NOMIRROR": 0, "G_TX_WRAP": 0, "G_TX_MIRROR": 1, "G_TX_CLAMP": 2, "G_TX_NOMASK": 0, "G_TX_NOLOD": 0,
          "G_TX_RENDERTILE": 0, "G_TX_LOADTILE": 7, "G_TEXTURE_IMAGE_FRAC": 2, "G_ON": 1, "G_OFF": 0,
          "G_IM_FMT_RGBA": 0, "G_IM_FMT_YUV": 1, "G_IM_FMT_CI": 2, "G_IM_FMT_IA": 3, "G_IM_FMT_I": 4,
          "G_IM_SIZ_4b": 0, "G_IM_SIZ_8b": 1, "G_IM_SIZ_16b": 2, "G_IM_SIZ_32b": 3,
          "G_LIGHTING": 0x20000, "G_TEXTURE_GEN": 0x40000, "G_TEXTURE_GEN_LINEAR": 0x80000, "G_SHADE": 0x4,
          "G_SHADING_SMOOTH": 0x200, "G_CULL_FRONT": 0x1000, "G_CULL_BACK": 0x2000, "G_CULL_BOTH": 0x3000,
          "G_ZBUFFER": 0x1, "G_FOG": 0x10000, "G_LOD": 0x100000, "G_CLIPPING": 0x800000,
          "LAYER_FORCE": 0, "LAYER_OPAQUE": 1, "LAYER_OPAQUE_DECAL": 2, "LAYER_OPAQUE_INTER": 3, "LAYER_ALPHA": 4,
          "LAYER_TRANSPARENT": 5, "LAYER_TRANSPARENT_DECAL": 6, "LAYER_TRANSPARENT_INTER": 7}


def _num(s: str):
    """A C integer expression of literals and known constants (| << >> + - * ( )), else the stripped string."""
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        pass
    expr = re.sub(r"\(\s*(?:u?s?\d+|unsigned|signed|int|short|char)\s*\)", "", s)   # casts
    toks = re.findall(r"0[xX][0-9A-Fa-f]+|\d+|[A-Za-z_]\w*|<<|>>|[|+\-*()&~]", expr)
    if not toks or "".join(toks).replace(" ", "") != re.sub(r"\s+", "", expr):
        return s
    py = []
    for t in toks:
        if re.match(r"[A-Za-z_]", t):
            if t not in _CONST:
                return s
            py.append(str(_CONST[t]))
        else:
            py.append(str(int(t, 0)) if t[0].isdigit() else t)
    try:
        return int(eval("".join(py), {"__builtins__": {}}, {}))       # noqa: S307 - digits and operators only
    except Exception:                                                   # noqa: BLE001
        return s


class CSource:
    """An actor folder in the decomp source format: model.inc.c (+ geo.inc.c, anims/*.inc.c), PNG textures."""

    def __init__(self, actor_dir: Path, texture_roots: list[Path] | None = None):
        self.dir = Path(actor_dir)
        self.roots = [self.dir, *(texture_roots or [])]
        self.vtx: dict[str, np.ndarray] = {}
        self.gfx: dict[str, list] = {}
        self.lights: dict[str, tuple] = {}
        self.tex: dict[str, str] = {}
        self.geo: dict[str, list] = {}
        self.s16: dict[str, np.ndarray] = {}
        self.anim: dict[str, list] = {}
        self.anim_tables: dict[str, list[str]] = {}
        files = [self.dir / "model.inc.c", self.dir / "geo.inc.c"] + sorted((self.dir / "anims").glob("*.inc.c"))
        for f in files:
            if f.is_file():
                self._parse(_preprocess(f.read_text("utf-8", "replace")))

    def _parse(self, text: str):
        for words, name, body in _statements(text):
            ty = words[-1] if words[-1] not in ("const", "static") else words[-2]
            if ty == "Vtx":
                v = np.array([int(x, 0) for x in re.findall(r"-?0[xX][0-9A-Fa-f]+|-?\d+", body)], np.int64)
                self.vtx[name] = v.reshape(-1, 10)
            elif ty == "Gfx":
                self.gfx[name] = _calls(body)
            elif ty.startswith("Lights"):
                c = _calls(body)
                if c and c[0][0].startswith("gdSPDefLights"):
                    a = [int(_num(x)) for x in c[0][1]]
                    self.lights[name] = (tuple(a[0:3]), tuple(a[3:6]))
            elif ty in ("u8", "u16", "Texture", "ALIGNED8") or "rgba" in name or "_ia" in name:
                m = re.search(r'"([^"]+)"', body) or re.search(r'#include\s+"([^"]+)"', body)
                if m:
                    self.tex[name] = m.group(1)
                elif ty == "u16":                              # animation indices
                    self.s16[name] = np.array([int(x, 0) for x in re.findall(r"-?0[xX][0-9A-Fa-f]+|-?\d+", body)],
                                              np.int64) & 0xFFFF
            elif ty == "s16":
                self.s16[name] = np.array([int(x, 0) for x in re.findall(r"-?0[xX][0-9A-Fa-f]+|-?\d+", body)], np.int64)
            elif ty == "GeoLayout":
                self.geo[name] = _calls(body)
            elif "Animation" in words and "&" in body:          # a table: { &anim_a, &anim_b, NULL }
                self.anim_tables[name] = re.findall(r"&\s*([A-Za-z_]\w*)", body)
            elif ty == "Animation":
                body2 = body.strip().strip("{}")
                parts = [p.strip() for p in re.split(r",(?![^()]*\))", body2) if p.strip()]
                self.anim[name] = parts

    def texture_path(self, sym: str) -> Path | None:
        ref = self.tex.get(sym)
        if not ref:
            return None
        base = Path(ref).name
        base = re.sub(r"\.inc\.c$", "", base)
        cands = [base + ".png", base]
        for root in self.roots:
            for c in cands:
                for p in (root / c, root / Path(ref).parent.name / c):
                    if p.is_file():
                        return p
        stem = base.split(".")[0]                             # 'mario_buttons.rgba16' declared as rgba32: any format
        for root in self.roots:
            hits = sorted(root.glob(stem + ".*.png"))
            if hits:
                return hits[0]
        return None

    def geo_cmds(self, name: str, _depth: int = 0) -> list[tuple]:
        """GeoLayout array -> flat commands, GEO_BRANCH targets inlined (they are layouts of this file)."""
        out = []
        for mac, args in self.geo[name]:
            m = mac.replace("GEO_", "", 1)
            if m == "OPEN_NODE":
                out.append(("open",))
            elif m == "CLOSE_NODE":
                out.append(("close",))
            elif m in ("RETURN", "END"):
                break
            elif m == "BRANCH":
                tgt = args[1].strip()
                if tgt in self.geo and _depth < 32:
                    out += self.geo_cmds(tgt, _depth + 1)
                    if int(_num(args[0])) == 0:
                        break
            elif m in ("BRANCH_AND_LINK",):
                tgt = args[0].strip()
                if tgt in self.geo and _depth < 32:
                    out += self.geo_cmds(tgt, _depth + 1)
            elif m == "ANIMATED_PART":
                out.append(("part", {"layer": _num(args[0]), "t": tuple(int(_num(x)) for x in args[1:4]),
                                     "dl": None if args[4].strip() == "NULL" else args[4].strip()}))
            elif m == "DISPLAY_LIST":
                out.append(("dl", {"layer": _num(args[0]), "dl": args[1].strip()}))
            elif m == "SWITCH_CASE":
                out.append(("switch", {"n": _num(args[0]), "fn": args[1].strip()}))
            elif m == "RENDER_RANGE":
                out.append(("range", {"lo": int(_num(args[0])), "hi": int(_num(args[1]))}))
            elif m in ("SCALE", "SCALE_WITH_DL"):
                out.append(("scale", {"layer": _num(args[0]), "s": int(_num(args[1])) / 65536.0,
                                      "dl": args[2].strip() if len(args) > 2 else None}))
            elif m in ("TRANSLATE_ROTATE", "TRANSLATE_ROTATE_WITH_DL"):
                out.append(("trs", {"layer": _num(args[0]), "t": tuple(int(_num(x)) for x in args[1:4]),
                                    "r": tuple(int(_num(x)) for x in args[4:7]),
                                    "dl": args[7].strip() if len(args) > 7 else None}))
            elif m in ("TRANSLATE_NODE", "TRANSLATE_NODE_WITH_DL", "TRANSLATE", "TRANSLATE_WITH_DL"):
                out.append(("trs", {"layer": _num(args[0]), "t": tuple(int(_num(x)) for x in args[1:4]), "r": (0, 0, 0),
                                    "dl": args[4].strip() if len(args) > 4 else None}))
            elif m in ("ROTATION_NODE", "ROTATION_NODE_WITH_DL", "ROTATE", "ROTATE_WITH_DL"):
                out.append(("trs", {"layer": _num(args[0]), "t": (0, 0, 0), "r": tuple(int(_num(x)) for x in args[1:4]),
                                    "dl": args[4].strip() if len(args) > 4 else None}))
            elif m == "HELD_OBJECT":
                out.append(("held", {}))
            elif m == "BILLBOARD_WITH_PARAMS_AND_DL" or m == "BILLBOARD":
                out.append(("group", {}))
            elif m == "ASM":
                out.append(("group", {"asm": args[1].strip() if len(args) > 1 else ""}))
            else:
                out.append(("group", {"macro": m}))
        return out


# ================================================================ display lists -> ops

_CC_A = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "1", "NOISE"] + ["0"] * 8
_CC_B = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "CENTER", "K4"] + ["0"] * 8
_CC_C = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "SCALE", "COMBINED_ALPHA",
         "TEXEL0_ALPHA", "TEXEL1_ALPHA", "PRIMITIVE_ALPHA", "SHADE_ALPHA", "ENV_ALPHA", "LOD_FRACTION",
         "PRIM_LOD_FRAC", "K5"] + ["0"] * 16
_CC_D = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "1", "0"]
# named combine modes (gbi.h) -> the colour part of cycle 1 (a, b, c, d)
_CC_NAMED = {"G_CC_PRIMITIVE": ("0", "0", "0", "PRIMITIVE"), "G_CC_SHADE": ("0", "0", "0", "SHADE"),
             "G_CC_MODULATERGB": ("TEXEL0", "0", "SHADE", "0"), "G_CC_MODULATERGBA": ("TEXEL0", "0", "SHADE", "0"),
             "G_CC_MODULATEI": ("TEXEL0", "0", "SHADE", "0"), "G_CC_MODULATEIA": ("TEXEL0", "0", "SHADE", "0"),
             "G_CC_MODULATEIDECALA": ("TEXEL0", "0", "SHADE", "0"), "G_CC_MODULATERGBDECALA": ("TEXEL0", "0", "SHADE", "0"),
             "G_CC_DECALRGB": ("0", "0", "0", "TEXEL0"), "G_CC_DECALRGBA": ("0", "0", "0", "TEXEL0"),
             "G_CC_BLENDRGBA": ("TEXEL0", "SHADE", "TEXEL0_ALPHA", "SHADE"),
             "G_CC_BLENDRGBDECALA": ("TEXEL0", "SHADE", "TEXEL0_ALPHA", "SHADE"),
             "G_CC_MODULATERGBFADE": ("TEXEL0", "0", "SHADE", "0"), "G_CC_MODULATERGBFADEA": ("TEXEL0", "0", "SHADE", "0"),
             "G_CC_DECALFADE": ("0", "0", "0", "TEXEL0"), "G_CC_DECALFADEA": ("0", "0", "0", "TEXEL0"),
             "G_CC_BLENDRGBFADEA": ("TEXEL0", "SHADE", "TEXEL0_ALPHA", "SHADE")}


def combine_mode(abcd) -> str:
    """'shade' (no texture) | 'tex' (texture only) | 'modulate' (texture x shade) | 'blend' (texture over the shade
    colour by its alpha) | 'prim' / 'env' (a constant colour)."""
    a, b, c, d = [str(x).strip().upper().replace("G_CCMUX_", "") for x in abcd]
    toks = {a, b, c, d}
    if "TEXEL0" in toks or "TEXEL1" in toks:
        if a == "TEXEL0" and b == "SHADE" and "ALPHA" in c and d == "SHADE":
            return "blend"
        if "SHADE" in toks:
            return "modulate"
        return "tex"
    if "SHADE" in toks:
        return "shade"
    if "PRIMITIVE" in toks:
        return "prim"
    if "ENVIRONMENT" in toks:
        return "env"
    return "shade"


def ops_c(src: CSource, name: str) -> list[tuple]:
    """A Gfx array of a CSource -> ops (see run_ops)."""
    out = []
    for mac, a in src.gfx.get(name, []):
        if mac == "gsSPVertex":
            m = re.match(r"\s*&?\s*([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*\])?\s*(?:\+\s*(\d+))?", a[0])
            sym, off = m.group(1), int(m.group(2) or m.group(3) or 0)
            out.append(("vtx", sym, off, int(_num(a[1])), int(_num(a[2]))))
        elif mac == "gsSP1Triangle":
            out.append(("tri", int(_num(a[0])), int(_num(a[1])), int(_num(a[2]))))
        elif mac == "gsSP2Triangles":
            out.append(("tri", int(_num(a[0])), int(_num(a[1])), int(_num(a[2]))))
            out.append(("tri", int(_num(a[4])), int(_num(a[5])), int(_num(a[6]))))
        elif mac == "gsSP1Quadrangle":
            v = [int(_num(x)) for x in a[:4]]
            out += [("tri", v[0], v[1], v[2]), ("tri", v[0], v[2], v[3])]
        elif mac == "gsSPDisplayList":
            out.append(("call", a[0].strip()))
        elif mac == "gsSPBranchList":
            out.append(("jump", a[0].strip()))
        elif mac == "gsSPEndDisplayList":
            out.append(("end",))
        elif mac == "gsSPSetLights1" or mac == "gsSPSetLights0":
            lt = src.lights.get(a[0].strip())
            if lt:
                out.append(("lights", lt[0], lt[1]))
        elif mac == "gsSPLight":
            m = re.match(r"\s*&\s*([A-Za-z_]\w*)\s*\.\s*([al])", a[0])
            if m and m.group(1) in src.lights:
                amb, dif = src.lights[m.group(1)]
                out.append(("light_" + m.group(2), amb if m.group(2) == "a" else dif))
        elif mac == "gsDPSetTextureImage":
            out.append(("timg", a[3].strip(), _num(a[0]), _num(a[1]), _num(a[2])))
        elif mac == "gsDPSetTile":
            out.append(("tile", _num(a[4]), _num(a[0]), _num(a[1])))
        elif mac == "gsDPSetTileSize":
            out.append(("tsize", _num(a[0]), (int(_num(a[3])) >> 2) + 1, (int(_num(a[4])) >> 2) + 1))
        elif mac in ("gsDPLoadTextureBlock", "gsDPLoadTextureBlockS", "gsDPLoadTextureTile"):
            out += [("timg", a[0].strip(), _num(a[1]), _num(a[2]), _num(a[3])), ("tile", 0, _num(a[1]), _num(a[2])),
                    ("tsize", 0, int(_num(a[3])), int(_num(a[4])))]
        elif mac in ("gsDPLoadTextureBlock_4b", "gsDPLoadTextureTile_4b"):
            out += [("timg", a[0].strip(), _num(a[1]), 0, _num(a[2])), ("tile", 0, _num(a[1]), 0),
                    ("tsize", 0, int(_num(a[2])), int(_num(a[3])))]
        elif mac == "gsSPTexture":
            out.append(("texture", int(_num(a[0])), int(_num(a[1])), int(_num(a[4]))))
        elif mac == "gsDPSetCombineLERP":
            out.append(("combine", combine_mode(a[0:4])))
        elif mac == "gsDPSetCombineMode":
            out.append(("combine", combine_mode(_CC_NAMED.get(a[0].strip(), ("0", "0", "0", "SHADE")))))
        elif mac == "gsSPSetGeometryMode":
            out.append(("geo_set", int(_num(a[0])) if isinstance(_num(a[0]), int) else _flags(a[0])))
        elif mac == "gsSPClearGeometryMode":
            out.append(("geo_clear", int(_num(a[0])) if isinstance(_num(a[0]), int) else _flags(a[0])))
        elif mac == "gsSPGeometryMode":
            out += [("geo_clear", _flags(a[0])), ("geo_set", _flags(a[1]))]
        elif mac == "gsDPSetEnvColor":
            out.append(("env", tuple(int(_num(x)) for x in a[:4])))
        elif mac == "gsDPSetPrimColor":
            out.append(("prim", tuple(int(_num(x)) for x in a[2:6])))
    return out


def _flags(s: str) -> int:
    v = 0
    for t in re.findall(r"[A-Za-z_]\w*|0x[0-9a-fA-F]+|\d+", s):
        v |= _CONST.get(t, 0) if not t[0].isdigit() else int(t, 0)
    return v


def ops_rom(mem: SegMem, addr: int) -> list[tuple]:
    """A Fast3D (F3D) display list in ROM segments -> ops (calls left as ('call', address))."""
    out, a = [], addr
    for _guard in range(100000):
        w0, w1 = struct.unpack(">II", mem.at(a, 8))
        op = w0 >> 24
        a += 8
        if op == 0x04:                                       # G_VTX: ((n-1)<<4)|v0, len
            n, v0 = ((w0 >> 20) & 0xF) + 1, (w0 >> 16) & 0xF
            out.append(("vtx", w1, 0, n, v0))
        elif op == 0xBF:                                     # G_TRI1
            out.append(("tri", ((w1 >> 16) & 0xFF) // 10, ((w1 >> 8) & 0xFF) // 10, (w1 & 0xFF) // 10))
        elif op == 0x06:                                     # DL call / branch
            if (w0 >> 16) & 0xFF == 1:
                out.append(("jump", w1))
                break
            out.append(("call", w1))
        elif op == 0xB8:
            out.append(("end",))
            break
        elif op == 0x03:                                     # movemem: lights
            idx = (w0 >> 16) & 0xFF
            if idx == 0x86:
                out.append(("light_l", tuple(mem.at(w1, 3))))
            elif idx == 0x88:
                out.append(("light_a", tuple(mem.at(w1, 3))))
        elif op == 0xFD:
            out.append(("timg", w1, (w0 >> 21) & 7, (w0 >> 19) & 3, (w0 & 0xFFF) + 1))
        elif op == 0xF5:
            out.append(("tile", (w1 >> 24) & 7, (w0 >> 21) & 7, (w0 >> 19) & 3))
        elif op == 0xF2:
            out.append(("tsize", (w1 >> 24) & 7, ((w1 >> 12) & 0xFFF) // 4 + 1, (w1 & 0xFFF) // 4 + 1))
        elif op == 0xBB:
            out.append(("texture", (w1 >> 16) & 0xFFFF, w1 & 0xFFFF, w0 & 0xFF))
        elif op == 0xFC:
            a0, c0 = (w0 >> 20) & 0xF, (w0 >> 15) & 0x1F
            b0, d0 = (w1 >> 28) & 0xF, (w1 >> 15) & 7
            out.append(("combine", combine_mode((_CC_A[a0], _CC_B[b0], _CC_C[c0], _CC_D[d0]))))
        elif op == 0xB7:
            out.append(("geo_set", w1))
        elif op == 0xB6:
            out.append(("geo_clear", w1))
        elif op == 0xFB:
            out.append(("env", tuple(w1.to_bytes(4, "big"))))
        elif op == 0xFA:
            out.append(("prim", tuple(w1.to_bytes(4, "big"))))
    return out


# ================================================================ sources

class RomSource:
    """Segments of the operator's ROM for one actor: group bank (MIO0) + its geo (raw) + group0 (Mario)."""

    def __init__(self, mem: SegMem):
        self.mem = mem
        self._ops: dict[int, list] = {}

    def ops(self, dl):
        if dl not in self._ops:
            self._ops[dl] = ops_rom(self.mem, dl)
        return self._ops[dl]

    def vertices(self, sym, off, n):
        raw = self.mem.at(sym + 16 * off, 16 * n)
        v = np.frombuffer(raw, ">i2").reshape(n, 8).astype(np.int64)
        b = np.frombuffer(raw, np.uint8).reshape(n, 16).astype(np.int64)
        return np.concatenate([v[:, 0:3], v[:, 3:4], v[:, 4:6], b[:, 12:16]], 1)

    def texture(self, key):
        addr, fmt, siz, w, h = key
        from .sm64_mario import _tex_decode
        bpp = {0: 4, 1: 8, 2: 16, 3: 32}[siz]
        return _tex_decode(self.mem.at(addr, w * h * bpp // 8), fmt, siz, w, h)

    def geo(self, addr):
        return geo_cmds_rom(self.mem, addr)


class PackSource:
    """A CSource as the walker's source."""

    def __init__(self, src: CSource):
        self.src = src
        self._ops: dict[str, list] = {}
        self._img: dict[str, np.ndarray] = {}

    def ops(self, dl):
        if dl not in self._ops:
            self._ops[dl] = ops_c(self.src, dl)
        return self._ops[dl]

    def vertices(self, sym, off, n):
        return self.src.vtx[sym][off:off + n]

    def texture(self, key):
        sym = key[0]
        if sym not in self._img:
            from PIL import Image
            p = self.src.texture_path(sym)
            if p is None:
                raise FileNotFoundError(f"texture {sym} ({self.src.tex.get(sym)}) not found")
            self._img[sym] = np.asarray(Image.open(p).convert("RGBA"))
        return self._img[sym]

    def geo(self, name):
        return self.src.geo_cmds(name)


# ================================================================ animation frames

def anim_channels(values: np.ndarray, indices: np.ndarray, frame: int = 0) -> list[int]:
    """SM64 animation channels at one frame: indices are (count, start) pairs into values."""
    out = []
    for k in range(len(indices) // 2):
        cnt, st = int(indices[2 * k]), int(indices[2 * k + 1])
        i = st + (min(frame, cnt - 1) if cnt > 0 else 0)
        out.append(int(values[i]) if 0 <= i < len(values) else 0)
    return out


def rots_from_channels(ch: list[int]) -> list[tuple[int, int, int]]:
    """Channels (root x, y, z translation, then x, y, z rotation per part) -> [(rx, ry, rz)] per animated part."""
    return [(ch[3 + 3 * j], ch[4 + 3 * j], ch[5 + 3 * j]) for j in range((len(ch) - 3) // 3)]


def rom_anim(mem: SegMem, table: int, index: int, frame: int = 0, parts: int | None = None) -> list[tuple[int, int, int]]:
    """An animation of a group bank's table (segmented pointer array) -> part rotations (`parts` = the geo layout's
    animated parts; else the header's bone count)."""
    ptr = mem.u32(table + 4 * index)
    flags, ydiv, start, ls, le, nparts = struct.unpack(">6h", mem.at(ptr, 12))
    vals, idx = struct.unpack(">II", mem.at(ptr + 12, 8))
    nidx = ((parts if parts is not None else nparts) + 1) * 6
    indices = np.frombuffer(mem.at(idx, 2 * nidx), ">u2").astype(np.int64)
    top = int(max(indices[1::2] + indices[0::2])) if len(indices) else 0
    values = np.frombuffer(mem.at(vals, 2 * top), ">i2").astype(np.int64)
    return rots_from_channels(anim_channels(values, indices, frame))


def c_anim(src: CSource, name: str, frame: int = 0) -> list[tuple[int, int, int]]:
    """A decomp C animation (struct Animation + _values / _indices arrays) -> part rotations."""
    parts = src.anim[name]
    syms = [p.strip().lstrip("&") for p in parts]
    vals = next((src.s16[s] for s in syms if s in src.s16 and "value" in s), None)
    idx = next((src.s16[s] for s in syms if s in src.s16 and "ind" in s), None)
    if vals is None:
        vals = src.s16.get(name + "_values")
    if idx is None:
        idx = src.s16.get(name + "_indices")
    if vals is None or idx is None:
        raise KeyError(f"animation {name}: values / indices not found")
    return rots_from_channels(anim_channels(vals, idx, frame))


def mario_rom_anim(rom: bytes, index: int, frame: int = 0) -> list[tuple[int, int, int]]:
    """Mario's DMA animation table (located in this ROM) -> part rotations."""
    table = rom_layout(rom)["mario_anims"]
    off, _size = struct.unpack_from(">II", rom, table + 8 + 8 * index)
    a = table + off
    _flags, _yd, _st, _ls, _le, nparts = struct.unpack_from(">6h", rom, a)
    vals_o, idx_o, _ln = struct.unpack_from(">III", rom, a + 12)
    nidx = (nparts + 1) * 6
    indices = np.frombuffer(rom[a + idx_o:a + idx_o + 2 * nidx], ">u2").astype(np.int64)
    top = int(max(indices[1::2] + indices[0::2]))
    values = np.frombuffer(rom[a + vals_o:a + vals_o + 2 * top], ">i2").astype(np.int64)
    return rots_from_channels(anim_channels(values, indices, frame))


# ================================================================ the walk

def _rot_xyz(rx, ry, rz):
    from .sm64_mario import _rot_xyz as r
    return r(rx, ry, rz)


def _deg_rot(r):
    """GEO_TRANSLATE_ROTATE angles (degrees in C; s16 0x10000/360 units in the ROM handled by the caller)."""
    return _rot_xyz(*(int(x * 0x10000 / 360) for x in r))


def _case(node, pick: dict | None = None):
    kids = node["children"]
    if not kids:
        return []
    want = (pick or {}).get(str(node.get("fn")), 0)
    k = kids[want] if 0 <= want < len(kids) else kids[0]
    if _draws(k):
        return [k]
    return [next((c for c in kids if _draws(c)), k)]


def _has_part(n) -> bool:
    return any(c["kind"] == "part" or _has_part(c) for c in n.get("children", []))


def _draws(n) -> bool:
    return bool(n.get("dl")) or any(_draws(c) for c in n.get("children", []))


def walk(tree: dict, rots: list | None, *, skip_trs: bool = True, pick: dict | None = None) -> tuple[list, list]:
    """Tree -> (joints [{parent, t, M (4x4 row-vector world incl. scale), part}], draws [(layer, order, joint, M, dl)])."""
    joints, draws = [], []
    root_j = None

    def go(node, M, j):
        nonlocal root_j
        kind = node["kind"]
        kids = node["children"]
        if kind in ("held",):
            return
        if kind == "trs" and skip_trs and (any(node["t"]) or any(node["r"])) and not _has_part(node):
            return                                           # Mario's wing-cap wings (the cap switch hides them)
        if kind == "range" and node["lo"] > 0:
            return
        if kind == "switch":
            kids = _case(node, pick)
        if kind == "part":
            k = sum(1 for jt in joints if jt["part"] is not None)          # the animation's part index
            r = _rot_xyz(*rots[k]) if rots and k < len(rots) else np.eye(3)
            L = np.eye(4)
            L[:3, :3] = r
            L[3, :3] = node["t"]
            M = L @ M
            joints.append({"parent": j, "t": node["t"], "M": M, "part": k})
            j = len(joints) - 1
        elif kind == "scale":
            S = np.eye(4)
            S[:3, :3] *= node["s"]
            M = S @ M
        elif kind == "trs":
            L = np.eye(4)
            L[:3, :3] = _deg_rot(node["r"])
            L[3, :3] = node["t"]
            M = L @ M
        if node.get("dl"):
            if j is None:                                    # geometry above the first animated part: one root joint
                if root_j is None:
                    joints.append({"parent": None, "t": (0, 0, 0), "M": np.eye(4), "part": None, "name": "root"})
                    root_j = len(joints) - 1
                j = root_j
            draws.append((int(node.get("layer") or 1), len(draws), j, M, node["dl"]))
        for c in kids:
            go(c, M, j)
    go(tree, np.eye(4), None)
    return joints, draws


def run(source, draws) -> dict:
    """Run the display lists in SM64's draw order (by layer, then tree order) with one vertex cache.
    -> {verts: [(pos, normal | None, (s, t), rgba, joint, texture scale)], tris: [(material key, (i, j, k))]}."""
    verts, tris = [], []
    cache = [None] * 256
    st = {"amb": (100, 100, 100), "dif": (200, 200, 200), "geo": 0x20000, "mode": "shade", "texon": False,
          "timg": None, "tfmt": None, "tsize": None, "tscale": (0xFFFF, 0xFFFF), "env": (255, 255, 255, 255),
          "prim": (255, 255, 255, 255)}

    def key():
        tex = None
        if st["mode"] in ("tex", "modulate", "blend") and st["timg"] is not None and st["tsize"]:
            fmt, siz = st["tfmt"] or st["timg"][1:3]
            tex = (st["timg"][0], fmt, siz, *st["tsize"])
        lit = bool(st["geo"] & 0x20000)
        return (st["mode"] if tex else ("shade" if st["mode"] in ("tex", "modulate", "blend") else st["mode"]),
                tuple(st["dif"]), tuple(st["amb"]), tex, bool(st["geo"] & 0x40000) and tex is not None, lit,
                tuple(st["env"][:3]) if st["mode"] == "env" else tuple(st["prim"][:3]) if st["mode"] == "prim" else None)

    def exe(dl, j, M, depth=0):
        if depth > 32:
            return
        for op in source.ops(dl):
            o = op[0]
            if o == "vtx":
                _, sym, off, n, v0 = op
                raw = source.vertices(sym, off, n)
                lit = bool(st["geo"] & 0x20000)
                for k, v in enumerate(raw):
                    p = np.array([v[0], v[1], v[2], 1.0]) @ M
                    c = [int(x) & 0xFF for x in v[6:10]]
                    nrm = None
                    if lit:
                        n_ = np.array([((x + 128) % 256) - 128 for x in c[:3]], float) @ M[:3, :3]
                        ln = np.linalg.norm(n_)
                        nrm = n_ / ln if ln > 1e-9 else None
                    uv = (float(v[4]), float(v[5]))
                    verts.append((p[:3], nrm, uv, c, j, st["tscale"]))
                    if v0 + k < len(cache):
                        cache[v0 + k] = len(verts) - 1
            elif o == "tri":
                idx = [cache[i] if 0 <= i < len(cache) else None for i in op[1:4]]
                if None not in idx:
                    tris.append((key(), tuple(idx)))
            elif o == "call":
                exe(op[1], j, M, depth + 1)
            elif o == "jump":
                exe(op[1], j, M, depth + 1)
                return
            elif o == "end":
                return
            elif o == "lights":
                st["amb"], st["dif"] = op[1], op[2]
            elif o == "light_l":
                st["dif"] = op[1]
            elif o == "light_a":
                st["amb"] = op[1]
            elif o == "timg":
                st["timg"] = (op[1], op[2], op[3], op[4])
                st["tfmt"] = None
            elif o == "tile":
                if op[1] == 0:
                    st["tfmt"] = (op[2], op[3])
            elif o == "tsize":
                if op[1] == 0:
                    st["tsize"] = (op[2], op[3])
            elif o == "texture":
                st["texon"] = bool(op[3])
                st["tscale"] = (op[1], op[2])
            elif o == "combine":
                st["mode"] = op[1]
            elif o == "geo_set":
                st["geo"] |= op[1]
            elif o == "geo_clear":
                st["geo"] &= ~op[1]
            elif o == "env":
                st["env"] = op[1]
            elif o == "prim":
                st["prim"] = op[1]
    for _layer, _order, j, M, dl in sorted(draws, key=lambda d: (d[0], d[1])):
        exe(dl, j, M)
    return {"verts": verts, "tris": tris}


# ================================================================ model assembly

def _matcap_colour(img: np.ndarray) -> np.ndarray:
    """A texture-generated (matcap) material's base colour: the median of its lit centre disc."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    disc = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2 < 0.35 ** 2
    px = img[disc][:, :3].astype(float)
    return np.median(px, 0) if len(px) else img[..., :3].reshape(-1, 3).mean(0)


def assemble(source, joints: list, run_out: dict, *, unit: float = UNIT) -> dict:
    """Joints + run() output -> model: clean joint frames (rotation without scale, metres), per-material primitives
    with deduplicated vertices (position, smooth normal, uv, joint), materials (colour, image)."""
    J = []
    for jt in joints:
        M = jt["M"]
        R = M[:3, :3].copy()
        for r in range(3):
            n = np.linalg.norm(R[r])
            R[r] = R[r] / n if n > 1e-12 else np.eye(3)[r]
        U, _s, Vt = np.linalg.svd(R)                          # nearest rotation
        R = U @ Vt
        W = np.eye(4)
        W[:3, :3] = R
        W[3, :3] = M[3, :3] * unit
        J.append({"parent": jt["parent"], "world": W, "part": jt.get("part"), "name": jt.get("name")})
    verts = run_out["verts"]
    groups: dict = {}
    for k, idx in run_out["tris"]:
        groups.setdefault(k, []).append(idx)
    mats, prims, texcache = [], [], {}
    for k, tri_list in groups.items():
        mode, dif, amb, tex, texgen, lit, const = k
        img = None
        colour = np.array(const if const is not None else dif, float)
        if tex is not None:
            if tex not in texcache:
                texcache[tex] = source.texture(tex)
            img = texcache[tex]
            if texgen:                                        # matcap: its base colour, no texture
                colour, img = _matcap_colour(img), None
            elif mode == "blend":                             # decal over the shade colour (SM64 face / eyes)
                t = img.astype(float)
                al = t[..., 3:4] / 255.0
                img = np.concatenate([t[..., :3] * al + colour[None, None, :3] * (1 - al),
                                      np.full(al.shape, 255.0)], -1).astype(np.uint8)
            elif mode == "modulate":
                t = img.astype(float)
                img = np.concatenate([np.clip(t[..., :3] * colour[None, None, :3] / 255.0, 0, 255), t[..., 3:4]],
                                     -1).astype(np.uint8)
        vmap, P, N, UV, Jn, C = {}, [], [], [], [], []
        T = []
        for tri in tri_list:
            out = []
            for vi in tri:
                p, nrm, (s, t), c, jj, tsc = verts[vi]
                if img is not None:
                    w, h = tex[3], tex[4]
                    uv = (s * (tsc[0] + 1) / 65536.0 / 32.0 / w, t * (tsc[1] + 1) / 65536.0 / 32.0 / h)
                else:
                    uv = (0.0, 0.0)
                kk = (vi,) if nrm is None else (round(p[0], 4), round(p[1], 4), round(p[2], 4), jj,
                                                round(nrm[0], 3), round(nrm[1], 3), round(nrm[2], 3),
                                                round(uv[0], 5), round(uv[1], 5))
                if kk not in vmap:
                    vmap[kk] = len(P)
                    P.append(p * unit)
                    N.append(nrm if nrm is not None else np.zeros(3))
                    UV.append(uv)
                    Jn.append(jj)
                    C.append(c)
                out.append(vmap[kk])
            if len(set(out)) == 3:
                T.append(out)
        if not T:
            continue
        P, N = np.array(P, np.float32), np.array(N, np.float32)
        T = np.array(T, np.int64)
        if not lit or not np.abs(N).sum(1).all():            # unlit (vertex colours) or missing: smooth from faces
            N = np.where(np.abs(N).sum(1, keepdims=True) > 0, N, smooth_normals(P, T))
        base = np.append(np.clip(colour[:3] / 255.0, 0, 1), 1.0)
        if not lit and img is None and mode == "shade":      # vertex colours carry the colour
            base = np.append(np.clip(np.array(C, float)[:, :3].mean(0) / 255.0, 0, 1), 1.0)
        mats.append({"colour": base.tolist(), "image": img, "texgen": texgen, "mode": mode,
                     "name": f"m{len(mats)}" + ("_tex" if img is not None else "")})
        prims.append({"P": P, "N": N.astype(np.float32), "UV": np.array(UV, np.float32),
                      "J": np.array(Jn, np.int64), "T": T, "mat": len(mats) - 1})
    return prune({"joints": J, "prims": prims, "materials": mats})


def prune(model: dict) -> dict:
    """Drop joints the reader added (no animated part) that hold no vertex and no child joint."""
    J = model["joints"]
    used = set()
    for p in model["prims"]:
        used |= set(np.unique(p["J"]).tolist())
    parents = {jt["parent"] for jt in J}
    keep = [k for k, jt in enumerate(J) if jt.get("part") is not None or k in used or k in parents]
    if len(keep) == len(J):
        return model
    remap = {k: i for i, k in enumerate(keep)}
    model["joints"] = [dict(J[k], parent=remap.get(J[k]["parent"])) for k in keep]
    for p in model["prims"]:
        p["J"] = np.array([remap[j] for j in p["J"]], np.int64)
    return model


def smooth_normals(P: np.ndarray, T: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals, welded by position (seams between parts stay smooth)."""
    key = np.round(P / max(float(np.ptp(P)) if len(P) else 1.0, 1e-9) * 1e5).astype(np.int64)
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    acc = np.zeros((inv.max() + 1, 3))
    for c in range(3):
        np.add.at(acc, inv[T[:, c]], fn)
    n = acc[inv]
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return (n / np.where(ln > 1e-12, ln, 1)).astype(np.float32)


# ================================================================ body roles

# animated-part index -> role, per SM64 skeleton (the decomp geo order; Render96 keeps it so the game's animations play)
SKELETONS = {
    "mario": {"parts": 20, "roles": {"hip": 1, "chest": 2, "head": 3, "l_clav": 4, "l_upper": 5, "l_fore": 6,
                                     "l_hand": 7, "r_clav": 8, "r_upper": 9, "r_fore": 10, "r_hand": 11,
                                     "l_thigh": 13, "l_shin": 14, "l_foot": 15, "r_thigh": 17, "r_shin": 18,
                                     "r_foot": 19}},
    "peach": {"parts": 21, "roles": {"hip": 1, "chest": 2, "head": 3, "l_clav": 8, "l_upper": 9, "l_fore": 10,
                                     "l_hand": 11, "r_clav": 13, "r_upper": 14, "r_fore": 15, "r_hand": 16}},
    # Toad: legs 6-9 / 10-13 (pivot, thigh, shin, foot), arms 14-16 / 17-19 (shoulder, upper arm, mitten): no
    # forearm and no neck bone, so both are inserted
    "toad": {"parts": 20, "roles": {"hip": 1, "chest": 2, "head": 3, "l_thigh": 7, "l_shin": 8, "l_foot": 9,
                                    "r_thigh": 11, "r_shin": 12, "r_foot": 13, "l_clav": 14, "l_upper": 15,
                                    "l_hand": 16, "r_clav": 17, "r_upper": 18, "r_hand": 19},
             "synth": ["neck_insert", "fore_insert"]},
    # Yoshi: body 1, upper body 2, head 3 (+ jaw 4-5), arms 6-9 / 10-13, legs 14-17 / 20-23 (pivot, thigh, shin,
    # foot), tail 18-19
    "yoshi": {"parts": 24, "roles": {"hip": 1, "chest": 2, "head": 3, "l_clav": 6, "l_upper": 7, "l_fore": 8,
                                     "l_hand": 9, "r_clav": 10, "r_upper": 11, "r_fore": 12, "r_hand": 13,
                                     "l_thigh": 15, "l_shin": 16, "l_foot": 17, "r_thigh": 21, "r_shin": 22,
                                     "r_foot": 23}},
    # Bowser (the game's 44 animated parts): shell + body 0, legs 1-6 / 29-34 (pivot, thigh, knee, ankle, foot and
    # shin meshes), tail 7-9, arms 10-16 / 22-28 (shoulder, upper, elbow, wrist, hand / forearm / upper-arm meshes),
    # head 17-21; one body part, so the chest is split off it
    "bowser": {"parts": 44, "roles": {"hip": 0, "head": 17, "l_clav": 10, "l_upper": 11, "l_fore": 12, "l_hand": 13,
                                      "r_clav": 22, "r_upper": 23, "r_fore": 24, "r_hand": 25, "l_thigh": 2,
                                      "l_shin": 3, "l_foot": 4, "r_thigh": 30, "r_shin": 31, "r_foot": 32},
               "synth": ["chest_split"]},
}


def face_forward(model: dict, roles: dict[str, int]) -> float:
    """Turn the posed model about +Y (in 90 degree steps) so the toes point to +Z: an animation's first frame can
    turn the whole actor (Toad's). The feet are the cue - each foot's geometry reaches forward from its joint - so the
    side labels are fixed only afterwards (mirror_sides). -> the turn in degrees."""
    J = model["joints"]
    d = np.zeros(3)
    for f in ("l_foot", "r_foot"):
        j = roles.get(f)
        if j is None:
            continue
        own = descendants(model, j) | {j}
        pts = [p["P"][np.isin(p["J"], list(own))] for p in model["prims"]]
        pts = [x for x in pts if len(x)]
        if pts:
            d += np.concatenate(pts).mean(0) - J[j]["world"][3, :3]
    allp = np.concatenate([p["P"] for p in model["prims"]]) if model["prims"] else np.zeros((1, 3))
    if np.hypot(d[0], d[2]) < 0.02 * (float(np.ptp(allp[:, 1])) or 1.0):
        return 0.0
    turn = -round(np.degrees(np.arctan2(d[0], d[2])) / 90.0) * 90.0       # toes -> +Z
    return turn_y(model, turn)


def turn_y(model: dict, turn: float) -> float:
    """Rotate the whole model (vertices, normals, joints) by `turn` degrees about +Y."""
    J = model["joints"]
    if turn % 360 == 0:
        return 0.0
    a = np.radians(turn)
    R = np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])   # row vectors: v @ R
    for p in model["prims"]:
        p["P"] = (p["P"] @ R).astype(np.float32)
        p["N"] = (p["N"] @ R).astype(np.float32)
    for jt in J:
        W = jt["world"].copy()
        W[:3, :3] = W[:3, :3] @ R
        W[3, :3] = W[3, :3] @ R
        jt["world"] = W
    return turn


def mirror_sides(roles: dict[str, int], world: dict[int, np.ndarray]) -> dict[str, int]:
    """l_ roles on the character's left (+X when facing +Z): swap the sides when the skeleton's 'l' chain is on -X."""
    pairs = [("l_upper", "r_upper"), ("l_thigh", "r_thigh"), ("l_hand", "r_hand")]
    vote = 0
    for a, b in pairs:
        if a in roles and b in roles:
            vote += np.sign(world[roles[a]][0] - world[roles[b]][0])
    if vote >= 0:
        return dict(roles)
    out = {}
    for r, j in roles.items():
        out[("r_" + r[2:]) if r.startswith("l_") else ("l_" + r[2:]) if r.startswith("r_") else r] = j
    return out


# ================================================================ synthetic joints (never move a vertex)

def add_joint(model: dict, parent: int, pos_world: np.ndarray, name: str) -> int:
    """A joint under `parent` at a world position, with the parent's orientation."""
    W = model["joints"][parent]["world"].copy()
    W[3, :3] = pos_world
    model["joints"].append({"parent": parent, "world": W, "part": None, "name": name, "synthetic": True})
    return len(model["joints"]) - 1


def descendants(model: dict, j: int) -> set[int]:
    out, todo = set(), [j]
    while todo:
        k = todo.pop()
        for c, jt in enumerate(model["joints"]):
            if jt["parent"] == k and c not in out:
                out.add(c)
                todo.append(c)
    return out


def insert_between(model: dict, a: int, b: int, name: str, frac: float = 0.5) -> int:
    """A joint on the way from a to its descendant b (the chain a -> ... -> b keeps every vertex where it is): b's
    parent becomes the new joint, which hangs off b's old parent."""
    J = model["joints"]
    pa, pb = J[a]["world"][3, :3], J[b]["world"][3, :3]
    new = add_joint(model, J[b]["parent"], pa + (pb - pa) * frac, name)
    J[b]["parent"] = new
    return new


def split_chest(model: dict, hip: int, upper_roots: list[int], frac: float = 0.5) -> int:
    """One body part for hip and chest (Bowser): a chest joint above the hip at `frac` of the way up to the shoulders;
    the body vertices above it and the arms / head roots move onto it."""
    J = model["joints"]
    hipw = J[hip]["world"][3, :3]
    tops = [J[r]["world"][3, :3] for r in upper_roots]
    y = hipw[1] + (np.mean([t[1] for t in tops]) - hipw[1]) * frac if tops else hipw[1] + 0.1
    chest = add_joint(model, hip, np.array([hipw[0], y, hipw[2]]), "chest")
    for r in upper_roots:
        J[r]["parent"] = chest
    for p in model["prims"]:
        sel = (p["J"] == hip) & (p["P"][:, 1] > y)
        p["J"][sel] = chest
    return chest


def split_head(model: dict, neck: int) -> int:
    """SM64 heads pivot at the neck: the pivot joint becomes the neck, a new head joint at the neck (a zero-length
    pivot, the head's base) takes the head's vertices (and every joint that hung off the pivot, e.g. Peach's hair
    parts). The head joint sits at the neck, not at the head's vertical centre, so the retarget's head-height
    reference (the head joint's Y) matches native donors whose head joint is at the neck: a centre-anchored head
    joint would map the head centre onto the target's neck and sink the head into the shoulders."""
    sel = [(p, np.where(p["J"] == neck)[0]) for p in model["prims"]]
    base = model["joints"][neck]["world"][3, :3]
    head = add_joint(model, neck, np.array(base), "head")
    for p, i in sel:
        p["J"][i] = head
    for k, jt in enumerate(model["joints"][:-1]):
        if jt["parent"] == neck:
            jt["parent"] = head
    return head


def pull_clavicle(model: dict, clav: int, chest: int, frac: float = 0.45):
    """A shoulder pivot with no geometry (SM64's arm root) sits on the upper arm: move it toward the chest so the
    clavicle has length. Its children keep their world frames, so no vertex moves."""
    J = model["joints"]
    if any(np.any(p["J"] == clav) for p in model["prims"]):
        return
    a, b = J[clav]["world"][3, :3], J[chest]["world"][3, :3]
    target = a + (np.array([b[0], a[1], b[2]]) - a) * frac
    J[clav]["world"] = J[clav]["world"].copy()
    J[clav]["world"][3, :3] = target


def add_skirt_legs(model: dict, hip: int, *, gap: float = 0.32) -> dict[str, int]:
    """Peach's dress has no legs: two leg chains under the hip (thigh / shin / foot at the dress's left and right
    quarter), the skirt's vertices below the waist weighted to them, blended toward the hip near the waist and between
    the legs near the middle, so the dress stretches instead of tearing. -> {role: joint}."""
    J = model["joints"]
    hipw = J[hip]["world"][3, :3]
    allp = np.concatenate([p["P"] for p in model["prims"]])
    ground = float(allp[:, 1].min())
    below = allp[allp[:, 1] < hipw[1]]
    half = float(np.percentile(np.abs(below[:, 0] - hipw[0]), 75)) if len(below) else 0.1
    off = max(half * 0.5, 0.02)
    roles = {}
    for side, sx in (("l", 1.0), ("r", -1.0)):
        x = hipw[0] + sx * off
        th = add_joint(model, hip, np.array([x, hipw[1] - 0.05 * (hipw[1] - ground), hipw[2]]), f"{side}_thigh")
        sh = add_joint(model, th, np.array([x, ground + 0.5 * (hipw[1] - ground), hipw[2]]), f"{side}_shin")
        ft = add_joint(model, sh, np.array([x, ground + 0.06 * (hipw[1] - ground), hipw[2] + 0.02]), f"{side}_foot")
        roles.update({f"{side}_thigh": th, f"{side}_shin": sh, f"{side}_foot": ft})
    waist, knee = hipw[1], ground + 0.5 * (hipw[1] - ground)
    for p in model["prims"]:
        W = np.zeros((len(p["P"]), 4))
        Jx = np.zeros((len(p["P"]), 4), np.int64)
        Jx[:, 0] = p["J"]
        W[:, 0] = 1.0
        on_hip = p["J"] == hip
        for vi in np.where(on_hip & (p["P"][:, 1] < waist))[0]:
            y, x = p["P"][vi, 1], p["P"][vi, 0] - hipw[0]
            down = float(np.clip((waist - y) / max(waist - knee, 1e-6), 0, 1))          # 0 at the waist .. 1 at the knee
            lower = float(np.clip((knee - y) / max(knee - ground, 1e-6), 0, 1))        # 0 above the knee .. 1 at the hem
            left = float(np.clip(0.5 + x / (2 * gap * max(off, 1e-6)), 0, 1))
            leg_w = down * down * (3 - 2 * down)
            l_th, l_sh = roles["l_thigh"], roles["l_shin"]
            r_th, r_sh = roles["r_thigh"], roles["r_shin"]
            ws = {hip: 1 - leg_w}
            for jj_th, jj_sh, s in ((l_th, l_sh, left), (r_th, r_sh, 1 - left)):
                ws[jj_th] = ws.get(jj_th, 0) + leg_w * s * (1 - lower)
                ws[jj_sh] = ws.get(jj_sh, 0) + leg_w * s * lower
            top = sorted(ws.items(), key=lambda kv: -kv[1])[:4]
            tot = sum(w for _j, w in top) or 1.0
            for c, (jj, w) in enumerate(top):
                Jx[vi, c], W[vi, c] = jj, w / tot
        p["J4"], p["W4"] = Jx, W
    return roles


# ================================================================ glTF

def _quat(R: np.ndarray) -> list[float]:
    """Rotation matrix (column-vector convention) -> glTF quaternion [x, y, z, w]."""
    m = R
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return (q / np.linalg.norm(q)).tolist()


def joint_names(model: dict, roles: dict[str, int]) -> list[str]:
    role_of = {j: r for r, j in roles.items()}
    out = []
    for k, jt in enumerate(model["joints"]):
        r = role_of.get(k)
        out.append(f"j{k:02d}" + (f"_{r}" if r else (f"_{jt['name']}" if jt.get("name") else "")))
    return out


def to_glb(model: dict, roles: dict[str, int], path: Path, *, name: str = "character",
           source_info: dict | None = None, max_tex: int = 512) -> Path:
    """The model as one self-contained GLB: skinned mesh (one primitive per material, smooth NORMAL, TEXCOORD_0,
    JOINTS_0 / WEIGHTS_0), joints with gbox_role extras, PNG textures embedded, gbox_source extras (licence,
    attribution) on the asset for gbox.blender_roundtrip."""
    from PIL import Image
    blob = bytearray()
    views, accs = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        data = np.ascontiguousarray(arr).tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob += data
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = np.asarray(arr).min(0).tolist(), np.asarray(arr).max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    def add_raw(data: bytes, mime: str):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        blob += data
        return len(views) - 1

    J = model["joints"]
    names = joint_names(model, roles)
    role_of = {j: r for r, j in roles.items()}
    nodes = []
    for k, jt in enumerate(J):
        W = jt["world"]
        Lw = W if jt["parent"] is None else W @ np.linalg.inv(J[jt["parent"]]["world"])
        R = Lw[:3, :3].T                                     # row-vector -> column-vector rotation
        nd = {"name": names[k], "translation": [float(x) for x in Lw[3, :3]], "rotation": _quat(R)}
        if k in role_of:
            nd["extras"] = {"gbox_role": role_of[k]}
        nodes.append(nd)
    for k, jt in enumerate(J):
        if jt["parent"] is not None:
            nodes[jt["parent"]].setdefault("children", []).append(k)
    images, textures, materials, prims = [], [], [], []
    tex_of: dict[bytes, int] = {}
    for m in model["materials"]:
        md = {"name": m["name"], "pbrMetallicRoughness": {"baseColorFactor": [float(x) for x in m["colour"]],
                                                          "metallicFactor": 0.0, "roughnessFactor": 0.8}}
        if m["image"] is not None:
            img = np.asarray(m["image"], np.uint8)
            key = img.shape[:2] + (hash(img.tobytes()),)
            if key not in tex_of:
                im = Image.fromarray(img, "RGBA")
                if max(im.size) > max_tex:                  # HD pack textures: the library keeps <= max_tex
                    s = max_tex / max(im.size)
                    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "PNG", optimize=True)
                images.append({"bufferView": add_raw(buf.getvalue(), "image/png"), "mimeType": "image/png"})
                textures.append({"source": len(images) - 1, "sampler": 0})
                tex_of[key] = len(textures) - 1
            md["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_of[key]}
            md["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
            if np.asarray(m["image"])[..., 3].min() < 250:
                md["alphaMode"] = "MASK"
                md["alphaCutoff"] = 0.5
        materials.append(md)
    for p in model["prims"]:
        n = len(p["P"])
        if "J4" in p:
            Jt, Wt = p["J4"].astype(np.uint16), p["W4"].astype(np.float32)
        else:
            Jt = np.zeros((n, 4), np.uint16)
            Jt[:, 0] = p["J"]
            Wt = np.zeros((n, 4), np.float32)
            Wt[:, 0] = 1.0
        attrs = {"POSITION": add(p["P"].astype(np.float32), 5126, "VEC3", 34962, True),
                 "NORMAL": add(p["N"].astype(np.float32), 5126, "VEC3", 34962),
                 "TEXCOORD_0": add(p["UV"].astype(np.float32), 5126, "VEC2", 34962),
                 "JOINTS_0": add(Jt, 5123, "VEC4", 34962), "WEIGHTS_0": add(Wt, 5126, "VEC4", 34962)}
        ind = p["T"].reshape(-1).astype(np.uint32)
        prims.append({"attributes": attrs, "indices": add(ind, 5125, "SCALAR", 34963), "material": p["mat"]})
    ibm = np.zeros((len(J), 16), np.float32)
    for k, jt in enumerate(J):
        Wc = np.eye(4)
        Wc[:3, :3] = jt["world"][:3, :3].T
        Wc[:3, 3] = jt["world"][3, :3]
        ibm[k] = np.linalg.inv(Wc).T.reshape(16)             # column-major
    roots = [k for k, jt in enumerate(J) if jt["parent"] is None]
    nodes.append({"name": name, "mesh": 0, "skin": 0, "extras": {"gbox_part": "body"}})
    gl = {"asset": {"version": "2.0", "generator": "gbox sm64_decomp",
                    **({"extras": {"gbox_source": source_info}} if source_info else {})},
          "scene": 0, "scenes": [{"nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}],
          "skins": [{"joints": list(range(len(J))), "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": roots[0]}],
          "materials": materials, "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob)}]}
    if images:
        gl.update(images=images, textures=textures,
                  samplers=[{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    blob += bytes((-len(blob)) % 4)
    out = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(blob)) + \
        struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(blob)) + b"BIN\x00" + bytes(blob)
    Path(path).write_bytes(out)
    return Path(path)


# ================================================================ ROM layout + cast

def rom_layout(rom: bytes) -> dict:
    """Where this ROM keeps what the reader needs, found by scanning (US and EU builds differ):
    {loads: [(cmd, seg, start, end)], seg04, seg17, mario_anims}."""
    loads = set()
    for m in re.finditer(rb"[\x17\x18]\x0c\x00[\x04-\x17]", rom):
        o = m.start()
        if o % 4:
            continue
        s, e = struct.unpack_from(">II", rom, o + 4)
        if 0 < s < e <= len(rom) and e - s < 0x200000 and (rom[o] == 0x17 or rom[s:s + 4] == b"MIO0"):
            loads.add((rom[o], rom[o + 3], s, e))
    seg04 = next(((s, e) for c, g, s, e in loads if g == 0x04 and c == 0x18), None)
    seg17 = next(((s, e) for c, g, s, e in loads if g == 0x17 and c == 0x17), None)
    anims = None
    for m in re.finditer(rb"\x00\x00\x00\xd1\x00\x00\x00\x00", rom):
        o = m.start()
        if o % 4 == 0:
            off0 = struct.unpack_from(">I", rom, o + 8)[0]
            if off0 == 8 + 0xD1 * 8:
                anims = o
                break
    return {"loads": sorted(loads, key=lambda x: (x[1], x[2])), "seg04": seg04, "seg17": seg17, "mario_anims": anims}


_LAYOUT_CACHE: dict = {}


def _layout(rom: bytes) -> dict:
    k = (len(rom), rom[0x10:0x18])
    if k not in _LAYOUT_CACHE:
        _LAYOUT_CACHE[k] = rom_layout(rom)
    return _LAYOUT_CACHE[k]


def _banks(rom: bytes, bank_seg: int):
    """(bank start, decompressed bank, geo segment bytes) for every group bank of this segment number whose geo
    segment (0x0C for 5, 0x0D for 6) is loaded right after it in the ROM."""
    from .formats.lz import mio0_decompress
    lay = _layout(rom)
    geo_seg = 0x0C if bank_seg == 5 else 0x0D
    for c, g, s, e in lay["loads"]:
        if g != bank_seg or c != 0x18:
            continue
        geo = next((rom[s2:e2] for c2, g2, s2, e2 in lay["loads"] if g2 == geo_seg and s2 == e), None)
        if geo is not None:
            yield s, mio0_decompress(rom, s, strict=False), geo


def _anim_ok(mem: SegMem, ptr: int, parts: int) -> bool:
    try:
        _f, _y, _st, _ls, le, n = struct.unpack(">6h", mem.at(ptr, 12))
        vals, idx = struct.unpack(">II", mem.at(ptr + 12, 8))
        ind = np.frombuffer(mem.at(idx, 2 * (parts + 1) * 6), ">u2")
    except (KeyError, struct.error, ValueError):
        return False
    seg = ptr >> 24
    return le > 0 and n in (parts, parts - 1) and vals >> 24 == seg and idx >> 24 == seg and \
        len(ind) == (parts + 1) * 6


def find_actor(rom: bytes, model_id: int, bank_seg: int, table_len: int, parts: int | None = None) -> dict:
    """Locate an actor in the operator's ROM by structure (addresses differ between the US / EU / JP builds):
    LOAD_MODEL_FROM_GEO(model_id, geo) in the level scripts -> the group bank whose geo segment holds that layout
    -> the animation table of `table_len` pointers in that bank whose animations fit the layout's part count.
    -> {mem, geo, table, parts}."""
    geo_seg = 0x0C if bank_seg == 5 else 0x0D
    geos = []
    for m in re.finditer(re.escape(bytes([0x22, 0x08, 0x00, model_id])), rom):
        if m.start() % 4 == 0:
            g = struct.unpack_from(">I", rom, m.start() + 4)[0]
            if g >> 24 == geo_seg and g not in geos:
                geos.append(g)
    for _start, bank, geo_bytes in _banks(rom, bank_seg):
        mem = SegMem({bank_seg: bank, geo_seg: geo_bytes})
        for g in geos:
            if (g & 0xFFFFFF) >= len(geo_bytes):
                continue
            try:
                tree = build_tree(geo_cmds_rom(mem, g))
                joints, draws = walk(tree, None)
                for _l, _o, _j, _M, dl in draws:
                    ops_rom(mem, dl)
            except (KeyError, ValueError, struct.error, IndexError):
                continue
            n = sum(1 for jt in joints if jt.get("part") is not None)
            if parts is not None and n != parts:
                continue
            lo, hi = bank_seg << 24, (bank_seg << 24) + len(bank)
            for o in range(0, len(bank) - 4 * table_len, 4):
                ptrs = struct.unpack_from(f">{table_len}I", bank, o)
                # every entry points into the bank; nearly all fit the layout (Bowser's table holds a 1-part stub)
                if all(lo <= x < hi for x in ptrs) and _anim_ok(mem, ptrs[0], n) and \
                        sum(_anim_ok(mem, x, n) for x in ptrs) >= 0.8 * table_len:
                    return {"mem": mem, "geo": g, "table": lo + o, "parts": n}
    raise ValueError(f"model {model_id:#x}: no segment-{bank_seg} bank with its geo layout and a {table_len}-entry "
                     "animation table was found in this ROM")


def mario_mem(rom: bytes) -> SegMem:
    from .formats.lz import mio0_decompress
    lay = _layout(rom)
    if not lay["seg04"] or not lay["seg17"]:
        raise ValueError("this SM64 ROM's group0 (Mario) segment loads were not found")
    return SegMem({0x04: mio0_decompress(rom, lay["seg04"][0], strict=False),
                   0x17: rom[lay["seg17"][0]:lay["seg17"][1]]})


# name -> (model id, bank segment, animation table length, skeleton, pose animation, frame, display name); the pose
# animations are the ones whose first frame reads cleanly in replacement readiness (Mario 197 = standing idle, Toad
# 1 = arms out, Bowser 8 = arms spread T pose; facing +Z by roles and by feet)
ROM_CAST = {
    "mario": (0x01, 4, 0, "mario", 197, 0, "Mario"),
    "peach": (0xDE, 5, 12, "peach", 0, 0, "Princess Peach"),
    "toad": (0xDD, 6, 8, "toad", 1, 0, "Toad"),
    "yoshi": (0x55, 5, 3, "yoshi", 0, 0, "Yoshi"),
    "bowser": (0x64, 6, 27, "bowser", 8, 0, "Bowser"),
}
MARIO_GEO = 0x17002DD4
# (character, pose animation) -> degrees about +Y that bring the posed actor to face +Z, where the animation's root
# rotation turns it (checked on renders: Toad's animation 1 has him facing away); other poses: the feet decide
POSE_TURN = {("toad", 1): 180.0}


def rom_pose(rom: bytes, who: str, anim: int | None = None, frame: int | None = None) -> tuple:
    """-> (SegMem, geo address, part rotations) for a ROM_CAST character."""
    mid, seg, tlen, _skel, a_idx, a_frame, _name = ROM_CAST[who]
    anim = a_idx if anim is None else anim
    frame = a_frame if frame is None else frame
    if who == "mario":
        return mario_mem(rom), MARIO_GEO, mario_rom_anim(rom, anim, frame)
    act = find_actor(rom, mid, seg, tlen, SKELETONS[ROM_CAST[who][3]].get("parts"))
    return act["mem"], act["geo"], rom_anim(act["mem"], act["table"], anim, frame, act["parts"])


def rom_character(rom: bytes, who: str, *, anim: int | None = None, frame: int | None = None) -> tuple[dict, list]:
    """One SM64 character from the ROM -> (model, joints raw) ready for finish()."""
    mem, geo, rots = rom_pose(rom, who, anim, frame)
    src = RomSource(mem)
    tree = build_tree(src.geo(geo))
    joints, draws = walk(tree, rots)
    return assemble(src, joints, run(src, draws)), joints


def pack_character(actor_dir: Path, who: str, *, rots: list | None = None, geo: str | None = None,
                   anim: str | int | None = None, frame: int = 0) -> tuple[dict, list]:
    """One character of a decomp-format pack (Render96 ...) -> (model, joints raw). rots: the pose (from the ROM's own
    animation when the pack has none); anim: the pack's own animation name (Bowser's)."""
    cs = CSource(Path(actor_dir))
    src = PackSource(cs)
    name = geo or next((g for g in cs.geo if g == f"{Path(actor_dir).name}_geo"), None) or list(cs.geo)[-1]
    if isinstance(anim, int):                                # an index into the pack's own animation table
        table = next(iter(cs.anim_tables.values()), [])
        anim = table[anim] if anim < len(table) else None
    if anim:
        rots = c_anim(cs, anim, frame)
    tree = build_tree(src.geo(name))
    joints, draws = walk(tree, rots)
    return assemble(src, joints, run(src, draws)), joints


def finish(model: dict, skeleton: str, *, synth: bool = True, turn: float | None = None) -> tuple[dict, dict[str, int]]:
    """Map the body roles (by animated-part index), turn the model to face +Z (the feet decide, or `turn` degrees),
    fix the sides, add the bones the game skeleton lacks."""
    spec = SKELETONS.get(skeleton) or {"roles": {}}
    part_to_joint = {jt["part"]: k for k, jt in enumerate(model["joints"]) if jt.get("part") is not None}
    roles = {r: part_to_joint[p] for r, p in spec["roles"].items() if p in part_to_joint}
    model["turn"] = face_forward(model, roles) if turn is None else turn_y(model, turn)
    world = {k: jt["world"][3, :3] for k, jt in enumerate(model["joints"])}
    roles = mirror_sides(roles, world)
    todo = spec.get("synth") or []
    if synth and "chest_split" in todo and "hip" in roles and "chest" not in roles:
        J = model["joints"]
        roots = []
        for r in ("l_clav", "r_clav", "neck", "head", "l_upper", "r_upper"):
            k = roles.get(r)
            while k is not None and J[k]["parent"] is not None and J[k]["parent"] != roles["hip"]:
                k = J[k]["parent"]
            if k is not None and J[k]["parent"] == roles["hip"] and k not in roots:
                roots.append(k)
        roles["chest"] = split_chest(model, roles["hip"], roots)
    if synth and "neck_insert" in todo and "neck" not in roles and {"chest", "head"} <= roles.keys():
        roles["neck"] = insert_between(model, roles["chest"], roles["head"], "neck")
    if synth and "head" in roles and "neck" not in roles:
        neck = roles["head"]
        roles["neck"] = neck
        roles["head"] = split_head(model, neck)
    if synth and "fore_insert" in todo:
        for side in ("l", "r"):
            if f"{side}_fore" not in roles and {f"{side}_upper", f"{side}_hand"} <= roles.keys():
                roles[f"{side}_fore"] = insert_between(model, roles[f"{side}_upper"], roles[f"{side}_hand"],
                                                       f"{side}_fore")
    if synth:
        for side in ("l", "r"):
            c = roles.get(f"{side}_clav")
            if c is not None and roles.get("chest") is not None:
                pull_clavicle(model, c, roles["chest"])
    if synth and "hip" in roles and "l_thigh" not in roles and skeleton == "peach":
        roles.update(add_skirt_legs(model, roles["hip"]))
    ground(model)
    heel_feet(model, roles)
    return model, roles


def heel_feet(model: dict, roles: dict[str, int]) -> None:
    """Foot pivots behind the soles (an ankle, not a toe): SM64 shoe parts (Toad's) and Peach's skirt feet can pivot
    in front of the lowest points, which reads as a character facing backwards. Only the joint frame moves (the
    vertices keep their bind positions)."""
    feet = [roles[f] for f in ("l_foot", "r_foot") if f in roles]
    if not feet or not model["prims"]:
        return
    P = np.concatenate([p["P"] for p in model["prims"]])
    H = float(np.ptp(P[:, 1])) or 1.0
    low = P[P[:, 1] < P[:, 1].min() + 0.06 * H]
    J = model["joints"]
    fz = np.mean([J[f]["world"][3, 2] for f in feet])
    if len(low) and low[:, 2].mean() - fz < 0.015 * H:
        for f in feet:
            J[f]["world"] = J[f]["world"].copy()
            J[f]["world"][3, 2] = low[:, 2].mean() - 0.03 * H


def ground(model: dict) -> dict:
    """Stand the model on y = 0 (the lowest vertex), centred on x / z over the hip-root joint."""
    allp = np.concatenate([p["P"] for p in model["prims"]]) if model["prims"] else np.zeros((1, 3))
    d = np.array([0.0, -float(allp[:, 1].min()), 0.0])
    for p in model["prims"]:
        p["P"] = (p["P"] + d).astype(np.float32)
    for jt in model["joints"]:
        jt["world"] = jt["world"].copy()
        jt["world"][3, :3] += d
    return model


def roles_by_name(model: dict, roles: dict[str, int]) -> dict[str, str]:
    """{role: joint index} -> {role: joint node name} (the names to_glb writes)."""
    names = joint_names(model, roles)
    return {r: names[j] for r, j in roles.items()}


# ================================================================ donors (ROM and HD pack)

# HD pack character -> (skeleton, the ROM_CAST character whose animation poses it, the pack's own animation index)
PACK_CAST = {"mario": ("mario", "mario", None, "Mario"), "luigi": ("mario", "mario", None, "Luigi"),
             "wario": ("mario", "mario", None, "Wario"), "peach": ("peach", "peach", None, "Princess Peach"),
             "toad": ("toad", "toad", None, "Toad"), "yoshi": ("yoshi", "yoshi", None, "Yoshi"),
             "bowser": ("bowser", None, 8, "Bowser")}
RENDER96 = {"pack": "Render96 ModelPack", "url": "https://github.com/Render96/ModelPack",
            "branch": "models_vanilla", "commit": "f4f438447748782b7c824cee903594706a3941e2",
            "licence": "No licence file in the repository or its releases (all rights reserved by the authors); "
                       "a free fan-made HD model pack published for use with Super Mario 64 PC ports. Used here "
                       "only locally, for the operator's own mods; never committed or redistributed.",
            "attribution": "Render96 team (github.com/Render96, ModelPack by DorfDork and the Render96 modellers); "
                           "Super Mario 64 characters (c) Nintendo"}


def build_rom_donor(rom: bytes, who: str, out: Path, *, game: dict | None = None) -> dict:
    """A ROM character as a donor GLB -> {path, roles (by joint name), stats, pose}."""
    model, _ = rom_character(rom, who)
    model, roles = finish(model, ROM_CAST[who][3], turn=POSE_TURN.get((who, ROM_CAST[who][4])))
    info = {"pack": "Super Mario 64 (operator's ROM)", "reader": "gbox.sm64_decomp", "reader_version": READER_VERSION,
            "licence": "extracted from the operator's own copy, local use only", "character": who,
            "donor_group": "mario", "donor_quality": "rom", "pose": f"SM64 animation {ROM_CAST[who][4]} frame 0",
            "name": f"{ROM_CAST[who][6]} (Super Mario 64)", "aliases": [f"SM64 {ROM_CAST[who][6]}"],
            "game_title": (game or {}).get("title") or "Super Mario 64 (USA)", "platform": "n64",
            **({"game_id": game["game_id"]} if game and game.get("game_id") else {})}
    p = to_glb(model, roles, Path(out), name=who, source_info=info)
    return {"path": p, "roles": roles_by_name(model, roles), "stats": stats(model), "info": info}


def build_pack_donor(actor_dir: Path, who: str, out: Path, *, rom: bytes | None = None,
                     pack: dict | None = None) -> dict:
    """A decomp-format pack character (Render96) as a donor GLB, posed with the ROM's own animation (or the pack's
    own, Bowser) -> {path, roles, stats, info}."""
    skel, rom_who, own_anim, name = PACK_CAST[who]
    rots, turn = None, None
    if own_anim is None:
        if rom is None:
            raise ValueError(f"{who}: the pose comes from the game's animation: pass the SM64 ROM")
        _mem, _geo, rots = rom_pose(rom, rom_who)
        # same skeleton, same pose: the game's own model (its feet) decides which way the pose turns the actor
        turn = POSE_TURN.get((rom_who, ROM_CAST[rom_who][4]))
        if turn is None:
            rom_model, _ = rom_character(rom, rom_who)
            turn = finish(rom_model, ROM_CAST[rom_who][3])[0]["turn"]
    model, _ = pack_character(Path(actor_dir), who, rots=rots, anim=own_anim)
    model, roles = finish(model, skel, turn=turn)
    info = {**(pack or RENDER96), "reader": "gbox.sm64_decomp", "reader_version": READER_VERSION, "character": who,
            "donor_group": "mario", "donor_quality": "hd", "name": f"{name} (HD, Render96)",
            "aliases": [f"{name} HD", f"Render96 {name}"],
            "pose": (f"Render96 animation {own_anim} frame 0" if own_anim is not None else
                     f"SM64 animation {ROM_CAST[rom_who][4]} frame 0 (the operator's ROM)"),
            "game_title": f"{(pack or RENDER96)['pack']} (Super Mario 64 HD models)"}
    p = to_glb(model, roles, Path(out), name=who, source_info=info)
    return {"path": p, "roles": roles_by_name(model, roles), "stats": stats(model), "info": info}


# ---------------------------------------------------------------- characters.DEDICATED (the `sm64` reader)

def roster() -> list[dict]:
    """The sm64 reader's roster beyond the 20-joint `mario` entry (gbox.sm64_mario, kept for the SM64 writer):
    rigged donors with all 18 body roles."""
    return [{"key": f"decomp:{w}", "slug": f"sm64_{w}", "name": f"{ROM_CAST[w][6]} (Super Mario 64)",
             "aliases": [f"SM64 {ROM_CAST[w][6]}", f"Super Mario 64 {ROM_CAST[w][6]}"], "kind": "character"}
            for w in ROM_CAST]


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED run() for a decomp:<who> roster entry."""
    from . import characters as C, n64_rom
    who = e["key"].split(":", 1)[1]
    rom = n64_rom.read(C._rom(ctx, game))
    r = build_rom_donor(rom, who, Path(work) / f"sm64_{who}.glb", game=game)
    return {"files": [r["path"]], "tool": "gbox.sm64_decomp", "roles": r["roles"],
            "source_files": [f"ROM: LOAD_MODEL_FROM_GEO {ROM_CAST[who][0]:#04x} + its group bank ({r['info']['pose']})"],
            "notes": (f"SM64 decomp-layout reader: {r['stats']['joints']} joints, {r['stats']['triangles']} triangles, "
                      "smooth vertex normals, one-cache skinning; 18 body roles"),
            "extra": {"sm64_decomp_reader": READER_VERSION, "character": who, "donor_group": "mario",
                      "donor_quality": "rom", **({"native_player": True} if who == "mario" else {})}}


def stats(model: dict) -> dict:
    return {"joints": len(model["joints"]), "triangles": int(sum(len(p["T"]) for p in model["prims"])),
            "vertices": int(sum(len(p["P"]) for p in model["prims"])), "materials": len(model["materials"]),
            "textures": sum(m["image"] is not None for m in model["materials"])}


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rom")
    r.add_argument("rom")
    r.add_argument("out")
    r.add_argument("--only", default=",".join(ROM_CAST))
    k = sub.add_parser("pack")
    k.add_argument("actors", help="the pack's actors folder (Render96/actors)")
    k.add_argument("out")
    k.add_argument("--rom", required=True, help="the SM64 ROM (poses come from the game's own animations)")
    k.add_argument("--only", default=",".join(PACK_CAST))
    a = ap.parse_args(argv)
    from . import n64_rom
    rom = n64_rom.read(a.rom)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for who in a.only.split(","):
        if a.cmd == "rom":
            res = build_rom_donor(rom, who, out / f"sm64_{who}.glb")
        else:
            res = build_pack_donor(Path(a.actors) / who, who, out / f"{who}_hd.glb", rom=rom)
        print(json.dumps({"character": who, "glb": str(res["path"]), **res["stats"], "roles": len(res["roles"])}))


if __name__ == "__main__":
    _main()
