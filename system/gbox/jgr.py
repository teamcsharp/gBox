"""Jet Grind Radio / Jet Set Radio (Sega Dreamcast) disc + archive reader (foundation).

The Dreamcast build stores its player and enemy character data in AFS archives under JETRADIO/
(PLAYER.AFS, ENEMY.AFS, ...). An AFS here is the CRI AFS layout: "AFS\\0", a uint32 table length,
then that many uint32 offset entries followed by the same number of uint32 size entries. The offset
table alternates large offsets (the PLAY/PTEX model/texture chunks) and small offsets; the real
character data chunks are the ones whose first 4 bytes spell PLAY, PTEX or main.

A PLAY chunk is a JGR container (NOT a standard Ninja NJCM): "PLAY" + uint32 N + N*(uint32 value,
uint32 kind) descriptor records, then the sub-object data at those relative offsets. PTEX is the same
container shape for the character's PVR texture set; "main" is the shared skeleton/model container.

This module parses the archive and container headers. Full mesh/vertex decode is follow-up work
(see docs/jgr_re_findings.md); this reader gives the verified container plumbing every later step
needs, reusing the existing gbox.gdrom.GDRom for the ISO9660 filesystem.
"""
from __future__ import annotations

import struct

AFS_MAGIC = b"AFS\x00"
PLAY_MAGIC = b"PLAY"
PTEX_MAGIC = b"PTEX"
MAIN_MAGIC = b"main"

# The game_id of the owned disc (Jet Grind Radio (USA), dreamcast).
GAME_IDS = {"4187aeab4d67638c": "Jet Grind Radio (USA)"}

PLAYER_FILES = ["JETRADIO/PLAYER.AFS", "JETRADIO/ENEMY.AFS"]


def afs_entries(data: bytes) -> tuple[int, list[int], list[int]]:
    """Parse a Sega AFS archive. Returns (count, offsets, sizes) straight off the header tables."""
    if len(data) < 8 or data[:4] != AFS_MAGIC:
        raise ValueError(f"not an AFS archive (magic {data[:4]!r})")
    count = struct.unpack_from("<I", data, 4)[0]
    need = 8 + 8 * count
    if len(data) < need:
        raise ValueError(f"AFS header truncated: need {need} bytes, have {len(data)}")
    offsets = list(struct.unpack_from("<" + "I" * count, data, 8))
    sizes = list(struct.unpack_from("<" + "I" * count, data, 8 + 4 * count))
    return count, offsets, sizes


def chunks(data: bytes) -> list[tuple[str, int]]:
    """The model/texture chunks an AFS references, in table order: [(kind, offset), ...].

    kind is 'play' (model), 'ptex' (texture set) or 'main' (shared container).
    """
    _, offsets, _ = afs_entries(data)
    out: list[tuple[str, int]] = []
    for off in offsets:
        if off < 0 or off + 4 > len(data):
            continue
        m = data[off:off + 4]
        if m == PLAY_MAGIC:
            out.append(("play", off))
        elif m == PTEX_MAGIC:
            out.append(("ptex", off))
        elif m == MAIN_MAGIC:
            out.append(("main", off))
    return out


def container_header(data: bytes, off: int) -> tuple[bytes, list[tuple[int, int]]]:
    """Parse a PLAY/PTEX/main container header at an absolute offset.

    Returns (magic, [(value, kind), ...]) where each record is a uint32 pair describing a
    sub-object (value = relative offset/size field, kind = sub-object id). The count field
    immediately follows the 4-byte magic.
    """
    if off + 8 > len(data):
        raise ValueError(f"container at {off} truncated")
    magic = data[off:off + 4]
    if magic not in (PLAY_MAGIC, PTEX_MAGIC, MAIN_MAGIC):
        raise ValueError(f"not a JGR container at {off}: magic {magic!r}")
    n = struct.unpack_from("<I", data, off + 4)[0]
    recs: list[tuple[int, int]] = []
    for i in range(n):
        base = off + 8 + 8 * i
        if base + 8 > len(data):
            raise ValueError(f"container header at {off} truncated at record {i}")
        value, kind = struct.unpack_from("<II", data, base)
        recs.append((value, kind))
    return magic, recs


def inventory(gdi: str) -> dict[str, list[tuple[str, int]]]:
    """Open a JGR GD-ROM and inventory every PLAY/PTEX/main chunk in its character AFS archives.

    Returns {archive_path: [(kind, offset), ...]}. Read-only; never writes to the disc.
    """
    from .gdrom import GDRom
    disc = GDRom(gdi)
    out: dict[str, list[tuple[str, int]]] = {}
    for path in PLAYER_FILES:
        try:
            blob = disc.read(path)
        except KeyError:
            continue
        out[path] = chunks(blob)
    return out


