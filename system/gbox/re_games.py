"""Resident Evil game data for gbox/re_mods_tool.py: addresses, code patches, item ids, verified live.

Resident Evil 4, GameCube NTSC-U (G4BE08, Disc 1 and Disc 2 have the same main.dol); RAM 0x80000000, big-endian.
Sources: Action Replay codes decrypted with Dolphin's ARDecrypt (GCNcrypt), Gecko codes (codes.rc24.xyz G4BE08),
static analysis of main.dol (capstone), and live checks on the Spark's Dolphin (GDB stub, breakpoints, watchpoints).

Globals
  pG    = *(u32*)0x802B2280 (r13-0x7500) = 0x8027F7D0  GLOBAL work: +0x4FA4 u32 money (ptas), +0x4FA8 u16 current room
          (0xSSRR: stage, room; e.g. 0x0100 = r100, 0x0400 = Mercenaries village), +0x4FB0 s16 player HP,
          +0x52F4 ESL enemy-set table (255 x 32 bytes: +0 flags (1 = enabled, 2 = spawned), +1 enemy id, +2 type,
          +3 set, +0xC/0xE/0x10 s16 position /10, +0x18 u16 room).
  pSys  = *(u32*)0x802B2284 (r13-0x74FC) = 0x80287E58  system save: +4 u32[] 'extra' bit flags, MSB first
          (bits 4..7 = Mercenaries Ada / HUNK / Krauser / Wesker; byte 0x80287E5C = 0xFF = every extra game).
  ItemMgr 0x802138E0: +0x14 item array (14-byte items: u16 id, u16 count, u8 in_use, u8 owner, u8, u8 level,
          u16 loaded ammo (13 bits), u8 x, u8 y, u8 outside_case, u8 in_case), +0x1C slot count.
  EmMgr 0x8027DF20: +0 slot array (slot 0 = player), +4 count (80), +8 stride (0xDE0). em +0x94 float pos[3],
          +0x398 u8 ESL index.
  Mercenaries: timer u32 at 0x80279308 (frames, 30 fps); combo struct 0x8021392C (+0x28 combo, +0x2C combo timer).
Game routines (called on the game thread by gBox's dispatcher)
  0x80147E6C take_item(id, count, 0)  what picking an item up calls: creates the item and auto-places it in the
                                      attache case; returns 1 when placed, 0 when there is no room.
  0x8001AF74 ItemMgr::count(mgr, id)
"""

GAME_ID = b"G4BE08"

# per-frame dispatcher (low-memory gap 0x80001800-0x80003000 that Dolphin only uses for its Gecko code handler;
# gBox refuses to install if that region holds anything but its own code)
CAVE, QUEUE, HOOKS, VARS, CAVE_END = 0x80002A00, 0x80002E00, 0x80002F00, 0x80002F20, 0x80003000
HOOK_SITE, HOOK_ORIG_TARGET = 0x80122610, 0x80122634     # main loop: `bl 0x80122634` (an empty function) each frame
QN, QSZ, HN = 5, 0x30, 8                                 # queue: {fn, r3..r10, f1, f2, result}

F_TAKE_ITEM = 0x80147E6C
F_ITEM_COUNT = 0x8001AF74
ITEM_MGR = 0x802138E0
P_GLOBAL, P_SYS = 0x802B2280, 0x802B2284
EXTRAS_BYTE = 0x80287E5C
MERC_TIMER = 0x80279308
MERC = 0x8021392C

# name: (address, original word, patched word, what it does) -- original bytes are checked before patching
PATCHES = {
    "infinite_ammo": (0x8001BD14, "a07f0000", "4bfffff8",
                      "ammo-use routine returns 'fired' without consuming (guns, rocket launchers, bow, throwables)"),
    "combo_freeze": (0x8001DD88, "3929ffff", "39290000", "Mercenaries combo countdown never runs: combos never end"),
    "merc_timer_freeze": (0x800C102C, "3809ffff", "38090000", "Mercenaries clock stops counting down"),
    "unlimited_health": (0x800CEC10, "7c1d0050", "60000000", "damage is never subtracted from the player's HP"),
}

