"""Resident Evil 4 (Nintendo Switch, title 010099A00BC1E000 v1.0.2): weapons, upgrade levels, ammo and the inventory in
RAM - offsets and decoders, READ ONLY (nothing here writes guest memory).

Every offset is a module (memory) offset of main, found statically in the decrypted NSO (docs/research/re4-weapons-ram.md
has the instructions, the cross-references and what a live test must check). Module offsets are fixed addresses on
lilspark (re4_switch.KNOWN_BASES); add the base found by re4_switch.module_base().

  tables (rodata unless noted)  WEAPON_TBL     43 x 22 B  {u16 id, u8, u8 class, u8 variant, u8, u16 ammo id, u16 cap[7]}
                                MAX_LEVEL_TBL  30 x 6 B   {u16 id, u8 max firepower, firing speed, reload, capacity}
                                FIRE_RATE_TBL  49 x f32[5] frames (30 Hz) between shots per firing-speed level
                                RELOAD_TBL     49 x f32[3] frames per reload level
                                FIREPOWER_TBL  49 x f32[7] damage per firepower level (DATA segment: writable)
                                SHOTGUN_FAR_TBL 3 x f32[7] the shotguns' second firepower column (DATA)
                                RIFLE_FIRE_TBL  2 x f32[5] the scoped rifles' shot timer (rifle, semi-auto)
  the game state                GAME_OBJ (bss; the pointer variable GAME_PTR_VAR holds its address): the equipped
                                weapon's class / variant / levels, the character, the mode flags, the frame step
  the item manager              ITEM_MGR (bss): the equipped item, the 384-slot item array (heap) of 14-byte items
  the player unit               re4_switch's player pointer: routine bytes +0x114, motion +0x228, motion speed +0x304

An item's upgrade levels are four 0-based nibbles of the u16 at item+6 (firepower | firing speed << 4 | reload << 8 |
capacity << 12; a nibble of 6 is the "exclusive" column); its loaded rounds are the u16 at item+8 >> 3.
"""
from __future__ import annotations

import struct

GAME = "010099A00BC1E000"

# --- static tables in main (module offsets) --------------------------------------------------------------------
WEAPON_TBL, WEAPON_N, WEAPON_SZ = 0xA07CC6, 43, 22
MAX_LEVEL_TBL, MAX_LEVEL_N, MAX_LEVEL_SZ = 0xA08078, 30, 6
N_CLASSES = 0x31
FIRE_RATE_TBL, FIRE_RATE_COLS = 0xA0AA18, 5          # GOT slot 0xB275D0; read by 0x293B50 (display) and 0x31E060
RELOAD_TBL, RELOAD_COLS = 0xA0A580, 3                # GOT slot 0xB275D8; read by 0x293BC0
FIREPOWER_TBL, FIREPOWER_COLS = 0xAF0E8C, 7          # GOT slot 0xB26760; read by 0x293910 and the damage routine
SHOTGUN_FAR_TBL = 0xAF13E8                           # GOT slot 0xB26768; rows for SHOTGUN_FAR_CLASSES in this order
SHOTGUN_FAR_CLASSES = (0x07, 0x08, 0x21)             # Shotgun, Striker, Riot Gun
RIFLE_FIRE_TBL = 0xA0BDD0                            # read by 0x333B00 as row (class - 9)
RIFLE_FIRE_CLASSES = (0x09, 0x0A)                    # Rifle, Rifle (semi-auto)
WRITABLE = {FIREPOWER_TBL: True, SHOTGUN_FAR_TBL: True, FIRE_RATE_TBL: False, RELOAD_TBL: False,
            RIFLE_FIRE_TBL: False, WEAPON_TBL: False, MAX_LEVEL_TBL: False}   # by segment (rodata is mapped r--)

FPS = 30                        # the tables count 30 Hz frames: 0x293B50 returns FR / 30.0 seconds
GATE_LEAD = 2                   # 0x31E060 waits for the shot motion to cross frame int(FR) - 2
RAPID_FIRE_FLOOR = 3.0          # the smallest FR whose int(FR) - 2 (= 1) the crossing test 0x2B9810 can still see
CAP_INFINITE = 0x8000           # a capacity entry of 0x8000: use_ammo (0x2997E0) never consumes
EXCLUSIVE = 6                   # the nibble that selects a table's 7th (exclusive) column

# --- the game state object ---------------------------------------------------------------------------------------
GAME_PTR_VAR = 0xB1AE08         # data: u64 = module + GAME_OBJ (relocated; the GOT slot 0xB25D78 holds &GAME_PTR_VAR)
GAME_OBJ = 0x1274338            # bss
G_FLAGS = 0x78                  # u32 mode flags: bit 30 = The Mercenaries (the loadout dispatcher 0x296CA0)
MERCS_FLAG = 1 << 30
G_FRAME_STEP = 0xA4             # f32: added to every motion frame x its speed each tick (1.0 = one 30 Hz frame);
                                # CountDown::move (0x200C0) takes it off the round clock: read 0.5 live (60 fps),
                                # 2026-11-10 (re4_switch.PG_SPEED)
