"""Tony Hawk's Pro Skater 3 (USA) (GameCube) - owned-build inventory reader.

Stage 1 (inventory) of the native character-replacement pipeline for
game_id ``f44659a1b6a1c479``.

Owned source (never modified, read-only):
    /mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/
        Tony Hawk's Pro Skater 3 (USA).gcz

Container chain (all verified against the owned file):
    GCZ (Dolphin scrubbed image, magic 0xB10BC001)
      -> GameCube disc image (big-endian)
         -> disc header at 0x000 (game id 0x00, title 0x20, DOL 0x420, FST 0x424/0x428)
            -> FST: 12-byte entries {u8 is_dir, u24 name offset, u32 file offset,
                 u32 size}, entry 0 is the root, name table follows the entries.

Asset census of the owned build (FST walk, 4246 entries):
    323 .SKN meshes, 361 .tex texture containers, 281 .ska animation clips,
    874 .png board/logo/skin textures, 2077 .dsp audio streams, 148 .dff,
    36 .pre (preload lists), 17 .qb (script bytecode), 32 .dtk (audio),
    28 .h4m (video), 11 .hed (stream headers), 29 .bsp (collision),
    6 .fnt (font), 20 .prk, 1 .bnr (banner).

Character assets (this is what the replacement work targets):
    models/skater_m/   170 .SKN male skater body parts (head_*, shirt_*, pant_*,
                       shoe_*, Hat_*, Hair_*, Jaw_*, Tattoo_*, Extra_*, plus the
                       shared base mesh skater_m.SKN)
    models/skater_f/    43 .SKN female skater body parts (same layout)
    models/PedPro_*     pedestrian "pro" bodies (Koston, Muska, Glifberg, ...)
    models/Crowd_*, Ped_*, Bird_*, Shark_*, skater_slater, skater_maul, ...
    textures/skater_m/ 383 .png skin/board/logo textures
    anims/<set>/      .ska animation clips per model set

Formats verified here (big-endian; nothing here is copied from another title):
  .SKN  u32 version, u32 chunk_offset, u32 count, 13 x f32 matrix (bytes 12..64),
        then a 'NBCG' chunk at chunk_offset.
  .ska  'NACG' chunk at offset 0.
  .tex  32-byte header, 'GCTX' chunk at offset 32, then a NUL-terminated
        source PNG name (e.g. "CSKF_NH_Koston_face.png") and raw pixel data.
  .png  GCTX chunk at offset 0 (boards/logos) - same container, different offset.

Honest limits of this stage:
  * ``count`` in the .SKN header is captured verbatim; its meaning
    (bones / materials / primitives) is NOT proven yet.
  * The link between a character slot and the .SKN body part is inferred from
    naming plus the .pre/.qb script tables, not from the loader.
  * No pixel decoder for .tex/GCTX yet - only the container header is parsed.
"""

from __future__ import annotations

import hashlib
import os
import re
import struct

from .formats import gcfst
from .gcz import GCZ

SOURCE_PATH = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
               "Tony Hawk's Pro Skater 3 (USA).gcz")

SKN_CHUNK_MAGIC = b"NBCG"
SKA_CHUNK_MAGIC = b"NACG"
GCTX_MAGIC = b"GCTX"

# The base body mesh of the male skater: the slot a donor character replaces.
PRIMARY_SLOT = "models/skater_m/skater_m.SKN"
# A named character head, used as the second, small, easily eyeballed slot.
NAMED_SLOT = "models/skater_m/Head_Koston.SKN"

_PNG_NAME_RE = re.compile(rb"[A-Za-z0-9_./+\-]{5,}\.png")


# --------------------------------------------------------------------------- #
# source identity
# --------------------------------------------------------------------------- #
_MANIFEST_CACHE: dict = {}
_HASH_CACHE: dict = {}


def source_sha256(path: str = SOURCE_PATH, chunk: int = 1 << 20) -> str:
    """Stream the owned source and hash its bytes (never a copied reference)."""
    if path in _HASH_CACHE:
        return _HASH_CACHE[path]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    _HASH_CACHE[path] = h.hexdigest()
    return _HASH_CACHE[path]


# --------------------------------------------------------------------------- #
# container walk
# --------------------------------------------------------------------------- #
def manifest(path: str = SOURCE_PATH, with_hash: bool = True) -> dict:
    """Authoritative owned-build manifest: disc header + every FST member.

    Cached per process (path, with_hash); the hash is streamed once per process.
    """
    key = (path, bool(with_hash))
    if key not in _MANIFEST_CACHE:
        _MANIFEST_CACHE[key] = _manifest_uncached(path, with_hash)
    return _MANIFEST_CACHE[key]


