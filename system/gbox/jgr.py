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

import hashlib
import json
from pathlib import Path
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


def afs_names(data: bytes) -> list[str]:
    """Read the bounded CRI AFS filename directory, checking each recorded entry size."""
    count, offsets, sizes = afs_entries(data)
    if not count:
        return []
    table_end = 8 + 8 * count
    if any(off < table_end or off + size > len(data) for off, size in zip(offsets, sizes)):
        raise ValueError("AFS entry extends outside the archive")
    found = []
    for at in dict.fromkeys((min(offsets) - 8, table_end)):
        if at < table_end or at + 8 > len(data):
            continue
        off, size = struct.unpack_from("<II", data, at)
        if off < table_end or size < 48 * count or off + size > len(data):
            continue
        records = [data[off + 48 * i:off + 48 * (i + 1)] for i in range(count)]
        if not all(struct.unpack_from("<I", record, 44)[0] == sizes[i]
                   for i, record in enumerate(records)):
            continue
        try:
            names = [record[:32].split(b"\0", 1)[0].decode("ascii") for record in records]
        except UnicodeDecodeError:
            continue
        if all(names):
            found.append(names)
    if not found:
        raise ValueError("AFS archive has no file-name directory matching its entry table")
    if any(names != found[0] for names in found[1:]):
        raise ValueError("AFS archive has ambiguous file-name directories")
    return found[0]


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


FLAT_BASE = 0x10000   # play_model(materials=True): strip classes other than plain textured are keyed FLAT_BASE + i


