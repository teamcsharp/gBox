"""One call from a library file (disc image, ROM, archive or install folder) to a file listing with the first bytes of
every file and the main executable: what the fingerprinter (gbox.assimilate) and the inventory stage start from.

  .iso/.gcm (GameCube/Wii)  gcdisc FST           .gcz            gcz + formats.gcfst
  .iso (PS1/PS2), .bin      formats.iso9660      .chd (PS1 v4)   psxdisc.PSXDisc
  .gdi / .cdi (Dreamcast)   gdrom.GDRom          .z64/.v64/.n64  n64_rom (no filesystem: magic scan of the ROM)
  .nds (Nintendo DS)         formats.nitro NitroFS (LZ77 members listed decompressed)
  .zip                      its members          folder (PC/Steam, extracted disc)  the files

listing() never writes and reads at most `head` bytes of at most `max_files` files (the rest are listed by name and
size only), so it is safe on a slow share.
"""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gcfst, iso9660

EXECUTABLE_NAMES = ("main.dol", "1st_read.bin", "default.xbe", "default.xex", "eboot.bin", "boot.bin", "start.dol")


@dataclass
class Listing:
    source: str
    kind: str                                             # gc_disc | iso9660 | gdrom | n64_rom | zip | folder | ...
    files: list[dict] = field(default_factory=list)       # {path, size, head (bytes)}
    executable: bytes = b""
    executable_name: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self, head: int = 16) -> dict:
        return {"source": self.source, "kind": self.kind, "executable": self.executable_name,
                "executable_size": len(self.executable), "notes": self.notes,
                "files": [{"path": f["path"], "size": f["size"], "head": f.get("head", b"")[:head].hex()}
                          for f in self.files]}


def _boot_name(cnf: bytes) -> str:
    import re
    m = re.search(rb"BOOT2?\s*=\s*cdrom0?:\\?\\?([^;\s]+)", cnf, re.I)
    return m.group(1).decode("latin-1").replace("\\", "/").lstrip("/").upper() if m else ""


def _pick_exe(files: list[dict], read) -> tuple[str, bytes]:
    by = {f["path"].upper(): f for f in files}
    cnf = by.get("SYSTEM.CNF")
    if cnf:
        boot = _boot_name(read(cnf["path"], 512))
        if boot and boot in by:
            return by[boot]["path"], read(by[boot]["path"], None)
    for f in files:
        if Path(f["path"]).name.lower() in EXECUTABLE_NAMES:
            return f["path"], read(f["path"], None)
    exes = [f for f in files if f["path"].lower().endswith((".exe", ".elf", ".xex", ".dol"))]
    if exes:
        f = max(exes, key=lambda f: f["size"])
        return f["path"], read(f["path"], None)
    return "", b""


def _fill(files: list[dict], read, head: int, max_files: int) -> None:
    for f in files[:max_files]:
        try:
            f["head"] = read(f["path"], head)
        except Exception:                                 # noqa: BLE001  (a damaged entry costs its head only)
            f["head"] = b""


