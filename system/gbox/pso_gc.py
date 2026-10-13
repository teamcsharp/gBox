"""Phantasy Star Online Episode I & II (Plus) (GameCube) -> player classes and enemies as rigged, textured GLBs.

Owned source: GPOE8P (USA) disc 0 rev 2 "PHANTASY STAR ONLINE EPISODE I&II", catalog 436e0bb84d5337d1 (HyperSpin GCZ,
read in place through gbox.gcz). The game executable is PsoV3.dol (main.dol is only the AppSwitcher bootstrap). Formats
(docs/pso_gc.md has the offsets and the evidence):

* Disc: GameCube FST, 3510 files. Area data is packed in GSL archives (gsl_<area>.gsl): a table of 0x30-byte entries
  {char name[0x20], u32 BE offset in 0x800 units, u32 BE size, 8 zero bytes}, the files 0x800-aligned behind it.
  Enemy packs live only there (gsl_forest01.gsl holds bm_ene_re8_b_beast.bml, the Booma family, ...).
* BML: the Dreamcast pack layout (gbox.pso_player.bml_files) with big-endian header fields; entries PRS-compressed,
  a body .nj may carry a PRS'd GVM texture archive behind it.
* NJ: Ninja chunk models (NJTL + POF0 + NJCM + POF0). Chunk / POF0 sizes stay little-endian; the payload is big-endian
  with two swap units: node / model structs and VERTEX chunks are u32-swapped (the second vertex-chunk word is
  u32 count << 16 | base), POLYGON chunks are u16-swapped (strips, tiny and material chunks). gbox.ninja.NJ(be=True).
* Textures: GVM archives (GVMH: u32 LE header size, u16 BE flags, u16 BE count, entries) of GVR textures (optional
  GBIX, then GVRT: u32 LE size, byte 0x0A = palette format << 4 | data flags, byte 0x0B = GX format, u16 BE width,
  height; then the GX texel blocks). The player banks pl<X>tex.afs are AFS (little-endian table) of GBIX+GVRT entries.

Player classes: letters A..L (HUmar .. FOmar; M..Z are placeholder slots). Every class body pl<X>bdy00.nj is the
Dreamcast 64-node tree (gbox.pso_player.PLAYER_PARENTS) with weighted vertices; the head (pl<X>hedNN.nj), hair
(pl<X>haiNN.nj) and cap (pl<X>capNN.nj) are separate models drawn at the head node 56. Enemies: every bm_ene_*.bml body
on its own node tree (its .njm motions in the same pack drive it), body roles inferred from the tree
(gbox.pso_enemy.infer_roles) or the fixed Booma map.

characters.DEDICATED row "pso_gc" (roster(), extract_run()); writer gbox.pso_gc_swap.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import numpy as np

from . import gcdisc, ninja, uap

GAME_ID = "GPOE8P"
GAME_IDS = {"436e0bb84d5337d1": "Phantasy Star Online Episode I & II Plus (USA)",
            "7a3692dc0cbc9b82": "Phantasy Star Online Episode I & II Plus",
            "6b55435e3c565370": "Phantasy Star Online Episode I & II (USA)",
            "5b5792e27be59f59": "Return To Ragol V1.0.3"}
READER_VERSION = 1
CLASSES = ["HUmar", "HUnewearl", "HUcast", "RAmar", "RAcast", "RAcaseal", "FOmarl", "FOnewm", "FOnewearl",
           "HUcaseal", "RAmarl", "FOmar"]
LETTERS = "ABCDEFGHIJKL"
CLASS_LETTER = {c: LETTERS[i] for i, c in enumerate(CLASSES)}
HEAD_NODE = 56                                       # the head mesh node: heads, hair and caps ride it
HEAD_MOUNT = 59                                      # its hidden child (flags 0x1d): the frame they are modelled in


def letter(cls: str) -> str:
    """A class name (HUcast) or letter (c) -> the upper-case letter."""
    if cls in CLASS_LETTER:
        return CLASS_LETTER[cls]
    low = {k.lower(): v for k, v in CLASS_LETTER.items()}
    if cls.lower() in low:
        return low[cls.lower()]
    if len(cls) == 1 and cls.isalpha():                  # A..L the classes; M..Z placeholder slots on the disc
        return cls.upper()
    raise ValueError(f"unknown PSO class {cls!r} ({', '.join(CLASSES)})")


# ------------------------------------------------------------------------------------------------ disc and archives

def open_disc(path) -> gcdisc.GCDisc:
    """An owned .iso / .gcm / .gcz (read in place); refuses another game."""
    disc = gcdisc.GCDisc(path)
    if disc.game_id[:4] != GAME_ID[:4]:
        raise ValueError(f"{Path(path).name}: not Phantasy Star Online Ep I&II ({GAME_ID}), got {disc.game_id}")
    return disc


def gsl_entries(data: bytes) -> list[tuple[str, int, int]]:
    """[(name, byte offset, size)] of a GSL archive, in table order."""
    out, i = [], 0
    while (i + 1) * 0x30 <= len(data):
        name = data[i * 0x30:i * 0x30 + 0x20].split(b"\0")[0]
        if not name:
            break
        off, size = struct.unpack_from(">II", data, i * 0x30 + 0x20)
        if off * 0x800 + size > len(data):
            raise ValueError(f"GSL entry {name!r} runs past the archive ({off * 0x800 + size} > {len(data)})")
        out.append((name.decode("latin-1"), off * 0x800, size))
        i += 1
    return out


def gsl_files(data: bytes) -> dict[str, bytes]:
    return {n: data[o:o + s] for n, o, s in gsl_entries(data)}


def gsl_build(data: bytes, replace: dict[str, bytes]) -> bytes:
    """The archive with entries {name: new bytes} swapped in; every file stays in table order, 0x800-aligned, behind
    a table area as large as the original's (an unchanged archive comes back byte-identical)."""
    ents = gsl_entries(data)
    start = min((o for _n, o, _s in ents), default=0x800)
    head = bytearray(data[:start])
    body = bytearray()
    order = sorted(range(len(ents)), key=lambda k: ents[k][1])     # files in their original disc order
    for k in order:
        n, o, s = ents[k]
        blob = replace.get(n, data[o:o + s])
        pos = start + len(body)
        struct.pack_into(">II", head, k * 0x30 + 0x20, pos // 0x800, len(blob))
        body += blob + bytes((-len(blob)) % 0x800)
    tail = bytes(len(data) - (start + len(body))) if not replace and len(data) > start + len(body) else b""
    return bytes(head + body) + tail


def bml_files(data: bytes) -> list[dict]:
    from .pso_player import bml_files as _bf
    return _bf(data, ">")


def bml_build(data: bytes, replace: dict[str, bytes], textures: dict[str, bytes] | None = None) -> bytes:
    from .pso_player import bml_build as _bb
    return _bb(data, replace, textures, ">")


def bml_entry(data: bytes, name: str) -> tuple[bytes, bytes | None]:
    """(decompressed file, decompressed texture archive or None) of one BML entry."""
    for e in bml_files(data):
        if e["name"].split(b"\0")[0].decode("latin-1").lower() == name.lower():
            raw = ninja.prs_decompress(e["raw"]) if e["fields"][0] != e["fields"][2] else e["raw"]
            tex = None
            if e["tex"] is not None:
                tex = ninja.prs_decompress(e["tex"]) if e["fields"][3] != e["fields"][4] else e["tex"]
            return raw, tex
    raise KeyError(f"no entry {name} in the pack")


def afs(data: bytes) -> list[bytes]:
    from .pso_player import afs as _afs
    return _afs(data)


# ------------------------------------------------------------------------------------------------ textures (GVM / GVR)

def gvr_header(chunk: bytes) -> dict:
    """{gbix, gvrt (offset of 'GVRT'), size, pal_fmt, flags, fmt, w, h, data (offset of the texels)}."""
    q = chunk.find(b"GVRT")
    if q < 0 or q + 16 > len(chunk):
        raise ValueError("no GVRT chunk")
    gbix = struct.unpack_from(">I", chunk, chunk.find(b"GBIX") + 8)[0] if b"GBIX" in chunk[:q] else None
    size = struct.unpack_from("<I", chunk, q + 4)[0]
    w, h = struct.unpack_from(">HH", chunk, q + 12)
    return {"gbix": gbix, "gvrt": q, "size": size, "pal_fmt": chunk[q + 10] >> 4, "flags": chunk[q + 10] & 0xF,
            "fmt": chunk[q + 11], "w": w, "h": h, "data": q + 16}


def gvr_decode(chunk: bytes) -> np.ndarray:
    """A GVR texture -> RGBA uint8 (h, w, 4). GX formats I4..RGBA8, CMPR, and CI4 / CI8 with an internal palette."""
    from .melee_models import decode_texture
    hd = gvr_header(chunk)
    d = chunk[hd["data"]:]
    tlut, n = None, 0
    if hd["fmt"] in (8, 9):
        n = 16 if hd["fmt"] == 8 else 256
        if hd["flags"] & 0x8:                                  # internal palette ahead of the texels
            tlut, d = d[:2 * n], d[2 * n:]
        else:
            tlut = bytes(2 * n)
    return decode_texture(d, hd["fmt"], hd["w"], hd["h"], tlut, {0: 0, 1: 1, 2: 2}.get(hd["pal_fmt"], 2), n or 256)


def gvm_entries(data: bytes) -> list[tuple[str, bytes]]:
    """[(name, GVR chunk (GBIX + GVRT))] of a GVM archive, in archive order."""
    if data[:4] != b"GVMH":
        raise ValueError("not a GVM archive")
    names = gvm_list(data)["names"]
    o = 8 + struct.unpack_from("<I", data, 4)[0]
    out = []
    for name in names:
        start = o
        if data[o:o + 4] == b"GBIX":
            o += 8 + struct.unpack_from("<I", data, o + 4)[0]
        if data[o:o + 4] != b"GVRT":
            raise ValueError(f"GVM entry {name}: no GVRT at {o:#x}")
        o += 8 + struct.unpack_from("<I", data, o + 4)[0]
        out.append((name, data[start:o]))
    return out


def gvm_list(data: bytes) -> dict:
    """Parse just the GVMH header: return {header_size, flags, count, names[]}.

    Header: "GVMH", u32 LE header size, u16 BE flags, u16 BE count, then per texture
    {u16 BE id, char name[28] (flags & 8), u16 format (& 4), u16 dims (& 2), u32 gbix (& 1)}."""
    if len(data) < 12 or data[:4] != b"GVMH":
        raise ValueError("not a GVM file")
    size = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from(">H", data, 0xA)[0]
    flags = (data[8] | data[9]) & 0x0F       # entry-field bits; taken from either byte of the u16 flag word
    end = min(len(data), 8 + size)
    stride = 2 + (28 if flags & 8 else 0) + (2 if flags & 4 else 0) + (2 if flags & 2 else 0) + (4 if flags & 1 else 0)
    if 12 + count * stride > end:
        raise ValueError(f"{count} GVM entries of {stride} bytes overrun the {size}-byte header")
    names = []
    for i in range(count):
        off = 12 + i * stride + 2
        names.append(data[off:off + 28].split(b"\0")[0].decode("latin-1", "replace")
                     if flags & 8 else f"tex{i}")
    return {"header_size": size, "flags": flags, "count": count, "names": names}


def png_bytes(rgba: np.ndarray) -> bytes:
    a = np.ascontiguousarray(np.asarray(rgba, np.uint8))
    return ninja.png(a.shape[1], a.shape[0], a.tobytes())


# ------------------------------------------------------------------------------------------------ models

def read_nj(data: bytes) -> ninja.NJ:
    """A big-endian NJ file (NJTL / POF0 ahead of the NJCM allowed)."""
    return ninja.NJ(data, be=True)


def njcm_payload(data: bytes) -> tuple[bytes, bytes, bytes]:
    """(everything before NJCM, the NJCM payload, everything after it). Chunk sizes are little-endian on GC too."""
    o = data.find(b"NJCM")
    if o < 0:
        raise ValueError("no NJCM chunk")
    size = struct.unpack_from("<I", data, o + 4)[0]
    return data[:o], data[o + 8:o + 8 + size], data[o + 8 + size:]


def tree(data: bytes) -> list[dict]:
    """The NJCM node tree (gbox.ninja.tree_nodes layout) of a big-endian NJ file."""
    return ninja.tree_nodes(njcm_payload(data)[1], 0, ">")


def player_body_nj(disc: gcdisc.GCDisc, cls: str) -> bytes:
    """Return the raw bytes of pl<X>bdy00.nj for a class name/letter."""
    return disc.read(f"pl{letter(cls)}bdy00.nj")


def player_head_nj(disc: gcdisc.GCDisc, cls: str, head: int = 0) -> bytes:
    return disc.read(f"pl{letter(cls)}hed{head:02d}.nj")


def read_body(disc: gcdisc.GCDisc, cls: str) -> ninja.NJ:
    """Parse the class body NJCM model (big-endian node structs)."""
    return read_nj(player_body_nj(disc, cls))


def export_body(disc_path, cls: str, out_dir) -> Path:
    """The class as a GLB (body + default head / hair, textured; export_player) -> path to the written .glb."""
    return export_player(open_disc(disc_path), cls, out_dir)[0]


# ------------------------------------------------------------------------------------------------ PsoV3.dol tables

class Dol:
    """Big-endian reads from a GameCube DOL by virtual address."""

    def __init__(self, data: bytes):
        self.data = data
        offs, addrs, sizes = (struct.unpack_from(">18I", data, o) for o in (0, 0x48, 0x90))
        self.secs = [(offs[i], addrs[i], sizes[i], i < 7) for i in range(18) if sizes[i]]

    def off(self, addr: int) -> int | None:
        for o, a, s, _t in self.secs:
            if a <= addr < a + s:
                return o + addr - a
        return None

    def u32(self, addr: int) -> int:
        o = self.off(addr)
        if o is None:
            raise ValueError(f"{addr:#x} is outside the DOL")
        return struct.unpack_from(">I", self.data, o)[0]

    def cstr(self, addr: int) -> str:
        o = self.off(addr)
        if o is None:
            raise ValueError(f"{addr:#x} is outside the DOL")
        return self.data[o:self.data.index(b"\0", o)].decode("latin-1")

    def find_strings(self, s: str) -> list[int]:
        """Addresses of a NUL-terminated string that starts on a 4-byte boundary (how the compiler places them)."""
        pat, out = s.encode("latin-1") + b"\0", []
        o = self.data.find(pat)
        while o >= 0:
            for so, a, sz, _t in self.secs:
                if so <= o < so + sz and (o - so) % 4 == 0:
                    out.append(a + o - so)
            o = self.data.find(pat, o + 1)
        return out

    def data_refs(self, value: int) -> list[int]:
        """Addresses of 4-byte-aligned data words equal to value (pointer tables)."""
        pat, out = struct.pack(">I", value), []
        for so, a, sz, text in self.secs:
            if text:
                continue
            o = self.data.find(pat, so, so + sz)
            while o >= 0:
                if (o - so) % 4 == 0:
                    out.append(a + o - so)
                o = self.data.find(pat, o + 1, so + sz)
        return out

    def texlist(self, rec: int) -> list[str]:
        """An NJS_TEXLIST {char **names, u32 count} -> the texture names."""
        names, n = self.u32(rec), self.u32(rec + 4)
        if not 0 < n < 64:
            raise ValueError(f"texlist {rec:#x}: {n} names")
        return [self.cstr(self.u32(names + 4 * i)) for i in range(n)]

    def ptr_array(self, addr: int, n: int) -> list[int]:
        return [self.u32(addr + 4 * i) for i in range(n)] if addr else []


def class_tables(dol: bytes) -> dict[str, dict]:
    """Per class letter, from PsoV3.dol (found through the strings, no fixed addresses):
      afs    the name of every pl<X>tex.afs entry, in AFS order (a 16-byte record {u32 id, u32 count,
             char *"PL<X>TEX.AFS", char **names} per class)
      body / heads[i] / hairs[i]   the NJS_TEXLIST of the body, of head model i and of hair style i (shared by
             pl<X>hai<i>.nj and pl<X>cap<i>.nj); the names are the default variant (first costume / skin / colour)
      head_files / hair_files / cap_files   the model file of each slot ('' = none)
    The class descriptor (0x2C bytes) is {u32 x4 counts, hair files, cap files, head files, char *body file,
    hair texlists, head texlists, body texlist}, found by the pointer to its body file name at +0x1C."""
    D = Dol(dol)
    out: dict[str, dict] = {}
    for L in LETTERS:
        rec = next((r for a in D.find_strings(f"PL{L}TEX.AFS") for r in D.data_refs(a) if 0 < D.u32(r - 4) < 4096),
                   None)

        def is_desc(r):                                    # the body texlist pointer at +0x28 must parse
            try:
                return bool(D.texlist(D.u32(r + 0xC)))
            except (ValueError, UnicodeDecodeError):
                return False
        desc = next((r - 0x1C for a in D.find_strings(f"pl{L}bdy00.nj") for r in D.data_refs(a) if is_desc(r)), None)
        if rec is None or desc is None:
            continue
        count, names = D.u32(rec - 4), D.u32(rec + 4)
        w = [D.u32(desc + 4 * k) for k in range(11)]
        hair_files_p, cap_files_p, head_files_p, _body, hair_tl_p, head_tl_p, body_tl = w[4:11]
        nhair = 10 if hair_files_p else 0
        nhead = 1 if hair_files_p else 5                   # humans: one head model; androids: five
        cstr = lambda p: D.cstr(p) if p else ""
        tl = lambda p: D.texlist(p) if p else []
        out[L] = {"afs": [D.cstr(D.u32(names + 4 * i)) for i in range(count)], "afs_file": f"pl{L}tex.afs",
                  "body": D.texlist(body_tl),
                  "head_files": [cstr(p) for p in D.ptr_array(head_files_p, nhead)],
                  "heads": [tl(p) for p in D.ptr_array(head_tl_p, nhead)],
                  "hair_files": [cstr(p) for p in D.ptr_array(hair_files_p, nhair)],
                  "cap_files": [cstr(p) for p in D.ptr_array(cap_files_p, nhair)],
                  "hairs": [tl(p) for p in D.ptr_array(hair_tl_p, nhair)],
                  "counts": w[:4]}
    return out


_TABLES: dict[str, dict] = {}


def tables(disc: gcdisc.GCDisc) -> dict[str, dict]:
    """class_tables of this disc's PsoV3.dol (cached by the DOL's sha256)."""
    dol = disc.read("PsoV3.dol")
    key = hashlib.sha256(dol).hexdigest()
    if key not in _TABLES:
        _TABLES[key] = class_tables(dol)
    return _TABLES[key]


# ------------------------------------------------------------------------------------------------ player classes

# Body roles: the Dreamcast tree's map (gbox.pso_player.PLAYER_ROLES, 15 mesh nodes) plus the three joints between:
# neck = 55 (chest -> neck -> head mesh 56), clavicles = 26 / 39 (chest -> shoulder joint -> upper-arm chain).
NECK, L_CLAV, R_CLAV = 55, 26, 39


def class_roles(body_file: bytes, cls: str) -> dict[str, int]:
    """The 18 body roles (node indices) of a class body, checked against its own tree: the 15 mesh roles with
    gbox.pso_player.check_roles (tree, sides, heights, drawn vertices), neck / clavicles by their place in the tree."""
    from .formats.rig import is_below
    from .pso_enemy import vertex_owners
    from .pso_player import PLAYER_ROLES, check_roles
    L = letter(cls)
    nodes = tree(body_file)
    nj = read_nj(body_file)
    parents = [-1 if nd["parent"] is None else nd["parent"] for nd in nodes]
    world = [[b["m"][k][3] for k in range(3)] for b in nj.bones]
    bad = check_roles(parents, world, PLAYER_ROLES, vertex_owners(nj))
    roles = dict(PLAYER_ROLES) | {"neck": NECK, "l_clav": L_CLAV, "r_clav": R_CLAV}
    if not bad:
        for a, b in (("chest", "neck"), ("neck", "head"), ("chest", "l_clav"), ("l_clav", "l_upper"),
                     ("chest", "r_clav"), ("r_clav", "r_upper")):
            if not is_below(parents, roles[a], roles[b]):
                bad.append(f"{b} (node {roles[b]}) isn't below {a} (node {roles[a]})")
        if not world[L_CLAV][0] > 0 > world[R_CLAV][0]:
            bad.append("clavicles are mirrored")
    if bad:
        raise ValueError(f"pl{L}bdy00.nj ({CLASSES[LETTERS.index(L)]}): " + "; ".join(bad))
    return roles


def joint_roles(roles: dict[str, int]) -> dict[str, str]:
    """Node-index roles -> the joint names of the exported model (gbox.ninja.to_manifest names nodes nodeNNN)."""
    return {r: f"node{j:03d}" for r, j in roles.items()}


def _mat_point(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3)]


