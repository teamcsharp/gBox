"""Turok: Dinosaur Hunter (NTUE Rev B) — native asset reader (reader stage).

Exports one CGraphicObject's geometry (node hierarchy, parts, sections,
vertices, triangles), its texture-set references and the texture-set metadata
from the verified inventory to OBJ + JSON.

Verified against the owned NTUE Rev B build:
  zip  sha256 3b5df8341a02abc3216adc30d706debead51c307e0d61f2960c0402a69c6808f
  n64  sha256 d8c87aef86400ef8891d1933224d7b06bdebe688bb99a6923481db2a0d3ab31e
  z64  sha256 3f46508afd36173886f8a6ea65066663c431be9e1edb8d299356569d87e48bab

The ROM image is never modified; the reader only reads it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from gbox import turok_analysis as ta
from gbox import turok_inventory as ti

ROM_SHA256_Z64 = (
    "3f46508afd36173886f8a6ea65066663c431be9e1edb8d299356569d87e48bab"
)

# UV derivation is a HYPOTHESIS until the cart loader xref is proven: the
# CROM section carries a texture scale (mult_u/mult_v) and the vertex texture
# coordinate is an s16 stage coordinate.
NO_TEXSET = 0xFFFFFFFF  # CROM section with no texture set

UV_STAGE = 32768.0
UV_MULT_REF = 8192.0


def _texset_id(sec: dict):
    """Texture-set index of a section, or None when the CROM has no texture."""
    t = sec.get("info", {}).get("texset")
    return None if t is None or int(t) == NO_TEXSET else int(t)


def _uv(tc: int, mult: int) -> float:
    return (float(tc) / UV_STAGE) * (float(mult) / UV_MULT_REF)


def _texset_map(inv: dict) -> dict:
    out = {}
    for s in inv.get("texture_sets", {}).get("sets", []):
        out[s.get("i")] = s
    return out


def build_obj(geom: dict, source_sha256: str | None = None) -> str:
    """Render a decoded geometry tree as Wavefront OBJ text.

    Pure function: no ROM access, so it can be tested on synthetic fixtures.
    """
    lines = []
    if source_sha256:
        lines.append(f"# source rom sha256 {source_sha256}")
    v_base = 1
    for ni, node in enumerate(geom.get("nodes", [])):
        for pi, part in enumerate(node.get("parts") or []):
            for si, sec in enumerate(part.get("sections") or []):
                info = sec.get("info", {})
                texset = info.get("texset")
                verts = sec.get("vertices") or []
                tris = sec.get("triangles") or []
                lines.append(
                    f"# node {ni} part {pi} section {si} texset {texset} "
                    f"matflags {info.get('matflags')} verts {len(verts)} tris {len(tris)}"
                )
                lines.append(f"g node_{ni}_part_{pi}_section_{si}")
                lines.append(f"usemtl mat_tex{texset if texset is not None else 'none'}")
                mu = info.get("mult_u") or 0
                mv = info.get("mult_v") or 0
                for v in verts:
                    lines.append(f"v {float(v[0])} {float(v[1])} {float(v[2])}")
                    tu = v[4] if len(v) > 4 else 0
                    tv = v[5] if len(v) > 5 else 0
                    lines.append(f"vt {_uv(tu, mu):.6f} {1.0 - _uv(tv, mv):.6f}")
                for t in tris:
                    a, b, c = int(t[0]), int(t[1]), int(t[2])
                    lines.append(
                        f"f {v_base + a}/{v_base + a} {v_base + b}/{v_base + b} "
                        f"{v_base + c}/{v_base + c}"
                    )
                v_base += len(verts)
    return "\n".join(lines) + "\n"


def build_mtl(geom: dict) -> str:
    lines = ["# Turok NTUE Rev B materials"]
    seen = set()
    for node in geom.get("nodes", []):
        for part in node.get("parts") or []:
            for sec in part.get("sections") or []:
                texset = _texset_id(sec)
                if texset in seen:
                    continue
                seen.add(texset)
                lines.append(f"newmtl mat_tex{texset if texset is not None else 'none'}")
                lines.append("Ka 1.000 1.000 1.000")
                lines.append("Kd 1.000 1.000 1.000")
                lines.append("")
    return "\n".join(lines) + "\n"


def summarize(res: dict, inv: dict, index: int, source_sha256: str) -> dict:
    geom = res.get("geometry", {})
    tsets = _texset_map(inv)
    sections = []
    total_v = total_t = 0
    for ni, node in enumerate(geom.get("nodes", [])):
        for pi, part in enumerate(node.get("parts") or []):
            for si, sec in enumerate(part.get("sections") or []):
                info = sec.get("info", {})
                tris = sec.get("triangles") or []
                nv = len(sec.get("vertices") or [])
                max_idx = max((max(int(t[0]), int(t[1]), int(t[2])) for t in tris), default=-1)
                meta = tsets.get(_texset_id(sec), {})
                sections.append({
                    "node": ni, "part": pi, "section": si,
                    "texset": _texset_id(sec),
                    "texset_format": meta.get("format"),
                    "texset_bitmaps": meta.get("bitmaps"),
                    "texset_palettes": meta.get("palettes"),
                    "matflags": info.get("matflags"),
                    "mult_u": info.get("mult_u"),
                    "mult_v": info.get("mult_v"),
                    "n_vertices": nv,
                    "n_triangles": len(tris),
                    "triangle_max_index": max_idx,
                })
                total_v += nv
                total_t += len(tris)
    return {
        "object": index,
        "source_rom_sha256": source_sha256,
        "n_nodes": len(geom.get("nodes", [])),
        "node_tree": [
            {"node": ni, "child_node_indices": node.get("child_node_indices", []),
             "part_indices": node.get("part_indices", [])}
            for ni, node in enumerate(geom.get("nodes", []))
        ],
        "total_vertices": total_v,
        "total_triangles": total_t,
        "texture_sets": sorted({s["texset"] for s in sections if s["texset"] is not None}),
        "sections": sections,
        "anim_error": res.get("anim_error"),
    }


def export_object(rom: bytes, inv: dict, index: int, out_dir: Path) -> dict:
    obj = inv["graphic_objects"]["objects"][index]
    res = ta.decode_object(rom, obj)
    geom = res.get("geometry", {})
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(rom).hexdigest()
    obj_path = out_dir / f"object_{index}.obj"
    mtl_path = out_dir / f"object_{index}.mtl"
    obj_path.write_text(build_obj(geom, sha))
    mtl_path.write_text(build_mtl(geom))
    summary = summarize(res, inv, index, sha)
    summary["obj_file"] = obj_path.name
    summary["mtl_file"] = mtl_path.name
    sp = out_dir / f"object_{index}_summary.json"
    sp.write_text(json.dumps(summary, indent=2) + "\n")
    summary["summary_file"] = sp.name
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Turok NTUE Rev B native asset reader")
    ap.add_argument("rom", help="path to rom.z64 (read-only)")
    ap.add_argument("--object", type=int, default=64)
    ap.add_argument("--out", default="turok_export")
    ap.add_argument("--list", action="store_true", help="list object node/section counts")
    args = ap.parse_args(argv)

    rom = Path(args.rom).read_bytes()
    sha = hashlib.sha256(rom).hexdigest()
    print(f"ROM {args.rom} sha256 {sha}")
    if sha != ROM_SHA256_Z64:
        print(f"WARNING: expected {ROM_SHA256_Z64}")
    inv = ti.inventory(rom)
    if args.list:
        for o in inv["graphic_objects"]["objects"][:200]:
            print(o["i"], o)
        return 0
    summary = export_object(rom, inv, args.object, Path(args.out))
    print(json.dumps({k: v for k, v in summary.items() if k != "sections"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