# RE4 item ids (ITEM_ID). * = seen in game by gBox (case screen / inventory).
ITEMS = {
    0x00: "Magnum Ammo", 0x01: "Hand Grenade*", 0x02: "Incendiary Grenade", 0x03: "Matilda (weapon data present on GC; class 0x11)", 0x04: "Handgun Ammo*",
    0x05: "First Aid Spray*", 0x06: "Green Herb", 0x07: "Rifle Ammo", 0x08: "Chicken Egg", 0x09: "Brown Chicken Egg",
    0x0A: "Gold Chicken Egg", 0x0C: "Plaga Sample", 0x0D: "Krauser's Knife", 0x0E: "Flash Grenade*",
    0x12: "Green Herb (X2)", 0x13: "Green Herb (X3)", 0x14: "Mixed Herbs (G+R)", 0x15: "Mixed Herbs (G+R+Y)",
    0x16: "Mixed Herbs (G+Y)", 0x17: "Rocket Launcher (Special)", 0x18: "Shotgun Shells*", 0x19: "Red Herb",
    0x1A: "Handcannon Ammo", 0x1C: "Yellow Herb", 0x20: "TMP Ammo", 0x21: "Punisher", 0x22: "Punisher w/ Silencer",
    0x23: "Handgun*", 0x24: "Handgun w/ Silencer", 0x25: "Red9", 0x26: "Red9 w/ Stock", 0x27: "Blacktail",
    0x28: "Blacktail w/ Silencer", 0x29: "Broken Butterfly", 0x2A: "Killer7", 0x2B: "Killer7 w/ Silencer",
    0x2C: "Shotgun", 0x2D: "Striker*", 0x2E: "Rifle", 0x2F: "Rifle (semi-auto)", 0x30: "TMP", 0x31: "TMP (variant 1)", 0x32: "TMP w/ Stock", 0x33: "TMP (variant 3)",
    0x34: "Chicago Typewriter", 0x35: "Rocket Launcher*", 0x36: "Mine Thrower", 0x37: "Handcannon",
    0x38: "Combat Knife", 0x3E: "Custom TMP", 0x3F: "Silencer (Handgun)", 0x40: "Punisher (variant)", 0x41: "P.R.L. 412", 0x51: "Rifle (semi-auto) w/ Infrared Scope", 0x99: "Rifle w/ Infrared Scope", 0x42: "Stock (Red9)", 0x43: "Stock (TMP)",
    0x44: "Scope (Rifle)", 0x45: "Scope (semi-auto)", 0x46: "Mine-Darts", 0x52: "Krauser's Bow",
    0x53: "Chicago Typewriter (Ada)", 0x6A: "Chicago Typewriter Ammo", 0x6B: "Rifle + Scope",
    0x6C: "Rifle (semi-auto) + Scope", 0x6D: "Infinite Launcher", 0x72: "Arrows", 0x7C: "Attache Case S*",
    0x7D: "Attache Case M", 0x7E: "Attache Case L", 0x7F: "Attache Case XL", 0x94: "Riot Gun", 0xA0: "Rifle Ammo (Infrared)",
    0xA8: "Mixed Herbs (R+Y)", 0xAA: "Scope (Mine-thrower)", 0xAB: "Mine-thrower + Scope", 0xAC: "Playing Manual 1*",
    0xAD: "Info on Ashley*", 0xC5: "Infrared Scope", 0xFE: "Tactical Vest",
}
ALIASES = {
    "pistol": 0x23, "handgun": 0x23, "magnum": 0x29, "hand cannon": 0x37, "handcannon": 0x37, "rpg": 0x35,
    "rocket": 0x35, "rocket launcher": 0x35, "infinite rocket launcher": 0x6D, "grenade": 0x01, "frag": 0x01,
    "flashbang": 0x0E, "flash": 0x0E, "incendiary": 0x02, "molotov": 0x02, "tommy gun": 0x34, "typewriter": 0x34,
    "chicago": 0x34, "smg": 0x30, "machine gun": 0x30, "sniper": 0x2F, "sniper rifle": 0x2F, "shotgun ammo": 0x18,
    "shells": 0x18, "pistol ammo": 0x04, "handgun ammo": 0x04, "bullets": 0x04, "spray": 0x05, "first aid": 0x05,
    "herb": 0x06, "bow": 0x52, "mine launcher": 0x36, "knife": 0x38, "vest": 0xFE, "case": 0x7F, "attache case": 0x7F,
    "egg": 0x08, "gold egg": 0x0A, "magnum ammo": 0x00, "tmp ammo": 0x20, "rifle ammo": 0x07,
}


def item_name(i: int) -> str:
    return ITEMS.get(i, f"item 0x{i:02X}").rstrip("*")

