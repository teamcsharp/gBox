"""Star Fox - Assault (GameCube, product code GF7E01) native asset inventory.

Owned-build facts proved by this module (see the tests next to it):

* the disc image is a plain GameCube ISO: header magic 0xC2339F3D, game code
  ``GF7E01``, title ``STARFOX ASSAULT``, 962 FST members, ``main.dol`` as the
  executable.  The stock assimilation fingerprint guessed CRI Middleware
  (AFS/ADX/CPK) for this title, but the owned files carry no AFS/ADX/CPK
  container at all, so this module is the reader for the real build.
* stage and character payloads live in ``se/`` as C3D triplets::

      se/<name>.c3d   container / geometry header   magic b"C3Dp"
      se/<name>.chd   skeleton / character header   magic b"CHDp"
      se/<name>.cbd   the binary blob both headers point at

  100 complete triplets are present.  ``se_p`` is the player slot,
  ``vs_chr*`` are the versus characters (donor candidates).
* the first sixteen bytes of a .c3d / .chd header are big endian::

      0x00  u8[4]  magic          b"C3Dp" or b"CHDp"
      0x04  u16    version       0x0110 on every sampled asset
      0x06  u16    kind          asset type id (varies per asset)
      0x08  u16    count         element count of the table that follows
      0x0a  u16    table_offset  offset of that table inside this file
      0x0c  u32    blob_size     exact byte length of the matching .cbd

  ``blob_size`` is the join key: it equals the size of the ``<name>.cbd``
  member on the same disc, so every triplet is validated from the headers
  alone.  All 100 triplets match, which makes the join independent of any
  filename guess.

Member offsets come from the disc FST (``gbox.formats.gcfst``) and are
absolute byte offsets into the ISO image, so a member can be read back and
hashed without any intermediate copy.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

MAGIC_C3D = b"C3Dp"
MAGIC_CHD = b"CHDp"
HEADER_SIZE = 16
TRIPLET_DIR = "se/"
C3D_EXT = "c3d"
CHD_EXT = "chd"
CBD_EXT = "cbd"
PLAYER_SLOTS = ("se_p",)
VERSUS_PREFIX = "vs_chr"
TRIPLET_EXTS = (C3D_EXT, CHD_EXT, CBD_EXT)
CHUNK = 1 << 20


@dataclass
class C3DHeader:
    """Big endian header shared by the .c3d and .chd members of a triplet."""

    magic: str
    version: int
    kind: int
    count: int
    table_offset: int
    blob_size: int

    def to_json(self) -> dict:
        data = asdict(self)
        data["magic"] = self.magic
        return data


def parse_header(data: bytes, expect: bytes | None = None) -> C3DHeader:
    """Parse the 16 byte C3D/CHD header.  Raises ValueError on anything else."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"header truncated: need {HEADER_SIZE} bytes, have {len(data)}")
    magic = bytes(data[:4])
    if magic not in (MAGIC_C3D, MAGIC_CHD):
        raise ValueError(f"not a C3D/CHD header (magic {magic!r})")
    if expect is not None and magic != expect:
        raise ValueError(f"expected magic {expect!r}, got {magic!r}")
    version, kind, count, table_offset = struct.unpack_from(">HHHH", data, 4)
    (blob_size,) = struct.unpack_from(">I", data, 12)
    return C3DHeader(magic.decode("ascii"), version, kind, count, table_offset, blob_size)


def disc_identity(iso_path) -> dict:
    """GameCube disc header facts: code, revision, title and DOL offset."""
    with open(iso_path, "rb") as fh:
        h = fh.read(0x440)
    if len(h) < 0x440:
        raise ValueError("not a GameCube disc image (short header)")
    if struct.unpack_from(">I", h, 0x1C)[0] != 0xC2339F3D:
        raise ValueError("not a GameCube disc image (bad header magic)")
    dol_offset, fst_offset, fst_size = struct.unpack_from(">III", h, 0x420)
    return {
        "game_code": h[0x00:0x06].decode("ascii", "replace"),
        "disc_number": h[0x08:0x0A].decode("ascii", "replace"),
        "revision": h[0x0E],
        "maker_code": h[0x10:0x12].decode("ascii", "replace"),
        "disc_id": h[0x18:0x20].decode("ascii", "replace"),
        "title": h[0x20:0x60].split(b"\0")[0].decode("latin-1"),
        "dol_offset": dol_offset,
        "fst_offset": fst_offset,
        "fst_size": fst_size,
    }


def member_table(iso_path) -> dict:
    """{path: (offset, size)} for every member of the disc image.

    Offsets are absolute byte offsets into the ISO image, as stored in the
    GameCube FST entries.
    """
    from .formats import gcfst
    with open(iso_path, "rb") as fh:
        header = gcfst.disc_header(fh.read(0x440))
        fh.seek(header["fst_offset"])
        fst = fh.read(header["fst_size"])
    return {path: (off, size) for path, off, size, _entry in gcfst.parse_fst(fst, header["fst_offset"])}


