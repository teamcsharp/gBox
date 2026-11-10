"""Strike Force Bowling (GameCube, G5BE4Z) ``.FUC`` container reader/writer.

Layout (all little-endian, verified on all 30 GCNFUCs members)::

    0x00  4   magic ".FUC"
    0x04  4   version bytes "01" 04 07
    0x08  u32 entry count
    0x0C  u32 total file size
    0x10  entries[count]:
            u32 data offset (from file start)
            u32 UNCOMPRESSED size (payload is a zlib stream, 78 DA)
            NUL-terminated original PS2 build path ("Q:\\PS2BOWL\\ART\\...")
            padded with NULs to a 4-byte boundary
    ...   zlib payloads at the recorded offsets, contiguous and in directory
          order: compressed size = next offset - offset (last: total - offset).
          Decompressed payloads are RenderWare .DFF / .ANM and .DDS textures.

The path strings reveal the payload formats: .DFF (RenderWare clump), .ANM
(RenderWare anim), .DDS textures.  ``rebuild`` repacks with replaced payloads
and recomputes offsets, sizes and total size; an unchanged parse/rebuild is
byte-identical for the payload table and payload bytes.
"""

from __future__ import annotations

import struct
import zlib

MAGIC = b".FUC"
VERSION = b"01\x04\x07"
RW_CLUMP_ID = 0x10  # RenderWare chunk type for a Clump (DFF)


class FucError(ValueError):
    pass


def parse(data):
    """Return ``{"count","total","dir_end","entries"}``; entries carry path,
    offset, usize (uncompressed) and csize (zlib stream length)."""
    if len(data) < 16 or data[:4] != MAGIC or data[4:8] != VERSION:
        raise FucError("not a .FUC01 04.07 container")
    count, total = struct.unpack_from("<II", data, 8)
    if total != len(data):
        raise FucError("total size %d != file size %d" % (total, len(data)))
    pos, entries = 16, []
    for _ in range(count):
        if pos + 9 > len(data):
            raise FucError("directory overruns file")
        off, usize = struct.unpack_from("<II", data, pos)
        end = data.index(b"\x00", pos + 8)
        path = data[pos + 8:end].decode("latin-1")
        pos = (end + 1 + 3) & ~3
        entries.append({"path": path, "offset": off, "usize": usize})
    offs = [e["offset"] for e in entries] + [total]
    for i, e in enumerate(entries):
        e["csize"] = offs[i + 1] - e["offset"]
        if e["csize"] <= 0 or offs[i + 1] > total:
            raise FucError("bad offsets at %s" % e["path"])
    return {"count": count, "total": total, "dir_end": pos, "entries": entries}


def raw(data, entry):
    return data[entry["offset"]:entry["offset"] + entry["csize"]]


def payload(data, entry):
    """Decompressed payload, size-checked against the directory."""
    out = zlib.decompress(raw(data, entry))
    if len(out) != entry["usize"]:
        raise FucError("%s: inflated %d != usize %d" % (entry["path"], len(out), entry["usize"]))
    return out


def rw_header(blob):
    """(chunk_type, size, library_stamp) of a RenderWare chunk header, or None."""
    if len(blob) < 12:
        return None
    return struct.unpack_from("<III", blob, 0)


def rebuild(data, replacements=None, level=9):
    """Repack; ``replacements`` maps entry path -> new *decompressed* bytes.

    Untouched entries keep their original compressed bytes (byte-exact).
    Replaced entries are zlib-compressed; offsets, usizes and total are
    recomputed.  No-op rebuild is byte-identical to the input.
    """
    info = parse(data)
    rep = replacements or {}
    unknown = set(rep) - {e["path"] for e in info["entries"]}
    if unknown:
        raise FucError("unknown entries: %s" % sorted(unknown))
    blobs, usizes = [], []
    for e in info["entries"]:
        if e["path"] in rep:
            blobs.append(zlib.compress(rep[e["path"]], level))
            usizes.append(len(rep[e["path"]]))
        else:
            blobs.append(raw(data, e))
            usizes.append(e["usize"])
    out = bytearray(data[:info["dir_end"]])
    pos, p = info["dir_end"], 16
    for e, b, u in zip(info["entries"], blobs, usizes):
        struct.pack_into("<II", out, p, pos, u)
        p = (p + 8 + len(e["path"]) + 1 + 3) & ~3
        pos += len(b)
    struct.pack_into("<I", out, 12, pos)
    return bytes(out) + b"".join(blobs)
