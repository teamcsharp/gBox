# RE4 Switch weapons in RAM: fire rate, levels, ammo, the inventory, the Mercenaries loadouts

2026-11-10. Static analysis of the decrypted main NSO (`~/gBox_alt/switch/work/re4-nsp/main.bin` on lilspark: text file
0x100 -> mem 0x0, rodata file 0x656100 -> mem 0x656000, data file 0xae2100 -> mem 0xae2000). Every offset is a module
(memory) offset; add `re4_switch.module_base()`. The code with every offset and decoder is
`gbox/mercs/titles/re4_weapons.py` (read only); `tests/test_re4_weapons.py` checks it.

**Confidence.** Statically measured unless marked *inferred*. Two offsets are confirmed live: the game object's life
(`GAME_OBJ + G_HP` = module + 0x1279360, the field `scripts/re4sw_life_probe.py` found in a live round) and the
firepower table (module + 0xAF0E8C, rows by weapon class: the live mods' Weapon power / Max level wrote all 13 rows in a
live round, 2026-11-10 06:22 UTC). Everything else needs the live checks below.

## The tables

| Table | Offset | Shape | Read by | Writable |
|---|---|---|---|---|
| `WEAPON_TBL` | 0xA07CC6 | 43 x 22 B: u16 id, u8, u8 class, u8 variant, u8, u16 ammo id, u16 capacity[7] | the equip and ammo code | rodata |
| `MAX_LEVEL_TBL` | 0xA08078 | 30 x 6 B: u16 id, u8 counts (firepower, firing speed, reload, capacity) | the shop | rodata |
| `FIRE_RATE_TBL` | 0xA0AA18 | 49 classes x f32[5]: 30 Hz frames between shots per firing-speed level | 0x293B50 (display), 0x31E060 (the shot gate) | rodata |
| `RELOAD_TBL` | 0xA0A580 | 49 x f32[3] frames per reload level | 0x293BC0 | rodata |
| `FIREPOWER_TBL` | 0xAF0E8C | 49 x f32[7] damage per firepower level (the 7th: exclusive) | 0x293910, the damage routine | **data** |
| `SHOTGUN_FAR_TBL` | 0xAF13E8 | 3 x f32[7] the Shotgun / Striker / Riot Gun's second firepower column | the damage routine | data |
| `RIFLE_FIRE_TBL` | 0xA0BDD0 | 2 x f32[5] the scoped rifles' shot timer (class - 9) | 0x333B00 | rodata |

The shot gate (0x31E060) waits for the firing motion to cross frame `int(FR) - 2`: an interval under 3 frames is never
crossed, so the fastest handgun-style fire is FR 3.0 (10 shots/s at 30 Hz). A capacity entry of 0x8000 is infinite:
`use_ammo` (0x2997E0) never consumes. "rodata" is read-only to the game, but the emulator's memory writes reach it.

## The game state (bss, `GAME_OBJ` = 0x1274338; the pointer variable 0xB1AE08 holds its address)

+0x78 mode flags (bit 30 = The Mercenaries), +0xA4 f32 frame step (**live** 0.5 at 60 fps; the round clock falls by
it, `re4-switch-game-state.md`), +0x1A8 Stop_flg, +0x5090 Status_flg[4], +0x5028 / +0x502A life / maximum
(**live**), +0x5034 the equipped weapon's class, +0x5035 variant, +0x5036 magazine empty, +0x5037 firepower nibble,
+0x5038 firing-speed nibble, +0x5039 capacity nibble, +0x503C character (0 Leon, 1 Ashley, 2 Ada, 3 HUNK, 4 Krauser,
5 Wesker), +0x503E reload nibble.

## The inventory (`ITEM_MGR` = 0x124D918)

+0x10 the equipped item's pointer, +0x18 its id (0x800 = none), +0x1B owner, +0x20 the item array (384 x 14 B on the
heap). An item: u16 id, u16 count, u8 flags (bit 0 in use), u8 owner, u16 levels (four nibbles: firepower | firing
speed << 4 | reload << 8 | capacity << 12; 6 = exclusive), u16 (rounds loaded << 3 | empty bit), u8 x, u8 y, u8, u8 in
case.

## The Mercenaries loadouts (0x295070, by character)

Leon: Blacktail, Riot Gun, handgun ammo 30, shells 10, spray. Ada: Punisher, TMP, semi-auto rifle + scope, ammo,
incendiaries x3, spray. HUNK: Custom TMP, TMP ammo 50, hand grenades x3, spray. Krauser: bow, arrows 30, flash x3,
spray. Wesker: Handgun, Killer7, semi-auto rifle, silencer, grenades, flash x3, incendiary, spray. (Ids and levels in
`re4_weapons.MERC_LOADOUTS`.)

## What a live test must check

1. `Reader.check()` on a running round: the game object is fixed, the classes match, the handgun's fire-rate row reads
   14, 12, 10, 10, 10, the Handcannon's exclusive firepower 99.9.
2. Fire rate: write the equipped class's `FIRE_RATE_TBL` row to 3.0 and count shots per second (the bot's `shots`
   over time): from about 2 to about 10 with the handgun.
3. Infinite ammo: capacity entries 0x8000 for the equipped weapon's row: the HUD's rounds stop falling.
4. A weapon swap: the equipped item's id, levels and class rewritten - whether the model in hand changes or only the
   behaviour (the equip routine 0x294600 / 0x296D80 is what loads a model).
