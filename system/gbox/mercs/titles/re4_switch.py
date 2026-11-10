"""Title: Resident Evil 4 (Nintendo Switch: title 010099A00BC1E000, update 1.0.2) - The Mercenaries mode.

"RE4" here is ALWAYS this Switch edition (never the GameCube G4BE08 one). RE4 Switch is a port of the 2007 HD /
PS2 / PC build (biohazard 4), NOT MT Framework, so its RAM layout is the RE4 engine's (pG global work area, the
cEm / EmMgr enemy table, the title.cpp task with its TW work area), closer to gbox.re4_merc_bot / gbox.re4_menus
(GameCube) than to re5_switch / re6_switch (MT Framework). What is shared with those Switch drivers is only the
*mechanism*: ARM64, little-endian, ASLR, so every address is main's load base (module_base, pinned by a 64-byte
read-only signature) plus a fixed offset, and reads go through the gbox.adapters SwitchLinuxAdapter (Eden,
single-core, NCE: a guest address is the host address) / CitronLinuxAdapter.

Runs on Citron NEO d3df71e55 only (SWITCH_CITRON_TITLES). Eden cannot run it: single-core hangs the guest and
multi-core crashes with 0xE401. The guest RAM layout is the GAME's, so an offset measured in one session holds for all.

STATUS 2026-11-09 (docs/research/re4-parity.md section 7):
- MEASURED: module_base (signature; the same 0x3CA7C04000 on every lilspark boot read), round entry, the keymap, the
  walk from the title to a live round (the capture frame, gbox.mercs.titles.re4_switch_screens), the bss row layout and
  the heap windows (BSS_ROWS, HEAP_WINDOWS), and that the main menu holds no float that falls like a round clock.
- FOUND LIVE, NOT FIXED: the round clock (ClockFinder re-finds it each boot by its fall against wall time, hints first).
- PENDING: the player and Ganado classes and their position / facing offsets (PLAYER_CLASS, ENEMY_CLASSES, U_POS, U_YAW)
  and the kill / combo / score fields (MERC_*): scripts/re4sw_round_probe.py measures them in one live round.
  Until they are set snapshot() reads the clock only, the playbook fights from the frame, and mercs.ready stays false.

Known from RE4 itself (gbox.re4_menus / gbox.re4_merc_bot, GameCube), shared with the Switch port:
- 5 characters: Leon, Ada, Krauser, HUNK, Wesker (Select Player, portraits left to right)
- 4 stages: Village, Castle, Base, Waterworld (Select Stage, a 2x2 grid)
- The Mercenaries is a separate mode (title main menu -> THE MERCENARIES -> GAME START -> player -> stage -> round)
- The round is a countdown clock with a combo / score; a character starts with a fixed loadout

Measurements: docs/research/re4-switch-ram.md, docs/research/re4-switch-round-gate.md, docs/research/re4-switch-menu-walk.md.
The map file: profiles/gamedata/010099A00BC1E000-ram.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import time

from ..driver import Driver
from . import re4_nav, re4_walk                    # the stage mesh (room collision), the walker and the map's marks
from . import re4_switch_screens as screens

TITLE_ID = "010099A00BC1E000"
MAP_ID = TITLE_ID                       # profiles/gamedata/010099A00BC1E000-ram.json

# Static identity of the Switch build, from Citron's dump_nso (2026-11-05, docs/research/re4-switch-ram.md): the file is
# the 0x100-byte NSO header plus the image at vaddr 0, so a pattern at vaddr V is at base + V in the guest (NCE: guest
# address == host address). Verified live: the signature is found once, at base 0x3ca7c04000.
BUILD_ID = "82C2A04A21D3E0B850F273D4149C9003"     # the dumped main-*.nso name
MAIN_NSO_SHA256 = "98ca897f07b2c864a0cabfb9dd8ca46a54b88c565ba629da3b7a4b6a57a57441"
SIG_OFF = 0x100000                      # deep in the image, away from the load stubs at vaddr 0
KNOWN_BASES = (0x3CA7C04000,)           # where main loaded on every lilspark boot read (2026-11-05, 2026-11-09): one
                                        # signature read confirms it before module_base() scans the arena
SIGNATURE = bytes.fromhex(
    "fd7b07a9fdc30191355100b0b5c646f9a90240f928514439f30300aa88080035"
    "285544391f0d007121080054285100b008bd46f9080140f98a018a5208696a38")

# ---------------------------------------------------------------------------
# Where the round lives in memory (docs/research/re4-parity.md section 7, docs/research/re4-switch-ram.md).
# ---------------------------------------------------------------------------
# Measured 2026-11-09 on lilspark (Citron d3df71e55, NCE, direct addressing), read-only through the job API:
# * main loads at 0x3CA7C04000 on every boot seen (2026-11-05 and 2026-11-09: the signature read back exact at
#   base + SIG_OFF), so module offsets ARE fixed addresses on this host; module_base() still re-finds it.
# * the module's data + bss (ELF: data 0xae2000 + 0x4a738, bss 0xb2c738 + 0x11938c8, so it ends at 0x1cc0000) is
#   readable on every 64 KiB page of 0xb00000..0x1cc0000 at the main menu; Citron maps it as the eleven host rows of
#   BSS_ROWS (an adapter read must stay inside one; /proc/<pid>/mem reads straight across them). A whole-span dump
#   through the job API takes 3.9 s (2.6 s between the first and last row read).
# * the guest heap the units live in (2026-11-05: Leon's position copy at 0x5d559cafe0, unit objects at 0x5d55a77ad0)
#   is readable in HEAP_WINDOWS (64 MiB probe steps); the bss holds 1,289 pointers into it at the main menu.
S_PGLOBAL = S_EMMGR = S_MERC = S_TITLE_TASK = None   # not found (S_PLAYER is below, with the units)
DATA_OFF, BSS_OFF, BSS_END = 0xAE2000, 0xB2C738, 0x1CC0000
BSS_ROWS = ((0xB00000, 0x77D000), (0x127D000, 0x3000), (0x1280000, 0x6000), (0x1286000, 0x100000),
            (0x1386000, 0x5000), (0x138B000, 0x100000), (0x148B000, 0x6000), (0x1491000, 0x100000),
            (0x1591000, 0x625000), (0x1BB6000, 0x100000), (0x1CB6000, 0xA000))
HEAP_WINDOWS = ((0x5D2C000000, 0x5DAC000000), (0x5DB0000000, 0x5DBC000000), (0x5DC4000000, 0x5DEC000000))

# The round clock: an f32 countdown in seconds that opens at 120.0, stored as a cluster of copies 0x30 apart in the bss
# (2026-11-05: 0x3ca8e78710, ...8b90, ...8bc0 ... = module + CLOCK_HINTS; the drop matched wall time, 118.445 -> 107.337
# over 11.1 s). The base has not moved since, so the hints are tried first, but nothing is taken on trust: ClockFinder
# keeps only a float that FELL BY THE WALL TIME between two reads, anywhere in the bss. Recorded bytes from the main
# menu (tests/fixtures/re4sw_bss_menu.json) hold no such float, so a menu cannot pass for a round.
CLOCK_HINTS = (0x1274710, 0x1274B90, 0x1274BC0, 0x1274BF0, 0x1274C20, 0x1274C50, 0x1274C80, 0x1274CB0)
CLOCK_LO, CLOCK_HI = 2.0, 121.0         # what a round's clock reads when it is found (it opens at 120.0)
CLOCK_RATE = (0.6, 1.4)                 # clock seconds per wall second (emulation between 60 % and 140 %)
CLOCK_DT = (0.8, 8.0)                   # the two reads this far apart (a shorter gap cannot tell 1.0 from 0.6)
CLOCK_STALE_S = 4.0                     # a found clock that has not moved this long is re-checked (a pause holds it)
CLOCK_JUMP_S = 1.0                      # slack on the fastest fall a real clock can show between two reads

# The units. Code-derived (Ghidra, re4-switch-ram.md "twentieth pass"): FUN_004cd1c0, the damage routine, does
# hp = *(ushort *)(unit + 0x3c2) - damage(type = *(byte *)(unit + 0x3ce)) and zeroes it at death; the unit-state code
# uses unit + 0xa4 / + 0xb4 as vectors. Measured 2026-11-10 on lilspark (session 2608165663e8463e-bde10e3ca2664322,
# Leon, read on the You Are Dead screen after a round; tests/fixtures/re4sw_units_live.json): every unit is an object
# 0x10c8 bytes long in one heap pool whose first word is its class's vtable (module data), with
#   +0xa4 f32 x, y, z (cm; copies at +0x128 and +0x2a8), +0xb0 f32 rotation x, y, z (rad: x = z = 0, so the facing is
#   +0xb4), +0xbc f32 scale (Ganados 1.01-1.3: RE4 scales each one), +0x110 u32 id, +0x116 state, +0x3c2 / +0x3c4 u16
#   health / max (Ganados 400/400, one 3500/3500).
# * the player: class 0xb09a60, ONE object, id 0, pointed at from the bss at module + 0x11310f0 and + 0x113b398. His
#   +0x3c2 read 1860 with +0x3c4 0 while he lay dead, so his life is NOT that field (the GameCube build keeps it in pG):
#   the snapshot gives him hp None until it is found.
# * the Ganados: class 0xae7050 (ids 22, 24 ... 40): the Ganado health, random scale and positions round the player.
#   Not yet seen moving or losing health (the round was over when they were read) - the first live round confirms.
# * not units: 0xaed470 / 0xaed3b0 / 0xaed318 (health 1000) and 0xaedad0 (health 1), ids 1-21, the 0x18-stride table at
#   module + 0x113d2b0 - static set objects (props, lamps). The 2026-11-05 "spawn markers" were 0xae7050 objects read at
#   +0x4d0 (a home / target point: +0x500 now), not at their position.
U_ID, U_HP, U_TYPE = 0x110, 0x3C2, 0x3CE
UNIT_SIZE = 0x10C8
UNIT_CLASS_LEADS = (0xAE7050, 0xAED3B0, 0xAE8B10, 0xAED470, 0xAEE5E0)   # what the probe surveys
MARKER_CLASS = 0xAE7050                 # (kept for the probe: the class 2026-11-05 took for markers - the Ganados)
SET_OBJECT_CLASSES = (0xAED470, 0xAED3B0, 0xAED318, 0xAEDAD0)
S_PLAYER = 0x11310F0                    # bss: the player unit's pointer (a second copy at S_PLAYER_2)
S_PLAYER_2 = 0x113B398
PLAYER_CLASS: int | None = 0xB09A60
# 2026-11-10 00:58 UTC, a LIVE round (session 44235c1d29b8483e-a94ee7e0f9884280, Village, the bot walking): no object
# of 0xb09a60 was in the heap at all, S_PLAYER read 0, and S_PLAYER_2 led to exactly one object of class 0xb0c0a0
# whose +0xa4 moved between two reads 1.5 s apart (x 50,689 -> 50,769) - the live player. 0xb09a60 is the class the
# death screen showed. Either class is the player when the bss pointer leads to it.
PLAYER_CLASSES: tuple = (0xB0C0A0, 0xB09A60)
# 2026-11-10 21:46 (session 88a92225892b4c4f-b143533715b54c62, the DJ's pick Ada / Base): the player was not read at
# all - those two classes are Leon's. Every Mercenaries character is its own class, so the unit the player pointer
# leads to is the player whatever its class, while its vtable is a class vtable of the unit range (module offsets
# PLAYER_VTABLE_RANGE, which holds every unit class measured: Ganados 0xAE7050, set objects 0xAED318-0xAEE5E0, Leon
# 0xB09A60 / 0xB0C0A0) and not a Ganado's or a set object's. The class is reported (player_class) and kept.
PLAYER_VTABLE_RANGE = (0xAC0000, 0xB40000)
SEEN_PLAYER_CLASSES: dict = {}                  # class offset -> times read through the player pointer


def player_classes() -> tuple:
    """PLAYER_CLASS first, then the other measured player classes; nothing while PLAYER_CLASS is unmapped (None)."""
    if PLAYER_CLASS is None:
        return ()
    return tuple(dict.fromkeys((PLAYER_CLASS,) + tuple(globals().get("PLAYER_CLASSES") or ())))
ENEMY_CLASSES: tuple = (0xAE7050,)
U_POS: int | None = 0xA4
U_YAW: int | None = 0xB4                # rotation y; the heading convention (0 = +z, + toward +x) is INFERRED
U_HP_MAX: int | None = 0x3C4
U_SCALE = 0xBC
PLAYER_HP_IN_UNIT = False               # the player's +0x3c2 is not his life (see above): hp None until it is found
UNIT_HP_MAX = 30000                     # a health above this is not a health (a freed or foreign object)
UNIT_SCAN_CHUNK = 1 << 24               # 16 MiB per read while the census scans the heap
UNIT_RESCAN_S = 4.0                     # new spawns: the census looks again this often, inside the pool it found

# Mercenaries counters as module offsets (PENDING: the probe lists the candidates). Until they are measured the bot
# counts kills itself from the census (a unit whose health falls to 0) and says so (kills_source "census").
# The round's kill count (u32, module + 0x12010c4), measured on two live rounds 2026-11-10: Krauser / Waterworld
# read 0, 0, 1, 1, 5 ... 5 with five census kills; HUNK / Castle read 1 while the census saw none (a melee kill whose
# unit was freed between two reads - the census misses those). Trusted up to MERC_KILLS_MAX; above it, the census.
MERC_KILLS: int | None = 0x12010C4
MERC_KILLS_MAX = 2000
# The round probe on the live Krauser / Waterworld round (2026-11-10 22:07, five kills): these u32 module offsets
# stepped up with the fight - 0x12010c4 read 0, 0, 1, 1, 5 ... 5 (the round's kill count: the leading candidate for
# MERC_KILLS), the others 0 ... 9. Read beside the census every snapshot (snap["kill_candidates"]) until one is
# confirmed against a second round, then it becomes MERC_KILLS.
KILL_CANDIDATES: tuple = (0x12010C4, 0x120118C, 0x12014AC, 0x12013E4)
MERC_COMBO: int | None = None
MERC_SCORE: int | None = None

# Rows the walk steers to (re4_switch_screens reads them from the frame). The cursor opens on LOAD, and a confirm there
# loads a story save, so the walk only ever confirms on the row it has read as its target.
EXTRAS_ROW = 5                          # main menu: NEW GAME, LOAD, LEADERBOARDS, HELP & OPTIONS, ACHIEVEMENTS, EXTRAS, CREDITS
MERCENARIES_ROW = 2                     # EXTRAS: SEPARATE WAYS, ASSIGNMENT ADA, THE MERCENARIES, MOVIE BROWSER, ADA'S REPORT

CLOCK_MAX_S = 1200.0                    # the Mercenaries clock never reads more than this (sanity bound, from re4_merc_bot)

MAX_ENEMIES = 512                       # read budget for the EmMgr table (spawn multipliers expand it; re4_merc_bot)
PTR_LO, PTR_HI = 0x1000000, 1 << 40     # a plausible ARM64 guest pointer (as re5_switch.ptr_ok)

# The round shape the engine needs (driver.Driver.snapshot): keep this identical to re5_switch / re6_switch so the
# engine and round_reports read RE4 the same way.
PHASE_INTRO, PHASE_PLAYING, PHASE_OVER = 0, 1, 3

# ---------------------------------------------------------------------------
# Characters, stages, and the per-round targets (the randomizer mirrors re5_switch.StageCycle; wired on the scan).
# ---------------------------------------------------------------------------
CHARACTERS = ("Leon", "Ada", "Krauser", "HUNK", "Wesker")       # Select Player portraits, left to right
STAGES = ("Village", "Castle", "Base", "Waterworld")            # Select Stage, a 2x2 grid
PLAYER_TARGET, STAGE_TARGET = 0, 0                              # Leon, Village: the selects' first entries
# The 2x2 Select Stage grid, as the GameCube build lays it out (re4_menus: "0 the Village, up / down 2, left / right
# 1"): Village top left, Castle top right, Base bottom left, Waterworld bottom right. That the Switch port keeps this
# layout, and that the Select Player cursor steps one portrait per d-pad right press from Leon without skipping, are
# INFERRED (no live frame of a moved cursor yet): the first DJ round with a non-default pick must be checked on screen.
STAGE_MOVES = {0: (), 1: ("dright",), 2: ("ddown",), 3: ("dright", "ddown")}
STEER_GAP_S = 1.0                       # between two cursor moves on a select screen (open loop: one move per gap)

# MercMode's DJ pick for the next selects (request()): player / stage indexes, None = the default entry (Leon, Village).
SELECTION: dict = {"player": None, "stage": None}


def request(character=None, stage=None) -> dict:
    """The next Select Player / Select Stage picks (MercMode's DJ queue, `game.launch.mercmode.selection`): a character
    by name or index, a stage by index or name; None keeps the default entry. Returns the names it will steer to."""
    player = None
    if character is not None:
        player = character if isinstance(character, int) and not isinstance(character, bool) else next(
            (i for i, n in enumerate(CHARACTERS) if n.casefold() == str(character).casefold()), None)
        if player is None or not 0 <= player < len(CHARACTERS):
            raise ValueError(f"RE4 has no character {character!r} (one of {', '.join(CHARACTERS)})")
    where = None
    if stage is not None:
        where = stage if isinstance(stage, int) and not isinstance(stage, bool) else next(
            (i for i, n in enumerate(STAGES) if n.casefold() == str(stage).casefold()), None)
        if where is None or not 0 <= where < len(STAGES):
            raise ValueError(f"RE4 has no stage {stage!r} (0-{len(STAGES) - 1}: {', '.join(STAGES)})")
    SELECTION.update(player=player, stage=where)
    return {"character": CHARACTERS[player or 0], "stage": STAGES[where or 0],
            "player_index": player or 0, "stage_index": where or 0}


def selection_moves(where: str) -> tuple:
    """The cursor moves from the default entry to the requested one on a select screen (() = confirm the default)."""
    if where == "select_player":
        return ("dright",) * int(SELECTION.get("player") or 0)
    if where == "select_stage":
        return STAGE_MOVES[int(SELECTION.get("stage") or 0)]
    return ()

# The Switch default controls, from Capcom's official RE4 Switch manual (pages 6-7, 10; docs/research/
# mercenaries-character-specials.md 1.1, source S37): ready weapon ZL (aim with the right stick while it is held), fire
# ZL + ZR, reload ZL + B, knife L (+ ZR), action Y (every melee prompt: "(Y) KICK"), run B + stick up, 180 turn B +
# stick down, R "Give orders" - in Mercenaries Krauser's Plaga arm, NOT reload (the first cut had RELOAD_BTN = "r").
CONTROLS_READY = True                            # live-confirmed 2026-11-04 on lilspark/Citron (in-round send_input)
AIM_BTN, FIRE_BTN = "zl", "zr"                   # zl held = the gun up (the red laser), zr tapped = a shot; a = menu confirm
RELOAD_BTN = "b"                                 # with AIM_BTN held: ZL + B is the reload (B alone with the stick runs)
RELOAD_KEYS = (AIM_BTN, RELOAD_BTN)
ACTION_BTN = "y"                                 # the melee prompts ("(Y) KICK"), doors, pickups
KNIFE_BTN = "l"                                  # L readies the knife, L + ZR slashes
SPECIAL_BTN = "r"                                # "Give orders": Krauser's arm in Mercenaries
TURN = {"left": "lleft", "right": "lright"}      # RE4 is tank-controlled: the left stick turns. The d-pad is item select
AIM_TURN = {"left": "rleft", "right": "rright"}  # with the gun up the RIGHT stick moves the aim (the manual; not yet live)

DPAD = {"up": "dup", "down": "ddown", "left": "dleft", "right": "dright"}

# Round entry (measured live 2026-11-04, docs/research/re4-switch-round-gate.md): the stage loads with intro banners up and
# holds the whole round behind them. A pages them; one press is not enough, three start the clock, more are harmless.
INTRO_PRESSES, INTRO_GAP_S = 3, 0.9


def round_entry_events() -> list[dict]:
    """One A press in the shape SwitchLinuxAdapter.send_input takes."""
    return [{"key": "a", "down": True}, {"key": "a", "down": False}]


# ---------------------------------------------------------------------------
# Memory helpers (little-endian ARM64, as re5_switch).
# ---------------------------------------------------------------------------
def _rows(m):
    """The guest's readable rows [(start, end, perms)] in guest addresses (re5_switch._rows)."""
    ad = getattr(m, "adapter", None)
    guest = getattr(ad, "_guest", None)
    if callable(guest):
        try:
            _pid, arena = guest()
        except Exception:                                   # noqa: BLE001 - not booted yet
            return []
        shift = 0 if getattr(ad, "address_mode", "direct") == "direct" else arena.get("base", 0)
        return [(s - shift, e - shift, p) for s, e, p in arena.get("mapped", [])]
    rows = getattr(m, "rows", None)
    return list(rows() if callable(rows) else rows or [])


def module_base(m) -> int | None:
    """main's load address this boot: cached on m, re-checked by one signature read. None until SIGNATURE is measured."""
    if SIGNATURE is None or SIG_OFF is None:
        return None
    cached = getattr(m, "module_base", None)
    for base in ((cached,) if isinstance(cached, int) else ()) + KNOWN_BASES:
        try:
            if bytes(m.rd(base + SIG_OFF, len(SIGNATURE))) == SIGNATURE:
                if base != cached:
                    try:
                        m.module_base = base
                    except AttributeError:
                        pass
                return base
        except (ValueError, OSError):
            pass
    for s, e, p in _rows(m):
        if not p.startswith("r") or "w" in p:
            continue
        step = 1 << 24
        for off in range(s, e, step):
            n = min(step + len(SIGNATURE), e - off)
            try:
                chunk = bytes(m.rd(off, n))
            except (ValueError, OSError):
                break
            i = chunk.find(SIGNATURE)
            if i >= 0:
                found = off + i - SIG_OFF
                try:
                    m.module_base = found
                except AttributeError:
                    pass
                return found
    return None


def ptr_ok(p) -> bool:
    return isinstance(p, int) and PTR_LO <= p < PTR_HI


def u32(m, a) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def u64(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _anchor(m, base, off) -> int:
    """The pointer a static anchor holds (module_base + off -> a manager pointer). 0 when the anchor is None/unset."""
    if off is None or base is None:
        return 0
    try:
        return u64(m, base + off)
    except (ValueError, OSError, struct.error):
        return 0


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


_EMPTY = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
          "combo": None, "combo_timer": None, "max_combo": None, "mercenaries_phase": None}


def read_rows(m, base: int, rows=BSS_ROWS) -> list:
    """[(address, bytes)] of the module's data + bss, one read per measured host row (a row that fails is left out)."""
    out = []
    for off, n in rows:
        try:
            out.append((base + off, bytes(m.rd(base + off, n))))
        except (ValueError, OSError):
            continue
    return out


def _np():
    import numpy
    return numpy


def clock_candidates(before: list, after: list, dt: float) -> list:
    """[(address, before, after)] of every f32 that read CLOCK_LO..CLOCK_HI in `before` and had fallen by dt x CLOCK_RATE
    in `after` (both [(address, bytes)] reads of the same rows, `dt` wall seconds apart)."""
    np = _np()
    lo, hi = dt * CLOCK_RATE[0], dt * CLOCK_RATE[1]
    after_at = {a: d for a, d in after}
    out = []
    for a, d0 in before:
        d1 = after_at.get(a)
        if d1 is None or len(d1) != len(d0):
            continue
        n = len(d0) // 4 * 4
        f0 = np.frombuffer(d0[:n], dtype="<f4")
        f1 = np.frombuffer(d1[:n], dtype="<f4")
        with np.errstate(all="ignore"):
            drop = f0 - f1
            ok = np.isfinite(f0) & np.isfinite(f1) & (f0 >= CLOCK_LO) & (f0 <= CLOCK_HI) & (drop >= lo) & (drop <= hi)
        out += [(a + 4 * int(i), float(f0[i]), float(f1[i])) for i in np.nonzero(ok)[0]]
    return out


CLOCK_GROUP_S = 0.05                    # survivors reading within this of each other are copies of one clock


def pick_clock(cands: list) -> int | None:
    """The clock among the survivors: the biggest group of copies reading the same (the 2026-11-05 clock was 78 copies
    0x30 apart; a stray countdown is one float - on 2026-11-10 a lone timer at 26 s was taken at a round's start while
    the HUD read 1:59), the higher reading between equal groups, the lowest address of the group."""
    if not cands:
        return None
    groups: list = []
    for c in sorted(cands, key=lambda c: c[2]):
        if groups and c[2] - groups[-1][-1][2] <= CLOCK_GROUP_S:
            groups[-1].append(c)
        else:
            groups.append([c])
    best = max(groups, key=lambda g: (len(g), max(c[2] for c in g)))
    return min(c[0] for c in best)


class ClockFinder:
    """The round clock, found and then followed (one per boot, kept on m.re4_clock). observe() reads the bss every call
    until a clock is found (two reads CLOCK_DT apart, see clock_candidates), then one f32 a call. A found clock that
    stops moving for CLOCK_STALE_S is searched for again the same way (a pause also holds it, so that costs nothing)."""

    def __init__(self):
        self.addr: int | None = None
        self.sample = None                      # (wall time, rows) of the first read of a search
        self.last: tuple | None = None          # (wall time, value) of the last change
        self.found_at = None
        self.searches = 0

    def observe(self, m, base: int, now: float) -> float | None:
        if self.addr is not None:
            try:
                v = struct.unpack("<f", bytes(m.rd(self.addr, 4)))[0]
            except (ValueError, OSError, struct.error):
                v = None
            if v is None or not math.isfinite(v) or not -1.0 <= v <= CLOCK_MAX_S:
                self.addr = self.last = None                # gone: search again
                return None
            if self.last is not None and v < self.last[1] - (now - self.last[0]) * CLOCK_RATE[1] - CLOCK_JUMP_S:
                # it fell faster than the round's time runs (live 2026-11-10 21:00: 143 -> 95 in 2 s during the
                # intro): not the clock - search again (a bonus only ever adds time)
                self.rejects = self.__dict__.get("rejects", 0) + 1
                self.addr = self.last = self.sample = None
                return None
            if self.last is None or v != self.last[1]:
                self.last = (now, v)
            elif now - self.last[0] >= CLOCK_STALE_S and v > 0:
                self.addr, self.sample, self.last = None, None, None   # held: confirm it again from the next call
            return round(max(v, 0.0), 2)
        if self.sample is None or now - self.sample[0] > CLOCK_DT[1]:
            self.sample = (now, self._rows(m, base))
            self.searches += 1
            return None
        dt = now - self.sample[0]
        if dt < CLOCK_DT[0]:
            return None
        rows = self._rows(m, base)
        addr = pick_clock(clock_candidates(self.sample[1], rows, dt))
        self.sample = (now, rows)
        if addr is None:
            return None
        self.addr, self.found_at = addr, now
        return self.observe(m, base, now)

    @staticmethod
    def _rows(m, base):
        return read_rows(m, base, tuple((off, 4) for off in CLOCK_HINTS)) + read_rows(m, base)


def unit_addresses(chunks: list, vtables: dict) -> dict:
    """{class offset: [object addresses]} of the 8-aligned words in `chunks` ([(address, bytes)]) that equal one of
    `vtables` ({absolute vtable address: class offset}): a C++ object starts with its vtable pointer."""
    np = _np()
    out: dict = {off: [] for off in vtables.values()}
    keys = np.array(sorted(vtables), dtype="<u8")
    for a, d in chunks:
        lead = (-a) % 8
        n = (len(d) - lead) // 8 * 8
        if n <= 0:
            continue
        q = np.frombuffer(d[lead:lead + n], dtype="<u8")
        for i in np.nonzero(np.isin(q, keys))[0]:
            out[vtables[int(q[i])]].append(a + lead + 8 * int(i))
    return out


def read_unit(m, addr: int) -> dict | None:
    """One unit's fields (only the configured offsets), None when a read fails or its position is not a position."""
    try:
        raw = bytes(m.rd(addr, max(U_TYPE + 1, (U_POS or 0) + 12, (U_YAW or 0) + 4, (U_HP_MAX or 0) + 2)))
    except (ValueError, OSError):
        return None
    out = {"ptr": addr, "vtable": struct.unpack_from("<Q", raw, 0)[0], "hp": struct.unpack_from("<H", raw, U_HP)[0],
           "type": raw[U_TYPE], "id": struct.unpack_from("<I", raw, U_ID)[0]}
    if U_HP_MAX is not None:
        out["hp_max"] = struct.unpack_from("<H", raw, U_HP_MAX)[0]
    if U_POS is not None:
        pos = struct.unpack_from("<3f", raw, U_POS)
        if not all(math.isfinite(v) and abs(v) < 1e6 for v in pos):
            return None
        out["pos"] = pos
    if U_YAW is not None:
        yaw = struct.unpack_from("<f", raw, U_YAW)[0]
        out["rot"] = wrap(yaw) if math.isfinite(yaw) else None
    return out


class UnitCensus:
    """The units of the configured classes (PLAYER_CLASS, ENEMY_CLASSES), found by their vtable word in the heap and
    then read in place (one per boot, kept on m.re4_units). The first scan covers HEAP_WINDOWS; later scans (every
    UNIT_RESCAN_S, for new spawns) only the pool the first one found (+- POOL_MARGIN), so a round costs one full scan."""

    POOL_MARGIN = 1 << 22

    def __init__(self):
        self.units: dict = {}                   # address -> class offset
        self.pool: tuple | None = None
        self.scanned_at = None
        self.scans = 0

    @staticmethod
    def classes() -> tuple:
        return tuple(dict.fromkeys(c for c in (player_classes() + tuple(ENEMY_CLASSES)) if c is not None))

    def refresh(self, m, base: int, now: float) -> None:
        if not self.classes() or (self.scanned_at is not None and now - self.scanned_at < UNIT_RESCAN_S):
            return
        self.scanned_at = now
        vt = {base + c: c for c in self.classes()}
        found: dict = {}
        for lo, hi in ([self.pool] if self.pool else list(HEAP_WINDOWS)):
            for a in range(lo, hi, UNIT_SCAN_CHUNK):
                try:
                    chunk = [(a, bytes(m.rd(a, min(UNIT_SCAN_CHUNK, hi - a))))]
                except (ValueError, OSError):
                    continue
                for cls, addrs in unit_addresses(chunk, vt).items():
                    found.update((x, cls) for x in addrs)
        self.scans += 1
        if found:
            self.units = found
            if self.pool is None:
                self.pool = (max(min(found) - self.POOL_MARGIN, 0), max(found) + self.POOL_MARGIN)

    def read(self, m, base: int) -> tuple:
        """(player unit or None, [enemy units]), one read each, deduplicated by id + health + type (the arena shows
        some objects through two mappings, 2026-11-05)."""
        player, enemies, seen = None, [], set()
        for addr, cls in sorted(self.units.items()):
            u = read_unit(m, addr)
            if u is None or u["vtable"] != base + cls or u["hp"] > UNIT_HP_MAX or "pos" not in u:
                continue
            key = (u["id"], u["hp"], u["type"], cls)
            if key in seen:
                continue
            seen.add(key)
            u["class"] = cls
            if cls in player_classes() and player is None:
                player = u
            elif cls in ENEMY_CLASSES:
                u["slot"] = len(enemies)                 # the census order (address order), as re5_switch's slot
                enemies.append(u)
        return player, enemies


def player_unit(m, base: int) -> dict | None:
    """The player's unit through the bss pointer (S_PLAYER, then S_PLAYER_2), checked by its class's vtable word."""
    if PLAYER_CLASS is None or U_POS is None:
        return None
    for off in (S_PLAYER, S_PLAYER_2):
        if off is None:
            continue
        try:
            p = u64(m, base + off)
        except (ValueError, OSError, struct.error):
            continue
        if not ptr_ok(p):
            continue
        u = read_unit(m, p)
        if u is None or "pos" not in u:
            continue
        classes = player_classes()
        cls = next((c for c in classes if u["vtable"] == base + c), None)
        if cls is None:
            off = u["vtable"] - base
            lo, hi = PLAYER_VTABLE_RANGE
            if lo <= off < hi and off not in ENEMY_CLASSES and off not in SET_OBJECT_CLASSES and off % 8 == 0:
                cls = off                               # another character's class, through the player pointer
        if cls is not None:
            u["class"] = cls
            SEEN_PLAYER_CLASSES[cls] = SEEN_PLAYER_CLASSES.get(cls, 0) + 1
            return u
    return None


def _finder(m, name, kind):
    obj = getattr(m, name, None)
    if not isinstance(obj, kind):
        obj = kind()
        try:
            setattr(m, name, obj)
        except AttributeError:
            pass
    return obj


def snapshot(m, now: float | None = None, search: bool = True) -> dict:
    """The round from RAM in re5_switch.snapshot's shape, reading only what has been measured (every read guarded):
      timer   : the clock (ClockFinder), seconds; clock_addr says where it was found
      player  : {ptr, pos (x, y, z cm), rot (rad), hp, hp_max, class} once PLAYER_CLASS and U_POS are set
      enemies : [{ptr, pos, rot, hp, hp_max, class, id}] of ENEMY_CLASSES (the census)
      kills / combo / score : the MERC_* fields once measured (None until then: the bot counts kills from the census)
    search=False (the menus' screen(), a warm probe) reads a clock and units found before but scans for neither.
    """
    now = time.monotonic() if now is None else now
    snap: dict = dict(_EMPTY, enemies=[])
    base = module_base(m)
    if base is None:
        return snap
    snap["module_base"] = base
    clock = _finder(m, "re4_clock", ClockFinder)
    if search or clock.addr is not None:
        snap["timer"] = clock.observe(m, base, now)
    snap["clock_addr"] = clock.addr
    census = _finder(m, "re4_units", UnitCensus)
    if census.classes() and U_POS is not None:
        if search:
            census.refresh(m, base, now)
        player, enemies = census.read(m, base)
        player = player_unit(m, base) or player       # the bss pointer first: no scan needed for him
        if player is not None:
            if not PLAYER_HP_IN_UNIT:
                player["hp"] = player["hp_max"] = None     # his +0x3c2 is not his life (measured, see U_ID above)
            player.setdefault("hp_max", None)
            player.setdefault("rot", None)
            snap["player"] = player
        snap["enemies"] = [dict(e, hp_max=e.get("hp_max")) for e in enemies]
    if KILL_CANDIDATES:
        cand = {}
        for off in KILL_CANDIDATES:
            try:
                cand[hex(off)] = struct.unpack("<I", bytes(m.rd(base + off, 4)))[0]
            except (ValueError, OSError, struct.error):
                pass
        snap["kill_candidates"] = cand
    for key, off in (("kills", MERC_KILLS), ("combo", MERC_COMBO), ("score", MERC_SCORE)):
        if off is not None:
            try:
                v = struct.unpack("<I", bytes(m.rd(base + off, 4)))[0]
            except (ValueError, OSError, struct.error):
                continue
            if key != "kills" or v <= MERC_KILLS_MAX:       # an implausible count: the census counts instead
                snap[key] = v
    return snap


def own_screen(snap: dict) -> str:
    """playing / dead / results / story / loading from the round's own fields (mirrors re4_gc.own_screen, with the
    merc phase when the port exposes one). Conservative: unknown stays "loading", so the walk reads the frame instead."""
    p = snap.get("player")
    room, phase = snap.get("room"), snap.get("mercenaries_phase")
    if phase == PHASE_OVER:
        return "results"
    if not p:
        return "loading"
    # A room outside the Mercenaries stage range (0x04RR on the GC build) is the story, which the bot never plays.
    if room is not None and (room >> 8) != 0x04:
        return "story"
    timer = snap.get("timer")
    if timer is not None and not 0 < timer <= CLOCK_MAX_S:
        return "results"
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    if phase in (None, PHASE_PLAYING):
        return "playing"
    return "loading"


# ---------------------------------------------------------------------------
# Menu walk: title -> main menu -> EXTRAS -> THE MERCENARIES -> GAME START -> Select Player -> Select Stage -> round.
# Reads the capture frame, because the title task's menu state has no RAM anchor yet. A press goes in only on a screen a
# frame has named, and a confirm only on the row the walk wants. No BOOT_KEY: mercs_bot.Boot presses it on "unknown",
# and an unnamed screen is exactly where a blind A does harm (11-06: A presses went LOAD -> a story save -> the merchant).
# ---------------------------------------------------------------------------
# A confirm takes a moment to show, and the menus accept input while they fade. A second A in that moment lands on the
# next screen's default row: LOAD from the title, SEPARATE WAYS from the main menu. So each screen takes one confirm
# per gap, however long the picture takes to change.
CONFIRM_GAP_S = {"title": 5.0, "main_menu": 3.0, "extras_menu": 3.0, "mercs_title": 3.0, "select_player": 3.0,
                 "select_stage": 5.0, "round_intro": INTRO_GAP_S, "dead_continue": 3.0}
_confirmed: dict[str, float] = {}

# A stray confirm can still land on LOAD (a boot press on an unnamed screen, an operator tap) and the story save list
# then holds the walk for as long as nothing acts on it: measured 2026-11-07, the bot reached that list and produced
# identical frames for 260 s. The run used to end there ("story game"); it now cancels back out first, because the walk
# is still perfectly able to reach THE MERCENARIES once the menu is back. The budget keeps a title that genuinely
# refuses to leave the list from being cancelled at forever.
STORY_RECOVER_KEY = "b"
STORY_UP_KEY = "dup"                 # Cancel loading?'s cursor up to Yes
STORY_RECOVER_MAX = 4
STORY_GAP_S = 2.0
STORY_ANSWER_GAP_S = 0.8
_story_presses = 0
_story_last = float("-inf")          # a fresh walk may cancel straight away


def begin_run(selection=None, **_turn) -> None:
    """A new walk (mercs_bot.play, re4switch_bot.play): no confirm is outstanding, the story-list recovery starts
    fresh, and the DJ's pick (a MercMode selection dict: character, stage / stage_name) is what the selects steer to;
    without one they confirm the default entries."""
    global _story_presses, _story_last
    _confirmed.clear()
    _story_presses, _story_last = 0, float("-inf")
    SELECTION.update(player=None, stage=None)
    if isinstance(selection, dict):
        stage = selection.get("stage")
        request(selection.get("character"), stage if stage is not None else selection.get("stage_name"))


def _story_answer(key: str, now: float | None = None) -> str | None:
    """The Cancel loading? answer (up, then A on Yes), paced like the cancels; not counted against their budget."""
    global _story_last
    now = time.monotonic() if now is None else now
    if now - _story_last < STORY_ANSWER_GAP_S:
        return None
    _story_last = now
    return key


def _recover_story(now: float | None = None) -> str | None:
    """A cancel out of the story save list, or None while the gap or the budget says wait."""
    global _story_last
    now = time.monotonic() if now is None else now
    if _story_presses >= STORY_RECOVER_MAX or now - _story_last < STORY_GAP_S:
        return None
    _story_last = now
    return STORY_RECOVER_KEY


def _reader(m) -> screens.Reader:
    reader = getattr(m, "re4_screens", None)
    if reader is None:
        reader = screens.Reader()
        m.re4_screens = reader
    return reader


def screen(m, merc=None) -> dict:
    """Where RE4 is, for the menus loop (gbox.mercs_bot). The round's own RAM fields win once they are measured; until
    then, and on every menu, the capture frame. A frame that cannot be taken names nothing, so nothing is pressed."""
    snap = merc if isinstance(merc, dict) else snapshot(m, search=False)
    where = own_screen(snap)
    if where in ("playing", "dead", "results", "story"):
        return {"where": where, "cursor": None, "target": None}
    ad = getattr(m, "adapter", None)
    try:
        scr = _reader(m).read(ad.get_frame())
    except Exception as exc:                                # noqa: BLE001 - no frame yet (booting), or a torn one
        return {"where": "unknown", "cursor": None, "target": None, "frame_error": type(exc).__name__}
    if scr["where"] == "main_menu":
        scr["target"] = EXTRAS_ROW
    elif scr["where"] == "extras_menu":
        scr["target"] = MERCENARIES_ROW
    return {"cursor": None, "target": None, "reader": _reader(m), **scr}


def _confirm(where: str, now: float | None = None) -> str | None:
    now = time.monotonic() if now is None else now
    return "a" if now - _confirmed.get(where, float("-inf")) >= CONFIRM_GAP_S[where] else None


def step(scr: dict, now: float | None = None) -> str | None:
    """One press toward the next round, or None to wait. Never a press on a screen no frame has named."""
    where = scr.get("where")
    if where == "story_prompt" and scr.get("prompt") == "cancel":
        # "Cancel loading? Yes / No": B is No, back to the list, whose B opens this again (live 2026-11-10: ten
        # minutes in that loop). Yes leaves LOAD: up to it, then A (re4_switch_screens.prompt_kind reads the cursor)
        return _story_answer("a" if scr.get("cursor") == "yes" else STORY_UP_KEY, now)
    if where in ("story", "story_prompt"):                  # the story save list and its confirm: cancel, never confirm
        return _recover_story(now)
    if where in ("main_menu", "extras_menu"):
        cur, tgt = scr.get("cursor"), scr.get("target")
        if not isinstance(cur, int) or not isinstance(tgt, int):
            return None
        if cur == tgt:
            return _confirm(where, now)
        return DPAD["down"] if cur < tgt else DPAD["up"]
    if where in ("select_player", "select_stage"):
        # the DJ's pick: move from the default entry first (the reader counts the moves in: scr["moved"]), then confirm
        moves, done = selection_moves(where), int(scr.get("moved") or 0)
        if done < len(moves):
            return moves[done]
        return _confirm(where, now)
    if where in ("title", "mercs_title", "round_intro"):
        return _confirm(where, now)                         # these match the reference, so the default entry is up
    if where == "dead_continue":
        # "You Are Dead - Continue Yes / No", the cursor on Yes (measured frame): Yes plays the stage again. Measured
        # 2026-11-10: the frame-only playbook sat on this screen until MercMode's no-progress cut
        return _confirm(where, now)
    return None


# The walk's pace (re4switch_bot), closed on the frame. Measured 2026-11-09/10: at one press per 3.0 s the main menu
# alone took 12 s (LOAD -> EXTRAS is four steps), which is what put the walk inside the old stall escape's 12 s. A move
# now goes in every MOVE_GAP_S once the last one has shown on the read cursor (MOVE_RETRY_S without it: again); a
# confirm waits until its screen has been named SETTLE_S (a press during the fade-in is dropped) and, on a cursor
# menu, until two reads in a row agree the cursor is on the target. CONFIRM_GAP_S above still keeps a second confirm
# off a screen that is fading out (the double A that lands on LOAD).
MOVE_GAP_S, MOVE_RETRY_S = 0.8, 2.0
SETTLE_S, CONFIRM_AFTER_S = 1.0, 0.8
CURSOR_MENUS = ("main_menu", "extras_menu")


def next_is_move(scr: dict) -> bool:
    """Whether step(scr) would move a cursor (rather than confirm, cancel or wait)."""
    where = scr.get("where")
    if where in CURSOR_MENUS:
        cur, tgt = scr.get("cursor"), scr.get("target")
        return isinstance(cur, int) and isinstance(tgt, int) and cur != tgt
    if where in ("select_player", "select_stage"):
        return int(scr.get("moved") or 0) < len(selection_moves(where))
    return False


class Pace:
    """When the walk's next press may go in (see MOVE_GAP_S): observe() every read, ready() before step(), pressed()
    after a press."""

    def __init__(self):
        self.where, self.since = None, None
        self.last_press = float("-inf")
        self.moved_from = None                  # the cursor a move left from, until a read shows it elsewhere
        self.on_target = 0                      # reads in a row with the cursor on the target

    def observe(self, scr: dict, now: float) -> None:
        where = scr.get("where")
        if where != self.where:
            self.where, self.since, self.moved_from, self.on_target = where, now, None, 0
        if where in CURSOR_MENUS:
            cur = scr.get("cursor")
            self.on_target = self.on_target + 1 if isinstance(cur, int) and cur == scr.get("target") else 0
            if self.moved_from is not None and cur != self.moved_from:
                self.moved_from = None          # the last move showed

    def ready(self, scr: dict, now: float) -> bool:
        if next_is_move(scr):
            if now - self.last_press < MOVE_GAP_S:
                return False
            return self.moved_from is None or now - self.last_press >= MOVE_RETRY_S
        if self.since is None or now - self.since < SETTLE_S or now - self.last_press < CONFIRM_AFTER_S:
            return False
        return scr.get("where") not in CURSOR_MENUS or self.on_target >= 2

    def pressed(self, scr: dict, key: str, now: float) -> None:
        self.last_press = now
        self.moved_from = scr.get("cursor") if key in DPAD.values() and scr.get("where") in CURSOR_MENUS else None


def press_gap(scr: dict) -> float:
    """How long the walk waits after the last press before the next one on this screen: a select screen's cursor move
    (the DJ's pick, still owed) goes in every STEER_GAP_S, every other press keeps its screen's confirm gap."""
    where = scr.get("where")
    if where in ("select_player", "select_stage") and int(scr.get("moved") or 0) < len(selection_moves(where)):
        return STEER_GAP_S
    return CONFIRM_GAP_S.get(where, 3.0)


def wandered(scr: dict) -> str | None:
    """The run must end: a story game (the bot never plays RE4's story).

    A story *screen* is not a story game: the walk cancels out of it (`step`) and keeps going. Only when the recovery
    budget is spent does the run end, because then the list is where this title is stuck.
    """
    if scr.get("where") in ("story", "story_prompt"):
        return "story game" if _story_presses >= STORY_RECOVER_MAX else None
    return None


def pressed(scr: dict, key: str, now: float | None = None) -> None:
    """A menu press went in: starts that screen's confirm gap, and counts an intro page or a story-list cancel."""
    global _story_presses
    if key == "a" and scr.get("where") in CONFIRM_GAP_S:
        _confirmed[scr["where"]] = time.monotonic() if now is None else now
    if key == STORY_RECOVER_KEY and scr.get("where") in ("story", "story_prompt"):
        _story_presses += 1
    reader = scr.get("reader")
    if callable(getattr(reader, "press_went_in", None)):
        reader.press_went_in(scr.get("where"), key)


def warm_probe(m) -> dict:
    """gbox.mercs.warm_boot boot observer: a stable screen where the warm pool may pause the boot, read-only."""
    out = {"ready": False, "screen": "unknown", "title": MAP_ID}
    base = module_base(m)
    if base is None:
        return out
    where = screen(m).get("where", "unknown")
    if where in ("title", "main_menu", "extras_menu", "select_player", "select_stage", "mercs_title"):
        return out | {"ready": True, "screen": where, "token": ("re4sw", base, where)}
    return out | {"screen": where}


# ---------------------------------------------------------------------------
# Driver + first-cut combat brain.
# ---------------------------------------------------------------------------
class RE4Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # The Mercenaries on Switch is played solo on P1 here
    units_per_m = 1000.0                        # mm, measured (doctrine.view, the atlas): see MM_PER_CM below
    round_counters = ("shots", "hits", "turns", "backoffs", "holds", "dying", "escapes", "locates", "stand_breaks",
                      "crowd_picks", "kills_seen")

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        return re4_nav.attach(snapshot(m))             # snap["nav"]: the stage's floor mesh (the tactical map's too)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        return own_screen(snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        self.stats = stats
        return Bot(stats=stats, clock=clock, director=False)    # the engine runs the round's doctrine itself

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "mode": "mercenaries"}