def _mat_dir(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] for i in range(3)]


def attach(body: ninja.NJ, part: ninja.NJ, mount: int, tex_base: int, joint: int | None = None) -> int:
    """Put a part model's triangles into the body (texture ids tex_base + id), moved by the mount node's bind matrix
    and weighted to `joint` (default the mount; heads / hair / caps ride the head). -> triangles added."""
    joint = mount if joint is None else joint
    mw = body.bones[mount]["m"]
    added = 0
    for tex, tris in part.tris.items():
        out = body.tris.setdefault(tex_base + tex, [])
        for tri in tris:
            c2 = []
            for vi, t, *snap in tri:
                v = snap[0] if snap and snap[0] else part.vbuf.get(vi)
                if v is None:
                    break
                c2.append((vi, t, {"pos": _mat_point(mw, v["pos"]), "nrm": _mat_dir(mw, v["nrm"]) if v["nrm"] else None,
                                   "joints": [(joint, 1.0)]}))
            else:
                out.append(tuple(c2))
                added += 1
    return added


def player_parts(disc: gcdisc.GCDisc, cls: str, head: int = 0, hair: int = 0) -> list[dict]:
    """The models one default-looking character of the class is drawn from:
    [{file, texlist (names), tex_base, kind}] - body first (tex ids 0..), then head (100..), hair (200..), cap (300..)."""
    L = letter(cls)
    t = tables(disc).get(L)
    if t is None:
        raise ValueError(f"PsoV3.dol has no texture tables for class {L}")
    parts = [{"file": f"pl{L}bdy00.nj", "texlist": t["body"], "tex_base": 0, "kind": "body"}]
    hf = t["head_files"][head] if head < len(t["head_files"]) else ""
    if hf and hf in disc.files:
        parts.append({"file": hf, "texlist": t["heads"][head] if head < len(t["heads"]) else [], "tex_base": 100,
                      "kind": "head"})
    if t["hair_files"]:
        tl = t["hairs"][hair] if hair < len(t["hairs"]) else []
        for kind, files, base in (("hair", t["hair_files"], 200), ("cap", t["cap_files"], 300)):
            f = files[hair] if hair < len(files) else ""
            if f and f in disc.files:
                parts.append({"file": f, "texlist": tl, "tex_base": base, "kind": kind})
    return parts


