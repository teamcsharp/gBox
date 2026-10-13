"""Sega Ninja (NJ) chunk models, one import point for every Ninja-engine title (PSO, SA1/SA2, JGR, Time Stalkers,
Sonic Shuffle, Illbleed, Crazy Taxi 2 neighbours). The code lives in gbox.ninja (decode + chunk writer) and
gbox.ninja_swap (donor fit onto a Ninja tree); this module names it by role so a new title starts from here.

  decode   NJ (NJCM/NJTL/POF0 file -> nodes, weighted chunk vertices, strips), njtl, tree_nodes, tree_ranges,
           chunk_list_len, bml (PRS'd BML archives), pvm / pvr_decode (textures)
  encode   cnk_model_lists (vertex + strip chunk lists), write_tree (NJS_OBJECT tree), pof0 (pointer fixup list),
           pvr_vq / pvr_twiddled / pvr_like / pvm_replace (textures), prs_compress
  writer   target_from_nj (role map -> retarget target), fit (donor GLB -> per-node chunk models)

Chunk ids (Ninja SDK): 0 null, 1-5 bits (blend/mipmap/specular/cache/draw-polygon list), 8-9 tiny (texture), 16-31
material, 32-50 vertex (VN/VC/D8/N32/UF...), 56-58 volume, 64-75 strip (S/UVN/UVH/VN/D8 variants), 255 end.
"""
from __future__ import annotations

import importlib

CHUNK_TYPES = {"null": (0, 0), "bits": (1, 5), "tiny": (8, 9), "material": (16, 31), "vertex": (32, 50),
               "volume": (56, 58), "strip": (64, 75), "end": (255, 255)}

_EXPORTS = {
    **{n: "ninja" for n in ("NJ", "njtl", "tree_nodes", "tree_ranges", "chunk_list_len", "bml", "pvm", "pvr_decode",
                             "cnk_model_lists", "write_tree", "pof0", "pvr_vq", "pvr_twiddled", "pvr_like",
                             "pvm_replace", "pvm_entry_gbix", "to_manifest", "prs_compress", "prs_decompress")},
    **{n: "ninja_swap" for n in ("target_from_nj", "fit", "split_nodes")},
}


def chunk_kind(cid: int) -> str:
    """Chunk id -> its family name ('unknown' outside the SDK ranges)."""
    return next((k for k, (lo, hi) in CHUNK_TYPES.items() if lo <= cid <= hi), "unknown")


def __getattr__(name: str):
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(f"gbox.{mod}"), name)


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
