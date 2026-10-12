"""Mortal Kombat Gold (Dreamcast) model probe: the body of a GEO mesh part, the IMG texel format and the per-character
skeleton node tables in 1ST_READ.BIN. Measured on T-9701N V1.006 (1ST_READ sha256 05185248...e37a).

GEO part body (record flags 1, data at record + 4 + rel; see mkgold_inventory): `n` triangle strips back to back.

* strip header, 32 bytes: u32 0, u16 parity, u16 vertex count, 24 zero bytes
* vertex, 32 bytes: f32 normal x, y, z; f32 position x, y, z; f32 s, t

Positions are local to the part's joint and y-down (the MK4 convention): limb parts hang along -y from their joint.
A strip changes direction by repeating a vertex (degenerate triangle). Triangle i of a strip (vertices i, i+1, i+2)
faces along its vertex normals when (i + parity) is odd; otherwise its order is i, i+2, i+1 (about 83% agreement on
KL_GEO, the rest are smoothing-normal outliers). `t` is a whole multiple of 1/512 on most vertices and `s` is not
quantized, so `t` runs along the 512-texel width of the character page and `s` along its height.

IMG page: 16-bit ARGB1555, stored linearly (row-major, not twiddled). On KL_GEO.IMG the mean neighbour colour distance
is 46.7 linear vs 134.4 twiddled (RGB565 109.5/182.8, ARGB4444 160.0/267.9). `texel_layout` reproduces the numbers.

Skeletons (there are no skeleton files on the disc): 1ST_READ holds one 48-byte group per character ID, 23 groups at
0x8C32C6F8 (`character_table`, found by content). Each group has 4 x {model-set entry*, node table A*, node table B*}.
A model-set entry is 12 bytes {GEO load-table entry*, 0, 0}. A node record is 32 bytes {u32 code, u32 model-set entry*,
u32 0, f32 x, y, z, u32 index, u32 0}. code >> 20 (signed 12 bits) is the body-part number (negative: a joint without
a mesh), and the low 20 bits are flags. When 0x10 is clear, the walk pushes the current transform before the node.
0x08 pops after the node, and a pop on an empty stack ends the table. 0x01 marks the mirrored side, 0x02 the first
node of a mirrored chain and 0x04 the root. The offsets are local to the parent. Liu Kang's table (0x8C566744) is
pelvis(4) > spine joint > torso(3) > head(2); arms 5/7/9 and 6/8/10 hang off the torso, legs 11/13/15 and 12/14/16
off the spine joint. Code loads the table base 0x8C32C6AC (and +4) at 0x8C0A4746, 0x8C0B9FB2, 0x8C0BA0F2,
0x8C0BE558, 0x8C0C5BA4 and more (PC-relative literal pool loads).

    python -m gbox.mkgold_geo DISC.gdi --model KL_GEO --part 0 --obj kl0.obj --png kl.png --report r.json --validate
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

from .mkgold_inventory import KEY, SPRITE, exe_tables, geo_records, img_pages

STRIP = VERTEX = NODE = 32
GROUP = 48                            # character_table group: 4 x (model-set entry*, node table A*, node table B*)
NO_PUSH, POP, MIRROR, MIRROR_START, ROOT = 0x10, 0x08, 0x01, 0x02, 0x04
BUILD = {"1st_read_sha256": "0518524820d8a24d6978b494cf71a319635bbe6f8ad2c8941cf85bfa41d1e37a",
         "character_table": 0x8C32C6F8, "table_base_in_code": 0x8C32C6AC, "geo_load_table": 0x8C2F23E0}


# ------------------------------------------------------------------ GEO part bodies

def part_strips(data: bytes, rec: dict) -> list[dict]:
    """The `n` strips of one mesh record: [{offset, parity, normals, positions, st}]. Raises ValueError when a strip
    header is malformed or the strips overrun the record's bytes."""
    if rec["flags"] & SPRITE or "offset" not in rec:
        raise ValueError(f"record {rec['index']} is an inline sprite, not a mesh part")
    o, end, strips = rec["offset"], rec["offset"] + rec["bytes"], []
    for _ in range(rec["n"]):
        if o + STRIP > end:
            raise ValueError(f"record {rec['index']}: strip header past 0x{end:x}")
        lead, parity, nv = struct.unpack_from("<IHH", data, o)
        if lead or parity > 1 or any(data[o + 8:o + STRIP]) or o + STRIP + nv * VERTEX > end:
            raise ValueError(f"record {rec['index']}: bad strip header at 0x{o:x}")
        verts = [struct.unpack_from("<8f", data, o + STRIP + i * VERTEX) for i in range(nv)]
        strips.append({"offset": o, "parity": parity, "normals": [v[:3] for v in verts],
                       "positions": [v[3:6] for v in verts], "st": [v[6:8] for v in verts]})
        o += STRIP + nv * VERTEX
    return strips


