"""Bounded, read-only inspection of RetroArch/Flycast save states.

Container decoding follows RetroArch's rzip_stream.c and task_save.c. Maple
inspection follows Flycast mcfg_SerializeDevices and YUV_serialize for V47..V59.
Automatic discovery requires a VMU in port A's first or second expansion slot
and a unique, complete PowerVR register signature. Explicit Maple offsets can
inspect other supported topologies. This is a diagnostic subset, not a complete
serializer, state repair tool, or proof that a recorded frame is recoverable.

Based on the Nous/Hermes inspector from inbox #1216, independently corrected
for bounds, actual Maple slot order, microphone payload and scan ambiguity.
Never writes to its input or initializes an emulator.
"""
from __future__ import annotations

import struct
import zlib

FLYCAST_V59 = 854
FLYCAST_V47 = 842
MAX_STATE_BYTES = 256 * 1024 * 1024
MAX_RZIP_CHUNK = 64 * 1024 * 1024
MDT = {0: "SegaController", 1: "SegaVMU", 2: "Microphone", 3: "PurupuruPack",
       4: "AsciiStick", 5: "Keyboard", 6: "Mouse", 7: "LightGun", 8: "TwinStick",
       9: "NaomiJamma", 10: None}
MDT_NONE = 10
VMU_PAYLOAD = 128 * 1024 + 192 + 48 * 32
# gain is u32, followed by two serialized bools; there is no struct padding.
PAYLOAD = {0: 0, 1: VMU_PAYLOAD, 2: 6, 3: 8, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0}
VMU_ROOT_SIG = b"\x55" * 16
HOLLY_ID = struct.pack("<II", 0x17FD11DB, 0x11)
PVR_REG_BYTES = 0x8000
# 512 bytes YUV_tempdata plus seven u32 fields, immediately after Maple.
YUV_SERIALIZED_BYTES = 512 + 7 * 4
PVR_FB = {"FB_R_CTRL": 0x44, "FB_W_CTRL": 0x48, "FB_W_LINESTRIDE": 0x4C,
          "FB_R_SOF1": 0x50, "FB_R_SOF2": 0x54, "FB_R_SIZE": 0x5C,
          "FB_W_SOF1": 0x60, "FB_W_SOF2": 0x64, "PARAM_BASE": 0x20,
          "REGION_BASE": 0x2C}


def _bounds(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"truncated or out-of-bounds {label}")


def _u32(data: bytes, offset: int, label: str) -> int:
    _bounds(data, offset, 4, label)
    return struct.unpack_from("<I", data, offset)[0]


def _zstd(blob: bytes, limit: int) -> bytes:
    try:
        from compression import zstd  # Python 3.14+
    except ImportError:
        try:
            import zstandard
        except ImportError as exc:
            raise ValueError("RZIP v2 requires compression.zstd or zstandard") from exc
        try:
            declared = zstandard.frame_content_size(blob)
            if declared not in (zstandard.CONTENTSIZE_UNKNOWN, zstandard.CONTENTSIZE_ERROR) and declared > limit:
                raise ValueError("oversized RZIP zstd chunk")
            result = zstandard.ZstdDecompressor().decompress(
                blob, max_output_size=limit, allow_extra_data=False)
        except zstandard.ZstdError as exc:
            raise ValueError("invalid or truncated RZIP zstd chunk") from exc
    else:
        try:
            decoder = zstd.ZstdDecompressor()
            result = decoder.decompress(blob, max_length=limit + 1)
            if not decoder.eof or decoder.unused_data:
                raise ValueError("invalid, truncated or oversized RZIP zstd chunk")
        except zstd.ZstdError as exc:
            raise ValueError("invalid RZIP zstd chunk") from exc
    if len(result) > limit:
        raise ValueError("oversized RZIP zstd chunk")
    return result


def _deflate(blob: bytes, limit: int) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(blob, limit + 1)
    except zlib.error as exc:
        raise ValueError("invalid RZIP deflate chunk") from exc
    if len(result) > limit or decoder.unconsumed_tail:
        raise ValueError("oversized RZIP deflate chunk")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("truncated RZIP chunk or trailing compressed bytes")
    return result


