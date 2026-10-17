"""Super Bust-A-Move (USA) PS2 inventory: ISO9660 walk, -RA- containers, CMP3 codec, TIM2 sprites.

Owned build (favorite 6cd93f2e36885f31, request #1368): the hyperspin CD-type CHD
``Super Bust-A-Move (USA).chd`` holds one MODE1/2048 track.  ``chdman extractcd`` gives a
32,724,992-byte ISO9660 image (volume SUPER_BUST_A_MOVE, Acclaim, 2000-10-25) whose
SYSTEM.CNF boots ``cdrom0:\\SLUS_201.15;1`` (VER 1.00, NTSC).

Every game asset lives in 153 ``DATA/DATAnn/DATAxx.DAT`` files.  Each is a ``-RA-``
container::

    0x00  "-RA-" + 12 zero bytes
    0x14  u32 count
    0x18  u32 offsets[count]       (offsets[0] == 0x18 + 4*count; entry i ends at offsets[i+1]
                                    or at the end of the file)

An entry that starts with ``CMP3`` is ``"CMP3", u32 decoded_size`` followed by Okumura LZSS
(4096-byte ring pre-filled with zeros, write cursor 0xFEE, LSB-first flag bytes with
1 = literal, 2-byte references ``offset = b0 | (b1 & 0xF0) << 4``, ``length = (b1 & 15) + 3``).
Other entries are stored raw (VB ADPCM sample bodies).  Decoded payloads are TIM2 textures,
``pBAV`` (VAB) sound-bank headers, ``pQES`` (SEQ) sequences and VB sample data.

The boot ELF names the roster in its sound-test tables (``<NAME> VOICE`` strings) and keeps a
0x20-stride table of every DAT path (``\\DATA\\DATAnn\\DATAxx.DAT;1``).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import struct
import sys
from dataclasses import dataclass, field

GAME_ID = "6cd93f2e36885f31"
SERIAL = "SLUS_201.15"
SECTOR = 2048
# Hashes measured on the owned build (Oct 12 2026); the CHD hash is the stage source identity.
KNOWN = {
    "chd_sha256": "b7a76e1671bc3d60cc0b7bb4ae33579336e3e15feb16119ad74619d7dfd8c519",
    "iso_sha256": "7e0c4e6e2b7c82df1fff9bee6d94291af1a1a856b4b6796f03fea2b3a3e616b6",
    "boot_elf_sha256": "eeb913a6eac79a58d8424dc18190310f1ae5d14d762dec5a339f44ad9870d965",
}
RA_MAGIC = b"-RA-"
CMP3_MAGIC = b"CMP3"
TIM2_BPP = {1: 16, 2: 24, 3: 32, 4: 4, 5: 8}


# --------------------------------------------------------------------------- ISO9660
@dataclass
class IsoFile:
    path: str
    lba: int
    size: int


class Iso9660:
    """Minimal 2048-byte-sector ISO9660 reader (primary volume descriptor only)."""

    def __init__(self, path: str):
        self.path = path
        self._fh = open(path, "rb")
        pvd = self.sectors(16, 1)
        if pvd[0:6] != b"\x01CD001":
            raise ValueError("no ISO9660 primary volume descriptor at LBA 16")
        self.system_id = pvd[8:40].decode("ascii", "replace").strip()
        self.volume_id = pvd[40:72].decode("ascii", "replace").strip()
        self.volume_blocks = struct.unpack_from("<I", pvd, 80)[0]
        self.publisher = pvd[318:446].decode("ascii", "replace").strip()
        self.created = pvd[813:829].decode("ascii", "replace")
        root = pvd[156:190]
        self.files: list[IsoFile] = []
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", 0)
        self._by_name = {f.path.upper(): f for f in self.files}

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def sectors(self, lba: int, count: int) -> bytes:
        self._fh.seek(lba * SECTOR)
        return self._fh.read(count * SECTOR)

    def _walk(self, lba: int, size: int, prefix: str, depth: int):
        if depth > 16:
            raise ValueError("ISO9660 directory recursion too deep")
        buf = self.sectors(lba, (size + SECTOR - 1) // SECTOR)[:size]
        i = 0
        while i < len(buf):
            length = buf[i]
            if length == 0:  # records never straddle sectors; skip the padding
                i = (i // SECTOR + 1) * SECTOR
                continue
            rec = buf[i:i + length]
            i += length
            elba, esize, flags, nlen = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0], rec[25], rec[32]
            name = rec[33:33 + nlen]
            if name in (b"\x00", b"\x01"):
                continue
            text = name.decode("ascii", "replace").split(";")[0]
            if flags & 2:
                self._walk(elba, esize, prefix + text + "/", depth + 1)
            else:
                self.files.append(IsoFile(prefix + text, elba, esize))

    def find(self, path: str) -> IsoFile:
        key = path.replace("\\", "/").lstrip("/").split(";")[0].upper()
        if key not in self._by_name:
            raise FileNotFoundError(path)
        return self._by_name[key]

    def read(self, path: str) -> bytes:
        f = self.find(path)
        return self.sectors(f.lba, (f.size + SECTOR - 1) // SECTOR)[:f.size]


def parse_system_cnf(raw: bytes) -> dict:
    out = {}
    for line in raw.decode("ascii", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    boot = out.get("BOOT2") or out.get("BOOT") or ""
    out["platform"] = "ps2" if "BOOT2" in out else ("ps1" if "BOOT" in out else "unknown")
    m = re.search(r"\\([^\\;]+)(;\d+)?$", boot)
    out["boot_file"] = m.group(1) if m else None
    return out


# --------------------------------------------------------------------------- -RA- / CMP3
@dataclass
class RAEntry:
    index: int
    offset: int
    size: int
    codec: str  # "cmp3", "raw" or "empty"
    decoded_size: int


def parse_ra(buf: bytes) -> list[RAEntry]:
    if buf[:4] != RA_MAGIC or len(buf) < 0x18:
        raise ValueError("not a -RA- container")
    count = struct.unpack_from("<I", buf, 0x14)[0]
    table_end = 0x18 + 4 * count
    if count == 0 or table_end > len(buf):
        raise ValueError("bad -RA- entry count %d" % count)
    offs = list(struct.unpack_from("<%dI" % count, buf, 0x18))
    if offs[0] != table_end:
        raise ValueError("first -RA- offset 0x%x != table end 0x%x" % (offs[0], table_end))
    out = []
    for i, off in enumerate(offs):
        end = offs[i + 1] if i + 1 < count else len(buf)
        if not (table_end <= off <= end <= len(buf)):
            raise ValueError("-RA- entry %d out of range (0x%x..0x%x)" % (i, off, end))
        size = end - off
        if size == 0:
            out.append(RAEntry(i, off, 0, "empty", 0))
        elif buf[off:off + 4] == CMP3_MAGIC:
            out.append(RAEntry(i, off, size, "cmp3", struct.unpack_from("<I", buf, off + 4)[0]))
        else:
            out.append(RAEntry(i, off, size, "raw", size))
    return out


def cmp3_decompress(buf: bytes, off: int = 0, end: int | None = None) -> bytes:
    """Decode one CMP3 stream at ``buf[off:]``; raises ValueError if it ends early."""
    if buf[off:off + 4] != CMP3_MAGIC:
        raise ValueError("missing CMP3 magic")
    want = struct.unpack_from("<I", buf, off + 4)[0]
    src, stop = off + 8, len(buf) if end is None else end
    ring = bytearray(4096)
    r = 0xFEE
    out = bytearray()
    flags = 0
    while len(out) < want:
        flags >>= 1
        if not flags & 0x100:
            if src >= stop:
                break
            flags = buf[src] | 0xFF00
            src += 1
        if flags & 1:
            if src >= stop:
                break
            c = buf[src]
            src += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & 0xFFF
        else:
            if src + 1 >= stop:
                break
            lo, hi = buf[src], buf[src + 1]
            src += 2
            pos, n = lo | ((hi & 0xF0) << 4), (hi & 0x0F) + 3
            for k in range(n):
                c = ring[(pos + k) & 0xFFF]
                out.append(c)
                ring[r] = c
                r = (r + 1) & 0xFFF
    if len(out) < want:
        raise ValueError("CMP3 stream truncated: %d of %d bytes" % (len(out), want))
    return bytes(out[:want])


def cmp3_compress_literal(data: bytes) -> bytes:
    """Encode ``data`` as an all-literal CMP3 stream (valid for the game's decoder, 9/8 size)."""
    out = bytearray(CMP3_MAGIC + struct.pack("<I", len(data)))
    for i in range(0, len(data), 8):
        chunk = data[i:i + 8]
        out.append((1 << len(chunk)) - 1)
        out += chunk
    return bytes(out)


def ra_entry_payload(buf: bytes, entry: RAEntry) -> bytes:
    if entry.codec == "cmp3":
        return cmp3_decompress(buf, entry.offset, entry.offset + entry.size)
    return buf[entry.offset:entry.offset + entry.size]


# --------------------------------------------------------------------------- TIM2
def tim2_pictures(buf: bytes) -> list[dict]:
    if buf[:4] != b"TIM2" or len(buf) < 16:
        raise ValueError("not a TIM2 file")
    fmt, count = buf[5], struct.unpack_from("<H", buf, 6)[0]
    p = 128 if fmt == 1 else 16
    pics = []
    for _ in range(count):
        if p + 48 > len(buf):
            raise ValueError("TIM2 picture header past end of data")
        total, clut_size, image_size, header_size, clut_colors = struct.unpack_from("<IIIHH", buf, p)
        pict_format, mipmaps, clut_type, image_type = buf[p + 16:p + 20]
        width, height = struct.unpack_from("<HH", buf, p + 20)
        bpp = TIM2_BPP.get(image_type, 0)
        pics.append({
            "width": width, "height": height, "bpp": bpp, "clut_colors": clut_colors,
            "clut_type": clut_type, "mipmaps": mipmaps, "image_size": image_size,
            "clut_size": clut_size, "header_size": header_size, "pict_format": pict_format,
            "packed_ok": image_size == width * height * bpp // 8,
        })
        if total <= 0:
            break
        p += total
    return pics


def classify_payload(payload: bytes, codec: str) -> str:
    head = payload[:4]
    if head == b"TIM2":
        return "tim2"
    if head == b"pBAV":
        return "vab_header"
    if head == b"pQES":
        return "seq"
    if head == b"\x00\x00\x00\x00" and len(payload) >= 16 and payload[:16] == bytes(16):
        return "vb_adpcm"  # PS ADPCM bodies open with a silent 16-byte block
    return "unknown"


# --------------------------------------------------------------------------- boot ELF
def elf_info(elf: bytes) -> dict:
    if elf[:4] != b"\x7fELF":
        raise ValueError("boot file is not an ELF")
    entry, phoff = struct.unpack_from("<II", elf, 24)
    machine = struct.unpack_from("<H", elf, 18)[0]
    phnum = struct.unpack_from("<H", elf, 44)[0]
    segs = []
    for i in range(phnum):
        ptype, poff, vaddr, _pa, filesz, memsz, flags, _al = struct.unpack_from("<8I", elf, phoff + 32 * i)
        segs.append({"type": ptype, "offset": poff, "vaddr": vaddr, "filesz": filesz, "memsz": memsz, "flags": flags})
    return {"machine": machine, "mips": machine == 8, "entry": entry, "segments": segs}


def elf_file_to_vaddr(info: dict, file_off: int) -> int | None:
    for s in info["segments"]:
        if s["type"] == 1 and s["offset"] <= file_off < s["offset"] + s["filesz"]:
            return s["vaddr"] + file_off - s["offset"]
    return None


DAT_PATH_RE = re.compile(rb"\\DATA\\DATA([0-9A-F]{2})\\DATA([0-9A-F]{2})\.DAT;1\x00")
VOICE_RE = re.compile(rb"(?<![ -~])([A-Za-z][A-Za-z .\-]{0,14}?) (VOICE|voice)\x00")


def elf_dat_tables(elf: bytes) -> dict:
    """All DAT path strings plus the longest run of 0x20-stride entries (the file index table)."""
    hits = [(m.start(), "DATA/DATA%s/DATA%s.DAT" % (m.group(1).decode(), m.group(2).decode())) for m in DAT_PATH_RE.finditer(elf)]
    best, run = [], []
    for off, name in hits:
        if run and off - run[-1][0] == 0x20:
            run.append((off, name))
        else:
            run = [(off, name)]
        if len(run) > len(best):
            best = list(run)
    return {
        "string_count": len(hits),
        "distinct_paths": len({n for _, n in hits}),
        "index_table": {"file_offset": best[0][0] if best else None, "stride": 0x20, "count": len(best),
                         "order": "descending" if len(best) > 1 and best[0][1] > best[-1][1] else "ascending",
                         "first": best[0][1] if best else None, "last": best[-1][1] if best else None},
        "descriptor_refs": [{"file_offset": o, "path": n} for o, n in hits if (o, n) not in set(best)],
    }


def elf_voice_roster(elf: bytes) -> list[dict]:
    """Character names from the sound-test ``<NAME> VOICE`` tables, in table order."""
    tables = collections.OrderedDict()
    for m in VOICE_RE.finditer(elf):
        name = m.group(1).decode("ascii").strip()
        tables.setdefault(m.group(2).decode(), []).append({"name": name, "file_offset": m.start(1)})
    return [{"table": k, "names": v} for k, v in tables.items()]


# --------------------------------------------------------------------------- inventory
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def container_record(path: str, f: IsoFile, buf: bytes) -> dict:
    entries = parse_ra(buf)
    rec_entries, kinds, bpp = [], collections.Counter(), collections.Counter()
    for e in entries:
        payload = ra_entry_payload(buf, e) if e.size else b""
        kind = classify_payload(payload, e.codec) if payload else "empty"
        kinds[kind] += 1
        item = {"index": e.index, "offset": e.offset, "size": e.size, "codec": e.codec,
                "decoded_size": len(payload), "kind": kind, "sha256": _sha(payload)}
        if kind == "tim2":
            pics = tim2_pictures(payload)
            item["pictures"] = [{k: p[k] for k in ("width", "height", "bpp", "clut_colors", "mipmaps", "packed_ok")} for p in pics]
            for p in pics:
                bpp[p["bpp"]] += 1
        rec_entries.append(item)
    tims = [p for it in rec_entries for p in it.get("pictures", [])]
    signature = sorted({(p["width"], p["height"], p["bpp"]) for p in tims})
    if kinds and set(kinds) <= {"vab_header", "seq", "vb_adpcm", "unknown"} and "tim2" not in kinds:
        role = "sound_bank"
    elif kinds.get("tim2", 0) >= 60 and bpp.get(4, 0) * 2 >= sum(bpp.values()):
        role = "sprite_animation_bank"
    elif kinds.get("tim2", 0):
        role = "texture_set"
    else:
        role = "unknown"
    return {"path": path, "lba": f.lba, "size": f.size, "sha256": _sha(buf), "entry_count": len(entries),
            "kinds": dict(kinds), "tim2_bpp": {str(k): v for k, v in sorted(bpp.items())},
            "signature": ["%dx%d@%d" % s for s in signature], "role": role, "entries": rec_entries}


def inventory(iso_path: str, source_path: str | None = None, source_sha256: str | None = None,
              boot_copy_dir: str | None = None) -> dict:
    with Iso9660(iso_path) as iso:
        cnf = parse_system_cnf(iso.read("SYSTEM.CNF"))
        boot_name = cnf.get("boot_file") or SERIAL
        elf = iso.read(boot_name)
        info = elf_info(elf)
        containers = []
        for f in sorted(iso.files, key=lambda x: x.lba):
            if f.path.upper().startswith("DATA/") and f.path.upper().endswith(".DAT"):
                containers.append(container_record(f.path, f, iso.read(f.path)))
        iop = [{"path": f.path, "size": f.size, "sha256": _sha(iso.read(f.path))} for f in iso.files if f.path.upper().startswith("IOP/")]
        files = [{"path": f.path, "lba": f.lba, "size": f.size} for f in sorted(iso.files, key=lambda x: x.lba)]
        volume = {"system_id": iso.system_id, "volume_id": iso.volume_id, "publisher": iso.publisher,
                  "created": iso.created, "blocks": iso.volume_blocks}
    if boot_copy_dir:
        os.makedirs(boot_copy_dir, exist_ok=True)
        dst = os.path.join(boot_copy_dir, boot_name)
        if not os.path.exists(dst):
            with open(dst, "wb") as fh:
                fh.write(elf)
    groups = collections.defaultdict(list)
    for c in containers:
        groups[(c["role"], tuple(c["signature"]))].append(c["path"])
    totals = collections.Counter()
    for c in containers:
        totals["entries"] += c["entry_count"]
        for k, v in c["kinds"].items():
            totals[k] += v
        totals["cmp3"] += sum(1 for e in c["entries"] if e["codec"] == "cmp3")
        totals["raw"] += sum(1 for e in c["entries"] if e["codec"] == "raw")
        totals["tim2_pictures"] += sum(len(e.get("pictures", [])) for e in c["entries"])
    tables = elf_dat_tables(elf)
    idx = tables["index_table"]
    if idx["file_offset"] is not None:
        idx["vaddr"] = elf_file_to_vaddr(info, idx["file_offset"])
    iso_sha = sha256_file(iso_path)
    src_sha = source_sha256 or (sha256_file(source_path) if source_path else None)
    return {
        "game_id": GAME_ID,
        "title": "Super Bust-A-Move (USA)",
        "platform": cnf["platform"],
        "source": {"path": source_path, "sha256": src_sha, "container": "CHD v5 CD (one MODE1/2048 track)",
                   "matches_known": src_sha == KNOWN["chd_sha256"] if src_sha else None},
        "iso": {"path": iso_path, "sha256": iso_sha, "bytes": os.path.getsize(iso_path),
                "matches_known": iso_sha == KNOWN["iso_sha256"], **volume},
        "system_cnf": cnf,
        "boot": {"file": boot_name, "sha256": _sha(elf), "bytes": len(elf),
                 "matches_known": _sha(elf) == KNOWN["boot_elf_sha256"], **info},
        "launch_prerequisites": {
            "emulator": "PCSX2 (catalog core retroarch/pcsx2; rocketlauncher on the Windows node)",
            "bios": "PS2 BIOS (NTSC-U) supplied by the emulator install; not on the disc",
            "media": "CD (MODE1/2048) image; boot ELF loads IOP/IOPRP202.IMG then SIO2MAN/PADMAN/MCMAN/MCSERV/RSPU2DRV",
            "region": cnf.get("VMODE"), "version": cnf.get("VER"),
        },
        "iop_modules": iop,
        "files": files,
        "elf_dat_tables": tables,
        "roster_from_exe": elf_voice_roster(elf),
        "totals": dict(totals),
        "groups": [{"role": r, "signature": list(sig), "count": len(p), "paths": p} for (r, sig), p in sorted(groups.items(), key=lambda kv: kv[1][0])],
        "containers": containers,
        "format_notes": {
            "container": "-RA-: magic+12 zero bytes, u32 count @0x14, u32 offsets @0x18, entries run to next offset",
            "cmp3": "CMP3 + u32 decoded size + Okumura LZSS (N=4096 zero ring, r0=0xFEE, LSB-first flags, 1=literal, off=b0|(b1&0xF0)<<4, len=(b1&15)+3)",
            "sprites": "2D sprite frames are TIM2 pictures, mostly 4bpp/16-colour CLUT; character data has no 3D mesh or skeleton",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Super Bust-A-Move (USA) PS2 source inventory")
    ap.add_argument("iso")
    ap.add_argument("--source", help="owned CHD (hashed as the stage source identity)")
    ap.add_argument("--source-sha256")
    ap.add_argument("--boot-copy-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.source, a.source_sha256, a.boot_copy_dir)
    with open(a.out, "w") as fh:
        json.dump(m, fh, indent=1)
    t = m["totals"]
    print(json.dumps({"out": a.out, "platform": m["platform"], "boot": m["boot"]["file"], "boot_sha256": m["boot"]["sha256"],
                      "containers": len(m["containers"]), "totals": t,
                      "roster": [[n["name"] for n in tb["names"]] for tb in m["roster_from_exe"]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
