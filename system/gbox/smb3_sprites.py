"""Super Mario Bros. 3 (NES) player sprite reader (a collection ``sprites`` entry).

Inventory (``gbox.smb3_inventory``) located the four player-draw tables in PRG
bank 29 and the CHR page groups; analysis (``gbox.smb3_analysis``) traced
``Player_Draw`` to MMC3 R2 (PPU $1000), the palettes and the Kuribo's-shoe
shared page.  This reader turns that into editable, re-encodable art plus a
machine-readable frame map, straight from the owned Rev 0 ROM.

Per power-up it writes an *indexed 4-colour PNG* of the 81 frames (a 9x9 grid
of 24x32 cells).  Pixel index 0 is transparent and 1..3 are the power-up's
three palette colours, so editing a pixel's index edits exactly one 2bpp CHR
plane bit and ``encode_tile`` reconstructs the byte-identical tile.  The
reader also writes a 64x64 page atlas for every player CHR page (``$00-03``,
``$40-47``, ``$50-57``; every tile, referenced or not, is kept) and a strip of
the Kuribo page ``$0B`` tiles ``$28-$2D``, plus ``frames.json``: a
slot -> (page, tile) map per frame and the Mario/Luigi palettes from
``smb3_analysis.palette_rules``.

``python -m gbox.smb3_sprites SRC --out DIR`` writes the same files.  The
source is only read.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import smb3_analysis as ana
from . import smb3_inventory as inv

VERSION = "1.0"
READER_VERSION = 1
FPS = 60.0                       # NTSC NES vblank rate
SHEET_COLS = 9                   # 81 frames as a 9x9 grid of 24x32 cells
SHEET_ROWS = 9
TITLE_RE = re.compile(r"^super mario bros\.? 3\b")
# Neutral 4-shade palette for the raw CHR page atlases (index 0 = transparent).
ATLAS_PALETTE = [(0, 0, 0), (96, 96, 96), (168, 168, 168), (235, 235, 235)]


def title_test(title: str, platform: str) -> bool:
    return platform == "nes" and TITLE_RE.match((title or "").strip().lower()) is not None


def roster() -> list[dict]:
    """Mario only: Luigi is drawn by the same tables and CHR pages, differing
    only by the palette entry for small/big/leaf."""
    return [{"key": "MARIO", "slug": "smb3_mario", "name": "Mario (Super Mario Bros. 3)",
             "char": "mario",
             "aliases": ["Mario", "SMB3 Mario", "Super Mario Bros. 3 Mario"], "kind": "character"}]


# ------------------------------------------------------------------------------------------------ 2bpp codec

def encode_tile(rows) -> bytes:
    """8x8 colour indices 0..3 -> the 16-byte 2bpp CHR tile (plane 0, then plane 1)."""
    lo = bytearray(8)
    hi = bytearray(8)
    for y in range(8):
        l = h = 0
        for x in range(8):
            v = rows[y][x] & 3
            l |= (v & 1) << (7 - x)
            h |= (v >> 1) << (7 - x)
        lo[y] = l
        hi[y] = h
    return bytes(lo) + bytes(hi)


def tile_roundtrip(chr_: bytes, index: int) -> bool:
    """Decode + re-encode one 8x8 tile and compare against the raw CHR bytes."""
    return encode_tile(inv.tile(chr_, index)) == chr_[index * 16:index * 16 + 16]


# ------------------------------------------------------------------------------------------------ PNG

def indexed_png_bytes(w: int, h: int, indices: bytes, palette, transparent: int = 0) -> bytes:
    """A colour-type-3 (indexed) PNG: pixel byte = palette index, entry 0 transparent."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = b"".join(bytes(int(c[i]) & 0xFF for i in range(3)) for c in palette)
    trns = bytes([0])                     # index 0 alpha 0; every later entry is opaque
    raw = b"".join(b"\x00" + indices[y * w:(y + 1) * w] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"PLTE", plte)
            + chunk(b"tRNS", trns) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------------------------------------ extractor

