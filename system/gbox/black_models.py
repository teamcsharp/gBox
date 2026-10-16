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
  before the name table and points at each bone record relative to a base.
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
    record framing is not yet cracked (a u16 length-prefix walk does not cover the
    file). Census = verified invariants only: fixed size, padded tail, first-word
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


# .DB skeleton name table: a run of 24-byte records (null-terminated ASCII name, zero
# padded) anchored at the literal "World" bone. The FPS arms rig has no leg/spine/neck/
# head bones: it is the weapon-holding arms the player sees. The weapon-specific tail
# (AssualtRifle_*, Pistol_*, Shotgun_*, grenade bones, ...) varies per BG1_<weapon> slot.
SKEL_ANCHOR = b"World\x00"
BONE_RECORD = 24

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
