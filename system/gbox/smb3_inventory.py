"""Super Mario Bros. 3 (NES) build identity and player-sprite inventory.

SMB3 is a 2D MMC3 (iNES mapper 4) cartridge: 256 KB PRG ROM in 8 KB banks and
128 KB CHR ROM addressed by the game in 1 KB pages.  The player character is
not a mesh; it is a set of 8x16 sprite patterns.  The fixed player-draw code
(PRG bank 29, mapped at $C000 in the captainsouthbird/smb3 disassembly, which
targets the Rev 1 / PRG1 build) uses four tables that sit back to back:

* ``SPPF_Offsets``  81 bytes, frame -> (index*2 - 4) into ``SPPF_Table``
* ``SPPF_Table``    81 frames x 6 pattern bytes (top row 3, bottom row 3,
  ``$F1`` = sprite hidden)
* ``Player_FramePageOff`` 81 bytes, 1 KB CHR page offset (0..3) per frame
* 16 bytes of draw offsets, then ``Player_PUpRootPage`` (7 bytes): root CHR
  page for Small, Big, Fire, Leaf, Frog, Tanooki, Hammer.

``Player_Draw`` stores ``root + pageoff`` into ``PatTable_BankSel+2``, the
sprite page at PPU $1000.  Patterns < $40 live in that page; patterns >= $80
($A9/$AB/$AD) are in the shared page at PPU $1800 (``PatTable_BankSel+4``).

Addresses differ between Rev 0 and Rev 1, so this module locates the tables
by content and validates their internal structure instead of hard-coding the
disassembly's offsets.  ``python -m gbox.smb3_inventory SRC --out m.json
--png sheet.png`` writes the manifest and a contact sheet of every player
frame per power-up.  Originals are only read.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

INES_MAGIC = b"NES\x1a"
PRG_UNIT = 0x4000
CHR_UNIT = 0x2000
CHR_PAGE = 0x400
PRG_BANK = 0x2000
HIDDEN = 0xF1
FRAMES = 81
POWERUPS = ("small", "big", "fire", "leaf", "frog", "tanooki", "hammer")
# Player_PUpRootPage as shipped (identical in Rev 0 and Rev 1).
ROOT_SIG = bytes((0x50, 0x54, 0x54, 0x00, 0x50, 0x40, 0x44))
DRAW_OFFSETS = 16

# No-Intro identities (headerless CRC32/MD5/SHA1, from RetroArch's NES rdb).
KNOWN = {
    0xA0B0B742: {
        "name": "Super Mario Bros. 3 (USA)",
        "revision": "Rev 0 (PRG0)",
        "serial": "NES-UM-USA-1",
        "md5": "b76f978ad3076ea67f2b0aca7399c9e9",
        "sha1": "a611b90b4833b20a364bf06ee3be3b9093ea4df9",
    },
    0x2E6301ED: {
        "name": "Super Mario Bros. 3 (USA) (Rev 1)",
        "revision": "Rev 1 (PRG1)",
        "serial": "NES-UM-USA-1",
        "md5": "55b7111567c1709e849c574078699577",
        "sha1": "bb894d104c796f69ba16587eb66c0275f5c2fc02",
    },
}

MAPPERS = {0: "NROM", 1: "MMC1", 2: "UxROM", 3: "CNROM", 4: "MMC3"}


def read_source(path) -> tuple[bytes, dict]:
    """Return (iNES bytes, source info) for a .nes file or a zip holding one."""
    path = Path(path)
    raw = path.read_bytes()
    info = {"path": str(path), "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".nes")]
            if len(names) != 1:
                raise ValueError(f"expected one .nes member, found {names}")
            info["member"] = names[0]
            return z.read(names[0]), info
    return raw, info


def parse_ines(data: bytes) -> dict:
    if data[:4] != INES_MAGIC:
        raise ValueError("not an iNES image")
    f6, f7 = data[6], data[7]
    nes2 = (f7 & 0x0C) == 0x08
    trainer = bool(f6 & 4)
    prg = data[4] * PRG_UNIT
    chr_ = data[5] * CHR_UNIT
    start = 16 + (512 if trainer else 0)
    if len(data) < start + prg + chr_:
        raise ValueError("iNES image shorter than its header claims")
    mapper = (f6 >> 4) | (f7 & 0xF0)
    return {
        "prg_size": prg, "chr_size": chr_, "mapper": mapper,
        "mapper_name": MAPPERS.get(mapper, f"mapper {mapper}"),
        "mirroring": "four-screen" if f6 & 8 else ("vertical" if f6 & 1 else "horizontal"),
        "battery": bool(f6 & 2), "trainer": trainer, "nes2": nes2,
        "header_hex": data[:16].hex(), "prg_offset": start,
        "chr_offset": start + prg,
        "trailing_bytes": len(data) - (start + prg + chr_),
    }


def split(data: bytes, hdr: dict) -> tuple[bytes, bytes]:
    p = hdr["prg_offset"]
    return data[p:p + hdr["prg_size"]], data[hdr["chr_offset"]:hdr["chr_offset"] + hdr["chr_size"]]


def identify(body: bytes) -> dict:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    out: dict = {"crc32": f"{crc:08x}", "md5": hashlib.md5(body).hexdigest(),
           "sha1": hashlib.sha1(body).hexdigest(),
           "sha256": hashlib.sha256(body).hexdigest()}
    k = KNOWN.get(crc)
    if k and k["md5"] == out["md5"] and k["sha1"] == out["sha1"]:
        out.update(match=True, **{x: k[x] for x in ("name", "revision", "serial")})
    else:
        out["match"] = False
    return out


def locate_player_tables(prg: bytes) -> dict:
    """Find and validate the four player-draw tables in PRG ROM."""
    hits = []
    pos = prg.find(ROOT_SIG)
    while pos >= 0:
        page_off = pos - DRAW_OFFSETS - FRAMES
        table = page_off - FRAMES * 6
        offsets = table - FRAMES
        if offsets >= 0:
            offs = prg[offsets:table]
            pages = prg[page_off:page_off + FRAMES]
            ok_offs = all(offs[i] == 3 * i + 2 for i in range(FRAMES))
            ok_pages = all(v <= 3 for v in pages) and list(pages) == sorted(pages)
            if ok_offs and ok_pages:
                hits.append((offsets, table, page_off, pos))
        pos = prg.find(ROOT_SIG, pos + 1)
    if len(hits) != 1:
        raise ValueError(f"player tables not uniquely located ({len(hits)} candidates)")
    offsets, table, page_off, root = hits[0]
    bank = root // PRG_BANK
    cpu_base = 0xC000 if bank == 29 else None

    def cpu(off):
        return None if cpu_base is None else cpu_base + (off - bank * PRG_BANK)

    out = {
        "prg_bank": bank,
        "sppf_offsets": {"prg_offset": offsets, "cpu": cpu(offsets)},
        "sppf_table": {"prg_offset": table, "cpu": cpu(table)},
        "frame_page_off": {"prg_offset": page_off, "cpu": cpu(page_off)},
        "pup_root_page": {"prg_offset": root, "cpu": cpu(root)},
    }
    if cpu_base is not None:
        out["xrefs"] = {k: absolute_xrefs(prg, bank, out[k]["cpu"])
                        for k in ("sppf_offsets", "frame_page_off", "pup_root_page")}
        # SPPF_Table is reached through a zero-page pointer built from
        # LDA #<(SPPF_Table-4) / LDA #>(SPPF_Table-4).
        out["xrefs"]["sppf_table"] = immediate_pointer_xrefs(prg, bank, out["sppf_table"]["cpu"] - 4)
    out["frames"] = [list(prg[table + 6 * i: table + 6 * i + 6]) for i in range(FRAMES)]
    out["page_off"] = list(prg[page_off:page_off + FRAMES])
    out["root_pages"] = dict(zip(POWERUPS, prg[root:root + len(POWERUPS)]))
    return out


_ABS_READS = {0xAD: "LDA", 0xBD: "LDA,X", 0xB9: "LDA,Y", 0xAE: "LDX", 0xBE: "LDX,Y",
              0xAC: "LDY", 0xBC: "LDY,X", 0x6D: "ADC", 0x7D: "ADC,X", 0x79: "ADC,Y"}


def absolute_xrefs(prg: bytes, bank: int, target: int, window: int = 4) -> list:
    """Absolute-mode loads in ``bank`` whose operand is within ``window`` below
    ``target`` (the draw code reads SPPF_Table from 4 bytes shy, by design)."""
    lo, hi = bank * PRG_BANK, (bank + 1) * PRG_BANK
    out = []
    for i in range(lo, hi - 2):
        op = prg[i]
        if op in _ABS_READS:
            a = prg[i + 1] | prg[i + 2] << 8
            if target - window <= a <= target:
                out.append({"cpu": 0xC000 + (i - lo), "op": _ABS_READS[op],
                            "operand": a, "delta": a - target})
    return out


def immediate_pointer_xrefs(prg: bytes, bank: int, target: int, gap: int = 6) -> list:
    """``LDA #<target`` followed within ``gap`` bytes by ``LDA #>target``."""
    lo, hi = bank * PRG_BANK, (bank + 1) * PRG_BANK
    out = []
    for i in range(lo, hi - 3):
        if prg[i] == 0xA9 and prg[i + 1] == target & 0xFF:
            for j in range(i + 2, min(i + 2 + gap, hi - 1)):
                if prg[j] == 0xA9 and prg[j + 1] == target >> 8:
                    out.append({"cpu": 0xC000 + (i - lo), "op": "LDA #lo/#hi",
                                "operand": target, "delta": -4})
                    break
    return out


