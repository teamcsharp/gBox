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


def build_body_manifest(nj_bytes: bytes, afs_entries: list[bytes], name: str, out_dir, source: dict | None = None,
                        tex_base: int = 0):
    """Reader stage: a textured, skinned uap.Manifest of one player .nj (e.g. plAbdy00.nj).

    ASSUMPTION (partial, not yet proven in game): NJ texture id ``t`` -> ``plAtex.afs`` entry ``tex_base + t``.  The
    Ep3 disc has no NJTL name list in these files, so the mapping is positional until the DOL table is read.
    Writes ``textures/tex<entry>.png`` under *out_dir*; returns (manifest, {texid: afs entry index}).
    """
    from pathlib import Path
    from . import ninja, pso_gc

    nj = load_nj(nj_bytes)
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    tex_files: list[str | None] = [None] * (max(nj.tris) + 1 if nj.tris else 0)
    used: dict[int, int] = {}
    for tid in sorted(nj.tris):
        i = tex_base + tid
        if i >= len(afs_entries):
            continue
        rel = f"textures/tex{i:03d}.png"
        (out / rel).write_bytes(pso_gc.png_bytes(pso_gc.gvr_decode(afs_entries[i])))
        tex_files[tid] = rel
        used[tid] = i
    src = {"game": "Phantasy Star Online Episode III - C.A.R.D. Revolution (USA) (GC)", "game_id": "5b5ecb4c36a13584",
           "extraction_method": "gbox.pso3_analysis", "texture_mapping": "positional (unverified)"}
    src.update(source or {})
    return ninja.to_manifest(nj, name, src, tex_files), used


def export_body_glb(nj_bytes: bytes, afs_entries: list[bytes], name: str, out_dir, source: dict | None = None):
    """Write manifest.json + textures + <name>.glb; returns (glb path, texid map, uap.validate problems)."""
    from pathlib import Path
    from . import uap

    out = Path(out_dir)
    m, used = build_body_manifest(nj_bytes, afs_entries, name, out, source)
    import hashlib
    m.unit_scale_m = 0.1
    m.provenance = [{"step": "gbox.pso3_analysis.export_body_glb", "model_sha256": hashlib.sha256(nj_bytes).hexdigest(),
                     "afs_entries": len(afs_entries), "texture_mapping": "positional texid -> plAtex.afs entry (unverified)"}]
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb, used, uap.validate(m, out)