# Combat gates (operator's hard rules, memory gbox-bot-no-wall-shots-no-mine-standing): the bot must not shoot walls
# (fire only with a clear line of sight to the target) and must not stand on / near its own explosives. RE4 classic
# Mercenaries has no player-placed proximity mines (that is an RE5 mod), so the mine gate is a parity hook that stays
# inert here unless a hazard list is ever populated. The line-of-sight gate reads the stage's obstacle / navmesh data
# once it is mapped (snap["nav"] / snap["obstacles"], mirroring re5_switch_native_nav / gbox.mercs.obstacle_map);
# until then it cannot confirm a clear shot, so the bot fires only inside ENGAGE_RANGE_CM and when tightly aligned
# (a conservative default that limits long-range blind fire through geometry).
# UNITS (2026-11-10, measured): RE4 Switch's world is in MILLIMETRES - the room collision is the GameCube SAT to 0.1 mm
# (re4_switch_nav) and a live player position read x 50,689 on Village (50 m, not 500). The names below keep their
# historical _CM suffix; their values are the same distances in the game's mm (x MM_PER_CM). Before this the fight
# took every Ganado for 10x farther than he was: live it never fired (0 shots over 8 rounds) and walked into them.
MM_PER_CM = 10.0
ENGAGE_RANGE_CM = 1200.0 * MM_PER_CM                 # do not blind-fire past ~12 m before the line-of-sight gate is wired (tune live)
MINE_CLEAR_CM = 250.0 * MM_PER_CM                    # keep at least this far from an own hazard (parity with re5_switch_mines)

