"""Konductra (USA) (nds) native inventory reader -- stage 1 (inventory).

Game id : e5bf646a3ab9f344   (library: hyperspin)
Owned source (authoritative manifest):

  archive   : Arcade/collections/Nintendo DS/roms/Konductra (USA).7z
  sha256    : d5fd7ebcf230380d8cb6b790e26c4440fc9d7502d997cfdb0cc05e60d6dd6633
  member    : 0646 - Konductra (U)(Legacy).nds   (16777216 bytes)
  member sha: a71cafed14fa6d3871aa117dbf87ff50d0a72f74e21922488ea590aab267a6b1
  container : Nintendo DS cartridge image -- 0x200 byte header, ARM9/ARM7
              binaries, FAT (file allocation table) + FNT (filename table)
  byte order: little-endian throughout

What this module proves, and what it does not:

  * identity: the sha256 of the owned bytes is computed by streaming the file
    in 1 MiB chunks (never copied from a reference);
  * layout : the cartridge header and the FAT/FNT filesystem are parsed with
    every offset range-checked against the image extent;
  * census : assets are COUNTED from the filesystem (per extension, with
    sizes).  Filename patterns are reported separately and are labelled as
    guesses -- a name is not an asset.

This is an inventory reader only.  No model/texture/palette format is claimed
yet: the Nitro graphics formats (NCGR/NCLR/NSAR) and the LZ10 container are
re-used from gbox.formats.lz / gbox.tetris_ds once the Konductra payloads are
identified.  No writer is claimed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

KONDUKTRA_GAME_ID = "e5bf646a3ab9f344"
KONDUKTRA_TITLE = "Konductra (USA)"
KONDUKTRA_ROM_SHA256 = "a71cafed14fa6d3871aa117dbf87ff50d0a72f74e21922488ea590aab267a6b1"
KONDUKTRA_ROM_MEMBER = "0646 - Konductra (U)(Legacy).nds"
KONDUKTRA_ROM_SIZE = 16777216
KONDUKTRA_ARCHIVE_SHA256 = "d5fd7ebcf230380d8cb6b790e26c4440fc9d7502d997cfdb0cc05e60d6dd6633"
KONDUKTRA_ARCHIVE_PATH = "Arcade/collections/Nintendo DS/roms/Konductra (USA).7z"
KONDUKTRA_SHARE_ROM = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/"
                       "Konductra (USA).7z")

# Extensions that are counted as payload assets.  Purely a reporting bucket.
ASSET_EXTS = (".chr", ".ncgr", ".nclr", ".nsar", ".objs", ".pal", ".img", ".tiles",
              ".sheet", ".atlas", ".arc", ".dat", ".bin", ".raw", ".tex")

# Name patterns: reported as GUESSES only, never counted as assets.
NAME_GUESS_TOKENS = ("char", "konduc", "kond", "hero", "player", "man", "girl",
                      "boss", "enemy", "sprite", "spr", "anim", "face")


def sha256_file(path) -> str:
    """Stream the file in 1 MiB chunks and return its sha256 hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_member(archive: str) -> str | None:
    """Extract the .nds member of a 7z archive into a temp dir; return its path."""
    tool = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
    if not tool:
        return None
    tmp = tempfile.mkdtemp(prefix="konductra_")
    try:
        r = subprocess.run([tool, "x", "-y", f"-o{tmp}", archive], capture_output=True)
        if r.returncode != 0:
            return None
        for root, _dirs, names in os.walk(tmp):
            for name in names:
                if name.lower().endswith(".nds"):
                    return os.path.join(root, name)
    finally:
        pass  # temp dir is left for the caller lifetime; caller may clean up
    return None


def find_rom(path: str | None = None) -> Path | None:
    """Locate the owned Konductra .nds (explicit path, env var, or the share)."""
    candidates = []
    if path:
        candidates.append(Path(path))
    env = os.environ.get("KONDUKTRA_NDS")
    if env:
        candidates.append(Path(env))
    for cand in candidates:
        if cand.is_file() and cand.suffix.lower() == ".nds":
            return cand
    if os.environ.get("KONDUKTRA_NDS_ARCHIVE"):
        arc = os.environ["KONDUKTRA_NDS_ARCHIVE"]
        member = _extract_member(arc)
        if member:
            return Path(member)
    if os.path.isfile(KONDUKTRA_SHARE_ROM):
        member = _extract_member(KONDUKTRA_SHARE_ROM)
        if member:
            return Path(member)
    return None


