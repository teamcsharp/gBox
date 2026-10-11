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


# ---------------------------------------------------------------- native collection (gbox.characters)
PLAYER_AFS = "JETRADIO/PLAYER.AFS"
CHARACTER_COUNT = 16


def roster() -> list[dict]:
    """The 16 PLAY/PTEX character pairs of PLAYER.AFS, in archive order.

    Character names are not read from the disc yet, so entries use their archive index; aliases
    carry the index so a pick-whip label such as "JGR character 3" still resolves.
    """
    return [{"key": f"{i:02d}", "slug": f"jgr_char{i:02d}", "name": f"Jet Grind Radio character {i:02d}",
             "aliases": [f"JGR character {i}", f"JGR char {i:02d}", f"PLAYER.AFS PLAY {i}"], "kind": "character"}
            for i in range(CHARACTER_COUNT)]


def character_pair(data: bytes, index: int) -> tuple[int, int]:
    """(PLAY offset, PTEX offset) of character *index*: the archive stores them as consecutive pairs."""
    ch = chunks(data)
    plays = [o for k, o in ch if k == "play"]
    ptexs = [o for k, o in ch if k == "ptex"]
    if len(plays) != CHARACTER_COUNT or len(ptexs) != CHARACTER_COUNT:
        raise ValueError(f"PLAYER.AFS holds {len(plays)} PLAY / {len(ptexs)} PTEX chunks, expected {CHARACTER_COUNT}")
    return plays[index], ptexs[index]


def body_root(data: bytes, play_off: int) -> int:
    """The high-detail body: the 20-node root with the most triangles (variant 0 on ties)."""
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
    root = body_root(data, play)
    ctx.progress(50, f"Decoding PLAY +{play:#x} body root +{root:#x}")
    glb = export_play_glb(data, play, root, str(work), e["slug"], ptex)
    out = {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.jgr + gbox.ninja",
           "source_files": [f"{PLAYER_AFS} PLAY #{int(e['key'])} (+{play:#x}, root +{root:#x})",
                            f"{PLAYER_AFS} PTEX #{int(e['key'])} (+{ptex:#x})"],
           "notes": "High-detail body, variant 0, bind pose. Texture ids bind to PTEX order (ids 0-2 verified on "
                    "character 00 only). No in-game writer yet."}
    try:
        out["roles"] = body_roles(glb)
    except Exception as exc:                               # noqa: BLE001 - report instead of inventing roles
        out["notes"] += f" Rig roles not derived: {exc}"
    return out


# ---- native swap writer: a library character -> one PLAYER.AFS body (gbox.ninja_swap pipeline, as gbox.sa2_chars) ----
BUDGETS = (1400, 1150, 950, 800, 650, 500, 400, 300)
ATLAS_TEXTURE = 0                       # the PTEX texture the new strips draw (it's replaced by the character's atlas)
HEAD_NODES = {10, 11}


def swap_index(slot: str | None) -> int:
    """characters op=use slot -> PLAYER.AFS character index: 'player' (= 00), 'NN', 'jgr_charNN' or 'char:NN'."""
    s = (slot or "player").strip().lower()
    if s == "player":
        return 0
    digits = s.rsplit("char", 1)[-1].lstrip(":_ ")
    if not digits.isdigit() or not 0 <= int(digits) < CHARACTER_COUNT:
        raise ValueError(f"slot {slot!r}: use 'player' or a JGR character index 00-{CHARACTER_COUNT - 1:02d}")
    return int(digits)


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


def _material(buf: bytes, nodes: list[dict]) -> tuple[bytes, int, int, int]:
    from .sa2_chars import _first_material
    mat, tiny, texfl, strip = _first_material(buf, nodes)
    if not mat:
        raise ValueError("the body has no textured strip to copy the render state from")
    return mat, tiny, texfl, strip


