"""Devil Summoner 2: Raidou Kuzunoha vs. King Abaddon (PS2, SLUS_218.45) owned-disc inventory (#1507).

Read-only.  The owned file is a plain 2048-byte-sector ISO9660 image (catalog
label ps2 is right: SYSTEM.CNF boots ``cdrom0:\\SLUS_218.45;1``, VER 1.00, NTSC;
publisher ATLUS, volume date 2009-03-04).  Besides the boot ELF, IRX modules
and ``SMOVIE/*.IPS|IPU`` movies, every game asset sits in one Atlus DDS3-engine
archive pair (the Nocturne/Digital Devil Saga/Raidou engine):

* ``DDS3.DDT`` -- the directory tree.  12-byte records ``{u32 name_offset,
  u32 data, s32 size}``; name offsets point at NUL-terminated names inside the
  DDT.  A negative size is a directory with ``-size`` children whose records
  start at DDT byte offset ``data``; otherwise ``data`` is the file's first
  2048-byte sector inside ``DDS3.IMG`` and ``size`` its byte length.  Record 0
  is the unnamed root.
* ``DDS3.IMG`` -- the sector data.  On this build the 10060 DDT files tile the
  IMG exactly (last end sector == IMG sectors), which ``coverage`` checks.

Assets use the Atlus resource header ``{u16 type, u16 user, u32 size,
char magic[4], u32 0}``.  Character/model packages (``.PB``) are a ``PIB0``
header chunk followed by 0x40-aligned chunks: ``TXP0`` (type 9, texture pack:
u32 count at +0x10 then chunk-relative u32 offsets of ``TMX0`` pictures: u16
w at +0x12, u16 h at +0x14, u8 GS PSM at +0x16, 0x13 = PSMT8, 0x14 = PSMT4),
``MD00`` (type 6, model) and ``MT00`` (type 8, motion bank; u32 motion count at
+0x14).  Separate-file models use ``.MB`` (MD00) / ``.TB`` (TXP0) / ``.AB``
(MT00).  ``.LB`` files are compressed packages: type 0x0101, u32 packed size,
payload magic (``PBN\\0`` = a compressed PB), u32 unpacked size.  E.g.
``model_lb/devil_b/001.LB`` unpacks to exactly the size of ``model/devil/001.PB``.
Their codec is the analysis-stage opener; this module only reads headers.

Raidou himself is the battle player ``model/battle/human/player.PB`` (11
palettized TMX, MD00, 12-motion MT00), the field player
``model/field/fld_player.PB`` and the event models ``model/event/raidou_*``.

``python -m gbox.raidou2_inventory disc.iso --out manifest.json`` writes the
manifest (``--hash`` also hashes the whole ISO; slow on the SMB share).
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import struct
from pathlib import Path

SECTOR = 2048
BOOT = "SLUS_218.45"
DDT_NAME = "DDS3.DDT"
IMG_NAME = "DDS3.IMG"
CHUNK_TYPES = {b"PIB0": 1, b"TMX0": 2, b"MD00": 6, b"MSG1": 7, b"MT00": 8, b"TXP0": 9}
PSM = {0x00: "PSMCT32", 0x01: "PSMCT24", 0x02: "PSMCT16", 0x13: "PSMT8", 0x14: "PSMT4"}

# Asset groups that hold character bodies.  Roles come from the file names and
# are leads until the analysis stage ties them to the loaders.
CHARACTER_GROUPS = {
    "raidou_battle": re.compile(r"^model/battle/human/.*\.PB$", re.I),
    "raidou_field": re.compile(r"^model/field/fld_player\.PB$", re.I),
    "raidou_event": re.compile(r"^model/event/(raidou|raiodu)_.*\.PB$", re.I),
    "event_cast": re.compile(r"^model/event/.*\.PB$", re.I),
    "npc": re.compile(r"^model/npc/.*\.PB$", re.I),
    "devil": re.compile(r"^model/devil/.*\.PB$", re.I),
    "devil_hi": re.compile(r"^model/devil_hi/.*\.PB$", re.I),
    "devil_battle_lb": re.compile(r"^model_lb/devil_b/.*\.LB$", re.I),
}


def iso_files(f) -> dict[str, tuple[int, int]]:
    """``{"/PATH/NAME": (lba, size)}`` for every file of an ISO9660 image."""
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[1:6] != b"CD001" or len(pvd) < 190:
        raise ValueError("no ISO9660 primary volume descriptor at LBA 16")
    from .formats import iso9660                          # the shared ISO9660 walk (gbox.formats)
    root = pvd[156:190]
    return {"".join("/" + p for p in parts) + "/" + rec.name: (rec.lba, rec.size)
            for parts, rec, _d in iso9660.walk(iso9660.file_reader(f, SECTOR), struct.unpack_from("<I", root, 2)[0],
                                               struct.unpack_from("<I", root, 10)[0], strict=True, encoding="ascii",
                                               max_depth=16, too_deep="raise")
            if not rec.is_dir}


def pvd_info(f) -> dict:
    f.seek(16 * SECTOR)
    p = f.read(SECTOR)
    s = lambda a, b: p[a:b].decode("ascii", "replace").strip()
    return {"system_id": s(8, 40), "volume_id": s(40, 72), "volume_blocks": struct.unpack_from("<I", p, 80)[0],
            "publisher": s(318, 446), "application": s(574, 702), "created": s(813, 829)}


def ddt_entries(ddt: bytes) -> list[tuple[str, int, int]]:
    """``[(path, img_sector, size)]`` for every file in a DDS3 DDT tree."""
    def name(o: int) -> str:
        if not 0 <= o < len(ddt):
            raise ValueError(f"DDT name offset {o:#x} outside the tree")
        e = ddt.find(b"\0", o)
        return ddt[o:e if e >= 0 else len(ddt)].decode("ascii", "replace")

    out: list[tuple[str, int, int]] = []
    seen: set[int] = set()

    def walk(off: int, count: int, path: str) -> None:
        if off in seen or off < 0 or off + 12 * count > len(ddt):
            raise ValueError(f"bad DDT directory block at {off:#x} ({count} entries)")
        seen.add(off)
        for i in range(count):
            no, data, size = struct.unpack_from("<IIi", ddt, off + 12 * i)
            p = f"{path}/{name(no)}" if path else name(no)
            if size < 0:
                walk(data, -size, p)
            else:
                out.append((p, data, size))

    if len(ddt) < 12:
        raise ValueError("DDT too short")
    _no, data, size = struct.unpack_from("<IIi", ddt, 0)
    if size >= 0:
        raise ValueError("DDT record 0 is not the root directory")
    walk(data, -size, "")
    return out


def coverage(entries: list[tuple[str, int, int]], img_size: int) -> dict:
    """Overlaps, gaps and end sector of DDT files inside the IMG."""
    spans = sorted((s, s + (z + SECTOR - 1) // SECTOR, p) for p, s, z in entries if z)
    overlaps, gap_sectors, cur = [], 0, 0
    for a, b, p in spans:
        if a < cur:
            overlaps.append(p)
        else:
            gap_sectors += a - cur
        cur = max(cur, b)
    img_sectors = (img_size + SECTOR - 1) // SECTOR
    return {"files": len(entries), "empty_files": sum(1 for e in entries if not e[2]),
            "bytes": sum(e[2] for e in entries), "end_sector": cur, "img_sectors": img_sectors,
            "gap_sectors": gap_sectors, "overlaps": overlaps[:20], "overlap_count": len(overlaps),
            "exact_tiling": not overlaps and cur == img_sectors}


def atlus_header(b: bytes, o: int = 0) -> tuple[int, int, bytes] | None:
    """(type, size, magic) of an Atlus resource header at ``o``, or None."""
    if o + 16 > len(b):
        return None
    t, _u, size = struct.unpack_from("<HHI", b, o)
    magic = b[o + 8:o + 12]
    if CHUNK_TYPES.get(magic) != t or size < 16 or o + size > len(b):
        return None
    return t, size, magic


def tmx_info(b: bytes, o: int = 0) -> dict:
    if o < 0 or o + 0x17 > len(b):
        raise ValueError(f"TMX0 header at {o:#x} truncated")
    w, h, psm = struct.unpack_from("<HHB", b, o + 0x12)
    return {"w": w, "h": h, "psm": PSM.get(psm, psm)}


def pb_chunks(b: bytes) -> list[dict]:
    """Top-level chunks of a PIB0 package (0x10-aligned scan between chunks)."""
    if atlus_header(b) is None or b[8:12] != b"PIB0":
        raise ValueError("not a PIB0 package")
    out, o = [], 0
    while o + 16 <= len(b):
        h = atlus_header(b, o)
        if h is None:
            o += 16
            continue
        t, size, magic = h
        c = {"offset": o, "magic": magic.decode(), "size": size}
        if magic == b"TXP0":
            if o + 0x14 > len(b):
                raise ValueError(f"TXP0 chunk at {o:#x} too short")
            n = struct.unpack_from("<I", b, o + 0x10)[0]
            fits = 0 < n < 4096 and o + 0x14 + 4 * n <= len(b)
            offs = struct.unpack_from(f"<{n}I", b, o + 0x14) if fits else ()
            c["textures"] = [tmx_info(b, o + x) for x in offs
                             if o + x + 0x17 <= len(b) and atlus_header(b, o + x) and b[o + x + 8:o + x + 12] == b"TMX0"]
            c["texture_count"] = n
        elif magic == b"MT00":
            if o + 0x18 > len(b):
                raise ValueError(f"MT00 chunk at {o:#x} too short")
            c["motions"] = struct.unpack_from("<I", b, o + 0x14)[0]
        elif magic == b"TMX0":
            c["texture"] = tmx_info(b, o)
        out.append(c)
        o = (o + size + 15) & ~15
    return out


def lb_header(b: bytes) -> dict | None:
    """Header of a compressed ``.LB`` package, or None if it isn't one."""
    if len(b) < 16 or struct.unpack_from("<H", b)[0] != 0x0101:
        return None
    packed, = struct.unpack_from("<I", b, 4)
    return {"packed": packed, "magic": b[8:12].rstrip(b"\0").decode("latin1"),
            "unpacked": struct.unpack_from("<I", b, 12)[0]}