def strip_triangles(nv: int, parity: int) -> list[tuple[int, int, int]]:
    """Strip-local triangles ordered counter-clockwise about the vertex normals."""
    return [(i, i + 1, i + 2) if (i + parity) % 2 else (i, i + 2, i + 1) for i in range(nv - 2)]


def part_mesh(data: bytes, rec: dict) -> dict:
    """{positions, normals, st, faces, strips, tail}: one vertex per strip vertex, degenerate triangles dropped. tail
    counts the record bytes left after the last strip."""
    pos, nrm, st, faces = [], [], [], []
    strips = part_strips(data, rec)
    for s in strips:
        base, p = len(pos), s["positions"]
        pos += p
        nrm += s["normals"]
        st += s["st"]
        for t in strip_triangles(len(p), s["parity"]):
            if p[t[0]] != p[t[1]] and p[t[1]] != p[t[2]] and p[t[0]] != p[t[2]]:
                faces.append((base + t[0], base + t[1], base + t[2]))
    end = strips[-1]["offset"] + STRIP + len(strips[-1]["positions"]) * VERTEX if strips else rec["offset"]
    return {"positions": pos, "normals": nrm, "st": st, "faces": faces, "strips": len(strips),
            "tail": rec["offset"] + rec["bytes"] - end}


def facing_ratio(mesh: dict) -> float:
    """Share of faces whose winding agrees with the sum of their vertex normals."""
    good = total = 0
    P, N = mesh["positions"], mesh["normals"]
    for a, b, c in mesh["faces"]:
        e1 = [P[b][i] - P[a][i] for i in range(3)]
        e2 = [P[c][i] - P[a][i] for i in range(3)]
        cr = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        dot = sum(cr[i] * (N[a][i] + N[b][i] + N[c][i]) for i in range(3))
        if dot:
            total += 1
            good += dot > 0
    return good / total if total else 0.0


def bbox(points) -> list[list[float]]:
    return [[min(p[i] for p in points), max(p[i] for p in points)] for i in range(3)] if points else []


def to_obj(mesh: dict, name: str = "part", texture: str | None = None, y_up: bool = True) -> str:
    """Wavefront OBJ text. y_up rotates the y-down data 180 degrees about X (y, z negated; winding kept).
    vt = (t, 1 - s): t is the 512-wide axis of the page."""
    k = -1.0 if y_up else 1.0
    out = [f"# {name}: {len(mesh['positions'])} vertices, {len(mesh['faces'])} triangles (gbox.mkgold_geo)"]
    if texture:
        out += [f"mtllib {name}.mtl", f"usemtl {name}"]
    out += [f"v {x:.6f} {k * y:.6f} {k * z:.6f}" for x, y, z in mesh["positions"]]
    out += [f"vt {t:.6f} {1.0 - s:.6f}" for s, t in mesh["st"]]
    out += [f"vn {x:.6f} {k * y:.6f} {k * z:.6f}" for x, y, z in mesh["normals"]]
    out += [f"f {a + 1}/{a + 1}/{a + 1} {b + 1}/{b + 1}/{b + 1} {c + 1}/{c + 1}/{c + 1}" for a, b, c in mesh["faces"]]
    return "\n".join(out) + "\n"


