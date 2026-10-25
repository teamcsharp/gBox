"""RE6 PS3 (BLUS30855) native asset readers for Mercenaries stage work.

Reverse-engineered from the US/Asia retail dump (PS3_GAME/USRDIR/nativePS3),
verifiable against any RE6 PS3 .arc:

* ``arc`` v8 containers (``arc/PS3/*.arc``): big-endian ``\\0CRA`` header,
  80-byte entries (64-byte backslash path, u32 type hash, u32 compressed
  size, u32 size<<3|flags, u32 data offset). Entry payloads are zlib streams
  when compressed size < logical size, otherwise stored raw.
* ``sa`` scenario containers (``sa/PS3/*.arc``): same ARC v8 wrapper holding
  a single ``sc\\PS3<name>`` entry whose payload is a zlib stream that
  inflates to an SPK scenario pack.
* SPK scenario packs (``.sc``): ``\\0KPS`` magic, u32 tag (0xa14be3b6 on the
  retail dump), then a table of u32 big-endian per-section *uncompressed*
  sizes terminated by a repeat of the last value. Section payloads are
  stored compressed after the table; their internal chunk coding is not
  decoded here yet (next ticket step) but section boundaries and sizes are
  what the stage/bonus inventory needs to target.

This module is pure static analysis: no emulator, no live game memory.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ARC_MAGIC = b"\0CRA"
SPK_MAGIC = b"\0KPS"
SPK_RETAIL_TAG = 0xA14BE3B6
SPK_MAX_SECTIONS = 64

#: Known entry type hashes seen in RE6 PS3 arcs (subset used for inventory).
ARC_TYPE_NAMES = {
    0x241F5DEB: "tex",
    0x58A15856: "mod",
    0x2749C8A8: "mrl",
    0x3B5C7FD3: "gui",
    0x7808EA10: "rtex",
    0x02358E1A: "sc",  # scenario pack entry inside sa/PS3 arcs
}


@dataclass
class ArcEntry:
    name: str
    type_hash: int
    compressed_size: int
    logical_size: int
    flags: int
    offset: int

    @property
    def type_name(self) -> str:
        return ARC_TYPE_NAMES.get(self.type_hash, f"0x{self.type_hash:08x}")

    @property
    def compressed(self) -> bool:
        return self.compressed_size < self.logical_size


class ArcError(ValueError):
    pass


def read_arc(path: Path) -> list[ArcEntry]:
    """Parse an ARC v8 container and return its entry table."""
    data = Path(path).read_bytes()
    magic, version, count = struct.unpack_from(">4sHH", data, 0)
    if magic != ARC_MAGIC:
        raise ArcError(f"{path}: bad ARC magic {magic!r}")
    if version != 8:
        raise ArcError(f"{path}: unsupported ARC version {version}")
    entries: list[ArcEntry] = []
    for i in range(count):
        base = 8 + i * 80
        name = data[base : base + 64].split(b"\0")[0].decode("latin-1")
        type_hash, csize, sizeflags, offset = struct.unpack_from(">IIII", data, base + 64)
        entries.append(
            ArcEntry(
                name=name,
                type_hash=type_hash,
                compressed_size=csize,
                logical_size=sizeflags >> 3,
                flags=sizeflags & 7,
                offset=offset,
            )
        )
    return entries


def extract_arc_entry(path: Path, entry: ArcEntry) -> bytes:
    """Return the logical (decompressed) payload of one ARC entry."""
    data = Path(path).read_bytes()
    blob = data[entry.offset : entry.offset + entry.compressed_size]
    if not entry.compressed:
        if len(blob) != entry.logical_size:
            raise ArcError(f"{entry.name}: stored size {len(blob)} != logical {entry.logical_size}")
        return blob
    out = zlib.decompress(blob)
    if len(out) != entry.logical_size:
        raise ArcError(f"{entry.name}: inflated {len(out)} != logical {entry.logical_size}")
    return out


@dataclass
class SpkInfo:
    tag: int
    header_end: int  # offset of the first byte after the size table
    section_sizes: list[int] = field(default_factory=list)
    total_uncompressed: int = 0
    file_size: int = 0


class SpkError(ValueError):
    pass


def parse_spk(data: bytes) -> SpkInfo:
    """Parse the header of an SPK scenario pack (inflated .sc payload).

    Layout (big endian)::

        0x00  4s  magic b"\\0KPS"
        0x04  u32 tag (0xa14be3b6 on the retail US/Asia dump)
        0x08  u32 body size hint
        0x0c  u32 unknown (larger than body hint; role not yet identified)
        0x10  u32 per-section uncompressed sizes, last entry repeated as an
              end-of-table sentinel, then zero padding to the body

    ``section_sizes`` excludes the sentinel repeat.
    """
    if len(data) < 0x50 or data[:4] != SPK_MAGIC:
        raise SpkError("not an SPK scenario pack (bad magic)")
    tag = struct.unpack_from(">I", data, 4)[0]
    avail = max(0, (min(len(data), 0x10 + 4 * SPK_MAX_SECTIONS) - 0x10) // 4)
    raw = [struct.unpack_from(">I", data, 0x10 + 4 * i)[0] for i in range(avail)]
    sizes: list[int] = []
    for i, size in enumerate(raw):
        if size == 0:
            break
        if sizes and size == sizes[-1] and (i + 1 >= len(raw) or raw[i + 1] == 0):
            break  # sentinel repeat
        sizes.append(size)
    else:
        raise SpkError("size table did not terminate within 64 entries")
    if not sizes:
        raise SpkError("empty SPK size table")
    end = 0x10 + 4 * (len(sizes) + 1)
    while end < len(data) and data[end] == 0:
        end += 1
    return SpkInfo(
        tag=tag,
        header_end=end,
        section_sizes=sizes,
        total_uncompressed=sum(sizes),
        file_size=len(data),
    )


def read_scenario(arc_path: Path) -> tuple[str, bytes]:
    """Inflate the single sc entry of an sa/PS3 scenario arc.

    Returns ``(entry_name, spk_bytes)``.
    """
    entries = read_arc(arc_path)
    sc = [e for e in entries if e.type_name == "sc"]
    if len(sc) != 1:
        raise ArcError(f"{arc_path}: expected exactly one sc entry, found {len(sc)}")
    return sc[0].name, extract_arc_entry(arc_path, sc[0])


def inventory(arc_path: Path) -> dict:
    """JSON-friendly inventory of one ARC plus, for sa arcs, its SPK table."""
    entries = read_arc(arc_path)
    inv = {
        "arc": str(arc_path),
        "version": 8,
        "entries": len(entries),
        "items": [
            {
                "name": e.name,
                "type": e.type_name,
                "compressed": e.compressed,
                "compressed_size": e.compressed_size,
                "logical_size": e.logical_size,
            }
            for e in entries
        ],
    }
    sc = [e for e in entries if e.type_name == "sc"]
    if len(sc) == 1:
        name, blob = read_scenario(arc_path)
        info = parse_spk(blob)
        inv["scenario"] = {
            "entry": name,
            "spk_tag": f"0x{info.tag:08x}",
            "spk_size": info.file_size,
            "header_end": info.header_end,
            "section_sizes": [f"0x{s:x}" for s in info.section_sizes],
            "total_uncompressed": f"0x{info.total_uncompressed:x}",
        }
    return inv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RE6 PS3 arc/sa/SPK inventory")
    ap.add_argument("paths", nargs="+", type=Path, help=".arc files (arc/ or sa/ containers)")
    ap.add_argument("--json", action="store_true", help="emit one JSON object per arc")
    args = ap.parse_args(argv)
    for p in args.paths:
        if args.json:
            print(json.dumps(inventory(p), indent=2))
        else:
            inv = inventory(p)
            print(f"{p}: {inv['entries']} entries")
            for it in inv["items"][:20]:
                comp = "zlib" if it["compressed"] else "raw"
                print(f"  {it['name']:64s} {it['type']:>6} {comp} {it['logical_size']:>9}")
            if "scenario" in inv:
                s = inv["scenario"]
                print(
                    f"  scenario {s['entry']}: SPK tag {s['spk_tag']} size {s['spk_size']} "
                    f"sections {len(s['section_sizes'])} uncompressed {s['total_uncompressed']}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