def build_player(disc: gcdisc.GCDisc, cls: str, out_dir: Path | None = None, head: int = 0, hair: int = 0,
                 name: str | None = None, mount: int = HEAD_MOUNT) -> tuple[uap.Manifest, dict]:
    """-> (uap.Manifest of body + head + hair (+ cap) with the default textures written as PNGs under
    out_dir/textures, info {parts, textures {slot: afs entry name}, missing})."""
    L = letter(cls)
    parts = player_parts(disc, L, head, hair)
    body = read_nj(disc.read(parts[0]["file"]))
    for p in parts[1:]:
        attach(body, read_nj(disc.read(p["file"])), mount, p["tex_base"], HEAD_NODE)
    t = tables(disc)[L]
    ents = afs(disc.read(t["afs_file"]))
    index = {n.lower(): i for i, n in enumerate(t["afs"])}
    tex_files: list[str | None] = [None] * 400
    used, missing = {}, []
    for p in parts:
        for k, nm in enumerate(p["texlist"]):
            slot = p["tex_base"] + k
            if slot not in body.tris:
                continue
            i = index.get(nm.lower())
            if i is None or i >= len(ents):
                missing.append(nm)
                continue
            used[slot] = nm
            if out_dir is not None:
                rel = f"textures/{nm}.png"
                (Path(out_dir) / "textures").mkdir(parents=True, exist_ok=True)
                (Path(out_dir) / rel).write_bytes(png_bytes(gvr_decode(ents[i])))
                tex_files[slot] = rel
    name = name or f"pso_gc_{CLASSES[LETTERS.index(L)].lower()}"
    m = ninja.to_manifest(body, name, {"game": "Phantasy Star Online Episode I & II Plus (USA) (GC)", "game_id": GAME_ID,
                                       "class": L, "head": head, "hair": hair,
                                       "files": [p["file"] for p in parts] + [t["afs_file"]],
                                       "extraction_method": "gbox.pso_gc"}, tex_files)
    m.unit_scale_m = 0.1
    return m, {"parts": [p["file"] for p in parts], "textures": used, "missing": missing}


