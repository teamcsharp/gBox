"""DCX (FromSoftware DFLT/zlib) container decoder for Armored Core V (Xbox 360).

Big endian.  Layout verified on the owned ISO (sha256 d028051a...6189),
BDT payloads recorded by acv_inventory.parse_bhd5_buckets:

  0x00 "DCX\\0"
  0x04 u32 0x00010000
  0x08 u32 dcsOffset   (0x18)
  0x0C u32 dcpOffset   (0x24)
  0x10 u32 dcpSize     (0x24)
  0x14 u32 0x2C
  0x18 "DCS\\0" u32 uncompressedSize u32 compressedSize
  0x24 "DCP\\0" "DFLT" u32 0x20 u32 level ... (0x20 bytes)
  0x44 "DCA\\0" u32 dcaSize (8)
  0x4C zlib stream (compressedSize bytes; payload may be padded)

Read-only; bounded: every offset/size is checked against the buffer and the
inflated length must equal the DCS uncompressedSize.
"""
from __future__ import annotations

import struct
import zlib

DCX_MAGIC = b"DCX\0"


def parse_dcx(raw: bytes) -> dict:
    if len(raw) < 0x4C or raw[:4] != DCX_MAGIC:
        raise ValueError("not a DCX container")
    unk, dcs_off, dcp_off, dcp_size, dca_hint = struct.unpack_from(">5I", raw, 4)
    if raw[dcs_off:dcs_off + 4] != b"DCS\0":
        raise ValueError("DCS section missing at 0x%x" % dcs_off)
    usize, csize = struct.unpack_from(">II", raw, dcs_off + 4)
    if raw[dcp_off:dcp_off + 4] != b"DCP\0":
        raise ValueError("DCP section missing at 0x%x" % dcp_off)
    method = raw[dcp_off + 4:dcp_off + 8]
    dcp_len, level = struct.unpack_from(">II", raw, dcp_off + 8)
    dca_off = dcp_off + dcp_len
    if raw[dca_off:dca_off + 4] != b"DCA\0":
        raise ValueError("DCA section missing at 0x%x" % dca_off)
    (dca_size,) = struct.unpack_from(">I", raw, dca_off + 4)
    data_off = dca_off + dca_size
    if data_off + csize > len(raw):
        raise ValueError("compressed data 0x%x+%d exceeds container %d"
                         % (data_off, csize, len(raw)))
    return {"method": method.decode("ascii", "replace"), "level": level,
            "dcs_off": dcs_off, "dcp_off": dcp_off, "dca_off": dca_off,
            "data_off": data_off, "uncompressed_size": usize,
            "compressed_size": csize}


def decompress_dcx(raw: bytes) -> bytes:
    info = parse_dcx(raw)
    if info["method"] != "DFLT":
        raise ValueError("unsupported DCX method %r" % info["method"])
    out = zlib.decompressobj().decompress(
        raw[info["data_off"]:info["data_off"] + info["compressed_size"]])
    if len(out) != info["uncompressed_size"]:
        raise ValueError("inflated %d != DCS size %d"
                         % (len(out), info["uncompressed_size"]))
    return out
