"""Switch asset extraction: NSP -> NCA -> RomFS -> files, without any per-title guessing.

gBox could list XCI containers (`formats/nsw.py`) and layer replacement files over a title (`switch_mods.py`)
but had no way to *read* the game's own RomFS: `switch_mods._base_file` says so in one line, "gBox has no NCA
decryption". This module is that missing half.

It uses `nsz` (pypi) for the container and the crypto, and parses the RomFS FST itself, because nsz exposes
the decrypted RomFS section as a file-like stream rather than a file tree:

    header (0x50 bytes) -> dir_hash, dir_meta, file_hash, file_meta, data
    dir entry  (0x18 + name): u32 parent, u32 next, u64 child_file, u64 child_dir, u32 hash, u32 name_len
    file entry (0x20 + name): u32 parent, u32 next, u64 offset, u64 size, u32 hash, u32 name_len

Reading is targeted: the metadata tables are a few hundred KB, a file is read at its own offset, so a 19 GB
RomFS is never materialised.

Keys come from the operator's switch keys (prod.keys + title.keys); nothing here contains a key.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

KEY_SEARCH = (
    "~/gBox_alt/switch",
    "/mnt/gbox/quickswap2/Emulation/_switch",
    "~/gBox/system/gbox-data/switch",
)
TITLE_RE = re.compile(r"\[([0-9A-Fa-f]{16})\]")
KIND_BY_EXT = {
    # measured on Resident Evil 5 (Switch): .adpcm x10676, .opus x3916, .arc x1452, .srqr x486,
    # .sbkr x477, .mse x249, .stqr x94, .tex x68, .ase x37
    "model": {".mod", ".mesh", ".smd", ".dae", ".mse", ".ase", ".gr2", ".skl"},
    "texture": {".tex", ".png", ".jpg", ".jpeg", ".dds", ".tga", ".bmp", ".gif"},
    "audio": {".adpcm", ".opus", ".sngw", ".ogg", ".wav", ".at9", ".adx", ".sfx", ".mca", ".wem"},
    "video": {".mp4", ".bk2", ".usm", ".webm", ".srt"},
    "font": {".otf", ".ttf", ".fnt"},
    "data": {".json", ".xml", ".txt", ".csv", ".ini", ".db", ".eng"},
    "archive": {".arc", ".pkg", ".pak", ".bnk", ".sbnk", ".grp", ".dat", ".srqr", ".sbkr", ".stqr", ".cpk"},
}


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    for kind, exts in KIND_BY_EXT.items():
        if ext in exts:
            return kind
    return "other"


@dataclass
class Entry:
    path: str
    size: int
    offset: int            # offset inside the RomFS data area


@dataclass
class Inventory:
    title_id: str
    source: str
    entries: list[Entry] = field(default_factory=list)
    romfs_section: int = -1
    at: float = 0.0

    def counts(self) -> dict:
        out = {}
        for e in self.entries:
            out[kind_of(e.path)] = out.get(kind_of(e.path), 0) + 1
        return out

    def to_json(self) -> dict:
        return {"title_id": self.title_id, "source": self.source, "at": self.at,
                "romfs_section": self.romfs_section, "counts": self.counts(),
                "entries": [{"path": e.path, "size": e.size, "offset": e.offset} for e in self.entries]}


def keys_paths():
    prod = title = None
    for root in KEY_SEARCH:
        base = Path(root).expanduser()
        if (base / "prod.keys").is_file() and prod is None:
            prod = base / "prod.keys"
        if (base / "title.keys").is_file() and title is None:
            title = base / "title.keys"
    return prod, title


def _nsz():
    import nsz
    from nsz import Keys
    from nsz.Fs import Nsp as NspMod
    return nsz, Keys, NspMod


def open_nsp(path: str | Path):
    """Open a title NSP. nsz requires the [titleId] convention in the filename, so a compliant symlink is made."""
    nsz, Keys, NspMod = _nsz()
    prod, title = keys_paths()
    if not prod:
        raise RuntimeError("no prod.keys on this box")
    Keys.load(str(prod))
    if title:
        Keys.load(str(title))
    src = Path(path)
    title_id = TITLE_RE.search(src.name)
    if not title_id:
        # derive from the NSP's own ticket name is not available without opening; require the caller to pass one
        raise RuntimeError("the NSP filename must contain [titleId] (nsz requirement)")
    nsp = NspMod.Nsp(str(src))
    nsp.open()
    return nsp, title_id.group(1).upper()


def _sections(nsp):
    """Yield (index, filesystem) for every section of the largest NCA (the game NCA)."""
    ncas = [f for f in getattr(nsp, "files", []) if type(f).__name__ == "Nca"]
    if not ncas:
        raise RuntimeError("the NSP holds no NCA")
    game = max(ncas, key=lambda n: getattr(n, "size", 0))
    game.open()
    for i, fs in enumerate(getattr(game, "sectionFilesystems", []) or []):
        yield i, fs


class RomFS:
    """A parser over a decrypted RomFS section (file-like with seek/read)."""

    def __init__(self, stream):
        self.stream = stream
        self.stream.seek(0)
        head = self.stream.read(0x50)
        if len(head) < 0x50:
            raise ValueError("romfs header too short")
        (self.header_size, self.dir_hash_off, self.dir_hash_size, self.dir_meta_off,
         self.dir_meta_size, self.file_hash_off, self.file_hash_size, self.file_meta_off,
         self.file_meta_size, self.data_off) = struct.unpack_from("<10Q", head, 0)
        if self.header_size != 0x50:
            raise ValueError(f"not a romfs (header_size 0x{self.header_size:x})")
        self.stream.seek(self.dir_meta_off)
        self.dir_meta = self.stream.read(self.dir_meta_size)
        self.stream.seek(self.file_meta_off)
        self.file_meta = self.stream.read(self.file_meta_size)

    def _dir_at(self, off: int):
        base = self.dir_meta
        parent, nxt, child_file, child_dir, _hash, name_len = struct.unpack_from("<IIQQII", base, off)
        name = base[off + 0x18: off + 0x18 + name_len].decode("utf-8", "replace")
        return {"parent": parent, "next": nxt, "child_file": child_file, "child_dir": child_dir,
                "name": name}

    def _file_at(self, off: int):
        base = self.file_meta
        parent, nxt, data_off, size, _hash, name_len = struct.unpack_from("<IIQQII", base, off)
        name = base[off + 0x20: off + 0x20 + name_len].decode("utf-8", "replace")
        return {"parent": parent, "next": nxt, "offset": data_off, "size": size, "name": name}

    def entries(self) -> list[Entry]:
        out: list[Entry] = []
        stack = [(0, "")]                      # (dir offset, prefix); root dir is at offset 0
        seen = set()
        while stack:
            off, prefix = stack.pop()
            if off in seen:
                continue
            seen.add(off)
            node = self._dir_at(off)
            if node["child_file"] != 0xFFFFFFFFFFFFFFFF:
                f = node["child_file"]
                guard = 0
                while f != 0xFFFFFFFFFFFFFFFF and guard < 100000:
                    fe = self._file_at(f)
                    out.append(Entry(prefix + fe["name"], fe["size"], fe["offset"]))
                    f = fe["next"]
                    guard += 1
            if node["child_dir"] != 0xFFFFFFFFFFFFFFFF:
                d = node["child_dir"]
                guard = 0
                while d != 0xFFFFFFFFFFFFFFFF and guard < 100000:
                    de = self._dir_at(d)
                    stack.append((d, prefix + de["name"] + "/"))
                    d = de["next"]
                    guard += 1
        return out

    def read(self, entry: Entry) -> bytes:
        self.stream.seek(self.data_off + entry.offset)
        return self.stream.read(entry.size)


class FileRange:
    """A seek/read window over a region of a file: enough for the RomFS parser, no caching, no giant reads."""

    def __init__(self, path: str | Path, base: int, size: int):
        self.path = str(path)
        self.base = base
        self.size = size
        self._fh = open(self.path, "rb")
        self._pos = 0

    def seek(self, pos: int, whence: int = 0):
        self._pos = {0: pos, 1: self._pos + pos, 2: self.size + pos}[whence]
        return self._pos

    def tell(self) -> int:
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        self._fh.seek(self.base + self._pos)
        data = self._fh.read(n)
        self._pos += len(data)
        return data

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


UNIT = 0x200          # NCA media offsets and IVFC ranges are in 0x200-byte units


def section_infos(nca) -> list[dict]:
    """Per section: crypto type, fs type and the IVFC level table, read from nsz's decrypted header.

    Layout (from nsz/Fs/Ivfc.py): magic, magicNumber, masterHashSize, numberLevels, then numberLevels-1
    levels of 20 bytes: offset u64, size u64, blockSize u32, reserved u32. The last level is the data.
    """
    hdr = nca.header
    hdr.seek(0x400)
    out = []
    for index in range(4):
        raw = hdr.read(0x200)
        if len(raw) < 0x200:
            break
        info = {"index": index, "crypto": raw[2], "fs": raw[3]}
        ivfc_at = raw.find(b"IVFC")
        if ivfc_at >= 0:
            magic_number = struct.unpack_from("<I", raw, ivfc_at + 4)[0]
            master_hash = struct.unpack_from("<I", raw, ivfc_at + 8)[0]
            number_levels = struct.unpack_from("<I", raw, ivfc_at + 12)[0]
            pos = ivfc_at + 16
            levels = []
            for _ in range(max(0, number_levels - 1)):
                off, size = struct.unpack_from("<QQ", raw, pos)
                block = struct.unpack_from("<I", raw, pos + 16)[0]
                levels.append({"offset": off, "size": size, "block": block})
                pos += 24        # u64 offset, u64 size, u32 blockSize, u32 reserved
            info["ivfc"] = {"magic_number": magic_number, "master_hash_size": master_hash,
                            "number_levels": number_levels, "levels": levels}
        out.append(info)
    return out


def romfs_source(nsp_path: str | Path) -> dict:
    """Locate the title's RomFS: the section whose header carries an IVFC table, at its last level."""
    nsp, title_id = open_nsp(nsp_path)
    ncas = [f for f in getattr(nsp, "files", []) if type(f).__name__ == "Nca"]
    if not ncas:
        raise RuntimeError("the NSP holds no NCA")
    nca = max(ncas, key=lambda n: getattr(n, "size", 0))
    if getattr(nca, "header", None) is None:      # nsp.open() already opened it; re-opening resets the header
        nca.open()
    base = int(getattr(nca, "offset", 0))
    tables = nca.header.sectionTables
    best = None
    reasons = []
    for info in section_infos(nca):
        ivfc = info.get("ivfc")
        if not ivfc or not ivfc["levels"]:
            reasons.append(f"section {info['index']}: no ivfc levels")
            continue
        data = ivfc["levels"][-1]
        # the data extent may be recorded in 0x200 units (RE5's 0x2518000 * 0x200 equals its section size)
        size_units = data["size"] * UNIT
        section_start = tables[info["index"]].mediaOffset * UNIT
        section_end = tables[info["index"]].mediaEndOffset * UNIT
        span = section_end - section_start
        for size in (data["size"], size_units):
            if 0 < size <= span + UNIT:
                best = {"title_id": title_id, "section": info["index"], "crypto": info["crypto"],
                        "base": base + section_start + data["offset"], "size": size,
                        "offset_in_section": data["offset"], "levels": ivfc["levels"],
                        "number_levels": ivfc["number_levels"]}
                break
        if best:
            break
        reasons.append(f"section {info['index']}: data size {data['size']:#x} ({size_units:#x}) "
                       f"outside span {span:#x}, offset {data['offset']:#x}")
    if best is None:
        raise RuntimeError("no usable IVFC section (RomFS): " + "; ".join(reasons[:4]))
    return best