def export_player(disc: gcdisc.GCDisc, cls: str, out_dir, head: int = 0, hair: int = 0,
                  mount: int = HEAD_MOUNT) -> tuple[Path, dict]:
    """-> (path of the written .glb, info)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m, info = build_player(disc, cls, out, head, hair, mount=mount)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{m.name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb, info


# ------------------------------------------------------------------------------------------------ enemies

# key -> (pack, body entry, name). The pack names are the game's own; which body is which enemy is read off the area
# archives that load the pack (gsl_forest01/02: the Booma family, gsl_cave*: the sharks, ...), the entry names and the
# body sizes. Names marked (probable) are not confirmed in game yet. Packs ending _a are the Ultimate-mode variants.
ENEMIES = {
    "booma": ("bm_ene_re8_b_beast.bml", "re8_b_beast_wola_body.nj", "Booma"),
    "gobooma": ("bm_ene_re8_b_beast.bml", "re8_b_rdbeast_wola_body.nj", "Gobooma"),
    "gigobooma": ("bm_ene_re8_b_beast.bml", "re8_b_srdbeast_wola_body.nj", "Gigobooma"),
    "rag_rappy": ("bm_ene_lappy.bml", "re3_b_lappy_base.nj", "Rag Rappy"),
    "al_rappy": ("bm_ene_lappy.bml", "re3_s_lappy_base.nj", "Al Rappy"),
    "mothmant": ("bm_ene_bm3_fly.bml", "bm3_fly_body.nj", "Mothmant"),
    "monest": ("bm_ene_bm3_fly.bml", "bm3_s_nest.nj", "Monest"),
    "savage_wolf": ("bm_ene_bm5_wolf.bml", "bm5_s_kem_body.nj", "Savage Wolf"),
    "barbarous_wolf": ("bm_ene_bm5_wolf.bml", "bm5_s_keml_body.nj", "Barbarous Wolf"),
    "hildebear": ("bm_ene_bm2_moja.bml", "bm2w_s_moj_body.nj", "Hildebear (probable)"),
    "hildeblue": ("bm_ene_bm2_moja.bml", "bm2f_s_moj_body.nj", "Hildeblue (probable)"),
    "hildebear_c": ("bm_ene_bm2_moja.bml", "bm2c_s_moj_body.nj", "Hildebear variant (bm2c, probable)"),
    "evil_shark": ("bm_ene_bm1_shark.bml", "bm1_s_wala_body.nj", "Evil Shark (probable)"),
    "pal_shark": ("bm_ene_bm1_shark.bml", "bm1f_s_wala_body.nj", "Pal Shark (probable)"),
    "guil_shark": ("bm_ene_bm1_shark.bml", "bm1tl_s_wala_body.nj", "Guil Shark (probable)"),
    "grass_assassin": ("bm_ene_grass.bml", "re1_b_grass_base.nj", "Grass Assassin"),
    "poison_lily": ("bm_ene_re2_flower.bml", "re2_b_flower_root.nj", "Poison Lily"),
    "nano_dragon": ("bm_ene_nanodrago.bml", "bm6_s_drc_body.nj", "Nano Dragon"),
    "canadine": ("bm_ene_me1_mb.bml", "me1_y_mb.nj", "Canadine (probable)"),
    "sinow_beat": ("bm_ene_me3_shinowa.bml", "me3_y_me3.nj", "Sinow Beat"),
    "dubchic": ("bm_ene_dubchik.bml", "me2_y_me2.nj", "Dubchic"),
    "gilchic": ("bm_ene_dubchik.bml", "me2_y_me2_2.nj", "Gilchic"),
    "garanz": ("bm_ene_gyaranzo.bml", "me4_y_me4.nj", "Garanz"),
    "delsaber": ("bm_ene_df1_saver.bml", "df1_s_kil_body.nj", "Delsaber"),
    "chaos_bringer": ("bm_ene_df2_bringer.bml", "bm8_s_kb_body.nj", "Chaos Bringer"),
    "dimenian": ("bm_ene_df3_dimedian.bml", "df3_s_wala_body.nj", "Dimenian"),
    "la_dimenian": ("bm_ene_df3_dimedian.bml", "df3_sl_wala_body.nj", "La Dimenian"),
    "so_dimenian": ("bm_ene_df3_dimedian.bml", "df3_ssl_wala_body.nj", "So Dimenian"),
    "chaos_sorcerer": ("bm_ene_re4_sorcerer.bml", "re4_b_sorcer_body.nj", "Chaos Sorcerer"),
    "dark_belra": ("bm_ene_re7_berura.bml", "re7_b_bell_body.nj", "Dark Belra"),
    "bulclaw": ("bm_ene_balclaw.bml", "re6_b_bal_body.nj", "Bulclaw (probable)"),
    "claw": ("bm_ene_balclaw.bml", "re6_b_claw_body.nj", "Claw (probable)"),
    "dark_gunner": ("bm_ene_darkgunner.bml", "re5_b_gunner_body.nj", "Dark Gunner"),
    "merillia": ("bm_ene_re8_merill_lia.bml", "re8_b_beast_wola_body.nj", "Merillia"),
    "meriltas": ("bm_ene_re8_merill_lia.bml", "re8_b_srbeast_wola_body.nj", "Meriltas"),
    "ul_gibbon": ("bm_ene_bm5_gibon_u.bml", "gibon.nj", "Ul Gibbon"),
    "zol_gibbon": ("bm_ene_bm5_gibon_u.bml", "gibonb_gibon.nj", "Zol Gibbon"),
    "mericarol": ("bm_ene_bm9_s_mericarol.bml", "bm9_s_meri_body.nj", "Mericarol"),
    "gi_gue": ("bm_ene_gi_gue.bml", "gi_gue_all.nj", "Gi Gue"),
    "gibbles": ("bm_ene_gibbles.bml", "gibb_body.nj", "Gibbles"),
    "gee": ("bm_ene_me1_gee.bml", "me1_y_mb.nj", "Gee"),
    "sinow_zoa": ("bm_ene_me3_shinowa_zoa.bml", "me3_y_me3.nj", "Sinow Zoa (probable)"),
    "deldepth": ("bm_ene_del_depth.bml", "swim_body.nj", "Deldepth"),
    "delbiter": ("bm_ene_biter_body.bml", "biter_body.nj", "Delbiter"),
    "morfos": ("bm_ene_morfos.bml", "kabe_body.nj", "Morfos"),
    "recobox": ("bm_ene_recobox.bml", "me7_all.nj", "Recobox"),
    "dolmolm": ("bm_ene_abgc01_wola_body.bml", "abgc01_wola_body.nj", "Dolmolm (probable)"),
    "dolmdarl": ("bm_ene_abgc01_wola_body.bml", "abgc01l_wola_body.nj", "Dolmdarl (probable)"),
    "del_lily": ("bm_ene_dkflower.bml", "dkflower_root.nj", "Del Lily (probable)"),
    "ill_gill": ("bm_ene_ill_gill.bml", "darkand_body.nj", "Ill Gill"),
}
# The Booma family's tree is the Dreamcast enemy tree (gbox.pso_enemy.BOOMA_ROLES), checked by enemy_roles.
FIXED_ROLES = {"booma": "BOOMA_ROLES", "gobooma": "BOOMA_ROLES", "gigobooma": "GIGOBOOMA_ROLES"}

_PACK_HOME: dict[str, dict[str, list[str]]] = {}


def pack_homes(disc: gcdisc.GCDisc) -> dict[str, list[str]]:
    """{pack name: [the GSL archives that carry it, or '' for a loose disc file]} (cached per disc)."""
    key = getattr(disc.f, "name", str(id(disc)))
    if key not in _PACK_HOME:
        homes: dict[str, list[str]] = {}
        for g in sorted(n for n in disc.files if n.lower().endswith(".gsl")):
            for n, _o, _s in gsl_entries(disc.read(g)):
                homes.setdefault(n, []).append(g)
        for n in disc.files:
            if "/" not in n and n.lower().endswith(".bml"):
                homes.setdefault(n, []).append("")
        _PACK_HOME[key] = homes
    return _PACK_HOME[key]


def read_pack(disc: gcdisc.GCDisc, pack: str) -> bytes:
    """A BML pack's bytes from its first GSL archive (or the loose file)."""
    homes = pack_homes(disc).get(pack)
    if not homes:
        raise KeyError(f"{pack} is not on this disc")
    g = homes[0]
    return disc.read(pack) if g == "" else gsl_files(disc.read(g))[pack]


