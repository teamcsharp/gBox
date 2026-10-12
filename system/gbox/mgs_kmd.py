"""Native reader, validator and writer for PS1 Metal Gear Solid KMD models.

Layout (little endian), verified on the US VR Missions Snake ``init/39213.kmd``:

* header (0x20): u32 bone count, u32 object count, i32 bbox min xyz, max xyz
* object record (0x58 each): u32 flags, u32 face count, i32 bbox[6],
  i32 joint offset xyz (relative to the parent object), i32 parent,
  u32 unknown, u32 vertex count, u32 vertex offset, u32 vertex-order offset,
  u32 normal count, u32 normal offset, u32 normal-order offset,
  u32 uv offset, u32 texture-name offset, u32 pad
* per object data, packed in this order then zero padded to 4 bytes: vertices
  (SVECTOR x,y,z,pair; pair >= 0 is a vertex index in the parent object that
  this vertex is welded to), vertex order (4 x u8 per quad), normals (SVECTOR),
  normal order (4 x u8; bit 7 marks a corner a child welds to), uv (4 x u,v), texture name
  (u16 hash per quad).

The game animates object *i* with motion bone *i* and links it to the parent
named in its record, so a replacement must keep the original's object count,
order, parents, joint offsets and flags.  :func:`check_compatible` enforces
that contract; :func:`normalize` repairs welds, export flags and skeleton records
of a fitted candidate.  :func:`dumps` re-packs a model byte-identically to the game's layout.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace

HEADER = struct.Struct("<II6i")
RECORD = struct.Struct("<II6i3iiIIIIIIIIII")
SVEC = struct.Struct("<4h")


@dataclass
class KmdObject:
    flags: int
    pos: tuple
    parent: int
    unknown: int
    vertices: list = field(default_factory=list)      # (x, y, z, pair)
    normals: list = field(default_factory=list)       # (x, y, z, pad)
    faces: list = field(default_factory=list)         # 4 vertex indices
    face_normals: list = field(default_factory=list)  # 4 normal indices (bit 7 = flag)
    uvs: list = field(default_factory=list)           # 8 bytes per face
    textures: list = field(default_factory=list)      # u16 per face
    bbox: tuple = (0, 0, 0, 0, 0, 0)
    pad: int = 0
    tail: bytes = b""  # alignment bytes after the arrays (the disc keeps tool garbage there)

    def computed_bbox(self) -> tuple:
        if not self.vertices:
            return (0x7FFFFFFF,) * 3 + (-0x80000000,) * 3
        xs, ys, zs = (tuple(v[k] for v in self.vertices) for k in range(3))
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


@dataclass
class Kmd:
    bones: int
    bbox: tuple
    objects: list


def loads(data: bytes) -> Kmd:
    if len(data) < HEADER.size:
        raise ValueError("KMD is shorter than its header")
    bones, count, *bbox = HEADER.unpack_from(data, 0)
    if not 0 < count <= 64 or HEADER.size + count * RECORD.size > len(data):
        raise ValueError(f"KMD object table does not fit: {count} objects")
    objects = []
    for i in range(count):
        (flags, nf, *rest) = RECORD.unpack_from(data, HEADER.size + i * RECORD.size)
        bb, pos, parent, unk = tuple(rest[0:6]), tuple(rest[6:9]), rest[9], rest[10]
        nv, voff, vord, nn, noff, nord, uvo, texo, pad = rest[11:20]
        for name, off, size in (("vertex", voff, nv * 8), ("normal", noff, nn * 8),
                                ("vertex order", vord, nf * 4), ("normal order", nord, nf * 4),
                                ("uv", uvo, nf * 8), ("texture", texo, nf * 2)):
            if off + size > len(data):
                raise ValueError(f"object {i} {name} array runs past the end of the KMD")
        o = KmdObject(flags, pos, parent, unk, bbox=bb, pad=pad)
        o.vertices = [SVEC.unpack_from(data, voff + 8 * k) for k in range(nv)]
        o.normals = [SVEC.unpack_from(data, noff + 8 * k) for k in range(nn)]
        o.faces = [tuple(data[vord + 4 * k:vord + 4 * k + 4]) for k in range(nf)]
        o.face_normals = [tuple(data[nord + 4 * k:nord + 4 * k + 4]) for k in range(nf)]
        o.uvs = [bytes(data[uvo + 8 * k:uvo + 8 * k + 8]) for k in range(nf)]
        o.textures = [struct.unpack_from("<H", data, texo + 2 * k)[0] for k in range(nf)]
        end = texo + 2 * nf
        o.tail = bytes(data[end:end + (-end % 4)])
        objects.append(o)
    return Kmd(bones, tuple(bbox), objects)


def dumps(model: Kmd, *, recompute_bbox: bool = False) -> bytes:
    """Pack *model* in the game's layout (records, then each object's arrays)."""
    count = len(model.objects)
    cursor = HEADER.size + count * RECORD.size
    records, blobs = [], []
    for o in model.objects:
        nf = len(o.faces)
        if not (len(o.face_normals) == len(o.uvs) == len(o.textures) == nf):
            raise ValueError("face arrays of an object must have one entry per face")
        # The game's order: vertices, vertex order, normals, normal order, uv,
        # texture names, then zero padding so the next object's SVECTORs stay
        # word aligned (the R3000 reads them with lw; a 2-mod-4 array faults).
        parts = [b"".join(SVEC.pack(*v) for v in o.vertices),
                 b"".join(bytes(f) for f in o.faces),
                 b"".join(SVEC.pack(*n) for n in o.normals),
                 b"".join(bytes(f) for f in o.face_normals),
                 b"".join(bytes(u) for u in o.uvs),
                 b"".join(struct.pack("<H", t) for t in o.textures)]
        offs = []
        for blob in parts:
            offs.append(cursor)
            cursor += len(blob)
        pad = -cursor % 4
        parts.append(o.tail if len(o.tail) == pad else b"\0" * pad)
        cursor += pad
        voff, vord, noff, nord, uvo, texo = offs
        bb = o.computed_bbox() if recompute_bbox else o.bbox
        records.append(RECORD.pack(o.flags, nf, *bb, *o.pos, o.parent, o.unknown, len(o.vertices),
                                   voff, vord, len(o.normals), noff, nord, uvo, texo, o.pad))
        blobs.extend(parts)
    bbox = model.bbox
    if recompute_bbox:
        boxes = [o.computed_bbox() for o in model.objects if o.vertices]
        bbox = tuple(min(b[k] for b in boxes) for k in range(3)) + tuple(max(b[k] for b in boxes) for k in range(3, 6))
    return HEADER.pack(model.bones, count, *bbox) + b"".join(records) + b"".join(blobs)


def weld_targets(model: Kmd, index: int) -> set[int]:
    """Vertices of object *index* that a child object welds to."""
    return {v[3] for c in model.objects if c.parent == index for v in c.vertices if v[3] >= 0}


def array_offsets(data: bytes) -> list[int]:
    """Vertex and normal array offsets of every object in raw KMD bytes."""
    _bones, count, *_ = HEADER.unpack_from(data, 0)
    out = []
    for i in range(count):
        r = RECORD.unpack_from(data, HEADER.size + i * RECORD.size)
        if r[1] or r[13]:
            out += [r[14], r[17]]
    return out


def problems(model: Kmd, data: bytes | None = None) -> list[str]:
    """Self-consistency checks every game KMD passes.

    With the raw *data*, also require word-aligned SVECTOR arrays.
    """
    out = []
    if data is not None:
        bad = [hex(o) for o in array_offsets(data) if o % 4]
        if bad:
            out.append(f"SVECTOR arrays are not word aligned at {', '.join(bad[:6])}")
    for i, o in enumerate(model.objects):
        targets = weld_targets(model, i)
        for k, (f, n) in enumerate(zip(o.faces, o.face_normals)):
            if any(bool(ni & 0x80) != (vi in targets) for vi, ni in zip(f, n)):
                out.append(f"object {i} face {k} weld-export flags (normal index bit 7) do not "
                           "match the vertices its children weld to")
                break
        if not -1 <= o.parent < i:
            out.append(f"object {i} parent {o.parent} is not an earlier object")
            continue
        parent = model.objects[o.parent] if o.parent >= 0 else None
        nv, nn = len(o.vertices), len(o.normals)
        for k, f in enumerate(o.faces):
            if max(f) >= nv:
                out.append(f"object {i} face {k} uses vertex {max(f)} of {nv}")
        for k, f in enumerate(o.face_normals):
            if max(n & 0x7F for n in f) >= nn:
                out.append(f"object {i} face {k} uses normal {max(n & 0x7F for n in f)} of {nn}")
        for k, v in enumerate(o.vertices):
            if v[3] < 0:
                continue
            if parent is None or v[3] >= len(parent.vertices):
                out.append(f"object {i} vertex {k} pairs to missing parent vertex {v[3]}")
        if any(abs(c) > 0x7FFF for v in o.vertices for c in v[:3]):
            out.append(f"object {i} has a coordinate outside int16")
    return out


def skeleton(model: Kmd) -> list[tuple]:
    return [(o.flags, o.pos, o.parent, o.unknown) for o in model.objects]


def check_compatible(original: Kmd, candidate: Kmd, *, textures: set | None = None,
                     tolerance: int = 2, raw: bytes | None = None) -> list[str]:
    """Return every reason *candidate* cannot replace *original* in the game.

    The game's motion data and the KMD's own records bind object *i* to bone
    *i*: object count, order, flags, parents and joint offsets must not change.
    Welded (paired) vertices must exist in the parent and sit at the parent's
    vertex position minus the joint offset, or the mesh tears when animated.
    """
    out = problems(candidate, dumps(candidate) if raw is None else raw)
    if candidate.bones != original.bones or len(candidate.objects) != len(original.objects):
        out.append(f"object count {len(candidate.objects)}/{candidate.bones} differs from "
                   f"{len(original.objects)}/{original.bones}")
        return out
    for i, (a, b) in enumerate(zip(skeleton(original), skeleton(candidate))):
        if a != b:
            out.append(f"object {i} skeleton record {b} differs from the game's {a}")
    if out:
        return out
    if textures is None:
        textures = {t for o in original.objects for t in o.textures}
    for i, o in enumerate(candidate.objects):
        unknown = sorted(set(o.textures) - textures)
        if unknown:
            out.append(f"object {i} uses texture names absent from the game model: {unknown}")
        if o.parent < 0:
            continue
        parent = candidate.objects[o.parent]
        for k, v in enumerate(o.vertices):
            if 0 <= v[3] < len(parent.vertices):
                pv = parent.vertices[v[3]]
                if any(abs(v[j] + o.pos[j] - pv[j]) > tolerance for j in range(3)):
                    out.append(f"object {i} vertex {k} is welded to parent vertex {v[3]} "
                               "but does not sit on it")
    return out


PAIR_FLAG = 0x10000   # object flag: set on every disc object whose vertices weld to its parent


def weld_seams(original: Kmd, candidate: Kmd, *, radius: float = 48.0) -> tuple[Kmd, int]:
    """Close joint gaps of a rigidly fitted candidate the way the game's own models do.

    In bind pose, every vertex of a child object that lies within *radius* of a
    parent vertex (child local + joint offset vs parent local) is snapped onto
    that parent vertex and paired to it, so the renderer moves it with the
    parent and the seam stays shut while animating.  Vertices farther than
    4 x *radius* from the joint are never welded.  Only objects whose game
    record carries :data:`PAIR_FLAG` are welded (the others never pair on the
    disc), and :func:`normalize` then sets the parent corners' export flags.
    Returns the welded model and the number of new welds.
    """
    if len(candidate.objects) != len(original.objects):
        raise ValueError("candidate and game model differ in object count")
    objects = [replace(c, vertices=list(c.vertices)) for c in candidate.objects]
    welds, r2 = 0, radius * radius
    for i, (o, c) in enumerate(zip(original.objects, objects)):
        if o.parent < 0 or not o.flags & PAIR_FLAG:
            continue
        parent = objects[o.parent].vertices
        if not parent:
            continue
        pos = o.pos
        for k, (x, y, z, pair) in enumerate(c.vertices):
            if pair >= 0 or x * x + y * y + z * z > 16 * r2:   # only seam vertices near the joint itself
                continue
            w = (x + pos[0], y + pos[1], z + pos[2])
            j, d = min(((j, sum((p[a] - w[a]) ** 2 for a in range(3))) for j, p in enumerate(parent)),
                       key=lambda t: t[1])
            if d > r2:
                continue
            p = parent[j]
            c.vertices[k] = (p[0] - pos[0], p[1] - pos[1], p[2] - pos[2], j)
            welds += 1
    model, _notes = normalize(original, Kmd(candidate.bones, candidate.bbox, objects))
    return model, welds


def normalize(original: Kmd, candidate: Kmd, *, tolerance: int = 2) -> tuple[Kmd, list[str]]:
    """Make a fitted candidate obey the game's KMD contract without moving geometry.

    * the game's skeleton records (flags, joint offset, parent, unknown) are restored
      object by object, so motion bone *i* keeps driving object *i*;
    * welds to a missing parent vertex, or to one the vertex does not sit on, are
      re-pointed at the parent vertex at that position, or dropped when none is;
    * normal-index bit 7 is set exactly on corners whose vertex a child welds to,
      which is what every 16-joint character KMD on the disc does;
    * :func:`dumps` then word-aligns every object's arrays.

    Returns the fixed model and a list of the repairs made.
    """
    if len(candidate.objects) != len(original.objects):
        raise ValueError(f"candidate has {len(candidate.objects)} objects; the game model has "
                         f"{len(original.objects)}")
    notes = []
    objects = []
    for i, (o, c) in enumerate(zip(original.objects, candidate.objects)):
        if (c.flags, c.pos, c.parent, c.unknown) != (o.flags, o.pos, o.parent, o.unknown):
            notes.append(f"object {i}: restored the game's skeleton record")
        objects.append(replace(c, flags=o.flags, pos=o.pos, parent=o.parent, unknown=o.unknown,
                               vertices=list(c.vertices), face_normals=list(c.face_normals)))
    model = Kmd(original.bones, candidate.bbox, objects)
    for i, o in enumerate(objects):
        if o.parent < 0:
            if any(v[3] >= 0 for v in o.vertices):
                o.vertices = [(x, y, z, -1) for x, y, z, _ in o.vertices]
                notes.append(f"object {i}: root object cannot weld; welds dropped")
            continue
        parent = objects[o.parent].vertices
        for k, (x, y, z, pair) in enumerate(o.vertices):
            if pair < 0:
                continue
            want = (x + o.pos[0], y + o.pos[1], z + o.pos[2])
            def sits(j):
                return all(abs(parent[j][a] - want[a]) <= tolerance for a in range(3))
            if pair < len(parent) and sits(pair):
                continue
            match = next((j for j in range(len(parent)) if sits(j)), -1)
            o.vertices[k] = (x, y, z, match)
            notes.append(f"object {i} vertex {k}: weld {pair} -> {match if match >= 0 else 'none'}")
    for i, o in enumerate(objects):
        targets = weld_targets(model, i)
        fixed = [tuple((n & 0x7F) | (0x80 if v in targets else 0) for v, n in zip(f, fn))
                 for f, fn in zip(o.faces, o.face_normals)]
        if fixed != o.face_normals:
            notes.append(f"object {i}: set weld-export flags on {len(targets)} vertices")
            o.face_normals = fixed
    return model, notes
