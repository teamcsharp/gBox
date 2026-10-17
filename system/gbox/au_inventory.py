"""Inventory for 007 - Agent Under Fire (USA) (GameCube), game 65b7187589166b26.

Owned source: hyperspin Dolphin GCZ
    collections/Nintendo GameCube/roms/007 - Agent Under Fire (USA).gcz
    sha256 00a0ebbd99cf3934b626dbc0d5bfa0de53e91a1f717fbb1814cb6c93d393faac

Disc: GW7E01 (USA), "007: Agent Under Fire (tm)", EA (maker 0x69),
1,459,978,240-byte image, EAGL engine ("BIGF" .viv bigfiles + .ngc level
archives).  The boot path is boot.bat -> boot.elf; the main game
executable is Bond.elf (PowerPC ELF).

Usage:
    python -m gbox.au_inventory SRC.gcz --out au_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct

from .gcz import GCZ

GAME_ID = "65b7187589166b26"
TITLE = "007 - Agent Under Fire (USA)"
PLATFORM = "gamecube"

# Observed in the owned build's BIGF headers (see Viv.parse):
#   "BIGF" | u32 size (LE, == archive byte length) |
#   u32 file_count (BE) | u32 toc_size (BE) |
#   u32 unknown_a (BE) | u32 unknown_b (BE) | interleaved TOC:
#   (name \0 + u32be offset + u32be size) x file_count, then data.
VIV_HEADER_SIZE = 24


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FST:
    """GameCube filesystem table (standard 12-byte entries)."""

    def __init__(self, raw: bytes):
        if len(raw) < 12:
            raise ValueError("FST too small")
        word, parent, nxt = struct.unpack(">III", raw[:12])
        if not word >> 24:
            raise ValueError("FST root is not a directory")
        self.entry_count = nxt
        if self.entry_count * 12 > len(raw):
            raise ValueError(
                f"FST declares {self.entry_count} entries but only "
                f"{len(raw) // 12} fit")
        self.raw = raw
        self._names_base = self.entry_count * 12

    def _name(self, name_off: int) -> str:
        if name_off >= len(self.raw) - self._names_base:
            raise ValueError(f"name offset {name_off} out of range")
        end = self.raw.index(b"\x00", self._names_base + name_off)
        return self.raw[self._names_base + name_off:end].decode("latin1")

    def _entry(self, i: int):
        word, a, b = struct.unpack(
            ">III", self.raw[i * 12:i * 12 + 12])
        return bool(word >> 24), word & 0xFFFFFF, a, b

    def _next_index(self, i: int) -> int:
        is_dir, _, _, b = self._entry(i)
        return b if is_dir else i + 1

    def walk(self):
        """Yield (path, file_offset, file_size) for every regular file."""
        out = []

        def visit(i: int, prefix: str):
            is_dir, name_off, a, b = self._entry(i)
            name = self._name(name_off)
            if is_dir:
                j = i + 1
                while j < b:
                    visit(j, f"{prefix}/{name}" if name else prefix)
                    j = self._next_index(j)
            else:
                out.append((f"{prefix}/{name}", a, b))

        visit(0, "")
        return out


class ElfPPC:
    """Minimal PowerPC ELF (big-endian) header reader."""

    def __init__(self, data: bytes):
        if len(data) < 52 or data[:4] != b"\x7fELF":
            raise ValueError("not a big-endian ELF header")
        ident = data[4:20]
        (ident_class, ident_data,
         ident_version) = (ident[0], ident[1], ident[2])
        if ident_class != 1 or ident_data != 2:
            raise ValueError(
                "expected ELFCLASS32/ELFDATA2MSB "
                f"(got class={ident_class} data={ident_data})")
        (e_type, e_machine, e_version, e_entry, e_phoff, e_shoff,
         e_flags, e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum,
         e_shstrndx) = struct.unpack(">HHIIIIIHHHHHH", data[16:52])
        if e_machine != 20:  # EM_PPC
            raise ValueError(f"unexpected e_machine {e_machine}")
        self.entry = e_entry
        self.phoff, self.phentsize, self.phnum = e_phoff, e_phentsize, e_phnum
        self.shoff, self.shentsize, self.shnum = e_shoff, e_shentsize, e_shnum
        self.shstrndx = e_shstrndx
        self.flags = e_flags
        self._data = data

    def sections(self):
        """Return raw section-header records (name resolution omitted)."""
        out = []
        for i in range(self.shnum):
            off = self.shoff + i * self.shentsize
            rec = self._data[off:off + 40]
            if len(rec) < 40:
                break
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
             sh_link, sh_info, sh_align, sh_entsize) = struct.unpack(
                ">IIIIIIIIII", rec)
            out.append({
                "index": i, "type": sh_type, "flags": sh_flags,
                "addr": sh_addr, "offset": sh_offset, "size": sh_size,
            })
        return out


class Viv:
    """EA EAGL 'BIGF' bigfile ('.viv' containers on the disc).

    Header is 24 bytes, then interleaved TOC records of
    (null-terminated name, u32be data_offset, u32be data_size),
    then the data blobs.
    """

    def __init__(self, data: bytes, name: str = "<viv>",
                 total_size: int | None = None):
        self.name = name
        self.data = data
        if total_size is None:
            total_size = len(data)
        if data[:4] != b"BIGF":
            raise ValueError(f"{name}: missing BIGF magic")
        # Size field is little-endian in the driving.dat archives; the
        # remaining header fields are big-endian (observed: count and
        # toc_size validated against the actual TOC content).
        size_le = struct.unpack("<I", data[4:8])[0]
        count, toc_size, unk_a, unk_b = struct.unpack(">IIII", data[8:24])
        self.size_field_le = size_le
        self.file_count_be = count
        self.toc_size_be = toc_size
        self.unknown = (unk_a, unk_b)
        self.entries = []
        pos = VIV_HEADER_SIZE
        end = total_size
        for _ in range(count):
            if pos >= len(data):
                raise ValueError(f"{name}: TOC overruns head")
            nz = data.find(b"\x00", pos)
            if nz < 0 or nz + 1 + 8 > len(data):
                raise ValueError(f"{name}: bad TOC entry name")
            entry_name = data[pos:nz].decode("latin1")
            if (not entry_name or len(entry_name) > 200
                    or any(ord(c) < 32 or ord(c) > 126 for c in entry_name)):
                exc = ValueError(
                    f"{name}: TOC drift at byte {pos} "
                    f"(entry {len(self.entries)}); record layout differs "
                    f"from (name, u32be off, u32be size)")
                exc.partial_entries = list(self.entries)
                raise exc
            offset, size = struct.unpack(">II", data[nz + 1:nz + 9])
            if offset + size > end:
                raise ValueError(
                    f"{name}: entry {entry_name!r} at {offset}+{size} "
                    f"exceeds archive ({end})")
            self.entries.append((entry_name, offset, size))
            pos = nz + 9

    def read_entry(self, name: str) -> bytes:
        for entry_name, offset, size in self.entries:
            if entry_name == name:
                return self.data[offset:offset + size]
        raise KeyError(name)

    def entry_sha256(self, name: str) -> str:
        return sha256_bytes(self.read_entry(name))

    def names(self):
        return [e[0] for e in self.entries]


def manifest(src: str) -> dict:
    import os
    src_sha = sha256_bytes(open(src, "rb").read()) if False else None
    h = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    src_sha = h.hexdigest()

    with GCZ(src) as g:
        header = g.read(0x00, 0x80)
        game_code = header[0:4].decode("ascii", "replace")
        maker = header[4:6].decode("ascii", "replace")
        region = chr(header[3])
        title = header[0x20:0x60].decode("ascii", "replace").rstrip("\x00")
        disc_magic = header[0x18:0x1C].hex()
        dol_off, fst_off, fst_size, fst_max = struct.unpack(
            ">IIII", g.read(0x420, 16))
        fst_raw = g.read(fst_off, fst_size)
        fst = FST(fst_raw)
        files = fst.walk()
        exes = []
        archives = {"viv": [], "ngc": [], "other": []}
        census = {}
        for path, off, size in files:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else "(none)"
            census[ext] = census.get(ext, 0) + 1
            stem = path.rsplit("/", 1)[-1]
            if ext == "elf":
                data = g.read(off, min(size, 1 << 20))
                elf = ElfPPC(data)
                exes.append({
                    "path": path, "offset": off, "size": size,
                    "sha256": g.sha256_range(off, size),
                    "entry": elf.entry,
                    "phoff": elf.phoff, "phnum": elf.phnum,
                })
            elif ext == "viv":
                archives["viv"].append({
                    "path": path, "offset": off, "size": size,
                    "sha256": g.sha256_range(off, size),
                })
            elif ext == "ngc":
                archives["ngc"].append({
                    "path": path, "offset": off, "size": size,
                    "sha256": g.sha256_range(off, size),
                })

        # TOC census for every BIGF archive (names drive the character
        # inventory, so keep them in the manifest).
        viv_tocs = []
        for rec in archives["viv"]:
            size = rec["size"]
            head = g.read(rec["offset"], min(size, 1 << 20))
            try:
                viv = Viv(head, rec["path"], total_size=size)
                entries = [{"name": n, "offset": o, "size": s}
                           for n, o, s in viv.entries]
                viv_tocs.append({
                    "path": rec["path"],
                    "file_count_field": viv.file_count_be,
                    "toc_size_field": viv.toc_size_be,
                    "size_field_le": viv.size_field_le,
                    "unknown_fields": list(viv.unknown),
                    "entries": entries,
                    "note": ("entry offsets are absolute within the "
                             "archive; TOC only parsed from the first "
                             "1 MiB head"),
                })
            except ValueError as exc:
                partial = [{"name": n, "offset": o, "size": s}
                           for n, o, s in
                           getattr(exc, "partial_entries", [])]
                viv_tocs.append({
                    "path": rec["path"], "error": str(exc),
                    "partial_entries": partial,
                })

        char_hits = {}
        for toc in viv_tocs:
            if "entries" not in toc:
                continue
            for e in toc["entries"]:
                n = e["name"].lower()
                for key in ("char", "bond", "villain", "hero", "actor",
                            "player", "costume", ".mus", "model", ".gsh"):
                    if key in n:
                        char_hits.setdefault(toc["path"], []).append(e["name"])

        dir_census = {}
        for path, _, _ in files:
            parts = path.split("/")[1:-1]
            for depth in range(1, len(parts) + 1):
                key = "/".join(parts[:depth])
                dir_census[key] = dir_census.get(key, 0) + 1

        return {
            "game_id": GAME_ID,
            "title": TITLE,
            "platform": PLATFORM,
            "catalog": {
                "library": "hyperspin",
                "rel_path": "collections/Nintendo GameCube/roms/"
                            "007 - Agent Under Fire (USA).gcz",
                "core": "dolphin",
            },
            "source": {
                "sha256": src_sha,
                "size": g.file_size,
                "format": f"dolphin-gcz-v{sub_type_to_str(g.sub_type)}",
                "sub_type": g.sub_type,
                "block_size": g.block_size,
                "num_blocks": g.num_blocks,
                "data_size": g.data_size,
            },
            "disc": {
                "game_code": f"{game_code}{header[6]}{header[7]}",
                "game_code4": game_code,
                "maker": maker,
                "region_byte": region,
                "title": title,
                "disc_magic_0x1c": disc_magic,
                "dol_offset_0x420": dol_off,
                "fst_offset": fst_off,
                "fst_size": fst_size,
                "fst_max_size": fst_max,
                "fst_entries": fst.entry_count,
                "file_count": len(files),
                "total_file_bytes": sum(s for _, _, s in files),
            },
            "extensions_census": census,
            "directory_census": dir_census,
            "fst_files": [
                {"path": p, "offset": o, "size": s} for p, o, s in files],
            "executables": sorted(exes, key=lambda r: r["path"]),
            "archives": {k: sorted(v, key=lambda r: r["path"])
                         for k, v in archives.items()},
            "viv_tocs": viv_tocs,
            "character_container_hits": char_hits,
            "launch_prerequisites": {
                "core": "dolphin (RetroArch)",
                "runtime": "auto-install on Windows node "
                           "(catalog runtimes retroarch/dolphin)",
                "source_supported": "dolphin reads GCZ natively",
                "boot_chain": "boot.bat -> odrun boot.elf; main game "
                              "Bond.elf (per gc_map.txt level list)",
                "emulator_workers": "JAYBUILTFINALE (dolphin core)",
            },
            "character_status": (
                "2D/3D asset data nested inside EAGL BIGF .viv archives "
                "and .ngc level packages; the exact mesh/texture/animation "
                "entries are analysis-stage work (Bond.elf loaders)."
            ),
        }


def sub_type_to_str(sub: int) -> str:
    return "full" if sub == 0 else "scrubbed"


def extract(src: str, names, out_dir: str) -> list:
    """Copy disc files out of the GCZ by FST path ("/base.elf/Bond.elf") or basename ("Bond.elf").

    Returns [{"path", "offset", "size", "sha256", "out"}] in the order found; unknown names raise KeyError.
    The GCZ is never written to.
    """
    import os
    wanted = {n.lower(): n for n in names}
    found = []
    os.makedirs(out_dir, exist_ok=True)
    with GCZ(src) as g:
        _, fst_off, fst_size, _ = struct.unpack(">IIII", g.read(0x420, 16))
        for path, off, size in FST(g.read(fst_off, fst_size)).walk():
            key = path.lower() if path.lower() in wanted else path.rsplit("/", 1)[-1].lower()
            if key not in wanted:
                continue
            data = g.read(off, size)
            out = os.path.join(out_dir, path.rsplit("/", 1)[-1])
            with open(out, "wb") as f:
                f.write(data)
            found.append({"path": path, "offset": off, "size": size,
                          "sha256": sha256_bytes(data), "out": out})
            wanted.pop(key)
    if wanted:
        raise KeyError("not on the disc: " + ", ".join(sorted(wanted.values())))
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="path to the owned .gcz file")
    ap.add_argument("--out", default="au_inventory.json")
    ap.add_argument("--extract", nargs="+", metavar="FILE",
                    help="copy these disc files (FST path or basename, e.g. Bond.elf) "
                         "into --out-dir instead of writing the manifest")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args(argv)
    if args.extract:
        for rec in extract(args.src, args.extract, args.out_dir):
            print(f"{rec['sha256']}  {rec['size']:10d}  {rec['path']} -> {rec['out']}")
        return 0
    m = manifest(args.src)
    with open(args.out, "w") as f:
        json.dump(m, f, indent=2, sort_keys=True)
    print(f"wrote {args.out}")
    print("source sha256:", m["source"]["sha256"])
    print("disc:", m["disc"]["game_code"], m["disc"]["title"])
    print("files:", m["disc"]["file_count"],
          "exes:", len(m["executables"]),
          "viv:", len(m["archives"]["viv"]),
          "ngc:", len(m["archives"]["ngc"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