class KonductraNDS:
    """Read-only Nintendo DS cartridge: header + FAT/FNT filesystem."""

    def __init__(self, data: bytes):
        if len(data) < 0x200:
            raise ValueError("not an NDS image (too small)")
        self.data = data
        self.title = data[0x00:0x0C].decode("ascii", "replace").rstrip("\x00")
        self.gamecode = data[0x0C:0x10].decode("ascii", "replace")
        self.unitcode = data[0x12]
        (self.arm9_off, self.arm9_entry, self.arm9_ram, self.arm9_size) = struct.unpack_from("<IIII", data, 0x20)
        (self.arm7_off, self.arm7_entry, self.arm7_ram, self.arm7_size) = struct.unpack_from("<IIII", data, 0x30)
        (self.fnt_off, self.fnt_size) = struct.unpack_from("<II", data, 0x40)
        (self.fat_off, self.fat_size) = struct.unpack_from("<II", data, 0x48)
        if self.fat_size % 8:
            raise ValueError(f"FAT size {self.fat_size} is not a multiple of 8")
        if self.fat_off + self.fat_size > len(data):
            raise ValueError("FAT out of image range")
        self._fat = [struct.unpack_from("<II", data, off)
                     for off in range(self.fat_off, self.fat_off + self.fat_size, 8)]
        self._files, self._dirs, self.dir_entry_size = self._parse_fnt()

    def _parse_fnt(self):
        if self.fnt_off + self.fnt_size > len(self.data):
            raise ValueError("FNT out of image range")
        fnt = self.data[self.fnt_off:self.fnt_off + self.fnt_size]
        if len(fnt) < 8:
            raise ValueError("FNT truncated")
        root_off = struct.unpack_from("<I", fnt, 0)[0]
        first_id = struct.unpack_from("<H", fnt, 4)[0]
        last = None
        for dir_entry_size in (4, 2):     # standard Nitro (id+parent) then id-only
            try:
                files, dirs, end = self._walk(fnt, root_off, "", [first_id], dir_entry_size)
            except Exception as exc:      # try the other directory-entry layout
                last = exc
                continue
            if end == len(fnt):
                return files, dirs, dir_entry_size
            if end < len(fnt) and not any(fnt[end:]):
                return files, dirs, dir_entry_size   # trailing NUL padding only
            last = ValueError(f"FNT walk ended at 0x{end:X}, FNT size 0x{len(fnt):X}")
        raise ValueError(f"FNT parse failed: {last}")

    def _walk(self, fnt, sub_off, prefix, counter, dir_entry_size):
        files, dirs = {}, []
        pos = sub_off
        kids = []
        while True:
            if pos >= len(fnt):
                raise ValueError("FNT overrun")
            ctl = fnt[pos]
            pos += 1
            if ctl == 0:
                break
            namelen = ctl & 0x7F
            is_dir = bool(ctl & 0x80)
            name = fnt[pos:pos + namelen].decode("ascii", "replace")
            pos += namelen
            if is_dir:
                if pos + dir_entry_size > len(fnt):
                    raise ValueError("FNT directory entry truncated")
                dir_id = struct.unpack_from("<H", fnt, pos)[0]
                pos += dir_entry_size
                kids.append((name, dir_id))
            else:
                fid = counter[0]
                counter[0] += 1
                if fid >= len(self._fat):
                    raise ValueError(f"file id {fid} beyond FAT ({len(self._fat)} entries)")
                start, end = self._fat[fid]
                if start > end or end > len(self.data):
                    raise ValueError(f"FAT entry {fid} out of image range")
                path = f"{prefix}/{name}".lstrip("/")
                files[path] = {"path": path, "id": fid, "start": start, "end": end,
                               "size": end - start}
        for name, dir_id in kids:
            child = f"{prefix}/{name}".lstrip("/")
            dirs.append({"path": child, "id": dir_id})
            sub_files, sub_dirs, pos = self._walk(fnt, pos, child, counter, dir_entry_size)
            files.update(sub_files)
            dirs.extend(sub_dirs)
        return files, dirs, pos

    def paths(self) -> list[str]:
        return sorted(self._files)

    def raw(self, path: str) -> bytes:
        info = self._files[path]
        return self.data[info["start"]:info["end"]]

    def files(self) -> list[dict]:
        return [self._files[p] for p in self.paths()]

    def census(self) -> dict:
        """Counted assets (from the filesystem) kept separate from name guesses."""
        exts = Counter()
        for info in self._files.values():
            ext = os.path.splitext(info["path"])[1].lower() or "<none>"
            exts[ext] += 1
        counted = [{"ext": e, "count": c} for e, c in sorted(exts.items(), key=lambda kv: (-kv[1], kv[0]))]
        guesses = [f for f in self.files()
                   if any(tok in f["path"].lower() for tok in NAME_GUESS_TOKENS)]
        assets = [f for f in self.files()
                  if os.path.splitext(f["path"])[1].lower() in ASSET_EXTS]
        assets.sort(key=lambda f: (-f["size"], f["path"]))
        candidates = []
        for f in assets[:10]:
            head = self.raw(f["path"])[:4]
            candidates.append({**f, "head_hex": head.hex(),
                               "lz10": len(head) == 1 and head[0] == 0x10})
        return {
            "counted_by_ext": counted,
            "counted_total": sum(exts.values()),
            "counted_bytes": sum(f["size"] for f in self._files.values()),
            "name_guesses": [{"path": g["path"], "size": g["size"]} for g in guesses],
            "target_candidates": candidates,
            "directories": self._dirs,
        }