# ---- weapons / Mercenaries loadouts (verified live; see re_mods_tool.py) ----
FIRE_RATE_TBL = 0x801ED248   # float[5] per weapon class: frames between shots per firing-speed level (TMP 3, Handcannon 35)
FIREPOWER_TBL = 0x80203B14   # float[7] per weapon class: damage per firepower level (Handcannon 30..60, 99.9 exclusive)
WEAPON_TBL, WEAPON_N, WEAPON_SZ = 0x801DF47C, 43, 22   # {u16 item id, u8, u8 class, u8 variant, u8, u16 ammo item, u16 capacity[6], u16}
N_CLASSES = 0x22
FIRE_RATE_ORIG = bytes.fromhex('3f8000003f8000003f8000003f8000003f80000041600000414000004120000041200000412000004160000041400000412000004120000041200000418000004160000041400000414000004140000041600000414000004100000040c0000040c0000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a80000423800004238000042380000423800004238000041b0000041b0000041b0000041b0000041b0000041a0000041a0000041a0000041a0000041a00000422c0000414000004140000041400000414000004040000040400000404000004040000040400000404000004040000040400000404000004040000042900000429000004290000042900000429000004220000042200000422000004220000042200000420c0000420c0000420c0000420c0000420c000041f8000041f8000041f8000041f8000041f8000041600000414000004120000041200000412000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000041a0000041a0000041a0000041a0000041a000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004238000042380000423800004238000042380000')
FIREPOWER_ORIG = bytes.fromhex('3f8000003f8000003f8000003f8000003f8000003f8000003f8000003f6666663f8ccccd3fa666663fc000003fd9999a3ff333333ff333333f8000003f99999a3fb333333fcccccd3fe6666640000000400000003fb333333fd9999a400000004019999a403333334060000040a000003fcccccd3fe666664000000040133333402ccccd404000004059999a41500000417000004188000041a0000041c0000041e000004248000041c8000041f00000420c0000420c0000420c0000420c0000420c0000408000004090000040a0000040c0000040e00000410000004100000040c0000040e0000041000000411000004120000041400000414000004080000040a0000040c000004100000041200000414000004190000040e000004100000041100000413000004150000041700000417000003ecccccd3f0000003f19999a3f4ccccd3f8000003f99999a3fe66666412000004120000041200000412000004120000041200000412000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000041f00000420c00004220000042340000424800004270000042c7cccd3f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f99999a3fb333333fcccccd3fe6666640000000400000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004120000041200000412000004120000041200000412000004120000040a00000412000004170000041a0000041c800004248000042480000412000004120000041200000412000004120000041200000412000003f8000003f99999a3fb333333fcccccd40000000408000004080000040e000004100000041100000414000004180000042000000420000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000040a0000040b0000040c0000040d0000040e000004100000041200000')
LOAD_SITE, LOAD_FN = 0x8001978C, 0x80018CC4   # Merc start: bl give_merc_loadout(ItemMgr, character)
LOAD_WRAP = 0x80002B00   # runs the game's loadout, then gBox's records {u8 char|0xFF, u8 flags (1 equip, 2 remove one, 4 raw get), u16 id, u16 count}
LOAD_WRAP_CODE = bytes.fromhex('9421ffd07c0802a690010034bf61001c7c7f1b787c9e2378480161ad7c7d1b783f808000639c2f40881c00002c0000fe418200a42c0000ff4182000c7c00f0004082008c8b7c000173600002418200147fe3fb78a09c0002480182394800007073600004418200187fe3fb78a09c0002a0bc00044801799d48000054a07c0002a09c000438a00000481452e5736000014182003c7fe3fb78a09c0002480177952c030000418200287c641b787fe3fb7848018be13d20800061292f24a01c0002b009000038000096b00900023b9c00064bffff587fa3eb78bb61001c800100347c0803a6382100304e800020')
RECS, RECS_END = 0x80002F40, 0x80003000
EQUIP_NOW = 0x80002C00  # equip_now(item*): ItemMgr equip + player weapon swap (class -> pG+0x4FBC/0x4F7C, reload weapon)
EQUIP_NOW_CODE = bytes.fromhex('9421ffe07c0802a690010024bfa100147c7f1b787c641b783c608021606338e048018b71a07f000048019d7d7c7e1b78a07f000048019db9812d8b008ba94fbc9bc94fbc9bc94f7c98694fbd806d98c44813ff91812d8b007fc4f378806d98c488a94fbd48140281806d98c4481402b138600001bba10014800100247c0803a6382100204e800020')
PEND, PEND_HOOK = 0x80002F24, 0x80002C90   # {u16 item, u16 frames}: equip that item once the Merc run is playing
PEND_HOOK_CODE = bytes.fromhex('3d20800061292f24a06900002c030000408200084e800020a08900022c040000418200103884ffffb08900024e800020800d98c42c000000408200084e8000209421fff07c0802a69001001438000000b00900007c641b783c608021606338e0480176412c030000418200084bffff05800100147c0803a6382100104e800020')
GUARD_STUB, GUARD_SITE, GUARD_ORIG = 0x80002D20, 0x800F7180, bytes.fromhex('4181ff8c')
GUARD_CODE, GUARD_BRANCH = bytes.fromhex('408100102c0b000041820008480f43e0480f4454'), bytes.fromhex('4bf0bba0')
# effect-animation loop 0x800F710C..0x800F7180 spins forever when an effect's frame step is 0 - which happens when a
# weapon's effect data is not loaded for the current stage (Handcannon in The Mercenaries froze the game). The guard exits.
CHARACTERS = {'leon': 0, 'ashley': 1, 'ada': 2, 'hunk': 3, 'krauser': 4, 'wesker': 5, 'any': 0xFF, 'all': 0xFF}
MERC_DEFAULT_WEAPONS = {0: [0x27, 0x94], 2: [0x21, 0x30, 0x2F], 3: [0x3E], 4: [0x52], 5: [0x23, 0x2A, 0x2F]}

# items the GameCube build cannot give: no attache-case shape / no weapon-table entry (take_item crashes on them)
NOT_GIVABLE = {0x41: "P.R.L. 412 has no weapon-table entry and no attache-case shape in the GameCube build (giving it crashed "
                     "the take-item routine at 0x8014695C); it is not usable on GC"}
# names from other RE4 releases (2023 remake / PS2) -> the GameCube item, or why it does not exist here
OTHER_NAMES = {"stingray": 0x2F, "sr m1903": 0x2E, "bolt action rifle": 0x2E, "w-870": 0x2C, "chicago sweeper": 0x34,
               "sg-09 r": 0x23, "red 9": 0x25, "tmp": 0x30, "lh": 0x37, "broken butterfly": 0x29, "killer 7": 0x2A,
               "infinite rocket launcher": 0x6D, "riot gun": 0x94, "striker": 0x2D, "mine thrower": 0x36,
               "combat knife": 0x38, "knife": 0x38}