def play_model(buf: bytes, root: int, materials: bool = False):
    """Walk one PLAY model tree with the shared Ninja chunk parser (:class:`gbox.ninja.NJ`).

    materials=True files every strip chunk by what it is, read from the chunk itself: a lit textured strip stays under
    its texture id; any other strip is keyed ``FLAT_BASE + i`` with ``.materials[i]`` = {"outline": the strip's
    ignore-light flag (NJD_FST_IL, bit 0 of the strip chunk flags), "texture": its texture id or None (chunk 0x40/43/
    46/49 carry no UVs), "colour": the (r, g, b, a) material diffuse}. On the cast's gameplay bodies the
    ignore-light strips are the cel-shading outline: an inverted hull ~0.1 unit outside the body with reversed normals,
    drawn black (or with the shared tiny GBIX 2 texture); an ordinary viewer draws it as a dark shell around the
    character (#1396). The default keeps the shared parser's behaviour (one list per texture id)."""
    from .ninja import NJ

    class _PlayNJ(NJ):
        def __init__(self, d: bytes, start: int):
            self.e, self.d = "<", bytearray(d) if materials else d
            self.bones, self.vbuf, self.tris, self.tex, self.plcache = [], {}, {}, 0, {}
            self.materials, self._diffuse = [], (255, 255, 255, 255)
            self._walk(start, None, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
            if materials:
                self.d = bytes(self.d)

        def _polys(self, o):
            if not materials:
                return super()._polys(o)
            p = o
            while True:
                typ, fl = self.d[p], self.d[p + 1]
                if typ == 0xFF:
                    return
                if typ in (4, 5):
                    raise ValueError(f"cached polygon list chunk at +{p:#x}: not a JGR body strip list")
                if typ < 8:
                    p += 2
                elif typ in (8, 9):
                    self.tex = self.u("H", p + 2)[0] & 0x1FFF
                    p += 4
                elif 0x10 <= typ <= 0x3A:
                    if typ <= 0x17 and typ & 1:                    # material with diffuse: BGRA bytes
                        b, g, r, a = self.d[p + 4:p + 8]
                        self._diffuse = (r, g, b, a)
                    p += 4 + self.u("H", p + 2)[0] * 2
                elif 0x40 <= typ <= 0x4B:
                    end = p + 4 + self.u("H", p + 2)[0] * 2
                    textured = typ not in (0x40, 0x43, 0x46, 0x49)
                    key = self.tex
                    if fl & 1 or not textured:
                        mat = {"outline": bool(fl & 1), "texture": self.tex if textured else None,
                               "colour": self._diffuse}
                        if mat not in self.materials:
                            self.materials.append(mat)
                        key = FLAT_BASE + self.materials.index(mat)
                    # decode this one strip chunk with the shared parser: end the list right after it for the call
                    saved, self.tex, tail = self.tex, key, bytes(self.d[end:end + 2])
                    self.d[end:end + 2] = b"\xff\x00"
                    try:
                        super()._polys(p)
                    finally:
                        self.d[end:end + 2], self.tex = tail, saved
                    p = end
                else:
                    return                                         # unknown chunk: stop, as the shared parser does

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


# ---------------------------------------------------------------- draw groups and their texture lists (#1396)
# PLAY+8 points at the character's binding record: int32 native ID, then one 16-byte slot per draw group (the group's
# root object, repeated four times). PTEX+8 points at a record of the same shape whose slots are NJS_TEXLIST pointers
# ({NJS_TEXNAME *names (count x 12 zero bytes, filled at load), u32 count}, followed by `count` pointers to GBIX+PVRT
# data in the PTEX), ended by -1. A strip's texture id indexes ITS group's texlist, not the PTEX file order: Yo-Yo's
# spray-can body binds id 0 to the shared can texture (GBIX 760) and id 1 to the body atlas, and Gum's body atlas is
# PTEX texture 1. The six groups have the same roles on all 16 USA characters (checked on the owned disc):
GROUP_ROLES = ("body",            # 0: gameplay body, high detail (what the player sees while skating)
               "body_lod",        # 1: the same body, low detail
               "body_spray",      # 2: high-detail body with the spray can in the right hand (shared texture GBIX 760)
               "body_spray_lod",  # 3: low-detail body with the can
               "shadow",          # 4: shadow volume: 20 nodes, vertices only, no strips
               "head")            # 5: separate 4-node head (face-expression sheet); a single empty node on Goji/Pots
GROUP_COUNT = len(GROUP_ROLES)
CHARACTER_GROUP = 0


def _record_slots(chunk: bytes, what: str, variant: int = 0) -> tuple[int, list[int]]:
    """(native ID, slot `variant` of each of the GROUP_COUNT draw groups) from a PLAY/PTEX binding record. Each group
    has four slots; they are equal except on the rival leaders' PTEX, whose slots 1-3 name alternate colour atlases
    (GBIX 355000 / 455000 ...). Slot 0 is the default look."""
    if len(chunk) < 12:
        raise ValueError(f"{what}: truncated chunk")
    rec = struct.unpack_from("<I", chunk, 8)[0]
    if rec % 4 or rec < 12 or rec + 4 + 16 * GROUP_COUNT > len(chunk):
        raise ValueError(f"{what}: binding record offset {rec:#x} is outside the chunk")
    nid = struct.unpack_from("<i", chunk, rec)[0]
    return nid, [struct.unpack_from("<4I", chunk, rec + 4 + 16 * k)[variant] for k in range(GROUP_COUNT)]


def play_groups(data: bytes, play_off: int) -> list[int | None]:
    """Root object of each draw group (GROUP_ROLES order) from the PLAY binding record; None for an empty slot."""
    buf = play_bytes(data, play_off)
    _, roots = _record_slots(buf, f"PLAY +{play_off:#x}")
    out = []
    for k, r in enumerate(roots):
        if r and not _is_object(buf, r):
            raise ValueError(f"PLAY +{play_off:#x}: draw group {k} root +{r:#x} is not an object")
        out.append(r or None)
    return out


def ptex_texlists(data: bytes, ptex_off: int) -> list[list[int]]:
    """Per draw group (GROUP_ROLES order): the PTEX texture index (``ptex_textures`` order) of each Ninja texture id."""
    size = entry_size(data, ptex_off)
    chunk = bytes(data[ptex_off:ptex_off + size])
    if chunk[:4] != PTEX_MAGIC:
        raise ValueError(f"+{ptex_off:#x} is not a PTEX chunk")
    _, lists = _record_slots(chunk, f"PTEX +{ptex_off:#x}")
    index = {t["offset"]: i for i, t in enumerate(ptex_textures(data, ptex_off, size))}
    out = []
    for k, p in enumerate(lists):
        if not p:
            out.append([])
            continue
        if p % 4 or p + 8 > len(chunk):
            raise ValueError(f"PTEX +{ptex_off:#x}: texlist {k} at {p:#x} is outside the chunk")
        _names, count = struct.unpack_from("<II", chunk, p)
        if count > 64 or p + 8 + 4 * count > len(chunk):
            raise ValueError(f"PTEX +{ptex_off:#x}: texlist {k} has an implausible count {count}")
        ptrs = struct.unpack_from(f"<{count}I", chunk, p + 8)
        if any(q not in index for q in ptrs):
            raise ValueError(f"PTEX +{ptex_off:#x}: texlist {k} points outside its GBIX/PVRT textures")
        out.append([index[q] for q in ptrs])
    return out


def atlas_texture(data: bytes, ptex_off: int, texlists: list[list[int]] | None = None) -> int:
    """PTEX index of the gameplay body's atlas: the largest texture in group 0's texlist (Gum's is PTEX 1, the
    Poison Jam leaders' PTEX 1; texture 0 is an 8x8 / face sheet there)."""
    texlists = ptex_texlists(data, ptex_off) if texlists is None else texlists
    texs = ptex_textures(data, ptex_off)
    if not texlists or not texlists[CHARACTER_GROUP]:
        raise ValueError(f"PTEX +{ptex_off:#x}: the body group has no texture list")
    return max(texlists[CHARACTER_GROUP], key=lambda i: (texs[i]["width"] * texs[i]["height"], -i))


def group_manifest(data: bytes, play_off: int, root: int, texlist: list[int], name: str,
                   texture_files: list[str] | None, source: dict, outline: bool | None = False):
    """uap manifest of one draw group: texture ids bound through the group's own texlist (``texture_files`` in PTEX
    order), untextured strips as flat diffuse-colour materials, skinned to the group's node skeleton.

    outline: False = without the cel-shading outline strips (play_model's ignore-light class), True = those alone,
    None = everything. Returns (manifest, model, triangle count)."""
    from types import SimpleNamespace
    from .ninja import to_manifest
    nj = play_model(play_bytes(data, play_off), root, materials=True)

    def keep(key):
        if outline is None:
            return True
        is_outline = key >= FLAT_BASE and nj.materials[key - FLAT_BASE]["outline"]
        return is_outline == outline
    tris = {k: v for k, v in nj.tris.items() if keep(k)}
    files = None
    if texture_files is not None:
        files = [texture_files[i] if 0 <= i < len(texture_files) else None for i in texlist]
    flat_files = {}
    for k in tris:
        if k >= FLAT_BASE:
            t = nj.materials[k - FLAT_BASE]["texture"]
            flat_files[k] = files[t] if files is not None and t is not None and t < len(texlist) else None
    m = to_manifest(SimpleNamespace(tris=tris, vbuf=nj.vbuf, bones=nj.bones), name, source, None)
    for mat, mesh in zip(m.materials, m.meshes):
        tid = mat.source.get("ninja_texture_id", -1)
        if tid >= FLAT_BASE:
            info = nj.materials[tid - FLAT_BASE]
            r, g, b, a = info["colour"]
            kind = "outline" if info["outline"] else "flat"
            mat.name = mesh.name = f"{name}_{kind}{tid - FLAT_BASE}"
            mat.texture = flat_files.get(tid)
            mat.base_color = [1, 1, 1, 1] if mat.texture else [round(r / 255, 4), round(g / 255, 4),
                                                                round(b / 255, 4), round(a / 255, 4)]
            mat.source = {"strip_class": kind, "ninja_texture_id": info["texture"],
                          "ptex_index": texlist[info["texture"]] if info["texture"] is not None
                          and info["texture"] < len(texlist) else None,
                          "diffuse": f"#{r:02x}{g:02x}{b:02x}{a:02x}"}
        else:
            known = 0 <= tid < len(texlist)
            mat.texture = files[tid] if files is not None and known else None
            mat.source = {"strip_class": "textured", "ninja_texture_id": tid, "ptex_index": texlist[tid] if known else None}
    return m, nj, sum(len(t) for t in tris.values())


def export_character(data: bytes, index: int, out_dir: str, name: str) -> dict:
    """Write character *index* as its gameplay body alone, with everything else as separate parts (#1396).

    ``<name>.glb`` (+ manifest.json, textures/) is draw group 0, the body the game draws while skating, textured
    through its own PTEX texlist and without its cel-shading outline hull. ``parts/`` gets the outline hull
    (``<name>_outline.glb``) and every other draw group that draws anything: the spray-can bodies, the low-detail
    bodies and the separate head (``<name>_<role>.glb``, complete with their own outlines). The shadow volume has no
    strips and is listed only. Returns {glb, root, triangles, parts: [{role, draw_group, root, triangles, file?}],
    texlists}."""
    from . import uap
    from .ninja import png
    out = Path(out_dir)
    play, ptex = character_pair(data, index)
    groups, texlists = play_groups(data, play), ptex_texlists(data, ptex)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    files = []
    for i, tex in enumerate(ptex_textures(data, ptex)):
        w, h, rgba = decode_texture(tex)
        rel = f"textures/{name}_tex{i:02d}_gbix{tex['gbix']}.png"
        (out / rel).write_bytes(png(w, h, rgba))
        files.append(rel)
    base = {"game": GAME_IDS["4187aeab4d67638c"], "files": [PLAYER_AFS], "play_offset": play, "ptex_offset": ptex,
            "extraction_method": "gbox.jgr (draw groups + PTEX texlists)"}
    root = groups[CHARACTER_GROUP]
    if root is None:
        raise ValueError(f"PLAY {index:02d} has no gameplay body group")
    body_list = texlists[CHARACTER_GROUP] if texlists else []
    m, _nj, tris = group_manifest(data, play, root, body_list, name, files,
                                  base | {"root": root, "draw_group": CHARACTER_GROUP, "role": GROUP_ROLES[CHARACTER_GROUP]})
    if not m.meshes:
        raise ValueError(f"PLAY {index:02d}: the gameplay body draws nothing besides its outline")
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    parts = []

    def part(role, k, r, texlist, which):
        row = {"role": role, "draw_group": k, "root": None if r is None else f"{r:#x}", "triangles": 0}
        if r is not None:
            pm, pnj, n = group_manifest(data, play, r, texlist, f"{name}_{role}", files,
                                        base | {"root": r, "draw_group": k, "role": role}, which)
            row["nodes"], row["triangles"] = len(pnj.bones), n
            if pm.meshes:
                (out / "parts").mkdir(exist_ok=True)
                path = out / "parts" / f"{name}_{role}.glb"
                path.write_bytes(uap.to_glb(pm, out))
                row["file"] = f"parts/{path.name}"
        parts.append(row)
    part("outline", CHARACTER_GROUP, root, body_list, True)
    for k, (role, r) in enumerate(zip(GROUP_ROLES, groups)):
        if k != CHARACTER_GROUP:
            part(role, k, r, texlists[k] if k < len(texlists) else [], None)
    return {"glb": str(glb), "root": root, "triangles": tris, "parts": parts, "texlists": texlists}


# ---------------------------------------------------------------- native collection (gbox.characters)
PLAYER_AFS = "JETRADIO/PLAYER.AFS"
CHARACTER_COUNT = 16
# 2: draw group 0 alone through its PTEX texlist, extras as parts/ (#1396). Collection entries of an older reader
# (largest-triangle spray-can body, texture ids bound to PTEX file order) are re-extracted by characters.collect.
READER_VERSION = 2


def needs_refresh(meta: dict) -> bool:
    """A collection entry this reader made before READER_VERSION (characters.extract_dedicated re-extracts it)."""
    return "gbox.jgr" in (meta.get("extraction_tool") or "") and meta.get("jgr_reader", 1) < READER_VERSION


# Verified USA PLAYER.AFS directory order and 1ST_READ debug labels at 0x8c10df40.
# These labels identify resources; they do not identify the currently controlled actor.
ARCHIVE_NAMES = ["bis", "code", "conpo", "corn", "ereki", "goji", "gum", "nat", "plug", "pots", "reco",
                 "rival_lshocker", "rival_ntank", "rival_pjam", "rival_snpjam", "yoyo"]
NATIVE_DEBUG_NAMES = ["BEAT(EREKI)", "GUM", "CORN", "COMBO", "CODE", "NUTS", "RECO", "BIS", "YO_YO",
                      "PLUG(PENCH)", None, None, None, "GOJI", "POTS", None]
USA_NATIVE_IDS = [7, 4, 3, 2, 0, 13, 1, 5, 9, 14, 6, 11, 12, 10, 15, 8]


def _slot_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def character_aliases(names: list[str] | None = None, ids: list[int] | None = None) -> dict[str, int]:
    """Resolve archive filenames and native debug labels without silently choosing an ambiguous alias."""
    if names is None:
        names = ARCHIVE_NAMES
        if ids is None:
            ids = USA_NATIVE_IDS
    if len(names) != CHARACTER_COUNT or any(not isinstance(n, str) or not _slot_key(n) for n in names):
        raise ValueError("JGR character names must identify all 16 archive entries")
    if ids is not None and (len(ids) != CHARACTER_COUNT or any(type(n) is not int for n in ids)
                            or sorted(ids) != list(range(CHARACTER_COUNT))):
        raise ValueError("JGR native IDs must be a permutation of integers 0-15")
    out = {}
    for index, name in enumerate(names):
        aliases = [name, name + "dat.bin"]
        label = NATIVE_DEBUG_NAMES[ids[index]] if ids is not None else None
        if label:
            aliases.extend(label.replace(")", "").split("("))
        for alias in aliases:
            key = _slot_key(alias)
            if key in out and out[key] != index:
                raise ValueError(f"JGR character alias {alias!r} is ambiguous")
            out[key] = index
    return out


def character_names(data: bytes) -> list[str]:
    """Internal PLAY resource names from this archive's directory, in its actual entry order."""
    names = afs_names(data)
    _, offsets, _ = afs_entries(data)
    out = []
    for name, off in zip(names, offsets):
        if data[off:off + 4] != PLAY_MAGIC:
            continue
        if not name.endswith("dat.bin") or "/" in name or "\\" in name:
            raise ValueError(f"PLAY directory name {name!r} is not a character dat.bin resource")
        out.append(name[:-len("dat.bin")])
    character_aliases(out)  # Check normalized filenames before adding native-label aliases.
    return out


def roster() -> list[dict]:
    """The verified USA resource names; collection slugs keep their archive positions."""
    out = []
    for index, name in enumerate(ARCHIVE_NAMES):
        native = USA_NATIVE_IDS[index]
        label = NATIVE_DEBUG_NAMES[native]
        title = (label.split("(")[0].replace("_", "-").title() if label else name.replace("_", " ").title())
        aliases = [f"JGR character {index}", f"JGR char {index:02d}", f"PLAYER.AFS PLAY {index}",
                   name, name + "dat.bin"]
        if label:
            aliases.append(label)
        out.append({"key": f"{index:02d}", "slug": f"jgr_char{index:02d}", "kind": "character",
                    "name": f"{title} (JGR {name}, ID {native})", "aliases": aliases, "native_id": native})
    return out


def character_pair(data: bytes, index: int) -> tuple[int, int]:
    """(PLAY offset, PTEX offset) of character *index*: the archive stores them as consecutive pairs."""
    ch = chunks(data)
    plays = [o for k, o in ch if k == "play"]
    ptexs = [o for k, o in ch if k == "ptex"]
    if len(plays) != CHARACTER_COUNT or len(ptexs) != CHARACTER_COUNT:
        raise ValueError(f"PLAYER.AFS holds {len(plays)} PLAY / {len(ptexs)} PTEX chunks, expected {CHARACTER_COUNT}")
    return plays[index], ptexs[index]


def body_root(data: bytes, play_off: int) -> int:
    """Extraction/build heuristic: most triangles among 20-node roots; the runtime draw group is unverified."""
    rows = [r for r in play_summary(data, play_off) if r["nodes"] == 20 and r["triangles"]]
    if not rows:
        raise ValueError(f"PLAY +{play_off:#x} has no 20-node body")
    return max(rows, key=lambda r: r["triangles"])["root"]


# Every PLAY body shares one 20-node tree: node000 root, node001 pelvis (legs and spine branch here),
# node002-004 / node005-007 right / left leg, node008-009 spine, node010-011 head, node012-015 /
# node016-019 right / left clavicle, shoulder, elbow, wrist. Parent index per node:
BODY_PARENTS = [-1, 0, 1, 2, 3, 1, 5, 6, 1, 8, 9, 10, 9, 12, 13, 14, 9, 16, 17, 18]
# Roles in gbox.characters.tree_roles vocabulary. tree_roles itself can't read these rigs: every leaf
# sits under the pelvis, and two characters (02, 12) are bound with an arm raised above the head.
BODY_ROLES = {"hip": "node001", "chest": "node008", "head": "node010",
              "l_thigh": "node005", "l_shin": "node006", "l_foot": "node007",
              "r_thigh": "node002", "r_shin": "node003", "r_foot": "node004",
              "l_upper": "node017", "l_fore": "node018", "l_hand": "node019",
              "r_upper": "node013", "r_fore": "node014", "r_hand": "node015"}


def body_roles(glb_path) -> dict[str, str]:
    """BODY_ROLES after checking the exported skin matches BODY_PARENTS and its left side is +X."""
    import json
    from pathlib import Path
    raw = Path(glb_path).read_bytes()
    g = json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]])
    joints = g["skins"][0]["joints"]
    names = [g["nodes"][j].get("name") for j in joints]
    if names != [f"node{i:03d}" for i in range(len(BODY_PARENTS))]:
        raise ValueError(f"unexpected joint names {names[:4]}...")
    parent = {c: i for i, n in enumerate(g["nodes"]) for c in n.get("children", [])}
    got = [joints.index(parent[j]) if parent.get(j) in joints else -1 for j in joints]
    if got != BODY_PARENTS:
        raise ValueError(f"skeleton tree differs from the JGR body tree: {got}")
    tx = {names[k]: g["nodes"][j].get("translation", [0, 0, 0])[0] for k, j in enumerate(joints)}
    if not (tx["node005"] > 0 > tx["node002"] and tx["node016"] > 0 > tx["node012"]):
        raise ValueError("left/right sides are not on +X/-X")
    return dict(BODY_ROLES)


