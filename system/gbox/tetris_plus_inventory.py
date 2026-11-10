"""Tetris Plus (USA, PS1) inventory: native CHD v5 read (gbox.chd.ChdDisc, no chdman), ISO9660 manifest with
per-file sha256, boot PS-X EXE identity, and TIM texture scan/export for the 2D sprite packs.

Tetris Plus is a 2D puzzle game (overlay EXEs + BIN packs holding PSX TIM images), not a Sega Ninja title.
Read-only; the disc is never modified.

    python -m gbox.tetris_plus_inventory <disc.chd> [--out DIR] [--tim FILE.BIN:INDEX]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

TIM_MAGIC = 0x10
BOOT = "SLUS_003.38"


def sha256_stream(chd_disc, name: str) -> str:
    lba, n = chd_disc.files[name.upper()]
    h, left = hashlib.sha256(), n
    for i in range((n + 2047) // 2048):
        c = chd_disc.sector(lba + i)[:left]
        h.update(c)
        left -= len(c)
    return h.hexdigest()


def exe_header(data: bytes) -> dict:
    if data[:8] != b"PS-X EXE":
        raise ValueError("not a PS-X EXE")
    pc, gp, load, size = struct.unpack_from("<IIII", data, 0x10)
    return {"pc": pc, "gp": gp, "load_addr": load, "text_size": size}


def parse_tim(buf: bytes, off: int = 0) -> dict | None:
    """Parse one TIM at ``off``; None when it is not a valid, in-bounds TIM. Fields only, no pixel decode."""
    if off + 12 > len(buf) or struct.unpack_from("<I", buf, off)[0] != TIM_MAGIC:
        return None
    flags = struct.unpack_from("<I", buf, off + 4)[0]
    if flags & ~0xB or (flags & 3) == 3 and flags & 8:
        return None
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[flags & 3]
    p = off + 8
    clut = None
    if flags & 8:
        bnum, cx, cy, cw, ch = struct.unpack_from("<IHHHH", buf, p)
        if bnum != 12 + cw * ch * 2 or not (0 < cw <= 1024 and 0 < ch <= 512) or p + bnum > len(buf):
            return None
        clut = {"x": cx, "y": cy, "w": cw, "h": ch, "off": p + 12}
        p += bnum
    if p + 12 > len(buf):
        return None
    bnum, ix, iy, iw, ih = struct.unpack_from("<IHHHH", buf, p)
    if bnum != 12 + iw * ih * 2 or not (0 < iw <= 1024 and 0 < ih <= 512) or p + bnum > len(buf):
        return None
    width = iw * {4: 4, 8: 2, 16: 1, 24: 2 / 3}[bpp]
    return {"off": off, "bpp": bpp, "clut": clut, "fb_x": ix, "fb_y": iy, "fb_w": iw, "h": ih,
            "width": int(width), "data_off": p + 12, "end": p + bnum}


def scan_tims(buf: bytes) -> list[dict]:
    out, o = [], 0
    while True:
        o = buf.find(struct.pack("<I", TIM_MAGIC), o)
        if o < 0:
            return out
        t = parse_tim(buf, o)
        if t:
            out.append(t)
            o = t["end"]
        else:
            o += 4


def _bgr555(v: int) -> tuple[int, int, int, int]:
    r, g, b = v & 31, (v >> 5) & 31, (v >> 10) & 31
    return (r * 255 // 31, g * 255 // 31, b * 255 // 31, 0 if v == 0 else 255)


def tim_to_png(buf: bytes, tim: dict, clut_row: int = 0) -> bytes:
    """Decode a 4/8/16-bit TIM to an RGBA PNG (stdlib zlib; palette entry 0x0000 is transparent)."""
    w, h, bpp = tim["width"], tim["h"], tim["bpp"]
    if bpp == 24:
        raise ValueError("24-bit TIM not supported")
    d = tim["data_off"]
    pal = None
    if bpp in (4, 8):
        c = tim["clut"]
        if c is None:
            raise ValueError("indexed TIM without CLUT")
        base = c["off"] + clut_row * c["w"] * 2
        pal = [_bgr555(struct.unpack_from("<H", buf, base + 2 * i)[0]) for i in range(min(c["w"], 1 << bpp))]
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            if bpp == 16:
                px = _bgr555(struct.unpack_from("<H", buf, d + (y * w + x) * 2)[0])
            elif bpp == 8:
                px = pal[buf[d + y * w + x]]
            else:
                b = buf[d + y * (w // 2) + x // 2]
                px = pal[(b >> 4) if x & 1 else (b & 15)]
            row += bytes(px)
        rows.append(bytes(row))

    def chunk(t, body):
        c = struct.pack(">I", len(body)) + t + body
        return c + struct.pack(">I", zlib.crc32(t + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def inventory(disc_path, out_dir=None, tim_pack: str = "PAZLEE.BIN", tim_index: int = 0) -> dict:
    from .chd import ChdDisc, track_layout
    d = ChdDisc(disc_path)
    try:
        files = []
        for name, (lba, size) in sorted(d.files.items()):
            files.append({"path": name, "lba": lba, "size": size, "sha256": sha256_stream(d, name)})
        boot = d.read(BOOT)
        man = {
            "game": "Tetris Plus (USA)", "platform": "psx", "container": "CHD v5 CD", "track_type": d.track_type,
            "volume": d.pvd[40:72].decode("latin-1").strip(), "byte_order": "little", "offset_base": "file start",
            "boot": {"path": BOOT, "sha256": hashlib.sha256(boot).hexdigest(), "size": len(boot), **exe_header(boot)},
            "files": files, "packs": {},
        }
        for f in files:
            if f["path"].endswith(".BIN"):
                man["packs"][f["path"]] = len(scan_tims(d.read(f["path"])))
        pack = d.read(tim_pack)
        tims = scan_tims(pack)
        if out_dir is not None:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            png = tim_to_png(pack, tims[tim_index])
            (out / f"{Path(tim_pack).stem}_{tim_index:03d}.png").write_bytes(png)
            man["target_asset"] = {"pack": tim_pack, "index": tim_index, "tim": {k: v for k, v in tims[tim_index].items()
                                    if k != "clut"}, "png_sha256": hashlib.sha256(png).hexdigest()}
            (out / "manifest.json").write_text(json.dumps(man, indent=1))
        return man
    finally:
        d.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("--out") + 1] if "--out" in a else "."
    m = inventory(a[0], out)
    print(json.dumps({k: m[k] for k in ("boot", "packs", "target_asset") if k in m}, indent=1))
