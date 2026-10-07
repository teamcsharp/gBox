"""Phantasy Star Online map data (GameCube big-endian / Dreamcast little-endian REL files).

c.rel collision: root -> table of 0x18-byte entries {mesh*, sphere center xyz, radius, flags}, 0-terminated;
mesh = {u32 nv, vertices* (xyz f32), u32 nf, faces*}; face = 36 bytes {u16 v0, v1, v2, flags, f32 normal xyz, ...}.
Verified 2026-10-05 on map_forest01c.rel (GPOE8P): 69 meshes, 1455 triangles, the raster matches Forest 1's layout.
"""
import math
import struct

TRIGGER_FLAG = 0x8000            # 164 tris in Forest 1 cut across open ground: event/trigger volumes, not walls


def rel_root(data: bytes, be: bool = True) -> int:
    e = ">" if be else "<"
    return struct.unpack_from(e + "I", data, len(data) - 0x10)[0]


def collision(data: bytes, be: bool = True) -> list[tuple]:
    """[(v0, v1, v2, flags, normal)] in world coordinates. be=True: GameCube layout; be=False: Dreamcast layout."""
    if not be:
        return collision_dc(data)
    e = ">" if be else "<"
    ro = struct.unpack_from(e + "I", data, len(data) - 0x20)[0]
    o = struct.unpack_from(e + "I", data, rel_root(data, be))[0]
    tris = []
    while o + 0x18 <= ro:
        p = struct.unpack_from(e + "I", data, o)[0]
        if p == 0:
            break
        nv, vp, nf, fp = struct.unpack_from(e + "4I", data, p)
        V = [struct.unpack_from(e + "3f", data, vp + 12 * i) for i in range(nv)]
        for i in range(nf):
            a, b, c, fl = struct.unpack_from(e + "4H", data, fp + 36 * i)
            n = struct.unpack_from(e + "3f", data, fp + 36 * i + 8)
            tris.append((V[a], V[b], V[c], fl, n))
        o += 0x18
    return tris


DC_TRIGGER = 0x00000000          # ponytail: DC face flag meanings not mapped yet; every face counts as geometry


def collision_dc(data: bytes) -> list[tuple]:
    """Dreamcast c.rel: same 0x18-byte table; mesh = {u32 nf, faces*}; face = 68 bytes with inline vertices:
    {v0 xyz, v1 xyz, v2 xyz, normal xyz, centre xyz, f32 radius, u32 flags} (verified on PSO V2 MAP_FOREST01C.REL)."""
    ro = struct.unpack_from("<I", data, len(data) - 0x20)[0]
    o = struct.unpack_from("<I", data, rel_root(data, False))[0]
    tris = []
    while o + 0x18 <= ro:
        p = struct.unpack_from("<I", data, o)[0]
        if p == 0:
            break
        nf, fp = struct.unpack_from("<2I", data, p)
        for i in range(nf):
            f = struct.unpack_from("<16fI", data, fp + 68 * i)
            tris.append((f[0:3], f[3:6], f[6:9], 0, f[9:12]))
        o += 0x18
    return tris


def walkable_cells(tris, size: float = 10.0, step: float = 6.0, body: float = 18.0) -> tuple[set, set]:
    """(floor cells, wall cells). Floors = upward faces (cell height = highest floor under the cell centre).
    A steep face only walls a cell if it rises above the floor by more than `step` (a curb you can't step up)
    and starts below head height (`body`), so ramps, curbs and cliffs under the walkway don't cut the map."""
    floor_y: dict = {}
    for (a, b, c, fl, n) in tris:
        if fl & TRIGGER_FLAG or n[1] <= 0.6:
            continue
        xs, zs = (a[0], b[0], c[0]), (a[2], b[2], c[2])
        for i in range(int(math.floor(min(xs) / size)), int(math.floor(max(xs) / size)) + 1):
            for j in range(int(math.floor(min(zs) / size)), int(math.floor(max(zs) / size)) + 1):
                px, pz = (i + 0.5) * size, (j + 0.5) * size
                if _inside(px, pz, a, b, c):
                    y = _height(px, pz, a, b, c)
                    floor_y[(i, j)] = max(floor_y.get((i, j), -1e9), y)
    wall = set()
    for (a, b, c, fl, n) in tris:
        if fl & TRIGGER_FLAG or abs(n[1]) > 0.6:
            continue
        ylo, yhi = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        for (p, q) in ((a, b), (b, c), (c, a)):
            steps = max(1, int(math.hypot(q[0] - p[0], q[2] - p[2]) / (size / 3)))
            for k in range(steps + 1):
                u = k / steps
                cell = (int(math.floor((p[0] + (q[0] - p[0]) * u) / size)), int(math.floor((p[2] + (q[2] - p[2]) * u) / size)))
                fy = floor_y.get(cell)
                if fy is None or (yhi > fy + step and ylo < fy + body):
                    wall.add(cell)
    return set(floor_y), wall


def _height(px, pz, a, b, c):
    """y of the triangle's plane at (px, pz)."""
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return a[1] - (nx * (px - a[0]) + nz * (pz - a[2])) / ny if abs(ny) > 1e-9 else a[1]