def extract_run(ctx, game: dict, e: dict, work) -> dict:
    """gbox.characters DEDICATED runner: export one character's high-detail body as a skinned GLB."""
    from pathlib import Path
    from .characters import _dc_gdi
    from .gdrom import GDRom
    work = Path(work)
    data = GDRom(str(_dc_gdi(ctx, game))).read(PLAYER_AFS)
    play, ptex = character_pair(data, int(e["key"]))
    ctx.progress(50, f"Decoding PLAY +{play:#x} draw groups")
    x = export_character(data, int(e["key"]), str(work), e["slug"])
    root = x["root"]
    files = [x["glb"], work / "textures", work / "manifest.json"]
    if (work / "parts").is_dir():
        files.append(work / "parts")
    extras = [p for p in x["parts"] if p.get("file")]
    out = {"files": files, "tool": "gbox.jgr + gbox.ninja",
           "source_files": [f"{PLAYER_AFS} PLAY #{int(e['key'])} (+{play:#x}, root +{root:#x})",
                            f"{PLAYER_AFS} PTEX #{int(e['key'])} (+{ptex:#x})"],
           "extra": {"jgr_reader": READER_VERSION, "draw_group": GROUP_ROLES[CHARACTER_GROUP],
                     "parts": [{k: p[k] for k in ("role", "draw_group", "root", "triangles", "file") if k in p}
                               for p in x["parts"]]},
           "notes": "The gameplay body (draw group 0 of the PLAY binding record) alone, textured through its own "
                    "PTEX texture list; untextured strips keep their flat material colour. "
                    f"{len(extras)} other draw groups (spray-can and low-detail bodies, separate head) are separate "
                    "files under parts/; the shadow volume has no strips. Offline experimental writer available; "
                    "visible native replacement remains unverified."}
    try:
        out["roles"] = body_roles(glb)
    except Exception as exc:                               # noqa: BLE001 - report instead of inventing roles
        out["notes"] += f" Rig roles not derived: {exc}"
    return out