NOT_ON_GC = {"bolt thrower": "2023 remake only", "sentinel nine": "2023 remake DLC only", "skull shaker": "2023 remake DLC only",
             "xm96e1": "2023 remake only", "cqbr": "2023 remake only", "primal knife": "2023 remake only",
             "matilda": "added in the PS2 release; the GC disc has unused weapon data (item 0x03, class 0x11) only",
             "prl 412": NOT_GIVABLE[0x41], "p.r.l. 412": NOT_GIVABLE[0x41], "prl": NOT_GIVABLE[0x41]}
ALIASES.update(OTHER_NAMES)

# ---- enemy spawn multiplier (Mercenaries + story rooms) ----
# Every ESL enemy-set entry of the current room that the game spawns (flag 2) is cloned N-1 times by calling the game's
# own single-entry spawner 0x800CA12C(index, 0) from the per-frame hook, with the entry's x/z nudged by `spread` units
# per copy. The spawner refuses an index whose enemy is alive (0x800C9DE0 check, called at 0x800CA1E4) - gBox replaces
# that call with li r3,1 while the multiplier is on. Bounded by the 80-slot enemy manager (EmMgr 0x8027DF20).
SPAWN_HOOK, SPAWN_VARS, SPAWN_DONE = 0x80002800, 0x80002F28, 0x800029C0     # vars: u8 factor, u8 spread
SPAWN_HOOK_CODE = bytes.fromhex("3d20800061292f28880900002c000002408000084e8000209421ffc07c0802a690010044bee1001c83ed8b003bc0000057dd28343bbd52f47fbdfa1457dcd97e579c103a3d208000612929c07f9c4a1457c906fe3b6000017f7b4830835c00008b3d000073200002408200107f5ad878935c0000480000b07f40d8382c000000408200a47f5adb78935c0000a01d0018a13f4fa87c0048004082008c881d00012c000000418200803d20800061292f288b0900003b18ffff8ae90001ab5d000cab7d00107f5aba14b35d000c7f77d850b37d0010732000fd981d00007fc3f37838800000480c78499b3d00003b18ffff2c1800004181ffd0a81d000c893d00003d20800061292f288b0900003b18ffff7f18b9d67f58d050b35d000c7f7bc214b37d00103bde00012c1e00ff4180ff04bae1001c800100447c0803a6382100404e800020")
SPAWN_DUP_SITE, SPAWN_DUP_ORIG, SPAWN_DUP_PATCH = 0x800CA1E4, bytes.fromhex("4bfffbfd"), bytes.fromhex("38600001")

# ---- explosions (the game's own detonation sequences, called on the game thread) ----
# hand grenade detonation 0x8003B5FC / flash grenade 0x8003BBFC: effect 0x80103C38(0,-1,pos,0,0,id) + sound 0x80055944 +
# area attack 0x80142FE8(0, pos, pos, class, 0, radius) (class 0x13 grenade / 0x17 flash, radius floats 0x801E0B7C / 0x801E0BA4)
GRENADE_AT, FLASH_AT = 0x80002500, 0x80002600            # (vec3* pos)
GRENADE_AT_CODE = bytes.fromhex("9421ffd07c0802a690010034bfc100287c7e1b7838000000900100089001000c386000003880ffff7fc5f37838c0000038e000003900000d3920000039400000481016f938600001388000147fc5f37838c0000038e0000039000000480533e93d20801ec0290b7c386000007fc4f3787fc5f37838c0001338e0000048140a6d38600001bbc10028800100347c0803a6382100304e800020")
FLASH_AT_CODE = bytes.fromhex("9421ffd07c0802a690010034bfc100287c7e1b7838000000900100089001000c386000003880ffff38a0000038c0000038e000003900003f3920000039400000481015f938000000900100089001000c386000003880ffff7fc5f37838c0000038e000003900000c3920000039400000481015c938600001388000137fc5f37838c0000038e0000039000000480532b93d20801ec0290ba4386000007fc4f3787fc5f37838c0001738e000004814093d38600001bbc10028800100347c0803a6382100304e800020")
PERIODIC, PVARS = 0x800026D0, 0x80002F2C                 # PVARS: u16 period (frames, 30/s), u16 counter, u32 routine
PERIODIC_CODE = bytes.fromhex("3d20800061292f2ca00900002c000000408200084e800020a0890002388400017c0400004080000cb08900024e80002038800000b0890002806d98c42c030000408200084e800020814d8b00880a00202c000003418200084e800020818900047d8903a6386300944e800420")
BLAST_POS = 0x80002EF0                                   # vec3 scratch for one-shot blasts
# bullet impacts: the attack routine calls the impact-effect fn 0x80104604(hitpos, normal, material, class) at 0x80143364;
# gBox wraps it and also detonates a grenade at the hit point for weapon classes set in BOOM_MASK (bit = class).
IMPACT_WRAP, IMPACT_SITE, IMPACT_ORIG, IMPACT_BRANCH = 0x80002400, 0x80143364, bytes.fromhex("4bfc12a1"), bytes.fromhex("4bebf09d")
IMPACT_WRAP_CODE = bytes.fromhex("9421ffe07c0802a690010024bfc100187c7f1b787cde3378481021ed281e001f4181002c3d20800061292f3480090000394000017d4af0307c0050382c0000004182000c7fe3fb78480000b9bbc10018800100247c0803a6382100204e800020")
BOOM_MASK = 0x80002F34
LAST_HIT = 0x4F3C                                        # pG+: last bullet/blast hit position (vec3)