G_MONEY = 0x501C                # u32 (inferred: GC layout +0x78, zeroed by the new-game routine)
G_ROOM = 0x5020                 # u16 0xSSRR (inferred: GC layout +0x78)
G_HP, G_HP_MAX = 0x5028, 0x502A # u16: = module + 0x1279360 (re4_switch.PLAYER_LIFE, measured live) - the +0x78 shift
G_CLASS = 0x5034                # u8 the equipped weapon's class (WEAPON_TBL row +3), set by equip 0x294600 / 0x296D80
G_VARIANT = 0x5035              # u8 its variant (row +4: 0 plain, 1 silencer / scope, 2 stock / IR scope)
G_EMPTY = 0x5036                # u8 1 while its magazine is empty
G_FIREPOWER = 0x5037            # u8 its firepower nibble (the damage routine reads FIREPOWER_TBL[class][min(n, 6)])
G_FIRING_SPEED = 0x5038         # u8 its firing-speed nibble (0x31E060 / 0x333B00 index the fire tables with it)
G_CAPACITY = 0x5039             # u8 its capacity nibble
G_CHARACTER = 0x503C            # u8 0 Leon, 1 Ashley, 2 Ada, 3 HUNK, 4 Krauser, 5 Wesker (the loadout switch's index)
G_RELOAD = 0x503E               # u8 its reload nibble
G_DIFFICULTY = 0x84F0           # u8 (inferred: <= 1 doubles damage and magazine capacity)
G_PAUSE = 0x86FF                # u8 non-zero: units do not advance their motions
CHARACTERS = {0: "Leon", 1: "Ashley", 2: "Ada", 3: "HUNK", 4: "Krauser", 5: "Wesker"}

# --- the item manager --------------------------------------------------------------------------------------------
ITEM_MGR = 0x124D918            # bss (the GOT slot 0xB25F60 holds its address)
M_EQUIPPED = 0x10               # u64 item* of the equipped item (0 = none)
M_EQUIPPED_ID = 0x18            # u16 its id; NO_WEAPON when nothing is in hand
M_OWNER = 0x1B                  # u8 whose items the lists mean: 1 = Ashley's, else 0
M_ITEMS = 0x20                  # u64 item array (heap)
M_LAST = 0x28                   # u64 the item the last give made
M_SLOTS = 0x30                  # i32 array length (the constructor 0x296FB0 sets 384)
NO_WEAPON = 0x800
ITEM_SZ = 14
ITEM_SLOTS = 384

# --- the player unit (re4_switch.S_PLAYER_2 -> the unit) -------------------------------------------------------------
P_ROUTINE = 0x114               # u8[4] the routine numbers (r_no 0..3); the handgun-style shot is +0x115 = 25 (inferred)
P_MOTION = 0x228                # the unit's motion; frame f32 at +0x2C (cur) / +0x34 (prev), +0xD4 the running frame
P_MOTION_FRAME = P_MOTION + 0x2C
P_MOTION_PREV = P_MOTION + 0x34
P_MOTION_SPEED = 0x304          # f32 = motion + 0xDC: frame += speed x G_FRAME_STEP each tick (0x2B8F10); 1.0 normal
P_RIFLE_TIMER = 0x4E4           # f32 the scoped rifle's shot timer (0x333B00 adds G_FRAME_STEP, fires past the table)

# --- weapons: id -> class (WEAPON_TBL, measured) and the max-level counts (MAX_LEVEL_TBL, measured) --------------------
CLASS_OF = {
    0x23: 0x02, 0x24: 0x02, 0x25: 0x03, 0x26: 0x03, 0x03: 0x11, 0x21: 0x01, 0x40: 0x01, 0x27: 0x04, 0x29: 0x05,
    0x2C: 0x07, 0x2D: 0x08, 0x2E: 0x09, 0x6B: 0x09, 0x99: 0x09, 0x2F: 0x0A, 0x6C: 0x0A, 0x51: 0x0A, 0x30: 0x0B,
    0x32: 0x0B, 0x36: 0x0E, 0xAB: 0x0E, 0x2A: 0x06, 0x34: 0x0C, 0x35: 0x0D, 0x17: 0x0D, 0x6D: 0x0D, 0x37: 0x0F,
    0x38: 0x10, 0x01: 0x13, 0x02: 0x16, 0x0E: 0x17, 0x08: 0x19, 0x09: 0x1F, 0x0A: 0x20, 0x94: 0x21, 0x52: 0x1C,
    0x3E: 0x0B, 0x41: 0x2E, 0x28: 0x2E, 0x10: 0x30, 0x47: 0x07, 0x53: 0x0C,
}
MAX_LEVELS = {                  # id: (firepower, firing speed, reload, capacity) level COUNTS (nibble max = count - 1)
    0x23: (6, 3, 3, 6), 0x24: (6, 3, 3, 6), 0x25: (6, 3, 3, 6), 0x26: (6, 3, 3, 6), 0x03: (6, 1, 3, 6),
    0x21: (6, 3, 3, 6), 0x40: (6, 3, 3, 6), 0x27: (6, 3, 3, 6), 0x29: (6, 1, 3, 4), 0x2C: (6, 1, 3, 6),
    0x2D: (6, 1, 3, 6), 0x94: (6, 1, 3, 6), 0x2E: (6, 1, 3, 6), 0x6B: (6, 1, 3, 6), 0x99: (6, 1, 3, 6),
    0x2F: (6, 1, 3, 6), 0x6C: (6, 1, 3, 6), 0x51: (6, 1, 3, 6), 0x30: (6, 1, 3, 6), 0x32: (6, 1, 3, 6),
    0x3E: (6, 1, 3, 6), 0x36: (3, 1, 2, 3), 0xAB: (3, 1, 2, 3), 0x34: (6, 1, 1, 6), 0x2A: (3, 1, 3, 3),
    0x37: (6, 1, 3, 6), 0x47: (6, 1, 1, 6), 0x53: (6, 1, 1, 6), 0x41: (1, 1, 1, 1), 0x28: (1, 1, 1, 1),
}
# the 7th capacity entry (the exclusive) where it is not 0 - Matilda / Striker 100, Chicago / Handcannon infinite
EXCLUSIVE_CAPACITY = {0x03: 100, 0x2D: 100, 0x34: CAP_INFINITE, 0x53: CAP_INFINITE, 0x37: CAP_INFINITE}
# campaign guns a random "high-powered, max level" pick draws from (magnums, shotguns, rifles, machine guns, launchers)
# No sniper rifles (operator 2026-11: "do not have people using sniper rifles at all ... replace them with random rapid
# fire magnums or shotguns"): the scoped Rifle (0x2E) and Rifle semi-auto (0x2F) are never drawn at random.
SNIPER_ITEMS = frozenset({0x2E, 0x2F, 0x51, 0x6B, 0x6C, 0x99})
HIGH_POWER = tuple(i for i in (0x29, 0x2A, 0x37, 0x2D, 0x94, 0x2C, 0x34, 0x25, 0x27, 0x30, 0x03, 0x35, 0x6D,
                               # 0x36 the MINE THROWER: the operator wants it used ("I want the mine launcher to be
                               # used"), and a mine-dart is a weapon-path projectile (class 0x0E) with no spawn helper
                               # to aim at a coordinate, so drawing it as the round's weapon is the only way to have
                               # it in play - the native ring can spawn only grenade-class blasts (0x13/0x16/0x17).
                               0x36)
                   if i not in SNIPER_ITEMS)
