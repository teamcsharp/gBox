"""Read-only inspection of RetroArch/Flycast (libretro) save states.

Used to diagnose state-replay defects (inbox #1216) without loading the state into a core:
  * unpack RetroArch ``#RZIPv`` (zlib/zstd chunks) and ``RASTATE`` containers to the core's MEM blob;
  * read the Flycast serializer version (V59 == 854 in current cores);
  * locate and decode the Maple device table (``mcfg_SerializeDevices``) so a loaded state's controller /
    VMU / rumble topology can be compared with a fresh boot;
  * read the PowerVR framebuffer registers and whether the last render was render-to-texture.

Never writes to the input. Layout follows flyinghead/flycast core/serialize.cpp (dc_serialize order:
aica, sb, nvmem, gdrom, maple, pvr, ...).
"""
from __future__ import annotations

import struct
import zlib

FLYCAST_V59 = 854
MDT = {0: "SegaController", 1: "SegaVMU", 2: "Microphone", 3: "PurupuruPack", 4: "AsciiStick", 5: "Keyboard",
       6: "Mouse", 7: "LightGun", 8: "TwinStick", 9: "NaomiJamma", 10: None}
MDT_NONE = 10
VMU_PAYLOAD = 128 * 1024 + 192 + 48 * 32           # flash_data + lcd_data + lcd_data_decoded
PAYLOAD = {0: 0, 1: VMU_PAYLOAD, 2: 3, 3: 8}       # bytes after the u8 player_num, per device type
VMU_ROOT_SIG = b"\x55" * 16                        # VMU system block 255 starts with 16 x 0x55
HOLLY_ID = struct.pack("<II", 0x17FD11DB, 0x11)    # PVR ID + REVISION registers (start of pvr_regs)
PVR_FB = {"FB_R_CTRL": 0x44, "FB_W_CTRL": 0x48, "FB_W_LINESTRIDE": 0x4C, "FB_R_SOF1": 0x50, "FB_R_SOF2": 0x54,
          "FB_R_SIZE": 0x5C, "FB_W_SOF1": 0x60, "FB_W_SOF2": 0x64, "PARAM_BASE": 0x20, "REGION_BASE": 0x2C}


def _zstd(blob: bytes) -> bytes:
    try:
        from compression import zstd                # Python 3.14+
        return zstd.decompress(blob)
    except ImportError:
        import zstandard                             # optional on older interpreters
        return zstandard.ZstdDecompressor().decompressobj().decompress(blob)


def unpack(raw: bytes) -> bytes:
    """Return the core's serialized blob from a RetroArch state file (rzip and/or RASTATE wrapped)."""
    data = raw
    if data.startswith(b"#RZIPv"):
        pos, parts = 20, []
        while pos < len(data):
            (n,) = struct.unpack_from("<I", data, pos)
            blob = data[pos + 4:pos + 4 + n]
            pos += 4 + n
            parts.append(_zstd(blob) if blob[:4] == b"\x28\xb5\x2f\xfd" else zlib.decompress(blob))
        data = b"".join(parts)
    if data.startswith(b"RASTATE"):
        pos = 8
        while pos + 8 <= len(data):
            tag, n = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
            if tag == b"MEM ":
                return data[pos + 8:pos + 8 + n]
            if tag == b"END ":
                break
            pos += 8 + ((n + 7) & ~7)
        raise ValueError("RASTATE container has no MEM block")
    return data


def version(mem: bytes) -> int:
    return struct.unpack_from("<i", mem, 0)[0]


def _parse_table(mem: bytes, p: int) -> tuple[list[list[dict | None]], int]:
    ports = []
    for _ in range(4):
        row = []
        for _ in range(6):
            t = mem[p]
            p += 1
            if t == MDT_NONE:
                row.append(None)
                continue
            if t not in PAYLOAD:
                raise ValueError(f"unsupported maple device type {t} at {p - 1}")
            row.append({"type": MDT[t], "player_num": mem[p]})
            p += 1 + PAYLOAD[t]
        ports.append(row)
    return ports, p


def maple_devices(mem: bytes) -> dict:
    """Decode mcfg_SerializeDevices. Anchored on port A's VMU root block, then validated by walking the
    header (pending_reset, SDCKBOccupied, mapleDmaOut list) so the table start is exact."""
    if version(mem) < 842:                          # header layout below needs >= V47 (V16 = 811)
        raise ValueError(f"serializer {version(mem)} predates V47")
    start = 0
    while True:
        i = mem.find(VMU_ROOT_SIG, start)
        if i < 0:
            raise ValueError("no VMU root block found; cannot anchor the maple table")
        start = i + 1
        flash = i - 0xFF * 512
        if flash < 10 or mem[flash - 2] != 1 or mem[flash - 4] != 0:
            continue
        t0 = flash - 4                              # [00 pn][01 pn] = controller + VMU on port A
        for k in range(max(0, t0 - 65536), t0 - 5):
            if mem[k] > 1 or mem[k + 1] > 1:
                continue
            (n,) = struct.unpack_from("<I", mem, k + 2)
            q, ok, dma = k + 6, n < 64, []
            for _ in range(n if ok else 0):
                if q + 8 > t0:
                    ok = False
                    break
                addr, words = struct.unpack_from("<II", mem, q)
                dma.append((addr, words))
                q += 8 + 4 * words
            if ok and q == t0:
                ports, end = _parse_table(mem, t0)
                return {"offset": k, "pending_reset": bool(mem[k]), "sdckb_occupied": bool(mem[k + 1]),
                        "dma_out": dma, "ports": ports, "end": end}


def pvr_framebuffer(mem: bytes, after: int = 0) -> dict:
    i = mem.find(HOLLY_ID, after)
    if i < 0:
        raise ValueError("PowerVR register block not found")
    regs = {k: struct.unpack_from("<I", mem, i + o)[0] for k, o in PVR_FB.items()}
    return {"offset": i, **regs, "last_render_is_rtt": bool(regs["FB_W_SOF1"] & 0x1000000)}


def compare_maple(a: bytes, b: bytes) -> dict:
    """Topology diff between two states (e.g. supplied moment vs. fresh-boot control)."""
    ma, mb = maple_devices(a), maple_devices(b)
    keys = ("pending_reset", "sdckb_occupied", "dma_out", "ports")
    return {"same": all(ma[k] == mb[k] for k in keys), "a": {k: ma[k] for k in keys}, "b": {k: mb[k] for k in keys}}
