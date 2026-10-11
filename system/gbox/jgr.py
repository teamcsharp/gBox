"""Jet Grind Radio / Jet Set Radio (Sega Dreamcast) disc + archive reader (foundation).

The Dreamcast build stores its player and enemy character data in AFS archives under JETRADIO/
(PLAYER.AFS, ENEMY.AFS, ...). An AFS here is the standard CRI AFS layout: "AFS\\0", a uint32 entry
count, then that many interleaved (uint32 offset, uint32 size) pairs. On the owned USA disc PLAYER.AFS
holds 34 entries: 16 (PLAY model, PTEX texture set) pairs, one shared "main" container and one EFTX
effect-texture set. Each entry's size is exact (the next entry starts at the following 0x800 boundary).

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
EFTX_MAGIC = b"EFTX"

# The game_id of the owned disc (Jet Grind Radio (USA), dreamcast).
GAME_IDS = {"4187aeab4d67638c": "Jet Grind Radio (USA)"}

PLAYER_FILES = ["JETRADIO/PLAYER.AFS", "JETRADIO/ENEMY.AFS"]


def afs_entries(data: bytes) -> tuple[int, list[int], list[int]]:
    """Parse a Sega AFS archive. Returns (count, offsets, sizes).

    The table is ``count`` interleaved (offset, size) uint32 pairs straight after the 8-byte header.
    """
    if len(data) < 8 or data[:4] != AFS_MAGIC:
        raise ValueError(f"not an AFS archive (magic {data[:4]!r})")
    count = struct.unpack_from("<I", data, 4)[0]
    need = 8 + 8 * count
    if len(data) < need:
        raise ValueError(f"AFS header truncated: need {need} bytes, have {len(data)}")
    pairs = struct.unpack_from("<" + "I" * (2 * count), data, 8)
    return count, list(pairs[0::2]), list(pairs[1::2])


_CHUNK_KINDS = {PLAY_MAGIC: "play", PTEX_MAGIC: "ptex", MAIN_MAGIC: "main", EFTX_MAGIC: "eftx"}


def chunks(data: bytes) -> list[tuple[str, int]]:
    """The model/texture chunks an AFS references, in table order: [(kind, offset), ...].

    kind is 'play' (model), 'ptex' (texture set), 'main' (shared container) or 'eftx' (effect
    textures). Entries with any other leading magic are skipped.
    """
    _, offsets, _ = afs_entries(data)
    out: list[tuple[str, int]] = []
    for off in offsets:
        if off < 0 or off + 4 > len(data):
            continue
        kind = _CHUNK_KINDS.get(bytes(data[off:off + 4]))
        if kind:
            out.append((kind, off))
    return out


def entry_size(data: bytes, off: int) -> int:
    """Exact byte size of the AFS entry starting at absolute offset ``off``."""
    _, offsets, sizes = afs_entries(data)
    return sizes[offsets.index(off)]


def container_header(data: bytes, off: int) -> tuple[bytes, list[tuple[int, int]]]:
    """Parse a PLAY/PTEX/main container header at an absolute offset.

    Returns (magic, [(value, kind), ...]) where each record is a uint32 pair describing a
    sub-object (value = relative offset/size field, kind = sub-object id). The count field
    immediately follows the 4-byte magic.
    """
    if off + 8 > len(data):
        raise ValueError(f"container at {off} truncated")
    magic = data[off:off + 4]
    if magic not in _CHUNK_KINDS:
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


# ---------------------------------------------------------------- PTEX texture sets
def ptex_textures(data: bytes, ptex_off: int, size: int | None = None) -> list[dict]:
    """Every GBIX+PVRT texture inside a PTEX (or EFTX) chunk, in file order.

    The PTEX header table is followed (at the first GBIX) by back-to-back Dreamcast PVR textures,
    each ``GBIX`` (global index) + ``PVRT`` chunk, 4-byte aligned, zero padded to the entry end. The
    walk stops at the entry end or at the first non-GBIX data. Each dict has ``offset`` (relative
    to the chunk), ``gbix``, ``pixfmt``, ``datafmt``, ``width``, ``height`` and ``bytes`` (the GBIX +
    PVRT bytes, ready for :func:`gbox.ninja.pvr_decode`).
    """
    if size is None:
        size = entry_size(data, ptex_off)
    end = min(len(data), ptex_off + size)
    out: list[dict] = []
    q = data.find(b"GBIX", ptex_off + 8, end)
    while 0 <= q and q + 16 <= end and data[q:q + 4] == b"GBIX":
        glen, gbix = struct.unpack_from("<II", data, q + 4)
        r = q + 8 + glen
        if data[r:r + 4] != b"PVRT":
            raise ValueError(f"GBIX at +{q - ptex_off:#x} not followed by PVRT")
        plen = struct.unpack_from("<I", data, r + 4)[0]
        tex_end = r + 8 + plen
        if tex_end > end:
            raise ValueError(f"PVRT at +{r - ptex_off:#x} overruns its entry")
        w, h = struct.unpack_from("<HH", data, r + 12)
        out.append({
            "offset": q - ptex_off,
            "gbix": gbix,
            "pixfmt": data[r + 8],
            "datafmt": data[r + 9],
            "width": w,
            "height": h,
            "bytes": bytes(data[q:tex_end]),
        })
        q = (tex_end + 3) & ~3
        while q + 4 <= end and data[q:q + 4] == b"\0\0\0\0":
            q += 4
    return out


def decode_texture(tex: dict) -> tuple[int, int, bytes]:
    """Decode one :func:`ptex_textures` entry to (width, height, RGBA bytes)."""
    from .ninja import pvr_decode
    w, h, rgba, _ = pvr_decode(tex["bytes"])
    return w, h, rgba


def export_texture_set(data: bytes, ptex_off: int, outdir: str) -> list[str]:
    """Decode every texture of one PTEX chunk to PNG files in ``outdir``; returns the paths."""
    import os
    from .ninja import png
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i, tex in enumerate(ptex_textures(data, ptex_off)):
        w, h, rgba = decode_texture(tex)
        path = os.path.join(outdir, f"tex{i:02d}_gbix{tex['gbix']}_{w}x{h}.png")
        with open(path, "wb") as f:
            f.write(png(w, h, rgba))
        paths.append(path)
    return paths



# ---------------------------------------------------------------- PLAY model trees (Ninja chunk objects)
# A PLAY chunk is a raw Ninja *chunk-model* object tree without the NJCM wrapper. Every pointer is
# relative to the start of the PLAY chunk. NJS_OBJECT is 0x34 bytes (evalflags, model, pos[3],
# ang[3], scl[3], child, sibling); NJS_CNK_MODEL is (vlist, plist, center[3], radius) and sits after
# its plist/vlist. Container header records of kind 1-3 point at model roots (the first record is a
# root table, not an object); kinds 4-7 are motion/other data. Body roots carry 20 nodes.

MODEL_KINDS = (1, 2, 3)


def play_bytes(data: bytes, play_off: int, size: int | None = None) -> bytes:
    """The PLAY chunk as its own buffer, so its internal pointers index it directly."""
    if size is None:
        size = entry_size(data, play_off)
    return bytes(data[play_off:play_off + size])


def _is_object(buf: bytes, o: int) -> bool:
    """Cheap NJS_OBJECT sanity check: small eval flags, sane scale, aligned in-range pointers."""
    if o % 4 or not 0 <= o <= len(buf) - 0x34:
        return False
    flags, model = struct.unpack_from("<II", buf, o)
    scl = struct.unpack_from("<3f", buf, o + 0x20)
    child, sib = struct.unpack_from("<II", buf, o + 0x2C)
    if flags > 0xFF or not all(1e-3 < abs(s) < 1e3 for s in scl):
        return False
    return all(p == 0 or (p % 4 == 0 and p < len(buf)) for p in (model, child, sib))


def play_model_roots(data: bytes, play_off: int, size: int | None = None) -> list[int]:
    """Model root object offsets (relative to the PLAY chunk), in container-header order.

    Header records of kind 1-3 point at model roots; the first record is a root table (not an
    object) and kinds 4-7 hold motion/other data. A record is kept only when it looks like an
    NJS_OBJECT (:func:`_is_object`).
    """
    buf = play_bytes(data, play_off, size)
    _, recs = container_header(data, play_off)
    roots: list[int] = []
    for v, k in recs:
        if k in MODEL_KINDS and v not in roots and _is_object(buf, v):
            roots.append(v)
    return roots


def play_model(buf: bytes, root: int):
    """Walk one PLAY model tree with the shared Ninja chunk parser (:class:`gbox.ninja.NJ`)."""
    from .ninja import NJ

    class _PlayNJ(NJ):
        def __init__(self, d: bytes, start: int):
            self.e, self.d = "<", d
            self.bones, self.vbuf, self.tris, self.tex, self.plcache = [], {}, {}, 0, {}
            self._walk(start, None, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])

    if not 0 <= root <= len(buf) - 0x34:
        raise ValueError(f"root +{root:#x} outside the PLAY chunk")
    return _PlayNJ(buf, root)


def play_summary(data: bytes, play_off: int) -> list[dict]:
    """Per-root node, vertex, triangle and texture-id counts for one PLAY chunk."""
    buf = play_bytes(data, play_off)
    out = []
    for root in play_model_roots(data, play_off):
        nj = play_model(buf, root)
        out.append({"root": root, "nodes": len(nj.bones), "vertices": len(nj.vbuf),
                    "triangles": sum(len(t) for t in nj.tris.values()), "texture_ids": sorted(nj.tris)})
    return out


def export_play_glb(data: bytes, play_off: int, root: int, out_dir: str, name: str,
                    ptex_off: int | None = None) -> str:
    """Write one PLAY model (skinned to its node skeleton) as a package + self-contained GLB.

    When ``ptex_off`` is given, that PTEX set is decoded into ``textures/`` and Ninja texture id
    *i* is bound to the set's *i*-th texture. Returns the GLB path.
    """
    from pathlib import Path
    from . import uap
    from .ninja import png, to_manifest
    out = Path(out_dir)
    files: list[str | None] = []
    if ptex_off is not None:
        (out / "textures").mkdir(parents=True, exist_ok=True)
        for i, tex in enumerate(ptex_textures(data, ptex_off)):
            w, h, rgba = decode_texture(tex)
            rel = f"textures/{name}_tex{i:02d}_gbix{tex['gbix']}.png"
            (out / rel).write_bytes(png(w, h, rgba))
            files.append(rel)
    out.mkdir(parents=True, exist_ok=True)
    nj = play_model(play_bytes(data, play_off), root)
    m = to_manifest(nj, name, {"game": GAME_IDS["4187aeab4d67638c"], "files": ["JETRADIO/PLAYER.AFS"],
                               "play_offset": play_off, "root": root, "extraction_method": "gbox.jgr"},
                    files or None)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return str(glb)