def _inside(px, pz, a, b, c):
    d1 = (px - b[0]) * (a[2] - b[2]) - (a[0] - b[0]) * (pz - b[2])
    d2 = (px - c[0]) * (b[2] - c[2]) - (b[0] - c[0]) * (pz - c[2])
    d3 = (px - a[0]) * (c[2] - a[2]) - (c[0] - a[0]) * (pz - a[2])
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render_objects(data: bytes, be: bool = False) -> list[tuple[int, list]]:
    """Render-geometry REL (Dreamcast d.rel): root {u32 sections, f32, u32 table}; section = 60 bytes {id, pos xyz f32,
    rot xyz BAMS, radius, u32 entries*, .., .., u32 count @+0x2C}; entry = 48 bytes {NJS_OBJECT*, ...}.
    Returns [(section id, [object offset, ...] with the section matrix)] as (id, matrix, [offsets])."""
    from .ninja import _node_matrix
    e = ">" if be else "<"
    cnt, _, tbl = struct.unpack_from(e + "IfI", data, rel_root(data, be))
    out = []
    for s in range(cnt):
        o = tbl + 60 * s
        sid = struct.unpack_from(e + "I", data, o)[0]
        pos, rot = struct.unpack_from(e + "3f", data, o + 4), struct.unpack_from(e + "3i", data, o + 16)
        ents, n = struct.unpack_from(e + "I", data, o + 0x20)[0], struct.unpack_from(e + "I", data, o + 0x2C)[0]
        objs = [struct.unpack_from(e + "I", data, ents + 48 * k)[0] for k in range(n)] if ents else []
        out.append((sid, _node_matrix(pos, rot, (1, 1, 1), False), [p for p in objs if p]))
    return out


def render_manifest(data: bytes, name: str, source: dict, textures: list[str] | None = None, be: bool = False):
    """A whole area's render geometry -> one static UAP package (one mesh per texture, world space, no skeleton).
    Each object is resolved right after it is walked: chunk vertex indices restart per object."""
    from . import uap
    from .ninja import NJ
    acc: dict[int, tuple[list, list, list]] = {}
    for _sid, m, objs in render_objects(data, be):
        for p in objs:
            nj = NJ.__new__(NJ)
            nj.e, nj.d, nj.bones, nj.vbuf, nj.tris, nj.tex = (">" if be else "<"), data, [], {}, {}, 0
            nj.plcache = {}
            try:
                nj._walk(p, None, m)
            except (struct.error, IndexError, KeyError):
                continue                                   # ponytail: skip objects using chunk types we don't decode
            for tex, tris in nj.tris.items():
                pos, nrm, uv = acc.setdefault(tex, ([], [], []))
                for tri in tris:
                    if all(c[0] in nj.vbuf for c in tri):
                        for c in tri:
                            vi, t = c[0], c[1]
                            v = c[2] if len(c) > 2 and c[2] else nj.vbuf[vi]     # snapshot taken at draw time
                            pos.append([round(c, 4) for c in v["pos"]])
                            n = v["nrm"] or [0, 1, 0]
                            ln = math.sqrt(sum(c * c for c in n)) or 1
                            nrm.append([c / ln for c in n])
                            uv.append(t or [0, 0])
    meshes, mats = [], []
    for tex, (pos, nrm, uv) in sorted(acc.items()):
        if not pos:
            continue
        mats.append(uap.Material(name=f"tex{tex}", texture=textures[tex] if textures and tex < len(textures) else None,
                                 source={"ninja_texture_id": tex}))
        meshes.append(uap.Mesh(name=f"{name}_tex{tex}", positions=pos, normals=nrm, uvs=uv, indices=list(range(len(pos))),
                               material=len(mats) - 1))
    return uap.Manifest(name=name, source=source, meshes=meshes, materials=mats,
                        nodes=[uap.Node(name=x.name, mesh=i) for i, x in enumerate(meshes)], roots=list(range(len(meshes))),
                        confidence={"geometry": "partial", "materials": "partial", "textures": "partial" if textures else "missing",
                                    "skeleton": "n/a", "animations": "missing", "source_identity": "verified"})


def to_obj(tris, path):
    with open(path, "w") as f:
        for t in tris:
            for v in t[:3]:
                f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for i in range(len(tris)):
            f.write(f"f {3 * i + 1} {3 * i + 2} {3 * i + 3}\n")


def _selftest():
    # one quad floor (2 tris) + a wall strip: floor cells inside, wall cells along x=20
    V = [(0, 0, 0), (40, 0, 0), (40, 0, 40), (0, 0, 40), (20, 0, 0), (20, 30, 0), (20, 30, 40), (20, 0, 40)]
    def rel(V, faces, be=True):
        e = ">" if be else "<"
        vb = b"".join(struct.pack(e + "3f", *v) for v in V)
        fb = b"".join(struct.pack(e + "4H", *f[:3], f[3]) + struct.pack(e + "3f", *f[4]) + b"\0" * 16 for f in faces)
        mesh = struct.pack(e + "4I", len(V), 0, len(faces), len(vb))
        mesh_off = len(vb) + len(fb)
        table_off = mesh_off + 16
        table = struct.pack(e + "I4fI", mesh_off, 0, 0, 0, 100, 0) + b"\0" * 0x18
        body = vb + fb + mesh + table
        root_off = len(body)
        body += struct.pack(e + "I", table_off)
        relocs_off = len(body)
        return body + struct.pack(e + "5I", relocs_off, 0, 0, 0, root_off) + b"\0" * 12
    faces = [(0, 1, 2, 1, (0, 1, 0)), (0, 2, 3, 1, (0, 1, 0)), (4, 5, 6, 1, (1, 0, 0)), (4, 6, 7, 1, (1, 0, 0))]
    for be in (True, False):
        tris = collision(rel(V, faces, be), be)
        assert len(tris) == 4
        fl, wl = walkable_cells(tris, 10)
        assert (0, 0) in fl and (3, 3) in fl and (2, 1) in wl and (0, 0) not in wl, (sorted(fl), sorted(wl))
    print("psomap selftest ok")


if __name__ == "__main__":
    _selftest()
