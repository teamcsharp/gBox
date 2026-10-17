"""Sonic Adventure (Dreamcast) analysis: map the basic-model trees in 1ST_READ.BIN to their characters through the
executable's own code, and walk a tree's NJS_MODEL meshsets into triangles.

Evidence chain, all read from the exact USA 1ST_READ.BIN (sha256 45bc5d3c...367a, base 0x8C010000):

* Each character has a PVM entry table ``{char *name, NJS_TEXLIST *list}`` (``SONIC`` -> 0x8C1C6C94, 28 textures).
* SH-4 code loads that texlist with a PC-relative ``mov.l @(disp,PC),Rn`` (``0xDnnn``). The function holding the
  load (``njSetTexture`` before the draw) also loads -- itself or through the draw function it calls -- an
  NJS_OBJECT node of exactly one tree, or a table whose words point at that tree (PL_ACTION/NJS_ACTION records).
* The tree's material texture ids all fit in that texlist.

``character_map(exe)`` reproduces that chain and returns the root plus the function/xref addresses that prove it.

    python -m gbox.sa1_analysis 1ST_READ.BIN
"""
from __future__ import annotations

import json
import math
import struct
import sys

from .sa1_inventory import KEY, MESHSET_SIZE, Exe, scan_trees

CODE_END = 0x150000                 # code + rodata precede the model data in 1ST_READ.BIN
PRO, RTS = 0x4F22, 0x000B           # sts.l pr,@-r15 / rts
TEXLIST_NAMES = {"sonic": "SONIC", "tails": "MILES", "knuckles": "KNUCKLES", "amy": "AMY", "big": "BIG",
                 "e102": "E102", "eggman": "EGGMAN"}


class Code:
    """PC-relative literal loads and rough function bounds of SH-4 code in an executable image."""

    def __init__(self, ex: Exe, code_end: int = CODE_END):
        self.ex, self.end = ex, min(code_end, len(ex.d))
        self.loads: dict[int, list[int]] = {}
        for off in range(0, self.end, 2):
            op = struct.unpack_from("<H", ex.d, off)[0]
            if op >> 12 == 0xD:
                pc = ex.key + off
                lit = (pc & ~3) + 4 + (op & 0xFF) * 4
                if ex.ok(lit):
                    self.loads.setdefault(ex.u("I", lit)[0], []).append(pc)

    def h(self, p: int) -> int:
        return struct.unpack_from("<H", self.ex.d, p - self.ex.key)[0]

    def function(self, pc: int) -> tuple[int, int]:
        """(start, rts) around pc: back to the ``sts.l pr`` prologue and its register pushes, forward to rts."""
        p = pc & ~1
        while p > self.ex.key and self.h(p) != PRO:
            p -= 2
        while p - 2 >= self.ex.key and (self.h(p - 2) & 0xFF0F == 0x2F06 or self.h(p - 2) & 0xFF00 == 0x7F00
                                        or self.h(p - 2) & 0xFF0F == 0xFF0B):
            p -= 2                  # mov.l Rm,@-r15 / add #-n,r15 / fmov.s FRm,@-r15
        e = pc & ~1
        while e < self.ex.key + self.end and self.h(e) != RTS:
            e += 2
        return p, e

    def literals(self, f: tuple[int, int]) -> list[tuple[int, int]]:
        out = []
        for p in range(f[0], f[1] + 4, 2):
            op = self.h(p)
            if op >> 12 == 0xD:
                lit = (p & ~3) + 4 + (op & 0xFF) * 4
                if self.ex.ok(lit):
                    out.append((p, self.ex.u("I", lit)[0]))
        return out