# The fight (gbox.mercs.core.doctrine: never idle, shoot on sight, the combo every 2-5 s, crowds, locate by the map).
# RE4 is tank-controlled and stands still while it aims: the gun comes up only once the body is within RAISE_TOL of the
# target (the right stick then fine-turns the aim, the trigger is tapped inside TURN_TOL once the gun has been up
# AIM_READY_S), and every tick without a shot moves him: a step on open ground when he has stood STAND_MAX_S, the walk
# to the nearest Ganado by the map when none is in range. Distances are the game's units (mm, units_per_m 1000: the
# constants are written in cm x MM_PER_CM). An error > 0 turns LEFT (the GameCube convention re4_walk steers by; a
# live facing read, U_YAW, would confirm it: re4_walk.TURN_POSITIVE flips the walk in one place).
RAISE_TOL = 0.35                         # rad: the body this close to the target, the gun comes up
AIM_READY_S = 0.25                       # the gun up this long before the first tap (a tap as it rises is not a shot)
RUN_BTN = "b"                            # held with the stick up: a run (the manual: B + left stick up)
RUN_CM = 800.0 * MM_PER_CM                           # locating a Ganado farther than this: run, not walk
QUICK_TURN = ("ldown", RUN_BTN)          # the 180 turn (the manual: B + left stick down), the escape from a crowd
RELOAD_SHOTS = 8                         # shots since the last reload: reload (ZL + B) at the next quiet moment (no
                                         # ammo read yet; a reload on a full magazine costs a moment and nothing else)