# ---- native swap writer: a library character -> one PLAYER.AFS body (gbox.ninja_swap pipeline, as gbox.sa2_chars) ----
BUDGETS = (1400, 1150, 950, 800, 650, 500, 400, 300, 270, 240, 200)   # char 00's 5 big lists need 4 holes:
# at 300 triangles two of them overshoot the biggest hole by 28 bytes, so smaller steps follow (#1155)
ATLAS_TEXTURE = 0       # legacy (PTEX texture 0 / id 0): the writer now finds both per group (group_texture_ids)
HEAD_NODES = {10, 11}


# Archive position is not the game's character ID. Each PLAY starts "PLAY", u32, u32 binding-record offset (relative to
# the PLAY); the record's first int32 is the native character ID that 1ST_READ's lookup (0x8c0c7f74) compares with the
# caller's ID, followed by the body-root slots. On the USA disc archive 00 is native ID 7 and native ID 0 is archive 04.
def native_ids(data: bytes) -> list[int]:
    """Native character ID of every PLAYER.AFS character, in archive order (checked: a permutation of 0-15)."""
    ids = []
    for i in range(CHARACTER_COUNT):
        play, _ = character_pair(data, i)
        size = entry_size(data, play)
        if size < 12 or play + size > len(data):
            raise ValueError(f"PLAY {i:02d}: truncated AFS entry")
        rec = struct.unpack_from("<I", data, play + 8)[0]
        if rec % 4 or rec < 12 or rec + 0x8c > size:
            raise ValueError(f"PLAY {i:02d} (+{play:#x}): binding record offset {rec:#x} is outside the PLAY")
        ids.append(struct.unpack_from("<i", data, play + rec)[0])
    if sorted(ids) != list(range(CHARACTER_COUNT)):
        raise ValueError(f"PLAYER.AFS native character IDs {ids} are not a permutation of 0-{CHARACTER_COUNT - 1}")
    return ids


def native_id_for_archive(data: bytes, index: int) -> int:
    if not 0 <= index < CHARACTER_COUNT:
        raise ValueError(f"archive index {index} outside 00-{CHARACTER_COUNT - 1:02d}")
    return native_ids(data)[index]


def archive_index_for_native_id(data: bytes, native_id: int) -> int:
    ids = native_ids(data)
    if native_id not in ids:
        raise ValueError(f"native character ID {native_id} is not bound by any PLAYER.AFS PLAY (IDs 0-{CHARACTER_COUNT - 1})")
    return ids.index(native_id)


def swap_index(slot: str | None, data=None, active_id: int | None = None) -> int:
    """characters op=use slot -> PLAYER.AFS archive index.

    'NN', 'jgr_charNN' or 'char:NN' name an archive position; 'id:N' names the game's native character ID (needs
    `data`, the PLAYER.AFS bytes or a callable returning them). Names such as 'beat' / 'ereki' use archive filenames
    and verified native debug labels (the USA table when no data is supplied). 'player' resolves only through a known
    active native character ID: archive 00 is not the default player, so it is never guessed."""
    s = (slot or "player").strip().lower()
    load = (lambda: data() if callable(data) else data)
    if s == "player":
        if active_id is None:
            raise ValueError("slot 'player': the active native character ID is unknown, so the archive entry can't be "
                             "chosen (archive 00 is native ID 7, not the default player). Use 'id:N' for native "
                             f"character ID N or 'NN' for archive index 00-{CHARACTER_COUNT - 1:02d}")
        if type(active_id) is not int or not 0 <= active_id < CHARACTER_COUNT:
            raise ValueError("active_id must be a native integer ID from 0 to 15")
        s = f"id:{active_id}"
    if s.startswith(("id", "native")):
        num = s.split("id", 1)[-1] if s.startswith("id") else s[len("native"):]
        num = num.lstrip(":_ ")
        if not num.isdigit():
            raise ValueError(f"slot {slot!r}: native character IDs look like 'id:0'")
        buf = load()
        if buf is None:
            raise ValueError(f"slot {slot!r}: resolving a native character ID needs the PLAYER.AFS data")
        return archive_index_for_native_id(buf, int(num))
    key = _slot_key(s)
    if key and not key.isdigit() and not key.startswith(("jgrchar", "char")):
        buf = load() if data is not None else None
        names, ids = (character_names(buf), native_ids(buf)) if buf is not None else (ARCHIVE_NAMES, USA_NATIVE_IDS)
        aliases = character_aliases(names, ids)
        if key in aliases:
            return aliases[key]
        raise ValueError(f"slot {slot!r}: no JGR character has that name; names on this disc: {', '.join(names)}")
    digits = s.rsplit("char", 1)[-1].lstrip(":_ ")
    if not digits.isdigit() or not 0 <= int(digits) < CHARACTER_COUNT:
        raise ValueError(f"slot {slot!r}: use a resource name such as 'beat', 'id:N' (native character ID), "
                         "'player' with a known active ID, or a "
                         f"JGR archive index 00-{CHARACTER_COUNT - 1:02d}")
    return int(digits)


