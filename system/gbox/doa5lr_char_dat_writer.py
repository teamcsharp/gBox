"""Native writer for DOA5LR (PS3) ``char_dat`` payloads and CHCM containers.

First milestone of the writer stage (request #2450):

  * :func:`encode_noop` re-serializes the ``char_dat`` header (0x00..0xB4:
    outer+inner headers, 7 section pointers, 16-slot pointer table) from the
    verified :func:`gbox.doa5lr_char_dat.parse_char_dat` model and copies the
    data region (0x10..EOF) verbatim.  Round-trip acceptance: the output is
    byte-identical to the input (entry 0018: 58,484 B, sha256
    d0b72267...72e6; entry 0940: 7,357,824 B).

  * :func:`replace_entry_in_container` rewrites one CHCM entry row region
    (offset/size from the verified table) in ``chara_common.lnk`` leaving the
    rest of the 1.8 GB archive untouched.  Same-size (no-op) replacement must
    leave the container hash unchanged (02af8aef...1c18); size-invariant
    section replacement is the next milestone.

Byte order: big-endian throughout (PS3).  Offsets are absolute from the
payload/container start.
"""
from __future__ import annotations

import hashlib
import os
import struct

from gbox.doa5lr_char_dat import CharDatError, MAGIC, RESERVED, parse_char_dat
from gbox import doa5lr_chcm_extract as chcm

__all__ = [
    "WriterError",
    "encode_noop",
    "replace_entry_in_container",
    "container_sha256",
]

HEADER_END = 0xB4
DATA_START = 0x10


class WriterError(ValueError):
    """Raised when a write operation would corrupt the archive."""


def _u32(off: int, value: int) -> bytes:
    return struct.pack(">I", value)


def encode_noop(payload: bytes) -> bytes:
    """Re-serialize a ``char_dat`` payload header and return the full bytes.

    Every header field in 0x00..0xB4 is written from the parsed model; the
    data region 0x10..EOF is copied verbatim.  The result is re-parsed and
    must reproduce the same structural model, which proves the header model
    is complete.  For an owned-source entry the output is byte-identical to
    the input.
    """
    info = parse_char_dat(payload)
    out = bytearray(payload)

    # outer header (0x00..0x40)
    out[0x00:0x08] = MAGIC
    out[0x08:0x0C] = _u32(0x08, RESERVED)
    outer = info["outer_header"]
    out[0x14:0x18] = _u32(0x14, outer["flags_14"])
    out[0x18:0x1C] = _u32(0x18, outer["flags_18"])
    out[0x20:0x24] = _u32(0x20, outer["hdr_size"])
    out[0x30:0x34] = _u32(0x30, outer["data_ptr"])

    # inner subheader (0x40..0x74)
    out[0x40:0x48] = MAGIC
    out[0x48:0x4C] = _u32(0x48, RESERVED)
    inner = info["inner_header"]
    out[0x54:0x58] = _u32(0x54, inner["n_sections"])
    out[0x58:0x5C] = _u32(0x58, inner["n_entries"])
    out[0x60:0x64] = _u32(0x60, 0x30)
    out[0x70:0x74] = _u32(0x70, inner["data_ptr"])

    # section pointer array (0x78..0x94) and pointer table (0x94..0xB4)
    for i, p in enumerate(info["section_ptrs"]):
        out[0x78 + 4 * i:0x7C + 4 * i] = _u32(0x78 + 4 * i, int(p, 16))
    for i, p in enumerate(info["ptable"]):
        out[0x94 + 4 * i:0x98 + 4 * i] = _u32(0x94 + 4 * i, int(p, 16))

    # the re-serialized bytes must re-parse to the identical model
    reinfo = parse_char_dat(bytes(out))
    if reinfo["size"] != info["size"]:
        raise WriterError("re-parsed size mismatch")
    for key in ("section_ptrs", "ptable", "geometry_table", "texture_table"):
        if reinfo[key] != info[key]:
            raise WriterError(f"re-parsed {key} differs")
    if len(reinfo["sections"]) != len(info["sections"]) or any(
        a["start"] != b["start"] or a["end"] != b["end"]
        for a, b in zip(reinfo["sections"], info["sections"])
    ):
        raise WriterError("re-parsed section bounds differ")
    return bytes(out)


def container_sha256(path: str) -> str:
    """Streaming sha256 of a (large) container file."""
    return chcm.sha256_file(path)


def replace_entry_in_container(
    container_path: str,
    index: int,
    new_payload: bytes,
    output_path: str | None = None,
    expected_sha256: str | None = None,
) -> dict:
    """Rewrite CHCM entry ``index`` in-place (or into ``output_path``).

    The CHCM row (size/offset) comes from the verified table; only the bytes
    of the target entry region are written.  Currently requires
    ``len(new_payload) == entry size`` (same-size / no-op replacement);
    size-invariant reallocation is the next milestone.

    Returns a receipt dict with entry and container sha256 values.  If
    ``expected_sha256`` is given, the rewritten container must match it
    (the acceptance check for a byte-identical no-op).
    """
    entries = chcm.parse_entries(container_path)
    if not 0 <= index < len(entries):
        raise IndexError("entry %d out of range (%d)" % (index, len(entries)))
    size, dup, zero, offset = entries[index]
    if len(new_payload) != size:
        raise WriterError(
            "size mismatch: entry %d is %d bytes, new payload is %d bytes "
            "(size-invariant replacement not implemented yet)" % (index, size, len(new_payload))
        )

    target = output_path or container_path
    if output_path:
        if not os.path.exists(output_path):
            raise FileNotFoundError(output_path)
        if os.path.getsize(output_path) != os.path.getsize(container_path):
            raise WriterError("output size differs from source container")

    region_before = None
    digest = hashlib.sha256()
    chunk = 1 << 22
    with open(target, "rb+") as handle:
        # hash original entry region before the rewrite
        handle.seek(offset)
        region_before = handle.read(size)
        handle.seek(offset)
        handle.write(new_payload)
        # stream the whole rewritten container
        handle.seek(0)
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    sha = digest.hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise WriterError(
            "container sha256 %s != expected %s" % (sha, expected_sha256)
        )
    return {
        "index": index,
        "offset": offset,
        "size": size,
        "row": {"size": size, "dup": dup, "zero": zero},
        "entry_sha256_before": hashlib.sha256(region_before).hexdigest(),
        "entry_sha256_after": hashlib.sha256(new_payload).hexdigest(),
        "container_sha256": sha,
        "container_path": target,
    }