def _romfs_for(nsp_path: str | Path):
    src = romfs_source(nsp_path)
    stream = FileRange(nsp_path, src["base"], src["size"])
    return src, RomFS(stream)


def inventory(nsp_path: str | Path, cache_dir: Path | None = None) -> Inventory:
    """List every file in the title's RomFS (metadata only; no file data is read).

    Prefers hactool, which decrypts and decompresses the sections this module could not (block-compressed
    NCAs, rights-id titles with the ticket's title key). Falls back to the built-in IVFC/CTR reader.
    """
    try:
        inv = inventory_hactool(nsp_path)
    except Exception:
        src, romfs = _romfs_for(nsp_path)
        inv = Inventory(title_id=src["title_id"], source=str(nsp_path), entries=romfs.entries(),
                        romfs_section=src["section"], at=time.time())
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{inv.title_id}.json").write_text(json.dumps(inv.to_json()), encoding="utf-8")
    return inv


# ---------------------------------------------------------------- hactool backend
HACTOOL_CANDIDATES = (
    "~/gBox_alt/hactool/hactool",
    "/usr/local/bin/hactool",
    "/opt/hactool/hactool",
    "~/hactool/hactool",
)


def hactool_path() -> Path | None:
    """The hactool binary, if this box has one (GBOX_HACTOOL overrides)."""
    override = os.environ.get("GBOX_HACTOOL")
    if override and Path(override).is_file():
        return Path(override)
    for cand in HACTOOL_CANDIDATES:
        p = Path(cand).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def _ticket_key(nsp_path: str | Path) -> str:
    """The ticket's decrypted title key as hex, for hactool's --titlekey."""
    nsp, _tid = open_nsp(nsp_path)
    ticket = next((f for f in nsp.files if type(f).__name__ == "Ticket"), None)
    if ticket is None:
        raise RuntimeError("this NSP carries no ticket")
    tk = ticket.getTitleKey()
    return tk if isinstance(tk, str) else bytes(tk).hex()


