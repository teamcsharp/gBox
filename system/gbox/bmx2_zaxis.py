"""Native reader for the Z-Axis chunked containers of Dave Mirra Freestyle BMX 2 (PS2).

The PS2 release (SLUS-20159) keeps rider models in ``.ZIT`` files, rider
animation in ``.ZAD`` files and shared assets in ``.ZAL`` archives.  All of
them are IFF-like: a 4 byte ASCII tag, a little endian ``u32`` payload size
and the payload, with no padding between chunks.

A rider model carries a chunked mesh.  ``TGPT`` groups a ``TGPH`` header, a
``MOBO`` bone table and the vertex streams ``TGVP`` (positions), ``TGVN``
(normals), ``TGVU`` (uvs) and ``TGVC`` (colours), plus the index stream
``TGVI`` and the face streams ``TGFP``/``TGFN``/``TGFM``.  Real files are wrapped ``FMDL > MODL > {TXRC.., TGEO > TGPT.., TGIN}``.  TGVI is NOT a\nplain triangle list in the real files (max index exceeds the vertex count), so only\nthe container structure and vertex/bone counts are decoded; faces are still open.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

HEADER = 8
MOBO_RECORD = 52
MOBO_NAME_OFFSET = 28
TGPH_BONES_OFFSET = 8
TGPH_NAMED_OFFSET = 12
CONTAINER_TAGS = frozenset({"FMDL", "MODL", "TGEO", "TGPT"})
KNOWN_TAGS = frozenset({
    "FMDL", "MODL", "TGIN", "TGTD", "TGFR", "TXRC", "TXRH", "TBMP", "TGEO", "TGPT", "TMTB", "TGIH", "TGLO", "TGHD",
    "TGPH", "MOBO", "TGVP", "TGVN", "TGVC", "TGVU", "TGVI", "TGPB", "TGFP",
    "TGFN", "TGFM", "MATI", "BM8",
})


def _is_tag(raw: bytes) -> bool:
    return len(raw) == 4 and all(32 <= c < 127 for c in raw)


@dataclass
class Chunk:
    """One IFF chunk: tag, offset of the tag, payload size, payload bytes."""

    tag: str
    offset: int
    size: int
    payload: bytes


def walk(data: bytes, start: int = 0) -> List[Chunk]:
    """Walk chunk headers from ``start``; stops at the first implausible header."""
    out: List[Chunk] = []
    off = start
    while off + HEADER <= len(data):
        tag = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        if not _is_tag(tag) or size > len(data) - off - HEADER:
            break
        out.append(Chunk(tag.decode("latin-1"), off, size, data[off + HEADER:off + HEADER + size]))
        off += HEADER + size
    return out


def top_chunks(data: bytes) -> List[Chunk]:
    """Top level chunks, tolerating a short file header before the first tag."""
    best: List[Chunk] = []
    for start in (0, 24):
        found = walk(data, start)
        if sum(c.size for c in found) > sum(c.size for c in best):
            best = found
    return best


def deep_chunks(data: bytes, depth: int = 0) -> List[Chunk]:
    """Top level chunks plus the chunks nested in container tags (TGEO/TGPT)."""
    out: List[Chunk] = []
    for chunk in top_chunks(data):
        out.append(chunk)
        if chunk.tag in CONTAINER_TAGS and depth < 4:
            out.extend(deep_chunks(chunk.payload, depth + 1))
    return out


def find(data: bytes, tag: str) -> Optional[Chunk]:
    for chunk in deep_chunks(data):
        if chunk.tag == tag:
            return chunk
    for chunk in top_chunks(data):
        if chunk.tag == tag:
            return chunk
    return None


def parse_txrh(payload: bytes) -> Dict[str, object]:
    """``TXRH`` texture resource header: magic, width, height, level name."""
    out: Dict[str, object] = {"magic": struct.unpack_from("<I", payload, 0)[0]}
    if len(payload) >= 8:
        out["width"], out["height"] = struct.unpack_from("<HH", payload, 4)
    match = re.search(rb"[ -~]{3,}\x00", payload[16:])
    out["name"] = match.group()[:-1].decode("latin-1", "replace").strip() if match else ""
    return out


def parse_tgph(payload: bytes) -> Dict[str, int]:
    """``TGPH`` mesh header: the skeleton size and the named bone count."""
    head: Dict[str, int] = {
        "flags": struct.unpack_from("<I", payload, 0)[0],
        "tag": struct.unpack_from("<I", payload, 4)[0],
    }
    if len(payload) >= 18:
        head["bone_count"] = struct.unpack_from("<H", payload, TGPH_BONES_OFFSET)[0]
        head["named_bones"] = struct.unpack_from("<H", payload, TGPH_NAMED_OFFSET)[0]
        head["flags2"] = struct.unpack_from("<H", payload, TGPH_NAMED_OFFSET + 2)[0]
        head["streams"] = struct.unpack_from("<H", payload, TGPH_NAMED_OFFSET + 4)[0]
    return head


def parse_mobo(payload: bytes) -> List[str]:
    """Bone names from the ``MOBO`` object table (52 byte records, name at +28)."""
    names: List[str] = []
    for index in range(len(payload) // MOBO_RECORD):
        base = index * MOBO_RECORD
        raw = payload[base + MOBO_NAME_OFFSET:base + MOBO_RECORD]
        name = raw.split(b"\x00")[0].decode("latin-1", "replace")
        if name:
            names.append(name)
    return names


def parse_tgvi(payload: bytes) -> List[int]:
    """Triangle indices (16 bit, three per triangle)."""
    count = len(payload) // 2
    return list(struct.unpack_from("<%dH" % count, payload, 0))


def list_members(data: bytes) -> List[Tuple[str, int, int]]:
    """Archive members as ``(tag, offset, size)`` tuples."""
    return [(c.tag, c.offset, c.size) for c in top_chunks(data)]


def archive_members(data: bytes) -> List[str]:
    """Member names of a ``.ZAL`` archive, taken from its ``ZDIR`` index."""
    index = find(data, "ZDIR")
    if index is None:
        return []
    names = [m.group().decode("latin-1")
             for m in re.finditer(rb"[A-Za-z0-9_./\\-]{4,120}\.[A-Za-z0-9]{2,4}", index.payload)]
    seen: List[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def part_keys(part: Dict[str, object]) -> List[str]:
    return ["TGVI"] if "index_words" in part else []


def mesh_summary(data: bytes) -> Dict[str, object]:
    """Summarise the rider mesh held in a ``.ZIT``/``.ZAL`` container."""
    out: Dict[str, object] = {"chunks": [c.tag for c in top_chunks(data)]}
    header = find(data, "TXRH")
    if header is not None:
        out["texture"] = parse_txrh(header.payload)
    parts: List[Dict[str, object]] = []
    for chunk in deep_chunks(data):
        if chunk.tag != "TGPT":
            continue
        part: Dict[str, object] = {}
        sub = {c.tag: c for c in walk(chunk.payload, 0)}
        if "TGPH" in sub:
            part["header"] = parse_tgph(sub["TGPH"].payload)
        if "MOBO" in sub:
            part["bones"] = parse_mobo(sub["MOBO"].payload)
        for stream in ("TGVP", "TGVN", "TGVU", "TGVC"):
            if stream in sub:
                part[stream] = sub[stream].size
        if "TGVI" in sub:
            indices = parse_tgvi(sub["TGVI"].payload)
            part["index_words"] = len(indices)
            part["max_index"] = max(indices) if indices else 0
        if "TGVP" in sub:
            part["vertices"] = sub["TGVP"].size // 12
        if "TGVI" in part_keys(part) and "vertices" in part:
            part["tgvi_is_plain_triangle_list"] = (
                part["index_words"] % 3 == 0 and part["max_index"] < part["vertices"])
        parts.append(part)
    out["parts"] = parts
    if parts:
        first = parts[0]
        out["vertices"] = first.get("vertices")
        out["index_words"] = first.get("index_words")
        out["bone_count"] = (first.get("header") or {}).get("bone_count")
        out["bone_names"] = first.get("bones")
    info = find(data, "TGIH")
    if info is not None:
        out["object_names"] = [m.group().decode("latin-1")
                               for m in re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{3,63}", info.payload)]
    return out
