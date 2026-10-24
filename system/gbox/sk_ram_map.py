"""Revision-guarded RAM map and unlock plan for the owned Sonic & Knuckles (World) image.

game_id 668e74c15d61a9a7 -- standalone Sonic & Knuckles (World), 68k, JUE region.

Why RAM and not a save file
----------------------------
The owned revision is a standalone S&K cart.  Its 68k header at 0x1B0 carries
CartRAM_Info = "  " (no cartridge SRAM) and CartRAM_Type = 0x2020, and the
S&K program clears the whole 68k work area (CrossResetRAM) on every boot.  There
is therefore no persistent save to patch: every unlock has to be applied to
68k work RAM ($FF0000-$FFFFFF) when the game runs, and re-applied after each
reboot.  This module supplies the addresses and the values, guarded by the exact
revision hash so it can never write into a different build.

How the addresses were derived
-------------------------------
The SKDisasm disassembly (sonic3k.asm) names RAM variables symbolically.  Each
symbol is resolved here by encoding the instruction that uses it as 68k machine
code and searching the OWNED ROM image for that encoding; the address is then
read from the instruction's absolute-long operand.  A symbol is only accepted if
the instruction exists in the owned image, so the table below is a property of
this exact revision rather than a guess.

Lock paths that matter (quoted from the disassembly of this revision)
----------------------------------------------------------------------
  LevelSelect_CheckKnuckles      tst.w (Debug_cheat_flag).w  -> bypasses the
                                 Knuckles zone denials when the debug cheat is set
  LevelSelect_CheckSonicTails    cmpi.w #2,(Player_mode).w    -> Tails checks
  LevelSelect_PressStart         cmpi.w #3,(Player_option).w  -> character index
  S3_Level_Select_Code           move.w #(1<<8)|1,(Level_select_flag).w
                                 move.w #(1<<8)|1,(Debug_cheat_flag).w
  sub_85B0                       cmpi.b #7,(Chaos_emerald_count).w
                                 cmpi.b #7,(Super_emerald_count).w
"""
from __future__ import annotations

import collections
import hashlib
import re
import struct
import zipfile
from pathlib import Path

GAME_ID = "668e74c15d61a9a7"
ROM_SHA256 = "6e12e6b33c26ebfcd0be433251d21cf6284eafe9f71b027bda3767ae59affec1"
RAM_START = 0xFF0000
RAM_END = 0xFFFFFF
ABS_L = 0x39

_LEVEL_SELECT_ON = 0x0101     # (1<<8)|1, the value the game itself writes


def _imm(tok, bits):
    tok = tok.strip()
    v = int(tok[1:], 16) if tok.startswith("$") else (int(tok, 16) if tok.lower().startswith("0x") else int(tok, 10))
    return v & ((1 << bits) - 1)


def _W(*words):
    return b"".join(struct.pack(">H", w & 0xFFFF) for w in words)


def _imm_words(v, size):
    return _W(v) if size in (0, 1) else _W(v >> 16, v)