RELOAD_CLEAR_CM = 350.0 * MM_PER_CM                  # ... quiet = nobody this near (doctrine IMPEDE_M)
CROWD_N, CROWD_CM = 4, 600.0 * MM_PER_CM             # a mob (doctrine CROWD_N / CROWD_M)
CROWD_CONE = 0.6                         # rad: in a mob, the Ganado nearest the gun's line within this is the target
SWARM_N, SWARM_CM = 3, 200.0 * MM_PER_CM             # this many this close: turn and go (he cannot shoot three at arm's length)
STAND_MAX_S, STAND_MOVE_CM, STAND_STEP_S = 1.5, 40.0 * MM_PER_CM, 0.8   # never stand: no metre in 1.5 s and no shot -> a step
SWEEP_S = 3.0                            # nobody on the map: walk, turning this long one way, then the other
KILL_PACE_S = 3.0                        # doctrine.KILL_PACE_S: from this long after a kill the next one is owed
COMBO_WINDOW_S = 5.0                     # doctrine.COMBO_MAX_S: a kill later than this after the last one breaks the combo
FIRE_GAP_S = 0.25                        # between trigger taps (a tap is down + up: the engine never holds the trigger)
# The shot's tolerance is the angle a Ganado's body covers at his distance (live 2026-11-10 22:07: 11 hits from 166
# shots with a flat 7-degree tolerance - 1.5 m off at 12 m): atan(FIRE_HALF_WIDTH_MM / distance), never under
# FIRE_TOL_MIN; inside AIM_NUDGE of it the right stick is tapped (a frame of turn) rather than held.
FIRE_HALF_WIDTH_MM, FIRE_TOL_MIN, AIM_NUDGE = 300.0, 0.02, 0.2
# The melee follow-up (docs/research/mercenaries-character-specials.md 2.1 / 6.1): RE4's Mercenaries is played shot ->
# stun -> the action button at the prompt (Leon's roundhouse / suplex, Krauser's double kick, HUNK's neckbreaker,
# Wesker's thrust punch, Ada's fan kick): a melee is a near-certain kill, hits the crowd round it and costs no ammo.
# The stun itself is not read from RAM yet, so the bot takes a Ganado whose health just fell (a hit, which is what
# stuns) within MELEE_MM in front, with nobody else at arm's reach (MELEE_CLEAR_MM: a melee's recovery in a crowd
# is how a bot gets grabbed), steps in to MELEE_REACH_MM and taps Y every MELEE_TAP_S while the window lasts. A Y
# with no prompt does nothing. Distances in mm.
MELEE = True
# The turn sign, checked live by the fight itself (2026-11-10: the stock round turned 4,365 ticks for 19 raises, the
# shape of a turn that runs away from its target): every turn tick compares the bearing error with the last one on
# the same Ganado; TURN_LEARN_N samples with the error growing at least 3x as often as it shrinks (+4) flip
# TURN_SIGN - here and in re4_walk, so the walker follows - and say so in stats (turn_sign, turn_sign_flips).
TURN_SIGN = 1                            # 1: an error > 0 turns left (the GameCube convention); -1: right
# Not in control (live 2026-11-10 21:00: the round intro's "Eliminate as many Ganados ..." after a Continue was not
# named by the frame reader, and the RAM fight turned at a frozen scene for a minute): a never-stand step (a turn
# and a walk) that ran its STAND_STEP_S without his position (FROZEN_MM) or his facing (FROZEN_RAD) changing is a
# scene that waits for a button (an intro text, a death camera) or a Ganado's grab: A tapped every FROZEN_TAP_S (it
# continues the text and is the grab's shake-off mash) until he moves. Aiming and firing never step, so never count.
FROZEN = True
# No clear shot (live 2026-11-10 21:06, Castle: 415 holds, every one the sight gate, 0 kills, a death - he stood
# aiming at a wall while they came): once the sight gate has held the shot SIGHT_HOLD_S he flanks - FLANK_S of the
# walk to the target by the mesh, the gun down - and tries again. Every block is logged (SIGHT_LOG, the wall, where
# the shot met it) so the gate can be judged on real positions.
SIGHT_HOLD_S, FLANK_S = 0.6, 1.5
SIGHT_LOG = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-sight-blocks.jsonl"
SIGHT_LOG_EVERY_S = 1.0
FROZEN_MM, FROZEN_RAD, FROZEN_TAP_S, FROZEN_KEY = 30.0, 0.01, 0.2, "a"
TURN_LEARN, TURN_LEARN_N = True, 16
MELEE_MM, MELEE_REACH_MM, MELEE_CLEAR_MM = 2500.0, 1400.0, 2000.0
MELEE_WINDOW_S, MELEE_TAP_S, MELEE_CONE = 1.6, 0.3, 0.5