def _game_nca_path(nsp_path: str | Path) -> Path:
    """Extract just the biggest NCA next to the NSP (once), because hactool wants an NCA file."""
    src = Path(nsp_path)
    work = Path(os.environ.get("GBOX_SWITCH_WORK", Path.home() / "gBox_alt" / "switch" / "work"))
    work.mkdir(parents=True, exist_ok=True)
    cached = sorted(work.glob("game-*.nca"))
    if cached:
        return cached[0]
    nsp, _tid = open_nsp(nsp_path)
    ncas = [f for f in nsp.files if type(f).__name__ == "Nca"]
    if not ncas:
        raise RuntimeError("the NSP holds no NCA")
    nca = max(ncas, key=lambda n: getattr(n, "size", 0))
    out = work / f"game-{getattr(nca, 'size', 0)}.nca"
    with open(src, "rb") as fh, open(out, "wb") as dst:
        fh.seek(int(getattr(nca, "offset", 0)))
        remaining = int(getattr(nca, "size", 0))
        while remaining > 0:
            chunk = fh.read(min(8 << 20, remaining))
            if not chunk:
                break
            dst.write(chunk)
            remaining -= len(chunk)
    return out


def inventory_hactool(nsp_path: str | Path) -> Inventory:
    """List the RomFS through hactool: it handles the block-compressed sections and rights-id crypto."""
    tool = hactool_path()
    if tool is None:
        raise RuntimeError("hactool is not installed on this box")
    prod, _title = keys_paths()
    if not prod:
        raise RuntimeError("no prod.keys on this box")
    nca = _game_nca_path(nsp_path)
    cmd = [str(tool), "-k", str(prod), f"--titlekey={_ticket_key(nsp_path)}", "-t", "nca",
           "--listromfs", str(nca)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"hactool failed ({proc.returncode}): {proc.stderr[-300:]}")
    entries = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("rom:/"):
            continue
        path = line[len("rom:/"):]
        if path and not path.endswith("/"):
            entries.append(Entry(path, 0, 0))
    if not entries:
        raise RuntimeError("hactool listed no RomFS entries")
    tid = TITLE_RE.search(Path(nsp_path).name)
    return Inventory(title_id=(tid.group(1).upper() if tid else ""), source=str(nsp_path),
                     entries=entries, romfs_section=1, at=time.time())