def enemy_raw(disc: gcdisc.GCDisc, key: str) -> tuple[bytes, bytes | None]:
    """(the body .nj with its NJTL, its decompressed GVM or None)."""
    pack, entry, _name = ENEMIES[key]
    return bml_entry(read_pack(disc, pack), entry)


def enemy_roles(key: str, raw: bytes) -> tuple[dict, dict, list[int]]:
    """(roles {role: node}, collapse {marker node: mesh node}, head nodes) of an enemy body: the fixed Booma map when
    it fits this tree (gbox.formats.rig.check_role_map), else inferred from the tree (gbox.pso_enemy.infer_roles)."""
    from . import pso_enemy
    from .formats.rig import ROLE_CHAINS, check_role_map
    nj = read_nj(raw)
    nodes = tree(raw)
    if key in FIXED_ROLES:
        roles = dict(getattr(pso_enemy, FIXED_ROLES[key]))
        parents = [-1 if nd["parent"] is None else nd["parent"] for nd in nodes]
        world = [[b["m"][k][3] for k in range(3)] for b in nj.bones]
        drawn = pso_enemy.vertex_owners(nj)
        chk = {r: j for r, j in roles.items() if j not in pso_enemy.BOOMA_COLLAPSE}
        if not check_role_map(parents, world, chk, drawn, [c for c in ROLE_CHAINS if all(r in chk for r in c)]):
            return roles, dict(pso_enemy.BOOMA_COLLAPSE), [roles["head"]]
    roles, collapse, heads = pso_enemy.infer_roles(nj, nodes)
    seen, clean = set(), {}
    for r in ("hip", "chest", "head") + tuple(k for k in roles if k not in ("hip", "chest", "head")):
        if r in roles and roles[r] not in seen:            # one node, one role (the inference can reuse the chest
            clean[r] = roles[r]                            # as a thigh on odd trees)
            seen.add(roles[r])
    return clean, collapse, heads


