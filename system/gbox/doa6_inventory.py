"""`doa6_inventory`: source inventory for the owned Dead or Alive 6 PC build.

The catalog labels this favorite ps_modern / "Sony PlayStation 4", but the owned artifact is the
Windows/Steam CODEX build (Steam AppID 838380). The game stores assets in KT-engine "DRK/RDB"
indexes (`_DRK0000`) plus IDRK chunk containers (`IDRK0000`, zlib chunks of 0x4000), shipped both
packed in `<rdbname>.rdb.bin*` files and loose in `data/0x%08x.file` (the executable loads loose
files by hash via `G1AFileResourceHash`, so `data/` is the native override surface).

Usage:
    python -m gbox.doa6_inventory GAMEDIR --out manifest.json [--bins-manifest bins_manifest.json]

The DRK index layout (same container family as Persona 5, quickbms persona5.bms):
    "_DRK0000" u32 goto u32 0x10 u32 files u32 ? cstr mountpath
    entry: "IDRK0000" u64 entry_size u64 ? u64 size u32 num1 u32 crc1 u32 crc2 u32 flags u32 ?
           u32 num2, num2*(u32,u32,u32), num1 bytes, [cstr name if flags&0x20000], pad4
A loose `0x<crc1:08x>.file` holds one IDRK entry: same header, then u32 zsize + zlib chunk per
0x4000 of output. Packed bins hold the same entry streams back to back.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

DRK_MAGIC = b"_DRK0000"
IDRK_MAGIC = b"IDRK0000"
RNK_MAGIC = b"_RNK0000"
CHUNK_SIZE = 0x4000

KNOWN_RDBS = (
    "KIDSSystemResource", "MaterialEditor", "system", "ScreenLayout",
    "RRPreview", "FieldEditor4", "CharacterEditor", "EventMaker3",
)


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


class RdbEntry:
    __slots__ = ("name", "crc1", "crc2", "flags", "size", "entry_size", "index_offset")

    def __init__(self, name: str, crc1: int, crc2: int, flags: int, size: int,
                 entry_size: int, index_offset: int):
        self.name = name
        self.crc1 = crc1
        self.crc2 = crc2
        self.flags = flags
        self.size = size
        self.entry_size = entry_size
        self.index_offset = index_offset

    def to_json(self) -> dict:
        return {"name": self.name, "crc1": self.crc1, "crc2": self.crc2,
                "flags": self.flags, "size": self.size, "index_offset": self.index_offset}


class Rdb:
    """Parsed `_DRK0000` index file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        if self.raw[:8] != DRK_MAGIC:
            raise ValueError(f"{path} is not a DRK index (magic {self.raw[:8]!r})")
        self.entry_offset, _dummy, self.file_count, _dummy2 = struct.unpack_from("<4I", self.raw, 8)
        end = self.raw.find(b"\0", 0x18)
        self.mount_path = self.raw[0x18:end].decode("latin1")
        self.entries: list[RdbEntry] = []
        pos = self.entry_offset
        for _ in range(self.file_count):
            entry = self._read_entry(pos)
            self.entries.append(entry)
            pos = (pos + entry.entry_size + 3) & ~3  # entry_size does not count inter-entry pad
        self.end_offset = pos

    def _read_entry(self, pos: int) -> RdbEntry:
        if self.raw[pos:pos + 8] != IDRK_MAGIC:
            raise ValueError(f"no IDRK entry at {pos:#x} of {self.path}")
        entry_size, _dummy, size, num1 = struct.unpack_from("<QQQI", self.raw, pos + 8)
        crc1, crc2, flags, _zero, num2 = struct.unpack_from("<5I", self.raw, pos + 36)
        p = pos + 56 + 12 * num2 + num1
        name = ""
        if flags & 0x20000:
            end = self.raw.find(b"\0", p)
            if end < 0:
                raise ValueError(f"unterminated name at {p:#x} of {self.path}")
            name = self.raw[p:end].decode("latin1")
        return RdbEntry(name, crc1, crc2, flags, size, entry_size, pos)

    def bins(self) -> list[Path]:
        """`<rdbname>.rdb.bin*` siblings, sorted."""
        stem = self.path.name  # e.g. RRPreview.rdb
        base = stem[:-4]  # RRPreview
        return sorted(self.path.parent.glob(base + ".rdb.bin*"))

    def to_json(self) -> dict:
        return {
            "file": str(self.path),
            "mount_path": self.mount_path,
            "file_count": self.file_count,
            "named": sum(1 for e in self.entries if e.name),
            "end_offset": self.end_offset,
            "parses_clean": self.end_offset == len(self.raw),
            "bins": [{"name": b.name, "size": b.stat().st_size} for b in self.bins()],
            "entries": [e.to_json() for e in self.entries],
        }