# ---------------------------------------------------------------- sub-object mesh plumbing
MESH_TERMINATOR = struct.pack("<HH", 255, 0)  # short restart marker inside kind==1 records


def decode_submesh(segment: bytes, max_search: int = 0x400) -> tuple[list[int], list[tuple[float, float, float]]]:
    """Decode the first self-contained indexed triangle submesh in a kind==1 record.

    JGR ``PLAY`` records are not standard Ninja/Naomi formats. The layout observed in the
    smallest self-contained record is:

    * 0x30-byte shared record header
    * index short list from 0x40 up to the first ``0x00FF`` restart marker
    * float32 vertex block (XYZ, 12 bytes each) aligned to the next 16-byte boundary after
      the marker

    The function returns ``([], [])`` when no marker is found or when the index list refers
    to vertices that are not present locally (the larger JGR records share vertices across
    sub-objects; those need further reverse engineering).
    """
    marker: int | None = None
    for i in range(0x40, min(len(segment), max_search), 2):
        if segment[i:i + 2] == MESH_TERMINATOR[:2]:
            marker = i
            break
    if marker is None:
        return [], []
    idx_shorts = segment[0x40:marker]
    if not idx_shorts or len(idx_shorts) % 2:
        return [], []
    indices = list(struct.unpack("<" + str(len(idx_shorts) // 2) + "H", idx_shorts))

    # Vertex block starts after a 4-byte marker plus padding to 16-byte alignment.
    vstart = (marker + 4 + 15) & ~15
    verts: list[tuple[float, float, float]] = []
    for k in range(2048):
        off = vstart + 12 * k
        if off + 12 > len(segment):
            break
        x, y, z = struct.unpack("<3f", segment[off:off + 12])
        total = abs(x) + abs(y) + abs(z)
        if 0.001 < total < 1000.0:
            verts.append((x, y, z))
        else:
            break
    if not verts or (indices and max(indices) >= len(verts)):
        return [], []
    return indices, verts


def play_subobjects(data: bytes, play_off: int, afs_size: int | None = None) -> list[dict]:
    """Return every sub-record inside a PLAY chunk as a dict.

    The PLAY container records are not guaranteed to appear in address order, but the
    ``value`` field is a relative offset from the start of the PLAY chunk and the records
    form one contiguous block (each record ends where the next one begins). We therefore
    sort records by ``value`` before slicing.

    Each returned dict has ``kind``, ``offset`` (absolute), ``relative`` (offset inside the
    PLAY chunk), ``length``, and ``bytes``. When ``afs_size`` is supplied it bounds the last
    record; otherwise the end of ``data`` is used.
    """
    magic, recs = container_header(data, play_off)
    sorted_recs = sorted(enumerate(recs), key=lambda item: item[1][0])
    out: list[dict] = []
    for j, (value, kind) in sorted_recs:
        off = play_off + value
        # Find the next record in sorted address order.
        idx = next((i for i, (_, (rv, _)) in enumerate(sorted_recs) if rv == value), -1)
        if idx + 1 < len(sorted_recs):
            end = play_off + sorted_recs[idx + 1][1][0]
        elif afs_size is not None:
            end = play_off + afs_size
        else:
            end = len(data)
        out.append({
            "index": j,
            "kind": kind,
            "offset": off,
            "relative": value,
            "length": end - off,
            "bytes": data[off:end],
        })
    return out


def split_submeshes(segment: bytes) -> list[bytes]:
    """Split a kind==1 mesh record on its short restart markers (0x00FF,0x0000).

    The first submesh has no leading 4-short header; every subsequent submesh is prefixed by
    ``[vcount?, icount?, ?, ?]`` and the terminator that preceded it. Returns the raw bytes of
    each submesh so higher-level decoders can interpret indices/vertices without inventing layouts.
    """
    if len(segment) < 0x30:
        return []
    # The 0x30-byte record header is shared; actual submesh data follows at 0x40.
    out = []
    i = 0x40
    start = i
    while i + 4 <= len(segment):
        if segment[i:i + 4] == MESH_TERMINATOR + b"\x00\x00":
            out.append(segment[start:i])
            start = i + 4
            i += 4
        else:
            i += 2
    if start < len(segment):
        out.append(segment[start:])
    return out