def tile(chr_: bytes, index: int) -> list[list[int]]:
    """Decode one 8x8 2bpp tile into rows of colour indices 0..3."""
    b = chr_[index * 16: index * 16 + 16]
    return [[((b[r] >> (7 - c)) & 1) | (((b[r + 8] >> (7 - c)) & 1) << 1)
             for c in range(8)] for r in range(8)]


def pattern_page(page: int, pattern: int, shared_page: int | None) -> tuple[int | None, int]:
    """Map an 8x16 sprite pattern to (CHR 1 KB page, tile index within page)."""
    t = pattern & 0xFE  # top tile of the 8x16 pair; bit 0 selects PPU $1000
    if t < 0x40:
        return page, t
    if 0x80 <= t < 0xC0 and shared_page is not None:
        return shared_page, t - 0x80
    return None, t


def player_inventory(prg: bytes, chr_: bytes, tables: dict) -> dict:
    pups = {}
    for name, root in tables["root_pages"].items():
        frames, pages = [], set()
        for f, pats in enumerate(tables["frames"]):
            page = root + tables["page_off"][f]
            sprites = []
            for slot, p in enumerate(pats):
                if p == HIDDEN:
                    continue
                pg, t = pattern_page(page, p, None)
                sprites.append({"slot": slot, "pattern": p, "page": pg, "tile": t})
                if pg is not None:
                    pages.add(pg)
            frames.append({"frame": f, "page": page, "sprites": sprites})
        pups[name] = {
            "root_page": root,
            "pages": sorted(pages),
            "chr_offsets": [p * CHR_PAGE for p in sorted(pages)],
            "page_sha256": {p: hashlib.sha256(chr_[p * CHR_PAGE:(p + 1) * CHR_PAGE]).hexdigest()
                            for p in sorted(pages)},
            "frames": frames,
        }
    shared = sorted({p for pats in tables["frames"] for p in pats
                     if p != HIDDEN and p >= 0x40})
    return {"powerups": pups, "shared_page_patterns": shared}