def _package_summary(chunks: list[dict]) -> dict:
    tex = [t for c in chunks for t in c.get("textures", [])]
    return {"chunks": [c["magic"] for c in chunks],
            "models": sum(c["magic"] == "MD00" for c in chunks),
            "model_bytes": sum(c["size"] for c in chunks if c["magic"] == "MD00"),
            "textures": len(tex), "texture_psm": dict(collections.Counter(t["psm"] for t in tex)),
            "motion_banks": sum(c["magic"] == "MT00" for c in chunks),
            "motions": sum(c.get("motions", 0) for c in chunks)}


def sha256_file(path, chunk: int = 16 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def build_manifest(iso: str | Path, source_sha256: str | None = None, hash_iso: bool = False) -> dict:
    iso = Path(iso)
    with open(iso, "rb") as f:
        files = iso_files(f)
        pvd = pvd_info(f)

        def read(lba: int, size: int, n: int | None = None) -> bytes:
            f.seek(lba * SECTOR)
            return f.read(size if n is None else min(n, size))

        need = {f"/{BOOT}", "/SYSTEM.CNF", f"/{DDT_NAME}", f"/{IMG_NAME}"}
        missing = sorted(need - set(files))
        if missing:
            raise ValueError(f"not the expected Raidou 2 disc layout, missing {missing}")
        cnf = read(*files["/SYSTEM.CNF"]).decode("ascii", "replace")
        boot = read(*files[f"/{BOOT}"])
        ddt = read(*files[f"/{DDT_NAME}"])
        img_lba, img_size = files[f"/{IMG_NAME}"]
        entries = ddt_entries(ddt)
        cov = coverage(entries, img_size)

        top = collections.Counter(p.split("/")[0] for p, _, _ in entries)
        ext = collections.Counter(p.rsplit(".", 1)[-1].upper() if "." in p.rsplit("/", 1)[-1] else "" for p, _, _ in entries)
        groups: dict[str, list] = {k: [] for k in CHARACTER_GROUPS}
        for p, s, z in entries:
            for g, rx in CHARACTER_GROUPS.items():
                if not rx.match(p):
                    continue
                rec = {"path": p, "sector": s, "size": z}
                if z:
                    if p.upper().endswith(".LB"):
                        rec["lb"] = lb_header(read(img_lba + s, z, 16))
                    elif g in ("raidou_battle", "raidou_field", "raidou_event"):
                        b = read(img_lba + s, z)
                        rec.update(_package_summary(pb_chunks(b)))
                        rec["sha256"] = hashlib.sha256(b).hexdigest()
                    else:
                        h = read(img_lba + s, z, 16)
                        rec["magic"] = h[8:12].decode("latin1")
                groups[g].append(rec)
                break

    manifest = {
        "game": "Shin Megami Tensei: Devil Summoner 2 - Raidou Kuzunoha vs. King Abaddon",
        "platform": "ps2", "serial": BOOT, "region": "USA",
        "iso": str(iso), "iso_size": iso.stat().st_size,
        "source_sha256": source_sha256 or (sha256_file(iso) if hash_iso else None),
        "pvd": pvd, "system_cnf": cnf.strip().splitlines(),
        "boot_elf": {"name": BOOT, "size": len(boot), "sha256": hashlib.sha256(boot).hexdigest(),
                     "elf": boot[:4] == b"\x7fELF", "machine": struct.unpack_from("<H", boot, 18)[0] if len(boot) > 20 else None},
        "iso_files": {p: {"lba": l, "size": s} for p, (l, s) in sorted(files.items())},
        "launch_prerequisites": ["PS2 BIOS (pcsx2 system dir)", "IRX/IOPRP250.IMG and IRX/*.IRX are loaded from the disc",
                                 "no encryption or online check; plain ISO9660"],
        "dds3": {"ddt": {"lba": files[f"/{DDT_NAME}"][0], "size": len(ddt), "sha256": hashlib.sha256(ddt).hexdigest()},
                 "img": {"lba": img_lba, "size": img_size}, "coverage": cov,
                 "top_dirs": dict(top.most_common()), "extensions": dict(ext.most_common())},
        "characters": {g: v for g, v in groups.items()},
        "character_counts": {g: len(v) for g, v in groups.items()},
    }
    return manifest


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Raidou 2 (PS2) owned-disc inventory")
    ap.add_argument("iso")
    ap.add_argument("--out")
    ap.add_argument("--source-sha256")
    ap.add_argument("--hash", action="store_true")
    a = ap.parse_args(argv)
    m = build_manifest(a.iso, a.source_sha256, a.hash)
    txt = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(json.dumps({"coverage": m["dds3"]["coverage"], "counts": m["character_counts"],
                      "boot_sha256": m["boot_elf"]["sha256"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