CACHE_VERSION = 6  # 3: multi-root writer. 4 was taken by #1151's branch builds (mod ..._a80947d49d022a3a), which
                   # put new vertices past the native cache span and drew no body in gameplay (#1153 live).
                   # 5: new vertices stay inside every group's native span (#1156).
                   # 6: the atlas is the body group's largest texlist texture and every group draws it under its
                   #    own texlist id (PTEX texture 0 / id 0 painted Gum, Code, Reco, Yo-Yo and the Poison Jam
                   #    leaders with the wrong texture; #1396).


def donor_fingerprint(model, roles: dict, scale=None) -> str:
    """Hash the donor, external glTF resources, and retarget settings before cache reuse."""
    from .characters import _load
    path = Path(model)
    raw = path.read_bytes()
    gltf, *_ = _load(path)
    resources = []
    for item in gltf.get("buffers", []) + gltf.get("images", []):
        uri = item.get("uri")
        if uri and not uri.startswith("data:"):
            resources.append({"uri": uri, "sha256": hashlib.sha256((path.parent / uri).read_bytes()).hexdigest()})
    record = {"model_sha256": hashlib.sha256(raw).hexdigest(), "resources": resources,
              "roles": roles, "scale": scale or {}}
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cache_identity(data: bytes, model, meta: dict, game: dict, index: int) -> dict:
    """Identity of an offline build; neither the caller ID nor the root heuristic proves native gameplay."""
    if type(index) is not int or not 0 <= index < CHARACTER_COUNT:
        raise ValueError("archive index must be an integer from 0 to 15")
    play, _ = character_pair(data, index)
    rig = meta.get("rig") or {}
    return {"schema": CACHE_VERSION, "writer": "gbox.jgr", "game_id": game["game_id"],
            "donor_slug": meta["slug"],
            "donor_sha256": donor_fingerprint(model, rig.get("roles") or {}, rig.get("scale")),
            "source_afs_sha256": hashlib.sha256(data).hexdigest(),
            "archive_index": index, "native_id": native_id_for_archive(data, index),
            "body_root": f"{body_root(data, play):#x}",
            "body_selection": "max_triangles_unverified", "runtime_verified": False}


def _mod_name(meta: dict, index: int, identity: dict | None = None) -> str:
    from .characters import slugify
    slug = meta["slug"]
    if not isinstance(slug, str) or not slug or slugify(slug) != slug:
        raise ValueError("JGR donor slug must be a safe collection slug")
    name = f"jgr_{slug}_{index:02d}"
    if identity is not None:
        name += "_" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return name


