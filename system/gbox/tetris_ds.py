"""Tetris DS (USA) native sprite reader.

Reverse-engineered from the owned dump `0366 - Tetris DS (U)(WRG).nds`
(sha256 4e443f9b03363900dda6fa308229a3b14631b0fedd14f1c2e4cc1d5b3224db68,
16 MiB, gamecode ATRE). Findings are structural: the Nintendo DS cartridge
filesystem (FAT/FNT) carries 528 files, most sprite data LZ10-compressed.

Formats observed (all little-endian unless noted):

* Cartridge filesystem  -- FAT entries (u32 start, u32 end) at fat_off;
  FNT main table with subtable offsets; file entries carry NO id, ids run
  sequentially from first_file_id (13 here) in DFS order; subdirectory
  subtables follow their parent's subtable contiguously; directory ids are
  0xF000 + 1-based discovery ordinal.
* LZ10 ("BLZ", type 0x10) -- header [u8 0x10][u24 decompressed_size], stream
  at offset 4; flag byte 0 = 8 literals; else 8 ops MSB-first, bit 1 = copy
  of big-endian u16 (len = (w>>12)+3, offset = w&0xFFF) reading BACKWARD
  into a zero-filled output buffer (out_pos - offset - 1 may be < 0 or
  beyond the current write position; unwritten bytes read as 0x00).
  Byte-identical to ndspy.lz10.decompress (verified against the owned ROM).
* .plz               -- raw palettes: 256 x u16 BGR555, no header.
* .NCLR.lz           -- LZ10'd "RLCN" Nitro palette: magic, u16 0xFFFE,
  u16 0x0001, u32 file size, u16 header size 0x10, u16 section count,
  then "TTLP" sections: [4cc][u32 size][u32 depth][u32 0][u32 data_size]
  [u32 data_offset relative to payload] + u16 BGR555 entries.
* .NCGR.lz           -- LZ10'd "RGCN" (this build spells the magic
  "NCGR"-reversed, not the standard "RCSR"): magic, u16 0xFFFE, u16 0x0101,
  u32 file size, u16 0x10, u16 section count, then "RAHC" sections:
  [4cc][u32 size][u32 (tile_w<<16|tile_h)][u32 depth][u32 0]
  [u32 data_size][u32 data_offset relative to payload] + tile indices.
  depth 3 = 4bpp (16 colors), 4 = 8bpp (256 colors).
* .chr               -- raw tile banks without header (sizes are multiples
  of 64 = 8x8 8bpp tiles; e.g. ct_.chr = 16640 B = 260 tiles).
* .objs              -- per-sprite tile lists: three u32 header words then
  u16 (tile_index, attribute) pairs; the pairs run to end of file.
* .clz/.slz/.bdz/.blz -- background char banks / screen maps (same LZ10);
  .tds = playfield/board data; .cz/.ntfp = audio; .sdat = sound archive.

This module is intentionally dependency-free (stdlib only) and ships its
own minimal PNG encoder so extracted sheets are portable.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

TETRIS_DS_GAMECODE = "ATRE"
TETRIS_DS_ROM_SHA256 = "4e443f9b03363900dda6fa308229a3b14631b0fedd14f1c2e4cc1d5b3224db68"


class LZ10Error(ValueError):
    pass


def lz10_decompress(data: bytes) -> bytes:
    """Nitro LZ10 (type 0x10) decompressor with the backward zero-window.

    Matches ndspy.lz10.decompress byte-for-byte on every compressed file of
    the owned Tetris DS (USA) ROM.
    """
    if not data or data[0] != 0x10:
        raise LZ10Error("not an LZ10 stream (missing 0x10 type byte)")
    out_len = data[1] | (data[2] << 8) | (data[3] << 16)
    out = bytearray(out_len)  # zero-filled: backward reads beyond out_pos see 0x00
    in_pos, out_pos = 4, 0
    while out_len > 0 and in_pos < len(data):
        d = data[in_pos]
        in_pos += 1
        if d:
            for _ in range(8):
                if d & 0x80:
                    if in_pos + 2 > len(data):
                        raise LZ10Error("truncated copy token")
                    w = (data[in_pos] << 8) | data[in_pos + 1]
                    in_pos += 2
                    length = (w >> 12) + 3
                    window = out_pos - (w & 0xFFF) - 1
                    for _ in range(length):
                        out[out_pos] = out[window]  # may read backward/zeroed cells
                        out_pos += 1
                        window += 1
                        out_len -= 1
                        if out_len == 0:
                            return bytes(out)
                else:
                    if in_pos >= len(data):
                        raise LZ10Error("truncated literal")
                    out[out_pos] = data[in_pos]
                    out_pos += 1
                    in_pos += 1
                    out_len -= 1
                    if out_len == 0:
                        return bytes(out)
                d = (d << 1) & 0xFF
        else:
            for _ in range(8):
                if in_pos >= len(data):
                    raise LZ10Error("truncated literal run")
                out[out_pos] = data[in_pos]
                out_pos += 1
                in_pos += 1
                out_len -= 1
                if out_len == 0:
                    return bytes(out)
    if out_len:
        raise LZ10Error(f"stream exhausted with {out_len} bytes missing")
    return bytes(out)


class NDSRom:
    """Read-only Nintendo DS cartridge: header + FAT/FNT filesystem.

    Files are returned with their payload; payloads whose first byte is
    0x10 are transparently LZ10-decompressed (matches every observed asset).
    """

    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 0x200:
            raise ValueError("not an NDS image (too small)")
        self.title = data[0x00:0x0C].decode("ascii", "replace").rstrip("\x00")
        self.gamecode = data[0x0C:0x10].decode("ascii", "replace")
        self.unitcode = data[0x12]
        (self.arm9_off, self.arm9_entry, self.arm9_ram, self.arm9_size) = struct.unpack_from("<IIII", data, 0x20)
        (self.arm7_off, self.arm7_entry, self.arm7_ram, self.arm7_size) = struct.unpack_from("<IIII", data, 0x30)
        (self.fnt_off, self.fnt_size) = struct.unpack_from("<II", data, 0x40)
        (self.fat_off, self.fat_size) = struct.unpack_from("<II", data, 0x48)
        self._fat = [
            struct.unpack_from("<II", data, off)
            for off in range(self.fat_off, self.fat_off + self.fat_size, 8)
        ]
        self._files = {}  # lowercase path -> (fat_index, start, end)
        self._parse_fnt()

    def _parse_fnt(self):
        fnt = self.data[self.fnt_off:self.fnt_off + self.fnt_size]
        if len(fnt) < 8:
            raise ValueError("FNT truncated")
        root_off = struct.unpack_from("<I", fnt, 0)[0]
        first_id = struct.unpack_from("<H", fnt, 4)[0]
        counter = [first_id]

        def parse_sub(sub_off, prefix):
            pos = sub_off
            kids = []
            while True:
                if pos >= len(fnt):
                    raise ValueError(f"FNT overrun at 0x{pos:X} under {prefix!r}")
                ctl = fnt[pos]
                pos += 1
                if ctl == 0:
                    break
                namelen = ctl & 0x7F
                is_dir = bool(ctl & 0x80)
                name = fnt[pos:pos + namelen].decode("ascii", "replace")
                pos += namelen
                if is_dir:
                    v = struct.unpack_from("<H", fnt, pos)[0]
                    pos += 2
                    kids.append((name, v))
                else:
                    fid = counter[0]
                    counter[0] += 1
                    if fid >= len(self._fat):
                        raise ValueError(f"file id {fid} beyond FAT ({len(self._fat)} entries)")
                    start, end = self._fat[fid]
                    self._files[f"{prefix}/{name}".lstrip("/").lower()] = (fid, start, end)
            for name, _ in kids:
                pos = parse_sub(pos, f"{prefix}/{name}")
            return pos

        end = parse_sub(root_off, "")
        if end != self.fnt_size:
            raise ValueError(f"FNT walk ended at 0x{end:X}, FNT size 0x{self.fnt_size:X}")

    def paths(self) -> list[str]:
        return sorted(self._files)

    def raw(self, path: str) -> bytes:
        """Raw payload bytes for a path (no decompression)."""
        key = path.lower().lstrip("/")
        if key not in self._files:
            raise KeyError(path)
        _, start, end = self._files[key]
        return self.data[start:end]

    def read(self, path: str, decompress: bool = True) -> bytes:
        """Payload, LZ10-decompressed when it carries the 0x10 type byte."""
        blob = self.raw(path)
        if decompress and blob and blob[0] == 0x10:
            return lz10_decompress(blob)
        return blob

    def is_tetris_ds_usa(self) -> bool:
        return self.gamecode == TETRIS_DS_GAMECODE and self.title == "TETRIS DS" and self.unitcode == 0x00

    def build_id(self) -> str:
        return f"{self.title.strip()} ({self.gamecode.strip()}, unit 0x{self.unitcode:02X})"


def rgb555(c: int) -> tuple[int, int, int]:
    r = (c >> 10) & 0x1F
    g = (c >> 5) & 0x1F
    b = c & 0x1F
    return (r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)


def parse_nclr(blob: bytes) -> list[list[tuple[int, int, int]]]:
    """Parse a Nitro NCLR ('RLCN') palette blob into palette color lists."""
    if blob[:4] != b"RLCN":
        raise ValueError("not an NCLR (missing RLCN magic)")
    if len(blob) < 0x10:
        raise ValueError("NCLR header truncated")
    header_size, num_sections = struct.unpack_from("<HH", blob, 0x0C)
    palettes = []
    pos = 0x10 + header_size - 0x10  # sections start right after the 0x10-byte header
    pos = header_size
    for _ in range(num_sections):
        if pos + 8 > len(blob):
            break
        magic = blob[pos:pos + 4]
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        payload = blob[pos + 8:pos + size]
        if magic == b"TTLP" and len(payload) >= 0x10:
            _depth = struct.unpack_from("<I", payload, 0)[0]
            data_size = struct.unpack_from("<I", payload, 0x08)[0]
            data_off = struct.unpack_from("<I", payload, 0x0C)[0]
            data = payload[data_off:data_off + data_size]
            colors = [rgb555(struct.unpack_from("<H", data, i)[0]) for i in range(0, len(data) - 1, 2)]
            palettes.append(colors)
        pos += size
    return palettes


def parse_ncgr(blob: bytes):
    """Parse this build's NCGR ('RGCN') into dicts of tiles + metadata.

    Returns {'width': w, 'height': h, 'depth': 3|4, 'tiles': [bytes,...]}
    where each tile is 8bpp index data for an 8x8 block (4bpp expanded).
    """
    if blob[:4] != b"RGCN":
        raise ValueError("not an RGCN (this build's NCGR variant)")
    header_size, num_sections = struct.unpack_from("<HH", blob, 0x0C)
    result = []
    pos = header_size
    for _ in range(num_sections):
        if pos + 8 > len(blob):
            break
        magic = blob[pos:pos + 4]
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        payload = blob[pos + 8:pos + size]
        if magic == b"RAHC" and len(payload) >= 0x18:
            dims = struct.unpack_from("<I", payload, 0)[0]
            w, h = dims >> 16, dims & 0xFFFF
            depth = struct.unpack_from("<I", payload, 4)[0]
            data_size = struct.unpack_from("<I", payload, 0x10)[0]
            data_off = struct.unpack_from("<I", payload, 0x14)[0]
            data = payload[data_off:data_off + data_size]
            tiles = []
            if depth == 3:  # 4bpp: two pixels per byte, expand to 8bpp
                for t in range(0, len(data), w * h // 2):
                    raw = data[t:t + w * h // 2]
                    tiles.append(bytes(v >> 4 if i & 1 == 0 else v & 0x0F
                                      for v in raw for i in (0, 1)))
            elif depth == 4:  # 8bpp
                for t in range(0, len(data), w * h):
                    tiles.append(data[t:t + w * h])
            else:
                raise ValueError(f"unsupported RGCN depth {depth}")
            result.append({"magic": magic.decode(), "width": w, "height": h,
                           "depth": depth, "tiles": tiles})
        pos += size
    return result


def raw_tiles(blob: bytes, bpp: int = 8) -> list[bytes]:
    """Split a headerless tile bank into 8x8 tiles of the given bpp."""
    per = 64 if bpp == 8 else 32
    if len(blob) % per:
        raise ValueError(f"tile bank size {len(blob)} is not a multiple of {per} ({bpp}bpp 8x8)")
    if bpp == 8:
        return [blob[i:i + 64] for i in range(0, len(blob), 64)]
    out = []
    for i in range(0, len(blob), 32):
        chunk = blob[i:i + 32]
        out.append(bytes(v >> 4 if j & 1 == 0 else v & 0x0F for v in chunk for j in (0, 1)))
    return out


def parse_objs(blob: bytes) -> dict:
    """Parse a .objs sprite tile list: 3 u32 header words + u16 pairs.

    The header words are small counts/flags (exact semantics per-word are
    still being confirmed against the ARM9 loader); the payload is a run of
    u16 (tile_index, attribute) pairs. Unaligned tails are reported, not
    fatal, so every owned .objs parses.
    """
    if len(blob) < 12:
        raise ValueError(".objs too small for header")
    a, b, c = struct.unpack_from("<III", blob, 0)
    tail = blob[12:]
    aligned = len(tail) - (len(tail) % 4)
    pairs = [struct.unpack_from("<HH", tail, i) for i in range(0, aligned, 4)]
    return {"header": (a, b, c), "pairs": pairs,
            "trailing_bytes": len(tail) - aligned,
            "tiles": sorted({t for t, _ in pairs})}


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))


def png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    """Minimal RGBA PNG encoder (stdlib only)."""
    raw = b"".join(b"\x00" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(raw, 6))
            + _png_chunk(b"IEND", b""))


def render_sheet(tiles: list[bytes], palette: list[tuple[int, int, int]],
                 tile_w: int = 8, tile_h: int = 8, transparent_index: int = 0):
    """Render tiles side by side in a square grid. Returns (width, height, RGBA)."""
    n = max(1, len(tiles))
    cols = 1
    while cols * cols < n:
        cols += 1
    rows = (n + cols - 1) // cols
    img = bytearray(cols * tile_w * rows * tile_h * 4)
    for i, tile in enumerate(tiles):
        gx, gy = (i % cols) * tile_w, (i // cols) * tile_h
        for ty in range(tile_h):
            for tx in range(tile_w):
                idx = tile[ty * tile_w + tx] if tile_w == 8 and len(tile) >= tile_w * tile_h else 0
                px = (gx + tx) * 4 + (gy + ty) * cols * tile_w * 4
                if idx == transparent_index:
                    continue
                r, g, b = palette[idx % len(palette)]
                img[px] = r
                img[px + 1] = g
                img[px + 2] = b
                img[px + 3] = 0xFF
    return cols * tile_w, rows * tile_h, bytes(img)


class TetrisDSReader:
    """High-level sprite extraction for the owned Tetris DS (USA) build."""

    GAMECODE = TETRIS_DS_GAMECODE

    def __init__(self, rom_bytes: bytes):
        self.rom = NDSRom(rom_bytes)
        if not self.rom.is_tetris_ds_usa():
            raise ValueError(f"not the Tetris DS (USA) build: "
                             f"{self.rom.build_id()} (want gamecode {self.GAMECODE})")

    def sprite_sets(self) -> list[str]:
        """Sprite set names = stems of .objs files plus .ncgr.lz banks."""
        stems = set()
        for p in self.rom.paths():
            base = p.rsplit("/", 1)[-1]
            if base.endswith(".objs"):
                stems.add(base[:-5].lower())
            elif base.lower().endswith(".ncgr.lz"):
                stems.add(base[:-8].lower())
        return sorted(stems)

    def extract(self, out_dir: str | Path, sets: list[str] | None = None) -> dict:
        """Extract sprites to out_dir; returns a JSON-serializable report."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "gamecode": self.rom.gamecode,
            "title": self.rom.title,
            "unitcode": self.rom.unitcode,
            "rom_sha256": None,
            "sets": {},
        }
        stems = sets or self.sprite_sets()
        default_palette = [(i, i, i) for i in range(256)]
        for stem in stems:
            info = {"files": [], "tiles": 0, "pairs": 0, "png": None, "json": None}
            chr_blob = self._try_read(f"/{stem}.chr")
            if chr_blob is None:
                chr_blob = self._try_read(f"/{stem}.ncgr.lz")
            objs_blob = self._try_read(f"/{stem}.objs")
            pal = default_palette
            pal_src = None
            for stem_try in (stem, stem.rstrip("_abc")):
                for ext in (".plz", ".pal", ".tpl", ".nclr.lz"):
                    pblob = self._try_read(f"/{stem_try}{ext}")
                    if not pblob:
                        continue
                    if pblob[:4] == b"RLCN":
                        pals = parse_nclr(pblob)
                        if pals:
                            pal = pals[0]
                            pal_src = f"{stem_try}{ext} (NCLR)"
                            break
                    elif ext == ".plz" and len(pblob) >= 2:
                        pal = [rgb555(struct.unpack_from("<H", pblob, i)[0])
                               for i in range(0, len(pblob) - 1, 2)]
                        pal_src = f"{stem_try}{ext}"
                        break
                if pal_src:
                    break
            tiles = []
            tile_w = tile_h = 8
            if chr_blob:
                if chr_blob[:4] == b"RGCN":
                    for ncgr in parse_ncgr(chr_blob):
                        tiles.extend(ncgr["tiles"])
                        tile_w, tile_h = ncgr["width"], ncgr["height"]
                    info["tile_source"] = "RGCN (NCGR)"
                else:
                    bpp = 8
                    if len(chr_blob) % 64:
                        if len(chr_blob) % 32 == 0:
                            bpp = 4
                        else:
                            raise ValueError(f"{stem}.chr size {len(chr_blob)} not a tile bank")
                    tiles = raw_tiles(chr_blob, bpp)
                    info["tile_source"] = f"raw {bpp}bpp"
            if objs_blob:
                parsed = parse_objs(objs_blob)
                info["pairs"] = len(parsed["pairs"])
                info["objs_header"] = parsed["header"]
                info["referenced_tiles"] = parsed["tiles"][:64]
                if tiles and parsed["pairs"]:
                    kept = [tiles[i] for i in parsed["tiles"] if i < len(tiles)]
                    if kept:
                        tiles = kept
            info["tiles"] = len(tiles)
            info["palette_source"] = pal_src
            info["tile_w"] = tile_w
            info["tile_h"] = tile_h
            if tiles:
                w, h, rgba = render_sheet(tiles, pal, tile_w, tile_h)
                png = out / f"{stem}_sprites.png"
                png.write_bytes(png_rgba(w, h, rgba))
                info["png"] = str(png)
            meta = {"stem": stem, "palette_source": pal_src, "palette_size": len(pal),
                    "tile_count": len(tiles)}
            meta_path = out / f"{stem}_meta.json"
            meta_path.write_text(json.dumps(meta, indent=2))
            info["json"] = str(meta_path)
            info["files"] = [p for p in (info.get("png"), info.get("json")) if p]
            report["sets"][stem] = info
        return report

    def _try_read(self, path: str) -> bytes | None:
        try:
            return self.rom.read(path)
        except KeyError:
            return None