def build_swap(gdi, model, roles: dict, work, name: str, index: int = 0, blender: str | None = None,
               progress=lambda p, m: None, scale: dict | None = None) -> dict:
    """-> {files {PLAYER_AFS: bytes}, report, rigged, atlas}: character `index`'s high-detail body drawn as `model`
    (rig `roles`). Its 20 node structs stay (so its motions drive the new mesh); every node keeps its original vertex
    chunks (the game's skinning reads them), the new vertices go after them in the vertex cache and the new strips
    draw those with PTEX texture 0, which becomes the character's atlas. The PLAY and PTEX entries are rewritten in
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
    mine = {nd["off"] for nd in nodes}
    others = []
    for r in play_model_roots(data, play):
        if r == root:
            continue
        try:
            others += [nd for nd in ninja.tree_nodes(buf, r) if nd["off"] not in mine]
        except Exception:                                  # noqa: BLE001 - a non-tree record: nothing to keep
            continue

    def model_ranges(nds):
        rs = []
        for nd in nds:
            if nd["model"]:
                vl, pl_ = struct.unpack_from("<II", buf, nd["model"])
                rs.append((nd["model"], nd["model"] + 24))
                if vl:
                    rs.append((vl, vl + ninja.chunk_list_len(buf, vl, "v")))
                if pl_:
                    rs.append((pl_, pl_ + ninja.chunk_list_len(buf, pl_, "p")))
        return rs
    body = bytearray(buf)
    for a_, b_ in model_ranges(nodes):
        body[a_:b_] = bytes(b_ - a_)
    shared = model_ranges(others)
    for a_, b_ in shared:                                  # still drawn by another tree: keep
        body[a_:b_] = buf[a_:b_]
    freed = np.zeros(len(buf), bool)
    for a_, b_ in model_ranges(nodes):
        freed[a_:b_] = True
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

    def orig_vlist(nd):
        if not nd["model"]:
            return b""
        vl = struct.unpack_from("<I", buf, nd["model"])[0]
        return buf[vl:vl + ninja.chunk_list_len(buf, vl, "v") - 4] if vl else b""
    vbase = (max(nj.vbuf) + 1 + 15) & ~15 if nj.vbuf else 0

    def home_of(nd):                                      # the freed hole that held this node's own lists
        if not nd["model"]:
            return None
        vl = struct.unpack_from("<I", buf, nd["model"])[0] or nd["model"]
        return next((k for k, h in enumerate(holes) if h[0] <= vl < h[1]), None)

    def encode(geo):
        out = bytearray(body)
        out += bytes((-len(out)) % 32)
        padded = len(out)
        free = [h[:] for h in holes]

        def alloc(blob, home=None):                         # the node's own hole first (each node's lists sit
            size = (len(blob) + 3) & ~3                     # between node structs), else best fit, else the end
            if home is not None and free[home][1] - free[home][0] >= size:
                h = free[home]
            else:
                fits = [h for h in free if h[1] - h[0] >= size]
                h = min(fits, key=lambda h: h[1] - h[0]) if fits else None
            if h is not None:
                o, h[0] = h[0], h[0] + size
            else:
                o = len(out)
                out.extend(bytes(size))
            out[o:o + len(blob)] = blob
            return o
        # vertex lists first, each into its node's hole (they hold the kept original chunks, the biggest part)
        built, vls = {}, {}
        for j, nd in enumerate(nodes):
            keep = orig_vlist(nd)
            if j in geo:
                P, N, T = geo[j]
                built[j] = ninja.cnk_model_lists(P, N, T, ATLAS_TEXTURE, mat, tiny_fl, tex_fl, strip_fl,
                                                 base=vbase, keep_vlist=keep)
                vls[j] = alloc(built[j][0], home_of(nd))
            elif keep:
                vls[j] = alloc(keep + struct.pack("<I", 0xFF), home_of(nd))
        ep, lists = None, {}
        for j in sorted(range(len(nodes)), key=lambda j: -len(built[j][1]) if j in built else 0):
            nd = nodes[j]
            if j in built:
                _vl, pl_, c, r = built[j]
                lists[j] = (vls[j], alloc(pl_, home_of(nd)), c, r)
            elif nd["model"]:
                if ep is None:
                    ep = alloc(struct.pack("<HH", 0xFF, 0))
                c_r = struct.unpack_from("<4f", buf, nd["model"] + 8)
                lists[j] = (vls.get(j, 0), ep, list(c_r[:3]), c_r[3])
        for j, nd in enumerate(nodes):
            mo = 0
            if j in lists:
                vo, po, c, r = lists[j]
                mo = alloc(struct.pack("<II4f", vo, po, *c, r), home_of(nd))
            flags = nd["flags"] & ~0x8 if j in geo else nd["flags"]
            struct.pack_into("<II", out, nd["off"], flags, mo)
        if len(out) == padded:                              # nothing landed at the end: keep the old length
            del out[len(buf):]
        if len(out) > room:
            raise ValueError(f"PLAY {index:02d}: {len(out)} bytes > {room} bytes of AFS room")
        return bytes(out)
    progress(20, f"Fitting {name} to JGR character {index:02d}'s {len(nodes)} nodes")
    r = NS.fit(Path(model), roles, tgt, Path(work), name, BUDGETS, blender, encode, 256, scale, progress)
    progress(80, "Encoding the texture atlas (PVR, PTEX texture 0's format)")
    from .ninja import pvr_like
    texs = ptex_textures(data, ptex)
    t0 = texs[ATLAS_TEXTURE]
    new_t = pvr_like(t0["bytes"], r["atlas"])
    if len(new_t) != len(t0["bytes"]):
        raise ValueError(f"PTEX texture {ATLAS_TEXTURE}: re-encoded {len(new_t)} bytes != {len(t0['bytes'])}")
    size = entry_size(data, ptex)
    pt = bytearray(data[ptex:ptex + size])
    pt[t0["offset"]:t0["offset"] + len(new_t)] = new_t
    afs = replace_entries(data, {play: r["data"], ptex: bytes(pt)})
    rep = r["report"] | {"character": f"{index:02d}", "play_bytes": len(r["data"]), "play_room": room,
                         "atlas": list(r["atlas"].size), "atlas_texture": ATLAS_TEXTURE, "vertex_base": vbase}
    return {"files": {PLAYER_AFS: afs}, "report": rep, "rigged": r["rigged"], "atlas": r["atlas"]}


def build_mod(cfg, meta: dict, game: dict, gdi, index: int = 0, progress=lambda p, m: None, root=None) -> dict:
    """On the control plane: jgr_<slug>_<NN> = a copy of the GD-ROM image with character NN's body replaced."""
    import json
    import shutil
    import time
    from pathlib import Path
    from . import characters as C, filemods
    from .gdrom import patch_gdi
    root = root or C.library_root(cfg)
    gid, name = game["game_id"], f"jgr_{meta['slug']}_{index:02d}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto the JGR body")
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "jgr"
    shutil.rmtree(work, ignore_errors=True)
    b = build_swap(gdi, root / meta["slug"] / meta["model"], roles, work, meta["name"], index, C._blender(cfg),
                   progress, (meta.get("rig") or {}).get("scale"))
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b["rigged"], tdir / f"jgr_{index:02d}.gltf")
    b["atlas"].save(tdir / "jgr_atlas.png")
    C.render_preview(tdir / f"jgr_{index:02d}.gltf", tdir / "jgr_preview.png")
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    progress(85, "Writing the modded GD-ROM image")
    img = patch_gdi(gdi, d, name, b["files"], progress)
    (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": gid, "image": img.name, "built": time.time(),
                                                  "files": sorted(b["files"]), "character": meta["slug"],
                                                  "report": json.loads(json.dumps(b["report"], default=str))}))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img.name, "report": b["report"], "rigged": str(tdir / f"jgr_{index:02d}.gltf")}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Jet Grind Radio (DC): build jgr_<slug>_<NN> on the control plane, then launch it."""
    from . import characters as C, filemods
    index = swap_index(getattr(inp, "slot", None))
    gid, name = game["game_id"], f"jgr_{meta['slug']}_{index:02d}"
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
    built = None
    if getattr(inp, "rebuild", False) or not have:
        if not C.library_root(ctx.config).is_dir():
            raise ValueError("JGR swaps are built on the control-plane node (the Spark): run this there")
        built = build_mod(ctx.config, meta, game, C._dc_gdi(ctx, game), index, ctx.progress)
        C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
               json={"game_id": gid, "slot": f"{index:02d}", "mod": name, "nodes": [C.HOST_OS],
                     "notes": f"replaces JGR character {index:02d}'s high-detail body (its 20 nodes and motions; "
                              f"{built['report']['triangles']} triangles, PTEX texture 0 = atlas); "
                              "preview targets/jgr_preview.png"})
    out = {"mod": name, "build": built,
           "replaces": f"JGR character {index:02d} (high-detail body; skeleton, motions and lower-detail bodies stay)"}
    if not getattr(inp, "launch", False):
        return out | {"status": "built" if built else "ready"}
    l = C._launch(ctx, gid, name, C.HOST_OS)
    return out | {"status": "built+launched" if built else "launched", "launch": l}
