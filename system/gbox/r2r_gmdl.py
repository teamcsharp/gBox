"""Ready 2 Rumble Boxing (Dreamcast) GMDL...RII model probe.

Layout PROVED by tiling on all 28 strict-RII GMDL entries of the owned build
(BOXING.RAT, source CHD sha256 bd33199e...9a53); field *meanings* marked
HYPOTHESIS are not yet confirmed against the SH-4 loader.

  0x00  u32 ntri            (proved: triangle stream parses exactly ntri records)
  0x04  u32 nvert           (proved: vertex block ends at 0x10 + nvert*64)
  0x08  u32 h2              (HYPOTHESIS: aux/bone-name count; 0 for props/icons)
  0x0c  u32 h3              (HYPOTHESIS: node/bone count; 22/25 on fighters, 1 on props)
  0x10  nvert * 64B vertex records (little endian):
          +0  4*u32 attrs   (attrs[1] small group index 0,1,2.. HYPOTHESIS bone/group)
          +16 4*f32 vecA    (x,y,z,w) w in {1.0,.75,.5..} HYPOTHESIS weight
          +32 4*f32 vecB    (x,y,z,w) HYPOTHESIS second position/normal
          +48 16 zero bytes (padding, all zero in every sample)
  then  16B triangle-block header (u32 a,a,0,0; a==h3-1 on fighters)
  then  ntri * 44B triangle records:
          3*u32 vertex index (< nvert, proved)  u32 tag (HYPOTHESIS material/tex)
          u32 0  6*f32 uv (3 corners)
  then  trailer starting with a 4x4 identity matrix (HYPOTHESIS skeleton /
        transform matrices); preserved verbatim as ``trailer`` for roundtrip.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

VERT_STRIDE = 64
TRI_STRIDE = 44
HDR = 16
TRI_HDR = 16


@dataclass
class Gmdl:
    ntri: int
    nvert: int
    h2: int
    h3: int
    verts: list  # (attrs4, vecA4, vecB4)
    tri_hdr: bytes
    tris: list   # (i0,i1,i2,tag,pad,uv6)
    trailer: bytes


def parse_gmdl(b: bytes) -> Gmdl:
    ntri, nvert, h2, h3 = struct.unpack_from("<4I", b, 0)
    tb = HDR + nvert * VERT_STRIDE
    end = tb + TRI_HDR + ntri * TRI_STRIDE
    if end > len(b):
        raise ValueError("GMDL truncated: need %d bytes, have %d" % (end, len(b)))
    verts = []
    for k in range(HDR, tb, VERT_STRIDE):
        verts.append((struct.unpack_from("<4I", b, k), struct.unpack_from("<4f", b, k + 16),
                      struct.unpack_from("<4f", b, k + 32)))
        if b[k + 48:k + 64] != bytes(16):
            raise ValueError("nonzero vertex padding at 0x%x" % k)
    tris = []
    for p in range(tb + TRI_HDR, end, TRI_STRIDE):
        i0, i1, i2, tag, pad = struct.unpack_from("<5I", b, p)
        if max(i0, i1, i2) >= nvert:
            raise ValueError("triangle index out of range at 0x%x" % p)
        tris.append((i0, i1, i2, tag, pad, struct.unpack_from("<6f", b, p + 20)))
    return Gmdl(ntri, nvert, h2, h3, verts, bytes(b[tb:tb + TRI_HDR]), tris, bytes(b[end:]))


def write_gmdl(g: Gmdl) -> bytes:
    out = bytearray(struct.pack("<4I", len(g.tris), len(g.verts), g.h2, g.h3))
    for a, va, vb in g.verts:
        out += struct.pack("<4I4f4f", *a, *va, *vb) + bytes(16)
    out += g.tri_hdr
    for i0, i1, i2, tag, pad, uv in g.tris:
        out += struct.pack("<5I6f", i0, i1, i2, tag, pad, *uv)
    return bytes(out + g.trailer)


def to_obj(g: Gmdl) -> str:
    """Editable Wavefront OBJ using vecA xyz as position (HYPOTHESIS)."""
    L = ["v %.6f %.6f %.6f" % v[1][:3] for v in g.verts]
    L += ["vt %.6f %.6f" % (t[5][2 * c], 1 - t[5][2 * c + 1]) for t in g.tris for c in range(3)]
    L += ["f " + " ".join("%d/%d" % (t[c] + 1, 3 * n + c + 1) for c in range(3)) for n, t in enumerate(g.tris)]
    return "\n".join(L) + "\n"