def unpack(raw: bytes, *, max_bytes: int = MAX_STATE_BYTES) -> bytes:
    """Return the core MEM blob; reject truncated, ambiguous or oversized containers.

    RZIP uses its declared codec (v1 deflate, v2 zstd), not payload guessing.
    The output budget bounds decompression, including unknown-size zstd frames.
    RASTATE v1 is validated through its terminal END block before returning MEM.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    data = raw
    if data.startswith(b"#RZIPv"):
        _bounds(data, 0, 20, "RZIP header")
        codec = data[6]
        if data[7] != ord("#") or codec not in (1, 2):
            raise ValueError("unsupported RZIP header or version")
        chunk_size, total = struct.unpack_from("<IQ", data, 8)
        if not 0 < chunk_size <= MAX_RZIP_CHUNK or total > max_bytes:
            raise ValueError("RZIP declared size exceeds inspection budget")
        pos, result = 20, bytearray()
        while len(result) < total:
            n = _u32(data, pos, "RZIP chunk header")
            pos += 4
            if not n:
                raise ValueError("empty RZIP compressed chunk")
            _bounds(data, pos, n, "RZIP chunk")
            blob = data[pos:pos + n]
            pos += n
            limit = min(chunk_size, total - len(result))
            decoded = _zstd(blob, limit) if codec == 2 else _deflate(blob, limit)
            if not decoded:
                raise ValueError("empty RZIP decoded chunk")
            result.extend(decoded)
        if len(result) != total or pos != len(data):
            raise ValueError("RZIP declared size mismatch or trailing data")
        data = bytes(result)
    if len(data) > max_bytes:
        raise ValueError("state exceeds inspection budget")
    if not data.startswith(b"RASTATE"):
        return data
    _bounds(data, 0, 8, "RASTATE header")
    if data[7] != 1:
        raise ValueError("unsupported RASTATE version")
    pos, mem = 8, None
    while pos < len(data):
        _bounds(data, pos, 8, "RASTATE block header")
        tag, n = data[pos:pos + 4], _u32(data, pos + 4, "RASTATE block size")
        pos += 8
        padded = (n + 7) & ~7
        _bounds(data, pos, padded, "RASTATE block payload/padding")
        if tag == b"MEM ":
            if mem is not None:
                raise ValueError("duplicate RASTATE MEM blocks")
            mem = data[pos:pos + n]
        if tag == b"END ":
            if n or pos != len(data):
                raise ValueError("invalid RASTATE END block or trailing data")
            if mem is None:
                raise ValueError("RASTATE container has no MEM block")
            return mem
        pos += padded
    raise ValueError("RASTATE container has no END block")


def version(mem: bytes) -> int:
    _bounds(mem, 0, 4, "serializer version")
    return struct.unpack_from("<i", mem, 0)[0]


def _maple_version(mem: bytes) -> None:
    v = version(mem)
    if not FLYCAST_V47 <= v <= FLYCAST_V59:
        raise ValueError(f"unsupported Maple serializer {v}; supported V47..V59")


def _parse_table(mem: bytes, p: int, limit: int | None = None) -> tuple[list[list[dict | None]], int]:
    limit = len(mem) if limit is None else limit
    if not 0 <= p <= limit <= len(mem):
        raise ValueError("invalid Maple table bounds")
    ports = []
    for _ in range(4):
        row = []
        for _ in range(6):
            if p >= limit:
                raise ValueError("truncated Maple device table")
            t = mem[p]
            p += 1
            if t == MDT_NONE:
                row.append(None)
                continue
            if t not in PAYLOAD:
                raise ValueError(f"unsupported Maple device type {t} at {p - 1}")
            size = 1 + PAYLOAD[t]
            if p + size > limit:
                raise ValueError("truncated Maple device payload")
            row.append({"type": MDT[t], "player_num": mem[p]})
            p += size
        ports.append(row)
    return ports, p


def _parse_maple(mem: bytes, offset: int, end: int) -> dict:
    _bounds(mem, offset, 6, "Maple header")
    if mem[offset] > 1 or mem[offset + 1] > 1:
        raise ValueError("invalid Maple serialized bool")
    n = _u32(mem, offset + 2, "Maple DMA count")
    p, dma = offset + 6, []
    if n > max(0, (end - p) // 8):
        raise ValueError("Maple DMA count exceeds table bounds")
    for _ in range(n):
        if p + 8 > end:
            raise ValueError("truncated Maple DMA header")
        addr, words = struct.unpack_from("<II", mem, p)
        p += 8
        if words > (end - p) // 4:
            raise ValueError("truncated Maple DMA payload")
        dma.append((addr, words))
        p += 4 * words
    ports, table_end = _parse_table(mem, p, end)
    if table_end != end:
        raise ValueError("Maple table does not end at the serialized YUV block")
    return {"offset": offset, "table_offset": p, "pending_reset": bool(mem[offset]),
            "sdckb_occupied": bool(mem[offset + 1]), "dma_out": dma,
            "ports": ports, "end": table_end}


def maple_devices(mem: bytes, *, offset: int | None = None) -> dict:
    """Decode a uniquely validated Maple table without guessing slot assignments.

    Main controllers occupy slot 5; VMU and rumble normally occupy slots 0/1.
    Auto discovery anchors port A's VMU and requires the exact subsequent
    540-byte YUV block and complete PVR registers. Unsupported devices or
    ambiguous candidates are rejected. A VMU-free table needs an explicit
    serializer-derived offset; auto discovery cannot prove it is absent.
    """
    _maple_version(mem)
    end = pvr_framebuffer(mem)["offset"] - YUV_SERIALIZED_BYTES
    if offset is not None:
        return _parse_maple(mem, offset, end)
    candidates = {}
    start, signatures = 0, 0
    while True:
        i = mem.find(VMU_ROOT_SIG, start, max(0, end))
        if i < 0:
            break
        signatures += 1
        if signatures > 256:
            raise ValueError("VMU signature scan exceeds inspection budget; supply an explicit offset")
        start = i + 1
        flash = i - 0xFF * 512
        if flash < 8 or mem[flash - 2] != 1:
            continue
        # First expansion slot, or second when the first slot is empty.
        table_starts = [flash - 2]
        if mem[flash - 3] == MDT_NONE:
            table_starts.append(flash - 3)
        for table in table_starts:
            try:
                _, actual_end = _parse_table(mem, table, end)
                if actual_end != end:
                    continue
            except ValueError:
                continue
            # Diagnostic search budget; a larger DMA queue requires an explicit offset.
            for k in range(max(4, table - 65536), table - 5):
                if mem[k] > 1 or mem[k + 1] > 1:
                    continue
                try:
                    found = _parse_maple(mem, k, end)
                except ValueError:
                    continue
                if found["table_offset"] == table:
                    candidates[k] = found
    if len(candidates) != 1:
        raise ValueError(f"expected one validated Maple table; found {len(candidates)}")
    return next(iter(candidates.values()))


def pvr_framebuffer(mem: bytes, after: int = 0) -> dict:
    """Inspect one complete register-signature candidate, rejecting ambiguity.

    FB_W_SOF1 bit 24 marks the register's framebuffer write destination as RTT.
    It does not establish which render completed, GPU cache contents, missing
    background bytes, or whether replay can recover a displayed frame.
    ``last_render_is_rtt`` is retained as a compatibility alias only.
    """
    if not 0 <= after <= len(mem):
        raise ValueError("invalid PVR scan offset")
    candidates = []
    p = after
    while True:
        p = mem.find(HOLLY_ID, p)
        if p < 0:
            break
        if p + PVR_REG_BYTES <= len(mem):
            candidates.append(p)
            if len(candidates) > 1:
                raise ValueError("expected one complete PowerVR register signature; found 2 or more")
        p += 1
    if len(candidates) != 1:
        raise ValueError(f"expected one complete PowerVR register signature; found {len(candidates)}")
    i = candidates[0]
    regs = {k: _u32(mem, i + o, "PVR register") for k, o in PVR_FB.items()}
    rtt = bool(regs["FB_W_SOF1"] & 0x1000000)
    return {"offset": i, **regs, "fb_write_is_rtt": rtt, "last_render_is_rtt": rtt}


def compare_maple(a: bytes, b: bytes) -> dict:
    """Compare the inspected topology and pending DMA metadata, not VMU content."""
    ma, mb = maple_devices(a), maple_devices(b)
    keys = ("pending_reset", "sdckb_occupied", "dma_out", "ports")
    return {"same": all(ma[k] == mb[k] for k in keys),
            "a": {k: ma[k] for k in keys}, "b": {k: mb[k] for k in keys}}
