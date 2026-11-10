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
    "swap_section",
    "scan_section_donors",
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


def _section_sizes(info: dict) -> list:
    return [sec["end"] - sec["start"] for sec in info["sections"]]


def swap_section(target_payload: bytes, donor_payload: bytes, section_index: int) -> bytes:
    """Return ``target_payload`` with section ``section_index`` replaced by the
    same-index donor section bytes.  Section sizes must match exactly so the
    payload length, pointer tables and every other section stay unchanged.
    """
    t = parse_char_dat(target_payload)
    d = parse_char_dat(donor_payload)
    if not 0 <= section_index < len(t["sections"]):
        raise WriterError("target has no section %d" % section_index)
    if section_index >= len(d["sections"]):
        raise WriterError("donor has no section %d" % section_index)
    ts, te = t["sections"][section_index]["start"], t["sections"][section_index]["end"]
    ds, de = d["sections"][section_index]["start"], d["sections"][section_index]["end"]
    if te - ts != de - ds:
        raise WriterError(
            "section %d size mismatch: target %d, donor %d" % (section_index, te - ts, de - ds)
        )
    out = bytearray(target_payload)
    out[ts:te] = donor_payload[ds:de]
    res = bytes(out)
    r = parse_char_dat(res)
    if len(res) != len(target_payload) or _section_sizes(r) != _section_sizes(t):
        raise WriterError("swapped payload no longer matches target layout")
    return res


def swap_sections(target_payload: bytes, donor_payload: bytes, section_indices) -> bytes:
    """Apply ``swap_section`` for each index in order (all sizes must match)."""
    out = target_payload
    for k in section_indices:
        out = swap_section(out, donor_payload, k)
    return out


def scan_section_donors(container_path: str, target_index: int) -> list:
    """List CHCM entries (other than the target) that parse as ``char_dat`` and
    have >=1 section with the same size as the target's same-index section.
    Returns dicts: index, size, matching_sections (list of section indices).
    """
    _info, target = chcm.extract_entry(target_index, container_path, container_path[:-4] + ".bin")
    tsizes = _section_sizes(parse_char_dat(target))
    entries = chcm.parse_entries(container_path)
    found = []
    with open(container_path, "rb") as fh:
        for i, (size, _dup, _zero, offset) in enumerate(entries):
            if i == target_index or size < 0xB4:
                continue
            fh.seek(offset)
            data = fh.read(size)
            try:
                sizes = _section_sizes(parse_char_dat(data))
            except Exception:
                continue
            m = [k for k, v in enumerate(sizes) if k < len(tsizes) and v == tsizes[k]]
            if m:
                found.append({"index": i, "size": size, "matching_sections": m})
    return found


def replace_entry_span_in_container(
    container_path: str,
    index: int,
    new_payload: bytes,
    output_path: str,
) -> dict:
    """Span-aware variant of ``replace_entry_in_container`` (request #2450).

    The CHCM 32B-table ``size`` understates many char_dat bodies, so the real slot is
    ``entry_span`` (up to the next entry offset).  ``new_payload`` may be shorter than the
    slot (<=); the remaining slot bytes are preserved from the source.  Only the copy at
    ``output_path`` (same size as the source, pre-made by the caller) is written, never the
    source.  Returns entry/container hashes.
    """
    from gbox.doa5lr_char_dat_variants import entry_span

    if os.path.abspath(output_path) == os.path.abspath(container_path):
        raise WriterError("span replacement refuses to write the source container")
    entries = chcm.parse_entries(container_path)
    if not 0 <= index < len(entries):
        raise IndexError("entry %d out of range (%d)" % (index, len(entries)))
    offset, span = entry_span(entries, index)
    if len(new_payload) > span:
        raise WriterError("payload %d B exceeds slot span %d B of entry %d" % (len(new_payload), span, index))
    if not os.path.exists(output_path):
        raise FileNotFoundError(output_path)
    if os.path.getsize(output_path) != os.path.getsize(container_path):
        raise WriterError("output size differs from source container")
    with open(output_path, "rb+") as handle:
        handle.seek(offset)
        before = handle.read(span)
        handle.seek(offset)
        handle.write(new_payload)
        handle.seek(offset)
        after = handle.read(span)
    if after[: len(new_payload)] != new_payload or after[len(new_payload):] != before[len(new_payload):]:
        raise WriterError("slot readback mismatch for entry %d" % index)
    return {
        "index": index,
        "offset": offset,
        "span": span,
        "slot_sha256_before": hashlib.sha256(before).hexdigest(),
        "slot_sha256_after": hashlib.sha256(after).hexdigest(),
        "container_sha256": container_sha256(output_path),
        "container_path": output_path,
    }