def _manifest_uncached(path: str, with_hash: bool) -> dict:
    z = GCZ(path)
    try:
        header = z.read(0, 0x440)
        head = gcfst.disc_header(header)
        fst = z.read(head["fst_offset"], head["fst_size"])
        entries = gcfst.parse_fst(fst, head["fst_offset"])
        data_size = z.data_size
    finally:
        z.close()

    files = [{"path": p, "offset": o, "size": s} for p, o, s, _ in entries]
    ext: dict[str, int] = {}
    for f in files:
        base = os.path.basename(f["path"])
        key = ("." + base.rsplit(".", 1)[-1].lower()) if "." in base else "<none>"
        ext[key] = ext.get(key, 0) + 1

    out = {
        "source_path": path,
        "game_code": head["game_id"],
        "title": head["title"],
        "disc": {
            "fst_offset": head["fst_offset"],
            "fst_size": head["fst_size"],
            "dol_offset": head["dol_offset"],
            "data_size": data_size,
        },
        "file_count": len(files),
        "extensions": dict(sorted(ext.items(), key=lambda kv: (-kv[1], kv[0]))),
        "files": files,
    }
    if with_hash:
        out["source_sha256"] = source_sha256(path)
    return out


def read_members(path: str, members, manifest_data: dict | None = None) -> dict:
    """Read several FST members out of the owned source in one pass."""
    want = set(members)
    m = manifest_data if manifest_data is not None else manifest(path, with_hash=False)
    found = {f["path"]: f for f in m["files"] if f["path"] in want}
    missing = want - set(found)
    if missing:
        raise KeyError(f"members not in FST: {sorted(missing)}")
    out = {}
    z = GCZ(path)
    try:
        for name, f in found.items():
            out[name] = z.read(f["offset"], f["size"])
    finally:
        z.close()
    return out


def read_member(path: str, member: str, manifest_data: dict | None = None) -> bytes:
    return read_members(path, [member], manifest_data)[member]


# --------------------------------------------------------------------------- #
# format probes
# --------------------------------------------------------------------------- #
def skn_header(blob: bytes) -> dict:
    """Parse the .SKN header (big-endian).  Verified on every .SKN of the build."""
    if len(blob) < 68:
        raise ValueError("short .SKN blob")
    version, chunk_offset, count = struct.unpack_from(">III", blob, 0)
    matrix = struct.unpack_from(">13f", blob, 12)
    magic = b""
    if 0 < chunk_offset <= len(blob) - 4:
        magic = blob[chunk_offset:chunk_offset + 4]
    return {
        "version": version,
        "chunk_offset": chunk_offset,
        "count": count,
        "chunk_magic": magic.decode("latin-1"),
        "matrix": list(matrix),
        "size": len(blob),
    }


def tex_header(blob: bytes) -> dict:
    """Parse the .tex / GCTX texture container header."""
    g = blob.find(GCTX_MAGIC)
    m = _PNG_NAME_RE.search(blob)
    return {
        "gctx_offset": g,
        "name": m.group().decode("latin-1") if m else None,
        "size": len(blob),
    }


def ska_header(blob: bytes) -> dict:
    """Parse the .ska animation container header ('NACG' chunk)."""
    if len(blob) < 16:
        raise ValueError("short .ska blob")
    magic = blob[0:4]
    w = struct.unpack_from(">3I", blob, 4)
    return {"magic": magic.decode("latin-1"), "w1": w[0], "w2": w[1], "w3": w[2],
            "size": len(blob)}


# --------------------------------------------------------------------------- #
# character asset census
# --------------------------------------------------------------------------- #
def character_parts(m: dict) -> dict:
    """Map of model directory -> .SKN part names (counted from the FST)."""
    by_dir: dict[str, list[str]] = {}
    for f in m["files"]:
        p = f["path"]
        if p.lower().endswith(".skn"):
            d = os.path.dirname(p)
            by_dir.setdefault(d, []).append(os.path.basename(p)[:-4])
    return {d: sorted(v) for d, v in sorted(by_dir.items())}


def native_target(m: dict, path: str = SOURCE_PATH) -> dict:
    """The identified native target slot(s) with per-asset digests."""
    by_path = {f["path"]: f for f in m["files"]}
    out = {"slots": {}}
    for label, slot in (("primary", PRIMARY_SLOT), ("named", NAMED_SLOT)):
        if slot not in by_path:
            continue
        blob = read_member(path, slot, m)
        entry = {
            "mesh": slot,
            "size": by_path[slot]["size"],
            "sha256": hashlib.sha256(blob).hexdigest(),
            "header": skn_header(blob),
        }
        stem = os.path.splitext(slot)[0]
        for ext in (".tex",):
            cand = stem + ext
            for f in m["files"]:
                if f["path"].lower() == cand.lower():
                    tb = read_member(path, f["path"], m)
                    entry["texture"] = f["path"]
                    entry["texture_sha256"] = hashlib.sha256(tb).hexdigest()
                    entry["texture_header"] = tex_header(tb)
                    break
        out["slots"][label] = entry
    return out


def inventory(path: str = SOURCE_PATH) -> dict:
    """Stage 1 result: build identity + container layout + character census."""
    m = manifest(path, with_hash=True)
    parts = character_parts(m)
    return {
        "source": {
            "path": path,
            "sha256": m["source_sha256"],
            "game_code": m["game_code"],
            "title": m["title"],
        },
        "container": {"kind": "gcz", "disc": m["disc"], "file_count": m["file_count"]},
        "extensions": m["extensions"],
        "character_model_dirs": {d: len(v) for d, v in parts.items()},
        "skater_m_parts": parts.get("models/skater_m", []),
        "skater_f_parts": parts.get("models/skater_f", []),
        "target": native_target(m, path),
    }