GREY = ((0, 0, 0, 0), (232, 64, 40, 255), (248, 184, 120, 255), (120, 72, 0, 255))


def render_sheet(chr_: bytes, inv: dict) -> tuple[int, int, bytes]:
    """RGBA contact sheet: one row per power-up, one 24x32 cell per frame."""
    cw, ch, pad = 24, 32, 2
    cols, rows = FRAMES, len(inv["powerups"])
    W, H = cols * (cw + pad), rows * (ch + pad)
    px = bytearray(W * H * 4)
    for r, (name, pu) in enumerate(inv["powerups"].items()):
        for fr in pu["frames"]:
            ox, oy = fr["frame"] * (cw + pad), r * (ch + pad)
            for s in fr["sprites"]:
                if s["page"] is None:
                    continue
                sx, sy = ox + (s["slot"] % 3) * 8, oy + (s["slot"] // 3) * 16
                base = s["page"] * 64 + s["tile"]
                for half in (0, 1):
                    for y, row in enumerate(tile(chr_, base + half)):
                        for x, v in enumerate(row):
                            if v:
                                o = ((sy + half * 8 + y) * W + sx + x) * 4
                                px[o:o + 4] = bytes(GREY[v])
    return W, H, bytes(px)


def png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def inventory(src) -> dict:
    data, source = read_source(src)
    hdr = parse_ines(data)
    prg, chr_ = split(data, hdr)
    ident = identify(prg + chr_)
    tables = locate_player_tables(prg)
    inv = player_inventory(prg, chr_, tables)
    return {
        "game": "Super Mario Bros. 3", "platform": "nes",
        "source": source, "ines": hdr, "identity": ident,
        "prg_bank_sha256": [hashlib.sha256(prg[i:i + PRG_BANK]).hexdigest()
                            for i in range(0, len(prg), PRG_BANK)],
        "chr_page_count": len(chr_) // CHR_PAGE,
        "launch": {"core": "mesen (libretro) or any MMC3-capable NES core",
                   "bios": None, "notes": "cartridge image only; no BIOS or disk system"},
        "player_tables": {k: v for k, v in tables.items() if k not in ("frames", "page_off")},
        "player": inv,
        "roster": [{
            "character": "Mario", "slot": "player",
            "powerups": list(POWERUPS),
            "frames_per_powerup": FRAMES,
            "note": "Luigi (player 2) is drawn by the same Player_Draw tables and CHR "
                    "pages; the analysis stage must confirm his palette-only difference",
        }],
        "constraints": {
            "sprite_mode": "8x16", "tile_bpp": 2, "colours_per_palette": 3,
            "page_size": CHR_PAGE, "tiles_per_page": 64,
            "frame_layout": "3x2 sprites (24x32), $F1 hides a sprite",
            "note": "a replacement must fit each power-up's 1 KB pages and the shared "
                    "frame table; a 3D donor must be rendered to 2bpp tiles",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    ap.add_argument("--png")
    a = ap.parse_args(argv)
    m = inventory(a.src)
    if a.png:
        data, _ = read_source(a.src)
        hdr = parse_ines(data)
        _, chr_ = split(data, hdr)
        Path(a.png).write_bytes(png_bytes(*render_sheet(chr_, m["player"])))
    text = json.dumps(m, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    pu = m["player"]["powerups"]
    print(json.dumps({"identity": m["identity"], "mapper": m["ines"]["mapper_name"],
                      "tables": m["player_tables"],
                      "pages": {k: v["pages"] for k, v in pu.items()}}, default=str))


if __name__ == "__main__":
    main()