def validate_cached_mod(directory, identity: dict, meta: dict) -> dict:
    """Fail closed on legacy, mismatched, incomplete or missing builds without altering their files."""
    directory = Path(directory)
    try:
        manifest = json.loads((directory / ".gbox-mod.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Existing JGR mod {directory.name} has no valid checked offline build identity; its files were preserved") from exc
    if (not isinstance(manifest, dict) or manifest.get("cache_identity") != identity
            or manifest.get("game_id") != identity["game_id"]
            or manifest.get("character") != meta["slug"] or manifest.get("name") != directory.name):
        raise ValueError(f"Existing JGR mod {directory.name} differs from the donor/source/target/root identity; its files were preserved")
    image = manifest.get("image")
    if (not isinstance(image, str) or Path(image).name != image or Path(image).suffix.lower() != ".gdi"
            or not (directory / image).is_file()):
        raise ValueError(f"Existing JGR mod {directory.name} has no local GDI image; its files were preserved")
    return manifest


def entry_room(data: bytes, off: int) -> int:
    """Bytes an AFS entry may grow to without moving the next entry (its size + the padding before the next one)."""
    _, offsets, _ = afs_entries(data)
    later = [o for o in offsets if o > off]
    return (min(later) if later else len(data)) - off


def replace_entries(data: bytes, new: dict[int, bytes]) -> bytes:
    """PLAYER.AFS with the entries at the given absolute offsets rewritten in place (table sizes updated). Every
    other byte stays, so the archive keeps its length and gbox.gdrom.patch_gdi rewrites it in its own sectors."""
    _, offsets, _ = afs_entries(data)
    out = bytearray(data)
    for off, blob in new.items():
        room = entry_room(data, off)
        if len(blob) > room:
            raise ValueError(f"AFS entry +{off:#x}: {len(blob)} bytes > {room} bytes of room")
        out[off:off + room] = blob + bytes(room - len(blob))
        struct.pack_into("<I", out, 8 + 8 * offsets.index(off) + 4, len(blob))
    return bytes(out)


def pack_blobs(holes: list[tuple[int, int]], sizes: dict, home: dict | None = None, tries: int = 0) -> dict:
    """Best-fit-decreasing placement of 4-byte-aligned blobs into free [start, end) holes -> {key: offset}.
    home {key: offset}: first try each blob (largest first) in the hole holding that offset (a node's lists go
    back where its old lists were), then best-fit the rest. tries: when that fails, this many seeded random
    restarts (each blob into a random hole it fits, largest blobs first) before giving up - the holes sit
    between fixed node structs, so plain best fit can strand one big list a few bytes short. Raises ValueError
    (with free/needed totals and the first blob that found no hole) when they don't fit."""
    import random
    need = {k: (s + 3) & ~3 for k, s in sizes.items()}
    order = sorted(sizes, key=lambda k: (-need[k], str(k)))
    home = home or {}

    def attempt(rng=None):
        free = sorted([[h[0], h[1], h[0]] for h in holes if h[1] > h[0]])   # [next free, end, original start]
        at = {}
        for k in order if home and rng is None else ():
            h = next((h for h in free if k in home and h[2] <= home[k] < h[1]), None)
            if h is not None and h[1] - h[0] >= need[k]:
                at[k], h[0] = h[0], h[0] + need[k]
        for k in order:
            if k in at:
                continue
            fits = [h for h in free if h[1] - h[0] >= need[k]]
            if not fits:
                big = max((h[1] - h[0] for h in free), default=0)
                raise ValueError(f"{sum(need.values())} bytes of lists need placing, "
                                 f"{sum(h[1] - h[0] for h in holes)} bytes are free; {k} ({need[k]} bytes) "
                                 f"found no hole (largest left {big} bytes)")
            h = min(fits, key=lambda h: (h[1] - h[0], h[0])) if rng is None else rng.choice(fits)
            at[k], h[0] = h[0], h[0] + need[k]
        return at
    try:
        return attempt()
    except ValueError as e:
        first = e
    rng = random.Random(1155)
    for _ in range(tries):
        try:
            return attempt(rng)
        except ValueError:
            continue
    raise first


def group_texture_ids(data: bytes, play: int, ptex: int, roots: list[int]) -> tuple[int, dict[int, int]]:
    """(PTEX index of the body atlas, {draw-group root: the Ninja texture id that draws it in that group's texlist})."""
    groups, texlists = play_groups(data, play), ptex_texlists(data, ptex)
    atlas = atlas_texture(data, ptex, texlists)
    out = {}
    for r in roots:
        if r not in groups:
            raise ValueError(f"JGR body {r:#x} is not a draw group of the PLAY binding record")
        tl = texlists[groups.index(r)]
        if atlas not in tl:
            raise ValueError(f"JGR draw group {groups.index(r)} ({r:#x}) has no texture id for the body atlas "
                             f"(PTEX texture {atlas}); its texlist is {tl}")
        out[r] = tl.index(atlas)
    return atlas, out


def body_twins(buf: bytes, data: bytes, play: int, root: int) -> dict[int, list[dict]]:
    """Other textured full-body groups whose native bind state matches up to node-local translations.

    Parent counts alone cannot establish interchangeable local model coordinates. A group that moves only
    node-local positions (archive 04's gameplay bodies 0x8da4/0x2039c place hand node 15 elsewhere than the
    max-triangle body) is accepted: build_swap re-expresses the new geometry of every node whose bind origin
    moves in that group's own frame (`twin_offsets`), so the group's bind pose matches the primary's.
    Different rotations, scales or evaluation flags are still refused before fitting or rewriting.
    Selection of these groups remains runtime-unverified.
    """
    from . import ninja
    primary = ninja.tree_nodes(buf, root)
    parents = lambda nodes: [n["parent"] if n["parent"] is not None else -1 for n in nodes]
    if parents(primary) != BODY_PARENTS:
        raise ValueError("Primary JGR body does not match the verified 20-node graph")
    out = {}
    for candidate in play_model_roots(data, play):
        if candidate == root:
            continue
        try:
            nodes = ninja.tree_nodes(buf, candidate)
            if parents(nodes) != BODY_PARENTS:
                continue
            geometry = play_model(buf, candidate)
        except (ValueError, struct.error, IndexError, RecursionError) as error:
            raise ValueError(f"Cannot classify JGR draw group {candidate:#x}") from error
        if not any(texture >= 0 and faces for texture, faces in geometry.tris.items()):
            continue
        if any(a["trs"][12:] != b["trs"][12:] or (a["flags"] & ~8) != (b["flags"] & ~8)
               for a, b in zip(primary, nodes)):         # trs = pos 3f | ang 3i | scl 3f: only pos may move
            raise ValueError(f"JGR body group {candidate:#x} has a different native bind/evaluation state; "
                             "independent retargeting is required before rewriting it")
        out[candidate] = nodes
    return out


def _bind_world(nodes: list[dict]) -> list:
    """World bind matrices of a depth-first node list (Ninja UNIT_POS/ANG/SCL and ZXY_ANG flags honoured)."""
    from .ninja import _mat_mul, _node_matrix
    out = []
    for nd in nodes:
        fl = nd["flags"]
        pos = (0.0, 0.0, 0.0) if fl & 1 else struct.unpack_from("<3f", nd["trs"], 0)
        ang = (0, 0, 0) if fl & 2 else struct.unpack_from("<3i", nd["trs"], 12)
        scl = (1.0, 1.0, 1.0) if fl & 4 else struct.unpack_from("<3f", nd["trs"], 24)
        local = _node_matrix(pos, ang, scl, bool(fl & 0x20))
        out.append(local if nd["parent"] is None else _mat_mul(out[nd["parent"]], local))
    return out


def twin_offsets(primary: list[dict], twin: list[dict], tol: float = 1e-6) -> dict[int, tuple[float, float, float]]:
    """{node: local offset} that re-expresses primary-frame geometry in a translation-only twin's node frame.

    body_twins guarantees equal rotations, scales and evaluation flags, so inv(W_twin) @ W_primary is a pure
    translation for every node; adding it to the new vertices keeps the twin's bind pose identical."""
    import numpy as np
    out = {}
    for j, (a, b) in enumerate(zip(_bind_world(primary), _bind_world(twin))):
        m = np.linalg.inv(np.array(b, float)) @ np.array(a, float)
        if not np.allclose(m[:3, :3], np.eye(3), atol=1e-5):
            raise ValueError(f"JGR twin node {j} differs by more than a translation; independent retargeting is required")
        if float(np.abs(m[:3, 3]).max()) > tol:
            out[j] = tuple(float(x) for x in m[:3, 3])
    return out


def _material(buf: bytes, nodes: list[dict]) -> tuple[bytes, int, int, int]:
    from .sa2_chars import _first_material
    mat, tiny, texfl, strip = _first_material(buf, nodes)
    if not mat:
        raise ValueError("the body has no textured strip to copy the render state from")
    return mat, tiny, texfl, strip


def build_swap(gdi, model, roles: dict, work, name: str, index: int = 0, blender: str | None = None,
               progress=lambda p, m: None, scale: dict | None = None) -> dict:
    """-> {files {PLAYER_AFS: bytes}, report, rigged, atlas}: character `index`'s high-detail body drawn as `model`
    (rig `roles`). Its 20 node structs stay (so its motions drive the new mesh). Each rewritten node carries only its
    own new vertices (JGR vertex chunks are plain 0x29, not SA2's weighted ones, so no original chunk has to run
    first), placed at the node's native cache base and clamped so every slot stays inside the native vertex span of
    EVERY group that draws the shared models (`vertex_slots`): on Beat, slots 368-529 past the stock 0-354 (low LOD
    0-178) drew no body at all in gameplay while the cutscene renderer drew it (#1153 live, #1156). The new strips
    draw the body atlas (atlas_texture: the gameplay body's largest texlist texture, which becomes the character's
    atlas) under each group's own texlist id for it (group_texture_ids; #1396). The PLAY and PTEX entries are rewritten in
    their own AFS room, so PLAYER.AFS keeps its size; the model is decimated until it fits."""
    import numpy as np
    from pathlib import Path
    from . import ninja, ninja_swap as NS
    from .gdrom import GDRom
    data = GDRom(str(gdi)).read(PLAYER_AFS)
    play, ptex = character_pair(data, index)
    room = entry_room(data, play)
    buf = play_bytes(data, play)
    root = body_root(data, play)
    nj = play_model(buf, root)
    tgt = NS.target_from_nj(nj, {k: int(v[4:]) for k, v in BODY_ROLES.items()}, HEAD_NODES)
    nodes = ninja.tree_nodes(buf, root)
    if len(nodes) != len(BODY_PARENTS):
        raise ValueError(f"PLAY {index:02d} body has {len(nodes)} nodes, expected {len(BODY_PARENTS)}")
    mat, tiny_fl, tex_fl, strip_fl = _material(buf, nodes)
    twins = body_twins(buf, data, play, root)
    twin_nodes = [nd for group in twins.values() for nd in group]
    offsets = {g: twin_offsets(nodes, group) for g, group in twins.items()}
    # Each group draws the atlas under ITS texlist's id for it (Yo-Yo's spray-can bodies: id 1, the gameplay bodies:
    # id 0; #1396), so a twin whose id differs from the primary's gets its own copy of the strips, like a moved node.
    atlas, tex_ids = group_texture_ids(data, play, ptex, [root, *twins])
    prim_tex = tex_ids[root]

    def _copy_id(g, j):
        d, t = offsets[g].get(j), tex_ids[g]
        return None if d is None and t == prim_tex else (j, tuple(round(x, 6) for x in (d or (0.0, 0.0, 0.0))), t)
    copies = {}                                    # (node, offset, texture id) -> blob key >= 20; equal twins share it
    for g in twins:
        for j in range(len(nodes)):
            if _copy_id(g, j) is not None:
                copies.setdefault(_copy_id(g, j), len(nodes) + len(copies))

    def copy_key(g, j):
        c = _copy_id(g, j)
        return None if c is None else copies[c]
    spans = {}
    for group_root in [root, *twins]:
        cache = nj.vbuf if group_root == root else play_model(buf, group_root).vbuf
        if not cache:
            raise ValueError(f"JGR body group {group_root:#x} writes no vertex cache slots")
        spans[group_root] = max(cache) + 1
    vlimit = min(spans.values())                           # every group must find each new slot in its own span
    mine = {nd["off"] for nd in nodes + twin_nodes}
    others = []
    for r in play_model_roots(data, play):
        if r == root or r in twins:
            continue
        try:
            group = ninja.tree_nodes(buf, r)
        except (ValueError, struct.error, IndexError, RecursionError) as error:
            raise ValueError(f"Cannot protect JGR draw group {r:#x}") from error
        if any(nd["off"] in mine for nd in group):
            raise ValueError(f"JGR unselected draw group {r:#x} shares an object node with the replacement body; "
                             "independent retargeting is required before rewriting it")
        others += group

    def model_ranges(nds):
        rs = []
        for nd in nds:
            if nd["model"]:
                if not 0 <= nd["model"] <= len(buf) - 24:
                    raise ValueError("JGR model struct extends outside its PLAY entry")
                vl, pl_ = struct.unpack_from("<II", buf, nd["model"])
                rs.append((nd["model"], nd["model"] + 24))
                if vl:
                    rs.append((vl, vl + ninja.chunk_list_len(buf, vl, "v")))
                if pl_:
                    rs.append((pl_, pl_ + ninja.chunk_list_len(buf, pl_, "p")))
        if any(not 0 <= a < b <= len(buf) for a, b in rs):
            raise ValueError("JGR model lists extend outside their PLAY entry")
        return rs
    body = bytearray(buf)
    for a_, b_ in model_ranges(nodes + twin_nodes):
        body[a_:b_] = bytes(b_ - a_)
    shared = model_ranges(others)
    # Object structs are live selectors/animation data, never allocation holes.
    shared += [(nd["off"], nd["off"] + 52) for nd in nodes + twin_nodes + others]
    if any(not 0 <= a < b <= len(buf) for a, b in shared):
        raise ValueError("JGR draw-node structure extends outside its PLAY entry")
    for a_, b_ in shared:                                  # still drawn by another tree: keep
        body[a_:b_] = buf[a_:b_]
    freed = np.zeros(len(buf), bool)
    mine_r = sorted(model_ranges(nodes + twin_nodes))
    for a_, b_ in mine_r:
        freed[a_:b_] = True
    # the alignment padding between one node's lists (plist | 2 bytes | vlist | model) is dead too: without it
    # every node's room splits in two and the kept vertex lists no longer fit beside their new chunks (#1155)
    for (_a, b_), (c_, _d) in zip(mine_r, mine_r[1:]):
        if 0 < c_ - b_ < 4 and not any(buf[b_:c_]):
            freed[b_:c_] = True
    for a_, b_ in shared:
        freed[a_:b_] = False
    holes, i = [], 0
    while i < len(freed):
        if freed[i]:
            j = i
            while j < len(freed) and freed[j]:
                j += 1
            st_ = (i + 3) & ~3
            if j - st_ >= 32:
                holes.append([st_, j])
            i = j
        else:
            i += 1
    tail = (len(buf) + 3) & ~3
    spare = [(tail, room)] if room - tail >= 4 else []     # the AFS padding after the entry: a last resort

    def orig_base(nd):
        if not nd["model"]:
            return 0
        vl = struct.unpack_from("<I", buf, nd["model"])[0]
        return struct.unpack_from("<H", buf, vl + 4)[0] if vl else 0
    homes = {}                                             # where each node's old vlist / plist / model sat
    for j, nd in enumerate(nodes):
        if nd["model"]:
            vl, pl_ = struct.unpack_from("<II", buf, nd["model"])
            homes.update({("v", j): vl or nd["model"], ("p", j): pl_ or nd["model"], ("m", j): nd["model"]})
    for g, group in twins.items():                         # a re-expressed copy goes back where its twin's lists sat
        for j, nd in enumerate(group):
            key = copy_key(g, j)
            if key is not None and nd["model"] and ("m", key) not in homes:
                vl, pl_ = struct.unpack_from("<II", buf, nd["model"])
                homes.update({("v", key): vl or nd["model"], ("p", key): pl_ or nd["model"], ("m", key): nd["model"]})

    def encode(geo):
        # every blob (new-only vertex lists, poly lists, model structs) is sized
        # first, then packed into the freed holes + the entry's AFS padding together (pack_blobs), so a node
        # whose new lists outgrow its own hole no longer spills past the entry while other holes sit empty
        built, blobs = {}, {}
        for j, nd in enumerate(nodes):
            if j in geo:
                P, N, T = geo[j]
                if len(P) > vlimit:                         # ValueError: fit() retries a smaller budget
                    raise ValueError(f"node {j}: {len(P)} vertices > {vlimit} native vertex cache slots")
                built[j] = ninja.cnk_model_lists(P, N, T, prim_tex, mat, tiny_fl, tex_fl, strip_fl,
                                                 base=min(orig_base(nd), vlimit - len(P)))
                blobs[("v", j)] = built[j][0]
                blobs[("p", j)] = built[j][1]
            if nd["model"]:
                blobs[("m", j)] = bytes(24)
        for (j, d, t), key in copies.items():              # the same strips in a twin's own node frame / texlist
            if j in geo:
                P, N, T = geo[j]
                moved = [[p[0] + d[0], p[1] + d[1], p[2] + d[2]] for p in P]
                built[key] = ninja.cnk_model_lists(moved, N, T, t, mat, tiny_fl, tex_fl, strip_fl,
                                                   base=min(orig_base(nodes[j]), vlimit - len(P)))
                blobs[("v", key)] = built[key][0]
                blobs[("p", key)] = built[key][1]
                blobs[("m", key)] = bytes(24)
        if any(nd["model"] and j not in built for j, nd in enumerate(nodes)):
            blobs[("e", 0)] = struct.pack("<HH", 0xFF, 0)
        sizes = {k: len(v) for k, v in blobs.items()}
        at, err = None, None
        for hs in ([tuple(h) for h in holes], [tuple(h) for h in holes] + spare):   # inside the old entry first
            for hm in (homes, None):                        # node lists back home first, else pure best fit
                try:
                    at = pack_blobs(hs, sizes, hm, 0 if hm else 2000)
                    break
                except ValueError as e:
                    err = err or e
            if at is not None:
                break
        if at is None:
            raise ValueError(f"PLAY {index:02d}: {err}")
        out = bytearray(body)
        out += bytes(max(0, max(at[k] + len(v) for k, v in blobs.items()) - len(out)))
        for j, nd in enumerate(nodes):
            if j in built:
                _vl, _pl, c, r = built[j]
                blobs[("m", j)] = struct.pack("<II4f", at[("v", j)], at[("p", j)], *c, r)
            elif nd["model"]:
                c_r = struct.unpack_from("<4f", buf, nd["model"] + 8)
                blobs[("m", j)] = struct.pack("<II4f", at.get(("v", j), 0), at[("e", 0)], *c_r)
        for key in sorted(k for k in built if k >= len(nodes)):
            _vl, _pl, c, r = built[key]
            blobs[("m", key)] = struct.pack("<II4f", at[("v", key)], at[("p", key)], *c, r)
        for k, v in blobs.items():
            out[at[k]:at[k] + len(v)] = v
        for j, nd in enumerate(nodes):
            flags = nd["flags"] & ~0x8 if j in geo else nd["flags"]
            struct.pack_into("<II", out, nd["off"], flags, at.get(("m", j), 0))
        for g, group in twins.items():
            for j, nd in enumerate(group):
                flags = nd["flags"] & ~0x8 if j in geo else nd["flags"]
                key = copy_key(g, j)
                key = key if key is not None and key in built else j
                struct.pack_into("<II", out, nd["off"], flags, at.get(("m", key), 0))
        if len(out) > room:
            raise ValueError(f"PLAY {index:02d}: {len(out)} bytes > {room} bytes of AFS room")
        return bytes(out)
    progress(20, f"Fitting {name} to JGR character {index:02d}'s {len(nodes)} nodes")
    r = NS.fit(Path(model), roles, tgt, Path(work), name, BUDGETS, blender, encode, 256, scale, progress)
    progress(80, f"Encoding the texture atlas (PVR, PTEX texture {atlas}'s format)")
    from .ninja import pvr_like
    texs = ptex_textures(data, ptex)
    t0 = texs[atlas]
    new_t = pvr_like(t0["bytes"], r["atlas"])
    if len(new_t) != len(t0["bytes"]):
        raise ValueError(f"PTEX texture {atlas}: re-encoded {len(new_t)} bytes != {len(t0['bytes'])}")
    size = entry_size(data, ptex)
    pt = bytearray(data[ptex:ptex + size])
    pt[t0["offset"]:t0["offset"] + len(new_t)] = new_t
    afs = replace_entries(data, {play: r["data"], ptex: bytes(pt)})
    rep = r["report"] | {"character": f"{index:02d}", "archive_index": index,
                         "native_id": native_id_for_archive(data, index),
                         "source_afs_sha256": hashlib.sha256(data).hexdigest(),
                         "body_root": f"{root:#x}", "body_groups": [f"{r:#x}" for r in [root, *twins]],
                         "bind_offsets": {f"{g:#x}": {str(j): [round(x, 5) for x in d] for j, d in sorted(o.items())}
                                          for g, o in offsets.items() if o},
                         "body_selection": "max_triangles_unverified",
                         "runtime_verified": False, "play_bytes": len(r["data"]), "play_room": room,
                         "atlas": list(r["atlas"].size), "atlas_texture": atlas,
                         "texture_ids": {f"{g:#x}": t for g, t in tex_ids.items()}, "vertex_slots": vlimit,
                         "group_vertex_spans": {f"{k:#x}": v for k, v in spans.items()}}
    return {"files": {PLAYER_AFS: afs}, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def build_mod(cfg, meta: dict, game: dict, gdi, index: int = 0, progress=lambda p, m: None, root=None,
              *, identity: dict | None = None, name: str | None = None) -> dict:
    """Build into a new immutable mod directory; existing mods and target files are never overwritten."""
    import shutil
    import tempfile
    import time
    from . import characters as C, filemods
    from .gdrom import GDRom, patch_gdi
    root = root or C.library_root(cfg)
    model = root / meta["slug"] / meta["model"]
    actual = cache_identity(GDRom(str(gdi)).read(PLAYER_AFS), model, meta, game, index)
    if identity is not None and identity != actual:
        raise ValueError("JGR donor/source/target identity changed before building; no existing files were altered")
    identity = actual
    base_name = _mod_name(meta, index, identity)
    name = name or base_name
    if name != base_name and (not name.startswith(base_name + "_") or C.slugify(name) != name):
        raise ValueError("JGR build name must be an identity-derived safe mod name")
    gid = game["game_id"]
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto the JGR body")
    d = filemods.mod_dir(cfg, gid, name)
    tdir = root / meta["slug"] / "targets" / name
    if d.exists() or tdir.exists():
        raise ValueError(f"JGR output {name} already exists; its files were preserved. Rebuild through use to create a new output.")
    d.mkdir(parents=True, exist_ok=False)
    work_parent = Path(cfg.cache) / "characters_build"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jgr_", dir=work_parent) as scratch:
        b = build_swap(gdi, model, roles, Path(scratch), meta["name"], index, C._blender(cfg),
                       progress, (meta.get("rig") or {}).get("scale"))
        for key in ("archive_index", "native_id", "source_afs_sha256", "body_root"):
            if b["report"].get(key) != identity[key]:
                raise ValueError(f"JGR build changed {key}; refusing publication")
        if donor_fingerprint(model, roles, (meta.get("rig") or {}).get("scale")) != identity["donor_sha256"]:
            raise ValueError("JGR donor changed during building; refusing publication")
        tdir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(b["rigged"], tdir / "rigged.gltf")
        b["atlas"].save(tdir / "jgr_atlas.png")
        C.render_preview(tdir / "rigged.gltf", tdir / "jgr_preview.png")
        progress(85, "Writing the modded GD-ROM image (native draw-group verification still required)")
        img = patch_gdi(gdi, d, name, b["files"], progress)
        manifest = {"name": name, "game_id": gid, "image": img.name, "built": time.time(),
                    "files": sorted(b["files"]), "character": meta["slug"], "cache_identity": identity,
                    "report": json.loads(json.dumps(b["report"], default=str))}
        with (d / ".gbox-mod.json").open("x") as stream:
            json.dump(manifest, stream)
    return {"mod": name, "image": img.name, "report": b["report"], "rigged": str(tdir / "rigged.gltf")}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """Resolve an explicit target and validate offline cache identity before reuse or an immutable rebuild."""
    import uuid
    from . import characters as C, filemods
    from .gdrom import GDRom
    source = {}
    def load():
        if not source:
            source["gdi"] = C._dc_gdi(ctx, game)
            source["data"] = GDRom(str(source["gdi"])).read(PLAYER_AFS)
        return source["data"]
    index = swap_index(getattr(inp, "slot", None), load, getattr(inp, "active_id", None))
    root = C.library_root(ctx.config)
    identity = cache_identity(load(), root / meta["slug"] / meta["model"], meta, game, index)
    gid, name = game["game_id"], _mod_name(meta, index, identity)
    d = filemods.mod_dir(ctx.config, gid, name)
    legacy = filemods.mod_dir(ctx.config, gid, _mod_name(meta, index))
    rebuild = bool(getattr(inp, "rebuild", False))
    have = False
    if d.exists():
        if not rebuild:
            validate_cached_mod(d, identity, meta)
            have = True
        else:
            name += "_" + uuid.uuid4().hex[:12]
    elif legacy.exists() and not rebuild:
        raise ValueError(f"Legacy JGR mod {legacy.name} has no checked donor/source/target/root identity. "
                         "Its files were preserved; use rebuild=true to create a separate verified build.")
    built = None
    if not have:
        if not root.is_dir():
            raise ValueError("JGR swaps are built on the control-plane node (the Spark): run this there")
        built = build_mod(ctx.config, meta, game, source["gdi"], index, ctx.progress,
                          identity=identity, name=name)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": f"{index:02d}", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"Offline build for native ID {identity['native_id']}, archive {index:02d}, "
                              f"heuristic root {identity['body_root']}; {built['report']['triangles']} triangles. "
                              "Native drawn root and visible replacement are unverified; "
                              f"preview targets/{name}/jgr_preview.png"})
    out = {"mod": name, "build": built, "target": identity,
           "runtime_verified": False,
           "replaces": f"JGR native ID {identity['native_id']} / archive {index:02d}, "
                       f"heuristic body root {identity['body_root']} (native draw group unverified)"}
    if not getattr(inp, "launch", False):
        return out | {"status": "built" if built else "ready"}
    l = C._launch(ctx, gid, name, C.HOST_OS)
    return out | {"status": "built+launched" if built else "launched", "launch": l}
