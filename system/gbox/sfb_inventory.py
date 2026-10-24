"""Strike Force Bowling (GameCube, G5BE4Z) owned-build inventory.

The owned build is the Dolphin ``.gcz`` container that ships in the HyperSpin
GameCube collection::

    collections/Nintendo GameCube/roms/Strike Force Bowling (USA).gcz

The disc it wraps is a GameCube ISO whose header game code is ``G5BE4Z`` and
whose title is ``Strike Force Bowling``.  This module produces an
authoritative manifest of every file on that disc by walking the GameCube
filesystem table (FST) with the shared ``gbox.formats.gcfst`` reader on top of
the shared ``gbox.gcz`` random-access reader.  The owned ROM is opened
read-only; nothing is ever written back to it.

Role classification uses directory and extension evidence only.  A member is
never called a character or a stage on the strength of its filename: the
``GCNFUCs`` group is reported as a *candidate* container set with
``role = "unverified"`` until the loader that consumes it is located.

Manifest shape::

    {
      "source":  {"path", "container", "file_size", "data_size",
                  "block_size", "num_blocks", "sha256"?},
      "disc":    {"game_code", "maker_code", "title", "endianness",
                  "main_dol_offset", "fst_offset", "fst_size"},
      "members": [{"path", "offset", "size", "ext", "kind", "group",
                   "role", "header_hex", "sha256"?}],
      "counts":  {"by_ext": {...}, "by_kind": {...}, "by_group": {...}},
      "candidates": {"fuc_containers": [...], "textures": [...],
                     "executables": [...]},
    }
"""

from __future__ import annotations

import hashlib
import os
import struct

from .formats.gcfst import parse_fst
from .gcz import GCZ

#: Disc game code / title of the owned build (verified against the disc header).
SFB_GAME_CODE = "G5BE4Z"
SFB_TITLE = "Strike Force Bowling"

#: Candidate locations of the owned source, most specific first.
ROM_CANDIDATES = (
    os.environ.get("GBOX_SFB_ROM", ""),
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
    "Strike Force Bowling (USA).gcz",
    "/home/ehm_eckx/gBox/system/gbox-data/collections/Nintendo GameCube/roms/"
    "Strike Force Bowling (USA).gcz",
)

KIND_BY_EXT = {
    ".dol": "executable",
    ".elf": "executable",
    ".bnr": "banner",
    ".tpl": "texture_container",
    ".spd": "audio_stream",
    ".spt": "audio_table",
    ".fuc": "fuc_container",
    ".ddf": "ddf_data",
}

GROUP_BY_DIR = {
    "GCNFUCs": "gcnfucs",
    "GCNSND1": "gcnsnd1",
    "GCNSND2": "gcnsnd2",
}

DEFAULT_HEADER_BYTES = 16


def find_owned_rom():
    """Return the path of the owned Strike Force Bowling container, or None."""
    for cand in ROM_CANDIDATES:
        if cand and os.path.exists(cand):
            return cand
    return None


def classify_member(path):
    """Return ``(ext, kind, group)`` for one FST member path.

    ``kind`` comes from the file extension, ``group`` from the containing
    directory.  Neither is a claim about the content of the file.
    """
    ext = os.path.splitext(path)[1].lower()
    kind = KIND_BY_EXT.get(ext, "data")
    parts = path.split("/")
    group = GROUP_BY_DIR.get(parts[0], "root") if len(parts) > 1 else "root"
    return ext, kind, group


def read_disc_header(gz):
    """Read the GameCube disc header (big-endian) from an open GCZ reader."""
    head = gz.read(0, 0x440)
    if len(head) < 0x440:
        raise ValueError("truncated disc header")
    main_dol_offset, fst_offset, fst_size = struct.unpack(">III", head[0x420:0x42C])
    return {
        "game_code": head[0x00:0x06].decode("latin-1").strip("\0 "),
        "maker_code": head[0x06:0x08].decode("latin-1").strip("\0 "),
        "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
        "endianness": "big",
        "main_dol_offset": main_dol_offset,
        "fst_offset": fst_offset,
        "fst_size": fst_size,
    }


def _sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def build_manifest(path, hash_members=False, hash_paths=None,
                   hash_kinds=None, hash_container=False,
                   header_bytes=DEFAULT_HEADER_BYTES):
    """Build the authoritative owned-build manifest for ``path``.

    ``hash_paths`` / ``hash_kinds`` restrict which members get a streamed
    sha256 (the full disc is ~1.2 GiB of members, so hashing everything is
    slow).  ``hash_container`` hashes the container file itself.
    """
    gz = GCZ(path)
    try:
        disc = read_disc_header(gz)
        fst = gz.read(disc["fst_offset"], disc["fst_size"])
        members = []
        for mpath, offset, size, _entry in parse_fst(fst, disc["fst_offset"]):
            ext, kind, group = classify_member(mpath)
            rec = {
                "path": mpath,
                "offset": offset,
                "size": size,
                "ext": ext,
                "kind": kind,
                "group": group,
                "role": "unverified",
            }
            if size:
                rec["header_hex"] = gz.read(offset, min(header_bytes, size)).hex()
            want_hash = hash_members
            if hash_paths and mpath in set(hash_paths):
                want_hash = True
            if hash_kinds and kind in set(hash_kinds):
                want_hash = True
            if want_hash and size:
                rec["sha256"] = gz.sha256_range(offset, size)
            members.append(rec)
            gz._cache.clear()          # keep memory flat over a whole-disc walk
        source = {
            "path": path,
            "container": "gcz",
            "file_size": gz.file_size,
            "data_size": gz.data_size,
            "block_size": gz.block_size,
            "num_blocks": gz.num_blocks,
        }
    finally:
        gz.close()

    members.sort(key=lambda r: r["path"])
    by_ext, by_kind, by_group = {}, {}, {}
    for rec in members:
        by_ext[rec["ext"]] = by_ext.get(rec["ext"], 0) + 1
        by_kind[rec["kind"]] = by_kind.get(rec["kind"], 0) + 1
        by_group[rec["group"]] = by_group.get(rec["group"], 0) + 1
    if hash_container:
        source["sha256"] = _sha256_file(path)
    return {
        "source": source,
        "disc": disc,
        "members": members,
        "counts": {"by_ext": by_ext, "by_kind": by_kind, "by_group": by_group},
        "candidates": {
            "fuc_containers": [r for r in members if r["kind"] == "fuc_container"],
            "textures": [r for r in members if r["kind"] == "texture_container"],
            "executables": [r for r in members if r["kind"] == "executable"],
        },
    }
