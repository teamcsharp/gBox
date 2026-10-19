"""Resident Evil 2 Dual Shock Edition (PSX) Disc 2 — memory card save analysis.

The RE2 Dual Shock PSX build does not use the standard PSX memory-card
library (``psopen``/``psdat``/``psmem``).  Progression state — room
completion flags, story gates — lives in BSS (zero-initialized in the
executable image) and is set at runtime by the room-transition code in
the STAGE code overlays.

Three memory-card filename references exist in the ``MEM_CARD.BIN`` data
overlay (``BASLUS-00421*``, ``BASLUS-0074800``, ``BASLUS-0042100``)
followed by an array of PSX virtual addresses in the ``0x801cXXXX``
range that point into the data segment.  The save routine that reads
and writes these files has not been located yet; the filename table and
address list are extracted here so a future run can trace the save
code.

Disc layout (Disc 2, SLUS_007, Claire disc):

* ``SLUS_007.56`` — PS-X EXE, entry ``0x800783c0``, text at
  ``0x80010000`` size ``0xf0800``.
* File table at virtual ``0x8009885c`` (file offset ``0x8888c``),
  858 records of ``{u32 size, u32 pos}`` where
  ``pos = lba | (tag << 24)``.
* ``COMMON/BIN/MEM_CARD.BIN`` — index 253, 23 932 bytes, LBA 71.
* ``COMMON/BIN/CONFIG.BIN`` — index 250, 27 756 bytes, LBA 25.
* ``COMMON/BIN/STAGE1..7.BIN`` — MIPS code overlays (STAGE6 is a data
  pointer table, the rest are executable stage logic).

Room flag table (runtime, BSS):

* Base virtual ``0x800d49e4``, 34 × u32 slots.
* All zeros in the executable image; set/cleared by room-transition
  code.
* Referenced by ``FUN_80049e20`` (room setup) and
  ``DAT_800cfbb8`` (player id slot).

This module extracts the memory-card overlay from a disc image, parses
the filename table and address list, and provides a skeleton save
reader/writer for the PSX memory-card block format so that once the
save routine is located the format can be completed.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# PSX CD sector constants
# ---------------------------------------------------------------------------

SECTOR_SIZE = 2352
SECTOR_HEADER = 48
DATA_OFFSET = SECTOR_HEADER  # data starts at offset 48 within a raw sector


# ---------------------------------------------------------------------------
# File table
# ---------------------------------------------------------------------------

FILE_TABLE_BASE = 0x8009885c
FILE_TABLE_COUNT = 858
# Offset of the file table inside the PS-X EXE (after 48-byte header):
FILE_TABLE_EXE_OFFSET = 0x8888c

PSX_EXE_HEADER_SIZE = 48
PSX_EXE_MAGIC = b"PS-X EXE"


@dataclass
class FileTableRecord:
    """One entry in the PSX file table."""
    index: int
    size: int
    lba: int
    tag: int
    raw_pos: int


def parse_file_table(exe: bytes) -> list[FileTableRecord]:
    """Parse the file table from a PSX executable.

    ``exe`` is the raw bytes of the SLUS_007.56 image (PS-X EXE format).
    Returns a list of :class:`FileTableRecord`.
    """
    if len(exe) < PSX_EXE_HEADER_SIZE + 8:
        raise ValueError("executable too small")
    if exe[:8] != PSX_EXE_MAGIC:
        raise ValueError(f"bad magic: {exe[:8]!r}")

    records: list[FileTableRecord] = []
    for i in range(FILE_TABLE_COUNT):
        off = FILE_TABLE_EXE_OFFSET + i * 8
        if off + 8 > len(exe):
            break
        size, raw_pos = struct.unpack_from("<II", exe, off)
        lba = raw_pos & 0x7FFFFF
        tag = (raw_pos >> 24) & 0xFF
        records.append(FileTableRecord(i, size, lba, tag, raw_pos))
    return records


def extract_file(disc: bytes, rec: FileTableRecord) -> bytes:
    """Extract a file's data from a raw PSX disc image.

    ``disc`` is a raw sector image (2352-byte sectors).  The LBA in the
    file table is the sector number.  Data starts at offset 48 within
    each sector.
    """
    start = rec.lba * SECTOR_SIZE + DATA_OFFSET
    if start + rec.size > len(disc):
        raise ValueError(
            f"file [{rec.index}] out of range: "
            f"start={start} size={rec.size} disc={len(disc)}"
        )
    return disc[start:start + rec.size]


# ---------------------------------------------------------------------------
# MEM_CARD.BIN — memory card overlay
# ---------------------------------------------------------------------------

@dataclass
class MemCardOverlay:
    """Parsed structure of COMMON/BIN/MEM_CARD.BIN."""
    raw: bytes
    filenames: list[str] = field(default_factory=list)
    addresses: list[int] = field(default_factory=list)
    sha256: str = ""

    @property
    def size(self) -> int:
        return len(self.raw)


def parse_mem_card_overlay(data: bytes) -> MemCardOverlay:
    """Parse the MEM_CARD.BIN data overlay.

    Layout (from disc analysis):

    ::

        Offset  Size  Content
        0x000   16    "BASLUS-00421*" + 2 null bytes
        0x010   16    "BASLUS-0074800" + 2 null bytes
        0x020   16    "BASLUS-0042100" + 2 null bytes
        0x030   4     padding (zeros)
        0x034   ...   array of u32 PSX virtual addresses (0x801cXXXX)
    """
    if len(data) < 0x34:
        raise ValueError(f"MEM_CARD.BIN too small: {len(data)} bytes")

    filenames: list[str] = []
    for i in range(3):
        off = i * 16
        raw_name = data[off:off + 16]
        # Strip trailing nulls
        name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        filenames.append(name)

    # Address array starts at 0x34
    addr_count = (len(data) - 0x34) // 4
    addresses: list[int] = []
    for i in range(addr_count):
        off = 0x34 + i * 4
        if off + 4 > len(data):
            break
        addr = struct.unpack_from("<I", data, off)[0]
        addresses.append(addr)

    return MemCardOverlay(
        raw=data,
        filenames=filenames,
        addresses=addresses,
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------------------
# CONFIG.BIN — room/timeline config
# ---------------------------------------------------------------------------

@dataclass
class ConfigOverlay:
    """Parsed structure of COMMON/BIN/CONFIG.BIN."""
    raw: bytes
    section_name: str = ""
    addresses: list[int] = field(default_factory=list)
    sha256: str = ""


def parse_config_overlay(data: bytes) -> ConfigOverlay:
    """Parse the CONFIG.BIN data overlay.

    Layout:

    ::

        Offset  Size  Content
        0x000   16    "01_TIM_LD" + 2 null bytes (section name)
        0x010   ...   array of u32 PSX virtual addresses
    """
    if len(data) < 0x10:
        raise ValueError(f"CONFIG.BIN too small: {len(data)} bytes")

    raw_name = data[:16]
    section_name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    addr_count = (len(data) - 0x10) // 4
    addresses: list[int] = []
    for i in range(addr_count):
        off = 0x10 + i * 4
        if off + 4 > len(data):
            break
        addr = struct.unpack_from("<I", data, off)[0]
        addresses.append(addr)

    return ConfigOverlay(
        raw=data,
        section_name=section_name,
        addresses=addresses,
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------------------
# STAGE code overlays
# ---------------------------------------------------------------------------

@dataclass
class StageOverlay:
    """Parsed structure of a STAGE*.BIN file."""
    raw: bytes
    name: str = ""
    is_code: bool = True
    is_pointer_table: bool = False
    sha256: str = ""
    first_words: list[int] = field(default_factory=list)


def parse_stage_overlay(data: bytes, name: str = "") -> StageOverlay:
    """Parse a STAGE*.BIN overlay.

    STAGE1-5 and STAGE7 are MIPS executable code (little-endian
    instruction words starting with ``0x3c028012`` — a ``lui`` loading
    ``0x8012`` into ``$v0``).  STAGE6 is a data pointer table (array of
    u32 addresses in the ``0x8011XXXX`` range).
    """
    is_code = False
    is_ptr_table = False
    first_words: list[int] = []

    if len(data) >= 4:
        w0 = struct.unpack_from("<I", data, 0)[0]
        # MIPS code overlay: first word is a lui instruction
        # lui $v0, 0x8012 -> 0x3C028012
        if (w0 >> 26) == 0x0C:  # R-type opcode for lui
            is_code = True
            for i in range(min(8, len(data) // 4)):
                first_words.append(struct.unpack_from("<I", data, i * 4)[0])
        # Data pointer table: first words are addresses in 0x80xxxxxx
        elif 0x80000000 <= w0 <= 0x8FFFFFFF:
            is_ptr_table = True
            for i in range(min(8, len(data) // 4)):
                first_words.append(struct.unpack_from("<I", data, i * 4)[0])

    return StageOverlay(
        raw=data,
        name=name,
        is_code=is_code,
        is_pointer_table=is_ptr_table,
        sha256=hashlib.sha256(data).hexdigest(),
        first_words=first_words,
    )


# ---------------------------------------------------------------------------
# PSX memory card block format
# ---------------------------------------------------------------------------

# PSX memory card: 8 MB (2048 × 4 KB blocks) or 4 MB.
# Each 4 KB block has a 128-byte header followed by data.
# The header contains:
#   0x000: 0x424153 ("SAB" — but actually "BAS" reversed in the file)
#   0x004: 8-byte filename (BASLUS-XXXXXXX)
#   0x00C: u32 size (bytes of data)
#   0x010: u32 creation time (PSX clock ticks)
#   0x014: u32 modification time
#   0x018: u32 block count
#   0x01C: u32 first block LBA
#   0x020: u32 free space
#   0x024: u32 checksum
#   0x028: u32 reserved
#
# NOTE: The exact field layout varies by source. The PSX memory card
# uses a 2 KB block size with a 64-byte header in some implementations
# and a 4 KB block size with a 128-byte header in others. The RE2
# Dual Shock save files (BASLUS-XXXXXXX) use the 2 KB block format.

PSX_MC_BLOCK_SIZE = 2048
PSX_MC_HEADER_SIZE = 64
PSX_MC_BLOCK_COUNT = 2048  # 8 MB card


@dataclass
class McBlock:
    """One block on a PSX memory card."""
    index: int
    is_free: bool = True
    filename: str = ""
    size: int = 0
    data: bytes = b""

    @property
    def lba(self) -> int:
        return self.index

    def to_dict(self) -> dict[str, Any]:
        if self.is_free:
            return {"index": self.index, "is_free": True}
        return {
            "index": self.index,
            "filename": self.filename,
            "size": self.size,
            "data_sha256": hashlib.sha256(self.data).hexdigest(),
        }


def parse_memory_card(card: bytes) -> list[McBlock]:
    """Parse a PSX memory card image.

    ``card`` is a raw 8 MB (or 4 MB) memory card image.  Returns a list
    of :class:`McBlock`, one per 2 KB block.
    """
    if len(card) < PSX_MC_BLOCK_SIZE:
        raise ValueError(f"memory card too small: {len(card)} bytes")

    count = len(card) // PSX_MC_BLOCK_SIZE
    blocks: list[McBlock] = []
    for i in range(count):
        off = i * PSX_MC_BLOCK_SIZE
        header = card[off:off + PSX_MC_HEADER_SIZE]
        if len(header) < PSX_MC_HEADER_SIZE:
            blocks.append(McBlock(i, is_free=True))
            continue

        # Magic: first 3 bytes should be "BAS" (0x42 0x41 0x53)
        magic = header[:3]
        if magic != b"BAS":
            # Free block or invalid
            # Check for 0x00 0x00 0x00 (free)
            if header[:4] == b"\x00\x00\x00\x00":
                blocks.append(McBlock(i, is_free=True))
            else:
                blocks.append(McBlock(i, is_free=False,
                                      data=card[off + PSX_MC_HEADER_SIZE:off + PSX_MC_BLOCK_SIZE]))
            continue

        # Parsed block
        filename = header[4:12].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        size = struct.unpack_from("<I", header, 12)[0] if len(header) >= 16 else 0
        data = card[off + PSX_MC_HEADER_SIZE:off + PSX_MC_BLOCK_SIZE]
        blocks.append(McBlock(i, is_free=False, filename=filename,
                              size=size, data=data))
    return blocks


def write_memory_card(blocks: list[McBlock]) -> bytes:
    """Serialize memory card blocks back to a raw image."""
    out = bytearray()
    for blk in blocks:
        if blk.is_free:
            out.extend(b"\x00" * PSX_MC_BLOCK_SIZE)
        else:
            # Build header
            header = bytearray(PSX_MC_HEADER_SIZE)
            header[:3] = b"BAS"
            fname = blk.filename.encode("ascii")[:8]
            header[4:4 + len(fname)] = fname
            header[4 + len(fname):12] = b"\x00" * (8 - len(fname))
            struct.pack_into("<I", header, 12, blk.size)
            out.extend(header)
            # Pad data to block size
            data = blk.data[:PSX_MC_BLOCK_SIZE - PSX_MC_HEADER_SIZE]
            out.extend(data)
            out.extend(b"\x00" * (PSX_MC_BLOCK_SIZE - PSX_MC_HEADER_SIZE - len(data)))
    return bytes(out)


# ---------------------------------------------------------------------------
# Room flag table (runtime BSS — not in the disc image)
# ---------------------------------------------------------------------------

ROOM_FLAG_BASE = 0x800D49E4
ROOM_FLAG_COUNT = 34
PLAYER_ID_SLOT = 0x800CFBB8


@dataclass
class RoomFlags:
    """Runtime room flag table (34 u32 slots).

    All zeros in the executable image (BSS).  Set at runtime by the
    room-transition code.  This structure is here so the save module
    can represent the flags once they are extracted from a live
    session or from a memory-card save.
    """
    base: int = ROOM_FLAG_BASE
    count: int = ROOM_FLAG_COUNT
    flags: list[int] = field(default_factory=lambda: [0] * ROOM_FLAG_COUNT)

    def __getitem__(self, i: int) -> int:
        return self.flags[i]

    def __setitem__(self, i: int, v: int) -> None:
        self.flags[i] = v

    def to_bytes(self) -> bytes:
        """Serialize as 34 little-endian u32."""
        return struct.pack(f"<{self.count}I", *self.flags)

    @classmethod
    def from_bytes(cls, data: bytes) -> "RoomFlags":
        """Deserialize from 136 bytes of little-endian u32."""
        if len(data) < ROOM_FLAG_COUNT * 4:
            raise ValueError(f"need {ROOM_FLAG_COUNT * 4} bytes, got {len(data)}")
        flags = list(struct.unpack_from(f"<{ROOM_FLAG_COUNT}I", data, 0))
        return cls(flags=flags)

    def summary(self) -> dict[str, Any]:
        nonzero = {i: hex(f) for i, f in enumerate(self.flags) if f != 0}
        return {
            "base": hex(self.base),
            "count": self.count,
            "nonzero_count": len(nonzero),
            "nonzero": nonzero,
            "all_zero": all(f == 0 for f in self.flags),
        }


# ---------------------------------------------------------------------------
# Save file representation
# ---------------------------------------------------------------------------

@dataclass
class SaveFile:
    """A single save file on the memory card."""
    filename: str
    size: int
    data: bytes
    block_index: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "size": self.size,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "block_index": self.block_index,
        }


# ---------------------------------------------------------------------------
# Top-level disc analysis
# ---------------------------------------------------------------------------

def analyze_disc(disc_path: str) -> dict[str, Any]:
    """Analyze a RE2 Dual Shock PSX Disc 2 image.

    Extracts the MEM_CARD.BIN, CONFIG.BIN, and STAGE*.BIN overlays
    and parses their structures.  Returns a JSON-serializable summary.
    """
    with open(disc_path, "rb") as f:
        disc = f.read()

    # Extract the main executable (SLUS_007.56)
    # It's the boot file — find it in the file table
    # First, we need the executable to get the file table.
    # The executable is at a known LBA on the disc.
    # From the probe: the executable is 987136 bytes.
    # Let's search for it by the PS-X EXE magic in the disc.

    # Actually, the executable is extracted separately. For this
    # function, we need both the disc and the executable.
    # The caller should provide the executable path separately.
    raise ValueError(
        "analyze_disc requires the executable; use "
        "analyze_disc_with_exe(disc_path, exe_path)"
    )


def analyze_disc_with_exe(disc_path: str, exe_path: str) -> dict[str, Any]:
    """Analyze a RE2 Dual Shock PSX Disc 2 image with its executable.

    Extracts and parses the MEM_CARD.BIN, CONFIG.BIN, and STAGE*.BIN
    overlays.  Returns a JSON-serializable summary.
    """
    with open(disc_path, "rb") as f:
        disc = f.read()
    with open(exe_path, "rb") as f:
        exe = f.read()

    ft = parse_file_table(exe)

    # Identify key files by index
    key_indices = {
        250: "CONFIG.BIN",
        253: "MEM_CARD.BIN",
        257: "STAGE1.BIN",
        258: "STAGE2.BIN",
        259: "STAGE3.BIN",
        260: "STAGE4.BIN",
        261: "STAGE5.BIN",
        262: "STAGE6.BIN",
        263: "STAGE7.BIN",
    }

    result: dict[str, Any] = {
        "disc": {"size": len(disc), "sha256": hashlib.sha256(disc).hexdigest()},
        "exe": {"size": len(exe), "sha256": hashlib.sha256(exe).hexdigest()},
        "file_table": {
            "count": len(ft),
            "base": hex(FILE_TABLE_BASE),
            "exe_offset": hex(FILE_TABLE_EXE_OFFSET),
        },
        "files": {},
    }

    for idx, name in key_indices.items():
        if idx >= len(ft):
            continue
        rec = ft[idx]
        try:
            data = extract_file(disc, rec)
            sha = hashlib.sha256(data).hexdigest()
            result["files"][name] = {
                "index": idx,
                "size": rec.size,
                "lba": rec.lba,
                "tag": hex(rec.tag),
                "sha256": sha,
            }

            if name == "MEM_CARD.BIN":
                mc = parse_mem_card_overlay(data)
                result["files"]["MEM_CARD.BIN"]["filenames"] = mc.filenames
                result["files"]["MEM_CARD.BIN"]["address_count"] = len(mc.addresses)
                result["files"]["MEM_CARD.BIN"]["addresses"] = [
                    hex(a) for a in mc.addresses[:16]
                ]

            elif name == "CONFIG.BIN":
                cfg = parse_config_overlay(data)
                result["files"]["CONFIG.BIN"]["section_name"] = cfg.section_name
                result["files"]["CONFIG.BIN"]["address_count"] = len(cfg.addresses)
                result["files"]["CONFIG.BIN"]["addresses"] = [
                    hex(a) for a in cfg.addresses[:16]
                ]

            elif name.startswith("STAGE"):
                st = parse_stage_overlay(data, name)
                result["files"][name]["is_code"] = st.is_code
                result["files"][name]["is_pointer_table"] = st.is_pointer_table
                result["files"][name]["first_words"] = [
                    hex(w) for w in st.first_words
                ]

        except Exception as e:
            result["files"][name]["error"] = str(e)

    # Room flag table (all zeros in the exe — BSS)
    ft_offset = ROOM_FLAG_BASE - 0x80010000 + PSX_EXE_HEADER_SIZE
    if ft_offset + ROOM_FLAG_COUNT * 4 <= len(exe):
        flags_raw = struct.unpack_from(
            f"<{ROOM_FLAG_COUNT}I", exe, ft_offset
        )
        result["room_flags"] = {
            "base": hex(ROOM_FLAG_BASE),
            "count": ROOM_FLAG_COUNT,
            "all_zero": all(f == 0 for f in flags_raw),
            "nonzero": {i: hex(f) for i, f in enumerate(flags_raw) if f != 0},
        }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            "usage: python -m gbox.re2psx_save DISC.BIN EXE [--mc CARD.BIN] "
            "[--out report.json]",
            file=sys.stderr,
        )
        return 2

    disc_path, exe_path = args[0], args[1]
    mc_path = None
    out_path = None
    if "--mc" in args:
        i = args.index("--mc")
        mc_path = args[i + 1]
        del args[i:i + 2]
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        del args[i:i + 2]

    report = analyze_disc_with_exe(disc_path, exe_path)

    if mc_path:
        with open(mc_path, "rb") as f:
            card = f.read()
        blocks = parse_memory_card(card)
        used = [b for b in blocks if not b.is_free]
        report["memory_card"] = {
            "size": len(card),
            "block_count": len(blocks),
            "used_blocks": len(used),
            "files": [b.to_dict() for b in used],
        }

    import json
    text = json.dumps(report, indent=1, default=str)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print(f"report -> {out_path}")

    # Summary
    mc = report.get("files", {}).get("MEM_CARD.BIN", {})
    cfg = report.get("files", {}).get("CONFIG.BIN", {})
    rf = report.get("room_flags", {})
    print(
        f"disc {report['disc']['size']}B "
        f"exe {report['exe']['size']}B "
        f"files {len(report.get('files', {}))} "
        f"mc_names {mc.get('filenames', [])} "
        f"cfg_section {cfg.get('section_name', '')} "
        f"room_flags_zero {rf.get('all_zero', '?')}"
    )
    for name, info in report.get("files", {}).items():
        if "error" in info:
            print(f"  {name}: ERROR {info['error']}")
        else:
            extra = ""
            if name == "MEM_CARD.BIN":
                extra = f" names={info.get('filenames')}"
            elif name == "CONFIG.BIN":
                extra = f" section={info.get('section_name')}"
            elif name.startswith("STAGE"):
                extra = f" code={info.get('is_code')} ptr={info.get('is_pointer_table')}"
            print(f"  {name}: {info['size']}B lba={info['lba']}{extra}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
