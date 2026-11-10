"""Format probe for PSO Episode III (GPSE8P) player models (request #2422, analysis stage).

Finding verified on the owned disc: ``pl*.nj`` files are *mixed endian*: the ``NJCM`` chunk size at +4 is
little-endian (as in the PSO Dreamcast/PC files) but the NJS_OBJECT/NJCM_MODEL/chunk body is BIG-endian
(GameCube).  ``gbox.ninja.NJ(be=True)`` would also read the size big-endian, so the size field is byte-swapped
first.  The NJCM body is followed by a POF0 pointer table.  ``plAtex.afs`` entries are GBIX+GVRT (GameCube GVR)
textures of mixed sizes (not all 8224 bytes).
"""
from __future__ import annotations

import struct

from .ninja import NJ, tree_nodes, tree_ranges


def njcm_body(data: bytes) -> bytes:
    """NJCM body of a GameCube player .nj (LE size, BE body); raises ValueError on a malformed header."""
    if data[:4] != b"NJCM":
        raise ValueError("no NJCM magic")
    size = struct.unpack_from("<I", data, 4)[0]
    if size + 8 > len(data):
        raise ValueError("NJCM size beyond file")
    return data[8:8 + size]


def load_nj(data: bytes) -> NJ:
    """Decode a GameCube player .nj with the shared Ninja chunk decoder."""
    body = njcm_body(data)
    return NJ(b"NJCM" + struct.pack("<I", len(body)) + body, be=True)


def analyze_nj(data: bytes) -> dict:
    body = njcm_body(data)
    nj = load_nj(data)
    ranges = tree_ranges(body, 0, ">")
    covered = len(set(i for a, b in ranges for i in range(a, b)))
    return {
        "body_size": len(body), "trailer_size": len(data) - 8 - len(body),
        "bones": len(nj.bones), "tree_nodes": len(tree_nodes(body, 0, ">")),
        "vertices": len(nj.vbuf), "triangles": sum(len(v) for v in nj.tris.values()),
        "triangles_by_texid": {k: len(v) for k, v in sorted(nj.tris.items())},
        "bytes_covered": covered,
    }


def parse_gvr_header(blob: bytes) -> dict:
    """GBIX (+8 = global index, big-endian) / GVRT header of an AFS texture entry."""
    if blob[:4] != b"GBIX" or blob[16:20] != b"GVRT":
        raise ValueError("not GBIX/GVRT")
    w, h = struct.unpack_from(">HH", blob, 0x1C)
    return {"gbix": struct.unpack_from(">I", blob, 8)[0], "data_format": blob[0x1B], "width": w, "height": h}
