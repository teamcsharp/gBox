"""Super Mario Bros. 3 (NES) player-sprite code analysis for the owned Rev 0 ROM.

This is a scripted 6502 disassembly (capstone MOS65XX) of the owned image.  It
ties the player tables found by ``gbox.smb3_inventory`` to the code that reads
them.  Addresses come from the Rev 0 / PRG0 bytes; the captainsouthbird
disassembly (Rev 1) supplies names only.

* ``PT2_Full_CHRROM_Switch`` (fixed bank 31) copies ``PatTable_BankSel``
  ($0719-$071E) to MMC3 R0..R5 with command ``$40|n``.  That means PRG mode 1
  ($8000 = bank 30, $A000 = R7, $C000 = R6, $E000 = bank 31) and CHR mode 0
  (R2..R5 = 1 KB windows at PPU $1000/$1400/$1800/$1C00).
* ``Player_Draw`` (bank 29 at $C000) stores ``PUpRootPage[suit] +
  FramePageOff[frame]`` to ``PatTable_BankSel+2``, so MMC3 R2 holds the 1 KB
  player page at PPU $1000.
* The grow animation stores that byte again with hard-coded pages ($54|n on
  even steps, $44|n on odd steps).
* ``Level_SetPlayerPUpPal`` (bank 8 at $A000) uploads 3 colours from
  ``PowerUp_Palettes`` to PPU $3F11-$3F13 (sprite palette 0).  Small, Big and
  Leaf take ``Player_Current`` (Mario or Luigi); the other suits ignore it.
* Kuribo's-shoe frames use patterns $A9/$AB/$AD (PPU $1A80-$1ADF), which is
  MMC3 R4 (``PatTable_BankSel+4``).  The object loader stores
  ``ObjectGroup_PatTableSel`` there, and ``OBJ_GOOMBAINSHOE`` requests page $0B.

``python -m gbox.smb3_analysis SRC --out analysis.json --png sheet.png``
writes the report and a palette-correct sheet (7 suits x Mario/Luigi, all 81
frames).  The source is only read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import smb3_inventory as inv

BANK = inv.PRG_BANK
FIXED = {30: 0x8000, 31: 0xE000}   # fixed windows in PRG mode 1
SWAP_C000 = 0xC000                  # R6 (banks 0, 29, ...)
SWAP_A000 = 0xA000                  # R7 (bank 8, object banks 1-5)
BRANCHES = {"bcc", "bcs", "beq", "bmi", "bne", "bpl", "bvc", "bvs"}
PLAYERS = ("mario", "luigi")

# Names from the Rev 1 disassembly (smb3.asm).  Each value is checked against
# the owned ROM's code or data below.
OBJ_GOOMBAINSHOE = 0x2B
OBJECTS_PER_BANK = 0x24            # object banks 1..5 hold $24 objects each
OBJ_PATTABLESEL = 0xA144           # ObjectGroup_PatTableSel in every object bank
# Walk base frames: PF_WALKSMALL_BASE, PF_WALKBIG_BASE, PF_WALKSPECIAL_BASE.
PROBE_FRAMES = {"small": 0x3E, "big": 0x0C, "fire": 0x0C, "leaf": 0x00,
                "frog": 0x00, "tanooki": 0x00, "hammer": 0x0C}
KURIBO_FRAMES = {"small": 0x43, "big": 0x18}   # PF_KURIBO_SMALL / PF_KURIBO_BIG

# Approximate NTSC 2C02 palette (FCEUX default), 64 RGB triplets.
NES_RGB = bytes.fromhex(
    "74747424188c0000a844009c8c0074a80010a400007c0800402c00004400005000003c14183c5c000000000000000000"
    "bcbcbc0070ec2038ec8000f0bc00bce40058d82800c84c0c88700000940000a800009038008088000000000000000000"
    "fcfcfc3cbcfc5c94fccc88fcf478fcfc74b4fc7460fc9838f0bc3c80d0104cdc4858f89800e8d8787878000000000000"
    "fcfcfca8e4fcc4d4fcd4c8fcfcc4fcfcc4d8fcbcb0fcd8a8fce4a0e0fca0a8f0bcb0fccc9cfcf0c4c4c4000000000000")
assert len(NES_RGB) == 192
SKY = (92, 148, 252)               # NES $22, used as the sheet background


@dataclass(frozen=True)
class Ins:
    cpu: int
    mnem: str
    ops: str
    raw: bytes
    value: int | None
    mode: str

    def text(self) -> str:
        return f"${self.cpu:04X}  {self.raw.hex():<6}  {self.mnem.upper()} {self.ops}".rstrip()


def _engine():
    import capstone  # capstone 5 ships the MOS65XX architecture
    return capstone.Cs(capstone.CS_ARCH_MOS65XX, capstone.CS_MODE_MOS65XX_6502)


def _bank(prg: bytes, b: int) -> bytes:
    return prg[b * BANK:(b + 1) * BANK]


def _find(buf: bytes, pat: bytes) -> list[int]:
    out, i = [], buf.find(pat)
    while i >= 0:
        out.append(i)
        i = buf.find(pat, i + 1)
    return out


def disasm(prg: bytes, bank: int, base: int, cpu: int, count: int) -> list[Ins]:
    """Decode ``count`` instructions of ``bank`` mapped at ``base`` from ``cpu``."""
    off = cpu - base
    if not 0 <= off < BANK:
        raise ValueError(f"${cpu:04X} is outside bank {bank} at ${base:04X}")
    out = []
    for i in _engine().disasm(_bank(prg, bank)[off:], cpu):
        raw, m, ops = bytes(i.bytes), i.mnemonic.lower(), i.op_str.strip()
        if m in BRANCHES:
            d = raw[1] - 0x100 if raw[1] & 0x80 else raw[1]
            value, mode = i.address + 2 + d, "rel"
        elif len(raw) == 1:
            value, mode = None, "imp"
        else:
            value = raw[1] if len(raw) == 2 else raw[1] | raw[2] << 8
            if ops.startswith("#"):
                mode = "imm"
            else:
                mode = "ind" if ops.startswith("(") else ("zp" if len(raw) == 2 else "abs")
                tail = ops.replace(" ", "").lower()
                mode += ",x" if tail.endswith(",x") else (",y" if tail.endswith(",y") else "")
        out.append(Ins(i.address, m, ops, raw, value, mode))
        if len(out) >= count:
            break
    return out


def _mnems(ins: list[Ins]) -> list[str]:
    return [x.mnem for x in ins]


def mmc3_layout(prg: bytes) -> dict:
    """PT2_Full_CHRROM_Switch: LDY #n / TYA / ORA #cmd / STA $8000 /
    LDA PatTable_BankSel,Y / STA $8001 / DEY / BPL, in fixed bank 31."""
    bank, base = 31, FIXED[31]
    code = _bank(prg, bank)
    hits = []
    for p in _find(code, b"\x98\x09"):
        if p < 2 or code[p - 2] != 0xA0:
            continue
        ins = disasm(prg, bank, base, base + p - 2, 8)
        if (_mnems(ins) == ["ldy", "tya", "ora", "sta", "lda", "sta", "dey", "bpl"]
                and ins[2].mode == "imm" and ins[3].mode == "abs" and ins[3].value == 0x8000
                and ins[4].mode == "abs,y" and ins[5].value == 0x8001
                and ins[7].value == ins[1].cpu):
            hits.append(ins)
    if len(hits) != 1:
        raise ValueError(f"MMC3 pattern-table loop not uniquely found ({len(hits)})")
    ins = hits[0]
    cmd, regs, sel = ins[2].value, ins[0].value + 1, ins[4].value
    prg_mode, chr_mode = cmd >> 6 & 1, cmd >> 7 & 1
    ppu = (0x1000, 0x1800, 0x0000, 0x0400, 0x0800, 0x0C00) if chr_mode else \
          (0x0000, 0x0800, 0x1000, 0x1400, 0x1800, 0x1C00)
    return {
        "routine": ins[0].cpu, "bank": bank, "pattable_bank_sel": sel,
        "command_base": cmd, "prg_mode": prg_mode, "chr_mode": chr_mode,
        "chr_windows": [{"reg": r, "ram": sel + r, "ppu": ppu[r],
                         "size": 0x800 if r < 2 else 0x400} for r in range(regs)],
        "cpu_windows": ({"$8000": "bank 30 (fixed)", "$A000": "R7", "$C000": "R6",
                         "$E000": "bank 31 (fixed)"} if prg_mode else
                        {"$8000": "R6", "$A000": "R7", "$C000": "bank 30 (fixed)",
                         "$E000": "bank 31 (fixed)"}),
        "listing": [x.text() for x in ins],
    }


def chr_reg(layout: dict, ppu_addr: int) -> int | None:
    for w in layout["chr_windows"]:
        if w["ppu"] <= ppu_addr < w["ppu"] + w["size"]:
            return w["reg"]
    return None


def player_draw(prg: bytes, tables: dict, layout: dict) -> dict:
    """Player_Draw head: LDX <frame / LDA FramePageOff,X / STA <t / LDY <suit /
    LDA PUpRootPage,Y / CLC / ADC <t / STA PatTable_BankSel+2."""
    bank = tables["prg_bank"]
    base = SWAP_C000 if layout["prg_mode"] else 0x8000
    fpo, root = tables["frame_page_off"]["cpu"], tables["pup_root_page"]["cpu"]
    code = _bank(prg, bank)
    found = []
    for p in _find(code, bytes((0xBD, fpo & 0xFF, fpo >> 8))):
        if p < 2 or code[p - 2] != 0xA6:
            continue
        ins = disasm(prg, bank, base, base + p - 2, 8)
        if (_mnems(ins) == ["ldx", "lda", "sta", "ldy", "lda", "clc", "adc", "sta"]
                and ins[4].mode == "abs,y" and ins[4].value == root
                and ins[2].value == ins[6].value and ins[7].mode == "abs"):
            found.append(ins)
    if len(found) != 1:
        raise ValueError(f"Player_Draw head not uniquely found ({len(found)})")
    ins = found[0]
    entry, store = ins[0].cpu, ins[7].value
    reg = store - layout["pattable_bank_sel"]
    if not 0 <= reg < len(layout["chr_windows"]):
        raise ValueError(f"Player_Draw stores ${store:04X}, not a PatTable_BankSel byte")
    callers = sorted(base + p for op in (0x20, 0x4C)
                     for p in _find(code, bytes((op, entry & 0xFF, entry >> 8))))
    return {"entry": entry, "bank": bank, "frame_zp": ins[0].value,
            "suit_zp": ins[3].value, "bank_store": store, "chr_reg": reg,
            "ppu": layout["chr_windows"][reg]["ppu"], "callers": callers,
            "listing": [x.text() for x in ins]}


def bank_store_sites(prg: bytes, ram: int) -> list[dict]:
    """Raw scan for STA/STX/STY abs ``ram`` in every bank (with 2 lead bytes)."""
    out = []
    for b in range(len(prg) // BANK):
        code = _bank(prg, b)
        for p in _find(code, bytes((ram & 0xFF, ram >> 8))):
            if p >= 1 and code[p - 1] in (0x8D, 0x8E, 0x8C):
                out.append({"bank": b, "offset": p - 1,
                            "op": {0x8D: "STA", 0x8E: "STX", 0x8C: "STY"}[code[p - 1]],
                            "lead": code[max(0, p - 3):p - 1].hex()})
    return out


def palette_rules(prg: bytes, draw: dict) -> dict:
    """Level_SetPlayerPUpPal: palette index from suit/statue/Player_Current,
    then PowerUp_Palettes[i*4+1..3] -> PPU $3F11-$3F13 and Palette_Buffer."""
    sig = re.compile(rb"\xA0.\xAD..\xD0.\xA5" + re.escape(bytes((draw["suit_zp"],)))
                     + rb"\xA8\xC9.\xF0.\xC9.[\x10\xB0].\xAC..", re.S)
    found = []
    for m in sig.finditer(prg):
        b, off = divmod(m.start(), BANK)
        if b in FIXED or off + 0x60 > BANK:
            continue
        code = _bank(prg, b)
        k = code.find(b"\xB9", off + 20, off + 0x60)
        if k < 0:
            continue
        base = (code[k + 2] << 8) & 0xE000
        ins = disasm(prg, b, base, base + off, 48)
        ins = ins[:next((i + 1 for i, x in enumerate(ins) if x.mnem == "rts"), len(ins))]
        pre = ins[:10]
        if (_mnems(pre)[:8] != ["ldy", "lda", "bne", "lda", "tay", "cmp", "beq", "cmp"]
                or pre[8].mnem not in ("bpl", "bcs") or pre[9].mnem != "ldy"):
            continue
        reads = [i for i, x in enumerate(ins) if x.mnem == "lda" and x.mode == "abs,y"]
        if len(reads) != 3:
            continue
        table = ins[reads[0]].value - 1
        if [ins[i].value for i in reads] != [table + 1, table + 2, table + 3]:
            continue
        imms = [x.value for x in ins[10:reads[0]] if x.mnem == "lda" and x.mode == "imm"]
        pbuf = [x.value for x in ins[reads[0]:] if x.mnem == "sta" and x.mode == "abs"]
        found.append((b, base, ins, pre, table, imms, pbuf))
    if len(found) != 1:
        raise ValueError(f"Level_SetPlayerPUpPal not uniquely found ({len(found)})")
    b, base, ins, pre, table, imms, pbuf = found[0]
    entries = pre[0].value + 1
    t = b * BANK + (table - base)
    return {
        "bank": b, "entry": ins[0].cpu, "statue_index": pre[0].value,
        "statue_flag": pre[1].value, "suit_zp": pre[3].value,
        "raccoon_suit": pre[5].value, "fire_suit": pre[7].value,
        "player_current": pre[9].value, "ppu": imms[0] << 8 | imms[1], "run": imms[2],
        "palette_buffer": pbuf, "table_cpu": table, "table_prg_offset": t,
        "palettes": [list(prg[t + 4 * i:t + 4 * i + 4]) for i in range(entries)],
        "listing": [x.text() for x in ins],
    }


def palette_index(rules: dict, suit: int, player: int, statue: bool = False) -> int:
    if statue:
        return rules["statue_index"]
    if suit == rules["raccoon_suit"] or suit < rules["fire_suit"]:
        return player
    return suit


def colours(rules: dict, suit: int, player: int, statue: bool = False) -> list[int]:
    return rules["palettes"][palette_index(rules, suit, player, statue)][1:4]


def grow_override(prg: bytes, tables: dict, draw: dict, a000_bank: int) -> dict:
    """LDA Player_GrowFrames,X / STA <frame / JSR Player_Draw / LDA $071B /
    AND #3 / ORA #even / PLP / BEQ / SEC / SBC #d / STA $071B."""
    bank, base = draw["bank"], SWAP_C000
    code = _bank(prg, bank)
    e, s = draw["entry"], draw["bank_store"]
    hits = _find(code, bytes((0x20, e & 0xFF, e >> 8, 0xAD, s & 0xFF, s >> 8, 0x29, 0x03, 0x09)))
    if len(hits) != 1:
        raise ValueError(f"grow page override not uniquely found ({len(hits)})")
    p = hits[0]
    ins = disasm(prg, bank, base, base + p, 9)
    if (_mnems(ins) != ["jsr", "lda", "and", "ora", "plp", "beq", "sec", "sbc", "sta"]
            or ins[8].value != s):
        raise ValueError("grow page override has an unexpected shape")
    if not (code[p - 5] == 0xBD and code[p - 2] == 0x85 and code[p - 1] == draw["frame_zp"]):
        raise ValueError("grow frame load not found before the Player_Draw call")
    table = code[p - 4] | code[p - 3] << 8
    back = code[max(0, p - 48):p]
    k = back.rfind(b"\x38\xE5")            # LDA #last / SEC / SBC <t (small Player)
    if k < 2 or back[k - 2] != 0xA9:
        raise ValueError("grow frame count not found")
    count = back[k - 1] + 1
    off = a000_bank * BANK + (table - SWAP_A000)
    frames = list(prg[off:off + count])
    if any(f >= inv.FRAMES for f in frames):
        raise ValueError("grow frames table is not in the expected $A000 bank")
    even, odd = ins[3].value, ins[3].value - ins[7].value
    steps = [{"index": x, "frame": f,
              "page": (even if x % 2 == 0 else odd) | (tables["page_off"][f] & 3)}
             for x, f in enumerate(frames)]
    return {"site": base + p, "even_base": even, "odd_base": odd,
            "ora_imm_cpu": ins[3].cpu + 1, "sbc_imm_cpu": ins[7].cpu + 1,
            "grow_frames_cpu": table, "grow_frames_bank": a000_bank,
            "grow_frames": frames, "steps": steps, "listing": [x.text() for x in ins]}


