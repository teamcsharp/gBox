"""Metal Gear Online (PS3, NPMG00020) target-asset identification probes.

Read-only. Locates one DAR member (the inventory target) and parses the
big-endian MDN and .slot headers observed on the owned build. Header fields
are recorded as observed; nothing here decodes geometry or reimports.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from . import savemgo_assets as assets

# Inventory target: owned SaveMGO.zip, NPMG00020/USRDIR, stage r_onlinelobby.
TARGET_ARCHIVE = "o/stage/r_onlinelobby/resident.dar"
TARGET_MEMBER = "mgo_head08_Bhat.mdn"
TARGET_ARCHIVE_SHA256 = "a8f66721df7eead2dac6c5ebfd4d1b4a26f874d99e8a2b69773dfb224d055f6f"
TARGET_MEMBER_SHA256 = "42694f4f788954edba139fea299d84d80ed0a4a2fb439e137c526c3fdb830734"
TARGET_MEMBER_SIZE = 15952
MDN_HEADER_WORDS = 24


def parse_mdn_header(blob: bytes) -> dict:
    """Parse the leading big-endian u32 words of an MDN model."""
    if len(blob) < 0x60 or blob[:4] != b"MDN ":
        raise ValueError("Not an MDN model")
    words = list(struct.unpack_from(">%dI" % (MDN_HEADER_WORDS - 1), blob, 4))
    declared = words[-1]
    if declared != len(blob):
        raise ValueError("MDN declared size does not match member size")
    return {"magic": "MDN ", "word1": words[0], "words": words, "declared_size": declared,
            "bounds_floats": list(struct.unpack_from(">8f", blob, 0x60))}


def parse_slot_header(blob: bytes) -> dict:
    """Parse the cleartext .slot header: u32 id, u16 1, u16 1, u16 count, u16 0, u32 1."""
    if len(blob) < 16:
        raise ValueError("Truncated slot header")
    ident, one_a, one_b, count, zero, one_c = struct.unpack_from(">IHHHHI", blob)
    if (one_a, one_b, zero, one_c) != (1, 1, 0, 1) or count == 0:
        raise ValueError("Unexpected slot header")
    return {"id": ident, "count": count}


def locate_member(path: Path, archive: str = TARGET_ARCHIVE, name: str = TARGET_MEMBER) -> dict:
    """Return identity (archive sha, member offset/size/sha) of one DAR member."""
    index, decoded = assets._archive(assets.data_root(path), archive)
    for row in index["members"]:
        if row["name"] == name:
            blob = decoded[row["offset"]:row["offset"] + row["size"]]
            return {"archive": archive, "archive_sha256": index["sha256"], "logical_stage": index["logical_stage"],
                    "member": name, "index": row["index"], "offset": row["offset"], "size": row["size"],
                    "kind": row["kind"], "sha256": hashlib.sha256(blob).hexdigest(), "blob": blob}
    raise ValueError("Member not found")
