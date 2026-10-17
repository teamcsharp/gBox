"""SoulCalibur III (PS2, SLUS_212.16 v1.01) owned-disc inventory (#1657).

Read-only.  The owned source is the HyperSpin CD-type CHD ``Soulcalibur III (USA).chd``
(CHD v5, one MODE1/2048 track); ``chdman extractcd`` gives a 2048-stride ISO9660 image.
The disc root holds ``PAD_0.DAT`` (1 GiB zero filler), the boot ELF, ``IRX/`` modules,
four CRI AFS archives (MOVIE/BGM/VOICE/SE) and ``ROOT.OLK``, which holds every model,
texture, motion and stage.  The fingerprint's RenderWare guess is metadata-only and is
not borne out by the files: there is no RW chunk stream, the container is Namco OLK.

OLK ("olnk") layout, verified over the whole ROOT.OLK:

* header (16 bytes): u32 entry count N, ``b"olnk"``, u32, u32;
* N+1 records of 16 bytes (u32 offset, u32 size, u32 timestamp, u32 zero);
  record 0 is ``(data_start, total)`` and the entry offsets are relative to
  ``data_start`` (0x800 at the root, the table size rounded up to 0x800 below it);
* a size of 0 is an empty slot (it repeats the previous offset).

ROOT.OLK's eight entries are nested OLKs.  The boot ELF names them: it holds a table
of 16-byte records ``(dir_ptr, name_ptr, 0, entry_count)`` for ``root.olk`` followed by
``motinfo/cpudata/cdata/event/stage/creation/human/contac.olk``.  Each child's entry
count in that table matches the nested OLK's N exactly (cpudata 768, cdata 1072,
event 192, stage 820, creation 3028, human 1413, contac 561), which is what maps the
names to positions.  motinfo is a 1-entry 0x800 placeholder on this build although
the ELF table expects 174 entries.

Most non-empty entries in human/stage/creation are packages: u32 child count, u32
child offsets (0 = empty) with 0x80-aligned children.  Child payload magics include
``"mmp\\0"``, ``"vtb\\0"`` and ``"lpb\\0"`` and a ``0x0b1c0e09``-style header that
also tops the creation group's raw entries.  Decoding those is the analysis stage.

``python -m gbox.sc3_inventory disc.iso --chd-sha256 HEX --out manifest.json``
"""
from __future__ import annotations

import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

SECTOR = 2048
BOOT = "SLUS_212.16"
OLK_MAGIC = b"olnk"
OLK_NAMES = ("root", "motinfo", "cpudata", "cdata", "event", "stage", "creation",
             "human", "contac")


# ---------------------------------------------------------------- ISO9660