# ---- item catalogue for the Ctrl+click picker / loadout pop-up (profiles/gamedata/<game_id>-items.json) ----
def item_kind(i: int) -> str:
    n = ITEMS.get(i, "").lower()
    if "ammo" in n or "shells" in n or "arrows" in n or "mine-darts" in n:
        return "ammo"
    if "grenade" in n:
        return "grenade"
    if "herb" in n or "spray" in n or "egg" in n:
        return "healing"
    if "case" in n or "vest" in n or "scope" in n or "stock" in n or "silencer" in n:
        return "other"
    if "manual" in n or "info" in n or "sample" in n:
        return "key"
    return "weapon"


# items the other RE4 releases add (PS2 2005 / Wii 2007 / PC UHD 2014 / X360 HD 2011 all carry the PS2 additions)
PS2_EXTRA = {0x03: "Matilda", 0x41: "P.R.L. 412"}


def items_catalog(platform: str = "gamecube") -> dict:
    out = []
    for i, n in sorted(ITEMS.items()):
        name = (PS2_EXTRA.get(i) if platform != "gamecube" else None) or n.rstrip("*")
        if platform == "gamecube" and i in NOT_GIVABLE:
            continue
        out.append({"name": name, "id": f"0x{i:02X}", "kind": item_kind(i) if i not in PS2_EXTRA else "weapon"})
    return {"game": "Resident Evil 4", "platform": platform, "items": out,
            "note": "ids are RE4's ITEM_ID values (same on GC/Wii/PS2/PC; re_mods give/replace/merc_loadout take names or ids)"}


# ---- per-release tables ---------------------------------------------------------------------------------------------
# GLOBAL work field offsets and other GC values used by re_mods_tool (the GC build's values are the module defaults)
G_MONEY, G_ROOM, G_HP = 0x4FA4, 0x4FA8, 0x4FB0
P_PLAYER = 0x802B9780 - 0x673C                           # *(u32*) = player em (pos at +0x94)
EXTRAS_OFF = 4                                           # pSys + 4: u32 unlock bits (byte 0 = extra games + Merc
                                                         # characters/stages, byte 1 bits = Professional ...)
# every Mercenaries time pickup goes through pG+0x4F7E (u16 seconds; hourglass item count): the clock routine adds
# seconds * 30 frames with this mulli, so changing its immediate scales every time bonus (RE4 has no melee time bonus)
TIME_BONUS_MUL = (0x800C0FE8, 0x1D290000, 30)            # mulli r9,r9,30
FPS = 30


class Version:
    """One RE4 release's addresses: overrides, else the GameCube values above. None = not located in that build yet."""

    def __init__(self, name: str, over: dict):
        self.name, self.over = name, over

    def __getattr__(self, k):
        if k in ("name", "over"):
            raise AttributeError(k)
        if k in self.over:
            v = self.over[k]
            if v is None:
                from .registry import Unsupported
                raise Unsupported(f"re_mods: {k} is not located in {self.name} yet (works on the GameCube release; "
                                  "see docs/mercenaries.md)")
            return v
        try:
            return globals()[k]
        except KeyError:
            raise AttributeError(k) from None

    def has(self, k) -> bool:
        return k not in self.over or self.over[k] is not None


