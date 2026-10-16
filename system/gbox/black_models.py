"""Black (PS2, SLUS_213.76): Criterion Black-engine cast reader (reconnaissance stage).

Request #1965 (23273c9c660d43c5): the title has zero registered replaceable slots, so a
native reader must exist before the Sonic cast build can be a real native mod. This module
holds the verified disc/format findings and the parsing we can already prove; the geometry
codec (WDD vertex streams), the DB skeleton/animation blocks and the .WDO resource table
remain the reader's open stages (see docs/black-ps2.md in the PR).

Verified evidence (request #1965 checkpoints):
* Owned disc: ISO9660 DVD, 3,919,609,856 bytes, unpacked from the owned CHD. PS2, not Xbox
  (the catalog's mixed Microsoft XBOX display label is wrong metadata).
* Executable: SLUS_213.76, PS2 ELF, cpu r5900, entry 0x00100008, 3,371,868 bytes,
  sha256 141b05209570458af9c8e27ab1911f258da6353909d813cd572df026254ffe4c
  (re_executable job 740e1951f57f4f89, receipt db9c7866100a404a).
* Ghidra analysis.json artifact sha256
  c6ad95c3f1a6ccefff1f3589f4f7c1249873c861250a2048cc91fb5046f03048
  (analyze_binary job e97b31b617164a6c, result_sha256 c4576e7e3803f3552b15e263c2b9787c1d2e8a1458fe04029a4c0590205baa9c):
  8027 functions / 2524 strings; the ELF is fully stripped (only `entry` + thunks).
* Loader string-xref sites (lui/addiu immediate pairs into the string section; LOADER_SITES
  pins them as a regression test): 0x1368c8 references the "AI gun model not found: %s"
  format string (the gun-model loader), 0x1abd00 / 0x1abd64 load `chars\\trans_ch.bin` /
  `chars\\trans_fp.bin`, 0x1d69a4..0x1d6b4c build the `chars\\guns\\GrdPin.wdo` /
  `GrdLnchr.wdo` file table, 0x3243bc owns the RwaRPCTransfer DMA error path. No plain
  u32 pointer tables reference these strings, so the loaders take the addresses in code.
* Cast assets: CHARS/BG1_<weapon>.WDD + .DB pairs, 31 weapon variants (AK1..SNR) plus
  GRDLNCHR/GRDPIN gun objects. The same BG1_AK1.WDD extent (lba 1251201, sha256
  e2c1cb3f...) is shared by CHARS/, CHARS/FPGUNS/, CHARS/STG_0001/ and CHARS/FRONTEND/
  directory records (hardlinks, not copies). Every WDD is exactly 65536 bytes; the
  matching DB is 557247..725139 bytes. DB tails hold ASCII names (e.g. "FireSelect") and
  the same PS2 RAM pointers the .WDO records carry.
* .WDO object container (GRDLNCHR.WDO, 211 bytes): u32 magic 0x0809, u32 file size,
  resource records with absolute EE-RAM pointers (0x0043cd60, 0x0043e008, 0x01120104,
  0x0148d00), trailing ASCII name "GrdLnchr" + "LF" extension.
* .DB skeleton table (BG1_*.DB, all 31 variants): the FPS arms rig is stored as 24-byte
  records of null-terminated ASCII bone names, anchored at the literal "World" bone and
  terminated by the first non-printable record. Every variant carries the same shared
  upper-body chain (World, Extra, Root, Shoulder/Elbow/Joint_wrist_twist/Wrist _lft/_rt,
  four fingers + thumb _lft/_rt) and then a WEAPON-SPECIFIC tail (AssualtRifle_* for the
  AK/AS families, Pistol_* for GK, Shotgun_* for GRL, grenade bones for BNS, ...). The
  skeleton is an FPS arms rig: there are no leg, spine, neck or head bones, and the cast
  "body" is the weapon-holding arms seen in first person. This is the skeleton the
  Sonic retarget must bind onto. An offset table of u32 (stride 0x18) sits immediately
  before the name table and holds ABSOLUTE file offsets into a contiguous
  ``nBones x 24``-byte bone-record block that begins right after the DB header; the
  header is ``0x70 + 72*nBones`` bytes (3 x 24-byte records per bone). The region
  after the name table is float32 animation data (rotation tracks plus "FireSelect"
  event markers at 0x84975 / 0xa01ec in BG1_AK1); the per-bone records and the WDD
  vertex streams are the remaining decode stages before read_model()/to_glb().
* .DB fixed header (0x70 bytes) is a section directory (db_header/db_sections): three
  lead-record pairs (second word carries a 0x5446-prefixed revision), a section count
  (always 9), a 0x80 stride word, then 9 absolute section offsets. In order: 4 data
  blocks, one animation block (magic 0x8161d7c0), a data block, 2 RIFF/WAVE audio
  chunks (48 kHz 16-bit mono PCM weapon samples), and a trailing .WDO object (magic
  0x0809) whose size field equals the remaining file length.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Callable

from .formats.iso9660 import pvd_root, walk

DISC = Path.home() / "gbox-cache" / "modbase" / "858ac1ab12044c9c" / "Black (USA).iso"
ELF = (Path.home() / "gBox" / "system" / "gbox-data" / "analysis" / "re" / "858ac1ab12044c9c"
       / "SLUS_213.76.elf")
ELF_SHA256 = "141b05209570458af9c8e27ab1911f258da6353909d813cd572df026254ffe4c"
ELF_ENTRY = 0x00100008

# Weapon suffixes of the soldier body variants on the owned disc (CHARS/BG1_*.WDD).
CAST_WEAPONS = ("AK1", "AK5", "AS5", "ASR", "BNS", "GK1", "GK5", "GRL", "HV5", "HVY", "M16",
                "M45", "MC5", "MG5", "MGN", "MP1", "MP5", "P90", "P95", "PS5", "PST", "RM1",
                "RM5", "RPG", "SH5", "SHG", "SM3", "SM5", "SMG", "SN5", "SNR")

# Addresses of the loader format strings in the ELF and the code sites whose lui/addiu
# immediates reference them (scanned from the owned ELF on the Spark, 2026-10-15).
LOADER_SITES = {
    # (string address, string fragment) -> [code VA, ...]
    0x3F4848: ("AI gun model not found: %s", [0x1368C8]),
    0x3F7020: (r"chars\trans_ch.bin", [0x1ABD00]),
    0x3F7038: (r"chars\trans_fp.bin", [0x1ABD64]),
    0x3F75D8: (r"chars\guns\GrdPin.wdo", [0x1D6A1C]),
    0x3F7608: (r"chars\guns\GrdLnchr.wdo", [0x1D6B4C]),
    0x40A040: ("EE  RwaRPCTransfer : ERROR!", [0x3243BC]),
}
ELF_LOAD_SEG = (0x1000, 0x100000)           # (file offset, vaddr) of the single LOAD segment


class FormatError(ValueError):
    pass


def disc_files(iso: Path | str | None = None) -> list[tuple[str, int, int]]:
    """(path, lba, size) of every file on the owned disc, directory hardlinks deduped.

    The plain walk reports the same extent once per directory record; CHARS/FPGUNS/,
    CHARS/STG_0001/ and CHARS/FRONTEND/ re-list the CHARS/ files, so dedupe on
    (path, lba, size) before counting.
    """
    iso = Path(iso) if iso else DISC
    f = open(iso, "rb")
    f.seek(16 * 2048)
    pvd = f.read(2048)
    root_lba, root_size = pvd_root(pvd)
    seen: set[tuple[str, int, int]] = set()
    rows: list[tuple[str, int, int]] = []

    def read(lba: int, n: int) -> bytes:
        f.seek(lba * 2048)
        return f.read(n * 2048)

    for path, rec, _ in walk(read, root_lba, root_size):
        full = "/".join(path + (rec.name,))
        key = (full, rec.lba, rec.size)
        if key in seen:
            continue
        seen.add(key)
        rows.append((full, rec.lba, rec.size))
    return rows


def list_cast(iso: Path | str | None = None) -> dict:
    """The replaceable cast on the owned disc: BG1 soldier bodies and gun objects.

    Every weapon variant ships one 65536-byte .WDD (geometry) and one ~0.6 MB .DB
    (skeleton/animation); the body mesh differs per variant, so the cast is
    per-weapon-variant, not one shared body.
    """
    found: dict[str, dict] = {}
    for path, lba, size in disc_files(iso):
        parts = path.split("/")
        if len(parts) != 2 or not parts[0].upper() == "CHARS":
            continue
        name = parts[1].upper()
        if name.startswith("BG1_") and name.endswith((".WDD", ".DB")):
            slot = name[: name.rfind(".")]
            found.setdefault(slot, {})[name[name.rfind(".") :]] = {"lba": lba, "size": size}
        elif name in ("GRDLNCHR.WDO", "GRDLNCHR.WDD", "GRDPIN.WDO", "GRDPIN.WDD"):
            found.setdefault(name, {})["lba"] = lba
            found.setdefault(name, {})["size"] = size
    return found


def parse_wdo(data: bytes) -> dict:
    """GRDLNCHR.WDO-style object container: magic, size, resource records, name.

    Record layout hypothesis (validated on the 211-byte GRDLNCHR.WDO): u32 magic 0x0809,
    u32 0, u32 total file size, then 0x2c-byte resource records holding {u32 size/offset
    pairs and absolute EE-RAM pointers in 0x00100000..0x02000000}, then the ASCII name
    with its 2-byte extension at the end.
    """
    if len(data) < 0x10:
        raise FormatError("WDO shorter than 16 bytes")
    magic, _, size = struct.unpack_from("<3I", data, 0)
    if magic != 0x0809:
        raise FormatError(f"WDO magic 0x{magic:04x}, expected 0x0809")
    if size != len(data):
        raise FormatError(f"WDO size field {size} != file size {len(data)}")
    # trailing name: last record of the file, after the resource table
    tail = data.rstrip(b"\x00")
    name = tail[tail.rfind(b"\x00") + 1 :].decode("ascii", "replace") if b"\x00" in tail else ""
    ram_ptrs: list[int] = []
    for o in range(0x10, min(len(data) - 4, 0x100), 4):
        v = struct.unpack_from("<I", data, o)[0]
        if 0x00100000 <= v <= 0x01FFFFFF:
            ram_ptrs.append(v)
    return {"magic": magic, "size": size, "name": name, "ram_ptrs": ram_ptrs}


def wdd_census(data: bytes) -> dict:
    """Structural census of a 65536-byte BG1_*.WDD geometry stream.

    The streams are small-byte quantized payloads with zero padding at the end; the
    record framing (16-byte [type][sub][payload] records) is parsed by wdd_records().
    Census = verified invariants only: fixed size, padded tail, first-word
    plausibility.
    """
    if len(data) != 65536:
        raise FormatError(f"WDD size {len(data)}, every BG1 WDD is exactly 65536 bytes")
    # first u32 is small and non-zero on every variant inspected
    head = struct.unpack_from("<I", data, 0)[0]
    if head == 0 or head > 0x00FFFFFF:
        raise FormatError(f"implausible WDD first word 0x{head:08x}")
    tail = data.rstrip(b"\x00")
    return {"size": len(data), "head": head, "zero_pad": len(data) - len(tail)}


WDD_SIZE = 65536
WDD_RECORD = 16
# The WDD record type byte is (stream_id << 4) | attr_id: the high nibble selects
# one of 5 sub-streams (0..4), the low nibble one of 13 attribute/record kinds
# (0..12). Verified on every data and pointer record of all 31 BG1_*.WDD
# (2026-10-16, 81,539 sub-2 records, 65 distinct types): bit 7 is always clear,
# high nibble <= 4, low nibble <= 12. The 14-byte payload is 14 independent
# quantized signed-byte channels (no index/short field), so a record is a
# per-(stream, attr) operand block, not a packed vertex with an inline bone index.
WDD_STREAMS = 5
WDD_ATTRS = 13


def wdd_records(data: bytes) -> list[tuple[int, int, bytes]]:
    """The 16-byte record stream of a BG1_*.WDD geometry blob.

    Verified on the owned disc (all 31 BG1_<weapon>.WDD, 2026-10-16): a WDD is a run
    of 4096 16-byte records, each ``[u8 type][u8 sub][14-byte payload]``.

    * ``sub`` is 0x02 (data record), 0x03 (a handful of table/pointer records — 10 in
      BG1_AK1, with non-zero types) or 0x00 (zero padding: type 0, payload all zero;
      these form the file tail).
    * The type byte stays below 0x80 on data records (0x00..0x4f on the owned disc).
    * The 14-byte payload is quantized attribute data as *signed bytes*, not 7 x i16:
      byte values cluster at 0, ±1, ±16 (0x10/0xf0), ±31 (0x1f/0xe1), ±32 (0x20/0xe0).
      Reading two adjacent small bytes as one little-endian i16 fabricates large values
      (0x7778 / 0x8888 = ±30584) that are an artifact, not a stored 16-bit quantity.
    """
    if len(data) != WDD_SIZE:
        raise FormatError(f"WDD size {len(data)}, every BG1 WDD is exactly {WDD_SIZE} bytes")
    return [(data[o], data[o + 1], data[o + 2:o + WDD_RECORD])
            for o in range(0, WDD_SIZE, WDD_RECORD)]


def wdd_summary(data: bytes) -> dict:
    """Framing census of a BG1_*.WDD: per-sub record counts and zero-padding split."""
    recs = wdd_records(data)
    subs: dict[int, int] = {}
    zero_pad = 0
    for _t, sub, payload in recs:
        subs[sub] = subs.get(sub, 0) + 1
        if sub == 0:
            zero_pad += 1
    return {"records": len(recs), "subs": subs, "zero_pad_records": zero_pad}


def wdd_type(t: int) -> tuple[int, int]:
    """Decode a WDD record type byte into ``(stream_id, attr_id)``.

    The type byte is ``(stream_id << 4) | attr_id``: high nibble = one of
    ``WDD_STREAMS`` sub-streams (0..4), low nibble = one of ``WDD_ATTRS``
    attribute/record kinds (0..12). Verified across all 31 BG1_*.WDD (2026-10-16):
    bit 7 is always clear, the high nibble never exceeds 4, and the low nibble
    never exceeds 12. This supersedes the earlier "type < 0x80" observation and
    gives the reader its stream/attribute axes.
    """
    if t < 0 or t > 0x7F:
        raise FormatError(f"WDD type 0x{t:02x} has bit 7 set")
    stream, attr = t >> 4, t & 0x0F
    if stream >= WDD_STREAMS:
        raise FormatError(f"WDD type 0x{t:02x} stream {stream} >= {WDD_STREAMS}")
    if attr >= WDD_ATTRS:
        raise FormatError(f"WDD type 0x{t:02x} attr {attr} >= {WDD_ATTRS}")
    return stream, attr


def wdd_type_census(data: bytes) -> dict:
    """(stream, attr) record-kind census of a WDD, validating every type byte.

    Every record's type (including the zero-padding tail, which is type 0) must
    decode via wdd_type(); data (sub 2) records are tallied into ``streams`` /
    ``attrs`` / ``kinds``, and pointer (sub 3) records into ``pointer``.
    """
    recs = wdd_records(data)
    streams: dict[int, int] = {}
    attrs: dict[int, int] = {}
    kinds: dict[tuple[int, int], int] = {}
    pointer: dict[int, dict[int, int]] = {}
    data_records = 0
    for t, sub, _p in recs:
        stream, attr = wdd_type(t)
        if sub == 2:
            data_records += 1
            streams[stream] = streams.get(stream, 0) + 1
            attrs[attr] = attrs.get(attr, 0) + 1
            kinds[(stream, attr)] = kinds.get((stream, attr), 0) + 1
        elif sub == 3:
            m = pointer.setdefault(stream, {})
            m[attr] = m.get(attr, 0) + 1
    return {
        "records": len(recs),
        "data_records": data_records,
        "streams": streams,
        "attrs": attrs,
        "kinds": kinds,
        "pointer": pointer,
    }


def wdd_runs(data: bytes) -> dict:
    """Split a WDD into its primitive runs, delimited by pointer (sub 3) records.

    A WDD is not a flat vertex array: it is a list of mesh primitives. Each
    primitive is a run of sub-2 data records terminated by a single sub-3 pointer
    record, followed by 2..8 sub-0 padding records that align the next run; the
    last run is followed by the zero-padding tail. Verified on all 31 owned
    BG1_*.WDD (2026-10-16): every variant has the same pointer -> padding -> data
    structure, with 10 primitives in BG1_AK1 (data-run lengths 893, 132, 221, 269,
    181, 267, 215, 219, 130, 144). The pointer record's (stream, attr) type marks
    the primitive that just ended.

    Returns ``runs`` as ``(start, count)`` data-record spans, ``pointers`` as
    ``(index, stream, attr)`` in file order, and ``padding`` as ``(start, count)``
    spans (the final span is the tail).
    """
    recs = wdd_records(data)
    runs: list[tuple[int, int]] = []
    pointers: list[tuple[int, int, int]] = []
    padding: list[tuple[int, int]] = []
    run_start = 0
    i = 0
    n = len(recs)
    while i < n:
        _t, sub, _p = recs[i]
        if sub == 2:
            i += 1
            continue
        if sub == 3:
            if i > run_start:
                runs.append((run_start, i - run_start))
            stream, attr = wdd_type(_t)
            pointers.append((i, stream, attr))
            j = i + 1
            while j < n and recs[j][1] == 0:      # alignment padding records
                j += 1
            if j > i + 1:
                padding.append((i + 1, j - i - 1))
            run_start = j
            i = j
            continue
        break                                    # sub 0 tail without a pointer
    if run_start < n:
        padding.append((run_start, n - run_start))
    return {"runs": runs, "pointers": pointers, "padding": padding}


# .DB skeleton name table: a run of 24-byte records (null-terminated ASCII name, zero
# padded) anchored at the literal "World" bone. The FPS arms rig has no leg/spine/neck/
# head bones: it is the weapon-holding arms the player sees. The weapon-specific tail
# (AssualtRifle_*, Pistol_*, Shotgun_*, grenade bones, ...) varies per BG1_<weapon> slot.
SKEL_ANCHOR = b"World\x00"
BONE_RECORD = 24
# The DB header (bytes 0..bone_records start) is BONE_HEADER_FIXED bytes of fixed
# data plus BONE_HEADER_PER bytes per skeleton bone (3 x 24-byte records). Verified
# on every BG1_*.DB: a 42-bone variant header is 0xC40, 43-bone is 0xC88, 44-bone is
# 0xCD0 — each = 0x70 + 72*nBones. The offset table (see db_bone_offset_table) holds
# ABSOLUTE file offsets into the contiguous nBones x 24-byte bone-record block that
# begins immediately after this header.
BONE_HEADER_FIXED = 0x70
BONE_HEADER_PER = 72

# The .DB fixed header (0x70 bytes) is a section directory: three u32 lead-record
# pairs (the second word of each has a constant DB_REV_PREFIX high half and a
# per-asset revision low half), a section count, a 0x80 stride/flags word, then that
# many ABSOLUTE file offsets of the file's sections. Verified on every owned
# BG1_*.DB (2026-10-16): the count is always 9 and the 9 sections follow a fixed
# order (see db_sections).
DB_REV_PREFIX = 0x5446          # constant high half of the three lead-record revision words
DB_HEADER_U32 = 17              # u32 words parsed from the 0x70-byte fixed header
DB_SECTION_COUNT = 9            # section count on every owned BG1_*.DB
WAV_MAGIC = b"RIFF"
WDO_MAGIC = b"\x09\x08\x00\x00"  # same magic as the .WDO object container
ANIM_MAGIC = 0x8161D7C0          # little-endian bytes c0 d7 61 81, DB section 4

# Bones that are the always-present FPS arms chain (not the weapon), in file order.
# Pinned from the owned disc; the weapon-specific bones sit between Wrist_rt and the
# right-hand finger chain (or, in a few variants, replace part of the finger chain).
SHARED_FPS_BONES = frozenset({
    "World", "Extra", "Root",
    "Shoulder_lft", "Elbow_lft", "Joint_wrist_twist", "Wrist_lft",
    "Finger1_Top_lft", "Finger1_Mid_lft", "Finger1_Tip_lft",
    "Finger2_Top_lft", "Finger2_Mid_lft", "Finger2_Tip_lft",
    "Finger3_Top_lft", "Finger3_Mid_lft", "Finger3_Tip_lft",
    "Finger4_Top_lft", "Finger4_Mid_lft", "Finger4_Tip_lft",
    "Thumb_Top_lft", "Thumb_Mid_lft", "Thumb_Tip_lft",
    "Shoulder_rt", "Elbow_rt", "Wrist_rt",
    "Finger1_Top_rt", "Finger1_Mid_rt", "Finger1_Tip_rt",
    "Finger2_Top_rt", "Finger2_Mid_rt", "Finger2_Tip_rt",
    "Finger3_Top_rt", "Finger3_Mid_rt", "Finger3_Tip_rt",
    "Finger4_Top_rt", "Finger4_Mid_rt", "Finger4_Tip_rt",
    "Thumb_Top_rt", "Thumb_Mid_rt", "Thumb_Tip_rt",
})


def db_skeleton(db: bytes) -> list[str]:
    """Ordered bone names of the FPS arms rig stored in a BG1_*.DB file.

    Walks 24-byte records from the "World" anchor, decoding each null-terminated ASCII
    name, and stops at the first record that is empty or non-printable (the table's
    trailing edge). Weapon-specific bones are included, in their file position.
    """
    anchor = db.find(SKEL_ANCHOR)
    if anchor < 0:
        raise FormatError("DB has no skeleton anchor 'World'")
    bones: list[str] = []
    off = anchor
    while off + BONE_RECORD <= len(db):
        rec = db[off:off + BONE_RECORD]
        end = rec.find(b"\x00")
        if end <= 0:
            break
        name = rec[:end]
        if not name or any(b < 0x20 or b > 0x7E for b in name):
            break  # first non-printable record terminates the table
        bones.append(name.decode("ascii"))
        off += BONE_RECORD
    return bones


def db_weapon_bones(db: bytes) -> list[str]:
    """The weapon-specific bones of a BG1_*.DB skeleton (bones outside SHARED_FPS_BONES).

    These vary per weapon family and are the slots a native cast writer must rebuild
    alongside the shared arms. Empty only if the file carries no weapon-specific bones.
    """
    return [b for b in db_skeleton(db) if b not in SHARED_FPS_BONES]


def db_bone_offset_table(db: bytes) -> dict:
    """The u32 offset table that immediately precedes the skeleton name table.

    A dense little-endian u32 array sits right before the "World" anchor; its values
    step by BONE_RECORD (24) and are ABSOLUTE file offsets into the contiguous
    per-bone record block that begins just after the DB header (see db_bone_records).
    On the owned disc the table has one entry per skeleton bone (BG1_AK1: 44 entries,
    0x0cd0..0x10d8, matching its 44 bone names). Returns the anchor, the ascending
    offset list, the table's file position, and the bone-record block bounds.
    """
    anchor = db.find(SKEL_ANCHOR)
    if anchor < 0:
        raise FormatError("DB has no skeleton anchor 'World'")
    offsets: list[int] = []
    o = anchor - 4
    while o >= 0:
        v = struct.unpack_from("<I", db, o)[0]
        if offsets and offsets[0] - v != BONE_RECORD:
            break
        offsets.insert(0, v)
        o -= 4
    if not offsets:
        raise FormatError("no bone offset table before the skeleton anchor")
    return {
        "anchor": anchor,
        "table_offset": o + 4,
        "offsets": offsets,
        "block_start": offsets[0],
        "block_end": offsets[-1] + BONE_RECORD,
    }


def db_bone_records(db: bytes) -> dict:
    """The contiguous per-bone record block the offset table points at.

    Each u32 in the offset table is an absolute file offset; the nBones records it
    addresses form one contiguous ``nBones x 24``-byte block that starts immediately
    after the DB header. Verified on every BG1_*.DB: the block start satisfies
    ``block_start == BONE_HEADER_FIXED + BONE_HEADER_PER * nBones`` (0xC40 / 0xC88 /
    0xCD0 for 42 / 43 / 44 bones), so the header holds 3 x 24-byte records per bone.
    The records' payload is heterogeneous (quantized key data plus small index/flag
    words) and remains the open decode stage.
    """
    tbl = db_bone_offset_table(db)
    offs = tbl["offsets"]
    n = len(offs)
    if offs[0] != BONE_HEADER_FIXED + BONE_HEADER_PER * n:
        raise FormatError(
            f"bone-record block start {offs[0]:#x} != 0x{BONE_HEADER_FIXED + BONE_HEADER_PER * n:x}"
        )
    if offs[-1] + BONE_RECORD > len(db):
        raise FormatError("bone-record block runs past end of DB")
    records = [db[o:o + BONE_RECORD] for o in offs]
    return {
        "count": n,
        "block_start": offs[0],
        "block_end": offs[-1] + BONE_RECORD,
        "records": records,
    }


def db_header(db: bytes) -> dict:
    """The fixed 0x70-byte header of a BG1_*.DB container.

    Layout (little-endian u32): three lead-record word-pairs, then a section count,
    a 0x80 stride/flags word, then that many ABSOLUTE file offsets of the file's
    sections. Verified on all 31 owned BG1_*.DB (2026-10-16): the count is always
    ``DB_SECTION_COUNT`` (9); each lead record's second word keeps the constant
    ``DB_REV_PREFIX`` high half with a monotonically increasing per-asset low half
    (a revision stamp, not a fixed sentinel).
    """
    if len(db) < 0x70:
        raise FormatError(f"DB shorter than its 0x70-byte header ({len(db)} bytes)")
    vals = struct.unpack_from(f"<{DB_HEADER_U32}I", db, 0)
    count = vals[6]
    if count < 1 or count > DB_SECTION_COUNT:
        raise FormatError(f"DB section count {count} outside 1..{DB_SECTION_COUNT}")
    return {
        "lead": [(vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])],
        "count": count,
        "flags": vals[7],
        "offsets": list(vals[8:8 + count]),
    }


def db_section_kind(db: bytes, off: int) -> str:
    """Classify the DB section at absolute file offset ``off``.

    Returns one of ``"wav"`` (RIFF/WAVE audio), ``"wdo"`` (0x0809 object container),
    ``"anim"`` (the 0x8161d7c0 animation block), ``"data"`` (a data block carrying a
    0x80 stride word at offset +0xc), or ``"unknown"`` (and ``"oob"`` past the file).
    """
    if off < 0 or off + 4 > len(db):
        return "oob"
    magic = db[off:off + 4]
    if magic == WAV_MAGIC:
        return "wav"
    if magic == WDO_MAGIC:
        return "wdo"
    if struct.unpack_from("<I", db, off)[0] == ANIM_MAGIC:
        return "anim"
    if off + 16 <= len(db) and struct.unpack_from("<I", db, off + 12)[0] == 0x80:
        return "data"
    return "unknown"


def db_sections(db: bytes) -> dict:
    """The parsed fixed header plus every section classified in directory order.

    On every owned BG1_*.DB the 9 sections are, in order: 4 data blocks, the anim
    block (magic 0x8161d7c0), 1 data block, 2 RIFF/WAVE audio chunks, and a trailing
    .WDO object (magic 0x0809). See db_section_kind for the kind vocabulary.
    """
    hdr = db_header(db)
    return {
        "header": hdr,
        "sections": [{"offset": o, "kind": db_section_kind(db, o)}
                     for o in hdr["offsets"]],
    }


def db_chunk_header(db: bytes, off: int) -> dict:
    """The 16-byte chunk header that opens a data or anim section.

    Every one of the 5 data sections and the anim section begins with the same
    16-byte header ``[u32 id][u32 id2][u32 count][u32 stride]``, where the stride
    word is always 0x80 (the fixed header's ``flags`` word). The anim chunk
    (id 0x8161d7c0) is distinguished by ``count == 0``. The WAV and WDO sections
    carry their own magics (``RIFF`` / 0x0809) and are not chunk headers. The
    ``id`` / ``id2`` words are per-chunk content hashes, not file offsets.
    """
    if off < 0 or off + 16 > len(db):
        raise FormatError(f"chunk header at {off:#x} runs past end of DB")
    ident, ident2, count, stride = struct.unpack_from("<4I", db, off)
    return {"offset": off, "id": ident, "id2": ident2,
            "count": count, "stride": stride}


def db_wave(db: bytes, off: int) -> dict:
    """Parse an embedded RIFF/WAVE chunk at absolute file offset ``off``.

    The owned disc stores two PCM samples per DB (weapon fire/reload audio):
    48 kHz, 16-bit, mono, little-endian. Returns the RIFF size, the fmt
    sub-chunk fields and the PCM stream parameters.
    """
    if off + 28 > len(db):
        raise FormatError(f"WAV at {off:#x} runs past end of DB")
    if db[off:off + 4] != WAV_MAGIC or db[off + 8:off + 12] != b"WAVE":
        raise FormatError(f"no RIFF/WAVE chunk at {off:#x}")
    size = struct.unpack_from("<I", db, off + 4)[0]
    if off + 8 + size > len(db):
        raise FormatError(f"WAV at {off:#x} size {size} runs past end of DB")
    sc_id = db[off + 12:off + 16]
    sc_size = struct.unpack_from("<I", db, off + 16)[0]
    tag, channels, rate, byte_rate, align, bits = struct.unpack_from(
        "<HHIIHH", db, off + 20)
    return {
        "offset": off, "riff_size": size, "subchunk": sc_id.decode("latin-1"),
        "subchunk_size": sc_size, "format_tag": tag, "channels": channels,
        "sample_rate": rate, "byte_rate": byte_rate, "block_align": align,
        "bits_per_sample": bits,
    }


def db_wave_sections(db: bytes) -> list[dict]:
    """Parse every embedded RIFF/WAVE section (two per DB on the owned disc)."""
    return [db_wave(db, s["offset"])
            for s in db_sections(db)["sections"] if s["kind"] == "wav"]


def db_tail_wdo(db: bytes) -> dict:
    """The trailing .WDO object is the DB's last section.

    Its size field (u32 at +8) must equal the remaining file length, i.e. the object
    runs from its offset to EOF. Verified on all 31 owned BG1_*.DB.
    """
    wdo = [s for s in db_sections(db)["sections"] if s["kind"] == "wdo"]
    if len(wdo) != 1:
        raise FormatError(f"expected exactly one trailing WDO section, found {len(wdo)}")
    off = wdo[0]["offset"]
    magic, _zero, size = struct.unpack_from("<3I", db, off)
    tail = len(db) - off
    if magic != 0x0809:
        raise FormatError(f"WDO section at {off:#x} magic 0x{magic:04x}, expected 0x0809")
    if size != tail:
        raise FormatError(f"WDO size field {size} != remaining file length {tail}")
    return {"offset": off, "magic": magic, "size": size, "tail": tail}


def elf_loader_sites(elf: Path | str | None = None) -> dict:
    """Re-derive the loader code sites from the owned ELF (regression pin).

    Scans the single LOAD segment for `lui rd, hi16` followed within three
    instructions by `addiu rt, rs, lo16` (or `ori`/`daddiu`) with rs == rd, whose
    assembled address is a known loader string address. The pairs are not always
    adjacent (a second `lui` or a data word may sit between them), which is why a
    naive adjacent-pair scan misses the sites.
    """
    elf = Path(elf) if elf else ELF
    data = elf.read_bytes()
    if data[:4] != b"\x7fELF":
        raise FormatError("not an ELF")
    off_base, va_base = ELF_LOAD_SEG
    span = len(data) - off_base - 4
    hi_of = {saddr: ((saddr + 0x8000) >> 16) & 0xFFFF for saddr in LOADER_SITES}
    hi_set = set(hi_of.values())
    hits: dict[int, list[int]] = {}
    for i in range(0, span, 4):
        w1 = struct.unpack_from("<I", data, off_base + i)[0]
        if (w1 >> 26) == 0x0F and (w1 & 0xFFFF) in hi_set:          # lui rd, hi16
            rd = (w1 >> 16) & 0x1F
            for j in (4, 8, 12):                                    # up to 2 skipped words
                if i + j + 4 > span:
                    break
                w2 = struct.unpack_from("<I", data, off_base + i + j)[0]
                op = w2 >> 26
                if op not in (0x09, 0x19, 0x0D):                    # addiu / daddiu / ori
                    continue
                rs = (w2 >> 21) & 0x1F
                if rs != rd:
                    continue
                lo16 = w2 & 0xFFFF
                if lo16 >= 0x8000:                                 # sign-extended lo half
                    lo16 -= 0x10000
                addr = (((w1 & 0xFFFF) << 16) + lo16) & 0xFFFFFFFF
                if addr in LOADER_SITES:
                    hits.setdefault(addr, []).append(va_base + i)
                break
    return hits


def read_model(_blob: bytes) -> dict:
    raise NotImplementedError("Black WDD geometry codec not yet cracked (next stage)")


def to_glb(_model: dict, _out) -> None:
    raise NotImplementedError("Black skeleton/animation mapping not yet cracked (next stage)")


if __name__ == "__main__":
    import json
    import sys

    iso = Path(sys.argv[1]) if len(sys.argv) > 1 else DISC
    print(json.dumps(list_cast(iso), indent=1))