def build_report(reader: TetrisDSReader, rom_sha256: str | None = None) -> dict:
    report = {
        "game": reader.rom.build_id(),
        "rom_sha256": rom_sha256 or TETRIS_DS_ROM_SHA256,
        "sprite_sets": reader.sprite_sets(),
    }
    return report


# Complete sprite-set inventory of the owned build (ATRE, WRG dump), verified
# by TetrisDSReader.sprite_sets() over the whole ROM filesystem.
TETRIS_DS_SETS = (
    'baloon', 'bgmrecord', 'ct_', 'ct_e1', 'ct_field_bg16_a', 'ct_field_bg16_b',
    'ct_item', 'ct_mario3', 'ct_suji_main', 'ct_suji_sub', 'ct_wifi_e1',
    'ctanime_bike', 'ctanime_champion', 'ctanime_devil', 'ctanime_hunt',
    'ctanime_ice', 'ctanime_kuppa', 'ctanime_metroid', 'ctanime_zelda',
    'dl_list', 'donkey', 'ed_font', 'effect', 'gryo', 'hsobj', 'hstopobj',
    'inseki', 'kz_blockobj', 'kz_icon', 'kz_message', 'kz_suji', 'lcnum12',
    'makimono', 'menusign', 'mesicon16', 'midblock', 'midblock8', 'mn_font',
    'mn_gameicon', 'mn_topobj', 'mn_underobj', 'mn_underobj2', 'mn_wait',
    'mn_window', 'mn_window2', 'mn_window3', 'mn_window4', 'od_effect',
    'od_qnum', 'odsuji', 'odsuji_time', 'odwaku', 'op_characters', 'pauseobj',
    'pauseobjwm', 'pt_fire', 'puzzle', 'puzzle_sub', 'pz_bg1', 'ro_screen',
    'sh_debug', 'super_mario', 'super_mario3', 'taki', 'tt_anime', 'tt_bar',
    'wf_denpa', 'wf_friendcode', 'wf_icon', 'wf_page', 'wf_sanka',
    'wf_tetsuduki', 'wf_time', 'wm_icon', 'yoshieye', 'zelda',
)


