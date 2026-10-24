"""Star Fox 64 (USA Rev A) F3DEX display-list walker and Arwing mesh exporter.

Opcode table pinned from the decomp build: Makefile ``GBI_DEFINES := -DF3DEX_GBI``
(F3DEX 1.x, *not* F3DEX2), so include/PR/gbi.h selects the ``#else`` branch:
DMA cmds G_MTX=1 G_MOVEMEM=3 G_VTX=4 G_DL=6; immediates G_IMMFIRST=-65 (0xBF):
TRI1=0xBF CULLDL=0xBE POPMTX=0xBD MOVEWORD=0xBC TEXTURE=0xBB SETOTHERMODE_H=0xBA
SETOTHERMODE_L=0xB9 ENDDL=0xB8 SETGEOMETRYMODE=0xB7 CLEARGEOMETRYMODE=0xB6
LINE3D=0xB5 RDPHALF_1=0xB4 TRI2=0xB1 BRANCH_Z=0xB0.
G_VTX packing (gSPVertex): w0 = cmd<<24 | (v0*2)<<16 | (n<<10 | (16n-1)).
Triangle indices are stored *2 (vertex-buffer byte index / 8 in F3DEX1).
"""

import math
import struct

from gbox import sf64_analysis as an

G_MTX, G_MOVEMEM, G_VTX, G_DL = 0x01, 0x03, 0x04, 0x06
G_TRI1, G_CULLDL, G_POPMTX, G_MOVEWORD, G_TEXTURE = 0xBF, 0xBE, 0xBD, 0xBC, 0xBB
G_SETOTHERMODE_H, G_SETOTHERMODE_L, G_ENDDL = 0xBA, 0xB9, 0xB8
G_SETGEOMETRYMODE, G_CLEARGEOMETRYMODE = 0xB7, 0xB6
G_LINE3D, G_RDPHALF_1, G_TRI2, G_BRANCH_Z = 0xB5, 0xB4, 0xB1, 0xB0
G_SETTIMG, G_SETTILE, G_LOADBLOCK = 0xFD, 0xF5, 0xF3

VTX_SIZE = 16
VERTEX_BUFFER = 32  # F3DEX 1.x rsp vertex cache (64 on DX variants; indices guarded)


def parse_vtx(seg, off):
    x, y, z, _flag, s, t = struct.unpack(">hhhHhh", seg[off:off + 12])
    r, g, b, a = seg[off + 12:off + 16]
    return {"pos": (x, y, z), "uv": (s / 32.0, t / 32.0), "rgba": (r, g, b, a)}


def walk_dl(seg, off, max_cmds=20000, _depth=0, _state=None):
    """Walk a display list in a segment-relative buffer; return dict with
    triangles (list of (v0, v1, v2, timg_addr)), vtx pool and texture refs.

    Only addresses whose top byte is the Arwing segment slot (0x03) or 0 are
    resolved inside ``seg``; other segments are recorded in ``external``.
    """
    st = _state if _state is not None else {
        "tris": [], "timgs": [], "external": [], "cmds": 0, "unknown": {},
        "vbuf": [None] * 64, "timg": None, "dls": [],
    }
    st["dls"].append(off)
    pos = off
    while st["cmds"] < max_cmds and pos + 8 <= len(seg):
        w0, w1 = struct.unpack(">II", seg[pos:pos + 8])
        pos += 8
        st["cmds"] += 1
        op = w0 >> 24
        if op == G_ENDDL:
            return st
        if op == G_VTX:
            n = (w0 >> 10) & 0x3F
            v0 = ((w0 >> 16) & 0xFF) // 2
            slot, o = an.segmented_parts(w1)
            if slot != 3 or o + n * VTX_SIZE > len(seg):
                st["external"].append(("vtx", w1))
                continue
            for i in range(n):
                if v0 + i < 64:
                    st["vbuf"][v0 + i] = parse_vtx(seg, o + i * VTX_SIZE)
        elif op == G_TRI1:
            idx = ((w1 >> 16) & 0xFF) // 2, ((w1 >> 8) & 0xFF) // 2, (w1 & 0xFF) // 2
            st["tris"].append((st["timg"], tuple(_snap(st, i) for i in idx)))
        elif op == G_TRI2:
            for w in (w0, w1):
                idx = ((w >> 16) & 0xFF) // 2, ((w >> 8) & 0xFF) // 2, (w & 0xFF) // 2
                st["tris"].append((st["timg"], tuple(_snap(st, i) for i in idx)))
        elif op == G_SETTIMG:
            fmt, siz = (w0 >> 21) & 7, (w0 >> 19) & 3
            st["timg"] = w1
            st["timgs"].append({"addr": w1, "fmt": fmt, "siz": siz})
        elif op == G_DL:
            slot, o = an.segmented_parts(w1)
            if slot == 3 and _depth < 8:
                walk_dl(seg, o, max_cmds, _depth + 1, st)
            else:
                st["external"].append(("dl", w1))
            if (w0 >> 16) & 0xFF == 1:  # branch (no push) ends this list
                return st
        elif op in (G_MTX, G_MOVEMEM, G_POPMTX, G_MOVEWORD, G_TEXTURE,
                    G_SETOTHERMODE_H, G_SETOTHERMODE_L, G_SETGEOMETRYMODE,
                    G_CLEARGEOMETRYMODE, G_CULLDL, G_RDPHALF_1, G_BRANCH_Z, G_LINE3D,
                    G_SETTILE, G_LOADBLOCK, 0xE6, 0xE7, 0xE8, 0xE9, 0xF2, 0xF0,
                    0xFC, 0xFB, 0xFA, 0xF8, 0xFF, 0xFE, 0xFD, 0x00):
            pass
        else:
            st["unknown"][op] = st["unknown"].get(op, 0) + 1
    return st


