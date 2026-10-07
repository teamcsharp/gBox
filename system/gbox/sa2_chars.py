"""Sonic Adventure 2 (Dreamcast, US) character models -> UAP / glTF (skinned Ninja chunk model + PVM textures).

SONIC2/<CHAR>MDL.PRS (e.g. SONICMDL.PRS) decompresses (PRS, gbox.ninja) to a little-endian table of
{s32 id, u32 NJS_OBJECT offset} ended by id -1; every pointer inside is a file offset. Id 0 is the full in-game model
(Sonic: 62 nodes, ~1370 triangles, weighted chunk vertices), 1..3 / 31.. / 48.. are lower detail versions and parts.
SONIC2/<CHAR>TEX.PRS decompresses to the PVM whose order matches the model's Ninja texture ids.
"""
from __future__ import annotations

import struct
from pathlib import Path

from . import ninja, uap

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def mdl_table(data: bytes) -> dict[int, int]:
    out, o = {}, 0
    while True:
        i, p = struct.unpack_from("<iI", data, o)
        o += 8
        if i == -1:
            return out
        out[i] = p


# SA2 characters face -X with +Y up; this turns them to face +Z (RE4 Leon, glTF viewers): (x, y, z) -> (z, y, -x)
FACE_Z = [[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, 0, 0, 1]]


def load_object(data: bytes, off: int, be: bool = False, root=IDENTITY) -> ninja.NJ:
    """Walk an NJS_OBJECT tree at a file offset. root = a matrix applied to the whole model (folded into the root
    bone, so the skeleton and the bind-pose vertices stay consistent)."""
    nj = ninja.NJ.__new__(ninja.NJ)
    nj.e, nj.d, nj.bones, nj.vbuf, nj.tris, nj.tex, nj.plcache = (">" if be else "<"), data, [], {}, {}, 0, {}
    nj._walk(off, None, root)
    for b in nj.bones:
        if b["parent"] is None:                            # root bones: local = world (includes `root`)
            b["t"], b["r"] = [b["m"][0][3], b["m"][1][3], b["m"][2][3]], ninja._quat(b["m"])
    return nj


def export(gdi: str, out_dir: str, char: str = "SONIC", model_id: int = 0) -> Path:
    from .gdrom import GDRom
    disc = GDRom(gdi)
    mdl = ninja.prs_decompress(disc.read(f"SONIC2/{char}MDL.PRS"))
    tex = ninja.prs_decompress(disc.read(f"SONIC2/{char}TEX.PRS"))
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    files = []
    for name, chunk in ninja.pvm(tex):
        try:
            w, h, rgba, _ = ninja.pvr_decode(chunk)
            (out / "textures" / f"{name}.png").write_bytes(ninja.png(w, h, rgba))
            files.append(f"textures/{name}.png")
        except ValueError:
            files.append(None)
    nj = load_object(mdl, mdl_table(mdl)[model_id], root=FACE_Z)
    name = f"sa2_{char.lower()}_{model_id}"
    m = ninja.to_manifest(nj, name, {"game": "Sonic Adventure 2 (DC, US)", "files": [f"SONIC2/{char}MDL.PRS",
                                     f"SONIC2/{char}TEX.PRS"], "model_id": model_id,
                                     "extraction_method": "gbox.sa2_chars"}, files)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--char", default="SONIC")
    ap.add_argument("--model", type=int, default=0)
    a = ap.parse_args()
    print(export(a.gdi, a.out, a.char, a.model))
