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
- MEASURED 2026-11-10: where the game is (game_state: intro / in control / grabbed / held / case / death camera /
  results, from MercSysWk, pG's Status_flg / Stop_flg and the HUD's CountDown) and the round clock itself (CountDown,
  module + 0x1132FC0: docs/research/re4-switch-game-state.md). ClockFinder (below) is the fallback when they cannot be
  read: what it found were pG matrix-palette floats, not the clock.
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
from ..core import combat                          # the universal fight (UNIVERSAL_CORE): at import, for the hot reload
from ..core import respond                         # the doctrine's answer to a threat (RESPOND): at import, too
from ..core import aim_book                        # the per-shot truth and the learning on every miss (AIM_BOOK)
from . import re4_nav, re4_walk                    # the stage mesh (room collision), the walker and the map's marks
from . import re4_room_map                         # the room's real map (#9342): walls / floor for walks and shots
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
# The fight's aim request for the RAM aim lock (re4_switch_mods.aim_lock): {ptr, yaw, at}, written onto the player's
# facing by the mods each snapshot while it is fresh (the operator 2026-11-10: "using hooks and ram byte readers to
# aim and shoot").
AIM_REQUEST: dict = {}


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
PLAYER_HP_IN_UNIT = False               # the player's +0x3c2 is not his life (see above): PLAYER_LIFE is
# The player's life (u16, module + 0x1279360; his maximum the u16 beside it), found by scripts/re4sw_life_probe.py on
# a live round 2026-11-10 23:10 (2a5953853331456c-0c42a27a33764dcd, HUNK / Castle): 1680, 1152, 96, 0 at the death
# screen; 1680 = HUNK's 7 bars x 240 (Leon's 7.75 x 240 = 1860, the value an earlier read could not place).
PLAYER_LIFE: int | None = 0x1279360
LIFE_SANE = (1, 12000)                  # a maximum outside this is not a life
UNIT_HP_MAX = 30000                     # a health above this is not a health (a freed or foreign object)
UNIT_SCAN_CHUNK = 1 << 24               # 16 MiB per read while the census scans the heap
UNIT_RESCAN_S = 4.0                     # new spawns: the census looks again this often, inside the pool it found

# Mercenaries counters as module offsets (PENDING: the probe lists the candidates). Until they are measured the bot
# counts kills itself from the census (a unit whose health falls to 0) and says so (kills_source "census").
# The round's kill count (u32, module + 0x12010c4), measured on two live rounds 2026-11-10: Krauser / Waterworld
# read 0, 0, 1, 1, 5 ... 5 with five census kills; HUNK / Castle read 1 while the census saw none (a melee kill whose
# unit was freed between two reads - the census misses those). Trusted up to MERC_KILLS_MAX; above it, the census.
# RETRACTED 2026-11-10 00:12 (session afc80a255a2c4e4e-4a17d67f77b14e17): the HUD read 0 kills while 0x12010c4 read 8 -
# it climbs with the fight but is not the kill count. Back to the census until the HUD's number is matched in RAM.
MERC_KILLS: int | None = None
MERC_KILLS_MAX = 2000
# The round probe on the live Krauser / Waterworld round (2026-11-10 22:07, five kills): these u32 module offsets
# stepped up with the fight - 0x12010c4 read 0, 0, 1, 1, 5 ... 5 (the round's kill count: the leading candidate for
# MERC_KILLS), the others 0 ... 9. Read beside the census every snapshot (snap["kill_candidates"]) until one is
# confirmed against a second round, then it becomes MERC_KILLS.
KILL_CANDIDATES: tuple = (0x12010C4, 0x120118C, 0x12014AC, 0x12013E4)
MERC_COMBO: int | None = None
MERC_SCORE: int | None = None

# ---------------------------------------------------------------------------
# Where the game is, from its own state (docs/research/re4-switch-game-state.md). Found 2026-11-10 by static analysis of
# main against the GameCube decompilation (adonis-singh/re4: global.h GLOBAL_WK / STA_* / SPF_*, mercenaries.cpp,
# cockpit.cpp CountDown) and confirmed live on lilspark (session 5a68e96bfd1447a2-780e877d92ec4151, Krauser on
# Waterworld: the intro card, the round, the death).
# * pG (the game's global work, re4_weapons.GAME_OBJ): SceEventStart (0x4A1B60) sets Status_flg [+0x5090] 0x1000
#   (STA_EVENT) and [+0x5094] 0x10000000 (STA_SUSPEND), masks the pad (KeyStop: Stop_flg [+0x1A8] SPF_KEY) and sets
#   SPF_ACTBTN | SPF_SCE_AT there; the flag words count their bits from the top (MSB first), as on the GameCube.
# * MercSysWk (0x124F690): MercSysMoveStart (0x2A7290) runs the intro with startSt [+0xD4] = 1, its step [+0xD5] (1:
#   the "Eliminate as many Ganados ..." card, which waits for A: SceMesSet); MercSysMoveMain (0x2A6DE0) sets mainSt
#   [+0xD9] = 1 only after the intro returns; MercSysResultMove (0x2A95D0) runs the results with rsltSt [+0xE0] = 1.
# * the HUD clock: CountDown (Cckpt 0x1132F10 + 0xB0): state u32 (1 alive, 8 paused: STA_SUSPEND or SPF_PL), frames
#   left f32 at +8 (initTime 0x20AF0: 2:00 = 3600.0), less pG's frame step [+0xA4] (0.5 at 60 fps) per game frame
#   unless paused or the case is open (CountDown::move 0x200C0). Live: 30.06 a wall second over 20 s of a round.
# Live, in order: the intro card - startSt 1/1, STA_EVENT and STA_SUSPEND on, Stop_flg 0x80400100, the clock 3600.0
# alive + paused (state 9); the round - startSt 0/2, mainSt 1, both flags off, Stop_flg 0, the clock running (state 1);
# the death - STA_DIEDEMO (Status_flg[0] 0x00100000) on, Stop_flg 0x80400100 again, the clock's state 0.
PG_PTR_VAR = 0xB1AE08                   # data: u64 -> pG (re4_weapons.GAME_PTR_VAR)
PG_OBJ = 0x1274338                      # pG itself (re4_weapons.GAME_OBJ)
PG_STEP = 0x28                          # u8 Rno0, the game task's step (game_func_tbl): live 0 at the menus, 2 while the
                                        # stage's room is set up, 3 in the room (the intro, the round, the death);
                                        # reported (game_step), not decided on: its other values are not seen yet
PG_SYSTEM = 0x78                        # u32 System_flg: SYS_MERCENARIES while The Mercenaries is the game
PG_SPEED = 0xA4                         # f32 the frame step (every motion and the clock advance by it each frame)
PG_STOP = 0x1A8                         # u32 Stop_flg
PG_STATUS = 0x5090                      # u32 Status_flg[4]
SYS_MERCENARIES = 0x40000000            # SYS_OMAKE_ETC_GAME (MercSysSetPoint 0x2AB320 tests it)
SPF_KEY, SPF_PL = 0x80000000, 0x10000000    # the pad masked (KeyStop); the player stopped (CountDown pauses on it)
STA_EVENT = (0, 0x00001000)             # (word, bit): an event runs (the round intro, the results, a scripted scene)
STA_SUSPEND = (1, 0x10000000)           # the world suspended (CountDown pauses)
STA_DIEDEMO = (0, 0x00100000)           # the death camera (MercSysMoveMain stops checking the clock's end)
STA_SUB_SCRN = (0, 0x00040000)          # the attache case / sub screen (CountDown does not count)
STA_PL_CATCHED = (1, 0x00008000)        # a Ganado holds him (em10's grabs set it; the mash, PlGacha, frees him): live
                                        # 2026-11-10 it was on at the samples his life fell 2400 -> 2112, 1458 -> 1255
MERC_WORK, MERC_WORK_SIZE = 0x124F690, 0xF0   # MercSysWk (MercSysInitRoom 0x2A6B10 clears +0x28 .. +0xF0)
MW_SCORE, MW_COMBO, MW_KILL = 0x28, 0x2C, 0x48     # MercSysSetPoint: score += base points, combo + 1, kill + 1
MW_MODE, MW_STAGE = 0x6C, 0x70                     # 0 Leon, 1 Ada, 2 Krauser, 3 HUNK, 4 Wesker; 0..3 Village..Waterworld
MW_START, MW_MAIN, MW_RESULT = 0xD4, 0xD9, 0xE0    # [run, step] of the intro, [run] of the round, [run, step] results
COUNTDOWN, COUNTDOWN_SIZE = 0x1132FC0, 0x10
CD_ALIVE, CD_PAUSE, CD_FRAME, CD_FPS = 0x1, 0x8, 0x8, 30.0
# phase: none (no round's scenario task: menus, a load) | intro (the round's intro: the card waits for A) | playing (in
# control, the clock running) | grabbed (a Ganado holds him: the mash) | held (in the round but not in control: an
# event, a prompt, the world suspended, the pad masked) | case (the attache case is open) | dead (the death camera) |
# results (the round's results sequence)
ROUND_PHASES = ("intro", "playing", "grabbed", "held", "case", "dead", "results")
PHASE_WHY = {"none": "no round running", "intro": "the round's intro card: A", "playing": "in control, the clock runs",
             "grabbed": "a Ganado has him: A (the shake-off)",
             "held": "the game holds the player (an event or a prompt): A", "case": "the attache case is open: B",
             "dead": "the death camera: A answers its Continue (Yes)", "results": "the round's results: A"}
# what each phase puts on the telemetry's `screen` (MercMode now_playing, the progress rule) and the tactical map
PHASE_SCREEN = {"none": None, "intro": "intro", "playing": "playing", "grabbed": "playing", "held": "held",
                "case": "case", "dead": "dead", "results": "results"}


def _flag(status, flag) -> bool:
    word, bit = flag
    return bool(status[word] & bit)


def decode_state(system: int, stop: int, status, merc: bytes, countdown: bytes, speed: float | None = None) -> dict:
    """The game's own state from its raw fields (see PG_* / MW_* / CD_*): {phase, in_control, clock, clock_running,
    intro_step, result_step, kills, score, combo, mode, stage, flags, why}. Pure: the tests feed it bytes."""
    mercs = bool(system & SYS_MERCENARIES)
    start_run, start_step = merc[MW_START], merc[MW_START + 1]
    main_run = merc[MW_MAIN]
    res_run, res_step = merc[MW_RESULT], merc[MW_RESULT + 1]
    cd_state = struct.unpack_from("<I", countdown, 0)[0]
    frame = struct.unpack_from("<f", countdown, CD_FRAME)[0]
    flags = {"event": _flag(status, STA_EVENT), "suspend": _flag(status, STA_SUSPEND),
             "die": _flag(status, STA_DIEDEMO), "case": _flag(status, STA_SUB_SCRN),
             "grabbed": _flag(status, STA_PL_CATCHED),
             "key_stop": bool(stop & SPF_KEY), "pl_stop": bool(stop & SPF_PL)}
    alive = bool(cd_state & CD_ALIVE) and math.isfinite(frame) and -1.0 <= frame <= CLOCK_MAX_S * CD_FPS
    # MercSysWk is cleared only when the next stage's room starts (MercSysInitRoom), so its run bytes outlive a soft
    # reset (You Are Dead -> No, the decomp's systemRestartInit): pG's flags are cleared there and the cockpit re-made
    # (Cckpt.gameInit), so a round's run byte counts only with its clock alive (set before the intro's run byte, live
    # through the round; the death clears it but sets STA_DIEDEMO, which the reset clears in turn)
    if not mercs:
        phase = "none"
    elif res_run:
        phase = "results"
    elif start_run:
        phase = "intro" if alive else "none"
    elif main_run and flags["die"]:
        phase = "dead"
    elif main_run and alive:
        phase = ("case" if flags["case"] else
                 "held" if flags["event"] or flags["suspend"] or flags["key_stop"] or flags["pl_stop"] else
                 "grabbed" if flags["grabbed"] else "playing")
    elif start_step == 2 and alive and frame > 0:
        # the intro's last frames: its run byte is down (step 2), the round's not up yet (the event ending, "mission
        # start"): live 2026-11-10 04:45:46 one sample read start 0/2, round 0, the clock just started (3599.45). After
        # the results (the clock at 0, the card save before the soft reset) the same bytes are no round
        phase = "intro"
    else:
        phase = "none"
    out = {"phase": phase, "in_control": phase == "playing", "why": PHASE_WHY[phase],
           "clock": round(max(frame, 0.0) / CD_FPS, 2) if alive else None,
           # the clock's own state: alive, not paused (STA_SUSPEND / SPF_PL), not stopped by the open case
           "clock_running": (alive and not cd_state & CD_PAUSE and not flags["case"]
                             and phase in ("playing", "grabbed", "held")),
           "clock_state": cd_state, "intro_step": start_step if phase == "intro" else None,
           "result_step": res_step if res_run else None, "mercenaries": mercs,
           "kills": struct.unpack_from("<i", merc, MW_KILL)[0], "score": struct.unpack_from("<I", merc, MW_SCORE)[0],
           "combo": struct.unpack_from("<i", merc, MW_COMBO)[0], "mode": struct.unpack_from("<i", merc, MW_MODE)[0],
           "stage": struct.unpack_from("<i", merc, MW_STAGE)[0], "flags": flags}
    if speed is not None:
        out["frame_step"] = round(speed, 3)
    return out


# The camera (#9386, docs/research/re4-switch-camera-ram.md, static from main.bin; its instructions checked in main.bin
# and the chain read live): pG + 0xA8 is the 0xF8-byte render copy of the camera (memcpy from CamCtrl + 0x88 every
# frame), the GameCube CAMERA struct moved by +0x34: Campos 0x14C and Target 0x158 (layout-derived), Fovy 0x168 (an
# instruction reads it), Look 0x178 (a getter reads it), the stored Distance 0x19C (layout-derived).
CAM_BLOCK, CAM_SIZE = 0xA8, 0xF8
CAM_POS, CAM_TARGET, CAM_FOVY, CAM_LOOK, CAM_DIST = 0x14C, 0x158, 0x168, 0x178, 0x19C
CAMERA_READ = True
# Read live 2026-11-10 (a menu scene, no player in RAM): pG = module + 0x1274338 through module + 0xB1AE08 (the doc's
# chain, game_state's own pointer), Campos (0, 1000, 2000), Target (0, 0, 0), Fovy 50.0, the stored Distance 2236.07 =
# |Campos - Target|: the layout holds. Campos beside his position in a round is not read yet, so the camera-to-player
# distance is taken as his only while it is a camera's (CAM_PLAYER_MAX_MM); past it the camera's own |Campos - Target|
# stands in (snap camera_dist_source "target").
CAM_PLAYER_MAX_MM = 8000.0


def decode_camera(raw: bytes) -> dict | None:
    """The camera block's fields (camera_state's read of pG + CAM_BLOCK), or None when they are not a camera (a
    position not finite or past 1e6 mm, a field of view outside 1 .. 179 degrees)."""
    if len(raw) < CAM_SIZE:
        return None

    def f(off, n=3):
        return struct.unpack_from(f"<{n}f", raw, off - CAM_BLOCK)
    pos, target, look = f(CAM_POS), f(CAM_TARGET), f(CAM_LOOK)
    fovy, dist = f(CAM_FOVY, 1)[0], f(CAM_DIST, 1)[0]
    vals = pos + target + look + (fovy, dist)
    if not all(math.isfinite(v) and abs(v) < 1e6 for v in vals) or not 1.0 < fovy < 179.0:
        return None
    return {"pos": pos, "target": target, "look": look, "fovy": fovy, "dist": dist,
            "target_dist": math.dist(pos, target)}


def camera_state(m, base: int | None = None) -> dict | None:
    """decode_camera of pG + CAM_BLOCK (one read), or None."""
    base = module_base(m) if base is None else base
    if base is None:
        return None
    try:
        pg = u64(m, base + PG_PTR_VAR)
        if not ptr_ok(pg):
            return None
        return decode_camera(bytes(m.rd(pg + CAM_BLOCK, CAM_SIZE)))
    except (ValueError, OSError, struct.error, TypeError):
        return None


# The gun's own aim (the operator 2026-11-10: "the bot aims terribly, their laser goes awry weirdly ... If the bot has
# access to the ram and hex info of the game, I want the aim impeccable"). Static, from main.bin (82C2A04A...) against the
# GameCube decompilation (pl_wep.cpp PlWepLockCtrl / PlWepLockRand, objWep.cpp drawLaserSight, em_sub.cpp
# GetWepTargetPos), every offset seen in a Switch instruction; not yet read in a live round (aim_state checks each read):
#   * PlWepLockCtrl (0x33DF80, the aim each frame while he aims): the aim's yaw is his facing (unit + 0xB4, U_YAW) plus the
#     waist twist m_Fwork0 (unit + 0x524: `str s1, [x19, #0x524]`; the stick moves it first, inside the weapon's cone of
#     at most 12 deg, then turns him); its pitch the blend m3r (module + 0x1265A08: now, target, rate - GOT 0xB27D00),
#     -1 down .. +1 up;
#   * PlWepLockRand (0x33EC50): the SWAY - the laser's random walk about its centre. pl->Wep (unit + 0x938) is the
#     weapon control: +0x28 the centre pitch (blend x pi/2), +0x2C the centre waist yaw, +0x38 the weapon object, whose
#     +0x3E0 .. +0x3EC (bureX, bureY, bureSpeedX, bureSpeedY: setAbility's 5.73 / 2.86 / 0.2864 / 0.2864 deg by default)
#     bound the walk (+-5.7 deg in pitch AND yaw: the clamp uses the pitch range for both) and its step a frame; a shot
#     kicks the aim to a fresh random point inside it (the recoil). With all four at 0 the walk adds nothing and the clamp
#     holds the aim exactly on its centre: no sway, no kick - the aim is where the centre is put;
#   * drawLaserSight (0x2E8744, each frame the laser is drawn): GetWepTargetPos(&lpos, &lcross, 0, pG->weapon_no
#     [pG + 0x5034], &m_SightEm, &attr) - lpos / lcross are its statics (module + 0x1265314 / + 0x1265320: the muzzle,
#     moved 50 cm along the line, and where the line meets the stage or a body), m_SightEm (weapon object + 0x418) the
#     enemy whose hit capsules the line meets first (emLineAtCk2), nearer than any wall: the game's own "the laser is on
#     him". The handgun's bullet goes down the same line (wep02_r3_fire00: the muzzle along -X with +-200 mm spread at
#     50 m, 0.23 deg).
# AIM_RAM off: the snapshot reads none of it and the fight is as before (the rollback, one constant).
AIM_RAM = True
PL_WEP, PL_WAIST_YAW = 0x938, 0x524
WEP_PITCH, WEP_CENTER_Y, WEP_OBJ = 0x28, 0x2C, 0x38
OBJ_SWAY, OBJ_ITEM, OBJ_STAT, OBJ_SIGHT_EM = 0x3E0, 0x400, 0x402, 0x418
LASER_STATIC = 0x1265310                 # u8 donfire; Vec lpos at +4; Vec lcross at +0x10
M3R = 0x1265A08
SWAY_SANE, WAIST_SANE, PITCH_SANE = 0.5, 0.35, 1.58     # rad: a read past these is not the field
LASER_NEAR_MM = (300.0, 3000.0)          # the ray's origin this near his position (ground) / this high over his feet
LASER_MIN_MM = 400.0                     # a ray shorter than this (a wall at the muzzle) is no line
# The weapon object's r_no_0 while the laser is drawn: setStat writes 0 .. 6 on Switch (69 strh sites; the GameCube's
# enum stops at 5, the PS2's has S_SET between S_READY and S_FIRE), so ready / set / fire are 1 .. 3 here (the bot's
# own "the gun is up AIM_READY_S" is the other half of the freshness test)
LASER_UP_STATS = (1, 2, 3)


def decode_aim(wep_raw: bytes, obj_raw: bytes, waist_raw: bytes, laser_raw: bytes, m3r_raw: bytes | None,
               wep: int, obj: int) -> dict | None:
    """The gun's aim from its raw fields (see AIM_RAM), or None when they are not the fields (a value out of its range).
    Pure: the tests feed it bytes. wep_raw from wep + 0x28 (0x18 bytes), obj_raw from obj + OBJ_SWAY (0x40), waist_raw
    the unit's + PL_WAIST_YAW (4), laser_raw LASER_STATIC (0x1C), m3r_raw M3R (12)."""
    try:
        pitch, center = struct.unpack_from("<2f", wep_raw, 0)
        obj_ptr = struct.unpack_from("<Q", wep_raw, WEP_OBJ - WEP_PITCH)[0]
        sway = struct.unpack_from("<4f", obj_raw, 0)
        item = struct.unpack_from("<H", obj_raw, OBJ_ITEM - OBJ_SWAY)[0]
        stat = obj_raw[OBJ_STAT - OBJ_SWAY]
        sight = struct.unpack_from("<Q", obj_raw, OBJ_SIGHT_EM - OBJ_SWAY)[0]
        waist = struct.unpack_from("<f", waist_raw, 0)[0]
        donfire = laser_raw[0]
        lpos, lcross = struct.unpack_from("<3f", laser_raw, 4), struct.unpack_from("<3f", laser_raw, 0x10)
        m3r = struct.unpack_from("<3f", m3r_raw, 0) if m3r_raw else None
    except (struct.error, IndexError, TypeError):
        return None
    vals = (pitch, center, waist) + sway + lpos + lcross
    if obj_ptr != obj or not all(math.isfinite(v) for v in vals) or abs(pitch) > PITCH_SANE \
            or abs(center) > WAIST_SANE or abs(waist) > WAIST_SANE or not all(0.0 <= s <= SWAY_SANE for s in sway) \
            or (sight and not ptr_ok(sight)) or item > 0x400 or any(abs(v) > 1e7 for v in lpos + lcross):
        return None
    out = {"wep": wep, "obj": obj, "pitch": pitch, "center": center, "waist": waist, "sway": sway, "item": item,
           "stat": stat, "sight": sight or None, "lpos": lpos, "lcross": lcross, "donfire": donfire}
    if m3r is not None and all(math.isfinite(v) for v in m3r) and abs(m3r[0]) <= 1.01:
        out["m3r"] = m3r[0]
    return out


def aim_state(m, base: int, player: int) -> dict | None:
    """decode_aim of the player's weapon control, weapon object, waist, the laser's statics and m3r (five reads), or
    None when a pointer or a value is not what the layout says."""
    try:
        wep = u64(m, player + PL_WEP)
        if not ptr_ok(wep):
            return None
        wep_raw = bytes(m.rd(wep + WEP_PITCH, 0x18))
        obj = struct.unpack_from("<Q", wep_raw, WEP_OBJ - WEP_PITCH)[0]
        if not ptr_ok(obj):
            return None
        obj_raw = bytes(m.rd(obj + OBJ_SWAY, 0x40))
        waist_raw = bytes(m.rd(player + PL_WAIST_YAW, 4))
        laser_raw = bytes(m.rd(base + LASER_STATIC, 0x1C))
        try:
            m3r_raw = bytes(m.rd(base + M3R, 12))
        except (ValueError, OSError):
            m3r_raw = None
    except (ValueError, OSError, struct.error, TypeError):
        return None
    return decode_aim(wep_raw, obj_raw, waist_raw, laser_raw, m3r_raw, wep, obj)


def laser_of(aim: dict | None, player: dict | None) -> dict | None:
    """The laser line {from, at, up} when the aim's statics are a line from his gun (its origin beside him, at a
    gun's height, the line long enough), else None. up: the weapon object stands ready / firing (LASER_UP_STATS)."""
    if not aim or not player or not player.get("pos"):
        return None
    lp, lc, pos = aim["lpos"], aim["lcross"], player["pos"]
    if math.hypot(lp[0] - pos[0], lp[2] - pos[2]) > LASER_NEAR_MM[1] or not LASER_NEAR_MM[0] <= lp[1] - pos[1] <= 2600.0:
        return None
    if math.dist(lp, lc) < LASER_MIN_MM:
        return None
    return {"from": lp, "at": lc, "up": aim.get("stat") in LASER_UP_STATS, "source": "ram"}