@re4_walk.attach                       # .walker (approach(goal) -> stick keys), snap["nav"], the map's marks, plan()
class Bot:
    """One decision per tick from the snapshot (re5_switch.Bot's shape: tick(snap) -> {"hold": keys, "tap": key}).

    In order: an own hazard underfoot -> step off it; a swarm at arm's length -> the quick turn and away; a target in
    range (the nearest; in a mob the one nearest the gun's line; the quickest kill once the combo is owed) -> turn, raise,
    fire through the operator's fire gates; no target in range -> locate the nearest Ganado by the map and walk / run to
    him; nobody known -> sweep the level. The never-stand rule then turns any tick that neither shoots nor moves into a
    step. stats carries what it did (shots, turns, locates, stand_breaks, crowd_picks, combo_owed_s, kills_seen ...)
    and the doctrine's measures (gbox.mercs.core.doctrine.Director, with its commands read back through
    doctrine.Reader: "hunt" / "explore" walk to the map's Ganado, "fight" / "score" fire first)."""

    TURN_TOL = 0.12                                      # rad: close enough to fire
    COUNTERS = ("shots", "hits", "turns", "backoffs", "holds", "dying", "escapes", "locates", "stand_breaks",
                "crowd_picks", "sweeps", "kills_seen", "raises", "combo_breaks", "reloads", "melee_tries",
                "melee_taps", "melee_kills", "frozen_taps", "frozen_spells", "flanks", "visible_picks",
                "blocked_picks")

    def __init__(self, stats: dict | None = None, clock=time.monotonic, director=True):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        for k in self.COUNTERS:
            self.stats.setdefault(k, 0)
        self.target = None
        self.doing, self.why = "idle", ""
        self._hp: dict = {}                              # enemy ptr -> last health (kills from the census)
        self._kill_at = None
        self._last_fire = -1e9
        self._aim_since = None                           # the gun up since (AIM_BTN held), None while it is down
        self._since_reload = 0                           # shots since the last reload
        self._stand = {"pos": None, "at": None, "until": -1e9, "keys": ()}
        self._sweep_at, self._sweep_dir = None, 1
        self._hit_at: dict = {}                          # enemy ptr -> when his health last fell (a hit)
        self._melee_at: dict = {}                        # enemy ptr -> the last Y tap at him
        self._melee_tap = -1e9
        self.walker = None                               # a mesh walker (approach(goal) -> stick keys), when attached
        self.director = self.reader = None
        if director:
            try:
                from ..core import doctrine
                self.director, self.reader = doctrine.Director(self.stats), doctrine.Reader()
            except Exception:                            # noqa: BLE001 - the doctrine never stops a fight
                self.director = self.reader = None

    # --- what he sees ---
    @staticmethod
    def _flat(p, q) -> float:
        return math.hypot(q[0] - p[0], q[2] - p[2])

    def _live(self, p, enemies) -> list:
        """[(distance, bearing error, enemy)] of the living Ganados with a position."""
        rot = p.get("rot") or 0.0
        out = []
        for e in enemies:
            if (e.get("hp") or 0) <= 0 or not e.get("pos"):
                continue
            d = self._flat(p["pos"], e["pos"])
            err = wrap(heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]) - rot)
            out.append((d, err, e))
        return out

    @staticmethod
    def _nearest(p, enemies):
        """The nearest living Ganado (kept for the first cut's callers)."""
        px, _, pz = p["pos"]
        live = [(math.hypot(e["pos"][0] - px, e["pos"][2] - pz), e)
                for e in enemies if (e.get("hp") or 0) > 0 and e.get("pos")]
        return min(live, key=lambda t: t[0])[1] if live else None

    def _count_kills(self, snap, now) -> None:
        """Kills: the game's own counter when it is measured (MERC_KILLS), else a census unit whose health fell to 0."""
        kills = snap.get("kills")
        if isinstance(kills, int) and not isinstance(kills, bool):
            if kills > self.stats.get("kills_seen", 0):
                self._kill_at = now
            self.stats["kills_seen"], self.stats["kills_source"] = kills, "game"
            return
        seen = {}
        for e in snap.get("enemies") or ():
            key = e.get("ptr")
            if key is None:
                continue
            hp = e.get("hp") or 0
            was = self._hp.get(key, 0)
            if was > 0 and hp < was:
                self.stats["hits"] += 1
                self._hit_at[key] = now
            if was > 0 and hp <= 0:
                self.stats["kills_seen"] += 1
                self._kill_at = now
                if now - self._melee_at.get(key, -1e9) <= MELEE_WINDOW_S:
                    self.stats["melee_kills"] += 1          # he went down inside a melee's window
            seen[key] = hp
        self._hp = seen
        self.stats["kills_source"] = "census"

    def combo_owed(self, now) -> float | None:
        """Seconds since the last kill when the next one is owed (KILL_PACE_S), None while the combo is fresh."""
        if self._kill_at is None:
            return None
        since = now - self._kill_at
        return since if since >= KILL_PACE_S else None

    # --- the operator's fire gates ---
    @staticmethod
    def _line_of_sight_ok(p, e, snap) -> bool:
        """No wall shots: a clear ray from Leon to the target. Uses the stage's obstacle / navmesh data when it is
        mapped (snap["nav"] / snap["obstacles"]); until then it cannot prove a wall is in the way, so the caller
        falls back to the ENGAGE_RANGE_CM limit. Returns True = cleared to fire on sight grounds."""
        nav, obstacles = snap.get("nav"), snap.get("obstacles")
        if nav is None and obstacles is None:
            return True                                     # no geometry yet: range limit does the gating
        # a ray test when the geometry has one; else the stage mesh's floor line (re5_nav.NavMesh.floor_segment, which
        # the RE4 room-collision mesh is built to): no linked floor between them is a wall, a drop or a fence
        seg = getattr(nav, "clear_segment", None) or getattr(nav, "floor_segment", None)
        if callable(seg):
            try:
                return bool(seg(tuple(p["pos"]), tuple(e["pos"])))
            except Exception:                               # noqa: BLE001 - a mesh error never fires blind
                return False
        return True

    @staticmethod
    def _near_own_hazard(p, snap) -> bool:
        """No standing on own mines: True if Leon is within MINE_CLEAR_CM of an own explosive. RE4 classic Mercenaries
        has none, so snap has no hazard list and this stays False; kept for parity with the RE5 rule."""
        px, _, pz = p["pos"]
        for h in (snap.get("own_hazards") or snap.get("ground_mines") or []):
            hp = h.get("pos")
            if hp and math.hypot(hp[0] - px, hp[2] - pz) < MINE_CLEAR_CM:
                return True
        return False

    def _may_fire(self, p, e, dist, snap) -> bool:
        """The operator's fire-gates, all of which must pass before a shot: controls confirmed, in range, clear line
        of sight (no wall shots), not on an own hazard (no mine standing)."""
        gate = ("controls" if not CONTROLS_READY else "range" if dist > ENGAGE_RANGE_CM
                else "sight" if not self._line_of_sight_ok(p, e, snap) else "hazard" if self._near_own_hazard(p, snap)
                else None)
        self._gate = gate
        if gate is not None:
            key = "hold_" + gate
            self.stats[key] = self.stats.get(key, 0) + 1
        return gate is None

    # --- the choice ---
    def _choose(self, live, now, p=None, snap=None):
        """(distance, error, enemy) to fight, or None: the quickest kill once the combo is owed, the one nearest the
        gun's line in a mob, else the nearest. Only Ganados inside ENGAGE_RANGE_CM are candidates, and of those the ones
        with a clear shot line first (live 2026-11-10 21:53, Wesker / Base: 48 held shots at Ganados behind real walls -
        the exact triangle test agreed on every one - while others stood round him; dead in 40 s). With none clear, the
        nearest - and self._pick_blocked says so: the fight goes round to him instead of aiming at the wall."""
        self._pick_blocked = False
        near = [t for t in live if t[0] <= ENGAGE_RANGE_CM]
        if not near:
            return None
        if p is not None and snap is not None and (snap.get("nav") is not None or snap.get("obstacles") is not None):
            clear = [t for t in near if self._line_of_sight_ok(p, t[2], snap)]
            if clear:
                if len(clear) < len(near):
                    self.stats["visible_picks"] += 1
                near = clear
            else:
                self._pick_blocked = True
                self.stats["blocked_picks"] += 1
                self.why = "every Ganado in range is behind a wall: round to the nearest"
                return min(near, key=lambda t: t[0])
        crowd = [t for t in near if t[0] <= CROWD_CM]
        if len(crowd) >= CROWD_N:
            lined = [t for t in crowd if abs(t[1]) <= CROWD_CONE]
            if lined:
                self.stats["crowd_picks"] += 1
                self.why = f"crowd fire: {len(crowd)} within {CROWD_CM / 1000:.0f} m, the one on the gun's line"
                return min(lined, key=lambda t: abs(t[1]))
        if self.combo_owed(now) is not None:
            self.why = "the combo is owed: the quickest kill"
            return min(near, key=lambda t: ((t[2].get("hp") or 0) * 0.5 + 300.0 * abs(t[1])) * MM_PER_CM + t[0])
        self.why = "the nearest Ganado"
        return min(near, key=lambda t: t[0])

    def _turn(self, err: float) -> set:
        # an error > 0 turns LEFT with TURN_SIGN 1: the GameCube RE4 / RE5 convention (the Switch world is the
        # GameCube's data - re4_switch_nav), the one re4_walk uses; _learn_turn checks it on every turn tick.
        return {TURN["left"] if (err > 0) == (TURN_SIGN > 0) else TURN["right"]}

    def _aim_turn(self, err: float) -> set:
        return {AIM_TURN["left"] if (err > 0) == (TURN_SIGN > 0) else AIM_TURN["right"]}

    def _learn_turn(self, key, err: float, now: float) -> None:
        """The turn sign's live check (TURN_LEARN): does the error on the same Ganado shrink between turn ticks?"""
        last = self.__dict__.get("_turn_seen")
        self._turn_seen = (key, err, now)
        if not last or last[0] != key or not 0 < now - last[2] <= 0.6 or max(abs(err), abs(last[1])) > 2.8:
            return
        d = abs(err) - abs(last[1])
        name = "turn_converge" if d < -0.02 else "turn_diverge" if d > 0.02 else None
        if name is None:
            return
        self.stats[name] = self.stats.get(name, 0) + 1
        self._turn_tally = t = self.__dict__.get("_turn_tally") or {"c": 0, "v": 0}
        t["c" if name == "turn_converge" else "v"] += 1
        if TURN_LEARN and t["c"] + t["v"] >= TURN_LEARN_N and t["v"] >= 3 * t["c"] + 4:
            flip_turn_sign(self)
            t["c"] = t["v"] = 0
        elif t["c"] + t["v"] >= 4 * TURN_LEARN_N:
            t["c"] = t["v"] = 0                          # a fresh window: the evidence stays recent

    def _command(self, now):
        if self.reader is None:
            return None
        try:
            cmd, _fresh = self.reader.current(self.stats, time.time())
        except Exception:                                # noqa: BLE001
            return None
        return cmd

    # --- the tick ---
    def tick(self, snap: dict, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        p = snap.get("player")
        if not p or p.get("pos") is None:
            self.doing, self.why = "idle", "no player in RAM"
            return {}
        self._count_kills(snap, now)
        if snap.get("kill_candidates"):                # the probe's counters beside the census (KILL_CANDIDATES)
            self.stats["kill_candidates"] = " ".join(f"{k}={v}" for k, v in snap["kill_candidates"].items())
        owed = self.combo_owed(now)
        self.stats["combo_owed_s"] = round(owed, 1) if owed is not None else None
        frozen = self._frozen(p, now)
        if frozen is not None:
            self.stats["doing"], self.stats["why"] = self.doing, self.why
            return frozen
        act = self._fight(p, snap, now)
        act = self._never_stand(p, act, snap, now)
        up = AIM_BTN in set(act.get("hold") or ())
        self._aim_since = (self._aim_since if self._aim_since is not None else now) if up else None
        if self.director is not None:
            try:
                from ..core import doctrine
                self.director.observe(doctrine.view(snap, RE4Switch), act, time.time())
            except Exception:                            # noqa: BLE001 - measuring never costs the tick
                pass
        self.stats["doing"], self.stats["why"] = self.doing, self.why
        return act

    def _fight(self, p, snap, now) -> dict:
        # Step off an own hazard first (no mine standing), even before facing the target.
        live = self._live(p, snap.get("enemies") or [])
        if self._near_own_hazard(p, snap):
            self.stats["backoffs"] += 1
            self.doing, self.why = "backoff", "standing near his own explosive"
            near = min(live, key=lambda t: t[0]) if live else None
            return {"hold": {"lup", TURN["right" if near and near[1] > 0 else "left"]}}
        swarm = [t for t in live if t[0] <= SWARM_CM]
        if len(swarm) >= SWARM_N:
            self.stats["escapes"] += 1
            self.doing, self.why = "escape", f"{len(swarm)} Ganados at arm's length: the quick turn and away"
            return {"hold": set(QUICK_TURN)}
        melee = self._melee(live, now)
        if melee is not None:
            return melee
        cmd = self._command(now)
        pick = self._choose(live, now, p, snap)          # a command never stops a shot at one in range (RE5 HUNT_R)
        if pick is not None:
            dist, err, e = pick
            self.target = e.get("ptr")
            if self.__dict__.get("_pick_blocked"):
                fl = self.__dict__.get("_flank")
                if not fl or fl["key"] != self.target or now >= fl["until"]:
                    self.stats["flanks"] = self.stats.get("flanks", 0) + 1     # no clear line to anyone: go round
                    self._log_block(p, e, snap)
                self._flank = {"key": self.target, "until": now + FLANK_S}
            fl = self.__dict__.get("_flank")
            if fl and fl["key"] == self.target and now < fl["until"]:
                keys, how = self._approach(p, e["pos"], err, snap, run=False)
                self.doing, self.why = "flank", f"no clear shot: round it by {how}"
                return {"hold": keys}
            if abs(err) > RAISE_TOL:
                self.stats["turns"] += 1
                self._learn_turn(self.target, err, now)
                self.doing = "turn"
                return {"hold": self._turn(err)}
            if not self._may_fire(p, e, dist, snap):
                self.stats["holds"] += 1
                if self.__dict__.get("_gate") == "sight":
                    flank = self._sight_blocked(p, e, err, snap, now)
                    if flank is not None:
                        return flank
                self.doing, self.why = "hold", "aligned, but a fire gate blocks the shot"
                return {"hold": {AIM_BTN}}                   # aim kept, no shot
            tol = max(FIRE_TOL_MIN, min(self.TURN_TOL, math.atan2(FIRE_HALF_WIDTH_MM, max(dist, 1.0))))
            if abs(err) > tol:
                self.stats["raises"] += 1
                self.doing = "aim"
                if abs(err) <= AIM_NUDGE:                    # close: a tap of the right stick, not a sweep past him
                    return {"hold": {AIM_BTN}, "tap": next(iter(self._aim_turn(err)))}
                return {"hold": {AIM_BTN} | self._aim_turn(err)}   # the gun up, the right stick turns the aim
            ready = self._aim_since is not None and now - self._aim_since >= AIM_READY_S
            if not ready or now - self._last_fire < FIRE_GAP_S:
                self.doing = "aim"
                return {"hold": {AIM_BTN}}
            self._last_fire = now
            self._since_reload += 1
            self.stats["shots"] += 1
            n = self.stats["shots"]
            self.stats["fire_err_deg"] = round((self.stats.get("fire_err_deg") or 0.0) * (n - 1) / n
                                             + math.degrees(abs(err)) / n, 2)   # the mean bearing error at a shot
            self.doing = "fire"
            # aim held, trigger TAPPED: the engine sends a tap as down+up before the hold, so the shot fires and the aim
            # key stays down. Holding both (the first cut) never released the trigger, so a round fired once and stuck.
            return {"hold": {AIM_BTN}, "tap": FIRE_BTN}
        self.target = None
        if self._since_reload >= RELOAD_SHOTS and not any(t[0] <= RELOAD_CLEAR_CM for t in live):
            # a quiet moment after a magazine's worth of shots: ZL + B (the aim first, then B, in this one batch:
            # re4switch_bot.Keys sends the holds before the tap)
            self._since_reload = 0
            self.stats["reloads"] += 1
            self.doing, self.why = "reload", f"{RELOAD_SHOTS} shots since the last reload and nobody near"
            return {"hold": {AIM_BTN}, "tap": RELOAD_BTN}
        return self._locate(p, live, now, cmd, snap)

    def _melee(self, live, now) -> dict | None:
        """The melee follow-up (MELEE_*): in to a Ganado just hit, then Y at the prompt; None when there is none."""
        if not MELEE:
            return None
        cand = [t for t in live if t[0] <= MELEE_MM and abs(t[1]) <= MELEE_CONE
                and now - self._hit_at.get(t[2].get("ptr"), -1e9) <= MELEE_WINDOW_S]
        if not cand:
            return None
        dist, err, e = min(cand, key=lambda t: t[0])
        if any(t[2] is not e and t[0] <= MELEE_CLEAR_MM for t in live):
            return None                                  # another at arm's reach: the gun, not a melee
        key = e.get("ptr")
        if self.target != key or self.doing != "melee":
            self.stats["melee_tries"] += 1
        self.target, self.doing = key, "melee"
        if dist > MELEE_REACH_MM:
            self.why = f"a Ganado just hit, {dist / 1000:.1f} m: in for the melee"
            return {"hold": {"lup"} | (self._turn(err) if abs(err) > self.TURN_TOL else set())}
        self.why = "the melee prompt: Y"
        if now - self._melee_tap >= MELEE_TAP_S:
            self._melee_tap = now
            self._melee_at[key] = now
            self.stats["melee_taps"] += 1
            return {"hold": set(), "tap": ACTION_BTN}
        return {"hold": set()}

    def _frozen(self, p, now) -> dict | None:
        """A tap of FROZEN_KEY while he is not in control (FROZEN_*), else None."""
        fz = self.__dict__.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})
        pos, rot = tuple(p["pos"]), p.get("rot")
        moved = (fz["pos"] is None or self._flat(fz["pos"], pos) > FROZEN_MM
                 or (rot is not None and fz["rot"] is not None and abs(wrap(rot - fz["rot"])) > FROZEN_RAD))
        if moved:
            fz.update(pos=pos, rot=rot, at=now, on=False)
            return None
        stepped = fz.get("stepped")
        if not FROZEN or stepped is None or stepped < fz.get("at", -1e9) or now - stepped < STAND_STEP_S:
            return None                                  # no step tried since he last moved, or it is still running
        if not fz["on"]:
            fz["on"] = True
            self.stats["frozen_spells"] = self.stats.get("frozen_spells", 0) + 1
        self.doing, self.why = "frozen", "not in control (an intro, a death camera or a grab): A"
        if now - fz["tap"] >= FROZEN_TAP_S:
            fz["tap"] = now
            self.stats["frozen_taps"] = self.stats.get("frozen_taps", 0) + 1
            return {"hold": set(), "tap": FROZEN_KEY}
        return {"hold": set()}

    def _sight_blocked(self, p, e, err, snap, now) -> dict | None:
        """The sight gate held this shot: logged (SIGHT_LOG), and past SIGHT_HOLD_S a FLANK_S flank begins."""
        key = e.get("ptr")
        sh = self.__dict__.get("_sight_hold")
        if not sh or sh["key"] != key or now - sh["last"] > 1.0:
            sh = self._sight_hold = {"key": key, "since": now, "last": now, "logged": -1e9}
        sh["last"] = now
        if now - sh["logged"] >= SIGHT_LOG_EVERY_S:
            sh["logged"] = now
            self._log_block(p, e, snap)
        if now - sh["since"] < SIGHT_HOLD_S:
            return None
        self._flank = {"key": key, "until": now + FLANK_S}
        self._sight_hold = None
        self.stats["flanks"] = self.stats.get("flanks", 0) + 1
        keys, how = self._approach(p, e["pos"], err, snap, run=False)
        self.doing, self.why = "flank", f"no clear shot: round it by {how}"
        return {"hold": keys}

    def _log_block(self, p, e, snap) -> None:
        """One sight block: the stats' last one and a line in SIGHT_LOG (the wall, where the shot met it)."""
        nav = snap.get("nav")
        hit = None
        try:
            bw = getattr(nav, "blocking_wall", None)
            hit = bw(tuple(p["pos"]), tuple(e["pos"])) if callable(bw) else None
        except Exception:                                # noqa: BLE001
            hit = None
        row = {"t": round(time.time(), 2), "room": getattr(nav, "room", None),
               "player": [round(v) for v in p["pos"]], "target": [round(v) for v in e["pos"]],
               "d_m": round(self._flat(p["pos"], e["pos"]) / 1000.0, 2),
               "dy": round(e["pos"][1] - p["pos"][1])}
        if isinstance(hit, tuple) and len(hit) == 3 and isinstance(hit[0], tuple):
            (x0, z0, x1, z1, lo, hi, attr), t, y = hit
            row.update(wall=[round(x0), round(z0), round(x1), round(z1)], lo=round(lo), hi=round(hi), attr=attr,
                       at=round(t, 3), shot_y=round(y))
        self.stats["sight_block_last"] = row
        try:
            SIGHT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SIGHT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def _approach(self, p, goal, err, snap, run: bool = False) -> tuple:
        """(stick keys, how) toward goal: the mesh walker when one is attached (Bot.walker.approach(goal) -> keys, the
        RE4 room-collision walker), else the first waypoint of the stage mesh's route (snap["nav"].route), else
        straight at it."""
        walker = self.walker
        if walker is not None:
            try:
                keys = set(walker.approach(tuple(goal), run=run) or ())
                if keys:
                    return keys, "the mesh walker"
            except Exception:                                # noqa: BLE001 - a walker error falls back to the line
                self.stats["walker_errors"] = self.stats.get("walker_errors", 0) + 1
        nav = snap.get("nav")
        route = getattr(nav, "route", None)
        if callable(route):
            try:
                pts = route(tuple(p["pos"]), tuple(goal)) or []
                wp = next((q for q in pts if isinstance(q, (tuple, list)) and len(q) >= 3
                           and all(isinstance(v, (int, float)) for v in q[:3])      # a waypoint, not a link
                           and self._flat(p["pos"], q) > 60.0 * MM_PER_CM), None)
                if wp is not None:
                    werr = wrap(heading(wp[0] - p["pos"][0], wp[2] - p["pos"][2]) - (p.get("rot") or 0.0))
                    keys = {"lup"} | (self._turn(werr) if abs(werr) > self.TURN_TOL else set())
                    return keys | ({RUN_BTN} if run else set()), "the stage mesh"
            except Exception:                                # noqa: BLE001
                self.stats["route_errors"] = self.stats.get("route_errors", 0) + 1
        keys = {"lup"} | (self._turn(err) if abs(err) > self.TURN_TOL else set())
        return keys | ({RUN_BTN} if run else set()), "the map"

    def _locate(self, p, live, now, cmd=None, snap=None) -> dict:
        """Nobody in range: the nearest Ganado by the map, walked to (run past RUN_CM); nobody known: the sweep."""
        if live:
            dist, err, e = min(live, key=lambda t: t[0])
            self.stats["locates"] += 1
            self.stats["locate_m"] = round(dist / 1000.0, 1)
            self.doing = "locate"
            run = dist > RUN_CM or self.combo_owed(now) is not None
            keys, how = self._approach(p, e["pos"], err, snap or {}, run)
            self.why = f"locating: the nearest Ganado {dist / 1000:.0f} m off by {how}" + (f" ({cmd})" if cmd else "")
            return {"hold": keys}
        if self._sweep_at is None or now - self._sweep_at >= SWEEP_S:
            self._sweep_at, self._sweep_dir = now, -self._sweep_dir
            self.stats["sweeps"] += 1
        self.doing, self.why = "sweep", "no Ganado on the map: exploring"
        return {"hold": {"lup", TURN["right" if self._sweep_dir > 0 else "left"]}}

    def _never_stand(self, p, act, snap, now) -> dict:
        """The doctrine's floor: a tick that neither fires nor moves him for STAND_MAX_S becomes a STAND_STEP_S step
        forward with a turn (the way changes each time). Aiming and firing are not standing."""
        st, pos = self._stand, p["pos"]
        hold = set(act.get("hold") or ())
        if act.get("tap") or AIM_BTN in hold:
            st.update(pos=tuple(pos), at=now, until=-1e9)
            return act
        if now < st["until"]:
            return dict(act, hold=set(st["keys"]))
        if st["pos"] is None or st["at"] is None or self._flat(st["pos"], pos) > STAND_MOVE_CM:
            st.update(pos=tuple(pos), at=now)
            return act
        if now - st["at"] < STAND_MAX_S:
            return act
        st["n"] = st.get("n", 0) + 1
        keys = {"lup", TURN["left" if st["n"] % 2 else "right"]}
        st.update(pos=tuple(pos), at=now, until=now + STAND_STEP_S, keys=tuple(keys))
        self.__dict__.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})["stepped"] = now
        self.stats["stand_breaks"] += 1
        self.doing, self.why = "step", f"stood {STAND_MAX_S:.1f} s: a step (he never stands)"
        return dict(act, hold=keys)

    def prompt_ok(self, button, snap, now):
        return False

    def save(self):
        pass


def flip_turn_sign(bot=None) -> int:
    """TURN_SIGN flipped (the fight's turns, the aim's, and re4_walk's for every walker made from now on and the
    bot's own). Returns the new sign."""
    global TURN_SIGN
    TURN_SIGN = -TURN_SIGN
    re4_walk.TURN_POSITIVE, re4_walk.TURN_NEGATIVE = re4_walk.TURN_NEGATIVE, re4_walk.TURN_POSITIVE
    w = getattr(bot, "walker", None)
    if w is not None and hasattr(w, "turn_pos"):
        w.turn_pos, w.turn_neg = w.turn_neg, w.turn_pos
    st = getattr(bot, "stats", None)
    if isinstance(st, dict):
        st["turn_sign_flips"] = st.get("turn_sign_flips", 0) + 1
        st["turn_sign"] = "error > 0 turns " + ("left" if TURN_SIGN > 0 else "right")
    return TURN_SIGN


DRIVER = RE4Switch