class Idrk:
    """One IDRK container: header fields plus chunk-decompressing reader."""

    def __init__(self, header: bytes, payload: bytes):
        if header[:8] != IDRK_MAGIC:
            raise ValueError(f"not an IDRK entry (magic {header[:8]!r})")
        self.entry_size, _dummy, self.size, self.num1 = struct.unpack_from("<QQQI", header, 8)
        self.crc1, self.crc2, self.flags, _zero, self.num2 = struct.unpack_from("<5I", header, 36)
        self.payload = payload

    @classmethod
    def from_bytes(cls, blob: bytes) -> "Idrk":
        if blob[:8] != IDRK_MAGIC:
            raise ValueError(f"not an IDRK entry (magic {blob[:8]!r})")
        entry_size = struct.unpack_from("<Q", blob, 8)[0]
        _dummy, size, num1 = struct.unpack_from("<QQI", blob, 16)
        crc1, crc2, flags, _zero, num2 = struct.unpack_from("<5I", blob, 36)
        p = 56 + 12 * num2 + num1
        if flags & 0x20000:
            end = blob.find(b"\0", p)
            if end < 0:
                raise ValueError("unterminated name in IDRK entry")
            p = end + 1
        p = (p + 3) & ~3
        self = cls(blob[:entry_size], blob[p:])
        # keep the caller's entry_size boundary only when the header agrees with it
        if entry_size >= p:
            self.payload = blob[p:entry_size] or blob[p:]
        return self

    def read_data(self, limit: int | None = None) -> bytes:
        out = bytearray()
        p = 0
        payload = self.payload
        while p < len(payload) and len(out) < self.size and (limit is None or len(out) < limit):
            zsize = struct.unpack_from("<I", payload, p)[0]
            p += 4
            chunk = zlib.decompress(payload[p:p + zsize])
            p += zsize
            out += chunk
        return bytes(out[:limit]) if limit is not None else bytes(out)

    def decompressed_size(self) -> int:
        return self.size


def read_loose_file(path: Path, limit: int | None = None, read_all: bool = False) -> bytes:
    """Decompress a loose `data/0xNNNNNNNN.file` IDRK container.

    With read_all=False only the header plus the first chunk are read from disk, which is
    enough for magic sniffing of multi-GB files.
    """
    path = Path(path)
    if read_all:
        blob = path.read_bytes()
    else:
        with open(path, "rb") as f:
            head = f.read(56)
            entry_size = struct.unpack_from("<Q", head, 8)[0]
            blob = head + f.read(min(entry_size - 56, 0x4000 + 4))
    return Idrk.from_bytes(blob).read_data(limit)


def sniff_magic(data: bytes) -> str:
    """Best-effort content classification from the first bytes."""
    if data[:8] == RNK_MAGIC:
        return "rnk"
    if data[:8] == DRK_MAGIC:
        return "drk"
    if data[:4] == b"G1M\x00" or data[:4] == b"G1MX":
        return "g1m"
    if data[:4] in (b"G1TG", b"G1T\x00", b"KTID"):
        return "g1t/ktid"
    if data[:4] in (b"G1AG", b"G1A\x00"):
        return "g1a"
    if data[:4] == b"KSCL":
        return "kscl"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF":
        return "riff"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:2] == b"PK":
        return "zip"
    return "unknown"


def inventory(game_dir: str | Path, bins_manifest: str | Path | None = None) -> dict:
    """Enumerate the owned DOA6 PC build and return a JSON-able manifest."""
    root = Path(game_dir)
    exe = root / "DOA6.exe"
    if not exe.exists():
        raise FileNotFoundError(f"no DOA6.exe under {root}")
    manifest = {
        "game_dir": str(root),
        "platform_label": "ps_modern (catalog label; actual content is Windows/Steam PC, AppID 838380)",
        "executable": {
            "name": exe.name,
            "size": exe.stat().st_size,
            "sha256": sha256_file(exe),
        },
        "rdbs": {},
        "loose": {},
        "launch": {},
    }
    for stem in KNOWN_RDBS:
        idx = root / (stem + ".rdb")
        if idx.exists():
            rdb = Rdb(idx)
            manifest["rdbs"][stem] = {
                "index_sha256": sha256_file(idx),
                "mount_path": rdb.mount_path,
                "file_count": rdb.file_count,
                "named": sum(1 for e in rdb.entries if e.name),
                "parses_clean": rdb.end_offset == len(rdb.raw),
                "bins": [{"name": b.name, "size": b.stat().st_size} for b in rdb.bins()],
            }
    data_dir = root / "data"
    if data_dir.is_dir():
        loose = sorted(data_dir.glob("0x*.file"))
        total = sum(f.stat().st_size for f in loose)
        kinds: dict[str, int] = {}
        from concurrent.futures import ThreadPoolExecutor

        def sniff_one(f: Path) -> str:
            try:
                return sniff_magic(read_loose_file(f, limit=8))
            except (ValueError, zlib.error):
                return "unreadable"

        with ThreadPoolExecutor(max_workers=16) as pool:
            for magic in pool.map(sniff_one, loose):
                kinds[magic] = kinds.get(magic, 0) + 1
        manifest["loose"] = {"files": len(loose), "total_bytes": total, "content": kinds}
    steam = {f.name for f in root.glob("steam_api64*")} | {f.name for f in root.glob("steamclient64*")}
    manifest["launch"] = {
        "prerequisites": "Windows x64, Steam (AppID 838380) or CODEX emu; saves at "
                         "%SystemDrive%\\Users\\Public\\Documents\\Steam\\CODEX\\838380",
        "steam_dlls": sorted(steam),
        "codex": sorted(f.name for f in root.glob("codex64*")),
        "redist": sorted(p.name for p in (root / "_CommonRedist").iterdir())
        if (root / "_CommonRedist").is_dir() else [],
    }
    if bins_manifest and Path(bins_manifest).exists():
        manifest["bins_manifest"] = json.loads(Path(bins_manifest).read_text())
    return manifest


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="DOA6 owned-build inventory")
    parser.add_argument("game_dir")
    parser.add_argument("--out", default=None, help="write the manifest to this JSON file")
    parser.add_argument("--bins-manifest", default=None)
    args = parser.parse_args()
    m = inventory(args.game_dir, args.bins_manifest)
    text = json.dumps(m, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
