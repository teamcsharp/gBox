"""Turok: Rage Wars (Europe NRWP) -- bounded GraphicObject 174 geometry probe.

Evidence-only analysis of the RNC parts inside GraphicObject 174's Geometry
block (see gbox.turok_rw_eu_inventory.target_asset for ROM offsets).  The
Dinosaur Hunter parser (gbox.turok_analysis.parse_geometry) does NOT apply:
every Rage Wars part is a 6-block CIndexedSet, not a 2-block geometry set.

PROVED by byte inspection of the owned Europe image (structure only):
  [0] CUnindexedSet {u32 recsize=16, u32 count} of 16-byte Vtx records.  The
      records are INTERLEAVED (s16 x,y,z first); the planar-by-byte layout
      used by Dinosaur Hunter gives out-of-range coordinates here.
  [1] empty unindexed set (8 bytes, count 0)
  [2] CIndexedSet of sections; each section is a CIndexedSet of 2 blocks:
      a 24-byte header and a raw u16 stream.
  [3],[4] small sets whose meaning is unproved (preserved verbatim)
  [5] CUnindexedSet {recsize=0x70, count=22}: byte-identical in all 37 parts

HYPOTHESES (not proved; do not build a writer on them without a loader
trace): the 24-byte section header is u32 unknown + the 20-byte CROMSection
(texset, matflags, RGBA, black, multU, multV); the u16 stream is a
triangle/cache command stream whose cache semantics differ from Dinosaur
Hunter; block [5] is a 22-node bone/pose table; the 16 large parts are
full-body variants and the 21 small ones are one-section accessories.
"""
from __future__ import annotations

import hashlib
import struct

from gbox.turok_inventory import decode_rnc, parse_indexed

PART_BLOCKS = 6
VTX_SIZE = 16


def _sub(blob: bytes):
    try:
        return parse_indexed(blob, 0)
    except Exception:  # not an indexed set
        return None


def parse_part(blob: bytes) -> dict:
    """Decode one decompressed Rage Wars geometry part; unknowns preserved."""
    blocks = _sub(blob)
    if blocks is None or len(blocks) != PART_BLOCKS:
        raise ValueError(f"part is not a {PART_BLOCKS}-block indexed set")
    raw = [blob[o:o + s] for o, s in blocks]
    rec, count = struct.unpack_from(">II", raw[0], 0)
    if rec != VTX_SIZE or len(raw[0]) != 8 + rec * count:
        raise ValueError(f"vertex block {rec}x{count} does not fit {len(raw[0])}B")
    verts = [struct.unpack_from(">3h", raw[0], 8 + i * VTX_SIZE)
             for i in range(count)]
    bbox = [(min(c), max(c)) for c in zip(*verts)] if verts else []
    sections = []
    for sb in (_sub(raw[2]) or []):
        sec_blob = raw[2][sb[0]:sb[0] + sb[1]]
        pair = _sub(sec_blob)
        if pair is None or len(pair) != 2:
            raise ValueError("section is not a 2-block set")
        head = sec_blob[pair[0][0]:pair[0][0] + pair[0][1]]
        stream = sec_blob[pair[1][0]:pair[1][0] + pair[1][1]]
        if len(head) != 24 or len(stream) % 2:
            raise ValueError(f"section header {len(head)}B / stream {len(stream)}B")
        unk, texset, matflags = struct.unpack_from(">III", head, 0)
        sections.append({
            "header_hex": head.hex(), "u32_unknown": unk, "texset": texset,
            "matflags": matflags, "color_rgba": head[12:16].hex(),
            "black_rgba": head[16:20].hex(),
            "mult_u": struct.unpack_from(">H", head, 20)[0],
            "mult_v": struct.unpack_from(">H", head, 22)[0],
            "stream_words": len(stream) // 2,
            "stream_sha256": hashlib.sha256(stream).hexdigest(),
        })
    return {
        "n_vertices": count, "bbox": bbox, "sections": sections,
        "block_sizes": [len(b) for b in raw],
        "block1_hex": raw[1].hex(), "block3_len": len(raw[3]),
        "block4_hex": raw[4].hex(),
        "block5_sha256": hashlib.sha256(raw[5]).hexdigest(),
        "block5_record": struct.unpack_from(">II", raw[5], 0),
    }


def probe(rom: bytes, index: int = 174) -> dict:
    """Probe every geometry part of one GraphicObject of a normalised ROM."""
    from gbox import turok_rw_eu_inventory as eu
    asset = eu.target_asset(rom, index)
    parts = []
    for p in asset["parts"]:
        blob = rom[p["rom"]:p["rom"] + p["packed_size"]]
        dec = decode_rnc(blob) if blob[:3] == b"RNC" else blob
        rec = parse_part(dec)
        rec.update(i=p["i"], rom=p["rom"], unpacked_sha256=hashlib.sha256(dec).hexdigest())
        parts.append(rec)
    return {"index": index, "geometry_sha1": asset["geometry_sha1"],
            "n_parts": len(parts),
            "large": [p["i"] for p in parts if len(p["sections"]) > 1],
            "small": [p["i"] for p in parts if len(p["sections"]) == 1],
            "block5_distinct": sorted({p["block5_sha256"] for p in parts}),
            "parts": parts}