def listing(path: str | Path, *, head: int = 64, max_files: int = 4000, exe_limit: int = 64 << 20,
            deep: int = 12, deep_bytes: int = 1 << 20) -> Listing:
    """deep / deep_bytes: the first deep_bytes of the `deep` largest files are kept as f["sample"] (archives such as
    AFS, DATA.BIN or .IMG show their inner formats only there)."""
    p = Path(path)
    suf = p.suffix.lower()
    from .. import rom_archives
    if p.is_dir():
        files = [{"path": q.relative_to(p).as_posix(), "size": q.stat().st_size} for q in sorted(p.rglob("*")) if q.is_file()]

        def read(name, n):
            with open(p / name, "rb") as fh:
                return fh.read(exe_limit if n is None else n)
        L = Listing(str(p), "folder", files)
    elif rom_archives.is_archive(p):
        files = [{'path': e['name'], 'size': e['size']} for e in rom_archives.members(p)]

        def read(name, n):
            return rom_archives.prefix(p, name, exe_limit if n is None else n)
        L = Listing(str(p), "zip" if suf == '.zip' else "archive", files)
        roms = [f for f in files if f["path"].lower().endswith((".z64", ".v64", ".n64"))]
        if roms:
            L.kind = "n64_rom"
            L.executable_name, L.executable = roms[0]["path"], read(roms[0]["path"], None)
            _n64_scan(L)
            return L
    elif suf in (".z64", ".v64", ".n64"):
        from .. import n64_rom
        L = Listing(str(p), "n64_rom", [], n64_rom.read(p), p.name)
        _n64_scan(L)
        return L
    elif suf in (".nds", ".srl"):
        from .nitro import NitroROM, decompress
        rom = NitroROM(p.read_bytes())
        files = [{"path": n, "size": len(rom.raw(n))} for n in rom.paths()]

        def read(name, n):                                # raw heads (the LZ77 tag is evidence); deep samples
            raw = rom.raw(name)                           # decompressed so inner magics are seen
            return raw[:n] if n is not None and n <= head else decompress(raw)[: (exe_limit if n is None else n)]
        L = Listing(str(p), "nitrofs", files, notes=[f"{rom.gamecode} {rom.title}"])
        L.executable_name = "arm9.bin"
        L.executable = rom.data[rom.arm9_off:rom.arm9_off + min(rom.arm9_size, exe_limit)]
    elif suf == ".gdi" or suf == ".cdi":
        from ..gdrom import GDRom
        g = GDRom(p)
        files = [{"path": k, "size": v[1]} for k, v in g.files.items()]

        def read(name, n):
            return g.read(name)[: (exe_limit if n is None else n)]
        L = Listing(str(p), "gdrom", files)
    elif suf == ".chd":
        from ..psxdisc import PSXDisc
        d = PSXDisc(p)
        files = [{"path": k, "size": v[1]} for k, v in d.files.items()]

        def read(name, n):
            return d.read(name)[: (exe_limit if n is None else n)]
        L = Listing(str(p), "iso9660", files)
    elif suf == ".gcz":
        from ..gcz import GCZ
        z = GCZ(str(p))
        h = gcfst.disc_header(z.read(0, 0x440))
        ents = gcfst.parse_fst(z.read(h["fst_offset"], h["fst_size"]), h["fst_offset"])
        files = [{"path": a, "size": s, "_off": o} for a, o, s, _e in ents]
        offs = {f["path"]: f["_off"] for f in files}

        def read(name, n):
            size = next(f["size"] for f in files if f["path"] == name)
            return z.read(offs[name], min(size, exe_limit if n is None else n))
        L = Listing(str(p), "gc_disc", files, notes=[f"{h['game_id']} {h['title']}"])
        L.executable_name, L.executable = "main.dol", _dol(lambda o, n: z.read(o, n), h["dol_offset"])
    else:
        with open(p, "rb") as fh:
            hdr = fh.read(0x440)
            fh.seek(0x8000)
            pvd = fh.read(2048)
        if len(hdr) >= 0x440 and struct.unpack_from(">I", hdr, 0x1C)[0] == 0xC2339F3D or hdr[0x18:0x1C] == b"\x5D\x1C\x9E\xA3":
            from ..gcdisc import GCDisc
            g = GCDisc(p)
            files = [{"path": k, "size": v[1]} for k, v in g.files.items()]

            def read(name, n):
                o, s = g.files[name]
                return g._r(o, min(s, exe_limit if n is None else n))
            L = Listing(str(p), "gc_disc", files, notes=[f"{g.game_id} {g.title}"])
            L.executable_name, L.executable = "main.dol", g.dol()
        elif pvd[1:6] == b"CD001":
            fh = open(p, "rb")
            lba, size = iso9660.pvd_root(pvd)
            table = iso9660.files(iso9660.file_reader(fh), lba, size, max_depth=16, max_dir_size=1 << 22)
            files = [{"path": k, "size": v[1]} for k, v in table.items()]

            def read(name, n):
                lba, s = table[name]
                fh.seek(lba * 2048)
                return fh.read(min(s, exe_limit if n is None else n))
            L = Listing(str(p), "iso9660", files)
        else:
            raise ValueError(f"{p.name}: not a disc image, ROM, archive or folder gBox can list")
    _fill(L.files, read, head, max_files)
    for f in sorted(L.files, key=lambda f: -f["size"])[:deep]:
        try:
            f["sample"] = read(f["path"], deep_bytes)
        except Exception:                                 # noqa: BLE001
            pass
    if len(L.files) > max_files:
        L.notes.append(f"{len(L.files) - max_files} files listed without their first bytes (max_files={max_files})")
    if not L.executable:
        try:
            L.executable_name, L.executable = _pick_exe(L.files, read)
        except Exception as e:                            # noqa: BLE001
            L.notes.append(f"executable not read: {type(e).__name__}: {e}")
    return L


def _dol(read, off: int) -> bytes:
    hdr = read(off, 0x100)
    offs, sizes = struct.unpack_from(">18I", hdr, 0), struct.unpack_from(">18I", hdr, 0x90)
    end = max((o + s for o, s in zip(offs, sizes) if s), default=0x100)
    return read(off, end)


N64_MAGICS = (b"MIO0", b"Yaz0", b"Yay0", b"RNC\x01", b"RNC\x02", b"vpk0")


def _n64_scan(L: Listing) -> None:
    """N64 ROMs have no filesystem: list every aligned codec header as a pseudo-file 'rom@offset'."""
    rom = L.executable
    for m in N64_MAGICS:
        i = rom.find(m)
        while i != -1 and len(L.files) < 20000:
            if i % 2 == 0:
                L.files.append({"path": f"rom@{i:08X}", "size": 0, "head": rom[i:i + 64]})
            i = rom.find(m, i + 1)
    L.notes.append(f"N64 ROM {len(rom)} bytes; {len(L.files)} codec headers")