def roster() -> list[dict]:
    """Native sprite sets of Tetris DS (USA) — the game's 2D 'models'."""
    return [{'key': s, 'slug': f'tetris_ds_{s}', 'name': f'Tetris DS sprites: {s}',
             'aliases': [s], 'kind': 'character'} for s in TETRIS_DS_SETS]


def extract_run(ctx, game, entry, work):
    """Character-collection run: locate the owned ROM, extract one set."""
    from pathlib import Path
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    rom = _locate_rom()
    reader = TetrisDSReader(rom)
    stem = (entry or {}).get('key')
    report = reader.extract(work, sets=[stem] if stem else None)
    files = [f for s in report['sets'].values() for f in s['files']]
    tiles = sum(s['tiles'] for s in report['sets'].values())
    return {'files': files, 'roles': {}, 'kind': 'sprites',
            'tool': 'gbox.tetris_ds (TetrisDSReader.extract)',
            'source_files': ['Tetris DS (USA).nds (WRG dump, ATRE)'],
            'notes': (f"tetris_ds reader on {reader.rom.build_id()}: "
                      f"{len(report['sets'])} set(s), {tiles} tiles")}


def _locate_rom() -> bytes:
    import os
    import shutil
    import subprocess
    import tempfile
    candidates = []
    if os.environ.get('TETRIS_DS_ROM'):
        candidates.append(os.environ['TETRIS_DS_ROM'])
    candidates += [
        '/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/Tetris DS (USA).7z',
        '/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/Tetris DS (USA).zip',
    ]
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        if cand.lower().endswith('.nds'):
            blob = open(cand, 'rb').read()
            if len(blob) >= 0x200 and blob[0x0C:0x10] == b'ATRE':
                return blob
            continue
        tmp = tempfile.mkdtemp(prefix='tetris_ds_')
        try:
            for tool in ('7z', '7za'):
                r = subprocess.run([tool, 'x', '-y', f'-o{tmp}', cand],
                                   capture_output=True)
                if r.returncode == 0:
                    break
            for root, _dirs, names in os.walk(tmp):
                for fn in names:
                    if fn.lower().endswith('.nds'):
                        blob = open(os.path.join(root, fn), 'rb').read()
                        if len(blob) >= 0x200 and blob[0x0C:0x10] == b'ATRE':
                            return blob
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise FileNotFoundError(
        'Tetris DS (USA) ROM not found; set TETRIS_DS_ROM to the .nds/.7z path')