def laser_gate(aim: dict | None, player: dict | None) -> str:
    """Why laser_of() accepts or rejects this frame - the aim ticket's diagnostic (live 2026-11-11 22:53: RE4 fired
    128 shots with 7 hits and never once took the laser path, so every aim was the fallback heading). Names the
    condition, so a stat outside LASER_UP_STATS is not confused with a bad origin or a short ray."""
    if not aim or not player or not player.get("pos"):
        return "no aim/player"
    lp, lc, pos = aim["lpos"], aim["lcross"], player["pos"]
    flat = math.hypot(lp[0] - pos[0], lp[2] - pos[2])
    high = lp[1] - pos[1]
    ray = math.dist(lp, lc)
    stat = aim.get("stat")
    return (f"stat={stat} up={stat in LASER_UP_STATS} flat={int(flat)}mm high={int(high)}mm "
            f"ray={int(ray)}mm wep={aim.get('wep')} sight={aim.get('sight')}")[:200]


def game_state(m, base: int | None = None) -> dict | None:
    """decode_state() read from the session (a few small reads), or None when the fields cannot be read (no module, a
    pG pointer that is not one): the callers then fall back to the frame."""
    base = module_base(m) if base is None else base
    if base is None:
        return None
    try:
        pg = u64(m, base + PG_PTR_VAR)
        if not ptr_ok(pg):
            return None
        head = bytes(m.rd(pg + PG_STEP, PG_STOP + 4 - PG_STEP))
        status = struct.unpack("<4I", bytes(m.rd(pg + PG_STATUS, 16)))
        merc = bytes(m.rd(base + MERC_WORK, MERC_WORK_SIZE))
        cd = bytes(m.rd(base + COUNTDOWN, COUNTDOWN_SIZE))
    except (ValueError, OSError, struct.error, TypeError):
        return None
    if len(head) < PG_STOP + 4 - PG_STEP or len(merc) < MERC_WORK_SIZE or len(cd) < COUNTDOWN_SIZE:
        return None
    system = struct.unpack_from("<I", head, PG_SYSTEM - PG_STEP)[0]
    speed = struct.unpack_from("<f", head, PG_SPEED - PG_STEP)[0]
    stop = struct.unpack_from("<I", head, PG_STOP - PG_STEP)[0]
    out = decode_state(system, stop, status, merc, cd, speed if math.isfinite(speed) else None)
    out["game_step"] = head[0]
    return out

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


def player_life(m, base: int) -> tuple:
    """(life, maximum) from PLAYER_LIFE, or (None, None): the maximum is the u16 beside it that is at least the
    life (after, then before), inside LIFE_SANE."""
    if PLAYER_LIFE is None:
        return None, None
    try:
        raw = bytes(m.rd(base + PLAYER_LIFE - 2, 6))
    except (ValueError, OSError):
        return None, None
    before, life, after = struct.unpack("<3H", raw)
    for top in (after, before):
        if LIFE_SANE[0] <= top <= LIFE_SANE[1] and life <= top:
            return life, top
    return None, None


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
    game = game_state(m, base)
    if game is not None:
        # the game's own state and its HUD clock (CountDown): ClockFinder's heuristic (any bss float that falls at
        # wall rate) found matrix-palette floats in pG (the "copies 0x30 apart" were Mtx rows) and read erratically
        snap["game"] = game
        snap["timer"], snap["clock_addr"], snap["clock_source"] = game["clock"], base + COUNTDOWN, "countdown"
        snap["mercenaries_phase"] = (PHASE_INTRO if game["phase"] == "intro" else
                                     PHASE_OVER if game["phase"] == "results" else
                                     PHASE_PLAYING if game["phase"] in ROUND_PHASES else None)
        snap["score"], snap["combo"] = game["score"], game["combo"]
        if FIRE_PATTERN or AIM_BOOK:                     # the equipped class (the fire pattern's / aim book's family)
            try:
                from . import re4_weapons as _w
                snap["weapon_class"] = bytes(m.rd(base + _w.GAME_OBJ + _w.G_CLASS, 1))[0]
                # The equipped ITEM id as well (item manager M_EQUIPPED_ID): the class byte is what the fire pattern
                # keys on, but the bow's fast path must not depend on one byte reading right. Krauser's bow is item
                # 0x52 / class 0x1C; live 2026-11-11 the bow was raised without discharging (the operator's "rain of
                # arrows"), which is what a misread class byte does: bow=False, the rifle gap and the 0.25 s wait.
                snap["equipped_id"] = struct.unpack("<H", bytes(m.rd(base + _w.ITEM_MGR + _w.M_EQUIPPED_ID, 2)))[0]
                # The item id is the second witness for the class: when the game object's class byte is unreadable
                # (live 2026-11-12: a whole RE6-era round with weapon= empty and hits collapsing to 10%), the fire
                # pattern's family and the aim book get nothing. CLASS_OF maps the equipped item to its class.
                if snap.get("weapon_class") is None and snap.get("equipped_id") in _w.CLASS_OF:
                    snap["weapon_class"] = _w.CLASS_OF[snap["equipped_id"]]
                # An id neither table knows cannot be aimed at or modelled: live 2026-11-12 a round read weapon=33 with
                # CLASS_OF[0x33] a KeyError, fired 19 shots and landed none. Name it in the stats instead of letting it
                # look like an aim failure.
                if snap.get("weapon_class") is not None and int(snap["weapon_class"]) not in CLASS_FAMILY:
                    stats["weapon_unmapped"] = int(snap["weapon_class"])
            except (ValueError, OSError, TypeError, IndexError, AttributeError):
                pass
        if 0 <= game["kills"] <= MERC_KILLS_MAX:
            # the game's own kill count (MercSysWk + MW_KILL): live 2026-11-10 04:46-04:47 it read 1, 2, 3, 4 with
            # the score 300, 600, 920, 1220, back to 0 at the Continue's new intro, then 1 .. 6 while the census
            # counted 5 (a Ganado freed between two census reads is missed)
            snap["kills"] = game["kills"]
    else:
        clock = _finder(m, "re4_clock", ClockFinder)
        if search or clock.addr is not None:
            snap["timer"] = clock.observe(m, base, now)
        snap["clock_addr"], snap["clock_source"] = clock.addr, "clock_finder"
    census = _finder(m, "re4_units", UnitCensus)
    if census.classes() and U_POS is not None:
        if search:
            census.refresh(m, base, now)
        player, enemies = census.read(m, base)
        player = player_unit(m, base) or player       # the bss pointer first: no scan needed for him
        if player is not None:
            if not PLAYER_HP_IN_UNIT:
                player["hp"], player["hp_max"] = player_life(m, base)   # module PLAYER_LIFE, not his unit
            player.setdefault("hp_max", None)
            player.setdefault("rot", None)
            snap["player"] = player
            if AIM_RAM and isinstance(player.get("ptr"), int):   # the gun's own aim and laser line (AIM_RAM)
                aim = aim_state(m, base, player["ptr"])
                if aim is not None:
                    snap["aim"] = aim
                    laser = laser_of(aim, player)
                    if laser is not None:
                        snap["laser"] = laser
                        if not laser.get("up"):
                            # The line is there but the gun's state is not one LASER_UP_STATS accepts, so `fresh` never
                            # becomes true and every shot takes the fallback heading - the ~40% rounds (2026-11-11).
                            snap["laser_gate"] = laser_gate(aim, player)
                    else:
                        # Why the laser was refused. Every steady aim request depends on it, and the ~40% rounds could
                        # not say whether the class byte, the ray's origin or its length was refusing (2026-11-11).
                        snap["laser_gate"] = laser_gate(aim, player)
        snap["enemies"] = [dict(e, hp_max=e.get("hp_max")) for e in enemies]
    if CAMERA_READ:                                      # the camera (#9386): where it is, how far from him
        cam = camera_state(m, base)
        if cam is not None:
            snap["camera"] = cam
            pos = (snap.get("player") or {}).get("pos")
            d = math.dist(cam["pos"], pos) if pos is not None else None
            if d is not None and d <= CAM_PLAYER_MAX_MM:
                snap["camera_dist_mm"], snap["camera_dist_source"] = round(d, 1), "player"
            elif pos is not None:                        # (Campos not in his frame: the camera's own distance)
                snap["camera_dist_mm"], snap["camera_dist_source"] = round(cam["target_dist"], 1), "target"
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
    merc phase when the port exposes one). Conservative: unknown stays "loading", so the walk reads the frame instead.
    With the game's own state (snap["game"], game_state) its phase decides: in control is "playing", the intro, a hold
    and the open case are "paused" (in the round, not in control: the Bot pages them), the death camera "dead", the
    results "results"; no round running falls through to the frame."""
    game = snap.get("game")
    if isinstance(game, dict) and game.get("phase") in ROUND_PHASES:
        return {"playing": "playing", "grabbed": "playing", "dead": "dead",
                "results": "results"}.get(game["phase"], "paused")
    if isinstance(game, dict) and game.get("phase") == "none":
        return "loading"
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
STORY_LEAVE_S = 4.0                  # after Yes: no press until the main menu has settled
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
    # the A on Yes leaves LOAD for the main menu, whose cursor opens on LOAD: a second A in the next seconds goes
    # straight back in (live 2026-11-10 22:55, frames 0.4 s apart: Yes, black, LOAD highlighted, black, the list)
    _story_last = now + (STORY_LEAVE_S if key == "a" else 0.0)
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
            # The reader could not name the row (live 2026-11-11 22:43: RE4 parked on extras_menu at 0 rounds for the
            # whole block). These are fixed lists whose target the reader still sets (EXTRAS_ROW / MERCENARIES_ROW), so
            # a step down beats refusing every press: the walk keeps moving and the next frame names the cursor.
            return DPAD["down"] if isinstance(tgt, int) else None
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
# Learned pace (operator 2026-11-10: "I need the bot learning the menu system and navigating them faster and faster
# and faster each and every time ... I never want to see the bot slowly navigating through menus"): the three waits
# above are learned per screen from the walk itself and kept across boots (PACE_FILE). A confirm the game took (the
# next screen named within PACE_TAKEN_S) shortens that screen's settle and confirm waits x PACE_FAST; a move that
# showed on the cursor (or a select screen's step counted) shortens its move gap; a confirm pressed again on the same
# screen, or a move re-sent because it never showed, lengthens them x PACE_SLOW. Never under the floors (a frame or
# two of the 30 fps read) and never over the hand-set values above (the old walk is the worst case).
# The table itself is the shared one (gbox.mercs.core.menu_pace.Table): this module keeps its file, knobs and state, so
# the learned file (screens -> settle / confirm_after / move_gap, taken / missed) reads and writes exactly as before,
# and the walk's clock (re4switch_bot: menu_s, the walks, the bests) shares the same file.
PACE_FILE = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "learned" / "010099A00BC1E000" / "menu_pace.json"
PACE_KNOBS = {"settle": (SETTLE_S, 0.06), "confirm_after": (CONFIRM_AFTER_S, 0.10), "move_gap": (MOVE_GAP_S, 0.08)}
PACE_FAST, PACE_SLOW, PACE_TAKEN_S, PACE_SAVE_S = 0.75, 1.5, 3.0, 2.0
PACE_SELECT_MOVE_FLOOR = 0.30            # the select screens' moves are open loop (counted as sent, not as seen)
PACE_NAMES = {"settle": "settle", "confirm_after": "confirm", "move_gap": "move"}   # the panel's menu_pace line
_PACE: dict = {"screens": None, "dirty": False, "saved": float("-inf")}


def _pace_floor(where, knob: str, floor: float) -> float:
    if knob == "move_gap" and where in ("select_player", "select_stage"):
        return max(floor, PACE_SELECT_MOVE_FLOOR)        # open loop there: a dropped move picks the wrong entry
    return floor


def pace_table():
    """This title's learned menu pace (PACE_FILE / _PACE, read at each call: tests point both elsewhere)."""
    from ..core import menu_pace
    return menu_pace.Table(PACE_FILE, PACE_KNOBS, state=_PACE, floor=_pace_floor, fast=PACE_FAST, slow=PACE_SLOW,
                           save_s=PACE_SAVE_S)


def _pace_screens() -> dict:
    return pace_table().screens()


def pace_value(where, knob: str) -> float:
    """This screen's learned wait (PACE_KNOBS), the hand-set value until it has learned one."""
    return pace_table().value(where, knob)


def _pace_learn(where, knobs, faster: bool, now: float) -> None:
    pace_table().learn(where, knobs, faster, now)


def pace_save(now: float | None = None, force: bool = False) -> None:
    """The learned pace to PACE_FILE (at most every PACE_SAVE_S unless forced)."""
    pace_table().save(now, force)


def pace_summary() -> str:
    """The learned waits, one line per screen (the run's menu_pace stat)."""
    return pace_table().summary(PACE_NAMES)


def menu_status() -> dict:
    """The sidebar's menus line (gbox.mercs.bot_logic.status): the kept walks, round to round and from the launch."""
    from ..core import menu_pace
    return menu_pace.status(PACE_FILE)


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
        self.confirm = None                     # (screen, when) of the last confirm, until the next screen is named
        self.move = None                        # (screen, when, the select screen's step count) of the last move
        self.steps = None                       # (screen, its step count) at the last read
        self.misses = 0                         # presses the game dropped (re-sent / confirmed again): the walk's clock

    def observe(self, scr: dict, now: float) -> None:
        where = scr.get("where")
        if where != self.where:
            if self.confirm and self.confirm[0] == self.where and now - self.confirm[1] <= PACE_TAKEN_S:
                _pace_learn(self.confirm[0], ("settle", "confirm_after"), True, now)   # taken: that screen faster
            self.confirm = None
            self.where, self.since, self.moved_from, self.on_target = where, now, None, 0
        if where in CURSOR_MENUS:
            cur = scr.get("cursor")
            self.on_target = self.on_target + 1 if isinstance(cur, int) and cur == scr.get("target") else 0
            if self.moved_from is not None and cur != self.moved_from:
                self.moved_from = None          # the last move showed
                if self.move and self.move[0] == where:
                    _pace_learn(where, ("move_gap",), True, now)
                    self.move = None
        steps = int(scr.get("moved") or 0)
        if where in ("select_player", "select_stage"):
            if self.steps and self.steps[0] == where and steps > self.steps[1] and self.move and self.move[0] == where:
                _pace_learn(where, ("move_gap",), True, now)                        # a select step counted
                self.move = None
            self.steps = (where, steps)

    def ready(self, scr: dict, now: float) -> bool:
        where = scr.get("where")
        if next_is_move(scr):
            gap = pace_value(where, "move_gap")
            if now - self.last_press < gap:
                return False
            return self.moved_from is None or now - self.last_press >= max(0.35, gap * MOVE_RETRY_S / MOVE_GAP_S)
        if self.since is None or now - self.since < pace_value(where, "settle") \
                or now - self.last_press < pace_value(where, "confirm_after"):
            return False
        return where not in CURSOR_MENUS or self.on_target >= 2

    def pressed(self, scr: dict, key: str, now: float) -> None:
        where = scr.get("where")
        move = key in DPAD.values()
        if move and self.move and self.move[0] == where and self.moved_from is not None:
            _pace_learn(where, ("move_gap",), False, now)   # sent again: the last one never showed - slower here
            self.misses += 1
        if not move and key in ("a", "plus") and self.confirm and self.confirm[0] == where:
            _pace_learn(where, ("settle", "confirm_after"), False, now)   # a second confirm: the first was not taken
            self.misses += 1
        self.last_press = now
        self.moved_from = scr.get("cursor") if move and where in CURSOR_MENUS else None
        if move:
            self.move = (where, now)
        elif key in ("a", "plus"):
            self.confirm = (where, now)


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
    try:                                                  # the walk's own press log (what it pressed, on what)
        WALK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WALK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 2), "where": scr.get("where"), "cursor": scr.get("cursor"),
                                 "prompt": scr.get("prompt"), "target": scr.get("target"), "key": key}) + chr(10))
    except OSError:
        pass
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
# The E3 watch (2026-11-10): the five `.bss` candidate pages read once per snapshot so the round's telemetry carries
# their bytes at every stage load. A page that is all zero at three loads can hold the RE4 native harness's mailbox
# (`re4_switch_native`); 16 bytes is the ask, `BSS_WATCH_BYTES` is what one read returns. Read-only: five 16-byte reads
# per snapshot, no writes, nothing changes the game.
BSS_WATCH_PAGES = (0x1CB9000, 0x1CBA000, 0x1CBB000, 0x1CBC000, 0x1700000)
BSS_WATCH_BYTES = 16


def bss_watch(m, base: int) -> dict:
    """{stage, at, pages: {offset: hex16 or None}} for the candidate pages (a failed read is None, never a stop)."""
    out: dict = {"at": round(time.monotonic(), 3), "pages": {}}
    for off in BSS_WATCH_PAGES:
        try:
            out["pages"][f"{off:#x}"] = bytes(m.rd(base + off, BSS_WATCH_BYTES)).hex()
        except (ValueError, OSError, TypeError, struct.error):
            out["pages"][f"{off:#x}"] = None
    return out


def watch_into(m, snap: dict, stats: dict | None) -> None:
    """Publish this snapshot's five-page watch into `stats` (the JSON strings the telemetry carries).

    Both RE4 paths call it: the driver's own `snapshot` (the engine) and the `re4switch_bot` playbook, which reads
    through the module-level snapshot. The playbook path was missing it, so a whole RE4 round's telemetry carried no
    `bss_watch`/`bss_watch_loads` and the harness mailbox could never be chosen from three stage loads (live
    2026-11-11: the E3 watch was empty on the round that ran after the 05:00 restart).

    A load is also recorded at **every round start**, not only when the stage id changes: RE4 Switch's MercMode pick
    rides the launch, so one session plays the same stage every round (live 2026-11-11: nine rounds, stage 3, one
    watch entry), and the E3 acceptance - the page zero at three loads - could never be met inside a session.
    """
    if not isinstance(stats, dict) or not snap.get("module_base"):
        return
    try:
        watch = bss_watch(m, snap["module_base"])
        game = snap.get("game") or {}
        watch["stage"] = game.get("stage")
        # The telemetry publishes only scalar stats (gbox/tools.py body(): int/float/str/bool), so the watch goes out
        # as JSON strings; the accumulating list itself stays private (a list would be filtered).
        stats["bss_watch"] = json.dumps(watch, separators=(",", ":"))
        loads = stats.get("_bss_watch_loads")
        if not isinstance(loads, list):
            loads = stats["_bss_watch_loads"] = []
        phase = game.get("phase")
        last_phase = stats.get("_bss_watch_phase")
        started = phase in ("intro", "playing") and last_phase not in ("intro", "playing")
        stats["_bss_watch_phase"] = phase
        # one reading per stage load or round start: the last three are the three-load watch even when nobody polls
        if watch["stage"] is not None and (started or not loads or loads[-1].get("stage") != watch["stage"]):
            loads.append(watch)
            del loads[:-3]
            stats["bss_watch_loads"] = json.dumps(loads, separators=(",", ":"))
    except (OSError, ValueError, TypeError, struct.error):
        pass


class RE4Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # The Mercenaries on Switch is played solo on P1 here
    units_per_m = 1000.0                        # mm, measured (doctrine.view, the atlas): see MM_PER_CM below
    round_counters = ("shots", "hits", "turns", "backoffs", "holds", "dying", "escapes", "locates", "stand_breaks",
                      "crowd_picks", "kills_seen",
                      # the gun's raise / lower (FIRE_FIRST's telemetry; the operator 2026-11-10 night: the camera
                      # jerk of the weapon going up and down) and the wall tangents (ROOM_TANGENTS)
                      "gun_downs", "gun_kept", "gun_up_ticks", "gun_down_ticks",
                      "unwall_tangents", "unwall_tangent_steps") + respond.COUNTERS

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        snap = re4_nav.attach(snapshot(m))             # snap["nav"]: the stage's floor mesh (the tactical map's too)
        watch_into(m, snap, getattr(self, "stats", None))
        return snap

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
# (re4_switch_nav) and a live player position read x 50,689 (50 m, not 500; a Base position: only r403's collision,
# x 27,704 .. 88,786, holds it - #9342 - though it was noted on Village). The names below keep their
# historical _CM suffix; their values are the same distances in the game's mm (x MM_PER_CM). Before this the fight
# took every Ganado for 10x farther than he was: live it never fired (0 shots over 8 rounds) and walked into them.
MM_PER_CM = 10.0
ENGAGE_RANGE_CM = 1200.0 * MM_PER_CM                 # the blind range: no LOS data, fire no further than ~12 m
ENGAGE_RANGE_LOS_CM = 3500.0 * MM_PER_CM             # with the LASER/nav LOS gate wired, shoot on sight to ~35 m
# Past this he RUNS at him instead of standing and firing. The shot's tolerance is floored at FIRE_TOL_MIN 0.05 rad, so
# past ~6 m the bot may fire wider than a body - but a GOOD aim still lands at 10 m (1 deg is 17 cm on a 30 cm half
# body, which is the fight's own 10 m case), so 9 m was too eager: it stopped shooting where it can still hit. Standing
# at 15 m and beyond is the case that kills him - a machine-gunner across the stage (the operator, 2026-11-12: "failed
# to hit a target that was far away, so as a result she got killed by that zombie holding a machine gun on the other
# side of the map shooting at her"). 15 m keeps the 10 m shot and closes everything past it, and it is what makes the
# run-to-the-mesh-route case (a Ganado 30 m out behind a wall) a run instead of a raised gun.
HUNT_RUN_MM = 15000.0
# A boss is anything the shared doctrine calls one (gbox.mercs.core.doctrine.BOSS_HP_MIN = 3000, matching
# "dispatch bosses on sight"): it can end the round, so unlike a heavy it is closed on and destroyed, not kept away.
BOSS_HP_MIN = 3000.0
# (operator 2026-11-11 19:20: "why is the bot just letting these enemies walk up on him? He needs to be using magnums
#  and dispatching these foes as quickly as possible" - the 12 m blind gate held the gun until the Ganado was on him.
#  The gate was written before the line-of-sight gate was wired; with the nav/obstacle data the bot may fire to 35 m.)
FIRE_FIRST_CLOSE_MM = 900.0                          # inside this ring a body in the line is the target: fire anyway
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
# 1.6 (was 0.8): the operator, 2026-11-12: "Why is the bot lurching forward step by step slowly?" The step's own goal
# is STAND_STEP_MM 2000 mm, but it only walked STAND_STEP_S 0.8 s - about a metre at RE4's walk speed - so every stride
# stopped half way through, the stand clock reset, and he stood STAND_MAX_S 1.5 s before lurching another metre. 1.6 s
# is long enough to actually cover the 2000 mm the step was aiming at, so a step is one stride instead of a stumble.
STAND_MAX_S, STAND_MOVE_CM, STAND_STEP_S = 1.5, 40.0 * MM_PER_CM, 1.6   # never stand: no metre in 1.5 s and no shot -> a step
# A turn is not progress (the operator, live 2026-11-12: "they're just turning back and forth in place while stumbling
# backwards. I need the bot able to walk the level confidently"). A facing change used to reset the stand clock, so a bot
# facing a target turned every tick, never reached STAND_MAX_S, and spent the round rotating on the spot - the live round
# read stand_engaged=655 with turns=889. A turn now excuses the stand only this long after he last actually MOVED; past
# it the never-stand rule steps him forward regardless of where he is looking.
TURN_EXCUSE_S = 2.5
SWEEP_S = 3.0                            # nobody on the map: walk, turning this long one way, then the other
# The operator's quick commands (the PiP's ▾ menu and ⚠ Flawed, gbox.mercs.directives; operator 2026-11-10: "make sure
# that when I use one of the quick commands for guidance to the bot, that it's able to take those commands into
# consideration"). Before this the RE4 Switch bot read them only into its "why" line. Bot._operator_command:
#   explore / next_area  the Ganado he kept at dropped for CMD_DROP_S, CMD_ROAM_S along open floor away from here (_escape)
#   repetitive           the same drop and one such run: another target, another way
#   fight / hunt / rush  the walk to the nearest Ganado becomes a run (CMD_RUN); a shot at one in range still comes first
#   score                the quickest kill is the target (the combo's pick)
#   missing              the aim's stick and the turn sign are measured again from scratch
#   mine / mine_trail / flashbang  said (RE4 Mercenaries has no mines; no native flash on this build yet): he fights on
CMD_ROAM_S, CMD_DROP_S = 4.0, 15.0
CMD_RUN = ("fight", "hunt", "rush")
CMD_SAYS = {"fight": " - no wait: runs at the nearest Ganado, fires at any in range",
            "hunt": " - runs to the nearest Ganado by the map",
            "rush": " - runs in at the nearest Ganado (the melee follow-up on)",
            "score": " - the quickest kill first (the combo)",
            "explore": " - off this spot along open floor, the Ganado he kept at dropped",
            "next_area": " - off this spot along open floor, the Ganado he kept at dropped",
            "repetitive": " - dropped the Ganado he kept at for 15 s, another way",
            "missing": " - the aim's stick and turn sign measured again",
            "mine": ": RE4 Mercenaries has no mines - fighting on",
            "mine_trail": ": RE4 Mercenaries has no mines - fighting on",
            "flashbang": ": no native flash on RE4 Switch yet - fighting on"}