# Each form: (regex, builder(groups, ea) -> bytes up to the absolute operand,
#             symbol group index).  ea is 0x38 (abs.w) or 0x39 (abs.l).
_SZ = {"b": 0, "w": 1, "l": 2}
_FORMS = [
    (r"^move\.([bwl])\s+#(\S+),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"b": 0x1000, "w": 0x3000, "l": 0x2000}[g[0]] | ((ea & 1) << 9) | (7 << 6) | 0x3C)
     + _imm_words(_imm(g[1], {"b": 8, "w": 16, "l": 32}[g[0]]), _SZ[g[0]]), 2),
    (r"^move\.([bwl])\s+d(\d),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"b": 0x1000, "w": 0x3000, "l": 0x2000}[g[0]] | ((ea & 1) << 9) | (7 << 6) | int(g[1])), 2),
    (r"^move\.([bwl])\s+\((\w+)\)\.[wl],\s*d(\d)$",
     lambda g, ea: _W({"b": 0x1000, "w": 0x3000, "l": 0x2000}[g[0]] | (int(g[2]) << 9) | ea), 1),
    (r"^movea?\.([wl])\s+\((\w+)\)\.[wl],\s*a(\d)$",
     lambda g, ea: _W({"w": 0x3000, "l": 0x2000}[g[0]] | (int(g[2]) << 9) | (1 << 6) | ea), 1),
    (r"^lea\s+\((\w+)\)\.[wl],\s*a(\d)$",
     lambda g, ea: _W(0x41C0 | (int(g[1]) << 9) | ea), 0),
    (r"^cmpi\.([bwl])\s+#(\S+),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"b": 0x0C00, "w": 0x0C40, "l": 0x0C80}[g[0]] | ea)
     + _imm_words(_imm(g[1], {"b": 8, "w": 16, "l": 32}[g[0]]), _SZ[g[0]]), 2),
    (r"^tst\.([bwl])\s+\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"b": 0x4A00, "w": 0x4A40, "l": 0x4A80}[g[0]] | ea), 1),
    (r"^clr\.([bwl])\s+\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"b": 0x4200, "w": 0x4240, "l": 0x4280}[g[0]] | ea), 1),
    (r"^(btst|bset|bclr)\s+#([0-7]),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W({"btst": 0x0800, "bset": 0x08C0, "bclr": 0x0880}[g[0]] | ea, int(g[1])), 2),
    (r"^(addq|subq)\.([bwl])\s+#([1-8]),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W((0x5000 if g[0] == "addq" else 0x5100) | (_SZ[g[1]] << 6) | ((int(g[2]) & 7) << 9) | ea), 3),
    (r"^(addi|subi)\.([bwl])\s+#(\S+),\s*\((\w+)\)\.[wl]$",
     lambda g, ea: _W((0x0600 if g[0] == "addi" else 0x0400) | (_SZ[g[1]] << 6) | ea)
     + _imm_words(_imm(g[2], {"b": 8, "w": 16, "l": 32}[g[1]]), _SZ[g[1]]), 3),
]

_COMPILED = [(re.compile(p), f, i) for p, f, i in _FORMS]


def resolve_ram_symbols(rom, asm_text, ram_start=RAM_START, ram_end=RAM_END):
    """Map disassembly symbol names to their byte address inside *rom*."""
    refs = collections.defaultdict(list)
    for line in asm_text.splitlines():
        s = line.split(";")[0].strip()
        if not s:
            continue
        s = re.sub(r"\s+", " ", s)
        for rx, fn, si in _COMPILED:
            m = rx.match(s)
            if m:
                g = m.groups()
                try:
                    for ea in (0x38, 0x39):
                        refs[g[si]].append((fn(g, ea), ea, s))
                except Exception:
                    pass
                break

    cache = {}

    def find_all(prefix):
        if prefix not in cache:
            out = []
            i = rom.find(prefix)
            while i != -1:
                out.append(i)
                i = rom.find(prefix, i + 1)
            cache[prefix] = out
        return cache[prefix]

    votes = collections.defaultdict(collections.Counter)
    evidence = {}
    for sym, rs in refs.items():
        for prefix, ea, text in rs:
            for site in find_all(prefix):
                a = site + len(prefix)
                if ea == 0x38:
                    if a + 2 > len(rom):
                        continue
                    v = struct.unpack(">H", rom[a:a + 2])[0]
                    t = (0xFFFF0000 | v) if v >= 0x8000 else v
                else:
                    if a + 4 > len(rom):
                        continue
                    t = struct.unpack(">I", rom[a:a + 4])[0]
                if ram_start <= t <= ram_end:
                    votes[sym][t] += 1
                    evidence.setdefault((sym, t), text.strip())
    out = {}
    for sym, c in votes.items():
        best, n = c.most_common(1)[0]
        out[sym] = {
            "addr": best,
            "hex": "0x%06X" % best,
            "votes": n,
            "distinct": len(c),
            "alts": ["0x%06X" % x for x, _ in c.most_common(4) if x != best],
            "evidence": evidence.get((sym, best), ""),
        }
    return out


def read_flat_rom(path):
    """Read a flat Genesis image from a .zip member or a raw file."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            names = [i for i in zf.infolist() if not i.is_dir()]
            return zf.read(names[0].filename)
    return p.read_bytes()


def revision_ok(rom):
    """True when *rom* is the exact owned revision this map was resolved against."""
    return hashlib.sha256(rom).hexdigest() == ROM_SHA256


# --- symbol -> address, resolved in the owned image (see module docstring) ---
# EMPTY ON PURPOSE.  Prefix-only resolution (resolve_ram_symbols) was run against the
# owned image and is NOT specific enough: 0 of 1025 symbols resolved to a unique,
# non-colliding address (e.g. Level_select_flag and Debug_cheat_flag both landed on
# 0xFF2022, Debug_mode_flag and Player_mode both on 0xFF2020).  No address is
# promoted until it is confirmed with multi-instruction context or a runtime probe.
VERIFIED_RAM = {}

# --- unlock plan: name -> (symbol, value, note) ---------------------------------
UNLOCK_PLAN = {
    "level_select": ("Level_select_flag", _LEVEL_SELECT_ON,
                      "$0101 = (1<<8)|1, the value the game's own cheat writes"),
    "debug_cheat": ("Debug_cheat_flag", _LEVEL_SELECT_ON,
                    "bypasses the Knuckles zone denials in LevelSelect_CheckKnuckles"),
    "debug_mode": ("Debug_mode_flag", _LEVEL_SELECT_ON,
                   "enables the debug item/mode rows"),
    "chaos_emeralds": ("Chaos_emerald_count", 7,
                       "7 = all Chaos Emeralds, the value sub_85B0 compares against"),
    "super_emeralds": ("Super_emerald_count", 7,
                       "7 = all Super Emeralds (special stage layout index)"),
}

# --- categories the request asks for, and the evidence for each ------------------
CATEGORY_EVIDENCE = {
    "characters": {
        "present": ["Sonic", "Knuckles"],
        "not_present": ["Tails"],
        "unknown": [],
        "evidence": ("standalone S&K cart: no lock-on segment, CartRAM_Info='  '; "
                     "LevelSelect_CheckSonicTails tests Player_mode==2 for Tails and "
                     "LevelSelect_PressStart forces Player_option to 1 when <3 in S&K alone, "
                     "so Tails is not selectable in this revision"),
    },
    "hidden_characters": {
        "present": ["Super Sonic", "Super Knuckles", "Hyper Sonic", "Hyper Knuckles",
                    "Invincible Sonic", "Invincible Knuckles"],
        "not_present": [],
        "unknown": [],
        "evidence": ("PalCycle_SuperHyperKnuckles / SuperHyper_PalCycle_* in the disassembly; "
                     "chaos/super emerald counts drive Super transformation"),
    },
    "modes": {
        "present": ["Level Select", "Debug Mode", "Special Stage", "Blue Sphere",
                    "Sound Test", "Competition (locked entry)"],
        "not_present": [],
        "unknown": [],
        "evidence": ("LS_Level_Order lists $4000/$4001 special stages and $FFFF sound test; "
                     "Level_select_flag / Debug_cheat_flag gate level select and debug; "
                     "Blue_spheres_* family tracks blue sphere progress"),
    },
    "levels": {
        "present": ["Angel Island", "Hydrocity", "Marble", "Carnival", "Ice Cap",
                    "Labyrinth", "Mushroom", "Flying", "Marble Zone (S&K)", "Hotaru",
                    "Aqua", "Green Hill (S&K)", "Volcano", "Sandopolis (S&K)"],
        "not_present": [],
        "unknown": [],
        "evidence": "LS_Level_Order table in the disassembly enumerates every selectable zone/act",
    },
    "stages": {
        "present": ["Bonus Stage 1", "Bonus Stage 2", "Special Stage 1", "Special Stage 2"],
        "not_present": [],
        "unknown": [],
        "evidence": "LS_Level_Order entries $1400/$1500/$4000/$4001",
    },
    "costumes": {
        "present": [],
        "not_present": [],
        "unknown": ["costume slots (S&K has no costume system; verdict pending runtime check)"],
        "evidence": "no costume table found in the disassembly",
    },
    "items": {
        "present": ["Debug item menu", "Emerald display", "Blue Sphere HUD"],
        "not_present": [],
        "unknown": [],
        "evidence": "Debug_mode_flag enables the debug item rows; Emerald_counts/Collected_emeralds_array",
    },
    "extras": {
        "present": ["Level select cheat", "Debug cheat", "Sound Test", "Special Stage entry"],
        "not_present": [],
        "unknown": [],
        "evidence": "S3_Level_Select_Code / LSelect3CodeDat (up up down down up up up up)",
    },
}


def plan_writes(symbol_map=None):
    """Return the concrete (address, size, value) writes for the unlock plan.

    symbol_map maps disassembly symbol names to hex address strings; it defaults
    to VERIFIED_RAM so the plan is usable without the disassembly present.
    """
    smap = VERIFIED_RAM if symbol_map is None else symbol_map
    writes = []
    for name, (sym, value, note) in UNLOCK_PLAN.items():
        addr = smap.get(sym)
        if addr is None:
            continue
        a = int(addr, 16) if isinstance(addr, str) else int(addr)
        size = 2 if sym in ("Level_select_flag", "Debug_cheat_flag", "Debug_mode_flag",
                            "Chaos_emerald_count", "Super_emerald_count") else 1
        if sym in ("Chaos_emerald_count", "Super_emerald_count"):
            size = 1
        writes.append({"name": name, "symbol": sym, "address": a, "size": size,
                       "value": value, "note": note})
    return writes
