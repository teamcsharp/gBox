"""Resident Evil: The Mercenaries 3D (3DS, MT Framework Mobile) MOD v229 structure probe.

Analysis-stage decoder for the plNNNN MOD files inside ``/archive/uPl( <Name> ).arc``.
Everything here is derived from the owned EUR build's pl0000 (Chris) MOD and pinned by
invariants (table offsets, per-mesh vertex/index tiling, joint-id set identity):

  header    0x00  20 bytes  "MOD\\0" + u16 version + u16 bones + u16 meshes + u16 materials
                            + u32 vertices + u32 indices
  hdr u32s  0x14  u0 (=0x39FD, meaning TBD) | vtx_end | 0 | bones | 1 | 0x80
                    | bone_off | mat_off | mesh_off | vtx_off | idx_off
  bones     bone_off  20 x 0x20  {u32 joint_id, u32 w1, u32 w2, u32 0, 3 x f32 0, u32 0x7F800000}
            (joint ids here == the set of mesh joint ids: 0,1,2,0x14,0x18,0x1C,0x28,0x2F,0x30,
             0x37,0x38,0x3C,0x3D,0x40,0x46,0x50,0x53,0x54,0x58,0x60)
  materials mat_off  5 x 0x80   ASCII name at +0 (mangled), rest reserved
  meshes    mesh_off 46 x 0x30  {u16 tag 0xEFDF, u16 vertex_count, u16 joint_id, u16 1,
                                 u16 fmt (0x21 / 0x121), u16 0x424, u32 vertex_start,
                                 u32 0, u32 0xF606F017, u32 index_start, u32 index_count,
                                 8 bytes trailing (TBD)}
  vertices  vtx_off  stride 36  {f32 pos x,y,z (joint-local), s16 uv0 u,v (/32768),
                                 f32 uv1 u,v, u32 u24 (TBD), s16 pair (/32768, TBD),
                                 u32 skin = (weight<<16) | bone2}
  indices   idx_off  u16, one run per mesh: 2 or 3 header indices (strip restart) followed by
            (index_count) more; the per-mesh runs tile [0, index_total) exactly.

Nothing is written back into the image. ``python -m gbox.merc3d_mod MOD [--mesh 0 --obj out.obj]``
prints the structural summary. The real pl0000.mod decodes as:
  20 bones / 46 meshes / 5 materials / 13449 verts / 27624 indices, vtx_off 0x1B20,
  vtx_size 0x76344 (13449*36), idx_off 0x77E64, file 546354 bytes.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"MOD\x00"
HEADER = 20


class ModError(ValueError):
    pass


@dataclass
class Bone:
    joint: int
    w1: int
    w2: int
    pad: int
    pos: tuple[float, float, float]
    tail: int  # observed constant 0x7F800000


@dataclass
class Mesh:
    index: int
    tag: int
    vertex_count: int
    joint: int
    u3: int
    fmt: int
    f5: int
    vertex_start: int
    u4: int
    u5: int
    index_start: int
    index_count: int
    tail: bytes  # 8 bytes, semantics TBD
    header: int = 0  # strip header length (2 or 3), filled by index_tiling()

    @property
    def index_end(self) -> int:
        return self.index_start + self.header + self.index_count

    @property
    def vertex_end(self) -> int:
        return self.vertex_start + self.vertex_count


@dataclass
class Vertex:
    pos: tuple[float, float, float]
    uv0: tuple[float, float]   # s16 / 32768
    uv1: tuple[float, float]   # f32, 0..1
    u24: int                   # semantics TBD (e.g. 0x4DB20801)
    pair: tuple[float, float]  # s16 / 32768, spans +-1, semantics TBD
    bone2: int                 # low u16: second skin bone (index into the bone table)
    weight2: int               # high u16: weight of bone2 in percent (0..100)


class Mod:
    def __init__(self, data: bytes):
        if len(data) < HEADER or data[:4] != MAGIC:
            raise ModError("not a MOD")
        (ver, bones, meshes, mats, verts, idx) = struct.unpack_from("<HHHHII", data, 4)
        if ver != 229:
            raise ModError(f"unsupported MOD version {ver}")
        self.data = data
        self.version, self.bone_count, self.mesh_count = ver, bones, meshes
        self.material_count, self.vertex_count, self.index_count = mats, verts, idx
        (self.u0, self.vtx_size, self.u2, self.u3, self.u4, self.u5,
         self.bone_off, self.mat_off, self.mesh_off, self.vtx_off, self.idx_off) = \
            struct.unpack_from("<11I", data, 0x14)
        self.bones = [self._bone(i) for i in range(bones)]
        self.materials = [self._material(i) for i in range(mats)]
        self.meshes = [self._mesh(i) for i in range(meshes)]
        self._check_tables()
        self.index_tiling()

    def _u16(self, o): return struct.unpack_from("<H", self.data, o)[0]

    def _u32(self, o): return struct.unpack_from("<I", self.data, o)[0]

    def _f32(self, o): return struct.unpack_from("<f", self.data, o)[0]

    def _bone(self, i: int) -> Bone:
        o = self.bone_off + i * 0x20
        return Bone(*struct.unpack_from("<4I", self.data, o),
                    (self._f32(o + 0x10), self._f32(o + 0x14), self._f32(o + 0x18)),
                    self._u32(o + 0x1C))

    def _material(self, i: int) -> str:
        b = self.data[self.mat_off + i * 0x80: self.mat_off + i * 0x80 + 0x80].split(b"\0")[0]
        return b.decode("latin-1", "replace")

    def _mesh(self, i: int) -> Mesh:
        o = self.mesh_off + i * 0x30
        return Mesh(i, *struct.unpack_from("<6H", self.data, o), *struct.unpack_from("<5I", self.data, o + 12),
                    self.data[o + 0x20:o + 0x30])

    def _check_tables(self):
        """Pin the header's offset table against the file layout."""
        if self.idx_off + self.index_count * 2 > len(self.data) + 4:
            raise ModError("index buffer runs past end of file")
        if self.vtx_size != self.vertex_count * 36:
            raise ModError(f"vertex buffer size {self.vtx_size} != {self.vertex_count}*36")
        if self.vtx_off + self.vtx_size != self.idx_off:
            raise ModError(f"vertex buffer {self.vtx_off}+{self.vtx_size} != idx_off {self.idx_off:#x}")
        if sum(m.vertex_count for m in self.meshes) != self.vertex_count:
            raise ModError("mesh vertex counts don't sum to header")
        if self.mesh_off != self.mat_off + self.material_count * 0x80:
            raise ModError("material table size mismatch")
        joints = {b.joint for b in self.bones}
        if not joints <= {m.joint for m in self.meshes}:
            raise ModError("bone joint ids are not all referenced by meshes")

    def index_tiling(self):
        """Per-mesh index runs tile [0, index_count) with a 2- or 3-index strip header."""
        for i, m in enumerate(self.meshes):
            nxt = self.meshes[i + 1].index_start if i + 1 < self.mesh_count else self.index_count
            h = nxt - m.index_start - m.index_count
            if h not in (2, 3):
                raise ModError(f"mesh {i}: index run doesn't tile (header {h})")
            m.header = h

    def vertex(self, m: Mesh, k: int) -> Vertex:
        if not (0 <= k < m.vertex_count):
            raise ModError("vertex index out of range")
        o = self.vtx_off + (m.vertex_start + k) * 36
        u0, v0, u1, v1 = struct.unpack_from("<hhff", self.data, o + 12)
        skin = self._u32(o + 32)
        return Vertex((self._f32(o), self._f32(o + 4), self._f32(o + 8)),
                      (u0 / 32768.0, v0 / 32768.0), (u1, v1), self._u32(o + 24),
                      (struct.unpack_from("<h", self.data, o + 28)[0] / 32768.0,
                       struct.unpack_from("<h", self.data, o + 30)[0] / 32768.0),
                      skin & 0xFFFF, skin >> 16)

    def indices(self, m: Mesh) -> list[int]:
        o = self.idx_off + m.index_start * 2
        return list(struct.unpack_from(f"<{m.header + m.index_count}H", self.data, o))

    def obj(self, m: Mesh) -> str:
        """Wavefront OBJ of one mesh: positions, uv0, and the strip index run (header dropped)."""
        lines = [f"# MOD v{self.version} mesh {m.index} joint {m.joint} verts {m.vertex_count}"]
        for k in range(m.vertex_count):
            v = self.vertex(m, k)
            lines.append(f"v {v.pos[0]:.6f} {v.pos[1]:.6f} {v.pos[2]:.6f}")
            lines.append(f"vt {v.uv0[0]:.6f} {v.uv0[1]:.6f}")
        run = self.indices(m)[m.header:]
        for t in range(0, len(run) - 2, 3):
            if t // 3 % 2:
                lines.append(f"f {run[t] + 1}/{run[t] + 1} {run[t + 2] + 1}/{run[t + 2] + 1} "
                             f"{run[t + 1] + 1}/{run[t + 1] + 1}")
            else:
                lines.append(f"f {run[t] + 1}/{run[t] + 1} {run[t + 1] + 1}/{run[t + 1] + 1} "
                             f"{run[t + 2] + 1}/{run[t + 2] + 1}")
        return "\n".join(lines) + "\n"

    def summary(self) -> dict:
        return {
            "version": self.version, "bones": self.bone_count, "meshes": self.mesh_count,
            "materials": self.material_count, "vertices": self.vertex_count, "indices": self.index_count,
            "u0": self.u0, "vtx_size": self.vtx_size, "u2": self.u2, "u3": self.u3, "u4": self.u4, "u5": self.u5,
            "bone_off": self.bone_off, "mat_off": self.mat_off, "mesh_off": self.mesh_off,
            "vtx_off": self.vtx_off, "idx_off": self.idx_off, "size": len(self.data),
            "bone_joints": [b.joint for b in self.bones],
            "bone_w1": [b.w1 for b in self.bones], "bone_w2": [b.w2 for b in self.bones],
            "materials": self.materials,
            "mesh_formats": sorted({(m.fmt, m.f5) for m in self.meshes}),
            "strip_headers": sorted({m.header for m in self.meshes}),
            "mesh_joints": sorted({m.joint for m in self.meshes}),
        }


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("mod")
    ap.add_argument("--mesh", type=int, default=0)
    ap.add_argument("--obj")
    a = ap.parse_args(argv)
    mod = Mod(Path(a.mod).read_bytes())
    print(json.dumps(mod.summary(), indent=1))
    if a.obj:
        Path(a.obj).write_text(mod.obj(mod.meshes[a.mesh]))
        print(f"wrote mesh {a.mesh} -> {a.obj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