def pvm_texlists(ex: Exe, names=TEXLIST_NAMES.values()) -> dict[str, dict]:
    """PVM entry rows {char *name, NJS_TEXLIST *list}: name -> {entry, texlist, count}."""
    d, out = ex.d, {}
    words = struct.unpack_from("<%dI" % (len(d) // 4), d)
    holders: dict[int, list[int]] = {}
    for i, w in enumerate(words):
        if ex.key <= w < ex.key + len(d):
            holders.setdefault(w, []).append(ex.key + 4 * i)
    for name in names:
        pat = name.encode() + b"\0"
        i = d.find(pat)
        while i >= 0 and name not in out:
            if i == 0 or d[i - 1] == 0:
                for q in holders.get(ex.key + i, []):
                    if not ex.ok(q + 8):
                        continue
                    t = ex.u("I", q + 4)[0]
                    if ex.ok(t, 8):
                        tp, n = ex.u("II", t)
                        if ex.ok(tp) and 0 < n < 512:
                            out[name] = {"entry": q, "texlist": t, "count": n}
                            break
            i = d.find(pat, i + 1)
    return out


def _reaches(ex: Exe, lit: int, roots: dict[int, int], span: int = 0x1000) -> int | None:
    """Root reached from a table at lit: a word == root, or a word -> NJS_ACTION whose object is the root."""
    if not ex.ok(lit):
        return None
    for q in range(lit, min(lit + span, ex.key + len(ex.d) - 8), 4):
        w = ex.u("I", q)[0]
        if w in roots:
            return w
        if ex.ok(w, 8) and ex.u("I", w)[0] in roots:
            return ex.u("I", w)[0]
    return None


def character_map(ex: Exe, trees: list[dict] | None = None, min_nodes: int = 60) -> dict[str, dict]:
    """Map each character texlist to the player-sized tree its code draws, with the proving xrefs."""
    trees = trees if trees is not None else scan_trees(ex.d, ex.key)
    big = {int(t["addr"], 16): t for t in trees if t["nodes"] >= min_nodes}
    owner: dict[int, int] = {}                       # node/model address -> root
    for r in big:
        for n in ex.tree(r):
            owner[n["addr"]] = r
            if n["model"]:
                owner[n["model"]] = r
    roots = {r: r for r in big}
    code = Code(ex)
    tex = pvm_texlists(ex)

    def hit(lit):
        if lit in owner:
            return owner[lit], "node"
        r = _reaches(ex, lit, roots) if 0x8C150000 <= lit < ex.key + len(ex.d) else None
        return (r, "table") if r else (None, None)

    out = {}
    for slug, name in TEXLIST_NAMES.items():
        if name not in tex:
            continue
        t = tex[name]
        ev = []
        for site in code.loads.get(t["texlist"], []):
            f = code.function(site)
            lits = code.literals(f)
            for p, lit in lits:
                r, how = hit(lit)
                if r:
                    ev.append({"texlist_load": site, "function": f[0], "load": p, "value": lit, "via": how, "root": r})
            if not ev:                                 # one call down: njSetTexture then the draw routine
                for p, lit in lits:
                    if not (ex.key <= lit < ex.key + code.end) or lit & 1:
                        continue
                    if not any(code.h(lit + k) in (PRO, 0x2FE6) for k in (0, 2)):
                        continue
                    g = code.function(lit + 0x10 if code.h(lit) != PRO else lit)
                    for q, m in code.literals(g):
                        r, how = hit(m)
                        if r:
                            ev.append({"texlist_load": site, "function": f[0], "calls": lit, "load": q,
                                       "value": m, "via": how, "root": r})
                            break
            if ev:
                break
        if not ev:
            out[slug] = {"texlist": t["texlist"], "textures": t["count"], "root": None, "evidence": []}
            continue
        votes: dict[int, int] = {}
        for e in ev:
            votes[e["root"]] = votes.get(e["root"], 0) + 1
        region = [r for r in big if abs(r - t["texlist"]) < 0x60000]
        # the body is the tree with the most action-table references among this character's trees
        fam = sorted({*votes, *[r for r in region if _max_tex(ex, r) < t["count"]]})
        body = max(fam, key=lambda r: (_refs(ex, r), -r))
        out[slug] = {"texlist": t["texlist"], "textures": t["count"], "root": body,
                     "variants": [r for r in fam if r != body], "nodes": big[body]["nodes"],
                     "max_texture_id": _max_tex(ex, body), "evidence": ev[:4]}
    return out


def _max_tex(ex: Exe, root: int) -> int:
    return max((x for n in ex.tree(root) if n["model"] for x in ex.model(n["model"])["textures"]), default=-1)


def _refs(ex: Exe, root: int) -> int:
    return ex.d.count(struct.pack("<I", root))


# ------------------------------------------------------------------ basic-model walker

def _mat(o: tuple) -> list[list[float]]:
    flags, pos, ang, scl = o
    bams = [a * math.pi / 0x8000 for a in ang]
    def rx(a): c, s = math.cos(a), math.sin(a); return [[1, 0, 0], [0, c, -s], [0, s, c]]
    def ry(a): c, s = math.cos(a), math.sin(a); return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    def rz(a): c, s = math.cos(a), math.sin(a); return [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    mul = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    if flags & 2:
        r = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    elif flags & 0x20:                                  # NJD_EVAL_ZXY_ANG
        r = mul(mul(ry(bams[1]), rx(bams[0])), rz(bams[2]))
    else:
        r = mul(mul(rz(bams[2]), ry(bams[1])), rx(bams[0]))
    s = [1, 1, 1] if flags & 4 else scl
    t = [0, 0, 0] if flags & 1 else pos
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)]


def _chain(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) + (a[i][3] if j == 3 else 0) for j in range(4)]
            for i in range(3)]