KILL_PACE_S = 3.0                        # doctrine.KILL_PACE_S: from this long after a kill the next one is owed
COMBO_WINDOW_S = 5.0                     # doctrine.COMBO_MAX_S: a kill later than this after the last one breaks the combo
# Where the Ganados were seen, so "go and find the enemies" survives an empty snapshot (the operator, 2026-11-12).
SIGHT_MEMORY_N, SIGHT_MEMORY_S = 24, 45.0
# 0.05 (was 0.25): the operator, 2026-11-12: "be able to fire their gun 20 times faster and repeatedly. Every gun
# should fire like a machine gun with rapid fire." The trigger was tapped four times a second (0.25 s between taps),
# which no mod can raise - fire_rate speeds the weapon's own animation, not the bot's press. 0.05 s is twenty trigger
# pulls a second: a machine gun, and still long enough for the engine to see each press as an edge (a tap is down+up,
# and a zero-length press is ignored). Recoil is already gone: the aim lock zeroes the weapon object's sway bounds
# (+0x3E0..+0x3EC), so the 20th shot lands where the 1st did.
FIRE_GAP_S = 0.05
BOW_FIRE_GAP_S = 0.0025                  # the bow's fast trigger gap: the operator's 20x (0.05 / 20). It was 0.02 -
                                         # 50 a second, which is the rifle's class of gap, not a rain of arrows.
# (the operator 2026-11-11 21:33: "If the bot isn't rapid firing on these threats, then they will be destroyed.")
# The shot's tolerance is the angle a Ganado's body covers at his distance (live 2026-11-10 22:07: 11 hits from 166
# shots with a flat 7-degree tolerance - 1.5 m off at 12 m): atan(FIRE_HALF_WIDTH_MM / distance), never under
# FIRE_TOL_MIN; inside AIM_NUDGE of it the right stick is tapped (a frame of turn) rather than held.
FIRE_HALF_WIDTH_MM, FIRE_TOL_MIN, AIM_NUDGE = 300.0, 0.05, 0.2
# FIRE_TOL_MIN 0.05 rad (~2.9 deg): the operator 2026-11-11 19:53 ("the bot is just holding up the weapon without
# firing it") - at 1.1 deg the aim's pad error almost never came inside the tolerance, so the raise/aim ticks repeated
# forever and the trigger never tapped. A hit needs the body's half width (0.3 m) inside 0.05 rad to ~6 m; past that the
# atan2 term is the tighter bound and the floor only forgives what an enemy's body still covers.
# The melee follow-up (docs/research/mercenaries-character-specials.md 2.1 / 6.1): RE4's Mercenaries is played shot ->
# stun -> the action button at the prompt (Leon's roundhouse / suplex, Krauser's double kick, HUNK's neckbreaker,
# Wesker's thrust punch, Ada's fan kick): a melee is a near-certain kill, hits the crowd round it and costs no ammo.
# The stun itself is not read from RAM yet, so the bot takes a Ganado whose health just fell (a hit, which is what
# stuns) within MELEE_MM in front, with nobody else at arm's reach (MELEE_CLEAR_MM: a melee's recovery in a crowd
# is how a bot gets grabbed), steps in to MELEE_REACH_MM and taps Y every MELEE_TAP_S while the window lasts. A Y
# with no prompt does nothing. Distances in mm.
MELEE = True
# Low life (PLAYER_LIFE): under LOW_LIFE of his maximum with a Ganado within LOW_LIFE_MM he turns and runs (the
# quick turn, then B + up) for LOW_LIFE_RUN_S rather than trade another hit.
# 0.35 / 1500 / 0.9 (was 0.5 / 3500 / 1.6): running from a Ganado 3.5 m away is running from grab range - live
# 2026-11-12 the bot recorded low_life 28 times in one session with 10 deaths and 0 kills in the round, because it kept
# turning its back at 3.5 m and getting caught. It now only breaks away under 35% health with a Ganado inside 1.5 m, and
# for under a second: far enough to clear a swing, not far enough to abandon the fight.
LOW_LIFE, LOW_LIFE_MM, LOW_LIFE_RUN_S = 0.35, 1500.0, 0.9
# The operator's no-lost-rounds rule (2026-11-11 20:58: "I do not want to see the bot losing rounds. Only winning via
# endless combos is acceptable"): the disengage threshold is half his health (was 35%), the danger ring 3.5 m (was 3),
# and the run 1.6 s (was 1.2) - he leaves a losing trade earlier and longer, so the combo chain survives instead of a
# death resetting it.
# Every escape (low life, a heavy, a swarm) runs to a point ESCAPE_MM away along OPEN FLOOR (operator 2026-11-10: "just
# walking into walls in RE4" - the low-life retreat had run him into a wall, blind, B + up after the quick turn):
# the away line (each Ganado within ESCAPE_FROM_MM pushing by 1/d^2), then ESCAPE_TRIES_DEG off it, the first whose
# segment the stage mesh calls clear (nav.clear_segment) and whose end is not within ESCAPE_CLEAR_MM of a Ganado.
# The run goes there by _approach (the mesh walker), the quick turn first when it lies behind him (ESCAPE_QUICK_RAD).
# Walled in on every line: no escape - he fights. Counters: escape_lines_walled, escapes_walled_in.
ESCAPE_MM, ESCAPE_FROM_MM, ESCAPE_CLEAR_MM, ESCAPE_ARRIVED_MM = 3000.0, 4500.0, 1200.0, 700.0
ESCAPE_TRIES_DEG = (0, 35, -35, 70, -70, 105, -105, 140, -140)
ESCAPE_QUICK_RAD = 2.2
# Walled in on open floor, a ladder DOWN is the way out (operator 2026-11-10: the bot did not notice the ladder and died
# cornered): the nearest down-ladder crossing of the stage mesh (re4_nav crossing rows, kind "ladder", direction "down")
# whose approach lies within LADDER_ESCAPE_MM of him and nearer him than any Ganado near him (they would reach it
# first otherwise). The goal is the landing; the mesh walker takes the crossing (approach, portal, Y pulse).
LADDER_ESCAPE_MM, LADDER_FOE_MARGIN_MM = 9000.0, 300.0
# Heavies (the chainsaw Ganados, the Garrador, the Gatling man: a maximum health of HEAVY_HP or more; ordinary Ganados
# read 400, one 3500 on 2026-11-10): they kill from full life in one blow (live 23:21, HUNK / Base: Unlimited life
# had undone 26 hits, then one took him from 1560 to 0), so one inside HEAVY_KEEP_MM is run from - the quick turn,
# then B + up for HEAVY_RUN_S - and shot from beyond it.
HEAVY_HP, HEAVY_KEEP_MM, HEAVY_RUN_S = 2000, 3500.0, 1.0
# The turn sign, checked live by the fight itself (2026-11-10: the stock round turned 4,365 ticks for 19 raises, the
# shape of a turn that runs away from its target): every turn tick compares the bearing error with the last one on
# the same Ganado; TURN_LEARN_N samples with the error growing at least 3x as often as it shrinks (+4) flip
# TURN_SIGN - here and in re4_walk, so the walker follows - and say so in stats (turn_sign, turn_sign_flips).
# 1 (was -1): the GameCube convention the fight tests encode, and the one the live learner converged on - the round
# telemetry read turn_sign="error > 0 turns left" after turn_sign_flips=1 (live 2026-11-12). Starting at -1 meant every
# fresh round turned the WRONG way until the learner noticed: turn_diverge 258 of 616 comparisons and turns=3366 in one
# round, i.e. essentially every tick spent turning - the operator's "just turning back and forth and not going forward".
# The default now agrees with the learner; TURN_LEARN still flips it if a build really is mirrored.
TURN_SIGN = 1                            # 1: an error > 0 turns left (the GameCube convention); -1: right
# The Switch build's tank/aim axes are mirrored against the GameCube data (re4_switch_nav): with +1 the aim turn
# pushed the error AWAY from the target and the bot span in a turn loop (live 2026-11-11 20:42: turns 495, raises 363,
# shots 74, hits 4, doing "turn"). _learn_turn still checks the facing each turn tick and can correct this live.
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
# 0.3 / 0.5 (was 0.6 / 1.5): the operator's "they need to be stopping threats that are advancing on them" - a 1.5 s
# flank with the gun down is 1.5 s of not shooting, and live 2026-11-12 the bot spent whole rounds in
# "no clear shot: to the spot 0.9 m on where it opens" (74 shots, 24 hits, 0 kills, round after round). It now gives the
# sight half the time and the flank a third of it before firing at whatever is closest.
SIGHT_HOLD_S, FLANK_S = 0.3, 0.5
# FLANK_GIVE_UP_S (live 2026-11-12): the sight gate could hold a shot, wait SIGHT_HOLD_S and flank FLANK_S for ever on a
# Ganado whose line never opens - the operator's frame showed the bot pressed into a Ganado at 01'56" with 0 kills, and the
# round read doing=flank. After this much flanking at one target the gate is over and he shoots it: a shot into partial
# cover beats standing in the open walking around a Ganado, which is what the whole round became.
FLANK_GIVE_UP_S = 1.5
# The flank's end (live 2026-11-10, Castle r402: 22.6 s of 60 flanking, "no clear shot: round it by the mesh walker"
# the commonest reason - the whole route walked to a Ganado in the doorway when one step showed him). FLANK_LOS: a
# flank ends the tick the shot is open from where he stands; until then it walks to the nearest point along the mesh's
# route to the target from which the shot is clear (FLANK_SAMPLE_MM samples, FLANK_LOOK_MM at most, the route's first
# crossing at most), stops there and fires. Stats flank_los_opens, flank_los_goals. Off: the whole route to him.
FLANK_LOS = True
FLANK_SAMPLE_MM, FLANK_LOOK_MM, FLANK_ARRIVE_MM, FLANK_GOAL_S = 300.0, 12000.0, 400.0, 1.0
# No turning off a pack he is winning against (the same trace: a grudge pick, "he hurt him this round (2 hits), 4.5 m
# off", turned him from the Ganados at the doorway). PACK_KEEP: the scorer's grudge or the combo's quickest kill takes
# over from the target he is firing at (a shot within PACK_KEEP_S) only within the gun's swing (AIM_KEEP_RAD), or when
# he is hurt (his life fell within PACK_HURT_S) or swarmed (SWARM_N within SWARM_CM). Stats pack_keeps.
PACK_KEEP = True
PACK_KEEP_S, PACK_HURT_S = 1.5, 2.0
SIGHT_LOG = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-sight-blocks.jsonl"
SIGHT_LOG_EVERY_S = 1.0
WALK_LOG = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-walk-presses.jsonl"
# FROZEN_TAP_S 0.06 (was 0.2): 0.2 s is five taps a second, and live 2026-11-12 the bot died 7 times in 16 rounds in
# doing=grabbed with 36 straight hits and 0 kills - the grab's mash was too slow to break the hold, so it never got a
# shot away. A mash wants every frame it can get; 0.06 s is the engine's practical floor for a tap and 16 a second.
FROZEN_MM, FROZEN_RAD, FROZEN_TAP_S, FROZEN_KEY = 30.0, 0.01, 0.06, "a"
FROZEN_FIRE_S, FROZEN_FIRE_SHOTS = 5.0, 8   # firing this long / this many shots, unmoved and without a hit: not in control
TURN_LEARN, TURN_LEARN_N = True, 16
MELEE_MM, MELEE_REACH_MM, MELEE_CLEAR_MM = 2500.0, 1400.0, 2000.0
MELEE_WINDOW_S, MELEE_TAP_S, MELEE_CONE = 1.6, 0.3, 0.5
# The universal core (gbox.mercs.core.combat; the operator 2026-11-10: "I want the same aimbot I am critiquing in RE4 to
# improve across 5 and 6 ... I hate seeing the bot idle in RE4"): with UNIVERSAL_CORE on, the fight goes through the
# shared components, each where RE4 had nothing of its own:
#   * who hurt him (combat.Threats over gbox.mercs.threat_memory, THREAT_FILE): every fall of his life put on the
#     Ganado that landed it; that one is a grudge for the round and the target before the crowd's / the combo's pick
#     (_choose); a learned attack that has landed through his shots is run from along open floor (_lethal_out). The
#     Switch census reads no Ganado motion yet, so the learned wind-ups wait for one (the reach and the grudges do not);
#   * bosses and dangerous foes first (combat.identity_tier: gbox.mercs.enemy_identity once it lands, beside RE4's own
#     read - a heavy, HEAVY_HP, is "dangerous"): in reach on his level, before the grudge, never at the cost of one
#     at arm's length (SWARM_CM) - shot from beyond HEAVY_KEEP_MM, where _heavy_keep leaves him;
#   * the body profiles (combat.BodyTable, BODY_CLASSES): the shot's tolerance from the target class's own width;
#   * the not-in-control detector (combat.NotInControl): _frozen's two rules, a spell at most FROZEN_PAGE_MAX_S (paged
#     that long without a move, A is not the remedy and the fight goes on);
#   * the idle guard (combat.IdleGuard): the gun up IDLE_AIM_S at a Ganado in range without one shot (a gate that
#     holds, an aim that does not close) - he rounds him (the flank) instead of standing there aiming.
# Off: the fight as before (the rollback). A core error never costs the tick: the old path runs (universal_core_error).
UNIVERSAL_CORE = True
THREAT_FILE = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "re4-switch-threats.json"
THREAT_REACH_MM, GRUDGE_MM, LEVEL_MM = 3000.0, 10000.0, 2500.0   # (RE5's WINDUP_R / GRUDGE_R; doctrine LEVEL_M)
LETHAL_KEEP_X, LETHAL_BACKOFF_MAX_S, LETHAL_RUN_S = 1.15, 1.8, 1.0
FROZEN_PAGE_MAX_S = 4.0
IDLE_AIM_S = 2.0
# The raise / aim discipline (combat (g); live 2026-11-10 22:5x, Krauser / Base, the operator: "What is the bot doing
# right now? It's like walking into the wall flickering": 18 stand breaks and 5 flanks in 70 s, fire -> turn -> fire, the
# bow half-raised against a grid wall). RE4 cannot walk with the gun up, so every target switch past RAISE_TOL lowered
# it for a tank turn, and the never-stand step - blind, a step forward with a turn - lowered it again and walked into
# the wall. With UNIVERSAL_CORE:
#   * with the gun up, a target within AIM_KEEP_RAD is turned to with the stick that moves the aim (combat.AimStick
#     learns it live: the right stick first, as the manual says; held AIM_STICK_N ticks without his facing changing,
#     the left stick; its sign from which way his facing goes) - the gun goes down only to turn past it;
#   * a target in fire range with the shot not blocked meets the never-stand rule while he fires or his facing turns
#     toward it (the kill clock is the anti-idle there): no step; STAND_TURN_RAD of facing is progress;
#   * a step goes STAND_STEP_MM along open floor (combat.open_step on the stage mesh's clear_segment, not ending within
#     ESCAPE_CLEAR_MM of a Ganado); walled in on every line, no step (steps_walled_in).
AIM_KEEP_RAD, AIM_STICK_N, STAND_TURN_RAD, STAND_STEP_MM, STEP_TURN_RAD = 1.0, 10, 0.05, 2000.0, 0.8
# The steady aim cannot wait forever for a laser that never reads (see _ram_aim): past this it aims and fires the old
# way. AIM_READY_S is the raise itself, so this is the raise plus a beat.
AIM_RISE_MAX_S = 1.5
# FIRE_FIRST (the operator 2026-11-10, a live round: "the bot is raising their weapon over and over and getting
# defeated ... it needs to fire and deal with threats before lowering his weapon and fleeing or throwing grenades"):
#   * a living Ganado on him (FIRE_FIRST_MM) with a clear shot line from where he stands is answered with the gun: the
#     heavy's keep-away, the swarm's escape and the grenade swap stand down, and the never-stand step / the wall's
#     tangent do not lower the gun for them (the low-life run stays the doctrine's own answer, RESPOND);
#   * a target switch while that close keeps the gun up to AIM_KEEP_CLOSE_RAD, turned with the aim stick;
#   * the gun's lowering is counted with what did it (gun_downs / gun_down_last / gun_down_<doing>) so a live round
#     says why he raised and lowered (the operator's camera complaint).
FIRE_FIRST, FIRE_FIRST_MM, AIM_KEEP_CLOSE_RAD = True, 4500.0, 2.6
ENGAGED_DOINGS = frozenset({"turn", "aim", "fire", "hold"})
# Pressed against a wall (combat.WallPress; live 2026-11-10, Krauser / Base on the greybox build, the camera inside a
# wall and the bot not fighting - the operator: "the issue is more like this"). Every action that walks him (the left
# stick up, the gun down) goes through _wall_core, whatever made it (the locate, the flank, a run, the sweep, a step):
#   * WALL_PRESS_S of it with under WALL_PRESS_MM of ground while he is in control is a wall: remembered WALL_KEEP_S,
#     and a walk from within WALL_R_MM of it within WALL_CONE of that heading is refused from then on (never the same
#     wall again: he goes along it instead, the first open heading nearest the one he wanted);
#   * pressed, he turns away (the quick turn when the open floor is behind him) and steps UNWALL_MM onto open floor -
#     the first heading from straight back that is no remembered wall and that the stage mesh's clear_segment allows -
#     for at most UNWALL_S; walled in on every side, he stops walking into it (walls_boxed_in);
#   * the walker's mesh guard (re4_walk.Walker.guard: open floor within its probe ahead, else the nearest clear
#     heading) covers the bot's own walks too.
# The camera is not read on Switch, so its distance collapsing is no signal here; the stick against an unmoving
# position is. Stats walls_pressed, unwalls, walls_refused, walls_boxed_in.
WALL_PRESS_S, WALL_PRESS_MM, WALL_KEEP_S, WALL_R_MM, WALL_CONE = 0.6, 150.0, 60.0, 1500.0, 0.7
UNWALL_MM, UNWALL_S, CONTROL_S = 2500.0, 1.6, 5.0
SLIDE_TRIES_DEG = (45, -45, 90, -90, 135, -135, 180)             # a refused walk: along the wall, nearest first
# The room's real map (#9342, docs/research/re4-switch-mercs-collision.md, checked against the RomFS and live RAM
# positions: gbox.re4_switch_room_map; the operator's top RE4 complaint, 2026-11-10: he walks into walls and pins the
# camera). WallPress above learns a wall only once he is pressed against it; the room map knows them first. ROOM_MAP:
#   * every walk line the bot picks itself - an escape (_escape_goal), a never-stand step (combat.open_step), the way
#     off a wall (WallPress.away) - must be walk-clear on the room map too (titles.re4_room_map.walk_block): floor all
#     the way, no wall within his body's height crossed (the invisible blockers too, which the shot line passes), not
#     ending within re4_room_map.BODY_R_MM of one. The stage mesh's shot-line test (nav.clear_segment) stays;
#   * every tick that walks him (the left stick up, the gun down), whatever made it, probes ROOM_PROBE_MM along his
#     facing (ROOM_PROBE_RUN_MM running): a wall (crossed, or closed in on nearer than ROOM_BRUSH_MM - a corner, a
#     shallow angle) or the floor's edge there and that step is refused - along the wall
#     instead (WallPress.away, SLIDE_TRIES_DEG), or, when the mesh walker's route steers this tick and the line to its
#     point is clear, a turn on the spot toward that point; a crossing the walker is taking (a jump-over, a ladder) is
#     left to it;
#   * the line of sight with no stage mesh attached (snap["nav"] None) is the room map's: its walls at the shot's own
#     height, blockers passing (with the mesh, its exact triangle test stands: it stops a shot through every #9342
#     wall but the ones with an opening in them).
# Stats room_map (the room), room_map_walks_refused, room_map_steps_refused, room_map_route_turns, room_map_boxed_in,
# room_map_refused_last. Off: as before (the rollback).
ROOM_MAP = True
ROOM_PROBE_MM, ROOM_PROBE_RUN_MM = 800.0, 1300.0
ROOM_BRUSH_MM = 200.0     # the probe's own body half width: closer than this to a wall it is refused (his collision
                          # radius is not measured; the lines he picks keep re4_room_map.BRUSH_R_MM, 300 mm, of margin)
# The probe is scaled to the room (the operator 2026-11-10: "a probe scaled to the room"): ROOM_PROBE_SHARE of the
# room's smaller side, never under ROOM_PROBE_MM nor over ROOM_PROBE_MAX_MM (running: at least ROOM_PROBE_RUN_MM). A
# corridor is not probed like an arena. The way along a wall he is turned onto is scaled the same way
# (ROOM_UNWALL_SHARE, up to ROOM_UNWALL_MAX_MM) so a step reaches the wall's end or an opening, not a body's length on.
ROOM_PROBE_SHARE, ROOM_PROBE_MAX_MM = 0.04, 2000.0
ROOM_UNWALL_SHARE, ROOM_UNWALL_MAX_MM = 0.15, 6000.0
# The wall's tangent (the operator 2026-11-10: the bot "is still turning back and forth and is stuck in the same room";
# a bot_trace of session 25385f8f4eb94342-6eb677c2f1194dea: the room map's unwall, "a wall ahead, along it instead",
# sent a pure sideways stick - a 90 deg turn on the spot in a tank-controlled game - and the walker turned him back into
# the wall). ROOM_TANGENTS: the room map's refusal names the wall (core.room_map.RoomMap.walk_block_detail); the way
# off it is that wall's own tangent (RoomMap.tangents), not a heading across the room: he turns to the tangent, then
# pushes forward along the wall, which is a way the route and the walker do not undo. The side is kept per wall for at
# least UNWALL_SIDE_HOLD_S (a new look never flips it sooner; WALL_KEEP_S while that wall is his), so a wall he walks
# along stays on one hand instead of being crossed back over. Stats unwall_tangents, unwall_side_switches.
ROOM_TANGENTS, UNWALL_SIDE_HOLD_S = True, 0.8
ROOM_TANGENT_MAX_RAD = 2.2                # a tangent further off his facing than the quick turn's own: not this way
UNWALL_TANGENT_S = 4.0                    # a tangent detour's own cap (UNWALL_S for the step off a pressed wall): it
                                          # ends at the shot opening, not at the step's end