class SMB3Sprites:
    """One owned SMB3 ROM: player tables, CHR pages and the palettes, decoded."""

    def __init__(self, src):
        self.rep = ana.analyze(src)                       # palettes, grow steps, Kuribo page
        self.rules = self.rep["palettes"]
        self.shoe_page = self.rep["kuribo"]["page"]
        self.grow = self.rep["grow"]
        data, self.source = inv.read_source(src)
        hdr = inv.parse_ines(data)
        self.prg, self.chr = inv.split(data, hdr)
        self.ident = inv.identify(self.prg + self.chr)
        self.tables = inv.locate_player_tables(self.prg)

    @property
    def pages(self) -> list[int]:
        """The 20 player CHR pages ($00-03, $40-47, $50-57)."""
        return sorted({p for root in self.tables["root_pages"].values()
                       for p in range(root, root + 4)})

    def referenced_tiles(self) -> dict[int, set[int]]:
        """Every (page, tile) a player frame or grow step can draw."""
        used: dict[int, set[int]] = {}

        def add(page, pats):
            for p in pats:
                if p == inv.HIDDEN:
                    continue
                pg, t = inv.pattern_page(page, p, self.shoe_page)
                if pg is not None:
                    used.setdefault(pg, set()).update((t, t + 1))
        for root in self.tables["root_pages"].values():
            for f, pats in enumerate(self.tables["frames"]):
                add(root + self.tables["page_off"][f], pats)
        for st in self.grow["steps"]:
            add(st["page"], self.tables["frames"][st["frame"]])
        return used

    def suit_frames(self, name) -> list:
        """24x32 colour-index grids (0 = transparent) for all 81 frames of one power-up."""
        root = self.tables["root_pages"][name]
        return [ana.frame_indices(self.chr, self.tables["frames"][f],
                                  root + self.tables["page_off"][f], self.shoe_page)
                for f in range(inv.FRAMES)]

    def sheet_png(self, name, player: int = 0) -> bytes:
        who = ("mario", "luigi")[player]
        colours = self.rules["by_suit"][name][who]["colours"]
        palette = [(0, 0, 0)] + [ana.nes_rgb(c) for c in colours]
        w, h = SHEET_COLS * 24, SHEET_ROWS * 32
        idx = bytearray(w * h)
        for f, img in enumerate(self.suit_frames(name)):
            ox, oy = (f % SHEET_COLS) * 24, (f // SHEET_COLS) * 32
            for y, row in enumerate(img):
                for x, v in enumerate(row):
                    idx[(oy + y) * w + ox + x] = v
        return indexed_png_bytes(w, h, bytes(idx), palette)

    def atlas_png(self, page: int) -> bytes:
        """All 64 tiles of a 1 KB CHR page in an 8x8 grid (64x64 px), 2bpp indices kept."""
        idx = bytearray(64 * 64)
        for t in range(64):
            rows = inv.tile(self.chr, page * 64 + t)
            for y in range(8):
                for x in range(8):
                    idx[(t // 8 * 8 + y) * 64 + (t % 8) * 8 + x] = rows[y][x]
        return indexed_png_bytes(64, 64, bytes(idx), ATLAS_PALETTE)

    def kuribo_png(self, tiles: list[int]) -> bytes:
        """The shared shoe-page tiles as a horizontal strip (n*8 x 8 px)."""
        n = len(tiles)
        idx = bytearray(n * 8 * 8)
        for i, t in enumerate(tiles):
            rows = inv.tile(self.chr, self.shoe_page * 64 + t)
            for y in range(8):
                for x in range(8):
                    idx[y * (n * 8) + i * 8 + x] = rows[y][x]
        return indexed_png_bytes(n * 8, 8, bytes(idx), ATLAS_PALETTE)

    def verify_roundtrip(self) -> dict:
        used = self.referenced_tiles()
        mismatches, checked = [], 0
        for pg in sorted(used):
            for t in sorted(used[pg]):
                checked += 1
                if not tile_roundtrip(self.chr, pg * 64 + t):
                    mismatches.append({"page": pg, "tile": t})
        return {"checked": checked, "byte_identical": not mismatches, "mismatches": mismatches,
                "pages": {f"0x{p:02X}": len(used[p]) for p in sorted(used)}}

    def frame_map(self) -> dict:
        suits = {}
        for name in inv.POWERUPS:
            root = self.tables["root_pages"][name]
            frames = []
            for f, pats in enumerate(self.tables["frames"]):
                page = root + self.tables["page_off"][f]
                sprites = []
                for slot, p in enumerate(pats):
                    if p == inv.HIDDEN:
                        sprites.append({"slot": slot, "hidden": True})
                        continue
                    pg, t = inv.pattern_page(page, p, self.shoe_page)
                    sprites.append({"slot": slot, "pattern": p, "page": pg, "tile": t})
                frames.append({"frame": f, "page": page, "sprites": sprites})
            suits[name] = {
                "root_page": root, "pages": list(range(root, root + 4)), "sheet": f"sheets/{name}.png",
                "palettes": {"mario": self.rules["by_suit"][name]["mario"]["colours"],
                             "luigi": self.rules["by_suit"][name]["luigi"]["colours"]},
                "frames": frames,
            }
        used = self.referenced_tiles()
        atlases = []
        for page in self.pages:
            ref = used.get(page, set())
            free = [t for t in range(64) if t not in ref]
            blank = [t for t in free if not any(self.chr[(page * 64 + t) * 16:(page * 64 + t) * 16 + 16])]
            atlases.append({"page": f"0x{page:02X}", "file": f"atlases/atlas_{page:02x}.png", "tiles": 64,
                            "referenced": len(ref), "unreferenced": len(free), "unreferenced_blank": len(blank)})
        kuribo = {"page": f"0x{self.shoe_page:02X}", "file": f"atlases/kuribo_{self.shoe_page:02x}.png",
                  "tiles": [f"0x{t:02X}" for t in self.rep["kuribo"]["page_tiles"]]}
        return {
            "tool": f"gbox.smb3_sprites {VERSION}", "reader_version": READER_VERSION,
            "game": "Super Mario Bros. 3", "platform": "nes", "fps": FPS,
            "identity": self.ident, "source_sha256": self.source["sha256"],
            "sprite": {"mode": "8x16", "bits_per_pixel": 2, "slots": 6, "slot_grid": [3, 2],
                       "frame_pixels": [24, 32], "hidden": f"0x{inv.HIDDEN:02X}"},
            "sheet": {"cell": [24, 32], "grid": [SHEET_COLS, SHEET_ROWS], "frames": inv.FRAMES,
                      "index_meaning": "pixel index 0 = transparent, 1..3 = the suit palette colours; "
                                       "editing a pixel's index edits exactly one 2bpp CHR plane bit"},
            "shared_page": self.shoe_page,
            "palettes": {name: suits[name]["palettes"] for name in inv.POWERUPS},
            "suits": suits, "atlases": atlases + [kuribo], "roundtrip": self.verify_roundtrip(),
        }

    def export(self, work, progress=lambda pct, msg: None) -> list[Path]:
        work = Path(work)
        (work / "sheets").mkdir(parents=True, exist_ok=True)
        (work / "atlases").mkdir(parents=True, exist_ok=True)
        steps = list(inv.POWERUPS) + [f"page {p:02X}" for p in self.pages] + ["kuribo", "frame map", "overview"]
        for k, name in enumerate(inv.POWERUPS):
            progress(100 * k / len(steps), f"Mario: {name} sheet")
            (work / "sheets" / f"{name}.png").write_bytes(self.sheet_png(name))
        k = len(inv.POWERUPS)
        for page in self.pages:
            progress(100 * k / len(steps), f"page atlas {page:02X}")
            (work / "atlases" / f"atlas_{page:02x}.png").write_bytes(self.atlas_png(page))
            k += 1
        progress(100 * k / len(steps), "Kuribo page"); k += 1
        (work / "atlases" / f"kuribo_{self.shoe_page:02x}.png").write_bytes(
            self.kuribo_png(self.rep["kuribo"]["page_tiles"]))
        progress(100 * k / len(steps), "frame map"); k += 1
        fm = self.frame_map()
        (work / "frames.json").write_text(json.dumps(fm, indent=1))
        progress(100 * k / len(steps), "overview"); k += 1
        overview = ana.render_sheet(self.chr, self.tables, self.rules, self.shoe_page)
        (work / "overview.png").write_bytes(inv.png_bytes(*overview))
        return [work / "overview.png", work / "sheets", work / "atlases", work / "frames.json"]


# ------------------------------------------------------------------------------------------------ collection reader

def extract_run(ctx, game: dict, entry: dict, work) -> dict:
    """characters op=collect / extract: Mario's sprite sheets, atlases and frame map."""
    from .models import CatalogEntry
    from .tools import rom_path
    src = rom_path(CatalogEntry.model_validate(game), ctx.config)
    ex = SMB3Sprites(src)
    work = Path(work)
    prog = getattr(ctx, "progress", lambda p, m: None)
    files = ex.export(work, progress=lambda p, m: prog(20 + 0.7 * p, m))
    fm = json.loads((work / "frames.json").read_text())
    rt = fm["roundtrip"]
    pages = ", ".join(f"0x{p:02X}" for p in ex.pages)
    return {
        "files": files, "roles": {}, "kind": "sprites",
        "tool": f"gbox.smb3_sprites {VERSION}",
        "source_files": [f"{Path(src).name}: PRG bank 29 player tables, CHR pages {pages}, "
                         f"Kuribo page 0x{ex.shoe_page:02X}"],
        "notes": (f"81 frames x 7 power-ups as editable indexed 4-colour sheets, {len(ex.pages)} page atlases "
                  f"(every tile kept) and a slot->page/tile frame map. Luigi is Mario with a palette swap. "
                  f"CHR round-trip: {rt['checked']} referenced tiles re-encode byte-identical "
                  f"({'ok' if rt['byte_identical'] else 'MISMATCH'})."),
        "extra": {"picture": "2d", "smb3": {"reader": READER_VERSION, "frame_map": str(work / "frames.json"),
                                            "sheets": "sheets", "atlases": "atlases",
                                            "roundtrip": rt, "palettes": fm["palettes"]}},
    }


# ------------------------------------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Super Mario Bros. 3 player sprite extraction")
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ex = SMB3Sprites(a.src)
    files = ex.export(Path(a.out))
    fm = json.loads((Path(a.out) / "frames.json").read_text())
    print(json.dumps({"identity": ex.ident.get("revision"), "roundtrip": fm["roundtrip"],
                      "pages": len(ex.pages), "files": [str(f.relative_to(a.out)) for f in files]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