def extract(nsp_path: str | Path, inner_path: str, out_path: str | Path) -> Path:
    """Read one RomFS file out to disk.

    hactool extracts whole directories, so a single file is taken from its full extraction when that exists,
    otherwise the built-in reader is used.
    """
    want = inner_path.lstrip("/")
    out = Path(out_path)
    tool = hactool_path()
    if tool is not None:
        cache = Path(os.environ.get("GBOX_SWITCH_ROMFS", Path.home() / "gBox_alt" / "switch" / "romfs"))
        candidate = cache / want
        if candidate.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(candidate.read_bytes())
            return out
    _src, romfs = _romfs_for(nsp_path)
    entry = next((e for e in romfs.entries() if e.path == want), None)
    if entry is None:
        raise FileNotFoundError(f"{inner_path!r} is not in this RomFS (and no extracted tree is cached)")
    data = romfs.read(entry)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def extract_tree(nsp_path: str | Path, out_dir: str | Path) -> Path:
    """Extract the whole RomFS through hactool (a big, one-time operation: RE5's tree is ~19 GB)."""
    tool = hactool_path()
    if tool is None:
        raise RuntimeError("hactool is not installed on this box")
    prod, _title = keys_paths()
    nca = _game_nca_path(nsp_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(tool), "-k", str(prod), f"--titlekey={_ticket_key(nsp_path)}", "-t", "nca",
           f"--romfsdir={out}", str(nca)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600)
    if proc.returncode != 0:
        raise RuntimeError(f"hactool extraction failed ({proc.returncode}): {proc.stderr[-300:]}")
    return out