def _cross_check(data: bytes, files: list[dict]) -> dict:
    """Independent parse with the existing gbox.tetris_ds NDSRom reader."""
    try:
        from .tetris_ds import NDSRom
    except Exception as exc:                     # pragma: no cover - optional
        return {"ran": False, "reason": f"import failed: {exc}"}
    try:
        other = NDSRom(data)
    except Exception as exc:
        return {"ran": False, "reason": f"tetris_ds NDSRom failed: {exc}"}
    return {"ran": True, "reader": "gbox.tetris_ds.NDSRom",
            "file_count": len(other.paths()),
            "agrees": len(other.paths()) == len(files)}


def inventory(path: str | None = None) -> dict:
    """Stage 1: exact build identity + container layout + counted asset census."""
    rom = find_rom(path)
    if rom is None:
        raise FileNotFoundError(
            "owned Konductra (USA) ROM not reachable; set KONDUKTRA_NDS or "
            "KONDUKTRA_NDS_ARCHIVE to the owned file")
    digest = sha256_file(rom)
    data = rom.read_bytes()
    nds = KonductraNDS(data)
    files = nds.files()
    out = {
        "game_id": KONDUKTRA_GAME_ID,
        "title": KONDUKTRA_TITLE,
        "source": {"path": str(rom), "sha256": digest, "size": len(data),
                   "member": KONDUKTRA_ROM_MEMBER,
                   "expected_sha256": KONDUKTRA_ROM_SHA256,
                   "identity_ok": digest == KONDUKTRA_ROM_SHA256},
        "header": {
            "title": nds.title, "gamecode": nds.gamecode,
            "unitcode": nds.unitcode,
            "arm9": {"offset": nds.arm9_off, "size": nds.arm9_size, "entry": nds.arm9_entry},
            "arm7": {"offset": nds.arm7_off, "size": nds.arm7_size, "entry": nds.arm7_entry},
            "fnt": {"offset": nds.fnt_off, "size": nds.fnt_size},
            "fat": {"offset": nds.fat_off, "size": nds.fat_size},
            "dir_entry_size": nds.dir_entry_size,
            "byte_order": "little-endian",
        },
        "files": {"count": len(files), "list": files},
        "census": nds.census(),
        "cross_check": _cross_check(data, files),
    }
    return out


def build_report(rom_path: str | None = None) -> dict:
    inv = inventory(rom_path)
    return {
        "game_id": inv["game_id"],
        "source_sha256": inv["source"]["sha256"],
        "identity_ok": inv["source"]["identity_ok"],
        "header": inv["header"],
        "file_count": inv["files"]["count"],
        "counted_by_ext": inv["census"]["counted_by_ext"],
        "name_guesses": inv["census"]["name_guesses"],
        "target_candidates": inv["census"]["target_candidates"],
        "cross_check": inv["cross_check"],
    }