NAMES = {
    0x01: "Hand Grenade", 0x02: "Incendiary Grenade", 0x03: "Matilda", 0x04: "Handgun Ammo", 0x05: "First Aid Spray",
    0x07: "Rifle Ammo", 0x0E: "Flash Grenade", 0x10: "item 0x10 (class 0x30, ammo 0x11; name unconfirmed)",
    0x17: "Rocket Launcher (Special)", 0x18: "Shotgun Shells", 0x1A: "Handcannon Ammo", 0x20: "TMP Ammo",
    0x21: "Punisher", 0x23: "Handgun", 0x24: "Handgun w/ Silencer", 0x25: "Red9", 0x26: "Red9 w/ Stock",
    0x27: "Blacktail", 0x28: "item 0x28 (class 0x2E like the P.R.L. 412; name unconfirmed)", 0x29: "Broken Butterfly",
    0x2A: "Killer7", 0x2C: "Shotgun", 0x2D: "Striker", 0x2E: "Rifle", 0x2F: "Rifle (semi-auto)", 0x30: "TMP",
    0x32: "TMP w/ Stock", 0x34: "Chicago Typewriter", 0x35: "Rocket Launcher", 0x36: "Mine Thrower", 0x37: "Handcannon",
    0x38: "Knife", 0x3E: "Custom TMP", 0x3F: "Silencer (Handgun)", 0x40: "Punisher (variant)", 0x41: "P.R.L. 412",
    0x45: "Scope (semi-auto)", 0x46: "Mine-Darts", 0x47: "item 0x47 (shotgun class, 12 shells; name unconfirmed)",
    0x51: "Rifle (semi-auto) w/ Infrared Scope", 0x52: "Krauser's Bow", 0x53: "Chicago Typewriter (Ada)",
    0x6A: "Chicago Typewriter Ammo", 0x6B: "Rifle + Scope", 0x6C: "Rifle (semi-auto) + Scope", 0x6D: "Infinite Launcher",
    0x72: "Arrows", 0x7C: "Attache Case S", 0x7D: "Attache Case M", 0x94: "Riot Gun", 0x99: "Rifle w/ Infrared Scope",
    0xAB: "Mine-thrower + Scope",
}

# The Mercenaries starting inventories, from the code of 0x295070(item manager, G_CHARACTER) (measured statically): what
# each case gives (id, count; one take per entry), the levels it sets (the u16 at item+6) and fills to capacity, and the
# gun it equips. Ashley (1) has an empty case.
MERC_LOADOUTS = {
    0: {"items": ((0x27, 1), (0x94, 1), (0x04, 30), (0x18, 10), (0x05, 1)),
        "levels": {0x27: 0x2114, 0x94: 0x3204}, "equips": 0x27},
    2: {"items": ((0x21, 1), (0x30, 1), (0x2F, 1), (0x45, 1), (0x04, 30), (0x20, 100), (0x07, 5), (0x02, 1),
                  (0x02, 1), (0x02, 1), (0x05, 1)),
        "levels": {0x21: 0x3126, 0x30: 0x2104, 0x2F: 0x1115}, "equips": 0x21},
    3: {"items": ((0x3E, 1), (0x20, 50), (0x01, 1), (0x01, 1), (0x01, 1), (0x05, 1)),
        "levels": {0x3E: 0x2204}, "equips": 0x3E},
    4: {"items": ((0x52, 1), (0x72, 20), (0x72, 10), (0x0E, 1), (0x0E, 1), (0x0E, 1), (0x05, 1)),
        "levels": {}, "equips": 0x52},
    5: {"items": ((0x23, 1), (0x2A, 1), (0x2F, 1), (0x3F, 1), (0x01, 1), (0x01, 1), (0x01, 1), (0x01, 1), (0x0E, 1),
                  (0x0E, 1), (0x0E, 1), (0x02, 1), (0x05, 1)),
        "levels": {0x23: 0x5226, 0x2A: 0x1101, 0x2F: 0x5115}, "equips": 0x23},
}