# The mesh's own route legs pass (live 2026-11-10, Castle r402, the operator: "why does the bot meander and move at
# walls so weird?": the route went through the arena's west doorway, 1.38 m wide, and the probe refused the step at its
# jamb - "brushes a wall 16061,-28649-16103,-27186 (94 mm)" - so he slid up and down the wall beside the opening for
# 10 s, the walls he had pressed there refusing it for a minute more). ROOM_LEGS: a tick whose walk is the mesh
# walker's own route leg (its steer, toward a waypoint the mesh's floor reaches straight from him: re4_walk.Walker.leg)
# is left to the mesh - neither the room map's probe nor a remembered press refuses it (stats room_map_route_legs). The
# room map still guards every free step: the never-stand step, the escapes, the way off a wall, a melee approach, the
# sweep, the walker's straight line - and the line of sight. A doorway narrower than the margins allow gets margins
# scaled to its width (core.room_map.GAP_MARGIN_X).
ROOM_LEGS = True
# The camera collapsed (the operator's screenshot 2026-11-10: Krauser and Leon pinned, the camera inside a wall; the
# camera read from RAM: camera_state, #9386). The engine pulls the camera in against geometry, so while the stick walks
# him (in control, the gun down CAM_SETTLE_S - the aim's own zoom-in is no wall) a camera-to-player distance
# (snap["camera_dist_mm"]) under CAM_COLLAPSE_X of its running median for CAM_COLLAPSE_S is a wall press for WallPress
# above (combat.CameraCollapse): remembered at his facing and turned away from at once - the room map's walk test keeps
# the way off it clear of the wall behind him too. Stats camera_dist_mm, camera_collapses. Off: as before.
CAMERA_COLLAPSE = True
CAM_COLLAPSE_X, CAM_COLLAPSE_S, CAM_SETTLE_S = 0.6, 0.15, 1.0
# The throw (combat.ThrowPolicy, THROWS; the operator 2026-11-10: grenades at the enemies all the time, also while he
# flees): a hand / incendiary grenade at a pack (THROW_PACK_N within THROW_PACK_MM of one another, its centre between
# THROW_MIN_MM - outside his own blast - and THROW_MAX_MM) or at a heavy; a flash at a Ganado at arm's length; at most
# every THROW_GAP_S, his escape run or not (a throw back at the pursuers). The title's own path: the in-hand item swap
# re4_switch_mods already makes for the random weapon (_give_weapon's writes: the held item's id, the item manager's
# held id, the game state's class bytes), asked through HAND_REQUEST and answered in HAND_STATE by maintain() on every
# snapshot; then the manual's throw - the aim (ZL) and the fire (ZR) - and the hand's own bytes written back (the gun
# back). Each swap is a fresh grenade (no count to spend: infinite by construction); RE4 has no animation-speed mod to
# reuse, so the throw plays at the game's speed. NOT seen live yet: whether the game throws a grenade put in the hand
# this way - so off until a watched round turns it on (the sidebar's bot-logic knob THROWS, or here).
# The grenade ring and the scatter barrage (checkpoints F/G): the native harness's own blasts (flash 4000 mm floor,
# hand 7000, the barrage mixed). Both automatic paths are OFF until a live receipt per kind; the ops stay available
# for clicks/probes. Distances here are millimetres; the shared rule works in cm and the controller converts at its
# boundary (`re4_switch_native`), so the knobs keep the shared names.
# Operator 2026-11-11 20:34: "i want to see 360 launcher blast grenade launcher protection rounds happening every
# minute and a half across mercenaries RE 4 5 and 6." RE4's ring was off entirely; the launcher kind fires the title's
# own rounds (grenade_ring.launcher_rounds falls back to the title's grenade kinds for the launcher). RING_EVERY_S is
# the ring cooldown; the every-90-s periodic ring is grenade_ring.periodic_s (90.0), deployed.
RING, RING_N, RING_EVERY_S, RING_KIND = True, 4, 90.0, "launcher"
SCATTER, SCATTER_EVERY_S, SCATTER_N = False, 12.0, 8
SCATTER_FLASH_ONLY = False            # flash and hand are built: the flash cap narrows the draw, never refuses it


def scatter_kinds() -> tuple:
    """The kinds a random barrage can draw: the RE4 harness's built blasts (flash, hand; incendiary is G3)."""
    from . import re4_switch_native as native
    return tuple(native.SCATTER_KINDS)


THROWS = False
THROW_GAP_S, THROW_PACK_N, THROW_PACK_MM, THROW_FLASH_MM = 5.0, 3, 3000.0, 4000.0
THROW_MIN_MM, THROW_MAX_MM = 6000.0, 12000.0
THROW_HAND_S, THROW_RAISE_S, THROW_SETTLE_S, THROW_MAX_S = 1.0, 0.4, 0.8, 3.0
THROW_ITEMS = {"hand": 0x01, "fire": 0x02, "flash": 0x0E}     # re4_weapons.NAMES: hand / incendiary / flash grenade
# The heal: hurt, the first aid spray into his hand through the same flag write the grenades use (HAND_REQUEST), used,
# and the gun back - never the item screen. The operator, 2026-11-12: "they have unlimited healing items, so they should
# always have the ability to use a first aid spray and heal themselves if they need to in the game ... I don't want them
# bringing up the item screen. I want them able to just instantly just change their weapon by flipping a flag and
# changing it to the first aid spray and using it in the game in order to survive."
# The heal's route is blocked on this build, and only on this: HAND_REQUEST resolves WEAPON rows (that is how a grenade
# goes to his hand) and the First Aid Spray is an ITEM - the swap answers "ValueError: no weapon row for First Aid
# Spray" (live 2026-11-12, 4 aborts in one round). So it can never succeed until the mods can put an item row in his
# hand. The NAME COLLISION that froze a round is fixed either way (the state is _heal_state, so it can no longer shadow
# the _heal method), and the abort is clean and bounded by HEAL_BLOCK_S. Off until the item row exists, so a doomed
# swap does not spend its hand/back phases out of the fight every 8 s.
HEAL_ON = False
HEAL_ITEM = 0x05                        # re4_weapons.NAMES: "First Aid Spray"
HEAL_BELOW, HEAL_HAND_S, HEAL_USE_S, HEAL_SETTLE_S = 0.55, 0.7, 0.15, 0.3
# A FAILED swap must not become the round (live 2026-11-12, Waterworld: doing=heal "the first aid spray to hand (548 of
# 1560)" for the rest of the round, heals 0, shots 14 hits 2 kills 8 - hp stayed under HEAL_BELOW, so the abort cleared
# the state, the next tick started another swap, and he never fired a shot again). After a failed swap the heal is left
# alone this long and the fight resumes.
HEAL_BLOCK_S = 8.0
# Hit, break contact (the operator's choice, 2026-11-12): asked to pick between fleeing a heavy first and firing first,
# he said "keep firing but back off after the first heavy hit lands" and "I don't want the bot getting hurt - just have
# the bot locating and fighting these threats". So the fire-first rule stands until a blow actually lands, which is the
# only honest signal that the trade is being lost - a heavy kills from full life in one blow, so the second must miss.
HIT_BACKOFF_S = 1.2
# One backoff per landing, not a retreat loop: without a gap the bot is hit, turns away for 1.2 s, comes back into the
# crowd, is hit again, and never fires - live 2026-11-12 showed doing=backoff "hit 0.0 s ago" round after round with a
# handful of kills. And a hit that came from across the stage is not a reason to turn his back on it; only a foe within
# HIT_BACKOFF_RANGE_MM earns the break.
HIT_BACKOFF_GAP_S, HIT_BACKOFF_RANGE_MM = 3.0, 8000.0
HAND_REQUEST: dict = {}       # the bot's ask of re4_switch_mods: {"item": an item id, or None = the gun back, "seq", "at"}
HAND_STATE: dict = {}         # its answer: {"seq", "item" (in hand now, None = the gun), "verified", "error"}
# The doctrine's answer to a threat (gbox.mercs.core.respond; the operator 2026-11-10: "the secret to all adversarial
# combat situations is either flashbang, drop a mine, or fire the weapon upon them until there's no longer a threat";
# live the same day, Leon / Base: "unwall: walled in on every side" for seconds at a time, doctrine_idle_s 80 of 199 s):
# hurt in the last 1.5 s, or a Ganado within 2500 mm closing / of a class that hurt him (its learned reach, combat.Threats),
# and his own decision answered nothing - RE4 Switch has no flash (THROWS off: the in-hand grenade swap is unproven
# live) and Mercenaries here has no mines, so the answer is fire: _fight on the threats alone with no run-off (the
# low-life retreat, the heavy's keep-away and the swarm escape stand down while it fires; the sight gate and the flank
# keep every wall shot out). threat_lacks_flash / threat_lacks_mine count the ticks a flash or a mine was wanted.
RESPOND = True
RESPOND_BUSY = frozenset({"frozen", "dead", "wait", "intro", "grabbed", "held", "case", "results", "backoff"})
RESPOND_AIM = frozenset({"turn", "aim", "hold", "reload"})
RESPOND_ATTACK = frozenset({"fire", "melee"})
# Body profiles: enemy class -> a combat.KIND_BODIES name or a combat.Body (cm). Every Ganado is one class (villager,
# zealot and soldier alike, a heavy too), so his is the default; a class of another shape joins the census first.
BODY_CLASSES: dict = {}
# The fire pattern (gbox.mercs.core.fire_pattern; the operator 2026-11-10: "the bot fired the magnum with a nice scatter
# and a very rapid repeat and i want that across all these titles"). RE4's rapid repeat is already the bot's own: ZR
# tapped every FIRE_GAP_S, which re4_switch_mods.fire_rate paces to 0.25 s / N (0.05 s, a tap every 20 Hz tick, at the
# live 20x); the game takes at most FIRE_CAP_HZ (the shot gate waits for the firing motion to cross frame int(FR) - 2,
# so FR 3.0 at 30 Hz frames is the floor - re4_weapons.RAPID_FIRE_FLOOR, static analysis, not counted live). What the
# pattern adds is the scatter and the crowd hop, both through the aim RE4 already has:
#   * the scatter: no pitch here (tank aim), so shot after shot the facing goes to his bearing plus a yaw offset across
#     his body (combat.TankDriver: up to 0.6 of his half width for a magnum) - by AIM_REQUEST, which the aim lock
#     (re4_switch_mods.aim_lock, on live) writes into his facing every snapshot; the fire gate stays the body's
#     half-angle on the bearing error, so a scattered shot is one the gate allowed before. Earned: only within
#     fire_pattern's earn_s of a hit or a kill - an intro card (no effect) keeps every shot on his chest, so the
#     NotInControl fire rule sees the unmoving facing it did before;
#   * the hop: after hop_every taps on one living Ganado, the next goes to one already inside the gun's line cone
#     within 2.5 m of him, on his level and in the clear - only for the REST picks (FIRE_HOP_WHYS: the crowd's, the
#     combo's, the nearest), never away from a wind-up, a boss / dangerous one or a grudge.
# The family of the gun in hand: the game state's equipped class (re4_weapons.G_CLASS, read in snapshot as
# snap["weapon_class"]; the byte the random weapon writes) through CLASS_FAMILY; an unread class is FIRE_DEFAULT_FAMILY.
# Off: every shot at his chest, as before (one constant). Stats fire_pattern_*.
# The magnums only (operator 2026-11-10: "the scatter works if they have a magnum and 20x firerate. Its boring with the
# pistol"; and "the bot aims terribly, their laser goes awry weirdly"): handguns keep every shot on the body (no
# family), the magnums / shotguns / rifles keep their pattern; an unread class has none.
FIRE_PATTERN = True
FIRE_CLOSE_MM = 3000.0                   # no deliberate scatter on a body inside 3 m (operator 2026-11-11: the close
                                         # misses - the magnum's scatter off a body at arm's length was most of them)
FIRE_CAP_HZ = 10.0                       # static: FR 3.0 frames at 30 Hz (the shot gate's floor), not counted live
FIRE_DEFAULT_FAMILY = None
CLASS_FAMILY = {0x01: None, 0x02: None, 0x03: None, 0x04: None, 0x11: None,   # handguns: no scatter
                # 0x01 is also the Riot Gun's class (items 0x21/0x40) and it read None here, so weapon 33 fired with
                # no fire-pattern family - 9 shots, 0 hits (live 2026-11-11 23:23). Giving the class a scatter family
                # was tried and then reverted: RE4 then churned 19 rounds with 0 kills (live 2026-11-12 00:17), so a
                # shotgun model on a class that was verified with none is worse than the misfire it was meant to fix.
                # The item-id entry that used to sit here (0x21) was an ITEM in a class-keyed table and is gone.
                0x05: "magnum", 0x06: "magnum", 0x0F: "magnum",      # Broken Butterfly, Killer7, Handcannon
                0x07: "shotgun", 0x08: "shotgun",                    # Shotgun, Striker
                0x09: "rifle", 0x0A: "rifle",
                0x0B: None, 0x0C: None, 0x0D: None, 0x0E: None, 0x10: None, 0x1C: None, 0x2E: None}   # automatics,
                                         # launchers, the knife, the bow, the P.R.L.: no pattern
FIRE_HOP_WHYS = ("crowd fire", "the combo is owed", "the nearest Ganado")   # _choose's REST picks


# The aim book (gbox.mercs.core.aim_book; the operator 2026-11-10: "Every missed shot should train the bot to how they
# need to adjust their fire ... learning across these titles so they all get better"): every tap is a shot record - the
# point meant on him (his chest moved by the book's body point and lead), the line the gun really had (the laser's
# statics read from RAM, AIM_RAM; else his facing plus the waist twist), the game's answer (his health within
# aim_book.HIT_S) - and every resolved one teaches the book (learned/010099A00BC1E000/aim_book.json, its sub-cells in
# learned/_universal/aim_book.json for RE5 / RE6). AIM_BOOK off: no records, no corrections.
AIM_BOOK = True
AIM_LEAD_PRIOR_S = 0.10                  # snapshot -> the lock's write on the next one -> the game's frame: about 2 ticks
# The steady aim with the RAM aim (AIM_RAM, the aim lock on: re4_switch_mods._steady): the facing and the centre pitch
# written onto the book's point through the laser's own line (closed loop: the line's yaw / pitch error each tick, the
# pitch at AIM_PITCH_GAIN of it), the sway and the waist twist zeroed, no right-stick taps; the trigger only while the
# game's own sight (the weapon object's m_SightEm) names a living Ganado - the one on the line is the one shot. Gun up
# without a sight AIM_SIGHT_STALL_S: the old body-angle gate fires (aim_ram_sight_fallbacks), so a sight that never
# reads cannot hold the fire forever. GUN_H_MM: the gun's height while the line is not read yet (the open-loop pitch).
AIM_PITCH_GAIN, AIM_SIGHT_STALL_S, GUN_H_MM, AIM_LOCK_LIVE_S = 0.8, 1.5, 1450.0, 1.0
#: A close threat gets the old body-angle gate much sooner (operator 2026-11-11: "the bot just sits there instead of
#: firing on the enemies ... I'm watching him just watch them come up"): the steady aim's sight stall is 1.5 s at
#: range, 0.4 s inside AIM_SIGHT_CLOSE_MM, so a Ganado already on him is shot by his own gate before it reaches him.
AIM_SIGHT_STALL_CLOSE_S = 0.4
AIM_SIGHT_CLOSE_MM = 3000.0
AIM_FAMILY = {0x01: "handgun", 0x02: "handgun", 0x03: "handgun", 0x04: "handgun", 0x11: "handgun",
              0x05: "magnum", 0x06: "magnum", 0x0F: "magnum", 0x07: "shotgun", 0x08: "shotgun", 0x21: "shotgun",
              0x09: "rifle", 0x0A: "rifle", 0x0B: "automatic", 0x0C: "automatic"}


def aim_family(snap) -> str:
    """The aim book's family of the gun in his hand: every gun has one (the fire pattern's leaves the handguns out)."""
    cls = (snap or {}).get("weapon_class")
    if not isinstance(cls, int) or isinstance(cls, bool):
        return "gun"
    return AIM_FAMILY.get(cls, "other")


def fire_family(snap) -> str | None:
    """The fire pattern's family of the gun in his hand (snap["weapon_class"]), FIRE_DEFAULT_FAMILY when unread."""
    cls = (snap or {}).get("weapon_class")
    if not isinstance(cls, int) or isinstance(cls, bool):
        return FIRE_DEFAULT_FAMILY
    return CLASS_FAMILY.get(cls, FIRE_DEFAULT_FAMILY)


def threat_class(e) -> str | None:
    """The class threat memory learns a RE4 enemy under: its unit class with its maximum health (every Ganado is one
    vtable; a chainsaw man reads 3500 where a villager reads 400)."""
    cls = (e or {}).get("class")
    if cls is None:
        return None
    top = e.get("hp_max")
    name = f"{cls:#x}" if isinstance(cls, int) and not isinstance(cls, bool) else str(cls)
    return f"{name}:{top}" if isinstance(top, int) and not isinstance(top, bool) else name