def model_tris(ex: Exe, model: int) -> tuple[list[tuple], list[tuple[int, int, int]]]:
    """Local vertices and triangles of one basic NJS_MODEL (tris, quads, n-gons and strips)."""
    pts, _, n, msets, _, nms, _ = ex.u("IIiIIHH", model)
    verts = [ex.u("3f", pts + 12 * i) for i in range(n)]
    tris = []
    for m in range(nms):
        tm, nmesh, meshes = ex.u("HHI", msets + m * MESHSET_SIZE)
        kind, p = tm >> 14, meshes
        for _ in range(nmesh):
            if kind in (0, 1):
                k = 3 + kind
                idx = ex.u(f"{k}H", p); p += 2 * k
                tris.append(idx[:3])
                if k == 4:
                    tris.append((idx[1], idx[3], idx[2]))
                continue
            head = ex.u("H", p)[0]; p += 2
            cnt, flip = head & 0x3FFF, bool(head & 0x8000)
            idx = ex.u(f"{cnt}H", p); p += 2 * cnt
            if kind == 2:
                tris += [(idx[0], idx[i], idx[i + 1]) for i in range(1, cnt - 1)]
            else:
                for i in range(cnt - 2):
                    a, b, c = idx[i:i + 3]
                    tris.append((b, a, c) if (i % 2) ^ flip else (a, b, c))
    tris = [t for t in tris if max(t) < n and len(set(t)) == 3]
    return verts, tris


def tree_mesh(ex: Exe, root: int) -> dict:
    """Bind-pose world vertices and triangles for a whole tree, with each node's parent index."""
    nodes = ex.tree(root)
    mats, V, F, parts = [], [], [], []
    for i, nd in enumerate(nodes):
        p = nd["addr"]
        o = (ex.u("I", p)[0], ex.u("3f", p + 8), ex.u("3i", p + 0x14), ex.u("3f", p + 0x20))
        m = _mat(o)
        if nd["parent"] >= 0:
            m = _chain(mats[nd["parent"]], m)
        mats.append(m)
        if nd["model"]:
            verts, tris = model_tris(ex, nd["model"])
            base = len(V)
            V += [tuple(sum(m[r][c] * v[c] for c in range(3)) + m[r][3] for r in range(3)) for v in verts]
            F += [(a + base, b + base, c + base) for a, b, c in tris]
            parts.append({"node": i, "verts": len(verts), "tris": len(tris)})
    return {"vertices": V, "triangles": F, "parents": [n["parent"] for n in nodes], "parts": parts}


def to_obj(mesh: dict) -> str:
    lines = ["v %.5f %.5f %.5f" % v for v in mesh["vertices"]]
    lines += ["f %d %d %d" % (a + 1, b + 1, c + 1) for a, b, c in mesh["triangles"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("exe")
    ap.add_argument("--obj", help="write <slug>.obj bind-pose meshes into this directory")
    a = ap.parse_args(argv)
    ex = Exe(open(a.exe, "rb").read())
    cmap = character_map(ex)
    hx = lambda v: (f"0x{v:08X}" if isinstance(v, int) and v >= KEY else v if not isinstance(v, (dict, list))
                    else {k: hx(x) for k, x in v.items()} if isinstance(v, dict) else [hx(x) for x in v])
    print(json.dumps(hx(cmap), indent=1))
    if a.obj:
        from pathlib import Path
        Path(a.obj).mkdir(parents=True, exist_ok=True)
        for slug, c in cmap.items():
            if c["root"]:
                (Path(a.obj) / f"{slug}.obj").write_text(to_obj(tree_mesh(ex, c["root"])))


if __name__ == "__main__":
    sys.exit(main())