# The Mercenaries loadout function (0x295070; a jump table by character at 0xA06D98) as decoded from the decrypted
# executable (2026-11-10). Per weapon the case does three things with its id, and a patch has to change all of them:
#   give       MOV w0, #id; MOV w1, #count; BL 0x3578E0       the item is made (its model, its magazine)
#   find       CMP w10, #id                                   the inventory is searched for it - before the level write,
#              and again before the equip (BL 0x294600). The level block does NOT check the search's result: an id the
#              search cannot find is a null item and the game reads address 6 (a crash at the round's start), which is
#              why a give without its finds must never be written.
#   levels     MOV w8, #levels; BFXIL into item+6; MOV w1, #capacity level + 1; BL 0x293C90 (the first magazine)
#   mask       the AND that keeps item+6 afterwards: the compiler folded the known levels into the mask constant
#              (0x72114 for the Blacktail's 0x2114), so new levels would come out ANDed with the old ones; it is
#              replaced by the full mask 0x7FFFF (MOV w8, #0x7ffff, or AND w8, wN, #0x7ffff).
# Each entry: (module offset, role, the build's own instruction word); every word was read from main.bin and checked.
# NOT WRITTEN by default: re4_switch_mods.LOADOUT_CODE_PATCH is off (every boot with it hung at the stage load; code
# written from outside the emulator is not coherent under NCE - docs/research/re4-weapons-ram.md).
# Not patched, so a random weapon reaches them by the in-hand swap instead: Ada's semi-auto rifle (the scope 0x45 is
# attached to it by index), Wesker's semi-auto rifle (its own rifle code at 0x295FD0), Krauser's bow (no level block:
# a gun given there would start with an empty magazine and arrows for ammo).
LOADOUT_SLOTS = {
    0: (                                                                  # Leon
        {"id": 0x27, "equipped": True, "code": (                          # Blacktail
            (0x2951D4, "give", 0x528004E0), (0x295254, "find", 0x71009D5F), (0x295354, "find", 0x71009D5F),
            (0x295278, "levels", 0x52842288), (0x295280, "first_mag", 0x320007E1), (0x295294, "mask_mov", 0x11004108))},
        {"id": 0x94, "code": (                                            # Riot Gun
            (0x2951E4, "give", 0x52801280), (0x2952D4, "find", 0x7102515F),
            (0x2952F8, "levels", 0x52864088), (0x295300, "first_mag", 0x321E03E1), (0x295314, "mask_mov", 0x11037908))},
    ),
    2: (                                                                  # Ada
        {"id": 0x21, "equipped": True, "code": (                          # Punisher
            (0x2954A0, "give", 0x52800420), (0x295584, "find", 0x7100855F), (0x295E94, "find", 0x7100855F),
            (0x2955A8, "levels", 0x528624C8), (0x2955B0, "first_mag", 0x321E03E1), (0x2955BC, "mask_and", 0x121F46A8))},
        {"id": 0x30, "code": (                                            # TMP
            (0x2954B0, "give", 0x321C07E0), (0x2955F8, "find", 0x7100C15F),
            (0x29561C, "levels", 0x52842088), (0x295624, "first_mag", 0x320007E1), (0x295630, "mask_and", 0x121E42A8))},
    ),
    3: (                                                                  # HUNK
        {"id": 0x3E, "equipped": True, "code": (                          # Custom TMP (an ORR-immediate give)
            (0x29581C, "give", 0x321F13E0), (0x2958AC, "find", 0x7100F95F), (0x29592C, "find", 0x7100F95F),
            (0x2958D0, "levels", 0x52844088), (0x2958D8, "first_mag", 0x320007E1), (0x2958EC, "mask_mov", 0x11040108))},
    ),
    5: (                                                                  # Wesker
        {"id": 0x23, "equipped": True, "code": (                          # Handgun (the silencer goes on it)
            (0x295C68, "give", 0x52800460), (0x295D68, "find", 0x71008D5F), (0x29605C, "find", 0x71008D5F),
            (0x295D8C, "levels", 0x528A44C8), (0x295D94, "first_mag", 0x321F07E1), (0x295DA8, "mask_mov", 0x11044688))},
        {"id": 0x2A, "code": (                                            # Killer7 (its mask is already 0x7ffff)
            (0x295C78, "give", 0x52800540), (0x295F5C, "find", 0x7100A95F),
            (0x295F80, "levels", 0x52822028), (0x295F88, "first_mag", 0x321F03E1))},
    ),
}
FULL_MASK = 0x7FFFF            # item+6 levels | item+8 bits 0-2 (the empty bit and its neighbours): everything kept

