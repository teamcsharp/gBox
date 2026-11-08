"""A donor BIN from any extracted .glb: the collection becomes usable by every title's transfer.

`band_affine` needs a donor `Bin`. Extracted models are .glb files, and their geometry is a triangle soup in the bind pose - which is
exactly enough: the transfer bands the donor by height when it has no weights, so a soup is a valid donor.

The BIN is built against a template because the format wants a header and a material table; the template's own geometry is replaced
entirely by the donor's, so the result is the donor's shape in a BIN container.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import characters
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

TEMPLATE_PACK = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"),
                             "010099A00BC1E000/bio4/em/em16.udas")


def soup(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Every triangle of a .glb as (positions (3N,3), indices (N,3)) in the bind pose."""
    triples = characters._triangles(path)
    points = np.concatenate([np.asarray(points, np.float64).reshape(-1, 3) if np.asarray(points).ndim == 3
                             else np.asarray(points, np.float64).reshape(-1, 3) for points, _uv, _tex, _col in triples])
    # `_triangles` yields per-triangle records; a flat corner list with sequential indices is a valid mesh for a donor
    tris = np.arange(len(points), dtype=np.int64).reshape(-1, 3)
    return points, tris


def donor_bin(glb: str, template_pack: str = TEMPLATE_PACK) -> bytes:
    """A BIN whose geometry is the .glb's, using a real pack's slot as the container template."""
    data = open(template_pack, "rb").read()
    slot = INV.bin_slots(data, endian="<")[0]
    template = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
    points, tris = soup(glb)
    return R.bin_from(template, pos=points.astype(np.float32), tris=tris.astype(np.uint16))


if __name__ == "__main__":
    glb = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/donor.bin"
    blob = donor_bin(glb)
    open(out, "wb").write(blob)
    mesh = R.bin_read(blob)
    print(f"{glb} -> {out}: {len(blob)} bytes, {len(mesh.pos)} vertices, {len(mesh.tris)} triangles, "
          f"{len(mesh.mats)} material records")
