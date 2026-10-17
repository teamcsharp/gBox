"""Inventory the owned Perfect Dark N64 build.

Perfect Dark stores its executable and every game asset in one 32 MiB ROM.
The ROM's "files" area is a big-endian u32 offset table (0-terminated)
followed by a name table (u32 offsets relative to the name table start,
pointing at NUL-terminated names).  Each file occupies [offsets[i],
offsets[i+1]) and may be a raw blob or a Rare zip container: 2-byte magic
0x1173 followed by a raw-deflate stream (zlib wbits=-15) from byte 5, with
possible trailing padding.

File name prefixes select the asset class (per the n64decomp/perfect_dark
extractor, which documents this layout):

  A...  audio          C...  character models (chrs)
  G...  guns           L...  language strings
  P...  props          U...  setups (stages, MP setups)
  ...seg / ...padsZ / ...tilesZ   bg data (rooms, paths, tiled images)

The exact build is identified by ROM md5 against the six known versions
(n64decomp/perfect_dark README); the per-version files-table offset comes
from the same project's tools/extract vals table.  Table offsets are only
accepted after sanity checks so a wrong guess cannot fabricate an
inventory.

Usage: python -m gbox.pd_inventory SRC --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from gbox import n64_rom

# romid -> (md5, files-table offset in decompressed data segment, data
# segment ROM offset) from n64decomp/perfect_dark (README + tools/extract).
# Only these exact builds are recognised.
KNOWN_BUILDS = {
    "ntsc-beta":  ("aa93f4df16fceada399a749f5ad2f273", 0x29160, 0x30850),
    "ntsc-1.0":   ("7f4171b0c8d17815be37913f535e4e93", 0x28080, 0x39850),
    "ntsc-final": ("e03b088b6ac9e0080440efed07c1e40f", 0x28080, 0x39850),
    "pal-beta":   ("ad2de210a3455ba5ec541f0c78d91444", 0x29B90, 0x39850),
    "pal-final":  ("d9b5cd305d228424891ce38e71bc9213", 0x28910, 0x39850),
    "jpn-final":  ("538d2b75945eae069b29c46193e74790", 0x28800, 0x39850),
}

ZIP_MAGIC = b"\x11\x73"
MAX_FILES = 4096

# Segment starts for pal-final (ROM addresses, from tools/extract vals).
# Other builds keep these in the manifest only when the romid matches.
PAL_FINAL_SEGMENTS = {
    "files_table": 0x28910,
    "data": 0x39850,
    "game": 0x4FC40,
    "animations": 0x18CDC0,
    "mpconfigs": 0x7BC240,
    "textureconfig": 0x7D6A70,
    "textures": 0x1D5CA20,
    "copyright": 0x1FF5500,
}


@dataclass
class RomFile:
    index: int
    name: str
    kind: str
    offset: int
    end: int
    zipped: bool
    rom_sha256: str
    stored_sha256: str
    dec_size: int | None = None
    dec_sha256: str | None = None

    @property
    def size(self) -> int:
        return self.end - self.offset


def identify(rom: bytes) -> tuple[str, int, int]:
    """Return (romid, files_table_offset, data_segment_offset)."""
    md5 = hashlib.md5(rom).hexdigest()
    for romid, (known_md5, table, data_off) in KNOWN_BUILDS.items():
        if md5 == known_md5:
            return romid, table, data_off
    raise ValueError(
        "not a recognised Perfect Dark build (md5 %s); supported: %s"
        % (md5, ", ".join(KNOWN_BUILDS))
    )


def read_u32_table(blob: bytes, start: int, max_entries: int = MAX_FILES) -> list[int]:
    vals = []
    pos = start
    while pos + 4 <= len(blob) and len(vals) < max_entries:
        v = struct.unpack_from(">I", blob, pos)[0]
        if v == 0 and vals:
            return vals
        vals.append(v)
        pos += 4
    raise ValueError(f"u32 table at 0x{start:x} is unterminated or overlong")


def read_names(rom: bytes, table_addr: int, count: int) -> list[str]:
    rels = read_u32_table(rom, table_addr)
    if len(rels) != count:
        raise ValueError(
            f"name table at 0x{table_addr:x} has {len(rels)} entries, expected {count}"
        )
    names = []
    for rel in rels:
        addr = table_addr + rel
        if addr >= len(rom):
            raise ValueError(f"name pointer 0x{addr:x} outside ROM")
        end = rom.index(0, addr)
        names.append(rom[addr:end].decode("ascii"))
    return names


def unzip_pd(blob: bytes) -> tuple[bytes, int]:
    """Decompress a Rare 0x1173 zip container; return (data, unused_padding)."""
    if blob[:2] != ZIP_MAGIC:
        raise ValueError("not a Rare zip container")
    obj = zlib.decompressobj(wbits=-15)
    data = obj.decompress(blob[5:])
    return data, len(obj.unused_data)


def kind_of(name: str) -> str:
    if name.startswith("C"):
        return "chr"
    if name.startswith("G"):
        return "gun"
    if name.startswith("A"):
        return "audio"
    if name.startswith("L"):
        return "lang"
    if name.startswith("P"):
        return "prop"
    if name.startswith("U"):
        return "setup"
    if name.startswith("bgdata/"):
        if name.endswith(".seg"):
            return "bgroom"
        if name.endswith("padsZ"):
            return "bgpads"
        if name.endswith("tilesZ"):
            return "bgtiles"
    return "other"


def inventory(rom: bytes) -> dict:
    romid, files_off, data_off = identify(rom)
    return inventory_with(rom, romid, files_off, data_off)


def inventory_with(rom: bytes, romid: str, files_off: int, data_off: int) -> dict:

    # The file offset table lives inside the decompressed "data" segment:
    # rom[data_off:] is one 0x1173 zip container; offsets are relative to
    # the decompressed stream.  The table is [0, f0, f1, ..., fN-1]: the
    # leading 0 is skipped by the game, files f0..fN-2 span to the next
    # entry, and fN-1 is the ROM address of the name table (relative u32
    # pointers to NUL-terminated names).
    data, _unused = unzip_pd(rom[data_off:])
    vals = read_u32_table(data, files_off)
    if len(vals) < 3 or vals[0] != 0:
        raise ValueError(f"unexpected file table at data+0x{files_off:x}")
    names_addr = vals[-1]
    names = read_names(rom, names_addr, len(vals) - 1)
    if len(names) != len(vals) - 1:
        raise ValueError(
            f"name table at 0x{names_addr:x} has {len(names)} names, "
            f"expected {len(vals) - 1}"
        )

    files: list[RomFile] = []
    for i in range(len(vals) - 2):
        start, end = vals[i + 1], vals[i + 2]
        if not (0 <= start <= end <= len(rom)):
            raise ValueError(f"file {i} has bad extent 0x{start:x}-0x{end:x}")
        blob = rom[start:end]
        zipped = blob[:2] == ZIP_MAGIC
        dec_size = dec_sha = None
        unused = 0
        if zipped:
            data, unused = unzip_pd(blob)
            dec_size = len(data)
            dec_sha = hashlib.sha256(data).hexdigest()
            # `unused` is trailing padding after the deflate stream; the
            # stream itself is validated by zlib.
        files.append(
            RomFile(
                index=i,
                name=names[i + 1],
                kind=kind_of(names[i + 1]),
                offset=start,
                end=end,
                zipped=zipped,
                rom_sha256=hashlib.sha256(blob).hexdigest(),
                stored_sha256=hashlib.sha256(blob if not zipped else blob[: len(blob) - unused]).hexdigest(),
                dec_size=dec_size,
                dec_sha256=dec_sha,
            )
        )

    hdr = rom[:0x40]
    manifest = {
        "game": "Perfect Dark",
        "platform": "n64",
        "romid": romid,
        "region": "PAL" if romid.startswith("pal") else "NTSC" if romid.startswith("ntsc") else "JPN",
        "image_name": hdr[0x20:0x34].split(b"\0")[0].decode("ascii"),
        "cartridge_id": hdr[0x3B],
        "country_code": hdr[0x3C:0x3E].decode("ascii", "replace"),
        "version_byte": hdr[0x3E],
        "clock_rate": struct.unpack_from(">I", hdr, 0)[0],
        "entry_pc": hex(struct.unpack_from(">I", hdr, 4)[0]),
        "boot_checksum": hex(struct.unpack_from(">I", hdr, 0x10)[0]),
        "rom_size": len(rom),
        "rom_md5": hashlib.md5(rom).hexdigest(),
        "rom_sha256": hashlib.sha256(rom).hexdigest(),
        "rom_sha1": hashlib.sha1(rom).hexdigest(),
        "files_table_data_off": files_off,
        "data_segment_rom_off": data_off,
        "data_segment_dec_size": len(data),
        "names_table_rom_off": names_addr,
        "segments": PAL_FINAL_SEGMENTS if romid == "pal-final" else {"files_table": files_off},
        "file_count": len(files),
        "kinds": {},
        "files": [f.__dict__ for f in files],
        "characters": sorted({f.name[1:] for f in files if f.kind == "chr"}),
    }
    for f in files:
        manifest["kinds"][f.kind] = manifest["kinds"].get(f.kind, 0) + 1
    return manifest


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out: Path | None = None
    if "--out" in argv:
        i = argv.index("--out")
        out = Path(argv[i + 1])
        del argv[i:i + 2]
    if len(argv) != 1:
        print("usage: python -m gbox.pd_inventory SRC [--out manifest.json]", file=sys.stderr)
        return 2
    src = Path(argv[0])
    rom = n64_rom.read(src)
    data = inventory(rom)
    if out:
        out.write_text(json.dumps(data, indent=2))
        print(f"wrote {out}")
    kinds = data["kinds"]
    print(
        f"{data['romid']} {data['rom_md5']} files={data['file_count']} "
        f"kinds={kinds} chars={len(data['characters'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