# --- the attache case: what the loadout's gives can hold ---------------------------------------------------------
# The give 0x3578E0(id, count, mode) places every new item in a case grid first (0x3558A0 builds it from the items
# already there; mode 0, the Mercenaries loadout's, is 10 x 6) and makes the item (0x2942D0) ONLY when it fits: first
# fit, row by row, then turned. An item that does not fit is silently not given - and the loadout code after it
# searches the inventory for it (a null item, 0x29526C / 0x29559C / ...; Ada's and Wesker's attachment searches at
# 0x295DFC / 0x295EC4 have no bound at all). Measured 2026-11-10: the shapes are the item table at 0xB0C2E0 (0x60-byte
# entries: u16 id, +4 u8 width, +5 u8 height); the live HUNK case (Custom TMP at 0,0, TMP ammo at 4,0, grenades at 6..8,
# spray at 9) is exactly what case_layout gives.
CASE_COLS, CASE_ROWS = 10, 6
ITEM_SHAPE = {                  # id: (width, height) in case cells
    0x01: (1, 2), 0x02: (1, 2), 0x03: (5, 2), 0x04: (2, 1), 0x05: (1, 2), 0x07: (2, 1), 0x0E: (1, 2), 0x18: (2, 1),
    0x20: (2, 1), 0x21: (3, 2), 0x23: (3, 2), 0x25: (4, 2), 0x27: (3, 2), 0x29: (4, 2), 0x2A: (4, 2), 0x2C: (8, 2),
    0x2D: (5, 2), 0x2E: (9, 1), 0x2F: (7, 2), 0x30: (3, 2), 0x34: (7, 3), 0x35: (8, 2), 0x37: (4, 2), 0x3E: (4, 2),
    0x3F: (2, 1), 0x45: (3, 1), 0x52: (7, 3), 0x6D: (8, 2), 0x72: (4, 1), 0x94: (8, 2),
}


def case_layout(items) -> list:
    """[(id, (col, row, turned) or None)] for gives in this order into an empty Mercenaries case, the way 0x3578E0
    places them (None: not given). Items are (id, count) pairs; an id with no measured shape raises."""
    grid = [[False] * CASE_COLS for _ in range(CASE_ROWS)]

    def place(w, h):
        for r in range(CASE_ROWS - h + 1):
            for c in range(CASE_COLS - w + 1):
                if not any(grid[r + y][c + x] for y in range(h) for x in range(w)):
                    for y in range(h):
                        for x in range(w):
                            grid[r + y][c + x] = True
                    return c, r
        return None

    out = []
    for iid, _count in items:
        if iid not in ITEM_SHAPE:
            raise ValueError(f"no case shape for item {iid:#x} ({name(iid)})")
        w, h = ITEM_SHAPE[iid]
        at = place(w, h)
        if at is not None:
            out.append((iid, (at[0], at[1], False)))
            continue
        at = place(h, w) if w != h else None
        out.append((iid, (at[0], at[1], True) if at is not None else None))
    return out


def merc_gives(ch: int, ids) -> list:
    """Character ch's Mercenaries gives in the loadout's order with its LOADOUT_SLOTS weapons replaced by ids (None
    keeps a slot's own)."""
    stock = MERC_LOADOUTS[ch]["items"]
    items = list(stock)
    for slot, iid in zip(LOADOUT_SLOTS.get(ch, ()), ids):
        if iid is not None:                       # the slot's place in the stock order (not in the list being edited)
            items[next(n for n, (i, _) in enumerate(stock) if i == slot["id"])] = (iid, 1)
    return items


def case_fits(items) -> bool:
    """Does every give of this list find room in the case (so none is silently left out)?"""
    return all(at is not None for _, at in case_layout(items))


def movz_w(rd: int, imm: int) -> int:
    """The AArch64 word of MOVZ Wd, #imm16 (shift 0)."""
    if not (0 <= rd < 31 and 0 <= imm <= 0xFFFF):
        raise ValueError("movz w: register 0..30, immediate 0..0xffff")
    return 0x52800000 | (imm << 5) | rd


def movz_imm(word: int):
    """(register, immediate) of a MOVZ Wd, #imm16 word, or None for any other instruction."""
    if (word & 0xFFE00000) != 0x52800000:
        return None
    return word & 31, (word >> 5) & 0xFFFF


def cmp_w(rn: int, imm: int) -> int:
    """CMP Wn, #imm12 (SUBS WZR, Wn, #imm)."""
    if not (0 <= rn < 31 and 0 <= imm <= 0xFFF):
        raise ValueError("cmp w: register 0..30, immediate 0..0xfff")
    return 0x7100001F | (imm << 10) | (rn << 5)


def mov_full_mask(rd: int) -> int:
    """MOV Wd, #0x7ffff (ORR Wd, WZR, #0x7ffff: nineteen ones)."""
    return 0x32000000 | (18 << 10) | (31 << 5) | rd


def and_full_mask(rd: int, rn: int) -> int:
    """AND Wd, Wn, #0x7ffff."""
    return 0x12000000 | (18 << 10) | (rn << 5) | rd