GC = Version("Resident Evil 4 (GameCube NTSC-U, G4BE08)", {})
# Resident Evil 4: Wii Edition - the operator's image is the PAL disc RB4P08 (English). Found by Gecko codes (RB4P08 on
# codes.rc24.xyz: money/HP), gBox's GC tables matched in the Wii main.dol (fire-rate/firepower/weapon tables), a fuzzy
# function matcher GC->Wii (instruction-class + immediate + field-offset bags; the GC clock routine 0x800C0F20 ->
# Wii 0x80090490) and watchpoints on the Spark's Dolphin (the clock decrement 0x800905A4). Verified live 2026-10-07.
WII_PAL = Version("Resident Evil 4: Wii Edition (PAL RB4P08)", {
    "GAME_ID": b"RB4P08",
    "P_GLOBAL": 0x8043D3E0, "P_SYS": 0x8043D3E4,         # r13-0x7480 / r13-0x747C (r13 = 0x80444860)
    "EXTRAS_BYTE": None,                                 # read through P_SYS (pSys + 4) on every release
    "G_MONEY": 0x4FA8, "G_ROOM": 0x4FAC, "G_HP": 0x4FB4,
    "MERC_TIMER": 0x80329408, "MERC": None,
    "TIME_BONUS_MUL": (0x8009055C, 0x1C600000, 30),      # mulli r3,r0,30
    "PATCHES": {
        "merc_timer_freeze": (0x800905A0, "3803ffff", "38030000", "Mercenaries clock stops counting down"),
        "unlimited_health": (0x8009FD10, "7c1e0050", "60000000", "damage is never subtracted from the player's HP"),
    },
    "FIRE_RATE_TBL": 0x802BAAC8, "FIREPOWER_TBL": 0x802D1FC8, "WEAPON_TBL": 0x802AF750, "N_CLASSES": 0x31,
    "FIRE_RATE_ORIG": bytes.fromhex("3f8000003f8000003f8000003f8000003f80000041600000414000004120000041200000412000004160000041400000412000004120000041200000418000004160000041400000414000004140000041600000414000004100000040c0000040c0000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a8000041a800004238000042380000423800004238000042380000420400004204000042040000420400004204000042a4000042a4000042a4000042a4000042a40000425c000041c0000041c0000041c0000041c000004040000040400000404000004040000040400000404000004040000040400000404000004040000042900000429000004290000042900000429000004220000042200000422000004220000042200000420c0000420c0000420c0000420c0000420c000041f8000041f8000041f8000041f8000041f8000041600000414000004120000041200000412000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000041a0000041a0000041a0000041a0000041a000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000042380000423800004238000042380000423800003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004160000041400000412000004120000041200000404000004040000040400000404000004040000041a0000041a0000041a0000041a0000041a000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f800000418000004180000041800000418000004180000041800000418000004180000041800000418000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004292000042920000429200004292000042920000"),
    "FIREPOWER_ORIG": bytes.fromhex("3f8000003f8000003f8000003f8000003f8000003f8000003f8000003f6666663f8ccccd3fa666663fc000003fd9999a3ff333333ff333333f8000003f99999a3fb333333fcccccd3fe6666640000000400000003fcccccd3fe66666400666664020000040400000406ccccd40d000003fcccccd3fe666664000000040133333402ccccd404ccccd4090000041500000417000004188000041a0000041c0000041e000004248000041c8000041f00000420c0000420c0000420c0000420c0000420c0000408000004090000040a0000040c0000040e00000410000004100000040c0000040e0000041000000411000004120000041400000414000004080000040a0000040c0000041000000412000004140000041f0000040e000004100000041100000413000004150000041700000417000003ecccccd3f0000003f19999a3f4ccccd3f8000003f99999a3fe66666412000004120000041200000412000004120000041200000412000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000041f00000420c00004220000042340000424800004270000042c7cccd3f8000003f8000003f8000003f8000003f8000003f8000003f8000003fc000003fd9999a3ff33333400666664013333340200000402000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004120000041200000412000004120000041200000412000004120000040a00000412000004170000041a0000041c800004248000042480000412000004120000041200000412000004120000041200000412000003f8000003f99999a3fb333333fcccccd40000000408000004080000040e000004100000041100000414000004180000042000000420000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000040a0000040b0000040c0000040d0000040e0000041000000412000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004080000040a0000040c00000410000004120000041400000419000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f80000041c8000041f00000420c0000420c0000420c0000420c0000420c00003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000003f8000004184cccd4184cccd4184cccd4184cccd4184cccd4184cccd4184cccd"),
    "NOT_GIVABLE": {},
    # the per-frame dispatcher (give/equip/loadouts/blasts/spawns) needs the Wii main-loop hook + routines: not ported
    "HOOK_SITE": None, "ITEM_MGR": None, "P_PLAYER": None, "SPAWN_HOOK": None, "GRENADE_AT": None, "LOAD_SITE": None,
    "MELEE_CODE": None, "AIM_TURN": None,
})
VERSIONS = {GC.GAME_ID: GC, WII_PAL.GAME_ID: WII_PAL}