def to_mtl(name: str, texture: str) -> str:
    return f"newmtl {name}\nKd 1 1 1\nmap_Kd {texture}\nmap_d {texture}\n"


# ------------------------------------------------------------------ IMG texels

def argb1555(p: int) -> tuple[int, int, int, int]:
    c = lambda v: (v << 3) | (v >> 2)
    return c((p >> 10) & 31), c((p >> 5) & 31), c(p & 31), 255 if p & 0x8000 else 0


def page_texels(data: bytes, page: int = 0) -> tuple[int, int, tuple]:
    pg = img_pages(data)[page]
    w, h = pg["width"], pg["height"]
    return w, h, struct.unpack_from(f"<{w * h}H", data, pg["offset"])


def img_rgba(data: bytes, page: int = 0) -> tuple[int, int, bytes]:
    """(width, height, RGBA8 bytes) of one page, read as linear ARGB1555."""
    w, h, px = page_texels(data, page)
    lut = [argb1555(p) for p in range(0x10000)]
    return w, h, b"".join(bytes(lut[p]) for p in px)


def png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _morton(x: int, y: int) -> int:
    r = 0
    for i in range(11):
        r |= ((x >> i) & 1) << (2 * i + 1) | ((y >> i) & 1) << (2 * i)
    return r


def twiddled_index(x: int, y: int, w: int, h: int) -> int:
    """PVR twiddled address: square Morton blocks (y in the low bit) laid out along the longer side."""
    s = min(w, h)
    if w >= h:
        return (x // s) * s * s + _morton(x % s, y)
    return (y // s) * s * s + _morton(x, y % s)


def texel_layout(data: bytes, page: int = 0, step: int = 3) -> dict:
    """Mean colour distance between a texel and its right and lower neighbours under linear and twiddled addressing,
    per candidate 16-bit format. The smallest distance names the storage."""
    w, h, px = page_texels(data, page)
    fmts = {"ARGB1555": lambda p: (((p >> 10) & 31) * 8, ((p >> 5) & 31) * 8, (p & 31) * 8),
            "RGB565": lambda p: (((p >> 11) & 31) * 8, ((p >> 5) & 63) * 4, (p & 31) * 8),
            "ARGB4444": lambda p: (((p >> 8) & 15) * 17, ((p >> 4) & 15) * 17, (p & 15) * 17)}
    lin = lambda x, y: y * w + x
    tw = lambda x, y: twiddled_index(x, y, w, h)
    out = {}
    for name, rgb in fmts.items():
        for lay, idx in (("linear", lin), ("twiddled", tw)):
            d = n = 0
            for y in range(0, h - 1, step):
                for x in range(0, w - 1, step):
                    a, b, c = rgb(px[idx(x, y)]), rgb(px[idx(x + 1, y)]), rgb(px[idx(x, y + 1)])
                    d += sum(abs(a[i] - b[i]) + abs(a[i] - c[i]) for i in range(3))
                    n += 1
            out[f"{name}/{lay}"] = round(d / max(n, 1), 1)
    best = min(out, key=lambda k: out[k])
    return {"width": w, "height": h, "distance": out, "best": best,
            "alpha_set": round(sum(p >> 15 for p in px) / len(px), 3)}


# ------------------------------------------------------------------ skeleton node tables in 1ST_READ

def node_table(exe: bytes, addr: int, key: int = KEY, limit: int = 64) -> list[dict]:
    """Node records from addr until a pop on an empty stack (or a record of another model set)."""
    nodes, stack, cur, model_set = [], [], None, None
    o = addr - key
    while len(nodes) < limit and 0 <= o <= len(exe) - NODE:
        code, ms, _, x, y, z, index, _ = struct.unpack_from("<III3fII", exe, o)
        if model_set is None:
            model_set = ms
        elif ms != model_set:
            break
        part = code >> 20
        part -= 0x1000 if part & 0x800 else 0
        flags = code & 0xFFFFF
        nodes.append({"addr": key + o, "part": part, "flags": flags, "offset": (x, y, z), "index": index})
        if not flags & NO_PUSH:
            stack.append(cur)
        cur = len(nodes) - 1
        if flags & POP:
            if not stack:
                break
            cur = stack.pop()
        o += NODE
    return nodes


def node_parents(nodes: list[dict]) -> list[int | None]:
    """Parent node index of each node under the push/pop walk."""
    parents, stack, cur = [], [], None
    for i, n in enumerate(nodes):
        if not n["flags"] & NO_PUSH:
            stack.append(cur)
        parents.append(cur)
        cur = i
        if n["flags"] & POP:
            cur = stack.pop() if stack else None
    return parents


def rest_joints(nodes: list[dict], parents: list[int | None]) -> list[tuple[float, float, float]]:
    """Joint positions with identity rotations (offsets summed along the parent chain), y-down."""
    out: list[tuple[float, float, float]] = []
    for n, p in zip(nodes, parents):
        base = out[p] if p is not None else (0.0, 0.0, 0.0)
        out.append(tuple(base[i] + n["offset"][i] for i in range(3)))
    return out


def character_table(exe: bytes, key: int = KEY, tables: dict | None = None) -> dict:
    """The per-character-ID skeleton groups: {addr, characters: [{id, name, variants: [{model_set, geo, img,
    nodes_a, nodes_b}]}]}. Found by content: the longest run of 48-byte groups whose 4 triples each point at a model-set
    entry (first word: a GEO load-table entry) and at a node table whose records point back at that entry."""
    tabs = tables or exe_tables(exe, key)
    t0 = int(tabs["geo_table"]["addr"], 16)
    entries = tabs["geo_table"]["entries"]
    n = len(exe)
    u32 = lambda o: struct.unpack_from("<I", exe, o)[0]

    def entry(o: int) -> int | None:
        k, r = divmod(u32(o) - t0, 20)
        return k if r == 0 and 0 <= k < len(entries) else None

    def triple(o: int) -> int | None:
        ms, a = u32(o) - key, u32(o + 4) - key
        if not (0 <= ms <= n - 4 and 0 <= a <= n - NODE and (u32(o + 8) - key) % 4 == 0):
            return None
        return entry(ms) if u32(a + 4) == key + ms else None

    ok = {o for o in range(0, n - 12 + 1, 4) if 0 <= u32(o) - key < n and triple(o) is not None}
    start, length = None, 0
    for o in sorted(ok):
        if o - 12 in ok:
            continue                      # only runs of 12-byte triples that start here
        k = 0
        while o + 12 * k in ok:
            k += 1
        if k > length:
            start, length = o, k
    best = [start + GROUP * i for i in range(length // 4)] if start is not None else []
    names = tabs["roster"]["names"]
    chars = []
    for cid, o in enumerate(best):
        variants = []
        for j in range(4):
            ms, a, b = struct.unpack_from("<3I", exe, o + 12 * j)
            e = entries[entry(ms - key)]
            variants.append({"model_set": f"0x{ms:08X}", "geo": e["geo"], "img": e["img"],
                             "nodes_a": f"0x{a:08X}", "nodes_b": f"0x{b:08X}"})
        chars.append({"id": cid, "name": names[cid] if cid < len(names) else None, "variants": variants})
    return {"addr": f"0x{key + best[0]:08X}" if best else None, "stride": GROUP, "characters": chars}


def skeleton(exe: bytes, addr: str | int, key: int = KEY) -> dict:
    nodes = node_table(exe, int(addr, 16) if isinstance(addr, str) else addr, key)
    parents = node_parents(nodes)
    joints = rest_joints(nodes, parents)
    return {"nodes": [{"part": nd["part"], "flags": f"0x{nd['flags']:05X}", "parent": p,
                       "offset": [round(v, 6) for v in nd["offset"]], "rest": [round(v, 6) for v in j]}
                      for nd, p, j in zip(nodes, parents, joints)]}


# ------------------------------------------------------------------ CLI probe

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def validate_geo(read, names) -> dict:
    """Parse every mesh record of every GEO: counts and failures (failed_files: failing records per file)."""
    out = {"files": 0, "parts": 0, "strips": 0, "vertices": 0, "faces": 0, "tails": 0, "failures": [],
           "failed_files": {}}
    for nm in names:
        data = read(nm)
        out["files"] += 1
        for rec in geo_records(data):
            if rec["flags"] & SPRITE or "offset" not in rec:
                continue
            try:
                m = part_mesh(data, rec)
            except ValueError as e:
                out["failures"].append(f"{nm}: {e}")
                out["failed_files"][nm] = out["failed_files"].get(nm, 0) + 1
                continue
            out["parts"] += 1
            out["strips"] += m["strips"]
            out["vertices"] += len(m["positions"])
            out["faces"] += len(m["faces"])
            out["tails"] += m["tail"] != 0
    return out


def main(argv=None):
    import argparse
    from .gdrom import GDRom
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--model", default="KL_GEO", help="GEO/IMG stem, e.g. KL_GEO")
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--obj")
    ap.add_argument("--png")
    ap.add_argument("--report")
    ap.add_argument("--validate", action="store_true", help="parse every mesh part of every GEO on the disc")
    a = ap.parse_args(argv)
    g = GDRom(a.gdi)
    exe = g.read("1ST_READ.BIN")
    geo = g.read(f"{a.model}.GEO")
    rec = geo_records(geo)[a.part]
    mesh = part_mesh(geo, rec)
    rep = {"exe_sha256": _sha(exe), "build_match": _sha(exe) == BUILD["1st_read_sha256"],
           "model": a.model, "geo_sha256": _sha(geo),
           "part": {"index": a.part, "offset": f"0x{rec['offset']:x}", "bytes": rec["bytes"], "strips": mesh["strips"],
                    "vertices": len(mesh["positions"]), "faces": len(mesh["faces"]), "tail": mesh["tail"],
                    "facing_ratio": round(facing_ratio(mesh), 3), "bbox": bbox(mesh["positions"])}}
    if f"{a.model}.IMG" in g.files:
        img = g.read(f"{a.model}.IMG")
        rep["img"] = {"sha256": _sha(img), **texel_layout(img)}
        if a.png:
            Path(a.png).write_bytes(png_bytes(*img_rgba(img)))
    tabs = exe_tables(exe)
    table = character_table(exe, tables=tabs)
    rep["character_table"] = {"addr": table["addr"], "characters": len(table["characters"])}
    want = f"{a.model.lower()}.geo"
    for c in table["characters"]:
        for v in c["variants"]:
            if v["geo"] == want and "skeleton" not in rep:
                rep["skeleton"] = {"character": c["name"], "id": c["id"], **v, **skeleton(exe, v["nodes_a"])}
    rep["skeleton_sizes"] = {c["name"]: len(node_table(exe, int(c["variants"][0]["nodes_a"], 16)))
                             for c in table["characters"]}
    if a.validate:
        rep["geo_validation"] = validate_geo(g.read, sorted(n for n in g.files if n.endswith(".GEO")))
    if a.obj:
        name = Path(a.obj).stem
        tex = Path(a.png).name if a.png else None
        Path(a.obj).write_text(to_obj(mesh, name, tex))
        if tex:
            Path(a.obj).with_suffix(".mtl").write_text(to_mtl(name, tex))
    text = json.dumps(rep, indent=1)
    if a.report:
        Path(a.report).write_text(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
