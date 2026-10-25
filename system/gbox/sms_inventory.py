"""Super Mario Sunshine (USA) owned-build inventory: source identity, the Yaz0/RARC asset census and the one
identified native character-asset target.

The owned build is a Dolphin .gcz image of GameCube game id GMSE01. Its FST holds 174 files: 122 Yaz0-compressed
.szs archives, 21 .thp videos, 24 .aw audio banks, 3 .bin tables, plus .asn/.arc/.afc and the .bnr banner. Every
.szs decodes to a RARC archive whose members are the native asset family:

    .bmd  model (J3D2bmd3)     .bdl/.bmt  model variants    .btk/.bti  texture
    .bck/.btp/.brk  animation   .bas/.col  motion/collision  .jpa  joint pose

Counted from the owned image, not guessed: 48,144 RARC members, of which 8,784 are .bmd models. The one identified
native target asset is data/mario.szs!bmd/ma_mdl1.bmd -- Mario's body model.

Read-only: nothing here writes to the owned image. The model reader/writer is a later stage.
"""
from __future__ import annotations

import hashlib
import os
import struct

from .formats import rarc
from .formats.lz import yaz0_decompress
from .gcdisc import GCDisc

GAME_ID = "GMSE01"
TITLE = "Super Mario Sunshine"
TARGET_ARCHIVE = "data/mario.szs"
TARGET_MEMBER = "bmd/ma_mdl1.bmd"
BMD_MAGIC = b"J3D2bmd3"
GAME_ID_SLUG = "d98bd83133ac8d4c"


def sha256_file(path: str) -> str:
    """Streamed SHA-256 of the bytes actually on disk (never a copied reference hash)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_identity(path: str) -> dict:
    """Authoritative owned-source identity: path, size and the streamed hash of the owned bytes."""
    return {"path": os.path.abspath(path), "bytes": os.path.getsize(path), "sha256": sha256_file(path)}


def owned_source_path(cache_root: str | None = None, game_id: str = GAME_ID_SLUG) -> str | None:
    """The staged owned image for this game inside the gBox cache, or None when it is not staged.

    The owned build is a staged cache copy, not a loose ROM in the working directory: a filesystem sweep of the
    task workspace finds nothing. Look it up by catalog id instead.
    """
    roots = [cache_root] if cache_root else [
        os.environ.get("GBOX_CACHE"),
        "/home/ehm_eckx/gBox_alt/gbox-cache",
        "/home/ehm_eckx/gbox-cache",
    ]
    for root in roots:
        if not root:
            continue
        folder = os.path.join(root, game_id)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".gcz", ".iso", ".gcm")):
                return os.path.join(folder, name)
    return None


def disc_header(path: str) -> dict:
    """Game id, title and file count read from the owned image's disc header and FST."""
    d = GCDisc(path)
    try:
        return {"game_id": d.game_id, "title": d.title, "file_count": len(d.files)}
    finally:
        d.f.close()


def disc_files(path: str) -> list:
    """[(member path, size, disc offset)] for every file in the owned image's FST."""
    d = GCDisc(path)
    try:
        return sorted((name, size, off) for name, (off, size) in d.files.items())
    finally:
        d.f.close()


def read_disc_file(path: str, member: str) -> bytes:
    """The raw bytes of one FST file (still Yaz0-compressed when the member is a .szs)."""
    d = GCDisc(path)
    try:
        return d.read(member)
    finally:
        d.f.close()


def decode_szs(raw: bytes) -> bytes:
    """Yaz0 -> RARC payload for one .szs archive."""
    if raw[:4] != b"Yaz0":
        raise ValueError("not a Yaz0 archive")
    return yaz0_decompress(raw)


def szs_members(payload: bytes) -> list:
    """[(member path, payload offset, size)] for every member of a decoded RARC archive."""
    return [(m[0], m[1], m[2]) for m in rarc.walk(payload)]


def member_bytes(payload: bytes, member: str) -> bytes:
    """The bytes of one RARC member; the extent is bounded by the archive payload."""
    for name, off, size in szs_members(payload):
        if name != member:
            continue
        if off < 0 or size < 0 or off + size > len(payload):
            raise ValueError(f"{member}: RARC member extent outside the archive payload")
        return payload[off:off + size]
    raise KeyError(f"{member}: not present in the archive")


def bmd_probe(blob: bytes) -> dict:
    """Header facts of one native J3D model (big-endian). Only fields proven against the owned build are
    reported; the section table after the header is an unproved hypothesis and is not guessed here."""
    if len(blob) < 0x24 or blob[:8] != BMD_MAGIC:
        raise ValueError("not a J3D2bmd3 model")
    file_size, pad = struct.unpack_from(">2I", blob, 8)
    return {
        "magic": blob[:4].decode("ascii"),
        "version": blob[4:8].decode("ascii"),
        "file_size": file_size,
        "pad": pad,
        "section_tag": blob[0x10:0x14].decode("ascii", "replace"),
        "inf_tag": blob[0x20:0x24].decode("ascii", "replace"),
        "byte_order": "big-endian",
    }


def census_archives(path: str, archives=None) -> list:
    """One entry per .szs archive: member count, member bytes and the extension histogram."""
    out = []
    for name, size, off in disc_files(path):
        if not name.endswith(".szs"):
            continue
        if archives is not None and name not in archives:
            continue
        payload = decode_szs(read_disc_file(path, name))
        members = szs_members(payload)
        hist = {}
        for member, _o, msize in members:
            ext = os.path.splitext(member)[1].lower() or "<none>"
            hist[ext] = hist.get(ext, 0) + 1
        out.append({"archive": name, "archive_bytes": size, "archive_offset": off,
                    "decoded_bytes": len(payload), "members": len(members), "extensions": hist})
    return out


def target_asset(path: str) -> dict:
    """The one identified native target asset: Mario's body model inside data/mario.szs."""
    payload = decode_szs(read_disc_file(path, TARGET_ARCHIVE))
    members = dict((m, (o, s)) for m, o, s in szs_members(payload))
    if TARGET_MEMBER not in members:
        raise KeyError(f"{TARGET_MEMBER}: not present in {TARGET_ARCHIVE}")
    off, size = members[TARGET_MEMBER]
    blob = member_bytes(payload, TARGET_MEMBER)
    archive_offset = dict((n, o) for n, _s, o in disc_files(path))[TARGET_ARCHIVE]
    return {"archive": TARGET_ARCHIVE, "member": TARGET_MEMBER, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "member_offset": off, "member_size": size,
            "archive_offset": archive_offset, "archive_encoding": "Yaz0", "bmd": bmd_probe(blob)}


def inventory(path: str, census: bool = True) -> dict:
    """The authoritative owned-build manifest: source identity, disc header, every FST file, the Yaz0/RARC member
    census and the one identified native target asset."""
    files = disc_files(path)
    out = {
        "source": source_identity(path),
        "disc": disc_header(path),
        "files": [{"path": p, "bytes": s, "offset": o} for p, s, o in files],
        "archives": sum(1 for p, _s, _o in files if p.endswith(".szs")),
        "target": target_asset(path),
    }
    if census:
        out["census"] = census_archives(path)
    return out