# ---- melee / spin mods (GC): player-owned blasts, explosive + super melee, auto-spin -----------------------------
# Built with scripts/re4gc_cave_build.py (keystone; sources there). Cave 0x80001800-0x80001FFF (Dolphin's Gecko area,
# unused by gBox otherwise); vars at MELEE_VARS:
#   +0 u32 melee class mask (bit = attack class: knife 0x10)   +4 u8 blast (0 grenade, 1 flash, 2 rocket, FF off)
#   +5 u8 grenade-path class (0x13 grenade, 0x0D rocket)        +6 u8 launch on   +7 u8 blast where the launched enemy lands
#   +8 f32 blast radius  +C f32 launch up speed  +10 f32 launch away speed  +14 f32 gravity (units/frame, 30 fps)
#   +18 f32 spin radians/frame  +1C u8 spin mode (0 off, 1 while the button mask is held, 2 always)  +1E u16 pad mask
#   +20 f32 pi  +24 f32 2pi  +28 f32 1.0  +2C f32 0.0  +30 u32 launch frames limit  +40 4 launch slots x 0x1C
#   {em, frames, vx, vy, vz, y, ground y}
# Evidence (2026-10-07, Spark Dolphin): a blast whose attack owner (r3 of the attack routine 0x80142FE8) is the player
# em damages enemies but not the player (HP 1632 -> 1632; the same blast with owner 0: 1632 -> 912); knife hits go
# through the impact-effect call 0x80143364 with attack class 0x10 (a mask bit made every slash explode); an enemy's
# y written every frame from the dispatcher hook is drawn there (enemy lifted to y+30000 and landed 2.5 s later).
MELEE_VARS = 0x80001F00
MELEE_CODE = {
    "OWNED_GRENADE": (0x80001800, bytes.fromhex("9421ffd07c0802a690010034bfc100287c7e1b7838000000900100089001000c386000003880ffff7fc5f37838c0000038e000003900000d3920000039400000481023f938600001388000147fc5f37838c0000038e0000039000000480540e93d208000c0291f08806d98c47fc4f3787fc5f37888c91f0538e000004814176d38600001bbc10028800100347c0803a6382100304e800020")),
    "OWNED_FLASH": (0x800018A0, bytes.fromhex("9421ffd07c0802a690010034bfc100287c7e1b7838000000900100089001000c386000003880ffff38a0000038c0000038e000003900003f39200000394000004810235938000000900100089001000c386000003880ffff7fc5f37838c0000038e000003900000c39200000394000004810232938600001388000137fc5f37838c0000038e0000039000000480540193d20801ec0290ba4806d98c47fc4f3787fc5f37838c0001738e000004814169d38600001bbc10028800100347c0803a6382100304e800020")),
    "OWNED_BLAST": (0x80001970, bytes.fromhex("3d20800088091f042c000001408200084bffff204bfffe7c")),
    "MELEE_WRAP": (0x80001990, bytes.fromhex("9421ffe07c0802a690010024bfc100187c7f1b787cde337848102c5d281e001f41810070394000017d4af0303d20800080092f347c005039418200107fe3fb7848000b314800004c80091f007c0050394182004088091f062c0000004182001c7fe3fb784800004d3d20800088091f072c0000004082001c3d20800088091f042c0000ff4182000c7fe3fb784bffff55bbc10018800100247c0803a6382100204e800020")),
    "LAUNCH_START": (0x80001A40, bytes.fromhex("9421ffc07c0802a690010044bf2100207c7f1b783d20802883c9df2083a9df248389df283b6000003c0048746000240090010010c1a100103b4000017c1ae8004080006c7f3ae1d67f39f214801900007000060141820050881903982c0000ff41820044c0190094c03f0000ec000828ec400032c0190098c03f0004ec000828ec40103ac019009cc03f0008ec000828ec40103afc0268004080000cfda010907f3bcb783b5a00014bffff942c1b0000418200dc3d20800061291f403b4000043b200000800900042c00000041820014800900007c00d800418200b4480000102c190000408200087d394b783929001c375affff4082ffd02c19000041820090812d98c42c0900004182008493790000c01b0094c0290094ec600828c01b009cc029009cec800828eca300f2eca4293a3d208000c0091f28fc05000040800014c0691f2cc0891f2cfcc0189048000008fcc02834ec6301b2ec8401b2c0091f10ec630032ec840032d0790008c0091f0cd019000cd0990010c01b0098d0190014d019001880091f3090190004bb210020800100447c0803a6382100404e800020")),
    "LAUNCH_HOOK": (0x80001BE0, bytes.fromhex("9421ffd07c0802a690010034bf810020812d8b00880900202c000003408200d03fe0800063ff1f403bc00004819f00042c0c0000418200ac398cffff919f000483bf0000801d0000700006014182008cc01f0014c03f000cec00082ad01f00143d208000c0491f14ec211028d03f000cc07d0094c09f0008ec63202ad07d0094c07d009cc09f0010ec63202ad07d009cc0bf0018fc00280040800028d0bd009838000000901f000488091f072c00000041820030387d00944bfffcd948000024d01d0098801f00042c00000040820014d0bd00984800000c38000000901f00043bff001c37deffff4082ff44bb810020800100347c0803a6382100304e800020")),
    "SPIN_HOOK": (0x80001D00, bytes.fromhex("3d20800088091f1c2c0000004d820020814d8b00896a00202c0b00034c8200202c0000024182001c3d608028a16b7e9ea1891f1e7d6b60387c0b60004c820020814d98c42c0a00004d820020c00a00a4c0291f18ec00082ac0491f20fc0010004081000cc0691f24ec001828d00a00a44e800020")),
}
MELEE_CLASSES = {"knife": 0x10}          # player melee attack classes seen hitting through the impact path
PAD_HELD = 0x80287E9E                    # u16 held buttons (A 0x100, B 0x200, R 0x20, L 0x40, Z 0x10)
# aim turning (analog stick while aiming, 0x8014415C): yaw/pitch step = stick * sens * K / 200 / 10 / 20 with K = pi
# at 0x801ED930 (only that routine reads it); 0x801ED938 = pi/80 (the fixed step); scaled by aim_turn_speed.
AIM_TURN = ((0x801ED930, 3.1415927410125732), (0x801ED938, 0.039269909262657166))
HOOK_SLOT_LAUNCH, HOOK_SLOT_SPIN = 3, 4