def combat_profile() -> combat.TitleProfile:
    """RE4 Switch's calibration of the universal fight, from the live constants (a knob turned is in the next one)."""
    return combat.TitleProfile(
        title="re4_switch", title_id=TITLE_ID, units_per_cm=MM_PER_CM, aim_model="tank_heading",
        sticks="tank: the left stick turns the body (TURN, TURN_SIGN); ZL held, the right stick fine-turns the aim "
               "(AIM_TURN); ZR tapped",
        aim_btn=AIM_BTN, fire_btn=FIRE_BTN, turn_sign=TURN_SIGN, raise_s=AIM_READY_S, raise_tol=RAISE_TOL,
        fire_tol_min=FIRE_TOL_MIN, engage_cm=ENGAGE_RANGE_CM / MM_PER_CM, level_dy_cm=LEVEL_MM / MM_PER_CM,
        max_dy_cm=LEVEL_MM / MM_PER_CM,
        bodies=combat.BodyTable(default=combat.HUMAN._replace(r=FIRE_HALF_WIDTH_MM / MM_PER_CM), classes=BODY_CLASSES),
        specials=("melee_follow_up", "quick_turn", "knife", "special_arm"),
        threat_file=THREAT_FILE, windup_r_cm=THREAT_REACH_MM / MM_PER_CM, grudge_r_cm=GRUDGE_MM / MM_PER_CM,
        lethal_keep_x=LETHAL_KEEP_X, lethal_backoff_max_s=LETHAL_BACKOFF_MAX_S,
        class_key=threat_class, motion_key=lambda e: None, attacking=None, windup=None,
        turn_w=1.0, level_w=0.0, keep_x=1.5, grab_r_cm=SWARM_CM / MM_PER_CM,
        tier=combat.identity_tier(TITLE_ID, fallback=combat.hp_tier(dangerous_hp=HEAVY_HP)),   # a heavy: dangerous
        page_key=FROZEN_KEY, frozen_cm=FROZEN_MM / MM_PER_CM, frozen_rad=FROZEN_RAD, no_effect_s=FROZEN_FIRE_S,
        no_effect_shots=FROZEN_FIRE_SHOTS, step_s=STAND_STEP_S, page_tap_s=FROZEN_TAP_S, page_max_s=FROZEN_PAGE_MAX_S,
        page_clear_cm=0.0, idle_aim_s=IDLE_AIM_S,
        throw_kinds=tuple(THROW_ITEMS) if THROWS else (), throw_gap_s=THROW_GAP_S, pack_n=THROW_PACK_N,
        pack_r_cm=THROW_PACK_MM / MM_PER_CM, throw_min_cm=THROW_MIN_MM / MM_PER_CM,
        throw_max_cm=THROW_MAX_MM / MM_PER_CM, flash_r_cm=THROW_FLASH_MM / MM_PER_CM,
        fire_pattern=FIRE_PATTERN, fire_style="tap", fire_gap_s=FIRE_GAP_S, fire_tick_s=0.05, fire_cap_hz=FIRE_CAP_HZ,
        fire_cap_note="static: the shot gate's FR 3.0 floor at 30 Hz frames (re4_weapons); the bot taps every "
                      "FIRE_GAP_S (0.05 s at fire_rate 20x); magnum classes' own rows not read",
        family=fire_family)


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

    def _close_threats(self, p, snap) -> list:
        """[(distance, bearing error, enemy)] of the living Ganados within FIRE_FIRST_MM: the ones on him now."""
        try:
            return [t for t in self._live(p, snap.get("enemies") or ()) if t[0] <= FIRE_FIRST_MM]
        except Exception:                                # noqa: BLE001 - a read error never costs the tick
            return []

    def _shootable(self, p, snap, near=None) -> bool:
        """A Ganado on him now (within FIRE_FIRST_MM) with a clear shot line from where he stands: the fight can answer
        it without walking (FIRE_FIRST). The clear-line test reaches ENGAGE_RANGE_LOS_CM when the nav/obstacle data is
        there to prove it; inside FIRE_FIRST_CLOSE_MM the body itself is the target and the strict line test stands
        down (a Ganado that closed inside 9 m is answered, never watched - operator 2026-11-11 19:20)."""
        near = self._close_threats(p, snap) if near is None else near
        try:
            reach = ENGAGE_RANGE_LOS_CM if (snap.get("nav") or snap.get("obstacles")) else ENGAGE_RANGE_CM
            for t in near:
                if t[0] > reach:
                    continue
                if t[0] <= FIRE_FIRST_CLOSE_MM or self._line_of_sight_ok(p, t[2], snap):
                    return True
            return False
        except Exception:                                # noqa: BLE001 - no geometry: the range limit does the gating
            return False

    def _fire_first(self, p, snap, now=None) -> bool:
        """FIRE_FIRST: a Ganado on him now with a clear line the fight can answer from where he stands - the gun, not a
        walk (the heavy's keep-away, the swarm's escape, a grenade swap and the wall's tangent). One look a tick."""
        been = self.__dict__.get("_ff")
        if now is not None and isinstance(been, tuple) and been[0] == now:
            return been[1]
        got = bool(FIRE_FIRST and self._shootable(p, snap))
        if now is not None:
            self.__dict__["_ff"] = (now, got)
        return got

    @staticmethod
    def _nearest(p, enemies):
        """The nearest living Ganado (kept for the first cut's callers)."""
        px, _, pz = p["pos"]
        live = [(math.hypot(e["pos"][0] - px, e["pos"][2] - pz), e)
                for e in enemies if (e.get("hp") or 0) > 0 and e.get("pos")]
        return min(live, key=lambda t: t[0])[1] if live else None

    def _count_kills(self, snap, now) -> None:
        """Kills: the game's own counter when it is read (MercSysWk + MW_KILL), else a census unit whose health fell to
        0. The census still counts the hits either way (a health that fell: the melee follow-up's window)."""
        kills = snap.get("kills")
        game_count = isinstance(kills, int) and not isinstance(kills, bool)
        if game_count:
            if kills > self.__dict__.get("_game_kills", 0):
                self._kill_at = now                      # (a new round's count starts again from 0)
            self._game_kills = kills
            self.stats["kills_seen"], self.stats["kills_source"] = kills, "game"
        seen = {}
        for e in snap.get("enemies") or ():
            key = e.get("ptr")
            if key is None:
                continue
            # `e.get("hp") or 0` turned an unreadable health into 0, and 0 is the value that means dead - so an enemy
            # whose hp failed to read for one frame was stored as dead, and the next frame's `was > 0` was False: the
            # hit AND the kill were dropped (live 2026-11-12: 54 shots, 0 hits, 0 kills over 15 rounds). An unreadable
            # health is now skipped instead of being recorded as a corpse.
            hp = e.get("hp")
            if hp is None:
                continue
            was = self._hp.get(key, 0)
            if was > 0 and hp < was:
                self.stats["hits"] += 1
                self._hit_at[key] = now
            if was > 0 and hp <= 0:
                if not game_count:
                    self.stats["kills_seen"] += 1
                    self._kill_at = now
                if now - self._melee_at.get(key, -1e9) <= MELEE_WINDOW_S:
                    self.stats["melee_kills"] += 1          # he went down inside a melee's window
            seen[key] = hp
        self._hp = seen
        if not game_count:
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
            rm = re4_room_map.for_snap(snap) if ROOM_MAP else None
            if rm is None:
                return True                                 # no geometry yet: range limit does the gating
            try:                                            # the room map's walls at the shot's height (ROOM_MAP)
                return rm.sight_clear(tuple(p["pos"]), tuple(e["pos"]))
            except Exception:                               # noqa: BLE001 - a map error never fires blind
                return False
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
        of sight (no wall shots), not on an own hazard (no mine standing). The range gate follows the proven line:
        ENGAGE_RANGE_LOS_CM (35 m) with the nav/obstacle data, the 12 m blind limit otherwise - the same reach the
        target chooser uses, so a chosen 20 m target is not then held by a 12 m trigger gate (2026-11-11 19:36: the
        operator's "not opening fire hard enough")."""
        reach = ENGAGE_RANGE_CM
        if snap is not None and (snap.get("nav") is not None or snap.get("obstacles") is not None
                                 or self._room_map(snap) is not None):
            reach = ENGAGE_RANGE_LOS_CM
        gate = ("controls" if not CONTROLS_READY else "range" if dist > reach
                else "sight" if not (dist <= FIRE_FIRST_CLOSE_MM or self._line_of_sight_ok(p, e, snap)
                                     or self._sight_given_up(e))
                else "hazard" if self._near_own_hazard(p, snap)
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
        # The candidates reach as far as the shot can be PROVEN: with the nav/obstacle data (or the room map) the
        # clear-line test below is the gate, so a Ganado at 20-35 m is a target, not a walk-up (operator 2026-11-11
        # 19:36: "the bot is not opening fire hard enough on these enemies ... shooting them until they are
        # vanquished"). Without any LOS data the old 12 m blind limit stands.
        reach = ENGAGE_RANGE_CM
        if snap is not None and (snap.get("nav") is not None or snap.get("obstacles") is not None
                                 or self._room_map(snap) is not None):
            reach = ENGAGE_RANGE_LOS_CM
        near = [t for t in live if t[0] <= reach]
        if not near:
            return None
        dropped = self.__dict__.get("_cmd_blocked") or {}  # the operator's repetitive / explore: not that one again yet
        if dropped:
            kept = [t for t in near if dropped.get(t[2].get("ptr"), -1e9) <= now]
            near = kept or near                          # (only him in range: he is still fought, never stood at)
        if p is not None and snap is not None and (snap.get("nav") is not None or snap.get("obstacles") is not None
                                                   or self._room_map(snap) is not None):
            # Inside the close ring the body itself is the target: a Ganado with a shield (or any carried obstacle)
            # is never cover for a shot at arm's length (operator 2026-11-11 20:52: "the bot needs to continue firing
            # on them [with a shield] ... they need to decimate these enemies no matter what they are holding up").
            clear = [t for t in near if t[0] <= FIRE_FIRST_CLOSE_MM or self._line_of_sight_ok(p, t[2], snap)]
            if clear:
                if len(clear) < len(near):
                    self.stats["visible_picks"] += 1
                near = clear
            else:
                self._pick_blocked = True
                self.stats["blocked_picks"] += 1
                self.why = "every Ganado in range is behind a wall: round to the nearest"
                return min(near, key=lambda t: t[0])
        if self.__dict__.get("_cmd") == "score":         # the operator's "score": the quickest kill, as the combo's
            self.why = "the operator's score: the quickest kill"
            return min(near, key=lambda t: ((t[2].get("hp") or 0) * 0.5 + 300.0 * abs(t[1])) * MM_PER_CM + t[0])
        if UNIVERSAL_CORE and p is not None:
            got = self._threat_pick(p, near)             # the scorer's first tiers: a wind-up, then a grudge
            if got is not None:
                return self._keep_pack(p, live, near, got, now, "the grudge")
        crowd = [t for t in near if t[0] <= CROWD_CM]
        if len(crowd) >= CROWD_N:
            lined = [t for t in crowd if abs(t[1]) <= CROWD_CONE]
            if lined:
                self.stats["crowd_picks"] += 1
                self.why = f"crowd fire: {len(crowd)} within {CROWD_CM / 1000:.0f} m, the one on the gun's line"
                return min(lined, key=lambda t: abs(t[1]))
        if self.combo_owed(now) is not None:
            self.why = "the combo is owed: the quickest kill"
            got = min(near, key=lambda t: ((t[2].get("hp") or 0) * 0.5 + 300.0 * abs(t[1])) * MM_PER_CM + t[0])
            return self._keep_pack(p, live, near, got, now, "the combo's pick") if p is not None else got
        self.why = "the nearest Ganado"
        return min(near, key=lambda t: t[0])

    def _keep_pack(self, p, live, near, got, now, kind: str):
        """PACK_KEEP: the pick of the scorer (a grudge) or of the doctrine (the combo's quickest kill) replaces the
        target he is firing at (a shot within PACK_KEEP_S, still in range on a clear line) only within the gun's swing
        (AIM_KEEP_RAD), or when he is hurt (his life fell within PACK_HURT_S) or swarmed (SWARM_N within SWARM_CM);
        otherwise he stays on the pack he is winning against. stats pack_keeps."""
        d = self.__dict__
        hp = p.get("hp")
        if isinstance(hp, (int, float)) and not isinstance(hp, bool):
            last = d.get("_pk_hp")
            if isinstance(last, (int, float)) and hp < last:
                d["_pk_hurt_at"] = now
            d["_pk_hp"] = hp
        cur = next((t for t in near if t[2].get("ptr") == self.target), None) if self.target is not None else None
        if not PACK_KEEP or cur is None or got is cur or abs(got[1]) <= AIM_KEEP_RAD:
            return got
        if now - self._last_fire > PACK_KEEP_S:
            return got                                   # not firing at it now: no pack to stay on
        hurt = now - (d.get("_pk_hurt_at") or -1e9) <= PACK_HURT_S
        swarmed = sum(1 for t in live if t[0] <= SWARM_CM) >= SWARM_N
        if hurt or swarmed:
            return got
        pack = sum(1 for t in near if self._flat(t[2]["pos"], cur[2]["pos"]) <= CROWD_CM)
        self.stats["pack_keeps"] = self.stats.get("pack_keeps", 0) + 1
        self.why = f"on the pack he is firing at ({pack} there): {kind} waits"
        return cur

    # --- the fire pattern (FIRE_PATTERN: gbox.mercs.core.fire_pattern, the tank driver) ---
    def _fp(self):
        d = self.__dict__.get("_fp_driver")
        if d is None:
            d = self._fp_driver = combat.fire_driver(combat_profile(), self.stats)
        return d

    def _fp_aim(self, p, live, dist, err, e, snap, now) -> tuple:
        """(dist, err, enemy, the yaw offset) for this tick's shot: the hop to a neighbour on the gun's line after
        hop_every taps on a REST pick, then the scatter's yaw offset on whoever it is. A pattern error never costs the
        shot: the pick as it was, no offset (fire_pattern_error)."""
        try:
            prof, drv = self._profile(), self._fp()
            fam = prof.family(snap) if prof.family is not None else None
            if combat.fire_spec(prof, fam) is None:
                return dist, err, e, 0.0
            drv.observe(now, snap.get("enemies"), kills=snap.get("kills") if isinstance(snap.get("kills"), int) else None)
            hits = self.__dict__.get("_hit_at")
            drv.fp.effect(max(hits.values(), default=-1e9) if isinstance(hits, dict) else None)
            drv.fp.effect(self.__dict__.get("_kill_at"))
            rest = isinstance(self.why, str) and self.why.startswith(FIRE_HOP_WHYS)
            nb = drv.hop(prof, fam, now, p["pos"], e, [t[2] for t in live], locked=not rest)
            if nb is not None:
                t = next((t for t in live if t[2] is nb and t[0] <= ENGAGE_RANGE_CM), None)
                if t is not None and (snap.get("nav") is None and snap.get("obstacles") is None
                                      or self._line_of_sight_ok(p, nb, snap)):
                    dist, err, e = t
                    self.why = f"fire pattern: the hop to the next one on the gun's line ({dist / 1000:.1f} m)"
            steer, off = drv.aim(prof, fam, e, dist, err, now)
            if dist <= FIRE_CLOSE_MM:
                off = 0.0                                    # the scatter stays off a body inside 3 m
            return dist, err, e, off
        except Exception as exc:                         # noqa: BLE001 - the pattern never costs the shot
            self.stats["fire_pattern_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return dist, err, e, 0.0

    def _fp_fired(self, e, dist, err, snap, now) -> None:
        """A tap went out: the shot's point in the stats (scattered / centred / unearned), the scatter's next point."""
        try:
            prof, drv = self._profile(), self._fp()
            fam = prof.family(snap) if prof.family is not None else None
            if combat.fire_spec(prof, fam) is None:
                return
            drv.aim(prof, fam, e, dist, err, now, shot=True)
            drv.fired(now, e.get("ptr"), fam)
        except Exception as exc:                         # noqa: BLE001
            self.stats["fire_pattern_error"] = f"{type(exc).__name__}: {exc}"[:160]

    def _tap(self, e, dist, err, snap, now) -> dict:
        """The shot: ZR tapped with the aim held (the engine sends a tap as down + up before the hold, so the shot fires
        and the aim key stays down; holding both, the first cut, never released the trigger and a round fired once)."""
        self._last_fire = now
        if FIRE_PATTERN:
            self._fp_fired(e, dist, err, snap, now)
        self._since_reload += 1
        self.stats["shots"] += 1
        n = self.stats["shots"]
        self.stats["fire_err_deg"] = round((self.stats.get("fire_err_deg") or 0.0) * (n - 1) / n
                                         + math.degrees(abs(err)) / n, 2)   # the mean bearing error at a shot
        self.doing = "fire"
        return {"hold": {AIM_BTN}, "tap": FIRE_BTN}

    # --- the aim book and the steady aim (AIM_BOOK, AIM_RAM: gbox.mercs.core.aim_book) ---
    def _aim_core(self):
        c = self.__dict__.get("_aim_book_core")
        if c is None:
            c = self._aim_book_core = aim_book.AimCore(combat_profile(), self.stats, lead_prior_s=AIM_LEAD_PRIOR_S)
        return c

    def _aim_tick(self, snap, now) -> None:
        if AIM_BOOK:
            kills = snap.get("kills")
            self._aim_core().tick(now, snap.get("enemies") or (), kills if isinstance(kills, int) else None)
            st = self.stats                              # the round's two numbers by their plain names, on RE4
            st["hit_rate"], st["aim_err_deg"] = st.get("aimbook_hit_rate"), st.get("aimbook_err_deg")

    def _gun_origin(self, p, snap):
        """The line's origin: the laser's own (RAM) while it is up, else his position GUN_H_MM up (mm)."""
        laser = snap.get("laser")
        if laser is not None and laser.get("up"):
            return tuple(laser["from"]), True
        x, y, z = p["pos"]
        return (x, y + GUN_H_MM, z), False

    def _aim_plan(self, p, e, snap, now, fp_off=0.0):
        origin, _fresh = self._gun_origin(p, snap)
        return self._aim_core().plan(e, origin, aim_family(snap), now), origin

    def _aim_shot(self, p, e, snap, now, plan=None, actual=None, contact=None) -> None:
        """The tap's record (aim_book.Ledger): the plan meant, the laser's line when it is up, else `actual` angles."""
        if not AIM_BOOK:
            return
        try:
            if plan is None:
                plan, _o = self._aim_plan(p, e, snap, now)
            origin, fresh = self._gun_origin(p, snap)
            laser = snap.get("laser") if fresh else None
            gate = self.__dict__.get("_gate")
            los = None if gate == "controls" else gate is None
            extra = {}
            cam = snap.get("camera")
            if cam and plan is not None:                 # the camera's own line (Campos -> Target), for the log
                cy, cp = aim_book.angles(cam["pos"], cam["target"])
                wy, wp = aim_book.angles(cam["pos"], plan.point0)
                extra["cam"] = [round(math.degrees(cy), 2), round(math.degrees(cp), 2),
                                round(math.degrees(wrap(cy - wy)), 2), round(math.degrees(cp - wp), 2)]
            aim = snap.get("aim")
            if aim:
                extra["gun"] = {"pitch": round(aim["pitch"], 4), "waist": round(aim["waist"], 4),
                                "sight": aim.get("sight") == e.get("ptr"), "swayed": any(v > 0 for v in aim["sway"])}
            self._aim_core().shot(now, e, plan, origin=origin, at=laser["at"] if laser else None,
                                  contact=contact, los=los, actual=None if laser else actual, family=aim_family(snap),
                                  extra=extra)
        except Exception as exc:                         # noqa: BLE001 - the book never costs the shot
            self.stats["aimbook_error"] = f"{type(exc).__name__}: {exc}"[:160]

    def _lock_live(self, now) -> bool:
        """Whether the aim lock writes the requests (re4_switch_mods' count, stats mods_aim_writes, rose lately)."""
        n = self.stats.get("mods_aim_writes") or 0
        last = self.__dict__.get("_lock_seen") or (0, -1e9)
        if n > last[0]:
            self._lock_seen = last = (n, now)
        return now - last[1] <= AIM_LOCK_LIVE_S

    def _ram_aim(self, p, live, e, dist, err, fp_off, snap, now) -> dict | None:
        """AIM_RAM: the steady aim (see AIM_PITCH_GAIN). None: the old path aims and fires this tick (no aim read, the
        lock not writing, the core's error)."""
        aim, laser = snap.get("aim"), snap.get("laser")
        if not aim or p.get("ptr") is None or p.get("rot") is None or not self._lock_live(now):
            return None
        try:
            plan, origin = self._aim_plan(p, e, snap, now)
            if plan is None:
                return None
            pt = plan.point
            up = self._aim_since is not None and now - self._aim_since >= AIM_READY_S
            fresh = bool(up and laser is not None and laser.get("up"))
            rot = p.get("rot") or 0.0
            if fresh:
                lp, lc = laser["from"], laser["at"]
                want_y, want_p = aim_book.angles(lp, pt)
                have_y, have_p = aim_book.angles(lp, lc)
                yaw = wrap(rot + wrap(want_y - have_y))
                pitch = aim["pitch"] + AIM_PITCH_GAIN * (want_p - have_p)
                # The aim diagnostic (operator 2026-11-11: "analyze each and every round and adjust the aim ... impeccable
                # aim"): one line per steady request with every angle the request was built from and where the laser
                # actually crosses vs. the point it should. The 55-shot / 4-hit round could not be explained from the
                # counters alone; this says whether rot/have/want are on different references or lc is stale.
                try:
                    _dx = (pt[0] - lc[0], pt[1] - lc[1], pt[2] - lc[2])
                    self.stats["aim_diag"] = (
                        f"rot={math.degrees(rot):+.1f} have_y={math.degrees(have_y):+.1f} "
                        f"want_y={math.degrees(want_y):+.1f} d_yaw={math.degrees(wrap(want_y - have_y)):+.1f} "
                        f"pitch={math.degrees(pitch):+.1f} want_p={math.degrees(want_p):+.1f} "
                        f"have_p={math.degrees(have_p):+.1f} "
                        f"miss_mm={int(math.dist(lc, pt))} d=({int(_dx[0])},{int(_dx[1])},{int(_dx[2])}) "
                        f"deg={int(math.dist(lp, lc) / 1000.0)}m")[:240]
                except Exception:                    # noqa: BLE001 - a diagnostic never costs the aim
                    pass
            else:
                yaw = heading(pt[0] - p["pos"][0], pt[2] - p["pos"][2])
                pitch = math.atan2(pt[1] - origin[1], max(math.hypot(pt[0] - origin[0], pt[2] - origin[2]), 1.0))
            AIM_REQUEST.update(ptr=p["ptr"], yaw=wrap(yaw + fp_off), pitch=pitch, steady=True, wep=aim.get("wep"),
                               at=time.monotonic())
            self.stats["aim_ram"] = "line" if fresh else "rising"
            if not fresh:
                self._ram_since = None
                # The laser has to come up before the steady aim can measure anything - but it may never read at all
                # (live 2026-11-12, Waterworld: laser_gate stat=0 up=False for the whole round, so `fresh` was never
                # true and this branch held AIM_BTN from the first tick to the last: kills 0, aimbook_shots 0,
                # aim_ram_holds 119, why "the steady aim: the gun comes up onto the book's point"). The other stall
                # branch below has a timeout; this one had none. Past AIM_RISE_MAX_S the old gate fires normally.
                rise = self.__dict__.get("_rise_since")
                if rise is None:
                    rise = self.__dict__["_rise_since"] = now
                if now - rise >= AIM_RISE_MAX_S:
                    self.stats["aim_rise_fallbacks"] = self.stats.get("aim_rise_fallbacks", 0) + 1
                    return None                          # no laser to measure: aim and fire the old way
                self.doing, self.why = "aim", "the steady aim: the gun comes up onto the book's point"
                return {"hold": {AIM_BTN}}
            self.__dict__["_rise_since"] = None
            alive = {t[2].get("ptr"): t[2] for t in live if t[2].get("ptr") is not None}
            sight = aim.get("sight")
            on = alive.get(sight)
            if on is None:
                since = self.__dict__.get("_ram_since")
                if since is None:
                    since = self._ram_since = now
                self.stats["aim_ram_holds"] = self.stats.get("aim_ram_holds", 0) + 1
                if now - since >= (AIM_SIGHT_STALL_CLOSE_S if dist <= AIM_SIGHT_CLOSE_MM
                                   else AIM_SIGHT_STALL_S):
                    self.stats["aim_ram_sight_fallbacks"] = self.stats.get("aim_ram_sight_fallbacks", 0) + 1
                    return None                          # the old gate fires: a sight that never reads holds nothing
                self.doing, self.why = "aim", "the steady aim: the line is not on a Ganado yet"
                return {"hold": {AIM_BTN}}
            self._ram_since = None
            if now - self._last_fire < FIRE_GAP_S:
                self.doing = "aim"
                return {"hold": {AIM_BTN}}
            if on is not e:                              # the line names another one: he is the shot
                self.stats["aim_ram_sight_switches"] = self.stats.get("aim_ram_sight_switches", 0) + 1
                dist, err, e = next(t for t in live if t[2] is on)
                self.target = e.get("ptr")
                plan, _o = self._aim_plan(p, e, snap, now)
            self.stats["aim_ram_shots"] = self.stats.get("aim_ram_shots", 0) + 1
            self._aim_shot(p, e, snap, now, plan=plan, contact=True)
            self.why = "the steady aim: the game's sight is on him"
            return self._tap(e, dist, err, snap, now)
        except Exception as exc:                         # noqa: BLE001 - the RAM aim never costs the fight
            self.stats["aim_ram_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return None

    def _bow_in_hand(self, snap) -> bool:
        """The gun in hand is the bow (the fast-fire class family): arrows discharge on the bow's own fast path."""
        try:
            from . import re4_weapons as _w
            return (snap.get("weapon_class") in _w.MOTION_RATE_CLASSES
                    or snap.get("equipped_id") == _w.BOW_ITEM)
        except Exception:                                    # noqa: BLE001 - a read miss keeps the rifle path
            return False

    def _turn(self, err: float) -> set:
        # an error > 0 turns LEFT with TURN_SIGN 1: the GameCube RE4 / RE5 convention (the Switch world is the
        # GameCube's data - re4_switch_nav), the one re4_walk uses; _learn_turn checks it on every turn tick.
        return {TURN["left"] if (err > 0) == (TURN_SIGN > 0) else TURN["right"]}

    def _aim_turn(self, err: float) -> set:
        if UNIVERSAL_CORE:                               # the stick that moves the aim with the gun up (learned live)
            s = self._aim_stick()
            keys = TURN if s.stick == "left" else AIM_TURN
            return {keys["left"] if (err > 0) == (TURN_SIGN * s.sign > 0) else keys["right"]}
        return {AIM_TURN["left"] if (err > 0) == (TURN_SIGN > 0) else AIM_TURN["right"]}

    def _aim_stick(self) -> combat.AimStick:
        s = self.__dict__.get("_uc_aim_stick")
        if s is None:
            s = self._uc_aim_stick = combat.AimStick(self.stats, ("right", "left"), n=AIM_STICK_N)
        return s

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

    # --- the operator's quick commands (CMD_* above) ---
    def _operator_command(self, p, live, snap, now):
        """(command, action now or None): the command in force (the operator's, else the doctrine's), and for the
        operator's own a change of course: explore / next_area / repetitive drop the Ganado he kept at (CMD_DROP_S) and
        run CMD_ROAM_S along open floor (_escape); missing measures the aim stick and the turn sign again; the standing
        modes (fight / hunt / rush / score) go to _choose and _locate through self._cmd. Every one says what it did in
        stats directive_status (the PiP shows it beside the box); a command never presses a key by itself."""
        self._cmd = None
        d = self.__dict__
        roam = self._escaping(p, snap, now, "cmd")       # an operator's new way still under way (next_area: one-shot)
        if self.reader is None:
            return None, self._roaming(roam)
        try:
            cmd, fresh = self.reader.current(self.stats, time.time())
        except Exception as exc:                         # noqa: BLE001 - a command never stops a tick
            self.stats["directive_error"] = f"{type(exc).__name__}: {exc}"[:120]
            return None, self._roaming(roam)
        seq = self.stats.get("directive_seq")
        mine = cmd is not None and cmd == self.stats.get("directive") and seq is not None and (
            seq != d.get("_cmd_seq") or time.time() < float(self.stats.get("directive_until") or 0))
        if not mine:                                     # none, or the doctrine's: the walk to the map's Ganado
            if cmd is None:
                self.stats.pop("directive_active", None)
            return cmd, self._roaming(roam)
        new = seq != d.get("_cmd_seq")
        d["_cmd_seq"] = seq
        self.stats["directive_active"] = cmd
        self._cmd = cmd
        if new:
            self.stats["directive_status"] = "acting: " + cmd + CMD_SAYS.get(cmd, "")
            self.stats["directive_taken"] = self.stats.get("directive_taken", 0) + 1
            if cmd in ("explore", "next_area", "repetitive"):
                blocked = d.setdefault("_cmd_blocked", {})
                if self.target is not None:
                    blocked[self.target] = now + CMD_DROP_S
                self.target = None
                d.pop("_flank", None)
                d.pop("_run_cmd", None)
                self._sweep_at = None
                roam = self._escape(p, live, snap, now, "cmd", CMD_ROAM_S)
                d["_roam_why"] = cmd
            elif cmd == "missing":
                d.pop("_uc_aim_stick", None)             # the aim's stick and the turn sign, measured again
                d.pop("_turn_tally", None)
        return cmd, self._roaming(roam)

    def _roaming(self, act):
        """The operator's new way (an escape run of kind "cmd") as this tick's action, said; None when there is none."""
        if act is not None:
            self.doing, self.why = "walk", (f"the operator's {self.__dict__.get('_roam_why') or 'command'}: off this "
                                            "spot along open floor, another way")
        return act

    # --- the tick ---
    def tick(self, snap: dict, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        game = snap.get("game")
        if isinstance(game, dict) and not game.get("in_control"):
            act = self._not_in_control(game, now)       # never a shot, never "fire", at a screen that takes no aim
            self.stats["doing"], self.stats["why"] = self.doing, self.why
            return act
        p = snap.get("player")
        if not p or p.get("pos") is None:
            self.doing, self.why = "idle", "no player in RAM"
            return {}
        self._count_kills(snap, now)
        self._aim_tick(snap, now)                     # the aim book: the open shots resolved by the census (AIM_BOOK)
        if UNIVERSAL_CORE:
            self._core_tick(p, snap, now)             # the profile of this tick, who hurt him (combat.Threats)
            self._pose_tick(p, now)                   # moved or turned since the last tick: in control (AimStick)
        if snap.get("kill_candidates"):                # the probe's counters beside the census (KILL_CANDIDATES)
            self.stats["kill_candidates"] = " ".join(f"{k}={v}" for k, v in snap["kill_candidates"].items())
        owed = self.combo_owed(now)
        self.stats["combo_owed_s"] = round(owed, 1) if owed is not None else None
        frozen = self._frozen(p, now, ram_state=isinstance(game, dict))
        if frozen is not None:
            self.stats["doing"], self.stats["why"] = self.doing, self.why
            return frozen
        fight = self._fight(p, snap, now)
        fight_up = AIM_BTN in set(fight.get("hold") or ())
        act = self._respond(p, snap, fight, now)        # under threat: fire at it (no flash, no mines here) - never nothing
        act = self._never_stand(p, act, snap, now)
        if UNIVERSAL_CORE:
            act = self._idle_core(p, act, snap, now)   # the gun up at one in range without a shot: round him
            act = self._wall_core(p, act, snap, now)   # never walking into a wall (pressed: away to open floor)
        if FIRE_FIRST and fight_up and AIM_BTN not in set(act.get("hold") or ()) and self._fire_first(p, snap, now):
            self.stats["gun_kept"] = self.stats.get("gun_kept", 0) + 1
            act = fight                                 # fire first: not lowered for a step, a flank or a wall
        up = AIM_BTN in set(act.get("hold") or ())
        self._gun_down_telemetry(up, now)
        self._aim_since = (self._aim_since if self._aim_since is not None else now) if up else None
        if self.director is not None:
            try:
                from ..core import doctrine
                self.director.observe(doctrine.view(snap, RE4Switch), act, time.time())
            except Exception:                            # noqa: BLE001 - measuring never costs the tick
                pass
        r = self.__dict__.get("_resp")
        if r is not None:
            try:
                r.settle(act, self.doing)                # what he finally did, counted (threat_* / hurt_while_idle)
            except Exception as exc:                     # noqa: BLE001
                self.stats["threat_error"] = f"{type(exc).__name__}: {exc}"[:160]
        self.stats["doing"], self.stats["why"] = self.doing, self.why
        return act

    def _respond(self, p, snap, act, now) -> dict:
        """core.respond (RESPOND above) on this tick's decision: the fight on the threats when it answered nothing."""
        if not RESPOND or not UNIVERSAL_CORE or (p.get("hp") or 0) <= 0:
            return act
        try:
            r = self.__dict__.get("_resp")
            if r is None:
                r = self._resp = respond.Responder(self.stats)

            def fire(e, pool):
                self._doctrine_fire = e.get("ptr")
                try:
                    return self._fight(p, dict(snap, enemies=pool), now)
                finally:
                    self._doctrine_fire = None
            kit = respond.Kit(fire=fire, flash=None, mine=None, clear=lambda e: self._line_of_sight_ok(p, e, snap),
                              busy=RESPOND_BUSY, attack=RESPOND_ATTACK, aim=RESPOND_AIM)
            prof = self._profile()
            return r.respond(prof, now, p, snap.get("enemies") or (), act, kit, self.doing,
                             respond.Memory(self._uc("threats"), prof))
        except Exception as exc:                         # noqa: BLE001 - the doctrine never costs the tick
            self.stats["threat_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return act

    def _fight(self, p, snap, now) -> dict:
        # Step off an own hazard first (no mine standing), even before facing the target.
        live = self._live(p, snap.get("enemies") or [])
        seen = self._remember(live, now)                 # where they were, for when none are in the snapshot
        self._gate = None                                # (this tick's fire gate: _may_fire sets it when it runs)
        if self._near_own_hazard(p, snap):
            self.stats["backoffs"] += 1
            self.doing, self.why = "backoff", "standing near his own explosive"
            near = min(live, key=lambda t: t[0]) if live else None
            return {"hold": {"lup", TURN["right" if near and near[1] > 0 else "left"]}}
        heal = self._heal(p, snap, now)                  # hurt: the spray, without the item screen
        if heal is not None:
            return heal
        hit = self._hit_backoff(p, live, snap, now)      # a landed blow: break contact before the next one
        if hit is not None:
            return hit
        if UNIVERSAL_CORE:
            act = self._throw_core(p, live, snap, now) if not self._fire_first(p, snap, now) else None
            if act is not None:                              # a grenade at the pack (THROWS): never with one on him
                return act
        doctrine = self.__dict__.get("_doctrine_fire") is not None   # core.respond: he fires at the threat, no run-off
        fire_first = self._fire_first(p, snap, now)
        low = None if doctrine else self._low_life(p, live, now, snap)   # (the doctrine's own answer is the live one)
        if low is not None:
            return low
        heavy = None if (doctrine or fire_first) else self._heavy_keep(live, now, p, snap)
        if heavy is not None:
            return heavy
        if UNIVERSAL_CORE:
            act = self._lethal_out(p, live, snap, now)    # a learned attack his shots do not stop: out of its reach
            if act is not None:
                return act
        act = None if (doctrine or fire_first) else self._escaping(p, snap, now, "swarm")
        if act is not None:
            return act
        swarm = [t for t in live if t[0] <= SWARM_CM]
        if len(swarm) >= SWARM_N and not doctrine and not fire_first:
            act = self._escape(p, live, snap, now, "swarm", LOW_LIFE_RUN_S)
            if act is not None:
                self.stats["escapes"] += 1
                self.doing, self.why = "escape", f"{len(swarm)} Ganados at arm's length: away along open floor"
                return act
        melee = self._melee(live, now)
        if melee is not None:
            return melee
        cmd, roam = self._operator_command(p, live, snap, now)
        if roam is not None and not doctrine:
            return roam                                  # the operator's new way: off this spot first (a threat's
                                                         # answer, core.respond, still fires)
        pick = self._choose(live, now, p, snap)          # a command never stops a shot at one in range (RE5 HUNT_R)
        if pick is not None:
            dist, err, e = pick
            # Too far to put a shot on him, so RUN at him: _run_to is the escape run's own mesh path (the quick turn
            # when he lies behind, then the walker with B), so this is traversal of the stage rather than standing in
            # the open trading shots the pad cannot land (see HUNT_RUN_MM).
            # NEVER at a heavy. A heavy (hp_max >= HEAVY_HP: the chainsaw Ganados, the Garrador, the Gatling man) kills
            # from full life in one blow, and the rule for one is that it is "shot from beyond" HEAVY_KEEP_MM - running
            # at it would carry him inside the range fire_first then answers the gun from, which is how he died on Base
            # (hp 1860 -> 0 in two hits). A heavy past HUNT_RUN_MM falls through and is shot from here instead.
            # ...BUT a BOSS is the exception, and it is the opposite rule (the operator, 2026-11-12: "if they see a
            # boss, they need to basically destroy them on sight ... any boss characters that show up ... the bot needs
            # to deal with them ASAP, they cannot be allowed to exist and remain"). A boss can end the round outright,
            # so it is CLOSED ON and killed rather than shot at from a range the pad cannot land - doctrine.BOSS_HP_MIN
            # is the same 3000 the shared boss rule uses ("dispatch bosses on sight").
            boss = bool(e.get("boss")) or (e.get("hp_max") or 0) >= BOSS_HP_MIN
            if dist > HUNT_RUN_MM and (boss or (e.get("hp_max") or 0) < HEAVY_HP):
                self.target = e.get("ptr")
                self.stats["hunts"] = self.stats.get("hunts", 0) + 1
                self.doing, self.why = "hunt", f"{dist / (100.0 * MM_PER_CM):.0f} m off: running at him"
                return self._run_to(p, tuple(e["pos"]), snap)
            fp_off = 0.0                                 # the fire pattern's yaw offset across his body (FIRE_PATTERN)
            if FIRE_PATTERN and not self.__dict__.get("_pick_blocked"):
                dist, err, e, fp_off = self._fp_aim(p, live, dist, err, e, snap, now)
            self.target = e.get("ptr")
            if p.get("ptr") is not None and p.get("rot") is not None:
                AIM_REQUEST.update(ptr=p["ptr"], yaw=wrap((p.get("rot") or 0.0) + err + fp_off), at=time.monotonic(),
                                   pitch=None, steady=False)    # (the steady aim's own, _ram_aim, once the gun is up)
            if self.__dict__.get("_pick_blocked"):
                fl = self.__dict__.get("_flank")
                if not fl or fl["key"] != self.target or now >= fl["until"]:
                    self.stats["flanks"] = self.stats.get("flanks", 0) + 1     # no clear line to anyone: go round
                    self._log_block(p, e, snap)
                self._flank = {"key": self.target, "until": now + FLANK_S}
            fl = self.__dict__.get("_flank")
            if fl and fl["key"] == self.target and now < fl["until"]:
                act = self._flank_step(p, e, err, snap, now)
                if act is not None:
                    return act                           # (None: the shot is open from here - the gun up, below)
            cone = RAISE_TOL
            if UNIVERSAL_CORE and self._aim_since is not None and self._aim_stick().usable():
                keep = AIM_KEEP_CLOSE_RAD if (FIRE_FIRST and fire_first) else AIM_KEEP_RAD
                cone = max(RAISE_TOL, keep)              # the gun up: the aim stick turns him, the gun stays up
            # The shot's tolerance is the angle the body covers at THIS distance (atan2(half, dist)) - 16.7 deg for a
            # Ganado at 1 m, 2.9 deg at 6 m. The turn gate used the flat 2.9 deg minimum at every range, so at
            # point-blank it demanded precision the shot does not need and turned instead of firing: live 2026-11-12
            # the operator's own frame showed the bot pressed into a Ganado at 01'56" with 0 kills and doing=turn.
            # Both gates now share the one distance-aware tolerance, so a body at arm's length is shot at once.
            half = FIRE_HALF_WIDTH_MM
            if UNIVERSAL_CORE:                           # the body profile: his class's own half width (mm)
                try:
                    half = self._profile().body_units(e).r
                except Exception as exc:                 # noqa: BLE001 - the core never costs the shot
                    self._core_error(exc)
            tol = max(FIRE_TOL_MIN, min(self.TURN_TOL, math.atan2(half, max(dist, 1.0))))
            # Well off the gun (> RAISE_TOL) he turns on the spot with the gun DOWN - the walk turn. Everything closer
            # falls through to the aim block below, which holds AIM_BTN and picks a NUDGE (a tap of the right stick)
            # or a sweep by how close the error is. The gate used to skip that choice entirely: live 2026-11-12 it
            # returned the walk turn at every error, so while aiming nothing moved the aim - turns=3366 in one round
            # (every tick), doing=turn, gun_down_turn climbing: the operator's "just turning back and forth and not
            # going forward".
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
            if AIM_RAM:                                      # the steady aim through the gun's own line (AIM_RAM)
                act = self._ram_aim(p, live, e, dist, err, fp_off, snap, now)
                if act is not None:
                    return act
            if abs(err) > tol:                               # (tol: the body's angle at this distance, above)
                self.stats["raises"] += 1
                self.doing = "aim"
                aim_err = err + fp_off                       # toward this shot's point on him (0 offset: his bearing)
                if abs(err) <= AIM_NUDGE:                    # close: a tap of the right stick, not a sweep past him
                    if UNIVERSAL_CORE:
                        self._aim_stick().rest()
                    return {"hold": {AIM_BTN}, "tap": next(iter(self._aim_turn(aim_err)))}
                if UNIVERSAL_CORE and self._aim_since is not None:
                    self._aim_stick().observe(now, p.get("rot"), 1 if aim_err > 0 else -1)   # does this stick move it?
                return {"hold": {AIM_BTN} | self._aim_turn(aim_err)}   # the gun up, the right stick turns the aim
            # The bow fires on its own fast path (the operator 2026-11-11 21:32: "the bot was raising their bow and
            # arrow ... but because they weren't discharging arrows, the threats ... choked them to death"; 21:33:
            # "If the bot isn't rapid firing on these threats, then they will be destroyed"): the bow needs no rifle
            # raise wait and no 0.25 s trigger gap - the arrow discharges as soon as the raise settles.
            bow = self._bow_in_hand(snap)
            ready = bow or (self._aim_since is not None and now - self._aim_since >= AIM_READY_S)
            if not ready or now - self._last_fire < (BOW_FIRE_GAP_S if bow else FIRE_GAP_S):
                self.doing = "aim"
                return {"hold": {AIM_BTN}}
            if AIM_BOOK:                                     # the shot's record: his facing (+ the waist) as the line
                aim = snap.get("aim") or {}
                self._aim_shot(p, e, snap, now, plan=None, actual=(wrap((p.get("rot") or 0.0) + (aim.get("waist") or 0.0)),
                                                                   None))
            if bow:
                # The bow's own counters, under the names the run reviewer already expects (round_reports' aim group:
                # bow_firing_observations, bow_aim_error_deg - null because nothing computed them). Ten
                # Krauser/Waterworld reports read round_threat_forced_fire 41-200 with hits 0-4 and none could say
                # whether an arrow left the bow at all. bow_gap_s is the trigger gap actually in force, so 0.0025 (the
                # operator's 20x) is confirmed from the round instead of inferred.
                self.stats["bow_firing_observations"] = self.stats.get("bow_firing_observations", 0) + 1
                self.stats["bow_gap_s"] = BOW_FIRE_GAP_S
                self.stats["bow_aim_error_deg"] = round(math.degrees(abs(err)), 2)
            return self._tap(e, dist, err, snap, now)
        self.target = None
        if self._since_reload >= RELOAD_SHOTS and not any(t[0] <= RELOAD_CLEAR_CM for t in live):
            # a quiet moment after a magazine's worth of shots: ZL + B (the aim first, then B, in this one batch:
            # re4switch_bot.Keys sends the holds before the tap)
            self._since_reload = 0
            self.stats["reloads"] += 1
            self.doing, self.why = "reload", f"{RELOAD_SHOTS} shots since the last reload and nobody near"
            return {"hold": {AIM_BTN}, "tap": RELOAD_BTN}
        return self._locate(p, live, now, cmd, snap)

    def _escape_goal(self, p, live, snap):
        """A point ESCAPE_MM away from the Ganados near him along open floor (see ESCAPE_*), or None when every line
        is walled. Without a stage mesh: straight away."""
        px, py, pz = p["pos"]
        vx = vz = 0.0
        for d, _err, e in live:
            if d > ESCAPE_FROM_MM:
                continue
            dx, dz = px - e["pos"][0], pz - e["pos"][2]
            dd = max(math.hypot(dx, dz), 300.0)
            vx, vz = vx + dx / (dd * dd), vz + dz / (dd * dd)
        away = heading(vx, vz) if (vx or vz) else wrap((p.get("rot") or 0.0) + math.pi)
        seg = self._walk_test(snap)                      # the shot line's walls, and the room map's (ROOM_MAP)
        for deg in ESCAPE_TRIES_DEG:
            h = away + math.radians(deg)
            goal = (px + ESCAPE_MM * math.sin(h), py, pz + ESCAPE_MM * math.cos(h))
            if any(self._flat(goal, e["pos"]) < ESCAPE_CLEAR_MM for _d, _e, e in live):
                continue                                 # running into another one
            if callable(seg):
                try:
                    if not seg(tuple(p["pos"]), goal):
                        self.stats["escape_lines_walled"] = self.stats.get("escape_lines_walled", 0) + 1
                        continue                         # a wall, a drop or a fence that way
                except Exception:                        # noqa: BLE001 - a mesh error: that line is not trusted
                    continue
            return goal
        ladder = self._ladder_escape_goal(p, live, snap)
        if ladder is not None:
            self.stats["escape_ladders"] = self.stats.get("escape_ladders", 0) + 1
            return ladder
        self.stats["escapes_walled_in"] = self.stats.get("escapes_walled_in", 0) + 1
        return None

    def _ladder_escape_goal(self, p, live, snap):
        """The landing of the nearest ladder DOWN he can reach before the Ganados near him, or None (no mesh, no
        ladder, none within LADDER_ESCAPE_MM, or a Ganado nearer its approach than he is)."""
        rows = getattr(snap.get("nav"), "crossing_rows", None)
        if not isinstance(rows, dict):
            return None
        pos = p["pos"]
        best, gap = None, LADDER_ESCAPE_MM
        for row in rows.values():
            try:
                if row.get("kind") != "ladder" or row.get("direction") != "down":
                    continue
                ap, land = row["approach"], row["landing"]
                if abs(float(ap[1]) - float(pos[1])) > 1500.0:
                    continue                                 # not on his floor
                d = self._flat(pos, ap)
                if d >= gap or any(self._flat(e["pos"], ap) < d + LADDER_FOE_MARGIN_MM for _d, _e, e in live):
                    continue
                best, gap = (float(land[0]), float(land[1]), float(land[2])), d
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        return best

    def _run_to(self, p, goal, snap) -> dict:
        """The run to an escape goal: the quick turn when it lies behind him, else _approach (the mesh walker) with B."""
        err = wrap(heading(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) - (p.get("rot") or 0.0))
        if abs(err) > ESCAPE_QUICK_RAD:
            return {"hold": set(QUICK_TURN)}
        keys, _how = self._approach(p, goal, err, snap, run=True)
        return {"hold": set(keys) | {"lup", RUN_BTN}}

    def _escape(self, p, live, snap, now, kind: str, secs: float) -> dict | None:
        """An escape of this kind under way (its goal, until when), or a new one; None when walled in or arrived."""
        run = self.__dict__.get("_run_" + kind)
        if run and now < run["until"] and self._flat(p["pos"], run["goal"]) > ESCAPE_ARRIVED_MM:
            return self._run_to(p, run["goal"], snap)
        goal = self._escape_goal(p, live, snap)
        if goal is None:
            self.__dict__.pop("_run_" + kind, None)
            return None
        self.__dict__["_run_" + kind] = {"until": now + secs, "goal": goal}
        return self._run_to(p, goal, snap)

    def _escaping(self, p, snap, now, kind: str) -> dict | None:
        """The run of this kind still under way (before its until, not arrived), else None."""
        run = self.__dict__.get("_run_" + kind)
        if run and now < run["until"] and self._flat(p["pos"], run["goal"]) > ESCAPE_ARRIVED_MM:
            return self._run_to(p, run["goal"], snap)
        return None

    def _hit_backoff(self, p, live, snap, now) -> dict | None:
        """Hit: break contact for HIT_BACKOFF_S instead of trading another blow (the operator's choice, 2026-11-12).

        His fire-first rule stays - the gun answers a threat on him - and only a landed blow breaks it, because a heavy
        kills from full life in one blow (1560 -> 0) and a second one must not land. None when he has not been hit, or
        the backoff has run, or he is walled in (then he fights it).
        """
        hp = p.get("hp")
        last = self.__dict__.get("_hp_seen")
        self.__dict__["_hp_seen"] = hp
        if isinstance(hp, int) and isinstance(last, int) and hp < last:
            self.__dict__["_hurt_at"] = now
        at = self.__dict__.get("_hurt_at")
        if at is None or now - at > HIT_BACKOFF_S or now < self.__dict__.get("_backoff_block_until", -1e9):
            return None                                  # (no chaining: see HIT_BACKOFF_GAP_S)
        if p is None:
            return None
        near = min((t[0] for t in live), default=None)
        if near is None or near > HIT_BACKOFF_RANGE_MM:
            return None                                  # a hit from across the stage: answer it, do not turn away
        act = self._escape(p, live, snap, now, "hit", HIT_BACKOFF_S)
        if act is None:
            return None                                  # walled in: he fights it
        self.__dict__["_backoff_block_until"] = now + HIT_BACKOFF_GAP_S
        self.doing, self.why = "backoff", f"hit {now - at:.1f} s ago: breaking contact, then back to him"
        self.stats["hit_backoffs"] = self.stats.get("hit_backoffs", 0) + 1
        return act

    def _heal(self, p, snap, now) -> dict | None:
        """Hurt: the first aid spray into his hand, used, and the gun back - all through HAND_REQUEST, a flag write the
        mods answer, so the item screen is never opened (the operator, 2026-11-12; see HEAL_ITEM). Phases: hand (wait
        for HAND_STATE to confirm the spray), use (tap it), settle, back (the gun again). Any failure aborts to the gun
        with the reason in stats rather than standing there holding a spray."""
        hp, top = p.get("hp"), p.get("hp_max")
        if not HEAL_ON:
            return None                                  # (see HEAL_ON: the swap froze a live round)
        if not isinstance(hp, int) or not isinstance(top, int) or top <= 0:
            return None                                  # no life reading: never guess at a heal
        st = self.__dict__.get("_heal_state")
        if st is None:
            if hp > top * HEAL_BELOW or now < self.__dict__.get("_heal_block_until", -1e9):
                return None                              # (a failed swap blocks the retry, so the fight goes on)
            st = self.__dict__["_heal_state"] = {"phase": "hand", "since": now, "seq": self._hand_ask(HEAL_ITEM)}
        if st["phase"] == "hand":
            if HAND_STATE.get("seq") == st["seq"] and HAND_STATE.get("verified") \
                    and HAND_STATE.get("item") == HEAL_ITEM:
                st.update(phase="use", since=now)
            elif now - st["since"] > HEAL_HAND_S:
                self.stats["heal_aborts"] = self.stats.get("heal_aborts", 0) + 1
                self.stats["heal_abort_last"] = f"the swap: {HAND_STATE.get('error') or 'no answer'}"[:120]
                self.__dict__["_heal_block_until"] = now + HEAL_BLOCK_S
                st.update(phase="back", since=now, seq=self._hand_ask(None))
            else:
                self.doing, self.why = "heal", f"the first aid spray to hand ({hp} of {top})"
                return {"hold": set()}
        if st["phase"] == "use":
            if now - st["since"] < HEAL_USE_S:
                self.doing, self.why = "heal", f"the spray up ({hp} of {top})"
                return {"hold": set()}
            st.update(phase="settle", since=now)
            self.stats["heals"] = self.stats.get("heals", 0) + 1
            self.doing, self.why = "heal", f"the first aid spray used ({hp} of {top})"
            return {"tap": ACTION_BTN}
        if st["phase"] == "settle":
            if now - st["since"] < HEAL_SETTLE_S:
                self.doing, self.why = "heal", "the spray's settle"
                return {"hold": set()}
            st.update(phase="back", since=now, seq=self._hand_ask(None))
        if st["phase"] == "back":
            self.doing, self.why = "heal", "the gun back after the spray"
            if HAND_STATE.get("seq") == st["seq"] or now - st["since"] > HEAL_HAND_S:
                self.__dict__["_heal_state"] = None
            return {"hold": set()}
        return None

    def _heavy_keep(self, live, now, p=None, snap=None) -> dict | None:
        """HEAVY_*: a heavy within HEAVY_KEEP_MM - away along open floor (_escape), HEAVY_RUN_S at a time."""
        snap = snap or {}
        if p is not None:
            act = self._escaping(p, snap, now, "heavy")
            if act is not None:
                return act
        near = [t for t in live if t[0] <= HEAVY_KEEP_MM and (t[2].get("hp_max") or 0) >= HEAVY_HP]
        if not near:
            return None
        d, err, e = min(near, key=lambda t: t[0])
        act = self._escape(p, live, snap, now, "heavy", HEAVY_RUN_S) if p is not None else \
            ({"hold": set(QUICK_TURN)} if abs(err) < 1.6 else {"hold": {"lup", RUN_BTN}})
        if act is None:
            return None                                  # walled in: he fights it
        self.stats["heavy_escapes"] = self.stats.get("heavy_escapes", 0) + 1
        self.doing, self.why = "evade", f"a heavy ({e.get('hp_max')} health) {d / 1000:.1f} m off: away, then shoot"
        return act

    def _low_life(self, p, live, now, snap=None) -> dict | None:
        """LOW_LIFE: away from the Ganados along open floor (_escape), LOW_LIFE_RUN_S at a time."""
        snap = snap or {}
        hp, top = p.get("hp"), p.get("hp_max")
        act = self._escaping(p, snap, now, "low")
        if act is not None:
            return act
        if not isinstance(hp, int) or not isinstance(top, int) or top <= 0 or hp <= 0 or hp > top * LOW_LIFE:
            return None
        near = [t for t in live if t[0] <= LOW_LIFE_MM]
        if not near:
            return None
        act = self._escape(p, live, snap, now, "low", LOW_LIFE_RUN_S)
        if act is None:
            return None                                  # walled in on every line: he fights
        self.stats["low_life_runs"] = self.stats.get("low_life_runs", 0) + 1
        self.doing, self.why = "retreat", f"life {hp}/{top}: away from {len(near)} near, along open floor"
        return act

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

    # Not in control, read from the game's own state (snap["game"], game_state): what each phase presses, how often
    NOT_IN_CONTROL_KEYS = {"intro": ("a", 0.5), "grabbed": ("a", 0.12), "held": ("a", 0.6), "case": ("b", 1.0),
                           "dead": ("a", 1.5), "results": ("a", 1.0)}

    def _not_in_control(self, game: dict, now: float) -> dict:
        """The round's screen when the game says he is not in control (game_state): the intro card and a hold are paged
        with A, a grab is mashed with A, the open case closed with B, the death screen's Continue (its cursor opens on
        Yes, as the walk answers it) and the results paged with A; no round running gets nothing (the walk reads the
        menus from the frame). Never a shot: the trigger and the aim are let go, the aim lock's request is withdrawn."""
        phase = game.get("phase") or "none"
        self.target = None
        self._aim_since = None
        AIM_REQUEST.clear()
        self.doing = {"none": "wait", "dead": "dead"}.get(phase, phase)
        self.why = PHASE_WHY.get(phase, phase)
        if phase == "intro" and game.get("intro_step") not in (None, 1):
            self.why = ("the intro is closing: the round starts" if game.get("intro_step") == 2 else
                        "the round's intro (the camera): waiting for its card")
        self.stats["not_in_control_ticks"] = self.stats.get("not_in_control_ticks", 0) + 1
        key, every = self.NOT_IN_CONTROL_KEYS.get(phase, (None, 0.0))
        if phase == "intro" and game.get("intro_step") not in (None, 1):
            key = None                                   # the camera move: A only once the card is up
        if key is None:
            return {"hold": set()}
        last = self.__dict__.setdefault("_nic_tap", {})
        if now - last.get(phase, -1e9) < every:
            return {"hold": set()}
        last[phase] = now
        self.stats[phase + "_taps"] = self.stats.get(phase + "_taps", 0) + 1
        return {"hold": set(), "tap": key}

    def _frozen(self, p, now, ram_state: bool = False) -> dict | None:
        """A tap of FROZEN_KEY while he is not in control (FROZEN_*), else None: through the shared detector
        (combat.NotInControl) with UNIVERSAL_CORE, else the first version (_frozen_legacy). With the game's own state
        read (ram_state: tick() has already handled every phase that is not in control) the shared detector and the
        firing rule stay off: they were the stopgap for a fight that could not see the intro card."""
        if UNIVERSAL_CORE and not ram_state:
            if not FROZEN:
                return None
            try:
                stepped = (self.__dict__.get("_fz") or {}).get("stepped")
                hits = self.__dict__.get("_hit_at")
                last_hit = max(hits.values(), default=-1e9) if isinstance(hits, dict) else -1e9
                page = self._uc("nic").check(self._profile(), now, p["pos"], p.get("rot"),
                                             shots=self.stats.get("shots", 0) or 0, last_hit_at=last_hit,
                                             stepped_at=stepped)
            except Exception as exc:                     # noqa: BLE001 - the core never costs the tick
                self._core_error(exc)
                return self._frozen_legacy(p, now, ram_state)
            if page is None:
                return None
            self.doing, self.why = "frozen", f"not in control ({page.cause}: an intro, a death camera or a grab): A"
            return {"hold": set(), "tap": page.tap} if page.tap else {"hold": set()}
        return self._frozen_legacy(p, now, ram_state)

    def _frozen_legacy(self, p, now, ram_state: bool = False) -> dict | None:
        """_frozen before the universal core (UNIVERSAL_CORE off, or the game's own state read)."""
        fz = self.__dict__.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})
        pos, rot = tuple(p["pos"]), p.get("rot")
        moved = (fz["pos"] is None or self._flat(fz["pos"], pos) > FROZEN_MM
                 or (rot is not None and fz["rot"] is not None and abs(wrap(rot - fz["rot"])) > FROZEN_RAD))
        shots = self.stats.get("shots", 0) or 0
        if moved:
            fz.update(pos=pos, rot=rot, at=now, on=False, shots0=shots)
            return None
        stepped = fz.get("stepped")
        # Firing into a screen that takes no input (live 2026-11-10 03:52, Krauser on Waterworld's intro card "Eliminate
        # as many Ganados as you can": 620 shots, 0 hits, "crowd fire" for minutes): aiming and firing never step, so
        # the step rule above never armed. FROZEN_FIRE_SHOTS shots over FROZEN_FIRE_S without moving and without one
        # hit since he last moved is not a fight either.
        last_hit = max(self._hit_at.values(), default=-1e9) if isinstance(getattr(self, "_hit_at", None), dict) else -1e9
        fire_stuck = (FROZEN and not ram_state and now - fz.get("at", now) >= FROZEN_FIRE_S
                      and last_hit < fz.get("at", -1e9)
                      and shots - fz.get("shots0", shots) >= FROZEN_FIRE_SHOTS)
        if not FROZEN or not fire_stuck and (stepped is None or stepped < fz.get("at", -1e9)
                                             or now - stepped < STAND_STEP_S):
            return None                                  # no step tried since he last moved, or it is still running
        if fire_stuck and not fz["on"]:
            self.stats["frozen_fire_spells"] = self.stats.get("frozen_fire_spells", 0) + 1
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
        spent = self.__dict__.setdefault("_flank_spent", {})
        spent[key] = spent.get(key, 0.0) + FLANK_S      # (the give-up budget, FLANK_GIVE_UP_S)
        return self._flank_step(p, e, err, snap, now)

    def _sight_given_up(self, e) -> bool:
        """FLANK_GIVE_UP_S: this target has had a flank budget's worth of walking - the sight gate no longer blocks it."""
        spent = self.__dict__.get("_flank_spent") or {}
        if spent.get(e.get("ptr"), 0.0) < FLANK_GIVE_UP_S:
            return False
        self.stats["sight_given_up"] = self.stats.get("sight_given_up", 0) + 1
        return True

    def _flank_step(self, p, e, err, snap, now) -> dict | None:
        """One tick of a flank (no clear shot at e). FLANK_LOS: over as soon as the shot is open from where he stands
        (None: the fight raises the gun), else toward the nearest point along the mesh's route to e from which it is
        (_flank_goal) - he stops there and fires, he does not walk the route to e. Off: toward e himself."""
        if FLANK_LOS and self._line_of_sight_ok(p, e, snap):
            self._flank = None
            self.stats["flank_los_opens"] = self.stats.get("flank_los_opens", 0) + 1
            return None
        goal = self._flank_goal(p, e, snap, now) if FLANK_LOS else tuple(e["pos"])
        if goal is not None and goal != tuple(e["pos"]):
            gerr = wrap(heading(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) - (p.get("rot") or 0.0))
            # Operator 2026-11-11 19:36: "the bot needs to always be running around the level full speed in order to
            # get around and to basically put space between him and the threats behind him" - a flank ran at the walk
            # speed (run=False) while the Ganado closed; the flank is a run now.
            keys, how = self._approach(p, goal, gerr, snap, run=True)
            self.stats["flank_los_goals"] = self.stats.get("flank_los_goals", 0) + 1
            self.doing, self.why = "flank", (f"no clear shot: to the spot {self._flat(p['pos'], goal) / 1000:.1f} m on "
                                             f"where it opens, by {how}")
            return {"hold": keys}
        keys, how = self._approach(p, e["pos"], err, snap, run=True)
        self.doing, self.why = "flank", f"no clear shot: round it by {how}"
        return {"hold": keys}

    def _flank_goal(self, p, e, snap, now):
        """The nearest point along the mesh's route from him to e (FLANK_SAMPLE_MM apart, FLANK_LOOK_MM at most, to
        the route's first crossing) from which the shot to e is clear (_line_of_sight_ok), kept FLANK_GOAL_S for the
        same e; e's own position when none is (or no route). Within FLANK_ARRIVE_MM of it already: e's position."""
        key = (e.get("ptr"), round(e["pos"][0] / 500.0), round(e["pos"][2] / 500.0))
        c = self.__dict__.get("_flank_goal_c")
        if not (c and c["key"] == key and now - c["at"] < FLANK_GOAL_S):
            goal = tuple(e["pos"])
            route = getattr(snap.get("nav"), "route", None)
            try:
                pts = route(tuple(p["pos"]), tuple(e["pos"]), clearance=re4_walk.CLEARANCE_MM) if callable(route) else None
            except Exception:                            # noqa: BLE001 - a mesh error: straight at him
                pts = None
            poly = [tuple(p["pos"])]
            for q in pts or ():
                if hasattr(q, "approach"):
                    poly.append(tuple(q.approach))       # (a crossing: the samples stop at its foot)
                    break
                if isinstance(q, (tuple, list)) and len(q) >= 3:
                    poly.append(tuple(q[:3]))
            walked, found = 0.0, None
            for a, b in zip(poly, poly[1:]):
                L = self._flat(a, b)
                n = max(1, int(math.ceil(L / FLANK_SAMPLE_MM)))
                for i in range(1, n + 1):
                    walked += L / n
                    q = tuple(a[k] + (b[k] - a[k]) * i / n for k in range(3))
                    if walked > FLANK_LOOK_MM:
                        break
                    if self._line_of_sight_ok({"pos": q}, e, snap):
                        found = q
                        break
                if found is not None or walked > FLANK_LOOK_MM:
                    break
            goal = found or goal
            self._flank_goal_c = c = {"key": key, "at": now, "goal": goal}
        goal = c["goal"]
        if goal != tuple(e["pos"]) and self._flat(p["pos"], goal) <= FLANK_ARRIVE_MM:
            return tuple(e["pos"])                       # at the spot and still no shot (he moved): on toward him
        return goal

    def _log_block(self, p, e, snap) -> None:
        """One sight block: the stats' last one and a line in SIGHT_LOG (the wall, where the shot met it)."""
        nav = snap.get("nav")
        hit = None
        try:
            bw = getattr(nav, "blocking_wall", None)
            if not callable(bw) and nav is None:
                bw = getattr(self._room_map(snap), "sight_block", None)   # ROOM_MAP: the room map's wall
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

    def _remember(self, live, now) -> list:
        """Keep where the Ganados were seen (the freshest SIGHT_MEMORY_N, for SIGHT_MEMORY_S), so a round is not lost to
        an empty snapshot.

        The operator, 2026-11-12: "the bot survived, but they lost because they didn't go and find the enemies of the
        level to go fight them" and "make sure the bot understands and knows where enemies are so he can go and locate
        the threats". _locate could only walk to a Ganado present in THIS snapshot; with none present it swept blindly,
        which is the "just running around in the castle" he saw. Remembered positions give it somewhere to go.
        """
        mem = self.__dict__.setdefault("_seen", [])
        if live:
            mem.extend((float(t[2]["pos"][0]), float(t[2]["pos"][1]), float(t[2]["pos"][2]), now) for t in live
                       if t[2].get("pos"))
            del mem[:-SIGHT_MEMORY_N]
        return [m for m in mem if now - m[3] <= SIGHT_MEMORY_S]

    def _locate(self, p, live, now, cmd=None, snap=None) -> dict:
        """Nobody in range: the nearest Ganado by the map, walked to (run past RUN_CM); nobody known: the sweep."""
        if live:
            dist, err, e = min(live, key=lambda t: t[0])
            self.stats["locates"] += 1
            self.stats["locate_m"] = round(dist / 1000.0, 1)
            self.doing = "locate"
            run = dist > RUN_CM or self.combo_owed(now) is not None or self.__dict__.get("_cmd") in CMD_RUN
            keys, how = self._approach(p, e["pos"], err, snap or {}, run)
            self.why = f"locating: the nearest Ganado {dist / 1000:.0f} m off by {how}" + (f" ({cmd})" if cmd else "")
            return {"hold": keys}
        # None in this snapshot: go back to where they were last seen instead of sweeping blind (the operator's "they
        # lost because they didn't go and find the enemies of the level to go fight them").
        mem = self.__dict__.get("_seen") or []
        if mem and isinstance(p, dict) and p.get("pos"):
            x, y, z, _at = mem[-1]
            err = wrap(heading(x - p["pos"][0], z - p["pos"][2]) - (p.get("rot") or 0.0))
            keys, how = self._approach(p, (x, y, z), err, snap or {}, True)
            self.stats["locate_memory"] = self.stats.get("locate_memory", 0) + 1
            self.doing = "locate"
            self.why = (f"locating: back to where they were seen, "
                        f"{self._flat(p['pos'], (x, y, z)) / 1000:.0f} m by {how}")
            return {"hold": keys}
        if self._sweep_at is None or now - self._sweep_at >= SWEEP_S:
            self._sweep_at, self._sweep_dir = now, -self._sweep_dir
            self.stats["sweeps"] += 1
        self.doing, self.why = "sweep", "no Ganado on the map: exploring"
        return {"hold": {"lup", TURN["right" if self._sweep_dir > 0 else "left"]}}

    def _gun_down_telemetry(self, up: bool, now: float) -> None:
        """The raise / lower count the operator sees (2026-11-10: the bot "raising their weapon over and over", jarring
        on the camera): every tick the gun went from up to down, what did it (gun_down_last) and a count by reason
        (gun_down_<doing>), with the ticks the gun was up / down."""
        was = self.__dict__.get("_gun_up")
        if was and not up:
            self.stats["gun_downs"] = self.stats.get("gun_downs", 0) + 1
            self.stats["gun_down_last"] = f"{self.doing}: {self.why}"[:120]
            key = "gun_down_" + str(self.doing or "none")[:16]
            self.stats[key] = self.stats.get(key, 0) + 1
        self.stats["gun_up_ticks" if up else "gun_down_ticks"] = \
            self.stats.get("gun_up_ticks" if up else "gun_down_ticks", 0) + 1
        self.__dict__["_gun_up"] = up

    def _pose_tick(self, p, now) -> None:
        """His position or facing changed since the last tick (FROZEN_MM / FROZEN_RAD): he is in control."""
        pos, rot = tuple(p["pos"]), p.get("rot")
        last = self.__dict__.get("_uc_pose")
        self._uc_pose = (pos, rot)
        if last is not None and (self._flat(last[0], pos) > FROZEN_MM or (
                rot is not None and last[1] is not None and abs(wrap(rot - last[1])) > FROZEN_RAD)):
            self._aim_stick().control(now)
            self._uc_control_at = now

    def _camera_collapsed(self, snap, now, pushing: bool) -> bool:
        """CAMERA_COLLAPSE above: this tick's camera-to-player distance through combat.CameraCollapse; True on the tick
        a collapse is found. Not within CAM_SETTLE_S of the gun being up (its own zoom). stats camera_dist_mm."""
        dist = snap.get("camera_dist_mm")
        if not isinstance(dist, (int, float)) or isinstance(dist, bool):
            return False
        self.stats["camera_dist_mm"] = dist
        d = self.__dict__
        cc, source = d.get("_uc_cam"), snap.get("camera_dist_source") or "player"
        if cc is None or d.get("_uc_cam_source") != source:  # (another distance: a median of its own)
            cc = d["_uc_cam"] = combat.CameraCollapse(self.stats, CAM_COLLAPSE_X, CAM_COLLAPSE_S)
            d["_uc_cam_source"] = source
            self.stats["camera_dist_source"] = source
        settling = now - (d.get("_uc_cam_aim_at") or -1e9) < CAM_SETTLE_S
        return cc.observe(now, dist, pushing and not settling)

    # --- the room's real map (ROOM_MAP: titles.re4_room_map) ---
    def _room_map(self, snap):
        """This snapshot's room map (ROOM_MAP), else None; stats room_map names the room in use."""
        if not ROOM_MAP:
            return None
        rm = re4_room_map.for_snap(snap)
        if rm is not None:
            self.stats["room_map"] = rm.room
        return rm

    def _walk_test(self, snap):
        """The test for a walk line the bot picks itself, (a, b) mm -> bool, or None with no geometry at all: the
        stage mesh's shot line (nav.clear_segment, as before) and, with ROOM_MAP, the room map's walk_block."""
        nav = snap.get("nav")
        seg = getattr(nav, "clear_segment", None) if nav is not None else None
        seg = seg if callable(seg) else None
        rm = self._room_map(snap)
        if rm is None:
            return seg

        def clear(a, b) -> bool:
            if seg is not None and not seg(tuple(a), tuple(b)):
                return False
            why = rm.walk_block(tuple(a), tuple(b))
            if why is None:
                return True
            self.stats["room_map_walks_refused"] = self.stats.get("room_map_walks_refused", 0) + 1
            self.stats["room_map_refused_last"] = why[:120]
            return False
        return clear

    def _route_leg(self, act, p=None) -> bool:
        """ROOM_LEGS: this tick's action is the mesh walker's own route leg (re4_walk.Walker.leg: the route's steer,
        not a backstop step, toward a waypoint the mesh's floor reaches in a straight line from him), unchanged, with
        his facing within re4_walk.FOLLOW_TOL of the leg (an arc still swinging round toward it is the route-turn's)."""
        w = getattr(self, "walker", None)
        leg = getattr(w, "leg", None) if w is not None else None
        if not ROOM_LEGS or not isinstance(leg, dict) or leg.get("at") != getattr(w, "now", None) or not leg.get("open"):
            return False
        moves = {"lup", "ldown", TURN["left"], TURN["right"]}
        mine = set(act.get("hold") or ()) & moves
        if not mine or mine != set(leg.get("keys") or ()) & moves:
            return False
        if p is not None and isinstance(p.get("rot"), (int, float)) and p.get("pos") and leg.get("to"):
            to = leg["to"]
            off = wrap(heading(to[0] - p["pos"][0], to[1] - p["pos"][2]) - p["rot"])
            if abs(off) > re4_walk.FOLLOW_TOL:
                return False
        return True

    def _room_ahead(self, p, act, snap):
        """ROOM_MAP's probe on a walking tick: None (the way ahead is open, or a crossing the walker is taking), the
        reason the step is refused (a wall or the floor's edge within the probe of his facing - scaled to the room,
        _room_reach), or - when the mesh walker's route steers this tick and the line to its point is clear - that
        route's action: a turn on the spot toward its point while it lies past re4_walk.FOLLOW_TOL
        (room_map_route_turns), else None (the route goes on). A refusal by a wall keeps (why, wall) for the caller in
        self._room_hit: the wall's tangent is the way off it (ROOM_TANGENTS)."""
        d = self.__dict__
        d.pop("_room_hit", None)
        rm, rot, pos = self._room_map(snap), p.get("rot"), p.get("pos")
        if rm is None or not isinstance(rot, (int, float)) or not pos:
            return None
        if self._route_leg(act, p):
            self.stats["room_map_route_legs"] = self.stats.get("room_map_route_legs", 0) + 1
            return None                                      # ROOM_LEGS: the mesh's own route through the opening
        w = getattr(self, "walker", None)
        steered = w is not None and getattr(w, "wp", None) is not None and w.wp[2] == getattr(w, "now", None)
        if steered and getattr(w, "at_link", False):
            return None                                      # a jump-over / a ladder: through it is the way
        hold = set(act.get("hold") or ())
        reach = self._room_reach(rm, hold)
        end = (pos[0] + reach * math.sin(rot), pos[1], pos[2] + reach * math.cos(rot))
        hit = rm.walk_block_detail(tuple(pos), end, end_r=0.0, body_r=ROOM_BRUSH_MM)
        if hit is None:
            return None
        why, wall = hit
        if wall is not None:
            d["_room_hit"] = (why, wall)
        if steered:
            wp = (w.wp[0], pos[1], w.wp[1])
            if rm.walk_block(tuple(pos), wp, end_r=0.0, body_r=0.0) is None:   # (the route keeps its own clearance)
                err = wrap(heading(wp[0] - pos[0], wp[2] - pos[2]) - rot)
                if abs(err) <= re4_walk.FOLLOW_TOL:
                    return None                              # the route's point lies short of the wall: on to it
                self.stats["room_map_route_turns"] = self.stats.get("room_map_route_turns", 0) + 1
                self.doing, self.why = "turn", "the room map: a wall ahead, turning to the route's way round"
                return dict(act, hold=(hold - {"lup", RUN_BTN, TURN["left"], TURN["right"]}) | self._turn(err))
        return why

    def _room_reach(self, rm, hold) -> float:
        """The probe's length (mm): ROOM_PROBE_MM of the room's own scale (ROOM_PROBE_SHARE of its smaller side, within
        ROOM_PROBE_MM .. ROOM_PROBE_MAX_MM), and a run's longer look."""
        try:
            span = rm.span_mm()
        except Exception:                                    # noqa: BLE001 - a map without a span: the fixed probe
            span = 0.0
        reach = max(ROOM_PROBE_MM, min(span * ROOM_PROBE_SHARE, ROOM_PROBE_MAX_MM))
        return max(reach, ROOM_PROBE_RUN_MM) if RUN_BTN in hold else reach

    def _unwall_reach(self, rm) -> float:
        """The step along a wall (mm), scaled to the room like the probe (ROOM_UNWALL_SHARE of its smaller side, within
        UNWALL_MM .. ROOM_UNWALL_MAX_MM): far enough to reach its end or an opening."""
        try:
            span = rm.span_mm() if rm is not None else 0.0
        except Exception:                                    # noqa: BLE001
            span = 0.0
        return max(UNWALL_MM, min(span * ROOM_UNWALL_SHARE, ROOM_UNWALL_MAX_MM))

    @staticmethod
    def _same_heading(a: float, b: float) -> bool:
        return abs(wrap(a - b)) < 1e-6

    def _unwall_tries(self, now, rot, rm, wall, pressed):
        """The headings off his facing (degrees) `combat.WallPress.away` tries, this wall's tangents first (ROOM_TANGENTS:
        he turns to the tangent and walks along the wall), then the default order. The side he was turned onto for this
        wall is kept: a new side is not chosen before UNWALL_SIDE_HOLD_S, and the same wall keeps its hand WALL_KEEP_S.
        None: the default order (the wall is not known)."""
        base = list(combat.WallPress.TRIES_DEG if pressed else SLIDE_TRIES_DEG)
        if not ROOM_TANGENTS or rm is None or wall is None:
            return None if pressed else base
        try:
            sides = list(rm.tangents(wall))
        except Exception:                                    # noqa: BLE001 - no tangent: the default order
            return None if pressed else base
        if not sides:
            return None if pressed else base
        key = tuple(round(v) for v in wall[:4])
        last = self.__dict__.get("_uc_unwall_side")
        remembered = last.get("h") if isinstance(last, dict) and last.get("wall") == key \
            and now - last.get("at", -1e9) <= WALL_KEEP_S else None
        sides.sort(key=lambda h: (0 if remembered is not None and self._same_heading(h, remembered) else 1,
                                  abs(wrap(h - rot))))
        if remembered is not None and now - last.get("at", -1e9) < UNWALL_SIDE_HOLD_S:
            sides = [h for h in sides if self._same_heading(h, remembered)]   # no flip before the hold is over
        degs: list = []
        chosen = None
        for h in sides:
            err = wrap(h - rot)
            if abs(err) > ROOM_TANGENT_MAX_RAD:
                continue                                     # (behind him: the quick turn's, not this)
            deg = math.degrees(err)
            if all(abs(wrap(math.radians(deg - d))) > math.radians(10) for d in degs):
                degs.append(deg)
                if chosen is None:
                    chosen = h
        if not degs or chosen is None:
            return None if pressed else base
        if remembered is None:
            self.stats["unwall_tangents"] = self.stats.get("unwall_tangents", 0) + 1
            self.__dict__["_uc_unwall_side"] = {"wall": key, "h": chosen, "at": now}
        elif not self._same_heading(chosen, remembered) and now - last.get("at", -1e9) >= UNWALL_SIDE_HOLD_S:
            self.stats["unwall_side_switches"] = self.stats.get("unwall_side_switches", 0) + 1
            self.__dict__["_uc_unwall_side"] = {"wall": key, "h": chosen, "at": now}
        for deg in base:
            if all(abs(wrap(math.radians(deg - g))) > math.radians(10) for g in degs):
                degs.append(float(deg))
        return degs

    def _room_wall_beside(self, rm, pos):
        """The wall within his body's height beside him (pressed against it), or None: the room map's own walls."""
        try:
            return rm.wall_near(tuple(pos), WALL_R_MM)
        except Exception:                                    # noqa: BLE001 - the map never costs a tick
            return None

    @staticmethod
    def _on_tangent(p, goal, h) -> bool:
        """The goal `walls.away` chose lies along heading h from where he stands (2 deg): the tangent's own step."""
        return abs(wrap(heading(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) - h)) < math.radians(2.0)

    def _shot_open(self, p, snap) -> bool:
        """A living Ganado in fire range with a clear shot line from where he stands: the fight's own hunt works again,
        so a tangent detour is over (it exists only to open that line)."""
        try:
            for d, _err, e in self._live(p, snap.get("enemies") or ()):
                if d <= ENGAGE_RANGE_CM and self._line_of_sight_ok(p, e, snap):
                    return True
        except Exception:                                    # noqa: BLE001 - a geometry error: the detour goes on
            return False
        return False

    def _tangent_still(self, p, rm, un) -> bool:
        """One more step of the same tangent (the room's own scaled step), when it is walkable: un["goal"] moved on.
        False: the tangent is walled - the unwall is over."""
        if rm is None or not isinstance(un.get("h"), (int, float)):
            return False
        pos, h = tuple(p["pos"]), un["h"]
        dist = self._unwall_reach(rm)
        end = (pos[0] + dist * math.sin(h), pos[1], pos[2] + dist * math.cos(h))
        try:
            if rm.walk_block(pos, end, end_r=0.0, body_r=ROOM_BRUSH_MM) is not None:
                return False
        except Exception:                                    # noqa: BLE001 - a map error: the unwall is over
            return False
        un["goal"] = end
        self.stats["unwall_tangent_steps"] = self.stats.get("unwall_tangent_steps", 0) + 1
        return True

    def _wall_core(self, p, act, snap, now) -> dict:
        """WALL_* above: the action's walk checked against the walls he has pressed, and pressing a new one; with
        ROOM_MAP the room map's walls ahead of him too (_room_ahead)."""
        d = self.__dict__
        try:
            walls = d.get("_uc_walls")
            if walls is None:
                walls = d["_uc_walls"] = combat.WallPress(self.stats, WALL_PRESS_S, WALL_PRESS_MM / MM_PER_CM,
                                                          WALL_KEEP_S, WALL_R_MM / MM_PER_CM, WALL_CONE)
            for k in ("unwalls", "walls_refused", "walls_boxed_in"):
                self.stats.setdefault(k, 0)
            hold = set(act.get("hold") or ())
            if AIM_BTN in hold or act.get("tap"):            # the fight: the gun up, a shot, a press - no walk
                walls.observe(now, (0.0, 0.0, 0.0), None, False)
                d["_uc_unwall"] = None
                if AIM_BTN in hold:
                    d["_uc_cam_aim_at"] = now                # (the aim zooms the camera in: no collapse for a while)
                return act
            w = getattr(self, "walker", None)
            if w is not None and hasattr(w, "guard"):
                act = w.guard(act)                           # the mesh's own probe ahead (a wall, a fence, a drop)
            prof, k = self._profile(), MM_PER_CM
            pos_cm, rot = prof.pos_cm(p["pos"]), p.get("rot")
            un = d.get("_uc_unwall")
            rm = self._room_map(snap)
            fight_first = FIRE_FIRST and self._fire_first(p, snap, now)
            if un is not None:
                if now >= un["until"]:
                    un = d["_uc_unwall"] = None
                elif un.get("mode") == "tangent" and (fight_first or self._shot_open(p, snap)
                                                      or self._route_leg(act, p)):
                    un = d["_uc_unwall"] = None              # the shot / the fight is there: no detour, gun up
                elif self._flat(p["pos"], un["goal"]) <= ESCAPE_ARRIVED_MM:
                    if un.get("mode") == "tangent" and self._tangent_still(p, rm, un):
                        pass                                 # that step walked: on along the same tangent
                    else:
                        un = d["_uc_unwall"] = None
            out = {"hold": self._unwall_keys(p, un["goal"])} if un is not None else act
            hold = set(out.get("hold") or ())
            pushing = "lup" in hold
            in_control = now - (d.get("_uc_control_at") or -1e9) <= CONTROL_S
            # ROOM_LEGS, extended to the unwall (the operator 2026-11-10: the walker turned him back into the wall):
            # while this tick is the mesh walker's own route leg - its steer toward a waypoint the mesh's floor reaches
            # straight from him - no press is learned and no unwall made; the mesh's route is not second-guessed.
            leg = self._route_leg(out, p)
            if leg:
                self.stats["room_map_route_legs"] = self.stats.get("room_map_route_legs", 0) + 1
            pressed = walls.observe(now, pos_cm, rot, pushing, in_control and not leg)
            if CAMERA_COLLAPSE and self._camera_collapsed(snap, now, pushing and in_control) and not pressed:
                walls.remember(now, pos_cm, rot or 0.0)      # the camera pulled into a wall: a press (CAMERA_COLLAPSE)
                self.stats["walls_pressed"] = self.stats.get("walls_pressed", 0) + 1
                pressed = True
            refused = (not pressed and un is None and pushing and walls.blocked(now, pos_cm, rot)
                       and not leg)                          # (ROOM_LEGS: a press near a doorway never shuts it)
            ahead = None
            if not (pressed or refused) and un is None and pushing and ROOM_MAP and not leg:
                ahead = self._room_ahead(p, out, snap)        # a wall / the floor's edge on the room map ahead
                if isinstance(ahead, dict):
                    return ahead                             # the route's own way: a turn toward its point
            if not (pressed or refused or ahead):
                if un is not None:
                    self.doing, self.why = "unwall", un["why"]
                return out
            seg = self._walk_test(snap)                      # the shot line's walls, and the room map's (ROOM_MAP)
            clear = (lambda a, b: bool(seg(tuple(v * k for v in a), tuple(v * k for v in b)))) if seg else None
            hit = d.get("_room_hit") if ahead else None
            wall = hit[1] if isinstance(hit, tuple) and len(hit) > 1 else None
            if wall is None and pressed and rm is not None:
                wall = self._room_wall_beside(rm, p["pos"])   # pressed: the wall beside him is the one to leave
            tries = self._unwall_tries(now, rot or 0.0, rm, wall, pressed)
            goal_cm = walls.away(now, pos_cm, rot or 0.0, clear, self._unwall_reach(rm) / k, tries)
            goal = tuple(v * k for v in goal_cm) if goal_cm is not None else None
            side = d.get("_uc_unwall_side")
            key = tuple(round(v) for v in wall[:4]) if wall is not None else None
            tangent_h = side.get("h") if isinstance(side, dict) and side.get("wall") == key else None
            mode = ("tangent" if (not fight_first and tangent_h is not None and goal is not None
                                  and self._on_tangent(p, goal, tangent_h)) else "step")
            tangent = tries is not None
            why = ("pressed against a wall: along its tangent, then forward" if (tangent and pressed) else
                   "the room map: a wall ahead, along its tangent instead" if tangent else
                   "pressed against a wall: turning away onto open floor" if pressed else
                   "a wall he pressed before lies that way: along it instead" if refused else
                   "the room map: a wall ahead, along it instead")
            if ahead:
                self.stats["room_map_steps_refused"] = self.stats.get("room_map_steps_refused", 0) + 1
                self.stats["room_map_refused_last"] = ahead[:120]
            else:
                self.stats["walls_refused" if refused else "unwalls"] += 1
            if goal is None:
                self.stats["room_map_boxed_in" if ahead else "walls_boxed_in"] = \
                    self.stats.get("room_map_boxed_in" if ahead else "walls_boxed_in", 0) + 1
                self.doing, self.why = "unwall", "walled in on every side: not walking into it"
                return dict(out, hold=hold - {"lup", RUN_BTN})
            d["_uc_unwall"] = {"until": now + (UNWALL_TANGENT_S if mode == "tangent" else UNWALL_S),
                               "goal": goal, "why": why, "mode": mode, "h": tangent_h, "wall": key}
            d.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})["stepped"] = now
            self.doing, self.why = "unwall", why
            return {"hold": self._unwall_keys(p, goal)}
        except Exception as exc:                             # noqa: BLE001 - the core never costs the tick
            self._core_error(exc)
            return act

    def _unwall_keys(self, p, goal) -> set:
        """Toward an open-floor goal: the quick turn when it lies behind him, a turn on the spot while it is more than
        STEP_TURN_RAD off, then the walk onto it."""
        err = wrap(heading(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) - (p.get("rot") or 0.0))
        if abs(err) > ESCAPE_QUICK_RAD:
            return set(QUICK_TURN)
        if abs(err) > STEP_TURN_RAD:
            return self._turn(err)
        return {"lup"} | (self._turn(err) if abs(err) > self.TURN_TOL else set())

    def _never_stand(self, p, act, snap, now) -> dict:
        """The doctrine's floor: a tick that neither fires nor moves him for STAND_MAX_S becomes a STAND_STEP_S step.
        With UNIVERSAL_CORE the shared rules (combat (g), AIM_KEEP_RAD above): the fight meets it while he fires at a
        target in range or turns toward it, and the step goes along open floor (_never_stand_core); else the first
        version: forward with a turn, the way changing each time. Aiming and firing are never standing."""
        if UNIVERSAL_CORE:
            try:
                return self._never_stand_core(p, act, snap, now)
            except Exception as exc:                     # noqa: BLE001 - the core never costs the tick
                self._core_error(exc)
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
        # One turn direction for a BURST of steps. It used to alternate every single step (n % 2), which is the
        # back-and-forth on the spot the operator reported; four steps one way still flip, so a wall does not hold him.
        keys = {"lup", TURN["left" if (st["n"] // 4) % 2 else "right"]}
        st.update(pos=tuple(pos), at=now, until=now + STAND_STEP_S, keys=tuple(keys))
        self.__dict__.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})["stepped"] = now
        self.stats["stand_breaks"] += 1
        self.doing, self.why = "step", f"stood {STAND_MAX_S:.1f} s: a step (he never stands)"
        return dict(act, hold=keys)

    def _never_stand_core(self, p, act, snap, now) -> dict:
        """The never-stand rule by the shared discipline (combat.stand_engaged / combat.open_step): not standing while
        the gun is up or a shot goes out, nor while a target in fire range with a clear shot is fired at or turned
        toward (STAND_TURN_RAD of facing since the anchor); else STAND_MAX_S without STAND_MOVE_CM is a STAND_STEP_S
        step to a point STAND_STEP_MM along open floor (the stage mesh's clear_segment), steered there tick by tick;
        walled in on every line, no step. Without a mesh: the first version's step (forward, a turn each way)."""
        st, pos, rot = self._stand, tuple(p["pos"]), p.get("rot")
        hold = set(act.get("hold") or ())
        if act.get("tap") or AIM_BTN in hold:
            st.update(pos=pos, rot=rot, at=now, until=-1e9, goal=None)
            return act
        if now < st["until"]:
            return dict(act, hold=self._step_keys(p, st))
        if st["pos"] is None or st["at"] is None or self._flat(st["pos"], pos) > STAND_MOVE_CM:
            st.update(pos=pos, rot=rot, at=now)
            return act
        moved_s = now - st["at"]                          # (st["at"] is the last time he actually MOVED)
        turned = (rot is not None and st.get("rot") is not None and abs(wrap(rot - st["rot"])) > STAND_TURN_RAD
                  and moved_s <= TURN_EXCUSE_S)
        blocked = bool(self.__dict__.get("_pick_blocked")) or self.__dict__.get("_gate") == "sight"
        if combat.stand_engaged(self.target is not None and self.doing in ENGAGED_DOINGS, blocked,
                                now - self._last_fire, turned, STAND_MAX_S):
            if turned:
                st.update(pos=pos, rot=rot)              # the anchor moves on, the stand clock does NOT reset: a turn
                                                          # is not walking (TURN_EXCUSE_S above)
            self.stats["stand_engaged"] = self.stats.get("stand_engaged", 0) + 1
            return act
        if now - st["at"] < STAND_MAX_S:
            return act
        st["n"] = st.get("n", 0) + 1
        seg = self._walk_test(snap)                      # the shot line's walls, and the room map's (ROOM_MAP)
        goal, keys = None, ()
        if callable(seg):
            foes = [e["pos"] for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")]
            tries = (0, 45, -45, 90, -90, 135, -135, 180) if st["n"] % 2 else (0, -45, 45, -90, 90, -135, 135, 180)
            goal = combat.open_step(pos, rot or 0.0, seg, STAND_STEP_MM, avoid=foes, avoid_r=ESCAPE_CLEAR_MM,
                                    tries_deg=tries)
            if goal is None:
                # Every planned direction was refused, and this used to stand and re-try: on Base (r403) that was
                # walk_m 0.0 for the whole round, walk_still_s 2.2 and room_map_walks_refused 7 while the Ganados
                # closed - the operator's "standing in place trying to walk instead of going forward". A refused
                # DESTINATION is not a reason to stand: walk forward with a turn (the mesh-less step) and let the next
                # tick re-plan. Measured first: halving the room map's clearance rescued 0 of 707 wall-side walks, so
                # the refusal is right and the standing was the defect.
                self.stats["steps_walled_in"] = self.stats.get("steps_walled_in", 0) + 1
                keys = ("lup", TURN["left" if (st["n"] // 4) % 2 else "right"])
        else:
            keys = ("lup", TURN["left" if st["n"] % 2 else "right"])
        st.update(pos=pos, rot=rot, at=now, until=now + STAND_STEP_S, keys=keys, goal=goal)
        self.__dict__.setdefault("_fz", {"pos": None, "rot": None, "tap": -1e9, "on": False})["stepped"] = now
        self.stats["stand_breaks"] += 1
        self.doing, self.why = "step", (f"stood {STAND_MAX_S:.1f} s: a step "
                                        + ("along open floor" if goal is not None
                                           else "walled in: forward anyway" if callable(seg) else "(no stage mesh)"))
        return dict(act, hold=self._step_keys(p, st))

    def _step_keys(self, p, st) -> set:
        """The step's keys this tick: toward its open-floor goal (a turn on the spot while it lies more than
        STEP_TURN_RAD off his facing - never forward into what is in front), else the first version's fixed keys (the
        step it takes with no mesh at all walks forward with the turn, never a turn alone).

        The turn has a hysteresis (operator 2026-11-11: "the bot is vibrating ... whenever they're walking ... twitching
        around and not walking forward in a linear fashion"): a small opposite error keeps the direction already under
        way, so the left/right keys cannot flutter every tick; only a clear reversal (past 2 x TURN_TOL) turns back.
        """
        goal = st.get("goal")
        if goal is None:
            return set(st.get("keys") or ())
        err = wrap(heading(goal[0] - p["pos"][0], goal[2] - p["pos"][2]) - (p.get("rot") or 0.0))
        if abs(err) > STEP_TURN_RAD:
            self.__dict__.pop("_step_turn_sign", None)
            return self._turn(err)
        if abs(err) > self.TURN_TOL:
            last = self.__dict__.get("_step_turn_sign")
            sign = 1 if err > 0 else -1
            if last is not None and sign != last and abs(err) < self.TURN_TOL * 2:
                sign = last
            self.__dict__["_step_turn_sign"] = sign
            return {"lup"} | self._turn(abs(err) * sign)
        self.__dict__.pop("_step_turn_sign", None)
        return {"lup"}

    # --- the universal core (UNIVERSAL_CORE: gbox.mercs.core.combat) ---
    def _uc(self, name: str):
        """The core's pieces, made on first use (a bot the hot reload rebinds to this class never ran this version's
        __init__): threats (combat.Threats on THREAT_FILE), nic (combat.NotInControl), idle (combat.IdleGuard)."""
        d = self.__dict__
        got = d.get("_uc_" + name)
        if got is None:
            if name == "threats":
                got = combat.Threats(self._profile(), self.stats)
            elif name == "nic":
                got = combat.NotInControl(self.stats, prefix="frozen")
            else:
                got = combat.IdleGuard(self.stats)
            d["_uc_" + name] = got
        return got

    def _profile(self) -> combat.TitleProfile:
        """This tick's profile (made at the tick's start by _core_tick), else a fresh one."""
        return self.__dict__.get("_uc_prof") or combat_profile()

    def _core_error(self, exc) -> None:
        self.stats["universal_core_error"] = f"{type(exc).__name__}: {exc}"[:160]
        self.stats["universal_core_errors"] = self.stats.get("universal_core_errors", 0) + 1

    def _core_tick(self, p, snap, now) -> None:
        """Every tick: the profile (the live constants), and who hurt him (the living Ganados, his life's falls)."""
        try:
            prof = self.__dict__["_uc_prof"] = combat_profile()
            self._uc("threats").observe(now, p, snap.get("enemies") or (), prof)
        except Exception as exc:                         # noqa: BLE001 - the core never costs the tick
            self._core_error(exc)

    def _threat_pick(self, p, near):
        """(distance, error, enemy) of the scorer's first tiers among `near` (combat.Threats.priority: a wind-up within
        its reach, else a grudge on his level), or None: RE4's own choice stands."""
        try:
            got = self._uc("threats").priority(p, [t[2] for t in near])
        except Exception as exc:                         # noqa: BLE001
            self._core_error(exc)
            return None
        if got is None:
            return None
        e, kind, why = got
        pick = next((t for t in near if t[2] is e), None)
        if pick is None:
            return None
        if e.get("ptr") != self.target:
            self.stats[kind + "_picks"] = self.stats.get(kind + "_picks", 0) + 1
        self.why = why
        self.stats["core_pick"] = f"{kind}: {why}"[:160]
        return pick

    def _lethal_out(self, p, live, snap, now) -> dict | None:
        """A learned attack that lands through his shots, under way within its reach (combat.Threats.step_out): away
        along open floor (_escape), LETHAL_RUN_S at a time; walled in, he fights it."""
        act = self._escaping(p, snap, now, "lethal")
        if act is not None:
            return act
        try:
            e = self._uc("threats").step_out(p, [t[2] for t in live], now)
        except Exception as exc:                         # noqa: BLE001
            self._core_error(exc)
            return None
        if e is None:
            return None
        act = self._escape(p, live, snap, now, "lethal", LETHAL_RUN_S)
        if act is None:
            return None
        self.doing, self.why = "evade", (f"{threat_class(e)}: an attack that hurt him through his shots (learned): "
                                         "out of its reach")
        return act

    @staticmethod
    def _hand_ask(item) -> int:
        """A new HAND_REQUEST (an item id to hold, or None: the gun back) for re4_switch_mods.maintain; its seq."""
        seq = (HAND_REQUEST.get("seq") or 0) + 1
        HAND_REQUEST.clear()
        HAND_REQUEST.update(item=item, seq=seq, at=time.monotonic())
        return seq

    def _fleeing(self, now) -> bool:
        """An escape run under way (low life, a heavy, a swarm, a learned attack)."""
        return any((r := self.__dict__.get("_run_" + k)) and now < r["until"] for k in ("low", "heavy", "swarm", "lethal"))

    def _throw_core(self, p, live, snap, now) -> dict | None:
        """THROWS above: this tick's step of a throw (combat.ThrowPolicy decides): hand (the swap asked, HAND_STATE's
        answer awaited), aim (the body to the pack's centre, ZL THROW_RAISE_S), the throw (ZR), the follow-through,
        back (the gun's bytes written back). None: no throw now. With a Ganado at arm's length the throw is dropped
        (the gun back first) - never a grenade at his own feet."""
        d = self.__dict__
        pol = d.get("_uc_throws")
        if pol is None:
            pol = d["_uc_throws"] = combat.ThrowPolicy(self.stats)
        try:
            prof = self._profile()
            pol.observe(prof, now, self.stats.get("kills_seen"))
            st = d.get("_uc_throw")
            if st is None:
                if not THROWS:
                    return None
                fleeing = self._fleeing(now)
                plan = pol.decide(prof, now, p, [t[2] for t in live], set(THROW_ITEMS), fleeing=fleeing)
                if plan is None:
                    return None
                pol.started(now)
                st = d["_uc_throw"] = {"plan": plan, "phase": "hand", "since": now, "t0": now,
                                       "seq": self._hand_ask(THROW_ITEMS[plan.kind]), "thrown": False}
            plan, item = st["plan"], THROW_ITEMS[st["plan"].kind]
            close = plan.kind != "flash" and any(t[0] <= prof.units(prof.grab_r_cm) for t in live)   # (the flash is
            if st["phase"] in ("hand", "aim") and (close or now - st["t0"] > THROW_MAX_S):          # for that one)
                self.stats["throw_aborts"] = self.stats.get("throw_aborts", 0) + 1
                self.stats["throw_abort_last"] = "a Ganado at arm's length" if close else "no throw within THROW_MAX_S"
                st.update(phase="back", since=now, seq=self._hand_ask(None))
            if st["phase"] == "hand":
                if HAND_STATE.get("seq") == st["seq"]:
                    if HAND_STATE.get("verified") and HAND_STATE.get("item") == item:
                        st.update(phase="aim", since=now)
                    else:
                        self.stats["throw_aborts"] = self.stats.get("throw_aborts", 0) + 1
                        self.stats["throw_abort_last"] = f"the swap: {HAND_STATE.get('error') or 'not verified'}"[:120]
                        st.update(phase="back", since=now, seq=self._hand_ask(None))
                elif now - st["since"] > THROW_HAND_S:
                    self.stats["throw_aborts"] = self.stats.get("throw_aborts", 0) + 1
                    self.stats["throw_abort_last"] = "the swap never answered"
                    st.update(phase="back", since=now, seq=self._hand_ask(None))
                else:
                    self.doing, self.why = "throw", f"the {plan.kind} grenade to hand: {plan.why}"
                    return {"hold": set()}
            if st["phase"] == "aim":
                q = plan.point
                err = wrap(heading(q[0] - p["pos"][0], q[2] - p["pos"][2]) - (p.get("rot") or 0.0))
                if abs(err) > RAISE_TOL:
                    st["since"] = now                        # the raise's clock from when he faces them
                    self.doing, self.why = "turn", f"the {plan.kind} grenade: turning to {plan.why}"
                    return {"hold": self._turn(err)}
                if now - st["since"] < THROW_RAISE_S:
                    self.doing, self.why = "aim", f"the {plan.kind} grenade up at {plan.why}"
                    return {"hold": {AIM_BTN}}
                pol.thrown(now, plan.fleeing, self.stats.get("kills_seen"))
                st.update(phase="settle", since=now, thrown=True)
                self.doing, self.why = "throw", f"the {plan.kind} grenade at {plan.why}"
                return {"hold": {AIM_BTN}, "tap": FIRE_BTN}
            if st["phase"] == "settle":
                if now - st["since"] < THROW_SETTLE_S:
                    self.doing, self.why = "throw", "the throw's follow-through"
                    return {"hold": set()}
                st.update(phase="back", since=now, seq=self._hand_ask(None))
            if st["phase"] == "back":
                if HAND_STATE.get("seq") == st["seq"] or now - st["since"] > THROW_HAND_S:
                    if HAND_STATE.get("seq") != st["seq"]:
                        self.stats["hand_restore_timeouts"] = self.stats.get("hand_restore_timeouts", 0) + 1
                    d["_uc_throw"] = None
                    return None
                run = self._escaping(p, snap, now, "swarm") if close else None
                self.doing, self.why = "throw", "the gun back in his hand"
                return {"hold": set((run or {}).get("hold") or ()) - {AIM_BTN}}   # (never ZL with a grenade in hand)
        except Exception as exc:                             # noqa: BLE001 - the core never costs the tick
            self._core_error(exc)
            if d.get("_uc_throw") is not None:
                self._hand_ask(None)
            d["_uc_throw"] = None
        return None

    def _idle_core(self, p, act, snap, now) -> dict:
        """combat.IdleGuard on this tick's action: the gun up IDLE_AIM_S at the Ganado in range without a shot ->
        FLANK_S of the walk round to him (the flank), the gun down."""
        try:
            hold = set(act.get("hold") or ())
            tap = act.get("tap")
            verdict = self._uc("idle").tick(self._profile(), now, threat=self.target is not None,
                                            aiming=AIM_BTN in hold, fired=tap in (FIRE_BTN, ACTION_BTN, KNIFE_BTN),
                                            moving=bool(hold & {"lup", "ldown", "lleft", "lright"}))
        except Exception as exc:                         # noqa: BLE001
            self._core_error(exc)
            return act
        if verdict != "move":
            return act
        e = next((x for x in snap.get("enemies") or () if x.get("ptr") == self.target and x.get("pos")), None)
        if e is None:
            return act
        err = wrap(heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]) - (p.get("rot") or 0.0))
        self._flank = {"key": self.target, "until": now + FLANK_S}
        self.stats["flanks"] = self.stats.get("flanks", 0) + 1
        keys, how = self._approach(p, e["pos"], err, snap, run=False)
        self.doing, self.why = "flank", f"the gun up {IDLE_AIM_S:.1f} s without a shot: round him by {how}"
        return {"hold": keys}

    def prompt_ok(self, button, snap, now):
        return False

    def save(self):
        t = self.__dict__.get("_uc_threats")
        if t is not None:
            try:
                t.save()                                 # who hurt him, for the next round (THREAT_FILE)
            except Exception:                            # noqa: BLE001
                pass
        c = self.__dict__.get("_aim_book_core")
        if c is not None:
            try:
                c.save()                                 # the aim book's lessons (AIM_BOOK)
            except Exception:                            # noqa: BLE001
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