def read_member(iso_path, member_path, expected_size: int | None = None, table: dict | None = None) -> bytes:
    """Read one member out of the disc image using its FST offset."""
    table = member_table(iso_path) if table is None else table
    if member_path not in table:
        raise KeyError(f"member {member_path!r} not found in {iso_path!r}")
    offset, size = table[member_path]
    if expected_size is not None and size != expected_size:
        raise ValueError(f"{member_path}: FST says {size} bytes, expected {expected_size}")
    with open(iso_path, "rb") as fh:
        fh.seek(offset)
        data = fh.read(size)
    if len(data) != size:
        raise ValueError(f"{member_path}: short read ({len(data)} of {size} bytes)")
    return data


def source_sha256(iso_path) -> str:
    """SHA-256 of the owned source image, streamed (never a copied reference)."""
    digest = hashlib.sha256()
    with open(iso_path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def group_triplets(entries) -> dict:
    """Join ``se/`` listing entries into {name: {c3d: entry, chd: entry, cbd: entry}}."""
    joined: dict = {}
    for entry in entries:
        path = entry["path"]
        if not path.startswith(TRIPLET_DIR):
            continue
        stem, _, ext = path.rpartition(".")
        if ext.lower() not in TRIPLET_EXTS:
            continue
        name = stem[len(TRIPLET_DIR):] if stem.startswith(TRIPLET_DIR) else stem
        joined.setdefault(name, {})[ext.lower()] = entry
    return joined


def character_roster(triplets: dict) -> list:
    """Rows for every complete triplet, with the role gBox can prove from names."""
    rows = []
    for name, slot in sorted(triplets.items()):
        if not all(ext in slot for ext in TRIPLET_EXTS):
            continue
        role = "asset"
        if name in PLAYER_SLOTS:
            role = "player"
        elif name.startswith(VERSUS_PREFIX):
            role = "versus_character"
        rows.append({
            "name": name,
            "role": role,
            "c3d_size": slot[C3D_EXT]["size"],
            "chd_size": slot[CHD_EXT]["size"],
            "cbd_size": slot[CBD_EXT]["size"],
        })
    return rows


def describe_disc(iso_path) -> dict:
    """Manifest of the owned build: disc identity, triplets, blob cross-check."""
    table = member_table(iso_path)
    ident_dol_offset = disc_identity(iso_path)["dol_offset"]
    entries = [{"path": path, "size": size, "offset": off} for path, (off, size) in table.items()]
    triplets = group_triplets(entries)
    roster = character_roster(triplets)
    matched = 0
    checked = 0
    mismatches = []
    headers = []
    for row in roster:
        slot = triplets[row["name"]]
        try:
            head_c3d = parse_header(read_member(iso_path, slot[C3D_EXT]["path"], table=table))
            head_chd = parse_header(read_member(iso_path, slot[CHD_EXT]["path"], table=table))
        except ValueError:
            continue
        checked += 1
        blob_ok = head_c3d.blob_size == row["cbd_size"] == head_chd.blob_size
        if blob_ok:
            matched += 1
        else:
            mismatches.append({"name": row["name"], "c3d_blob": head_c3d.blob_size,
                               "chd_blob": head_chd.blob_size, "cbd_size": row["cbd_size"]})
        headers.append({"name": row["name"], "role": row["role"],
                        "c3d": head_c3d.to_json(), "chd": head_chd.to_json(),
                        "cbd_size": row["cbd_size"], "blob_size_match": blob_ok})
    manifest = {
        "source": str(iso_path),
        "kind": "gc_disc",
        # A GameCube disc keeps main.dol outside the FST, at the header's DOL offset.
        "executable": "main.dol" if ident_dol_offset else None,
        "dol_offset": ident_dol_offset,
        "file_count": len(entries),
        "triplet_count": len(roster),
        "blob_size_checked": checked,
        "blob_size_matched": matched,
        "blob_size_mismatches": mismatches,
        "roster": roster,
        "asset_headers": headers,
    }
    manifest.update(disc_identity(iso_path))
    return manifest


def read_asset(iso_path, name) -> dict:
    """Read one full triplet (.c3d/.chd/.cbd) and parse both headers."""
    table = member_table(iso_path)
    entries = [{"path": path, "size": size, "offset": off} for path, (off, size) in table.items()]
    slot = group_triplets(entries)[name]
    out = {"name": name}
    for ext in TRIPLET_EXTS:
        entry = slot[ext]
        out[ext] = read_member(iso_path, entry["path"], entry["size"], table=table)
    out["header"] = parse_header(out[C3D_EXT]).to_json()
    out["chd_header"] = parse_header(out[CHD_EXT]).to_json()
    out["sha256"] = {ext: hashlib.sha256(out[ext]).hexdigest() for ext in TRIPLET_EXTS}
    return out