# ---- #511 / #512: Mercenaries combo window, grenades that never hurt the player -------------------------------------
# Every address gBox added for these tickets, per release, with where it came from. live_checked stays False until
# someone checks it in the running game (docs/mercenaries.md "Live checks" has the exact steps); the tool reports it.
MERC_ADDRESS_TABLE = {
    "G4BE08": {
        "COMBO_WINDOW": {
            "address": 0x802B17F0, "size": 4, "original": 300,
            "what": "Mercenaries combo window in frames (s32, .sdata, 300 = 10 s at 30 fps): every kill after the first "
                    "reloads the combo timer (combo struct 0x8021392C +0x2C) from it",
            "source": "static analysis of the G4BE08 main.dol: its only reader is lwz r9,-0x7F90(r13) at 0x8001EF38 "
                      "(r13 = 0x802B9780), stored to +0x2C of the combo struct at 0x8001EF40 by the add-kill routine "
                      "0x8001EEA8; the countdown is the addi r9,r9,-1 at 0x8001DD88 (gBox's combo_freeze). Jay007's Gecko "
                      "code 'Infinite Combo Time (Mercenaries Mode)' 0401EF40 60000000 patches that same store",
            "confidence": "high (single reader, cross-checked with a published Gecko code)",
            "live_checked": False},
        "GRENADE_OWNER_A": {
            "address": 0x8003B7BC, "size": 4, "original": "38600000", "patched": "806d98c4",
            "what": "hand-grenade blast (routine 0x8003B5FC): li r3,0 -> lwz r3,-0x673C(r13), the attack owner becomes "
                    "the player for the area attack 0x80142FE8(owner, pos, pos, class 0x13, 0, radius) at 0x8003B7D4",
            "source": "static analysis of the G4BE08 main.dol (callers of the area attack 0x80142FE8; owner = r3). The "
                      "owner rule (a blast owned by the player em hurts enemies, never the player) is gBox's own live "
                      "evidence of 2026-10-07 for explosive_melee: HP 1632 -> 1632 with the player as owner, 1632 -> 912 "
                      "with owner 0 (MELEE_CODE notes above)",
            "confidence": "high for the site; the effect is inferred from the verified owner rule",
            "live_checked": False},
        "GRENADE_OWNER_B": {
            "address": 0x8003B868, "size": 4, "original": "38600000", "patched": "806d98c4",
            "what": "hand-grenade blast, second path (routine 0x8003B828, class 0x13 area attack at 0x8003B86C)",
            "source": "static analysis of the G4BE08 main.dol (as GRENADE_OWNER_A)",
            "confidence": "medium-high: the sibling routine of the hand-grenade object with the same class 0x13 blast",
            "live_checked": False},
    },
    # Resident Evil 4: Wii Edition PAL: none of these is located in the Wii main.dol yet (no Wii disc on the PC that
    # did the analysis; the GC->Wii feature-bag matcher in the notes above is the way). The tool refuses with that note.
    "RB4P08": {},
}
# Not patched (recorded so nobody re-derives it): the area-attack call at 0x8003A988 in routine 0x8003A8D4, classes
# 0x19/0x1F/0x20 by sub-type - probably the incendiary grenade's fire, unconfirmed; grenade_safe leaves it alone.

_T = MERC_ADDRESS_TABLE["G4BE08"]
COMBO_WINDOW = (_T["COMBO_WINDOW"]["address"], _T["COMBO_WINDOW"]["original"])
GRENADE_SAFE = tuple((e["address"], e["original"], e["patched"], e["what"])
                     for k, e in _T.items() if k.startswith("GRENADE_OWNER"))
WII_PAL.over.update({"COMBO_WINDOW": None, "GRENADE_SAFE": None})


def address_table(game_id) -> dict:
    """The #511/#512 address table of one release; unknown releases are refused (KeyError)."""
    gid = game_id.decode() if isinstance(game_id, bytes) else str(game_id)
    if gid not in MERC_ADDRESS_TABLE:
        raise KeyError(f"no Mercenaries address table for {gid!r}; known: {', '.join(MERC_ADDRESS_TABLE)}")
    return {k: {**v, "address": f"0x{v['address']:08X}"} for k, v in MERC_ADDRESS_TABLE[gid].items()}


# What the system unlock word really holds per release (pSys + 4, u32, MSB first). Only bits with evidence are named;
# unlock_all writes all 32 (verified live on GC and Wii: every extra mode + Professional).
UNLOCK_SCOPE = {
    "G4BE08": {"characters": ["Leon", "Ada", "HUNK", "Krauser", "Wesker"],
               "stages": ["Village", "Castle", "Island", "Waterworld"],
               "modes": ["The Mercenaries", "Assignment Ada"],
               "named_bits": {"0x08000000": "Mercenaries Ada", "0x04000000": "Mercenaries HUNK",
                              "0x02000000": "Mercenaries Krauser", "0x01000000": "Mercenaries Wesker",
                              "byte 0 = 0xFF": "every extra game + all Merc characters and stages"},
               "costumes": "none in Mercenaries (one outfit per character); the story-mode special costumes sit in the "
                           "other bytes of the same word, which unlock_all also sets (not separately confirmed)",
               "weapons": "none to unlock in Mercenaries (fixed loadouts; merc_loadout changes them)"},
    "RB4P08": {"characters": ["Leon", "Ada", "HUNK", "Krauser", "Wesker"],
               "stages": ["Village", "Castle", "Island", "Waterworld"],
               "modes": ["The Mercenaries", "Assignment Ada", "Separate Ways", "Movie Browser"],
               "named_bits": {"byte 0 = 0xFF": "every extra game + all Merc characters and stages"},
               "costumes": "none in Mercenaries (one outfit per character)",
               "weapons": "none to unlock in Mercenaries (fixed loadouts)"},
}