class Iso:
    """Seek-based ISO9660 root walk (the image is 4.4 GB; never load it whole)."""

    def __init__(self, path):
        self.path = str(path)
        self.f = open(self.path, "rb")
        pvd = self.sector(16)
        if pvd[1:6] != b"CD001":
            raise ValueError(f"{path}: no ISO9660 PVD at sector 16")
        root = pvd[156:190]
        self.files: dict[str, tuple[int, int]] = {}
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", set())

    def sector(self, lba: int, count: int = 1) -> bytes:
        self.f.seek(lba * SECTOR)
        return self.f.read(count * SECTOR)

    def _walk(self, lba: int, size: int, prefix: str, seen: set) -> None:
        if lba in seen:
            return
        seen.add(lba)
        buf = self.sector(lba, (size + SECTOR - 1) // SECTOR)[:size]
        o = 0
        while o < len(buf):
            ln = buf[o]
            if ln == 0:
                o = (o // SECTOR + 1) * SECTOR
                continue
            elba, esize = struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0]
            flags, nl = buf[o + 25], buf[o + 32]
            raw = buf[o + 33:o + 33 + nl]
            if raw not in (b"\0", b"\1"):
                name = raw.decode("latin-1").split(";")[0]
                if flags & 2:
                    self._walk(elba, esize, f"{prefix}{name}/", seen)
                else:
                    self.files[f"{prefix}{name}"] = (elba, esize)
            o += ln

    def read(self, name: str, offset: int = 0, size: int | None = None) -> bytes:
        lba, fsize = self.files[name]
        if size is None:
            size = fsize - offset
        size = max(0, min(size, fsize - offset))
        self.f.seek(lba * SECTOR + offset)
        return self.f.read(size)

    def sha256(self, name: str) -> str:
        lba, size = self.files[name]
        h = hashlib.sha256()
        self.f.seek(lba * SECTOR)
        left = size
        while left:
            chunk = self.f.read(min(left, 1 << 22))
            h.update(chunk)
            left -= len(chunk)
        return h.hexdigest()


# ---------------------------------------------------------------- OLK

def olk_table(head: bytes) -> dict:
    """Parse an OLK header + record table.  ``head`` must cover 16*(N+2) bytes."""
    if len(head) < 16 or head[4:8] != OLK_MAGIC:
        raise ValueError("not an OLK (no 'olnk' at +4)")
    n = struct.unpack_from("<I", head, 0)[0]
    need = 16 * (n + 2)
    if len(head) < need:
        raise ValueError(f"OLK table needs {need} bytes, got {len(head)}")
    recs = [struct.unpack_from("<IIII", head, 16 + 16 * i) for i in range(n + 1)]
    data_start, total = recs[0][0], recs[0][1]
    entries = []
    for i, (off, size, ts, _z) in enumerate(recs[1:]):
        entries.append({"index": i, "offset": data_start + off, "size": size, "timestamp": ts})
    return {"count": n, "data_start": data_start, "total": total, "entries": entries}


def olk_check(table: dict, length: int) -> list[str]:
    """Return problems: entries outside ``length`` or overlapping non-empty entries."""
    bad = []
    last_end = table["data_start"]
    for e in table["entries"]:
        if e["size"] == 0:
            continue
        if e["offset"] < last_end:
            bad.append(f"entry {e['index']} overlaps previous ({e['offset']:#x} < {last_end:#x})")
        end = e["offset"] + e["size"]
        if end > length:
            bad.append(f"entry {e['index']} ends at {end:#x} past {length:#x}")
        last_end = end
    return bad


def package_children(b: bytes, size: int | None = None) -> list[tuple[int, int]] | None:
    """Namco package: u32 count, u32 offsets (0 = empty).  Returns (offset, size) for the
    non-empty children or None when ``b`` does not look like one."""
    size = len(b) if size is None else size
    if len(b) < 8:
        return None
    c = struct.unpack_from("<I", b, 0)[0]
    if not 0 < c < 256 or 4 + 4 * c > len(b):
        return None
    offs = struct.unpack_from(f"<{c}I", b, 4)
    nz = [x for x in offs if x]
    if not nz or nz != sorted(nz) or nz[0] < 4 + 4 * c or nz[-1] >= size:
        return None
    if any(x % 0x10 for x in nz):
        return None
    uniq = sorted(set(nz))
    return [(o, (uniq[i + 1] if i + 1 < len(uniq) else size) - o) for i, o in enumerate(uniq)]


def magic_label(b: bytes) -> str:
    h = b[:4]
    if len(h) == 4 and h[3] == 0 and all(0x61 <= c <= 0x7a for c in h[:3]):
        return h[:3].decode()
    if h[:4] == b"TIM2":
        return "TIM2"
    return h.hex()


# ---------------------------------------------------------------- boot ELF table

def _elf_segments(elf: bytes) -> list[tuple[int, int, int]]:
    if elf[:4] != b"\x7fELF":
        raise ValueError("boot file is not an ELF")
    phoff = struct.unpack_from("<I", elf, 0x1C)[0]
    phn = struct.unpack_from("<H", elf, 0x2C)[0]
    segs = []
    for i in range(phn):
        p = struct.unpack_from("<8I", elf, phoff + 32 * i)
        if p[0] == 1:
            segs.append((p[2], p[1], p[4]))
    return segs


def elf_olk_table(elf: bytes) -> dict:
    """Find the ELF's OLK name table: 16-byte records (dir_ptr, name_ptr, 0, count)."""
    segs = _elf_segments(elf)

    def o2v(o):
        for va, off, sz in segs:
            if off <= o < off + sz:
                return va + o - off
        return None

    def v2o(v):
        for va, off, sz in segs:
            if va <= v < va + sz:
                return off + v - va
        return None

    root = elf.find(b"root.olk\0")
    if root < 0:
        raise ValueError("no root.olk string in the boot ELF")
    rv = o2v(root)
    pat = struct.pack("<I", rv)
    ref = -1
    for m in range(0, len(elf) - 3, 4):
        if elf[m:m + 4] == pat:
            ref = m
            break
    if ref < 4:
        raise ValueError("no pointer to root.olk")
    rec0 = ref - 4
    out = []
    o = rec0
    while o + 16 <= len(elf):
        dptr, nptr, z, cnt = struct.unpack_from("<4I", elf, o)
        no = v2o(nptr) if nptr else None
        if no is None:
            break
        name = elf[no:elf.index(b"\0", no)].decode("latin-1")
        if not name.endswith(".olk"):
            break
        out.append({"name": name, "count": cnt, "record_vaddr": o2v(o), "name_vaddr": nptr})
        o += 16
    return {"table_vaddr": o2v(rec0), "records": out}


# ---------------------------------------------------------------- inventory

def group_census(iso: Iso, base: int, entries: list[dict], sample: int = 0x1000) -> dict:
    heads = collections.Counter()
    child_magics = collections.Counter()
    packages = 0
    rows = []
    nonempty = [e for e in entries if e["size"]]
    for e in nonempty:
        b = iso.read("ROOT.OLK", base + e["offset"], min(e["size"], sample))
        heads[magic_label(b)] += 1
        kids = package_children(b, e["size"])
        row = {"index": e["index"], "offset": base + e["offset"], "size": e["size"], "head": magic_label(b)}
        if kids:
            packages += 1
            mags = []
            for co, _cs in kids:
                m = magic_label(iso.read("ROOT.OLK", base + e["offset"] + co, 4))
                child_magics[m] += 1
                mags.append(m)
            row["children"] = len(kids)
            row["child_magics"] = mags
        rows.append(row)
    return {
        "slots": len(entries),
        "nonempty": len(nonempty),
        "bytes": sum(e["size"] for e in nonempty),
        "packages": packages,
        "heads": dict(heads.most_common(12)),
        "child_magics": dict(child_magics.most_common(16)),
        "entries": rows,
    }


def inventory(iso_path, chd_sha256: str | None = None, iso_sha256: str | None = None) -> dict:
    iso = Iso(iso_path)
    if BOOT not in iso.files or "ROOT.OLK" not in iso.files:
        raise ValueError(f"{iso_path}: not SoulCalibur III US ({BOOT}/ROOT.OLK missing)")
    cnf = iso.read("SYSTEM.CNF").decode("latin-1")
    elf = iso.read(BOOT)
    names = elf_olk_table(elf)
    root_size = iso.files["ROOT.OLK"][1]
    root = olk_table(iso.read("ROOT.OLK", 0, 16 * 64))
    root_problems = olk_check(root, root_size)
    groups = {}
    elf_children = names["records"][1:]
    for e, rec in zip(root["entries"], elf_children):
        head = iso.read("ROOT.OLK", e["offset"], 16)
        n = struct.unpack_from("<I", head, 0)[0] if head[4:8] == OLK_MAGIC else None
        g = {"root_index": e["index"], "offset": e["offset"], "size": e["size"],
             "elf_count": rec["count"], "olk_count": n}
        if n is not None:
            t = olk_table(iso.read("ROOT.OLK", e["offset"], 16 * (n + 2)))
            g["data_start"] = t["data_start"]
            g["count_matches_elf"] = n == rec["count"]
            g["problems"] = olk_check(t, e["size"])
            g.update(group_census(iso, e["offset"], t["entries"]))
        groups[rec["name"].rsplit(".", 1)[0]] = g
    return {
        "game": "SoulCalibur III",
        "game_id": "afe447a632bd5e6b",
        "platform": "ps2",
        "serial": BOOT.replace("_", "-").replace(".", ""),
        "source_sha256": chd_sha256,
        "image_sha256": iso_sha256,
        "image": str(Path(iso_path).resolve()),
        "system_cnf": cnf,
        "boot": {"path": BOOT, "size": len(elf), "sha256": hashlib.sha256(elf).hexdigest()},
        "files": {k: {"lba": v[0], "size": v[1]} for k, v in sorted(iso.files.items())},
        "launch": {"emulator": "PCSX2 (retroarch/pcsx2)", "vmode": "NTSC",
                   "notes": "single-layer CD-type CHD image; no external BIOS beyond PS2 BIOS"},
        "elf_olk_table": names,
        "root_olk": {"size": root_size, "count": root["count"], "data_start": root["data_start"],
                     "problems": root_problems},
        "groups": groups,
        "engine_check": "fingerprint said RenderWare from metadata only; disc uses Namco OLK, not RW chunk streams",
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "SC3 inventory").splitlines()[0])
    ap.add_argument("iso")
    ap.add_argument("--chd-sha256")
    ap.add_argument("--iso-sha256")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(a.iso, a.chd_sha256, a.iso_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    summary = {k: {kk: v.get(kk) for kk in ("olk_count", "elf_count", "nonempty", "packages", "bytes")}
               for k, v in m["groups"].items()}
    print(json.dumps({"boot": m["boot"], "groups": summary}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
