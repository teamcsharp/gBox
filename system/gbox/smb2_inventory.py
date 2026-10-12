"""Super Mario Bros. 2 (USA) (NES) build identity and player-sprite inventory.

SMB2 USA is an MMC3 (iNES mapper 4) cartridge: 128 KB PRG ROM in 8 KB banks
(the last two banks are fixed at $C000-$FFFF) and 128 KB CHR ROM that the game
addresses in 1 KB units.  The four playable characters are 2D sprite
characters, not meshes.  Each character/size pair owns one 1 KB CHR page that
the NMI maps to the sprite pattern table through ``SpriteCHR1``:

* ``LoadCharacterCHRBanks`` (fixed bank): ``LDA CurrentCharacter / ASL A /
  ORA PlayerCurrentSize / TAY / LDA CHRBank_CharacterSize,Y / STA SpriteCHR1 /
  RTS``.  ``CurrentCharacter`` is 0 Mario, 1 Princess, 2 Toad, 3 Luigi and
  ``PlayerCurrentSize`` is 0 big, 1 small.
* ``CHRBank_CharacterSize``: eight distinct 1 KB CHR page numbers.
* The NMI CHR loop (``TYA / ORA #$80 / STA $8000 / LDA BackgroundCHR1,Y /
  STA $8001``) proves which MMC3 register (and PPU address) ``SpriteCHR1``
  feeds.
* ``CharacterTiles`` (fixed bank): 11 animation frames x 4 tile bytes, a 2x2
  grid of 8x16 sprites (``$FB`` = blank), then the Princess float body.  The
  per-frame and per-character eye-tile tables sit directly before it.
* ``CharacterPalette`` (switchable PRG): 4 x 4 sprite-palette bytes directly
  after ``StatOffsets`` and the four equal-size ``CharacterStats`` blocks.

Names follow the Xkeeper0/smb2 disassembly (which rebuilds PRG0 byte for
byte); every table is located in the owned ROM by structure and validated by
the code that reads it, not by hard-coded offsets.
``python -m gbox.smb2_inventory SRC --out m.json --png sheet.png`` writes the
manifest and a contact sheet of every frame for each character and size.
Originals are only read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zlib
from pathlib import Path

from .smb3_inventory import parse_ines, png_bytes, read_source, split, tile

GAME_ID = "768145c187bf6dd0"
TITLE = "Super Mario Bros. 2"
# sha256 of the owned HyperSpin "Super Mario Bros. 2 (USA).zip" (source_sha256)
OWNED_SOURCE_SHA256 = "2e345adccd0033683070b2c46b91d10a5c8d300797531aabcb01f297663a66aa"
PRG_BANK = 0x2000
CHR_PAGE = 0x400
BLANK = 0xFB
CHARACTERS = ("Mario", "Princess", "Toad", "Luigi")   # CurrentCharacter 0..3
SIZES = ("big", "small")                               # PlayerCurrentSize 0..1
FRAME_NAMES = ("walk1", "carry1", "walk2", "carry2", "duck", "duck_carry",
               "jump", "death", "lift", "throw", "climb")
# CharacterFrameEyeTiles (one per frame) + CharacterEyeTiles (Mario, Luigi,
# Toad, Princess) immediately precede CharacterTiles.
EYE_SIG = bytes((0x00, 0x00, 0x00, 0x00, 0xFB, 0xFB, 0x00, 0xFB, 0xFB, 0x00, 0xFB,
                 0xD5, 0xD9, 0xFB, 0xD7))
EYE_ORDER = ("Mario", "Luigi", "Toad", "Princess")

# No-Intro headerless identities (libretro-database metadat/no-intro NES dat).
KNOWN = {
    0x57AC67AF: {"name": "Super Mario Bros. 2 (USA)", "revision": "Rev 0 (PRG0)",
                 "md5": "ccd25b4fa7acddef38d75212ae0e5432",
                 "sha1": "43ac7c7aaf1846ead7b544302bb9131e4964fd32"},
    0xCA594ACE: {"name": "Super Mario Bros. 2 (USA) (Rev 1)", "revision": "Rev 1 (PRG1)",
                 "md5": "a64dcbaf95980145d2351850be735461",
                 "sha1": "ff5bcacf7417b4de1c49f9e54c2905d91391455b"},
}

# Other catalog entries with the same title; none is byte-identical by default.
RELATED_BUILDS = {
    "41f2194dd31fff96": "Super Mario Bros. 2 (USA) (Rev A), Phantom System collection: PRG1, "
                        "tables must be re-located, not copied",
    "baa0e1e576268abc": "Super Mario Bros. 2 (PlayChoice-10) MAME set: different hardware",
    "dd0028fe5e846f52": "Super Mario Bros. 2 (Japan) FDS: The Lost Levels, a different game",
}

# FCEUX default 2C02 palette, used only for the preview sheet.
NES_RGB = (
    0x747474, 0x24188C, 0x0000A8, 0x44009C, 0x8C0074, 0xA80010, 0xA40000, 0x7C0800,
    0x402C00, 0x004400, 0x005000, 0x003C14, 0x183C5C, 0x000000, 0x000000, 0x000000,
    0xBCBCBC, 0x0070EC, 0x2038EC, 0x8000F0, 0xBC00BC, 0xE40058, 0xD82800, 0xC84C0C,
    0x887000, 0x009400, 0x00A800, 0x009038, 0x008088, 0x000000, 0x000000, 0x000000,
    0xFCFCFC, 0x3CBCFC, 0x5C94FC, 0xCC88FC, 0xF478FC, 0xFC74B4, 0xFC7460, 0xFC9838,
    0xF0BC3C, 0x80D010, 0x4CDC48, 0x58F898, 0x00E8D8, 0x787878, 0x000000, 0x000000,
    0xFCFCFC, 0xA8E4FC, 0xC4D4FC, 0xD4C8FC, 0xFCC4FC, 0xFCC4D8, 0xFCBCB0, 0xFCD8A8,
    0xFCE4A0, 0xE0FCA0, 0xA8F0BC, 0xB0FCCC, 0x9CFCF0, 0xC4C4C4, 0x000000, 0x000000,
)

_ABS_READS = {0xAD: "LDA", 0xBD: "LDA,X", 0xB9: "LDA,Y", 0xAE: "LDX", 0xBE: "LDX,Y",
              0xAC: "LDY", 0xBC: "LDY,X"}


def _word(b: bytes, i: int) -> int:
    return b[i] | b[i + 1] << 8


def _fixed_range(prg: bytes) -> tuple[int, int]:
    """PRG offsets of the two fixed MMC3 banks (mode 0: $C000-$FFFF)."""
    return len(prg) - 2 * PRG_BANK, len(prg)


def cpu_addr(prg: bytes, off: int) -> int:
    lo, _ = _fixed_range(prg)
    if off >= lo:
        return 0xC000 + (off - lo)
    return 0x8000 + (off % (2 * PRG_BANK))


def fixed_offset(prg: bytes, cpu: int) -> int | None:
    if 0xC000 <= cpu <= 0xFFFF:
        return _fixed_range(prg)[0] + (cpu - 0xC000)
    return None


def identify(body: bytes) -> dict:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    out: dict = {"crc32": f"{crc:08x}", "md5": hashlib.md5(body).hexdigest(),
                 "sha1": hashlib.sha1(body).hexdigest(),
                 "sha256": hashlib.sha256(body).hexdigest()}
    k = KNOWN.get(crc)
    if k and k["md5"] == out["md5"] and k["sha1"] == out["sha1"]:
        out.update(match=True, name=k["name"], revision=k["revision"])
    else:
        out["match"] = False
    return out


def locate_chr_bank_select(prg: bytes) -> dict:
    """Find LoadCharacterCHRBanks and the CHRBank_CharacterSize table it reads."""
    lo, hi = _fixed_range(prg)
    hits = []
    for i in range(lo + 8, hi - 6):
        if prg[i] != 0xB9 or prg[i - 1] != 0xA8:          # TAY / LDA abs,Y
            continue
        if prg[i + 3] == 0x8D and prg[i + 6] == 0x60:      # STA abs / RTS
            sta = _word(prg, i + 4)
        elif prg[i + 3] == 0x85 and prg[i + 5] == 0x60:    # STA zp / RTS
            sta = prg[i + 4]
        else:
            continue
        table_cpu = _word(prg, i + 1)
        t = fixed_offset(prg, table_cpu)
        if t is None or t + 8 > hi:
            continue
        table = list(prg[t:t + 2 * len(CHARACTERS)])
        if len(set(table)) != 8 or max(table) >= 0x80:
            continue
        for ora_len, ora_op in ((3, 0x0D), (2, 0x05)):
            j = i - 1 - ora_len
            if prg[j] != ora_op or prg[j - 1] != 0x0A:     # ORA size / ASL A
                continue
            ora = _word(prg, j + 1) if ora_len == 3 else prg[j + 1]
            for lda_len, lda_op in ((3, 0xAD), (2, 0xA5)):
                m = j - 1 - lda_len
                if m < lo or prg[m] != lda_op:
                    continue
                lda = _word(prg, m + 1) if lda_len == 3 else prg[m + 1]
                hits.append({
                    "routine": {"prg_offset": m, "cpu": cpu_addr(prg, m)},
                    "table": {"prg_offset": t, "cpu": table_cpu},
                    "current_character_ram": lda, "player_size_ram": ora,
                    "sprite_chr1_ram": sta, "pages": table,
                })
    if len(hits) != 1:
        raise ValueError(f"LoadCharacterCHRBanks not uniquely located ({len(hits)} candidates)")
    return hits[0]


def locate_chr_update(prg: bytes) -> dict | None:
    """Find the MMC3 CHR register loop that copies the six CHR bank variables."""
    lo, hi = _fixed_range(prg)
    hits = []
    for i in range(lo, hi - 12):
        if (prg[i] == 0x98 and prg[i + 1] == 0x09 and prg[i + 3] == 0x8D
                and _word(prg, i + 4) == 0x8000 and prg[i + 6] == 0xB9
                and prg[i + 9] == 0x8D and _word(prg, i + 10) == 0x8001):
            hits.append({"prg_offset": i, "cpu": cpu_addr(prg, i),
                         "bank_select_or": prg[i + 2], "ram_base": _word(prg, i + 7)})
    return hits[0] if len(hits) == 1 else None


def sprite_page_mapping(banks: dict, update: dict | None) -> dict:
    """Which MMC3 register / PPU window SpriteCHR1 drives."""
    if update is None:
        return {"register": None, "ppu": None, "note": "MMC3 CHR loop not located"}
    reg = banks["sprite_chr1_ram"] - update["ram_base"]
    inverted = bool(update["bank_select_or"] & 0x80)
    if not 2 <= reg <= 5:
        return {"register": reg, "ppu": None, "note": "SpriteCHR1 is not a 1 KB register"}
    ppu = (reg - 2) * CHR_PAGE + (0 if inverted else 0x1000)
    return {"register": f"R{reg}", "ppu": ppu, "chr_a12_inversion": inverted,
            "note": "1 KB character page at the sprite pattern table"}


def locate_character_tiles(prg: bytes) -> dict:
    lo, hi = _fixed_range(prg)
    n = 4 * len(FRAME_NAMES)
    hits = []
    pos = prg.find(EYE_SIG, lo)
    while pos >= 0:
        t = pos + len(EYE_SIG)
        body = prg[t:t + n + 2]
        if len(body) == n + 2 and all(v == BLANK or (v % 2 == 0 and v < 0x40) for v in body[:n]):
            hits.append(pos)
        pos = prg.find(EYE_SIG, pos + 1)
    if len(hits) != 1:
        raise ValueError(f"CharacterTiles not uniquely located ({len(hits)} candidates)")
    eye = hits[0]
    t = eye + len(EYE_SIG)
    tc = cpu_addr(prg, t)
    xrefs = []
    for i in range(lo, hi - 2):
        if prg[i] in _ABS_READS:
            a = _word(prg, i + 1)
            if cpu_addr(prg, eye) <= a <= tc + n + 2:
                xrefs.append({"cpu": cpu_addr(prg, i), "op": _ABS_READS[prg[i]], "operand": a})
    return {
        "frame_eye_tiles": {"prg_offset": eye, "cpu": cpu_addr(prg, eye)},
        "eye_tiles": {"prg_offset": eye + 11, "cpu": cpu_addr(prg, eye + 11)},
        "character_tiles": {"prg_offset": t, "cpu": tc},
        "frames": {name: list(prg[t + 4 * k:t + 4 * k + 4]) for k, name in enumerate(FRAME_NAMES)},
        "frame_eye": dict(zip(FRAME_NAMES, prg[eye:eye + 11])),
        "eye": dict(zip(EYE_ORDER, prg[eye + 11:eye + 15])),
        "princess_float_body": list(prg[t + n:t + n + 2]),
        "xrefs": xrefs,
    }


def locate_character_palette(prg: bytes) -> dict:
    """StatOffsets = (Mario 0, Princess 3N, Toad N, Luigi 2N); palettes follow 4N bytes later."""
    hits = []
    for n in range(8, 64):
        sig = bytes((0, 3 * n, n, 2 * n))
        pos = prg.find(sig)
        while pos >= 0:
            pal = pos + 4 + 4 * n
            p = prg[pal:pal + 16]
            if len(p) == 16 and all(p[4 * c] == 0x0F for c in range(4)) and max(p) < 0x40:
                hits.append((pos, n, pal))
            pos = prg.find(sig, pos + 1)
    if len(hits) != 1:
        raise ValueError(f"CharacterPalette not uniquely located ({len(hits)} candidates)")
    so, n, pal = hits[0]
    return {
        "stat_offsets": {"prg_offset": so, "prg_bank": so // PRG_BANK, "cpu": cpu_addr(prg, so)},
        "stats_block_size": n,
        "character_palette": {"prg_offset": pal, "cpu": cpu_addr(prg, pal)},
        "palettes": {c: list(prg[pal + 4 * k:pal + 4 * k + 4]) for k, c in enumerate(CHARACTERS)},
    }


def player_inventory(chr_: bytes, banks: dict, tiles: dict, pal: dict) -> dict:
    out = {}
    for ci, name in enumerate(CHARACTERS):
        sizes = {}
        for si, size in enumerate(SIZES):
            page = banks["pages"][ci * 2 + si]
            data = chr_[page * CHR_PAGE:(page + 1) * CHR_PAGE]
            used: set[int] = set()
            frames = []
            for fname in FRAME_NAMES:
                sprites = []
                for slot, t in enumerate(tiles["frames"][fname]):
                    if t == BLANK:
                        sprites.append({"slot": slot, "tile": t, "blank": True})
                        continue
                    used.update((t, t + 1))
                    sprites.append({"slot": slot, "tile": t, "page": page})
                frames.append({"frame": fname, "sprites": sprites})
            nonblank = {i for i in range(64) if any(data[i * 16:(i + 1) * 16])}
            sizes[size] = {
                "chr_page": page, "chr_offset": page * CHR_PAGE,
                "page_sha256": hashlib.sha256(data).hexdigest(),
                "tiles_referenced": sorted(used),
                "tiles_nonblank": len(nonblank),
                "unreferenced_nonblank_tiles": sorted(nonblank - used),
                "frames": frames,
            }
        out[name] = {"current_character": ci, "palette": pal["palettes"][name],
                     "eye_tile": tiles["eye"][name], "sizes": sizes}
    return out


def render_sheet(chr_: bytes, player: dict) -> tuple[int, int, bytes]:
    """RGBA contact sheet: one row per character/size, one 16x32 cell per frame.

    Preview only: a right-hand sprite repeating its row's left tile is drawn
    mirrored (duck/death poses); the analysis stage confirms the attributes."""
    cw, ch, pad = 16, 32, 2
    W, H = len(FRAME_NAMES) * (cw + pad), len(CHARACTERS) * len(SIZES) * (ch + pad)
    px = bytearray(W * H * 4)
    row = 0
    for c in player.values():
        rgb = [0] + [NES_RGB[v & 0x3F] for v in c["palette"][1:4]]  # index 0 is transparent
        for s in c["sizes"].values():
            for fi, fr in enumerate(s["frames"]):
                ox, oy = fi * (cw + pad), row * (ch + pad)
                pats = [sp["tile"] for sp in fr["sprites"]]
                for sp in fr["sprites"]:
                    if sp.get("blank"):
                        continue
                    slot = sp["slot"]
                    mirror = slot % 2 == 1 and pats[slot - 1] == sp["tile"]
                    sx, sy = ox + (slot % 2) * 8, oy + (slot // 2) * 16
                    base = sp["page"] * 64 + sp["tile"]
                    for half in (0, 1):
                        for y, line in enumerate(tile(chr_, base + half)):
                            for x, v in enumerate(line):
                                if v:
                                    xx = 7 - x if mirror else x
                                    o = ((sy + half * 8 + y) * W + sx + xx) * 4
                                    col = rgb[v]
                                    px[o:o + 4] = bytes((col >> 16, (col >> 8) & 255, col & 255, 255))
            row += 1
    return W, H, bytes(px)


def inventory(src) -> dict:
    data, source = read_source(src)
    hdr = parse_ines(data)
    prg, chr_ = split(data, hdr)
    ident = identify(prg + chr_)
    banks = locate_chr_bank_select(prg)
    update = locate_chr_update(prg)
    tiles = locate_character_tiles(prg)
    pal = locate_character_palette(prg)
    player = player_inventory(chr_, banks, tiles, pal)
    for c in player.values():
        for s in c["sizes"].values():
            s["rom_offset"] = hdr["chr_offset"] + s["chr_offset"]
    return {
        "game_id": GAME_ID, "game": TITLE, "platform": "nes",
        "platform_check": {"ines": True, "mapper": hdr["mapper"], "no_intro_match": ident["match"],
                           "note": "catalog system 'Nintendo Classic Mini' is the HyperSpin "
                                   "emulator label; the file is a plain iNES MMC3 cartridge"},
        "source": source, "ines": hdr, "identity": ident,
        "prg_bank_sha256": [hashlib.sha256(prg[i:i + PRG_BANK]).hexdigest()
                            for i in range(0, len(prg), PRG_BANK)],
        "chr_page_count": len(chr_) // CHR_PAGE,
        "launch": {"core": "mesen (catalog core) or any MMC3-capable NES core", "bios": None,
                   "save": "battery" if hdr["battery"] else "none",
                   "notes": "cartridge image only; no BIOS, disk system or patches required"},
        "chr_banking": {"load_character_chr_banks": banks, "chr_update_loop": update,
                        "sprite_page": sprite_page_mapping(banks, update)},
        "tables": {k: v for k, v in tiles.items() if k not in ("frames", "frame_eye", "eye")},
        "palette_tables": {k: v for k, v in pal.items() if k != "palettes"},
        "frames": tiles["frames"],
        "player": player,
        "roster": [{
            "character": name, "slot": "player", "current_character": c["current_character"],
            "pages": {size: s["chr_page"] for size, s in c["sizes"].items()},
            "palette": bytes(c["palette"]).hex(),
        } for name, c in player.items()],
        "related_builds": RELATED_BUILDS,
        "constraints": {
            "sprite_mode": "8x16 (CharacterTiles holds even top-tile indices)",
            "tile_bpp": 2, "colours_per_palette": 3, "page_size": CHR_PAGE, "tiles_per_page": 64,
            "frame_layout": "2x2 sprites of 8x16 (16x32 cell), $FB = blank",
            "frames": len(FRAME_NAMES),
            "note": "a replacement must fit each character/size 1 KB page and the shared "
                    "CharacterTiles frame table; a 3D donor must be rendered to 2bpp tiles",
        },
        "open_questions": [
            "small-size (PlayerCurrentSize=1) draw offsets and which rows are shown",
            "eye overlay tiles $D5/$D9/$D7 are odd (PPU $1000 table): resolve their page",
            "Princess float body tiles are >= $40, outside the character page",
            "right-sprite mirroring rule in the player render routine",
        ],
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
        _, chr_ = split(data, parse_ines(data))
        Path(a.png).write_bytes(png_bytes(*render_sheet(chr_, m["player"])))
    text = json.dumps(m, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({"identity": m["identity"], "mapper": m["ines"]["mapper_name"],
                      "sprite_page": m["chr_banking"]["sprite_page"],
                      "roster": m["roster"]}, default=str))
    return 0


if __name__ == "__main__":
    main()