def slot_words(slot: dict, iid: int | None) -> list:
    """[(module offset, the build's word, the word for this weapon)] of one loadout slot; iid None (or the slot's own
    weapon at its own levels) gives every original word back."""
    out = []
    lv = max_levels(iid) if iid is not None and iid != slot["id"] else None
    if iid is not None and iid != slot["id"] and lv is None:
        raise ValueError(f"no max-level row for weapon {iid:#x} ({name(iid)})")
    for off, role, orig in slot["code"]:
        if lv is None:
            new = orig
        elif role == "give":
            new = movz_w(0, iid)
        elif role == "find":
            new = cmp_w(10, iid)
        elif role == "levels":
            new = movz_w(8, lv["packed"])
        elif role == "first_mag":
            new = movz_w(1, min(lv["capacity"] + 1, EXCLUSIVE + 1))
        elif role == "mask_mov":
            new = mov_full_mask(8)
        elif role == "mask_and":
            new = and_full_mask(orig & 31, (orig >> 5) & 31)
        else:
            raise ValueError(f"loadout role {role!r}")
        out.append((off, orig, new))
    return out


def slot_word_ok(role: str, orig: int, cur: int) -> bool:
    """Is `cur` at a site of this role the build's own word or one slot_words writes there (any weapon)? Anything else
    is another build's code: never written."""
    if cur == orig:
        return True
    if role == "give":
        got = movz_imm(cur)
        return got is not None and got[0] == 0
    if role == "find":
        return (cur & ~(0xFFF << 10)) == (orig & ~(0xFFF << 10))
    if role in ("levels", "first_mag"):
        got = movz_imm(cur)
        return got is not None and got[0] == (8 if role == "levels" else 1)
    if role == "mask_mov":
        return cur == mov_full_mask(8)
    if role == "mask_and":
        return cur == and_full_mask(orig & 31, (orig >> 5) & 31)
    return False


def name(iid: int) -> str:
    return NAMES.get(iid, f"item 0x{iid:02X}")


# --- levels ------------------------------------------------------------------------------------------------------
def levels_unpack(v: int) -> dict:
    """The u16 at item+6 -> the four 0-based level nibbles."""
    return {"firepower": v & 15, "firing_speed": (v >> 4) & 15, "reload": (v >> 8) & 15, "capacity": (v >> 12) & 15}


def levels_pack(firepower: int, firing_speed: int, reload: int, capacity: int) -> int:
    for n in (firepower, firing_speed, reload, capacity):
        if not 0 <= n <= 15:
            raise ValueError("a level nibble is 0..15")
    return firepower | firing_speed << 4 | reload << 8 | capacity << 12


def max_levels(iid: int, exclusive: bool = True) -> dict:
    """The highest levels the shop sells for this weapon (nibble = count - 1); with `exclusive`, firepower 6 (the
    exclusive column, as the game itself gives Wesker's handgun and Ada's Punisher) and capacity 6 where the weapon has
    an exclusive capacity. None for an id with no max-level row."""
    counts = MAX_LEVELS.get(iid)
    if counts is None:
        return None
    fp, fs, rl, cap = (max(0, c - 1) for c in counts)
    if exclusive:
        fp = EXCLUSIVE
        if iid in EXCLUSIVE_CAPACITY:
            cap = EXCLUSIVE
    return {"firepower": fp, "firing_speed": fs, "reload": rl, "capacity": cap,
            "packed": levels_pack(fp, fs, rl, cap)}


