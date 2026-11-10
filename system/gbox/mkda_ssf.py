"""Mortal Kombat: Deadly Alliance (GameCube) SSF container parser.

Grammar (big-endian), verified against artgc/scorpion.ssf of the owned disc
(sha256 fbb7271963b4e37625a358e97bc694bf5ed2be8f8a42974f4d1b300685dbe058):

  0x00  b"SEC "
  0x04  u32 version (4)
  0x08  u32 0
  0x0c  u32 flags/id (top level 0x7e; children carry per-section ids, e.g. 0x807e)
  0x10  u32 count     number of records
  0x14  u32 total     byte size of this section (== len for the top level)
  0x18  count * (u32 type, u32 offset, u32 size)   12-byte records
        followed by one zero-padded terminator record
Offsets are relative to the section start and 0x800-aligned in the top level.
Observed types: 6 = nested SEC section, 8 = nested SEC section (geometry/model
class), 7 = raw blob (headerless table), others reported as-is.
"""
import struct

MAGIC = b"SEC "
HDR = 0x18


class SSFError(ValueError):
    pass


def parse_section(buf: bytes, base: int = 0, limit: int | None = None) -> dict:
    """Parse one SEC section at buf[base:]; returns a dict with records (not recursed)."""
    limit = len(buf) if limit is None else limit
    if buf[base:base + 4] != MAGIC:
        raise SSFError(f"no SEC magic at {base:#x}")
    ver, zero, ident, count, total = struct.unpack_from(">5I", buf, base + 4)
    if ver != 4:
        raise SSFError(f"unexpected version {ver} at {base:#x}")
    if count > 0x10000 or base + HDR + 12 * count > limit:
        raise SSFError(f"record table out of range at {base:#x}")
    recs = []
    for i in range(count):
        t, o, s = struct.unpack_from(">3I", buf, base + HDR + 12 * i)
        if o + s > total and total:
            raise SSFError(f"record {i} [{o:#x}+{s:#x}] beyond section total {total:#x} at {base:#x}")
        recs.append({"index": i, "type": t, "offset": o, "size": s, "abs": base + o})
    return {"base": base, "ident": ident, "count": count, "total": total, "records": recs}


def walk(buf: bytes, base: int = 0, limit: int | None = None, depth: int = 0, max_depth: int = 8):
    """Yield (depth, section_dict, record) for every record, recursing into SEC children."""
    sec = parse_section(buf, base, limit)
    for r in sec["records"]:
        yield depth, sec, r
        if r["size"] >= 0x18 and buf[r["abs"]:r["abs"] + 4] == MAGIC and depth < max_depth:
            yield from walk(buf, r["abs"], r["abs"] + r["size"], depth + 1, max_depth)


def census(buf: bytes) -> dict:
    """{'sections': n, 'by_type': {type: count}, 'blobs': n_raw_records}."""
    by_type: dict[int, int] = {}
    sections = 1
    for _d, _s, r in walk(buf):
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        if buf[r["abs"]:r["abs"] + 4] == MAGIC:
            sections += 1
    return {"sections": sections, "by_type": by_type}