def build_enemy(disc: gcdisc.GCDisc, key: str, out_dir: Path | None = None) -> tuple[uap.Manifest, dict]:
    """-> (uap.Manifest of the enemy body on its own node tree with its GVM textures as PNGs, info {roles, ...})."""
    pack, entry, name = ENEMIES[key]
    raw, gvm = enemy_raw(disc, key)
    nj = read_nj(raw)
    names = ninja.njtl(raw, be=True)
    tex_by_name = dict(gvm_entries(gvm)) if gvm else {}
    if not gvm or any(n not in tex_by_name for n in names):   # a body without its own archive (Barbarous Wolf)
        bml = read_pack(disc, pack)                            # draws with its pack mates' textures
        for e in bml_files(bml):
            nm = e["name"].split(b"\0")[0].decode("latin-1")
            if e["tex"] is not None and nm.lower() != entry.lower():
                mate_raw, mate_gvm = bml_entry(bml, nm)
                for tn, chunk in gvm_entries(mate_gvm):
                    tex_by_name.setdefault(tn, chunk)
                if not names:                                  # no NJTL of its own: the mate's texture list
                    names = ninja.njtl(mate_raw, be=True)
    tex_files: list[str | None] = [None] * max(1, len(names))
    for k, nm in enumerate(names):
        chunk = tex_by_name.get(nm)
        if chunk is None and gvm:                          # no NJTL match: the k-th archive entry
            ents = gvm_entries(gvm)
            chunk = ents[k][1] if k < len(ents) else None
        if chunk is None or out_dir is None:
            continue
        rel = f"textures/{nm or f'tex{k}'}.png"
        (Path(out_dir) / "textures").mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / rel).write_bytes(png_bytes(gvr_decode(chunk)))
        tex_files[k] = rel
    roles, collapse, head_nodes = enemy_roles(key, raw)
    m = ninja.to_manifest(nj, f"pso_gc_{key}", {"game": "Phantasy Star Online Episode I & II Plus (USA) (GC)",
                                               "game_id": GAME_ID, "enemy": name, "files": [f"{pack}:{entry}"],
                                               "extraction_method": "gbox.pso_gc"}, tex_files)
    m.unit_scale_m = 0.1
    return m, {"roles": roles, "collapse": collapse, "head_nodes": head_nodes, "pack": pack, "entry": entry,
               "homes": pack_homes(disc).get(pack, []), "textures": names}