def _snap(st, i):
    v = st["vbuf"][i] if 0 <= i < 64 else None
    return v


def mesh_from_dl(seg, off):
    """Flatten a display list into (vertices, faces, texture refs)."""
    st = walk_dl(seg, off)
    verts, index, faces = [], {}, []
    for timg, tri in st["tris"]:
        if any(v is None for v in tri):
            continue
        face = []
        for v in tri:
            key = (v["pos"], v["uv"], v["rgba"])
            if key not in index:
                index[key] = len(verts)
                verts.append(v)
            face.append(index[key])
        faces.append((face, timg))
    return {"verts": verts, "faces": faces, "timgs": st["timgs"],
            "external": st["external"], "unknown": st["unknown"],
            "cmds": st["cmds"]}


def _rot_matrix(rot):
    """Limb euler (s16 angle units) -> 3x3, applied Rz*Ry*Rx (N64 SDK order)."""
    ax, ay, az = [r * 2 * math.pi / 65536.0 for r in rot]
    cx, sx, cy, sy, cz, sz = (math.cos(ax), math.sin(ax), math.cos(ay),
                              math.sin(ay), math.cos(az), math.sin(az))
    rx = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    ry = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    rz = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))
    mm = lambda a, b: tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                                  for j in range(3)) for i in range(3))
    return mm(rz, mm(ry, rx))


def walk_skeleton(seg, skel_off, max_limbs=64):
    """Return the flat limb list [{index, off, parent, trans, rot, dList}] by
    following root-pointer array -> child/sibling links."""
    limbs, seen = [], set()

    def visit(addr, parent):
        while addr and len(limbs) < max_limbs:
            slot, o = an.segmented_parts(addr)
            if slot != 3 or o in seen or o + 0x20 > len(seg):
                return
            seen.add(o)
            l = an.parse_limb(seg, o)
            idx = len(limbs)
            limbs.append({"index": idx, "off": o, "parent": parent,
                          "trans": l["trans"], "rot": l["rot"], "dList": l["dList"]})
            if l["child"]:
                visit(l["child"], idx)
            addr = l["sibling"]

    p = skel_off
    while p + 4 <= len(seg):
        a = an._u32(seg, p)
        if not an.is_segmented(a):
            break
        visit(a, -1)
        p += 4
    return limbs


def limb_world(limbs):
    """Rest-pose world (R, t) per limb (hierarchy-composed)."""
    world = []
    for l in limbs:
        r = _rot_matrix(l["rot"])
        t = l["trans"]
        if l["parent"] >= 0:
            pr, pt = world[l["parent"]]
            r = tuple(tuple(sum(pr[i][k] * r[k][j] for k in range(3)) for j in range(3))
                      for i in range(3))
            t = tuple(pt[i] + sum(pr[i][k] * t[k] for k in range(3)) for i in range(3))
        world.append((r, t))
    return world


def export_arwing_obj(rom, path):
    """Export the Arwing rest-pose mesh as an OBJ (one object per limb)."""
    seg = an.file_bytes(rom, "ast_arwing")
    skel = an.ARWING["skeleton"][1]
    limbs = walk_skeleton(seg, skel)
    world = limb_world(limbs)
    out, nv, summary = ["# Star Fox 64 Arwing rest pose, ast_arwing skeleton @%#x" % skel], 0, []
    for l, (r, t) in zip(limbs, world):
        if not l["dList"]:
            continue
        slot, o = an.segmented_parts(l["dList"])
        if slot != 3:
            continue
        m = mesh_from_dl(seg, o)
        if not m["faces"]:
            continue
        out.append("o limb_%d_dl%x" % (l["index"], o))
        for v in m["verts"]:
            p = v["pos"]
            w = [t[i] + sum(r[i][k] * p[k] for k in range(3)) for i in range(3)]
            out.append("v %.3f %.3f %.3f %.3f %.3f %.3f" % (*w, *(c / 255.0 for c in v["rgba"][:3])))
        for v in m["verts"]:
            out.append("vt %.5f %.5f" % (v["uv"][0] / 32.0, 1 - v["uv"][1] / 32.0))
        for f, _t in m["faces"]:
            out.append("f " + " ".join("%d/%d" % (nv + i + 1, nv + i + 1) for i in f))
        nv += len(m["verts"])
        summary.append({"limb": l["index"], "dl": o, "verts": len(m["verts"]),
                        "faces": len(m["faces"]), "unknown_ops": m["unknown"]})
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")
    return {"limbs": len(limbs), "meshes": summary, "total_verts": nv}


def main(argv=None):
    import json
    import sys
    argv = argv or sys.argv[1:]
    from gbox import sf64_inventory as inv
    rom = inv.load_rom(argv[0])
    print(json.dumps(export_arwing_obj(rom, argv[1]), indent=1))


if __name__ == "__main__":
    main()
