"""Owned-build inventory for WWF WrestleMania 2000 (USA) on N64 (#1349): identify the exact ROM, verify the
AKI file-table boot sites in the build's own code, validate the file table, parse the wrestler roster
(names, ids, attire pointers), and classify model/texture files.

    python -m gbox.wm2000_inventory SRC [--out manifest.json]

SRC is the owned zip / z64 / v64 / n64; it is only read. The build is keyed on the NWXE rev 0 header
(CRC1 90a59003); any other build fails loudly instead of being parsed with the wrong tables.

Facts fixed per exact build (z64 offsets), found in the boot segment (ROM 0x1000 -> RAM 0x80000400):

  * File table: the loader at RAM 0x80003CC0 mallocs 0xA120 bytes, then jal 0x198 copies that many bytes
    from ROM 0x11778BE (lui a0, 0x117 / addiu a0, 0x78BE at 0x80003CE8/EC) to the heap and stores the
    pointer at RAM 0x80057200. The copy loop (0x80003D30) builds FirstFile 0x144AA0 with lui s4/addiu s4
    and precomputes each file's size; sltiu 0x2847/0x2848 at 0x80003D9C/0x80003DDC bound the ids.
  * Roster: 74 variable-size records at ROM 0x40E08-0x41D00. Each record = 4 u32 attire pointers +
    NUL-terminated name + zero padding + fields; the fields hold a u32 pointer and 8 u16s
    (class, wrestler id, ..., appearance set, 0). Wrestler ids run 1..0x4B with 0x41/0x42 unused.
  * Formats (shared with the other AKI engine games, see gbox/aki_wrestling): AkiModel part models
    ({u8 scale, u8 nverts|0x80, u8 nfaces, u8 influence, s8 off x/y/z, u8 tex} + nverts x 8B vertices
    + nfaces x 3B indices, <=63 verts / 84 faces); CI textures; Asmik LZSS per-file compression
    (bit 0 of the table entry, 00 + 24-bit length header).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zipfile
import zlib
from collections import Counter
from pathlib import Path

from . import n64_rom

CODE_RAM = 0x80000400                              # boot segment: ROM 0x1000 -> RAM 0x80000400
CODE_ROM = 0x1000                                  # boot code start (after the IPL3 boot)
BUILD = (0x90A59003, "NWXE", 0)                    # CRC1, product code, revision of the owned build
SITES = {                                          # file-table boot sites, keyed by RAM address
    0x80003CC4: ("ori", 0x3404A120),               # ori a0, zero, 0xA120 (table byte size)
    0x80003CE8: ("ft_hi", 0x3C040117),             # lui a0, 0x117
    0x80003CEC: ("ft_lo", 0x248478BE),             # addiu a0, a0, 0x78BE  -> ROM 0x11778BE
    0x80003D00: ("size", 0x3406A120),              # ori a2, zero, 0xA120 (copy size)
    0x80003D30: ("first_hi", 0x3C140014),          # lui s4, 0x14
    0x80003D34: ("first_lo", 0x26944AA0),          # addiu s4, s4, 0x4AA0  -> FirstFile 0x144AA0
    0x80003D9C: ("bound", 0x2E422847),             # sltiu v0, s2, 0x2847 (nfiles)
    0x80003DDC: ("bound2", 0x2C422848),            # sltiu v0, v0, 0x2848 (nfiles + 1)
}
FT_ROM = 0x11778BE
FIRST = 0x144AA0
NFILES = 0x2847
ROSTER_AREA = (0x40E08, 0x41D00)                   # 74 roster records (58 wrestlers + DUMMY + 15 CAW slots)
CIC_BOOT = {0x90BB6CB5: "6102/7101", 0x6170A4A1: "6101", 0x0B050EE0: "6103/7103", 0x98BC2C86: "6105/7105",
            0xACC8580A: "6106/7106"}               # crc32 of the IPL3 boot code (ROM 0x40-0x1000)
BYTE_ORDER = {b"\x80\x37\x12\x40": "z64 (big-endian)", b"\x37\x80\x40\x12": "v64 (byte-swapped)",
              b"\x40\x12\x37\x80": "n64 (word-swapped)"}


def ram2rom(a: int) -> int:
    return a - CODE_RAM + CODE_ROM


def header(rom: bytes) -> dict:
    u32 = lambda o: struct.unpack_from(">I", rom, o)[0]
    region = chr(rom[0x3E])
    return {"name": rom[0x20:0x34].decode("ascii", "replace").strip(), "code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "rev": rom[0x3F], "region": {"E": "USA", "P": "Europe", "J": "Japan"}.get(region, region),
            "crc1": f"{u32(0x10):08x}", "crc2": f"{u32(0x14):08x}", "entry": f"{u32(0x08):08x}",
            "cic": CIC_BOOT.get(zlib.crc32(rom[0x40:0x1000]), "unknown"), "size": len(rom),
            "sha256_z64": hashlib.sha256(rom).hexdigest(), "md5_z64": hashlib.md5(rom).hexdigest()}


def container(path: Path) -> dict:
    """The owned file as stored (hash, archive members, actual byte order vs. the member's extension)."""
    raw = path.read_bytes()
    out = {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            ms = []
            for m in z.infolist():
                with z.open(m) as f:
                    order = BYTE_ORDER.get(f.read(4), "unknown")
                ext = Path(m.filename).suffix.lower().lstrip(".")
                ms.append({"name": m.filename, "size": m.file_size, "crc32": f"{m.CRC:08x}", "byte_order": order,
                           "extension_matches": order.startswith(ext)})
            out["members"] = ms
    else:
        out["byte_order"] = BYTE_ORDER.get(raw[:4], "unknown")
    return out


def boot_sites(rom: bytes) -> dict:
    """Re-read the file-table loader sites from the build's own boot code; fail loudly on any other build."""
    words = {}
    for ram, (kind, want) in SITES.items():
        got = struct.unpack_from(">I", rom, ram2rom(ram))[0]
        words[kind] = f"{got:08x}"
        if got != want:
            raise ValueError(f"boot site {kind} at {ram:#x} is {got:08x}, expected {want:08x} (not the NWXE rev 0 build)")
    return {"ok": True, "words": words, "ft_rom": FT_ROM, "first": FIRST, "nfiles": NFILES,
            "entries": NFILES + 1, "table_bytes": 4 * (NFILES + 1)}


def file_table(rom: bytes) -> dict:
    """The AKI file table: u32 per entry, (offset from FirstFile) | 1 = Asmik LZSS. Validated end to end."""
    n = NFILES + 1
    vals = struct.unpack_from(f">{n}I", rom, FT_ROM)
    clean = [v & ~1 for v in vals]
    for i in range(n - 1):
        if clean[i] > clean[i + 1]:
            raise ValueError(f"file table entry {i} is not monotonic: {clean[i]:#x} -> {clean[i + 1]:#x}")
    if clean[0] != 0:
        raise ValueError(f"file 1 does not start at FirstFile: offset {clean[0]:#x}")
    end = FIRST + clean[-1]
    if end != FT_ROM:
        raise ValueError(f"file data ends at {end:#x}, not at the file table {FT_ROM:#x}")
    lz = sum(1 for v in vals if v & 1)
    sizes = [clean[i + 1] - clean[i] for i in range(n - 1)]
    return {"files": NFILES, "entries": n, "first": FIRST, "ft": FT_ROM, "lzss": lz,
            "size_min": min(sizes), "size_max": max(sizes), "size_median": sorted(sizes)[n // 2 - 1],
            "data_span": [FIRST, FT_ROM], "tail": [FT_ROM + 4 * n, len(rom)],
            "tail_bytes": len(rom) - FT_ROM - 4 * n}


def roster(rom: bytes) -> list[dict]:
    """The 74 roster records: 4 attire pointers, name, and the id/class/set fields that follow."""
    lo, hi = ROSTER_AREA
    hi = min(hi, len(rom))
    out = []
    o = lo
    while o + 16 < hi:
        p = struct.unpack_from(">4I", rom, o)
        if all(0x80000000 <= q < 0x80800000 and q % 4 == 0 for q in p):
            j = o + 16
            name = bytearray()
            while j < hi and 0x20 <= rom[j] < 0x7F and len(name) < 48:
                name.append(rom[j])
                j += 1
            if not name:
                o += 4
                continue
            k = j
            while k < hi and rom[k] == 0:            # zero padding before the fields
                k += 1
            fields = rom[k:]
            ptr_at = next((t for t in range(min(len(fields) - 4, 8)) if
                           0x80000000 <= struct.unpack_from(">I", fields, t)[0] < 0x80800000), None)
            rec = {"addr": o, "name": bytes(name).decode("latin-1"), "attires": [f"{q:#x}" for q in p],
                   "fields_raw": fields[:24].hex(" ")}
            if ptr_at is not None and len(fields) >= ptr_at + 4 + 16:
                rec["field_ptr"] = f"{struct.unpack_from('>I', fields, ptr_at)[0]:#x}"
                u = struct.unpack_from(f">{8}H", fields, ptr_at + 4)
                rec.update(cls=u[0], id=u[1], f3=u[2], f4=u[3], f5=u[4], f6=u[5], set=u[6], z=u[7])
            out.append(rec)
            o = k
            continue
        o += 4
    if len(out) != 74:
        raise ValueError(f"roster parse found {len(out)} records, expected 74")
    return out


def classify(rom: bytes, vals: list[int], clean: list[int]) -> dict:
    """Count files whose bytes are AkiModel part models or CI textures, raw or Asmik-LZSS compressed."""
    from .aki_wrestling import lzss

    def is_model(b: bytes) -> bool:
        if len(b) < 8:
            return False
        nv, nf = b[1] & 0x7F, b[2]
        return (1 <= nv <= 63 and 1 <= nf <= 84) and 8 + nv * 8 + nf * 3 <= len(b) <= 8 + nv * 8 + nf * 3 + 4

    def is_tex(b: bytes) -> bool:
        if len(b) < 8:
            return False
        w, h = b[0] + 1, b[1] + 1
        if not (1 <= w <= 64 and 1 <= h <= 64) or w & (w - 1) or h & (h - 1):
            return False
        return ((b[2] << 8) | b[3]) in (16, 256) and len(b) == 8 + w * h

    n = NFILES
    count = {"models": 0, "textures": 0, "other": 0, "lzss_decoded": 0}
    for i in range(n):
        raw = rom[FIRST + clean[i]:FIRST + clean[i + 1]]
        body = lzss(raw) if vals[i] & 1 else raw
        if vals[i] & 1:
            count["lzss_decoded"] += 1
        if is_model(body):
            count["models"] += 1
        elif is_tex(body):
            count["textures"] += 1
        else:
            count["other"] += 1
    return count


def inventory(rom: bytes, source: Path | None = None) -> dict:
    h = header(rom)
    if (int(h["crc1"], 16), h["code"], h["rev"]) != BUILD:
        raise ValueError(f"not the owned NWXE rev 0 build: {h['crc1']} {h['code']} rev {h['rev']}")
    bs = boot_sites(rom)
    ft = file_table(rom)
    n = NFILES + 1
    vals = list(struct.unpack_from(f">{n}I", rom, FT_ROM))
    clean = [v & ~1 for v in vals]
    ws = roster(rom)
    ids = sorted({w["id"] for w in ws if "id" in w})
    return {
        "build": h,
        "source": container(source) if source else None,
        "boot": bs,
        "layout": {"boot": [0x40, 0x1000], "code_rom": [0x1000, FIRST], "code_ram": CODE_RAM,
                   "files_rom": [FIRST, FT_ROM], "file_table_rom": [FT_ROM, FT_ROM + 4 * n],
                   "tail_rom": [FT_ROM + 4 * n, len(rom)]},
        "file_table": ft,
        "roster": {"records": len(ws), "wrestlers": sum(1 for w in ws if w["id"] in ids and (w["id"] < 0x33 or w["id"] > 0x42)),
                   "caw_templates": sum(1 for w in ws if 0x33 <= w.get("id", 0) <= 0x41),
                   "ids": [f"{i:#x}" for i in ids], "missing_ids": [f"{i:#x}" for i in range(1, 0x4C)
                                                                     if i not in ids],
                   "entries": ws},
        "formats": {"models": "AkiModel part models (see gbox/aki_wrestling): <=63 verts / 84 faces, rest pose",
                    "textures": "CI4/CI8 + RGBA5551 palettes, some Asmik-LZSS compressed",
                    "compression": "Asmik LZSS, per file (bit 0 of the table entry)",
                    "animations": "not parsed: a part-model swap keeps the game's own skeleton and animations",
                    "roster_fields": "u16 cls (group), u16 id, u16 f3..f6 (semantics unproven), u16 set, u16 z",
                    "attire_blocks": "4 x u32 per wrestler -> 0x24-byte appearance blocks (analysis stage)"},
        "classification": classify(rom, vals, clean),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.wm2000_inventory",
                                 description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out", type=Path, help="write the JSON manifest here")
    a = ap.parse_args(argv)
    rom = n64_rom.read(a.rom)
    m = inventory(rom, a.rom)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    print(json.dumps({k: m[k] for k in ("build", "boot", "layout", "file_table", "classification")} |
                     {"roster_records": m["roster"]["records"],
                      "wrestlers": m["roster"]["wrestlers"],
                      "caw_templates": m["roster"]["caw_templates"],
                      "missing_ids": m["roster"]["missing_ids"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