def export_enemy(disc: gcdisc.GCDisc, key: str, out_dir) -> tuple[Path, dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m, info = build_enemy(disc, key, out)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{m.name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb, info


def enemy_joint_roles(info: dict) -> dict[str, str]:
    """An exported enemy's roles as joint names: mesh nodes only (collapsed markers / virtual joints left out)."""
    return {r: f"node{j:03d}" for r, j in info["roles"].items() if j not in (info.get("collapse") or {})}


# ------------------------------------------------------------------------------------------------ characters.DEDICATED

def slug_of(key: str) -> str:
    return f"pso_gc_{key.lower()}"


def roster() -> list[dict]:
    """The twelve player classes (kind character: op=collect gathers them) and the enemies (kind enemy: listed for the
    cast menu, ripped by op=extract, writer slot enemy:<key>)."""
    out = [{"key": L, "slug": slug_of(CLASSES[i]), "name": f"{CLASSES[i]} (PSO Ep I&II)", "kind": "character",
            "aliases": [CLASSES[i], f"PSO {CLASSES[i]}", f"PSO GC {CLASSES[i]}", f"Phantasy Star Online {CLASSES[i]}"],
            "slot": f"class:{CLASSES[i].lower()}"} for i, L in enumerate(LETTERS)]
    for k, (pack, entry, name) in ENEMIES.items():
        plain = name.split(" (")[0]
        out.append({"key": f"enemy:{k}", "slug": slug_of(k), "name": f"{plain} (PSO Ep I&II)", "kind": "enemy",
                    "aliases": [plain, f"PSO {plain}", f"{plain} (PSO GC enemy)"], "slot": f"enemy:{k}",
                    "file": pack, "entry": entry})
    return out


def disc_path(ctx, game) -> Path:
    """The owned image of this catalog game (.gcz / .iso read in place)."""
    from . import characters as C
    rom = C._rom(ctx, game)
    if rom.suffix.lower() in (".gcz", ".iso", ".gcm"):
        return rom
    return C._gc_iso(ctx, game)


def extract_run(ctx, game, e, work):
    """characters.DEDICATED run for one roster entry (characters.extract_dedicated)."""
    work = Path(work)
    disc = open_disc(disc_path(ctx, game))
    key = e["key"]
    if key.startswith("enemy:"):
        k = key.split(":", 1)[1]
        ctx.progress(30, f"Reading {ENEMIES[k][0]}:{ENEMIES[k][1]}")
        glb, info = export_enemy(disc, k, work)
        roles = enemy_joint_roles(info)
        return {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.pso_gc (enemy BML / GVM)",
                "source_files": [f"{g or '(disc)'}:{info['pack']}:{info['entry']}" for g in info["homes"][:1]],
                "roles": roles,
                "extra": {"pso_gc_reader": READER_VERSION, "pso_gc_slot": f"enemy:{k}", "pso_gc_pack": info["pack"]},
                "notes": f"{ENEMIES[k][2]}: the body on its own {len(read_nj(enemy_raw(disc, k)[0]).bones)}-node tree "
                         f"(its .njm motions in {info['pack']} drive it); roles {'fixed (Booma map)' if k in FIXED_ROLES else 'inferred from the tree'}"
                         f", {18 - len(roles)} of the 18 body roles absent (not a humanoid limb)."}
    L = letter(key)
    ctx.progress(30, f"Reading pl{L}bdy00.nj + head / hair and pl{L}tex.afs")
    glb, info = export_player(disc, L, work)
    roles = joint_roles(class_roles(disc.read(f"pl{L}bdy00.nj"), L))
    return {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.pso_gc (player body + parts)",
            "source_files": info["parts"] + [f"pl{L}tex.afs", "PsoV3.dol (texture lists)"], "roles": roles,
            "extra": {"pso_gc_reader": READER_VERSION, "pso_gc_class": L, "pso_gc_slot": f"class:{CLASSES[LETTERS.index(L)].lower()}",
                      "pso_gc_textures": info["textures"]},
            "notes": f"{CLASSES[LETTERS.index(L)]}: the 64-node weighted body with head / hair at node 59, the default "
                     f"costume, face and hair textures named by the game's own texture lists in PsoV3.dol; 18 body roles."}


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="PSO Ep I&II (GC): player classes / enemies -> rigged GLBs")
    ap.add_argument("image", help="owned .gcz / .iso")
    ap.add_argument("out")
    ap.add_argument("keys", nargs="*", help="class letters / names, or enemy keys (default: every class)")
    ap.add_argument("--preview", action="store_true", help="render a preview PNG next to each GLB")
    a = ap.parse_args(argv)
    disc = open_disc(a.image)
    out = Path(a.out)
    for k in a.keys or list(LETTERS):
        if k in ENEMIES:
            glb, info = export_enemy(disc, k, out / k)
            info = {"roles": enemy_joint_roles(info), "pack": info["pack"]}
        else:
            glb, info = export_player(disc, k, out / letter(k))
            info["roles"] = joint_roles(class_roles(disc.read(f"pl{letter(k)}bdy00.nj"), k))
        if a.preview:
            from . import characters as C
            C.render_preview(glb, glb.with_suffix(".png"))
        print(json.dumps({"key": k, "glb": str(glb), **info}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