def object_chr_requests(prg: bytes, layout: dict) -> dict:
    """LDX #0 / LDA ObjectGroup_PatTableSel,Y / BEQ / BPL / INX / AND #$7F /
    STA PatTable_BankSel+4,X: an object's CHR page request."""
    sig = bytes((0xB9, OBJ_PATTABLESEL & 0xFF, OBJ_PATTABLESEL >> 8, 0xF0))
    hits = []
    for b in range(len(prg) // BANK):
        code = _bank(prg, b)
        base = FIXED.get(b, SWAP_C000)
        for p in _find(code, sig):
            if p < 2 or code[p - 2] != 0xA2:
                continue
            ins = disasm(prg, b, base, base + p - 2, 7)
            if (_mnems(ins) == ["ldx", "lda", "beq", "bpl", "inx", "and", "sta"]
                    and ins[5].value == 0x7F and ins[6].mode == "abs,x"):
                hits.append((b, ins))
    if len(hits) != 1:
        raise ValueError(f"object CHR request loader not uniquely found ({len(hits)})")
    b, ins = hits[0]
    reg = ins[6].value + ins[0].value - layout["pattable_bank_sel"]
    return {"bank": b, "site": ins[1].cpu, "store": ins[6].value,
            "reg_bit7_clear": reg, "reg_bit7_set": reg + 1,
            "listing": [x.text() for x in ins]}


def kuribo_shared_page(prg: bytes, chr_: bytes, tables: dict, layout: dict, loader: dict) -> dict:
    shoe = sorted({f for f, pats in enumerate(tables["frames"])
                   if any(p != inv.HIDDEN and p >= 0x80 for p in pats)})
    pats = sorted({p for f in shoe for p in tables["frames"][f] if p != inv.HIDDEN and p >= 0x80})
    ppu = sorted({0x1000 * (p & 1) + (p & 0xFE) * 16 for p in pats})
    regs = sorted({chr_reg(layout, a) for a in ppu} | {chr_reg(layout, a + 31) for a in ppu})
    obj_bank = 1 + OBJ_GOOMBAINSHOE // OBJECTS_PER_BANK
    req = prg[obj_bank * BANK + (OBJ_PATTABLESEL - SWAP_A000) + OBJ_GOOMBAINSHOE % OBJECTS_PER_BANK]
    reg = loader["reg_bit7_set"] if req & 0x80 else loader["reg_bit7_clear"]
    page = req & 0x7F
    tiles = sorted({t for p in pats for t in (p - 0x80 & 0xFE, (p - 0x80 & 0xFE) + 1)})
    blank = [t for t in tiles if not any(chr_[(page * 64 + t) * 16:(page * 64 + t) * 16 + 16])]
    return {"frames": shoe, "patterns": pats, "ppu": ppu, "pattern_regs": regs,
            "object": OBJ_GOOMBAINSHOE, "object_bank": obj_bank, "request": req,
            "chr_reg": reg, "page": page, "page_tiles": tiles, "blank_tiles": blank,
            "page_sha256": hashlib.sha256(chr_[page * inv.CHR_PAGE:(page + 1) * inv.CHR_PAGE]).hexdigest()}


def frame_indices(chr_: bytes, pats, page: int, shared_page: int | None = None) -> list[list[int]]:
    """24x32 colour-index image of one frame (0 = transparent)."""
    img = [[0] * 24 for _ in range(32)]
    for slot, p in enumerate(pats):
        if p == inv.HIDDEN:
            continue
        pg, t = inv.pattern_page(page, p, shared_page)
        if pg is None:
            continue
        sx, sy = slot % 3 * 8, slot // 3 * 16
        for half in (0, 1):
            for y, row in enumerate(inv.tile(chr_, pg * 64 + t + half)):
                for x, v in enumerate(row):
                    if v:
                        img[sy + half * 8 + y][sx + x] = v
    return img


def nes_rgb(i: int) -> tuple[int, int, int]:
    i &= 0x3F
    return NES_RGB[3 * i], NES_RGB[3 * i + 1], NES_RGB[3 * i + 2]


def page_usage(chr_: bytes, tables: dict, grow: dict, shoe_page: int) -> dict:
    used: dict[int, set] = {}

    def add(page, pats):
        for p in pats:
            if p != inv.HIDDEN:
                pg, t = inv.pattern_page(page, p, shoe_page)
                if pg is not None:
                    used.setdefault(pg, set()).update((t, t + 1))
    for root in tables["root_pages"].values():
        for f, pats in enumerate(tables["frames"]):
            add(root + tables["page_off"][f], pats)
    for st in grow["steps"]:
        add(st["page"], tables["frames"][st["frame"]])
    out = {}
    for pg in sorted(used):
        free = [t for t in range(64) if t not in used[pg]]
        blank = [t for t in free if not any(chr_[(pg * 64 + t) * 16:(pg * 64 + t) * 16 + 16])]
        out[f"0x{pg:02X}"] = {"tiles_referenced": len(used[pg]), "unreferenced": len(free),
                              "unreferenced_blank": len(blank)}
    return out


def probe(chr_: bytes, tables: dict, rules: dict, shoe_page: int) -> dict:
    """Decode one walk frame per power-up with each player's real palette,
    plus the two Kuribo's-shoe frames with and without the shared page."""
    out = {}
    for s, name in enumerate(inv.POWERUPS):
        f = PROBE_FRAMES[name]
        page = tables["root_pages"][name] + tables["page_off"][f]
        plane = bytes(v for row in frame_indices(chr_, tables["frames"][f], page) for v in row)
        for pl, who in enumerate(PLAYERS):
            col = colours(rules, s, pl)
            rgb = b"".join(bytes(nes_rgb(col[v - 1])) if v else b"\0\0\0" for v in plane)
            out[f"{name}/{who}"] = {
                "frame": f, "page": page, "palette_index": palette_index(rules, s, pl),
                "colours": col, "opaque_pixels": sum(1 for v in plane if v),
                "indices_used": sorted(set(plane) - {0}),
                "index_sha256": hashlib.sha256(plane).hexdigest(),
                "rgb_sha256": hashlib.sha256(rgb).hexdigest()}
    for name, f in KURIBO_FRAMES.items():
        page = tables["root_pages"][name] + tables["page_off"][f]
        with_page = frame_indices(chr_, tables["frames"][f], page, shoe_page)
        without = frame_indices(chr_, tables["frames"][f], page, None)
        out[f"kuribo_{name}"] = {
            "frame": f, "page": page, "shared_page": shoe_page,
            "bottom_opaque": sum(1 for row in with_page[16:] for v in row if v),
            "bottom_opaque_without_shared": sum(1 for row in without[16:] for v in row if v)}
    return out


def render_sheet(chr_: bytes, tables: dict, rules: dict, shoe_page: int) -> tuple[int, int, bytes]:
    """RGBA sheet: rows = suit x (Mario, Luigi), one 24x32 cell per frame."""
    cw, ch, pad = 24, 32, 2
    rows = [(s, name, pl) for s, name in enumerate(inv.POWERUPS) for pl in range(len(PLAYERS))]
    W, H = inv.FRAMES * (cw + pad), len(rows) * (ch + pad)
    px = bytearray(bytes((*SKY, 255)) * (W * H))
    cache: dict = {}
    for r, (s, name, pl) in enumerate(rows):
        col = [bytes((*nes_rgb(c), 255)) for c in colours(rules, s, pl)]
        root = tables["root_pages"][name]
        for f, pats in enumerate(tables["frames"]):
            key = (name, f)
            if key not in cache:
                cache[key] = frame_indices(chr_, pats, root + tables["page_off"][f], shoe_page)
            ox, oy = f * (cw + pad), r * (ch + pad)
            for y, row in enumerate(cache[key]):
                for x, v in enumerate(row):
                    if v:
                        o = ((oy + y) * W + ox + x) * 4
                        px[o:o + 4] = col[v - 1]
    return W, H, bytes(px)


def _hex(v: int) -> str:
    return f"${v:04X}" if v > 0xFF else f"${v:02X}"


def constraints(layout, draw, rules, grow, shoe, tables) -> list[str]:
    r = tables["root_pages"]
    pal = {n: " ".join(f"{c:02X}" for c in colours(rules, s, 0)) for s, n in enumerate(inv.POWERUPS)}
    luigi = " ".join(f"{c:02X}" for c in colours(rules, 0, 1))
    return [
        "Sprites are 8x16 (pattern bit 0 selects the PPU $1000 table). A frame is 6 slots in a "
        "3x2 grid (24x32 px) and $F1 hides a slot. All suits share the 81 frames of "
        f"SPPF_Offsets/SPPF_Table (bank {tables['prg_bank']}).",
        f"Patterns below $40 come from ONE 1 KB page per frame: PUpRootPage[suit] + "
        f"FramePageOff[frame]. Player_Draw ({_hex(draw['entry'])}) stores it to "
        f"{_hex(draw['bank_store'])} (PatTable_BankSel+{draw['chr_reg']}), and "
        f"PT2_Full_CHRROM_Switch ({_hex(layout['routine'])}) copies it to MMC3 "
        f"R{draw['chr_reg']} = PPU {_hex(draw['ppu'])}-{_hex(draw['ppu'] + 0x3FF)}.",
        f"Patterns $80-$BF read MMC3 R{shoe['chr_reg']} (PPU $1800), which level objects own. "
        f"The Kuribo's-shoe frames {', '.join(_hex(f) for f in shoe['frames'])} depend on "
        f"OBJ_GOOMBAINSHOE requesting page {_hex(shoe['page'])} (tiles "
        f"{_hex(min(shoe['page_tiles']))}-{_hex(max(shoe['page_tiles']))}). A replacement must "
        "leave those tiles alone or point the shoe frames' top row into the player page.",
        f"Colours: 3 plus transparent from sprite palette 0 ({_hex(rules['ppu'])}-"
        f"{_hex(rules['ppu'] + rules['run'] - 1)}), uploaded by Level_SetPlayerPUpPal "
        f"({_hex(rules['entry'])}). Small/Big/Leaf use PowerUp_Palettes[Player_Current] "
        f"(Mario {pal['small']}, Luigi {luigi}). Fire {pal['fire']}, Frog {pal['frog']}, "
        f"Tanooki {pal['tanooki']} and Hammer {pal['hammer']} ignore the player. The statue uses "
        f"entry {rules['statue_index']}. Frog shares Luigi's colours, so editing a table entry "
        "also changes the other users of that entry.",
        f"CHR pages: small and frog share {_hex(r['small'])}-{_hex(r['small'] + 3)}; big and "
        f"fire share {_hex(r['big'])}-{_hex(r['big'] + 3)} (they differ only by palette); leaf "
        f"{_hex(r['leaf'])}-{_hex(r['leaf'] + 3)}; tanooki {_hex(r['tanooki'])}-"
        f"{_hex(r['tanooki'] + 3)}; hammer {_hex(r['hammer'])}-{_hex(r['hammer'] + 3)}.",
        f"The grow animation ({_hex(grow['site'])}) overrides the page with hard-coded "
        f"immediates: ORA #{_hex(grow['even_base'])} at {_hex(grow['ora_imm_cpu'])} on even "
        f"steps and SBC #{_hex(grow['even_base'] - grow['odd_base'])} at "
        f"{_hex(grow['sbc_imm_cpu'])} (pages {_hex(grow['odd_base'])}|n) on odd steps. Mid-grow "
        "frame $27 is therefore drawn from the hammer page group, whatever PUpRootPage says. "
        "Relocating those pages means patching both immediates.",
        "Each 16-px row of a frame uses up to 3 of the NES's 8 sprites per scanline. Keep $F1 "
        "slots where the original has them, or the new frames will add flicker.",
    ]


def analyze(src) -> dict:
    data, source = inv.read_source(src)
    hdr = inv.parse_ines(data)
    prg, chr_ = inv.split(data, hdr)
    ident = inv.identify(prg + chr_)
    tables = inv.locate_player_tables(prg)
    layout = mmc3_layout(prg)
    draw = player_draw(prg, tables, layout)
    rules = palette_rules(prg, draw)
    if rules["suit_zp"] != draw["suit_zp"]:
        raise ValueError("palette routine and Player_Draw disagree on Player_Suit")
    grow = grow_override(prg, tables, draw, rules["bank"])
    loader = object_chr_requests(prg, layout)
    shoe = kuribo_shared_page(prg, chr_, tables, layout, loader)
    by_suit = {name: {who: {"index": palette_index(rules, s, pl), "colours": colours(rules, s, pl)}
                      for pl, who in enumerate(PLAYERS)} for s, name in enumerate(inv.POWERUPS)}
    return {
        "game": "Super Mario Bros. 3", "platform": "nes", "stage": "analysis",
        "source": source, "identity": ident,
        "method": "capstone MOS65XX disassembly of the owned ROM. Tables are found by content "
                  "(smb3_inventory) and code by instruction shape; the Rev 1 disassembly is "
                  "used only for names",
        "mmc3": layout,
        "functions": {
            "PT2_Full_CHRROM_Switch": {"bank": layout["bank"], "cpu": layout["routine"]},
            "Player_Draw": {"bank": draw["bank"], "cpu": draw["entry"], "callers": draw["callers"]},
            "Player_GrowPageOverride": {"bank": draw["bank"], "cpu": grow["site"]},
            "Level_SetPlayerPUpPal": {"bank": rules["bank"], "cpu": rules["entry"]},
            "Object_CHRRequest": {"bank": loader["bank"], "cpu": loader["site"]},
        },
        "player_draw": draw, "grow": grow, "palettes": {**rules, "by_suit": by_suit},
        "object_chr_request": loader, "kuribo": shoe,
        "pattable_sel2_stores": bank_store_sites(prg, draw["bank_store"]),
        "table_xrefs": tables["xrefs"],
        "page_usage": page_usage(chr_, tables, grow, shoe["page"]),
        "probe": probe(chr_, tables, rules, shoe["page"]),
        "constraints": constraints(layout, draw, rules, grow, shoe, tables),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    ap.add_argument("--png")
    a = ap.parse_args(argv)
    rep = analyze(a.src)
    if a.png:
        data, _ = inv.read_source(a.src)
        prg, chr_ = inv.split(data, inv.parse_ines(data))
        tables = inv.locate_player_tables(prg)
        sheet = render_sheet(chr_, tables, rep["palettes"], rep["kuribo"]["page"])
        Path(a.png).write_bytes(inv.png_bytes(*sheet))
    text = json.dumps(rep, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({"identity": rep["identity"].get("revision"),
                      "functions": {k: _hex(v["cpu"]) for k, v in rep["functions"].items()},
                      "kuribo_page": _hex(rep["kuribo"]["page"]),
                      "palettes": {k: v["mario"]["colours"] for k, v in rep["palettes"]["by_suit"].items()},
                      "luigi_small": rep["palettes"]["by_suit"]["small"]["luigi"]["colours"]}))
    return rep


if __name__ == "__main__":
    main()