# --- the static tables, decoded from bytes read out of the running game ------------------------------------------------
def decode_weapon_table(blob: bytes) -> dict:
    """WEAPON_TBL bytes (WEAPON_N x WEAPON_SZ) -> {id: row}; the first row of an id wins (the game's lookups are a
    switch that maps each id to one row)."""
    out = {}
    for k in range(len(blob) // WEAPON_SZ):
        iid, b2, cls, var, b5, ammo = struct.unpack_from("<HBBBBH", blob, k * WEAPON_SZ)
        caps = struct.unpack_from("<7H", blob, k * WEAPON_SZ + 8)
        out.setdefault(iid, {"row": k, "id": iid, "class": cls, "variant": var, "ammo": ammo, "capacity": caps,
                             "b2": b2, "b5": b5})
    return out


def decode_max_levels(blob: bytes) -> dict:
    out = {}
    for k in range(len(blob) // MAX_LEVEL_SZ):
        iid, fp, fs, rl, cap = struct.unpack_from("<HBBBB", blob, k * MAX_LEVEL_SZ)
        out.setdefault(iid, (fp, fs, rl, cap))
    return out


def decode_f32_rows(blob: bytes, cols: int) -> list:
    n = len(blob) // (4 * cols)
    return [struct.unpack_from("<%df" % cols, blob, r * 4 * cols) for r in range(n)]


def capacity(row: dict, nibble: int, difficulty: int | None = None):
    """A weapon row's magazine at a capacity nibble, the way the game's 0x293C90 / 0x2997E0 read it: None for infinite
    (0x8000), doubled when the difficulty byte is 0 or 1 (inferred meaning)."""
    if not 0 <= nibble < 7:
        raise ValueError("capacity nibble 0..6")
    v = row["capacity"][nibble]
    if v == CAP_INFINITE:
        return None
    return v * 2 if difficulty is not None and difficulty <= 1 else v


def fire_interval_frames(fire_rows: list, cls: int, firing_speed: int) -> float:
    """FIRE_RATE_TBL[class][nibble] - the frames the handgun-style gate waits; the seconds are this / FPS."""
    return fire_rows[cls][firing_speed]


def gate_frame(fr: float) -> int:
    """The shot-motion frame 0x31E060 waits for: int(FR) - 2 (fcvtzs, sub #2). Below 1 the crossing never happens."""
    return int(fr) - GATE_LEAD


# The bow and the throwables (the operator 2026-11-10, coaching note #9508 while Krauser played: "fire the bow 20x
# faster"). They have no row that counts: FIRE_RATE_TBL's class 0x1C and the grenades' rows are not what paces them.
# Their rate is the FIRE STATE's motion (static, main.bin against the GameCube decompilation's pl_bow.cpp /
# pl_grenade.cpp): the player's routine bytes P_ROUTINE (r_no 0..3) read 00 06 02 xx while the weapon fires - Switch
# 0x3143B0 is the bow's fire step 1 (wep28_r3_fire10): PlWepLockCtrl, MotionCheckCrossFrame(+0x228, 16.0) takes the
# next arrow in hand, (35.0 from rodata 0x6E89CC) nocks it, and motionMove's end (0x2B6400) writes 00 06 01 00 (the
# set state: the next trigger fires) - so the time between arrows is that motion's length. The motion advances by
# frame += speed x pG's frame step (0x2B8F10: `ldr s1, [x0, #0xdc]` = P_MOTION_SPEED, the unit's +0x304), and the
# game's own 0x317FA0 sets the player's +0x304 AND his weapon object's +0x304 together (the bow's string and arrow
# have a motion of their own); motionMove (0x2B7C60) copies the player's +0x304 into the motion it drives
# (`ldr w9, [x19, #0x304]; str w9, [x8, #0xdc]`), and the three-way shot motion's set (mot3.set, 0x318F50) never
# touches it, so a speed written once holds through the shots that follow. So the weapon routine's motions played x the fire_rate multiplier are the bow fired that
# much faster (re4_switch_mods._motion_rate): the whole routine (r_no_1 6: the draw, the set, the fire, the holster),
# not the fire step alone - the snapshots come every 50 ms, so a speed written only once the fire step is seen would
# leave each shot's first frames at the game's pace; the set state's aim idle played fast changes nothing. Written as
# the routine starts, put back (to what it read) as it ends. Data only. The grenades follow the same routine layout in
# the decompilation (wep19: 0 ready, 1 set, 2 fire, 3 down, 4 next) and on Switch a five-entry state table is
# dispatched by r_no_2 (+0x116) at 0x3144A0 (its fire entry 0x314890 dispatching r_no_3 in turn); which class each
# table belongs to is not traced - with another layout the class / routine test simply never matches.
MOTION_RATE_CLASSES = {0x1C: "bow", 0x13: "hand grenade", 0x16: "incendiary grenade", 0x17: "flash grenade"}
#: Krauser's Bow, the item the bow class (0x1C) maps from (CLASS_OF[0x52] = 0x1C). _bow_in_hand accepts either, so
#: the 20 ms arrow path never depends on one class byte reading right.
BOW_ITEM = 0x52
ROUTINE_WEAPON, R2_FIRE = 6, 2          # r_no_1 6: the weapon routine; r_no_2 2: its fire state (pl_bow / pl_grenade)
OBJ_MOTION_SPEED = 0x304                # the weapon object's own motion speed (cModel + 0x304: 0x317FA0 writes it)
MOTION_SPEED_SANE = (0.05, 30.0)        # a speed outside this is not a motion's speed
ARROWS, ARROWS_MAX = 0x72, 99


def motion_rate_kind(cls, routine) -> str | None:
    """The MOTION_RATE_CLASSES kind when the class in hand is one of them AND the routine bytes are its weapon
    routine (r_no_0 0, r_no_1 ROUTINE_WEAPON: drawn, set, firing or holstering)."""
    if not isinstance(cls, int) or isinstance(cls, bool) or cls not in MOTION_RATE_CLASSES or not routine \
            or len(routine) < 3:
        return None
    return MOTION_RATE_CLASSES[cls] if routine[0] == 0 and routine[1] == ROUTINE_WEAPON else None


def rapid_fire_value(fr: float, mult: float) -> float:
    """A planning helper (no write): FR / mult kept at or above RAPID_FIRE_FLOOR, the last value the gate still sees."""
    if mult < 1:
        raise ValueError("multiplier >= 1")
    return max(RAPID_FIRE_FLOOR, fr / mult) if fr > RAPID_FIRE_FLOOR else fr


# --- the item records ------------------------------------------------------------------------------------------------
def decode_item(b: bytes, addr: int | None = None) -> dict:
    """One 14-byte item: +0 u16 id, +2 u16 count (stack size), +4 u8 flags (bit 0 in use), +5 u8 owner, +6 u16 levels,
    +8 u16 (bit 0: the magazine-empty flag; bits 3..15: rounds loaded), +0xA u8 x, +0xB u8 y (its place in the case),
    +0xC u8, +0xD u8 (1 = placed in the case)."""
    if len(b) < ITEM_SZ:
        raise ValueError("an item is 14 bytes")
    iid, count, flags, owner, levels, w8, x, y, b12, b13 = struct.unpack_from("<HHBBHHBBBB", b)
    return {"addr": addr, "id": iid, "name": name(iid), "count": count, "in_use": bool(flags & 1), "owner": owner,
            "levels_raw": levels, "levels": levels_unpack(levels), "loaded": w8 >> 3, "empty": bool(w8 & 1),
            "x": x, "y": y, "b12": b12, "in_case": b13}


def decode_items(blob: bytes, base: int | None = None, owner: int | None = None) -> list:
    """The item array -> the items in use (optionally only one owner's, as the game's own searches do)."""
    out = []
    for k in range(len(blob) // ITEM_SZ):
        it = decode_item(blob[k * ITEM_SZ:(k + 1) * ITEM_SZ], None if base is None else base + k * ITEM_SZ)
        if it["in_use"] and (owner is None or it["owner"] == owner):
            it["slot"] = k
            out.append(it)
    return out


# --- the live reader -------------------------------------------------------------------------------------------------
class Reader:
    """Read-only views over the running game: `rd(address, n) -> bytes` (the session adapter's read_memory, or
    re4_switch's Mem.rd) and the module base."""

    def __init__(self, rd, base: int):
        self.rd, self.base = rd, base

    def _u(self, fmt: str, a: int):
        return struct.unpack("<" + fmt, self.rd(a, struct.calcsize("<" + fmt)))[0]

    def game_obj(self) -> int:
        """The game state's address, through the pointer variable (expect base + GAME_OBJ)."""
        return self._u("Q", self.base + GAME_PTR_VAR)

    def game_state(self) -> dict:
        g = self.game_obj()
        blob = self.rd(g + G_MONEY, G_RELOAD - G_MONEY + 1)
        at = lambda off: blob[off - G_MONEY]
        flags = self._u("I", g + G_FLAGS)
        return {"game_obj": g, "fixed": g == self.base + GAME_OBJ, "flags": flags, "mercenaries": bool(flags & MERCS_FLAG),
                "frame_step": self._u("f", g + G_FRAME_STEP), "difficulty": self._u("B", g + G_DIFFICULTY),
                "hp": struct.unpack_from("<H", blob, G_HP - G_MONEY)[0],
                "hp_max": struct.unpack_from("<H", blob, G_HP_MAX - G_MONEY)[0],
                "character": CHARACTERS.get(at(G_CHARACTER), at(G_CHARACTER)),
                "weapon": {"class": at(G_CLASS), "variant": at(G_VARIANT), "empty": bool(at(G_EMPTY)),
                           "firepower": at(G_FIREPOWER), "firing_speed": at(G_FIRING_SPEED),
                           "capacity": at(G_CAPACITY), "reload": at(G_RELOAD)}}

    def items(self, owner: int | None = None) -> list:
        mgr = self.base + ITEM_MGR
        arr, n = self._u("Q", mgr + M_ITEMS), self._u("i", mgr + M_SLOTS)
        if not arr or not 0 < n <= 4096:
            return []
        own = self._u("B", mgr + M_OWNER) if owner is None else owner
        return decode_items(self.rd(arr, n * ITEM_SZ), arr, own)

    def equipped(self) -> dict | None:
        mgr = self.base + ITEM_MGR
        ptr, iid = self._u("Q", mgr + M_EQUIPPED), self._u("H", mgr + M_EQUIPPED_ID)
        if not ptr or iid == NO_WEAPON:
            return None
        it = decode_item(self.rd(ptr, ITEM_SZ), ptr)
        it["held_id"] = iid
        return it

    def tables(self) -> dict:
        b = self.base
        return {"weapons": decode_weapon_table(self.rd(b + WEAPON_TBL, WEAPON_N * WEAPON_SZ)),
                "max_levels": decode_max_levels(self.rd(b + MAX_LEVEL_TBL, MAX_LEVEL_N * MAX_LEVEL_SZ)),
                "fire_rate": decode_f32_rows(self.rd(b + FIRE_RATE_TBL, N_CLASSES * 4 * FIRE_RATE_COLS), FIRE_RATE_COLS),
                "reload": decode_f32_rows(self.rd(b + RELOAD_TBL, N_CLASSES * 4 * RELOAD_COLS), RELOAD_COLS),
                "firepower": decode_f32_rows(self.rd(b + FIREPOWER_TBL, N_CLASSES * 4 * FIREPOWER_COLS),
                                             FIREPOWER_COLS),
                "rifle_fire": decode_f32_rows(self.rd(b + RIFLE_FIRE_TBL, 2 * 4 * FIRE_RATE_COLS), FIRE_RATE_COLS)}

    def player_fire(self, player: int) -> dict:
        """The player unit's fields the fire gates use (player = the unit address re4_switch reads)."""
        r = self.rd(player + P_ROUTINE, 4)
        return {"routine": tuple(r), "motion_frame": self._u("f", player + P_MOTION_FRAME),
                "motion_prev": self._u("f", player + P_MOTION_PREV), "motion_speed": self._u("f", player + P_MOTION_SPEED),
                "rifle_timer": self._u("f", player + P_RIFLE_TIMER)}

    def check(self) -> dict:
        """Cheap proof the offsets match the running build: known rows of the tables, the game object fixed, the
        weapon table's ids in their measured classes."""
        t = self.tables()
        w = t["weapons"]
        return {"game_obj_fixed": self.game_obj() == self.base + GAME_OBJ,
                "handgun_class": w.get(0x23, {}).get("class") == CLASS_OF[0x23],
                "classes_match": all(w.get(i, {}).get("class") == c for i, c in CLASS_OF.items()),
                "handgun_fire_rate": [round(x, 3) for x in t["fire_rate"][0x02]] == [14.0, 12.0, 10.0, 10.0, 10.0],
                "handcannon_firepower": round(t["firepower"][0x0F][6], 1) == 99.9,
                "rifle_timer_row": [round(x, 3) for x in t["rifle_fire"][0]] == [20.0] * 5}
