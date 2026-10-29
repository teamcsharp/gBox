"""Resident Evil 6 (Nintendo Switch, title 01002A000CD48000 v1.0.2, main build 061D2A06CD700785E987C42CE2D72231) live
Mercenaries mods on Citron: data writes into the running game through the Switch adapter (write_memory reads every
write back). Everything is RAM only: a relaunch is the full revert. A bot module (gbox.hot_reload reloads it in place;
ORIG survives).

The Mercenaries playbook applies the profile's playing_ops through run() when a round starts (gbox/mercs_bot.py
apply_ops), and the driver (gbox.mercs.titles.re6_switch.RE6Switch.screen) calls maintain() on every snapshot.

ops:
  status                    what is on, and the in-hand weapon's rounds / capacity
  infinite_ammo on=true     every gun in the inventory keeps a full magazine: a weapon slot whose rounds fell below its
                            capacity is topped up on the next snapshot, so the gun never empties and never reloads (the
                            item slots - the tablets, the sprays, the grenades - are left alone)
  infinite_tablets on=true  the tablet case is kept at TABLET_KEEP tablets while its slot is alive (count-keeping, as RE5
                            Switch keeps its spray): only the count's s16 is written, only into a live cItem slot holding
                            the tablets (id 0x1D, in use, its item object set), re-read just before the write and read
                            back after it; never the id, the object pointer or a slot that is not the tablets'
  infinite_stamina on=true  the combat gauge (melee, quick shots, dodges) kept full: player +0x42A0 set to its maximum
                            +0x42A4 whenever it fell below (f32, re-read just before the write, read back after; only a
                            maximum in 1..STAMINA_SANE). Where (Ghidra, this build): the HUD's gauge (uIdLife's update
                            main+0x9FEA90) asks the player's vfunc 0x3F8 (main+0xBD9CD0) for its segments, int((gauge -
                            300) / 100); the vfunc 0x400 beside it gives the maximum's; the player's init sets both from
                            the character's level (main+0xB18BF4) and every spend / refill goes through the vfunc 0x3E0
                            (main+0xB209D0), which waits for the refill delay +0x42A8
  infinite_grenades on=true every hand / incendiary / flash grenade and remote bomb stack (the start list's slots, +0x9
                            15-23, type 0x113-0x116) kept at THROWN_MAX - it never reaches 0, where the ammo consumer
                            main+0xB25DC0 frees the stack and its object - and the item wheel's count (+0x9 7-14) at the
                            stacks' total; counts only (merc_loadout gives every loadout the stacks)
  unlock_stages on=true     every Mercenaries stage in the stage select: the stage select's update main+0xAAFB20 builds
                            its mask (+0x58) from cSystemInfo +0x970 & 0xFFFFE | 0xFE7F9 (>> 10 in mode 8), so stages 1
                            and 2 are the save's: only those bits (0x1806) ORed into both copies (+0x970, +0x5E80), read
                            back; the game's own next save keeps them (operator OK 2026-10-27, "random levels")
  auto_qte on=true          the game's own automatic action button: cSystemInfo mTempData.mExOptAutoActBtn (+0x46B0,
                            copy B +0x9BC0) set to 1 in both copies, that field only, read back; every QTE site tests it
                            (nonzero = automatic) (operator OK 2026-10-27, "auto QTE")
  kill_time on=true seconds=3 [seconds_max=N]  +seconds on the round clock for every new kill of sGameMan's count
                            (+0x408C) while a round is playing (RE5's kill_time): the clock sGameMan +0x3DF0 written as
                            the game's own time-add handler main+0x1DF9A4 writes it (clamped to 5999.99, the HUD's
                            bonus notice +0x3DF8 / +0x3DFC), read back; a new round counts afresh
  add_time seconds=N / set_time seconds=N  the round clock moved / set the same way (RE5's names; never under 1 s)
  auto_qte_ram on=true      while a zombie holds him (action 8 / 9 / 25), the grab's action button (sActionButton
                            [main+0x28E7AF0], ButtonMgr +0x50 + 0x398 * player, units +0x248 / +0x2E0) gets the escape
                            the game itself grants (the evaluation main+0x31F0C0): a chance button (type 8 ...: the grab)
                            its rolled outcome +0x8 set to 0, free at once; a mash button its progress +0x40 up to its
                            target +0x3C; the bot's own shake stays the fallback
  unlock_characters on=true every Mercenaries character and costume on the save: the character select's mask (cSystemInfo
                            +0x974 and its copy +0x5E84, which the select's constructor main+0xAA9158 ORs with 0x20010101)
                            set to 0x3FFFFFFF, both copies read back; nothing else in cSystemInfo is ever written, and the
                            game's own next save keeps it (live 2026-10-27: 0x10711 -> 0x3FFFFFFF, the select listed 9)
  fire_rate multiplier=N    every gun fires N times as fast: the game's own seconds between two shots, one f32 per
                            weapon record in the weapon parameter table (main+0x2962170, 48 records of 0x1A0, the
                            record's +0x1C), set to this build's value / N (never below FIRE_FLOOR: the countdown has to
                            pass zero), each read back; N=1 (or on=false) writes the build's values back. Grenades, the
                            remote bomb, the knife and the melee weapons keep theirs. A data write, live and reversible
                            (a relaunch reloads the table too); nothing else in the table, no code, no pointer.
                            Where (Ghidra, this build): every shot's fire action asks main+0xB26F90 for the interval -
                            ldr s8, [x0, #0x1c] at main+0xB2701C reads it from the in-hand weapon's record (the lookup
                            main+0x10ECE20: the weapon type's low byte, a few alternate-mode records) - and stores it in
                            player +0x5AEC (main+0x109A8C8); the player's update counts +0x5AEC down by the frame time
                            (main+0xBD3A90), and the automatic loop of the fire action (main+0x10982D0) fires again once
                            it is <= 0 with the trigger held (main+0x1098508..+0x1098528: re-arm main+0x109A8A0, the
                            state back to 0); a semi-automatic's next press is taken once it is below the record's
                            +0x20 (player +0x5590)

Where (measured live 2026-10-27 in a private Citron NEO session on the Spark; docs/research/re6-switch-ram.md):
  player +0x5070  the inventory: 12 cItem slots of 0x28 (vtable main+0x2875848), +0x8 1 = in use, +0x9 the slot's
                  index, +0xA the item id, +0xE s16 the rounds in the magazine, +0x14 s16 its capacity (the Wing Shooter
                  18 / 18; three shots took it to 15, the HUD's magazine row), +0x16 the carry limit. Slots 0-6 hold the
                  weapons, 7-11 the items: Chris's slot 0 is his assault rifle (id 0x0F, 30 / 30; a held ZR spent 24 rounds
                  in 2.5 s, an automatic), slot 1 id 0x07 (7 / 7), slot 7 id 0x1D (0 / 12: the tablets, Leon's 8 at the
                  start), 8 id 0x20 (0 / 3), 9-11 ids 0x13-0x15 (3 / 5, 0 / 5, 0 / 5)
  player +0x507E  the first slot's rounds = the gun in hand at the round start (gbox.mercs.titles.re6_switch.P_AMMO)
  player +0x5196  s16 the health tablets (8 at the start; R takes one)
"""
from __future__ import annotations

import struct
import time
import threading

from . import re6_switch as R

GAME = "Resident Evil 6 (Nintendo Switch 01002A000CD48000 v1.0.2, main 061D2A06CD700785E987C42CE2D72231)"
MAP_ID = R.MAP_ID
SLOTS, SLOT_STRIDE, SLOT_ROUNDS, SLOT_CAP, N_SLOTS = 0x5070, 0x28, 0xE, 0x14, 12
WEAPON_SLOTS = 7                                         # slots 0-6 the weapons; 7-11 the items (tablets, sprays, grenades)
SLOT_VTABLE = 0x2875848                                  # cItem
SLOT_USED, SLOT_ID, SLOT_OBJ = 0x8, 0xA, 0x20            # u8 1 = in use, u8 the item id, the item's object (never written)
TABLET_ID, TABLET_KEEP = 0x1D, 6                         # the tablet case (Leon 8 / 12 at the start, Chris 0 / 12)
P_STAMINA, P_STAMINA_MAX = 0x42A0, 0x42A4                # f32 the combat gauge and its maximum (100 a segment past 300)
ALL_SLOTS, SLOT_INDEX, SLOT_TYPE = 24, 0x9, 0xA          # the 24 cItem slots (the getter main+0xB22BB0 finds one by its
                                                         # +0x9 index); u16 +0xA the type (0x100 + the item id)
STACK_INDEXES = range(15, 24)                            # the start list's items, one slot each (grenades, the remote bomb)
WHEEL_INDEXES = range(7, 15)                             # the item wheel: a grenade's count there is its stacks' total
                                                         # (the ammo consumer main+0xB25DC0 recounts it after each throw)
STAMINA_SANE = 10000.0                                   # a maximum above this is not the gauge's
CHARACTER_MASK = (0x974, 0x974 + 0x5510)                 # cSystemInfo: the select's unlock mask, copy A and copy B
STAGE_MASK = (0x970, 0x970 + 0x5510)                     # cSystemInfo: the stage select's save bits (main+0xAAFB20 reads
STAGE_BITS = 0x1806                                      # them & 0xFFFFE | 0xFE7F9: stages 1 and 2 are the save's - bits
                                                         # 1, 2, and 11, 12 for mode 8, which shifts them down by 10)
AUTO_QTE = (0x46B0, 0x46B0 + 0x5510)                     # cSystemInfo mTempData.mExOptAutoActBtn: nonzero = the game's own
                                                         # automatic action button (every QTE site tests it, cbz / cbnz)
ALL_CHARACTERS = 0x3FFFFFFF                              # 4 costume bits for each of 7 characters, then bits 28 and 29
CAP_MAX = 200                                            # a capacity above this is not a gun's magazine
CHECK_S = 0.25                                           # maintain tops up at most this often
FIRE_MAX = 5.0                                               # operator 2026-10-28: "make the max fire rate multiplier for a weapon 5x"
FIRE_TABLE, FIRE_STRIDE, FIRE_RECORDS = 0x2962170, 0x1A0, 48   # the weapon parameter table (lookup main+0x10ECE20)
FIRE_INTERVAL, FIRE_TAG, FIRE_TAG_VALUE = 0x1C, 0x4, 60        # f32 the seconds between two shots; i32 60 in every record
FIRE_SITE, FIRE_SITE_WORD = 0xB2701C, 0xBD401C08               # main+0xB26F90: ldr s8, [x0, #0x1c] (this build's check)
FIRE_ORIGINAL = (10.0, 0.5, 0.6, 0.5, 1.2, 0.8, 0.6, 0.8, 1.2, 10.0, 0.7, 2.25, 0.1, 0.5, 0.5, 0.1, 0.1, 0.12, 1.0,
                 2.0, 2.0, 2.0, 2.0, 1.0, 10.0, 10.0, 10.0, 10.0, 0.1, 1.0, 0.1, 10.0, 1.0, 10.0, 10.0, 10.0, 10.0, 10.0,
                 10.0, 1.0, 0.5, 0.25, 2.25, 0.5, 0.1, 1.0, 1.0, 2.0)   # this build's intervals, records 0-47 (live dump)
FIRE_SKIP = frozenset({0x13, 0x14, 0x15, 0x16, 0x2F})   # the grenades and the remote bomb: thrown, never sped up
FIRE_GUN_MAX = 5.0                                       # a longer interval is the knife's or a melee weapon's
MAGNUM_RECORDS = frozenset({0x07, 0x08})                 # the magnums' records (0x107 / 0x108): fire_rate magnum=
THROW_RECORDS = frozenset({0x13, 0x14, 0x15})            # the hand, incendiary and flash grenades' (fire_rate throw=;
                                                         # not the remote bomb's): their 2.0 s, the throw's own wait
# down_fire (operator 16:22: "I want the fire rate tripled and them becoming even more lethal when grounded so they can
# rise again"): while he is down (re6_switch.DOWN_ACTIONS - dying, lying, crawling - held through DOWN_KEEP's) the
# weapon table at DOWN_FIRE_X times fire_rate's multipliers (its magnum's too), back to them the moment he is up; only
# once fire_rate has set the table this boot. The down_fire op sets the factor (1 = off).
DOWN_FIRE_X, DOWN_FIRE_MAX = 3.0, 10.0
# magnum_speed (operator 17:24: "blasting the Magnum in rapid succession with the recoil animation reduced"): while his
# action is the gun's fire (cPlAction_pl_act_weapon_fire: the shot and its recoil) with a magnum in hand (weapon records
# MAGNUM_RECORDS), his mDeltaTime (cUnit +0x30, as quick_attack) at MAGNUM_SPEED_X, 1.0 back after; fire_rate's table
# stays (the magnum's 8). Only once fire_rate has set the table this boot; the op sets the factor (1 = off). status
# magnum_fast counts the fire actions sped up.
MAGNUM_SPEED_X, MAGNUM_SPEED_MAX = 3.0, 6.0
# throw_speed (operator 19:01: "When throwing grenades give them 20x grenade throwing speed animation"): his mDeltaTime
# at THROW_SPEED_X while the throw runs (the gun's fire action with a grenade in hand: records THROW_RECORDS), as the
# magnum's; status throw_fast counts them.
THROW_SPEED_X, THROW_SPEED_MAX = 20.0, 20.0
MAGNUM_FIRE_ACTIONS = frozenset({"cPlAction_pl_act_weapon_fire"})
FIRE_FLOOR = 0.004                                       # never 0: a semi-automatic's next press waits for the countdown
                                                         # to fall below its record's +0x20 (0 for most), so it must pass 0
# The Mercenaries' starting loadouts (Ghidra, this build): main+0x38C740 copies one 0x74-byte entry into the game's
# per-player buffer when a round is set up - the entry of the pointer array main+0x2890008 at the costume's loadout index
# (the costume code table main+0x222B352, 5 bytes a code: character, variant, select id, costume, loadout index; costume
# 0 has its own entry, costumes 1-3 share the second). Modes 4-7 read the other arrays (+0x7C8, +0x1008, +0x17C8,
# +0x1F88); No Mercy and The Mercenaries read this one (live 2026-10-27: Chris's round matched it). An entry: u16 id,
# health / maximum (900 / 900), 0, 0xFF, 0, 0, 0; then 7 (type, rounds) weapon pairs at +0x10 (type 0x100 + the item id,
# rounds 0xFFFF for a melee weapon), 8 (type, count) item-wheel pairs at +0x2C, 9 (type, count) pairs at +0x4C given at
# the start (grenades, the remote bomb 0x116, the spray, ammo boxes 0x2xx); an empty pair is (0, 0xFFFF); +0x70 u32 0.
LOADOUT_BLOCK, LOADOUT_SIZE = 0x2890088, 0x74
L_ID, L_HP, L_TAG, L_TAG_VALUE = 0x0, 0x2, 0x8, 0xFF
L_WEAPONS, L_EXTRAS, N_WEAPONS, N_EXTRAS = 0x10, 0x4C, 7, 9
EMPTY = (0, 0xFFFF)
ROCKET = 0x117                                           # the rocket launcher (1 round; Ada's first costume)
SWAPS = ((0x107, 7), (0x108, 5), (0x104, 8), (0x105, 7), (0x106, 3))   # magnums and shotguns: (type, magazine)
MAGNUMS = ((0x107, 7), (0x108, 5))                      # merc_loadout magnum=: one of these in weapon slot 0 (the gun
                                                         # in his hand at the start) - his own when the entry has one
REMOTE_BOMB, HAND_GRENADE, INCENDIARY, FLASH = 0x116, 0x113, 0x114, 0x115
THROWN = (REMOTE_BOMB, HAND_GRENADE, INCENDIARY, FLASH)  # given in this order while the start list has room
THROWN_MAX = 5                                           # the grenades' and the remote bomb's carry limit (their records)
# RE6's weapons by item id (the type is 0x100 + id): the game's own names, read live from its message table
# (rGUIMessage soft\message\mes_item_eng: +0xA0 the count, +0xC0 a pointer per id; 2026-10-27 18:40), kept here for
# when it can't be read. The live weapon op and the app's dropdown list these.
WEAPON_NAMES = {
    0: "Hand-To-Hand", 1: "Nine-Oh-Nine (909)", 2: "Picador", 3: "Wing Shooter", 4: "Shotgun", 5: "Assault Shotgun",
    6: "Hydra", 7: "Lightning Hawk", 8: "Elephant Killer", 9: "Sniper Rifle", 10: "Semi-Auto Sniper Rifle",
    11: "Anti-Materiel Rifle", 12: "Ammo Box 50", 13: "Triple Shot", 14: "MP-AF", 15: "Assault Rifle for Special Tactics",
    16: "Bear Commander", 17: "Assault Rifle RN", 18: "Grenade Launcher", 23: "Crossbow", 24: "Survival Knife",
    25: "Combat Knife", 26: "Stun Rod", 27: "Rocket Launcher", 40: "Triple Shot"}
WEAPON_KIND = {1: "handgun", 2: "handgun", 3: "handgun", 12: "handgun", 13: "handgun", 40: "handgun", 4: "shotgun",
               5: "shotgun", 6: "shotgun", 7: "magnum", 8: "magnum", 9: "sniper", 10: "sniper", 11: "sniper",
               14: "machine gun", 15: "rifle", 16: "shotgun", 17: "rifle", 18: "launcher", 23: "crossbow",
               27: "launcher", 0: "melee", 24: "melee", 25: "melee", 26: "melee"}
WEAPON_MAG = {0x101: 15, 0x102: 16, 0x103: 18, 0x104: 8, 0x105: 7, 0x106: 3, 0x107: 7, 0x108: 5, 0x109: 6, 0x10A: 5,
              0x10B: 10, 0x10C: 50, 0x10D: 20, 0x10E: 30, 0x10F: 30, 0x110: 286, 0x111: 30, 0x112: 6, 0x117: 1,
              0x11B: 1, 0x128: 20, 0x100: 0xFFFF, 0x118: 0xFFFF, 0x119: 0xFFFF, 0x11A: 0xFFFF}
SHOTGUN_TYPES = frozenset({0x104, 0x105, 0x106})
MAGNUM_TYPES = frozenset({0x107, 0x108})
# The spread (operator 18:00: "change what weapon is being used by the bot actively ... instantly use that weapon"): a
# gun's model loads only for the round's loadout, so the empty weapon slots of every loadout get these at round set-up
# (merc_loadout spread=): the magnums and the shotguns, ready for the live switch and the grab swap.
SPREAD = ((0x108, 5), (0x107, 7), (0x104, 8), (0x105, 7), (0x106, 3))
ASKED: set = set()                                       # the (type, magazine) pairs live_weapon put in the loadouts
# No pistols (operator 2026-10-27 ~20:00: "for the characters in no mercy, replace the pistol with any random shotgun or
# magnum"; "i want the characters using random weapons from the game and campaign in mercenaries"): with the spread,
# each loadout's handgun is swapped for a gun drawn fresh at every select from the campaign's shotguns, magnums and
# machine guns (never a pistol, never one the loadout already has).
HANDGUN_TYPES = frozenset({0x101, 0x102, 0x103, 0x10C, 0x10D, 0x128})
# No sniper rifles (operator 2026-10-28: "Do not let the bot use sniper rifles. If they pull out a sniper rifle, replace it
# with a rapid fire randomized magnum"): the Sniper Rifle, Semi-Auto Sniper Rifle and Anti-Materiel Rifle become a random
# magnum (Lightning Hawk / Elephant Killer, fire_rate's multiplier on it) in every loadout, spread or not.
SNIPER_TYPES = frozenset({0x109, 0x10A, 0x10B})
MAGNUM_SWAPS = ((0x107, 7), (0x108, 5))
PISTOL_SWAPS = ((0x104, 8), (0x105, 7), (0x106, 3), (0x107, 7), (0x108, 5), (0x10E, 30), (0x10F, 30), (0x111, 30),
                (0x110, 286))
LOADOUTS = (                                             # this build's entries: id, weapons, start list (live dump)
    (0x0000, ((0x103, 18), (0x104, 8)), ((0x116, 4), (0x201, 50), (0x202, 8))),
    (0x1000, ((0x111, 30), (0x109, 6), (0x2112, 5120)), ((0x204, 60), (0x203, 30))),
    (0x0001, ((0x102, 16), (0x106, 3), (0x1112, 192)), ((0x201, 50), (0x20E, 30))),
    (0x1001, ((0x10C, 50), (0x109, 6)), ((0x304, 1), (0x120, 1), (0x114, 3), (0x201, 50), (0x203, 20))),
    (0x0002, ((0x10F, 30), (0x107, 7), (0x119, 0xFFFF)), ((0x113, 3), (0x204, 60), (0x206, 7))),
    (0x1002, ((0x101, 15), (0x104, 8), (0x11B, 1)), ((0x201, 50), (0x202, 20))),
    (0x0003, ((0x10E, 30), (0x10B, 10)), ((0x120, 1), (0x116, 3), (0x201, 50), (0x205, 20))),
    (0x1003, ((0x10C, 50), (0x10A, 5), (0x105, 7)), ((0x201, 30), (0x203, 15), (0x202, 10))),
    (0x0004, ((0x101, 15), (0x108, 5), (0x100, 0xFFFF)), ((0x115, 2), (0x201, 50), (0x207, 10))),
    (0x1004, ((0x118, 0xFFFF), (0x10A, 5), (0x112, 6)), ((0x120, 1), (0x203, 20), (0x208, 12))),
    (0x0005, ((0x10D, 20), (0x107, 7), (0x11A, 0xFFFF)), ((0x304, 1), (0x304, 1), (0x120, 1), (0x201, 30), (0x206, 10))),
    (0x1005, ((0x110, 286), (0x105, 7)), ((0x304, 1), (0x304, 1), (0x120, 1), (0x115, 2), (0x204, 60), (0x202, 20),
                                          (0x208, 3))),
    (0x0006, ((0x10C, 50), (0x117, 1)), ((0x114, 3), (0x201, 30), (0x20C, 60), (0x20D, 30))),
    (0x1006, ((0x10E, 30), (0x109, 6)), ((0x304, 1), (0x304, 1), (0x113, 3), (0x115, 2), (0x201, 30), (0x203, 6))),
    (0x0206, ((0x102, 16), (0x112, 6)), ((0x201, 50), (0x209, 12), (0x20A, 6))),
    (0x0007, ((0x101, 15), (0x10A, 5), (0x118, 0xFFFF)), ((0x116, 5), (0x120, 2), (0x201, 50), (0x203, 20))),
)
# The round clock (Ghidra: the game manager's own time-add handler main+0x1DF9A4, the time bonuses' and the finishers'
# path, works on sGameMan's Mercenaries block at +0x8A8): that block's +0x3DF0 - sGameMan +0x4698 - is the countdown
# itself, clamped to 5999.99 (main+0x21516F0), its +0x3DF8 (+0x46A0) the bonus the HUD shows (999 at most, added to
# while its notice +0x3DFC (+0x46A4) is up). sGameMan +0x3DF0 is the HUD's copy, rewritten every frame (live
# 2026-10-27: +30 there read back and was gone the next frame; +30 at +0x4698 stuck and the copy followed it).
# kill_time / add_time / set_time write the clock the same way (RE5's names: gbox.re5_mods_tool).
GM_CLOCK = 0x4698
CLOCK_MAX, CLOCK_MIN = 5999.99, 1.0                      # no write leaves the countdown at or under CLOCK_MIN
KILL_TIME_S, KILL_TIME_MAX_S = 5.0, 30.0                 # operator 2026-10-27 21:5x: "five seconds added to the timer" per kill
ADD_TIME_RANGE, SET_TIME_RANGE = (-3600, 3600), (1, 3600)
# The game's own action-button struggle (Ghidra): sActionButton [main+0x28E7AF0] (constructor main+0x31B350) holds a
# ButtonMgr per player at +0x50 + 0x398 * index (its update main+0x31D4F0), each with two ButtonUnits of 0x98 at +0x248
# and +0x2E0 (+0xC active, +0x10 the cActionButton). The evaluation main+0x31F0C0 adds 0.5 a press to the unit's
# progress +0x40 and grants the action once it reaches the target +0x3C (the cActionButton calls its success function:
# the zombie lets go); +0x4C counts the time limit to 100 (the bite). auto_qte_ram writes the progress up to the target
# while a zombie holds him: the escape the game itself grants when the mashing fills it.
S_ACTBTN, AB_MGRS, AB_MGR_STRIDE, AB_PLAYERS = 0x28E7AF0, 0x50, 0x398, 8
MGR_UNITS, UNIT_ACTIVE, UNIT_BUTTON, UNIT_TARGET, UNIT_PROGRESS = (0x248, 0x2E0), 0xC, 0x10, 0x3C, 0x40
# A zombie's grab is a "chance" button (unit +0x1C type 8, 0x12, 0x13, 0x17-0x19; live: type 8, target 34, time limit
# 180): its outcome is rolled once at the start into unit +0x8 (0 free at once, 1 / 2 / 3 free at 10 / 50 / 80 % of the
# time limit +0x4C, 4 the bite at 100 %; the roll weighs his health), +0xD set until the roll is done. For those
# auto_qte_ram writes the outcome the game itself can roll: 0, free at once.
UNIT_OUTCOME, UNIT_NEW, UNIT_TYPE = 0x8, 0xD, 0x1C
CHANCE_TYPES = frozenset({0x8, 0x12, 0x13, 0x17, 0x18, 0x19})
QTE_ROLLED_N = 20                       # status qte_rolled: the last outcomes the game had rolled for the grabs freed
QTE_TARGET_MAX = 1000.0                                  # a target above this is not a struggle's
ORIG: dict = {}                                          # id(adapter) -> this boot's settings
_LOCK = threading.RLock()
RELOAD_KEEP = ("ORIG", "_LOCK")


class Mem:
    """The session's guest memory for re6_switch's readers: rd() and the adapter (its guest rows find main)."""

    def __init__(self, ad):
        self.adapter = ad

    def rd(self, a: int, n: int) -> bytes:
        return self.adapter.read_memory(a, n)


class RE6Switch:
    """RE6 Switch in one session: main's base this boot, checked against this build's title gate."""

    def __init__(self, ad):
        self.ad = ad
        self.m = Mem(ad)
        self.state = ORIG.setdefault(id(ad), {})
        if isinstance(self.state.get("base"), int):
            self.m.module_base = self.state["base"]
        base = R.module_base(self.m)
        if base is None:
            raise RuntimeError("RE6 Switch's main is not in this session's memory (another title or build?)")
        self.base = base
        if self.state.get("base") != base:                   # a new boot: the old settings start over
            self.state.clear()
            self.state["base"] = base

    def slots(self, player: int) -> list[tuple[int, int, int]]:
        """The gun slots [(slot, rounds, capacity)]: the weapon slots' cItem records with a magazine (0 < capacity <=
        CAP_MAX; a knife has none). The item slots after them are not guns."""
        out = []
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * WEAPON_SLOTS)
        except (ValueError, OSError):
            return out
        for i in range(WEAPON_SLOTS):
            o = SLOT_STRIDE * i
            vt = struct.unpack_from("<Q", raw, o)[0]
            if vt != self.base + SLOT_VTABLE:
                break
            rounds, cap = struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0], struct.unpack_from("<h", raw, o + SLOT_CAP)[0]
            if 0 < cap <= CAP_MAX:
                out.append((player + SLOTS + o, rounds, cap))
        return out

    def tablet_slot(self, player: int) -> tuple[int, int, int] | None:
        """The tablet case's live slot (slot, count, capacity): an item slot (7-11) with the cItem vtable, in use, the
        tablets' id and its item object set; None when there is none (a character without the case, a slot the game
        cleared)."""
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * N_SLOTS)
        except (ValueError, OSError):
            return None
        for i in range(WEAPON_SLOTS, N_SLOTS):
            o = SLOT_STRIDE * i
            if (struct.unpack_from("<Q", raw, o)[0] == self.base + SLOT_VTABLE and raw[o + SLOT_USED] == 1
                    and raw[o + SLOT_ID] == TABLET_ID and struct.unpack_from("<Q", raw, o + SLOT_OBJ)[0]):
                return (player + SLOTS + o, struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0],
                        struct.unpack_from("<h", raw, o + SLOT_CAP)[0])
        return None

    def thrown_slots(self, player: int) -> tuple[list, list]:
        """The live grenade and remote bomb slots: (stacks, wheel), each [(slot, type, count, capacity)] - a cItem slot in
        use whose type is a grenade's or the remote bomb's, at a start-list index (15-23) or an item-wheel one (7-14)."""
        try:
            raw = self.ad.read_memory(player + SLOTS, SLOT_STRIDE * ALL_SLOTS)
        except (ValueError, OSError):
            return [], []
        stacks, wheel = [], []
        for i in range(ALL_SLOTS):
            o = SLOT_STRIDE * i
            if struct.unpack_from("<Q", raw, o)[0] != self.base + SLOT_VTABLE or raw[o + SLOT_USED] != 1:
                continue
            kind = struct.unpack_from("<H", raw, o + SLOT_TYPE)[0]
            if kind not in THROWN:
                continue
            row = (player + SLOTS + o, kind, struct.unpack_from("<h", raw, o + SLOT_ROUNDS)[0],
                   struct.unpack_from("<h", raw, o + SLOT_CAP)[0])
            if raw[o + SLOT_INDEX] in STACK_INDEXES:
                stacks.append(row)
            elif raw[o + SLOT_INDEX] in WHEEL_INDEXES:
                wheel.append(row)
        return stacks, wheel

    def status(self) -> dict:
        st = {"game": GAME, "module_base": hex(self.base), "infinite_ammo": bool(self.state.get("infinite_ammo")),
              "infinite_tablets": bool(self.state.get("infinite_tablets")),
              "infinite_stamina": bool(self.state.get("infinite_stamina")), "fire_rate_x": self.state.get("fire_rate", 1.0),
              "kill_time_on": bool((self.state.get("kill_time") or {}).get("on")),
              "kill_time_s": (self.state.get("kill_time") or {}).get("seconds", KILL_TIME_S),
              "kill_time_added": self.state.get("kill_time_added", 0.0),
              "auto_qte_ram": bool(self.state.get("auto_qte_ram")),
              "struggles_completed": self.state.get("struggles_completed", 0),
              "qte_rolled": list(self.state.get("qte_rolled") or ()),
              "infinite_grenades": bool(self.state.get("infinite_grenades")), "auto_qte": bool(self.state.get("auto_qte")),
              "quick_attack_x": self.state.get("quick_attack", 1.0),
              "magnum_speed_x": self.state.get("magnum_speed", MAGNUM_SPEED_X) if self.state.get("fire_rate") else 1.0,
              "down_fire_x": self.state.get("down_fire", DOWN_FIRE_X) if self.state.get("fire_rate") else 1.0,
              "next_weapon": hex(self.state["next_weapon"]) if self.state.get("next_weapon") else None,
              "live_weapon_sets": self.state.get("live_weapon_sets", 0)}
        from . import re6_switch as B
        st["bot"] = {"nades": B.NADES, "flash": B.FLASH, "aim_lock": B.AIM_LOCK, "bomb_drop": B.BOMB_DROP,
                     "want_weapon": B.WANT_WEAPON}
        snap = R.snapshot(self.m)
        p = snap.get("player")
        if p:
            st["guns"] = [{"rounds": r, "capacity": c} for _, r, c in self.slots(p["ptr"])]
            st["in_hand_rounds"] = p.get("ammo")
            t = self.tablet_slot(p["ptr"])
            st["tablets"] = {"count": t[1], "capacity": t[2]} if t else None
        return st


def infinite_ammo(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_ammo"] = bool(on)
    filled = 0
    snap = R.snapshot(g.m)
    p = snap.get("player")
    if on and p:
        filled = _top_up(g.ad, g, p["ptr"])
    return {"infinite_ammo": bool(on), "verified": True, "topped_up": filled,
            "note": "every gun's magazine kept at its capacity (each driver snapshot tops up a slot that fired): the "
                    "gun never empties and never reloads"}


def infinite_tablets(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_tablets"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_tablets(g.ad, g, p["ptr"])
    return {"infinite_tablets": bool(on), "verified": True, "kept": kept,
            "note": "the tablet case kept at %d while its slot is alive (its count's s16 only, re-read before and read "
                    "back after every write): a tablet taken is back on the next snapshot" % TABLET_KEEP}


RACE_SPENT = 3                                           # a count the game spent this much of right after the write
STAMINA_RACE = 400.0                                     # (a shot, a throw, a melee between the write and its read-back)


def _put_count(ad, addr: int, value: int) -> None:
    """A count (s16) written and read back; a read-back the game's own spending explains (the value lower by at most
    RACE_SPENT: a shot or a throw landed between the write and the read) counts as done - the next check tops it up -
    any other mismatch raises as the adapter does."""
    try:
        ad.write_memory(addr, struct.pack("<h", value))
    except RuntimeError:
        now = struct.unpack("<h", ad.read_memory(addr, 2))[0]
        if not 0 <= value - now <= RACE_SPENT:
            raise


def _keep_tablets(ad, g: RE6Switch, player: int) -> int:
    t = g.tablet_slot(player)
    if t is None:
        return 0
    slot, count, cap = t
    if not 0 <= count < TABLET_KEEP or cap < TABLET_KEEP:
        return 0
    again = g.tablet_slot(player)                            # the same live slot, unchanged, right before the write
    if again != t:
        return 0
    _put_count(ad, slot + SLOT_ROUNDS, TABLET_KEEP)
    return 1


def _keep_thrown(ad, g: RE6Switch, player: int) -> int:
    """Each live grenade / remote bomb stack back at THROWN_MAX (it never reaches 0, where the game frees it), then each
    item-wheel count at its stacks' total (what the game itself writes after a throw); counts only, each slot re-read
    just before its write."""
    stacks, _wheel = g.thrown_slots(player)
    writes = 0
    for slot, kind, count, _cap in stacks:
        if 0 < count < THROWN_MAX:
            again = struct.unpack("<h", ad.read_memory(slot + SLOT_ROUNDS, 2))[0]
            if again == count:
                _put_count(ad, slot + SLOT_ROUNDS, THROWN_MAX)
                writes += 1
    stacks, wheel = g.thrown_slots(player)
    totals: dict = {}
    for _slot, kind, count, _cap in stacks:
        totals[kind] = totals.get(kind, 0) + max(0, count)
    for slot, kind, count, _cap in wheel:
        want = totals.get(kind)
        if want is not None and count != want and 0 < want <= 99:
            _put_count(ad, slot + SLOT_ROUNDS, want)
            writes += 1
    return writes


def infinite_grenades(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_grenades"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_thrown(g.ad, g, p["ptr"])
    stacks = g.thrown_slots(p["ptr"])[0] if p else []
    return {"infinite_grenades": bool(on), "verified": True, "kept": kept,
            "stacks": [{"type": hex(k), "count": c} for _s, k, c, _cap in stacks],
            "note": "every grenade and remote bomb stack kept at %d (its count only, never 0: the game frees an empty "
                    "one), the item wheel's counts at their totals" % THROWN_MAX}


def stamina(ad, player: int) -> tuple[float, float] | None:
    """(gauge, maximum) of the player, None when the maximum is not a gauge's (1..STAMINA_SANE) or a value is not a
    number."""
    try:
        cur, top = struct.unpack("<2f", ad.read_memory(player + P_STAMINA, 8))
    except (ValueError, OSError):
        return None
    if not (1.0 <= top <= STAMINA_SANE) or cur != cur:
        return None
    return cur, top


def _keep_stamina(ad, player: int) -> int:
    s = stamina(ad, player)
    if s is None or s[0] >= s[1]:
        return 0
    if stamina(ad, player) != s:                             # moved between the reads: the next check takes it
        return 0
    try:
        ad.write_memory(player + P_STAMINA, struct.pack("<f", s[1]))
    except RuntimeError:                                     # a melee spent some right after the write: done
        now = struct.unpack("<f", ad.read_memory(player + P_STAMINA, 4))[0]
        if not 0.0 <= s[1] - now <= STAMINA_RACE:
            raise
    return 1


def infinite_stamina(g: RE6Switch, on: bool) -> dict:
    g.state["infinite_stamina"] = bool(on)
    kept = 0
    p = R.snapshot(g.m).get("player")
    if on and p:
        kept = _keep_stamina(g.ad, p["ptr"])
    s = stamina(g.ad, p["ptr"]) if p else None
    return {"infinite_stamina": bool(on), "verified": True, "kept": kept,
            "gauge": None if s is None else {"value": round(s[0], 1), "max": round(s[1], 1)},
            "note": "the combat gauge (player +0x42A0) kept at its maximum (+0x42A4): melee, quick shots and dodges "
                    "never run it dry (its f32 only, re-read before and read back after every write)"}


def _pairs(raw: bytes, off: int, n: int) -> list[tuple[int, int]]:
    return [struct.unpack_from("<2H", raw, off + 4 * i) for i in range(n)]


def _padded(pairs, n: int) -> list[tuple[int, int]]:
    return list(pairs) + [EMPTY] * (n - len(pairs))


def loadout_plan(entry: int, rocket: bool, thrown: int, rng, magnum: bool = False, spread: bool = False,
                 want=None) -> tuple[list, list]:
    """The entry's (weapons, start list) as merc_loadout leaves them: the rocket launcher swapped for a random magnum or
    shotgun at its magazine, the remote bomb and the grenades each at `thrown` (an existing pair raised, a missing one
    put in the start list's next empty pair while there is one); with magnum, a magnum in slot 0 - his own moved there
    (slot 0's gun taking its place), else 0x107 with slot 0's gun moved to the first empty slot."""
    _id, weapons, extras = LOADOUTS[entry]
    w = _padded(weapons, N_WEAPONS)
    if rocket:
        w = [rng.choice(SWAPS) if t == ROCKET else (t, c) for t, c in w]
    for i, (t, _c) in enumerate(w):                          # no sniper rifle: a random magnum in its place
        if t in SNIPER_TYPES:
            picks = [q for q in MAGNUM_SWAPS if all(q[0] != u for u, _c2 in w)] or list(MAGNUM_SWAPS)
            w[i] = rng.choice(picks)
    if magnum and w[0] not in MAGNUMS:
        own = next((i for i, pair in enumerate(w) if pair in MAGNUMS), None)
        if own is not None:
            w[0], w[own] = w[own], w[0]
        else:
            free = next((i for i, pair in enumerate(w) if pair == EMPTY), None)
            if free is not None:
                w[free] = w[0]
            w[0] = MAGNUMS[0]
    if want is not None and all(t != want for t, _c in w):  # the live weapon asked for: in an empty slot, else the last
        pair = (want, WEAPON_MAG.get(want, 10))              # spread one (never his first gun)
        free = next((i for i, q in enumerate(w) if q == EMPTY), None)
        w[free if free is not None else N_WEAPONS - 1] = pair
    if spread:                                               # no pistol: a random campaign gun in its place
        for i, (t, _c) in enumerate(w):
            if t in HANDGUN_TYPES:
                picks = [q for q in PISTOL_SWAPS if all(q[0] != u for u, _c2 in w)]
                if picks:
                    w[i] = rng.choice(picks)
        for pair in SPREAD:                                  # the magnums and shotguns into the empty slots
            if all(t != pair[0] for t, _c in w):
                free = next((i for i, q in enumerate(w) if q == EMPTY), None)
                if free is None:
                    break
                w[free] = pair
    x = _padded(extras, N_EXTRAS)
    if thrown > 0:
        for kind in THROWN:
            at = next((i for i, (t, _c) in enumerate(x) if t == kind), None)
            if at is None:
                at = next((i for i, p in enumerate(x) if p == EMPTY), None)
                if at is None:                               # no room for this one: a later one present is raised
                    continue
            if x[at][0] != kind or x[at][1] < thrown:
                x[at] = (kind, thrown)
    return w, x


def _loadout_ok(entry: int, raw: bytes) -> bool:
    """This build's entry, untouched or as merc_loadout leaves it: its id and header, every weapon pair the build's (or a
    swap where the rocket launcher was), every start pair the build's, or a thrown item where the build's was empty or
    the same item."""
    eid, weapons, extras = LOADOUTS[entry]
    hd = struct.unpack_from("<5H", raw, 0)
    if hd[0] != eid or hd[1] != 900 or hd[2] != 900 or hd[3] != 0 or hd[4] != L_TAG_VALUE:
        return False
    allowed = set(_padded(weapons, N_WEAPONS)) | set(SWAPS) | set(SPREAD) | set(PISTOL_SWAPS) | {EMPTY} | set(ASKED)
    for cur, orig in zip(_pairs(raw, L_WEAPONS, N_WEAPONS), _padded(weapons, N_WEAPONS)):
        if cur != orig and not (orig[0] == ROCKET and cur in SWAPS) and cur not in allowed:
            return False   # (a magnum moved to slot 0 leaves the build's own guns, rearranged)
    for cur, orig in zip(_pairs(raw, L_EXTRAS, N_EXTRAS), _padded(extras, N_EXTRAS)):
        if cur != orig and not (cur[0] in THROWN and 0 < cur[1] <= THROWN_MAX and (orig == EMPTY or orig[0] == cur[0])):
            return False
    return True


def merc_loadout(g: RE6Switch, on: bool = True, rocket: bool = True, thrown: int = THROWN_MAX, seed=None,
                 magnum: bool = False, spread: bool = False) -> dict:
    """Every Mercenaries starting loadout (the table the game copies at a round's set-up, so the game itself creates the
    weapons and items): no rocket launcher - a random magnum or shotgun in its place - and the remote bomb, the hand,
    incendiary and flash grenades at `thrown` each where the start list has room. Only the changed (type, count) pairs
    are written, each read back; off writes the build's pairs back. A round already set up keeps its inventory: the
    profile runs it from round_ops, at every character select."""
    import random
    try:
        thrown = int(thrown)
    except (TypeError, ValueError):
        raise ValueError("merc_loadout thrown: 0..5 of each grenade and the remote bomb") from None
    if not 0 <= thrown <= THROWN_MAX:
        raise ValueError("merc_loadout thrown: 0..5 of each grenade and the remote bomb")
    nw = g.state.get("next_weapon")
    if nw:                                                   # (kept across a bot reload: the table may hold it already)
        ASKED.add((nw, WEAPON_MAG.get(nw, 10)))
    base = g.base + LOADOUT_BLOCK
    try:
        raw = g.ad.read_memory(base, LOADOUT_SIZE * len(LOADOUTS))
    except (ValueError, OSError):
        raw = b""
    entries = [raw[i * LOADOUT_SIZE:(i + 1) * LOADOUT_SIZE] for i in range(len(LOADOUTS))]
    if len(raw) != LOADOUT_SIZE * len(LOADOUTS) or not all(_loadout_ok(i, e) for i, e in enumerate(entries)):
        return {"merc_loadout": False, "verified": False, "writes": 0,
                "reason": "the loadout table is not this build's (main+%#x): nothing written" % LOADOUT_BLOCK}
    rng = random.Random(seed)
    writes, swapped, given = 0, [], 0
    for i, cur in enumerate(entries):
        if on:
            w, x = loadout_plan(i, rocket, thrown, rng, magnum=magnum, spread=spread, want=g.state.get("next_weapon"))
        else:
            w, x = _padded(LOADOUTS[i][1], N_WEAPONS), _padded(LOADOUTS[i][2], N_EXTRAS)
        at = base + i * LOADOUT_SIZE
        for off, want, have in ((L_WEAPONS, w, _pairs(cur, L_WEAPONS, N_WEAPONS)),
                                (L_EXTRAS, x, _pairs(cur, L_EXTRAS, N_EXTRAS))):
            for k, (pw, ph) in enumerate(zip(want, have)):
                if pw != ph:
                    g.ad.write_memory(at + off + 4 * k, struct.pack("<2H", *pw))   # read back by the adapter
                    writes += 1
        if on:
            swapped += [(hex(LOADOUTS[i][0]), hex(t)) for (t, _c), (o, _d) in zip(w, _padded(LOADOUTS[i][1], N_WEAPONS))
                        if o == ROCKET and t != ROCKET]
            given += sum(1 for t, _c in x if t in THROWN)
    g.state["merc_loadout"] = bool(on)
    return {"merc_loadout": bool(on), "verified": True, "writes": writes, "rocket_swaps": swapped, "magnum_first": magnum,
            "thrown_pairs": given, "thrown_each": thrown if on else None,
            "note": "the Mercenaries' starting loadouts (main+%#x, read by the round set-up main+0x38C740): no rocket "
                    "launcher, the remote bomb and the grenades given; the next round set up starts with them"
                    % LOADOUT_BLOCK}


def _info_bits(g: RE6Switch, offs, bits: int, value=None) -> dict:
    """cSystemInfo u32s at offs (copy A, copy B): OR bits in (value None) or set to value, only where they differ,
    each read first and back after; nothing else in cSystemInfo is touched."""
    from ... import re6_switch_unlock as U
    info = U.system_info(g.m, g.base)
    if info is None:
        return {"verified": False, "reason": "no cSystemInfo yet (still booting)", "writes": 0}
    before = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in offs]
    writes = 0
    for off, v in zip(offs, before):
        want = (v | bits) if value is None else value
        if want != v:
            g.ad.write_memory(info + off, struct.pack("<I", want))
            writes += 1
    after = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in offs]
    ok = all((a & bits) == bits for a in after) if value is None else all(a == value for a in after)
    return {"verified": ok, "before": [hex(v) for v in before], "after": [hex(v) for v in after], "writes": writes}


def unlock_stages(g: RE6Switch, on: bool = True) -> dict:
    """Every Mercenaries stage in the stage select: only the stage bits of the save's word (cSystemInfo +0x970, copy B
    +0x5E80) - the select ORs the rest in itself - read first and back after; off changes nothing (the save keeps an
    unlock: the game's own next save)."""
    res = _info_bits(g, STAGE_MASK, STAGE_BITS) if on else {"verified": True, "writes": 0}
    g.state["unlock_stages"] = bool(on)
    return {"unlock_stages": bool(on), **res,
            "note": "the stage select's save bits (stages 1 and 2; the select sets the other eight itself): all ten "
                    "stages start from its next look, and the game's own next save keeps them"}


def auto_qte(g: RE6Switch, on: bool = True) -> dict:
    """The game's own automatic action button (QTEs and grabs resolve with nothing pressed): cSystemInfo
    mTempData.mExOptAutoActBtn in both copies set to 1 (off: 0), that field only, read back."""
    res = _info_bits(g, AUTO_QTE, 0, value=1 if on else 0)
    g.state["auto_qte"] = bool(on)
    return {"auto_qte": bool(on), **res,
            "note": "the game's own automatic action button: every QTE site tests the option (nonzero = automatic)"}


def _gm(g: RE6Switch) -> int:
    gm = R.u64(g.m, g.base + R.S_GAMEMAN)
    return gm if R.ptr_ok(gm) else 0


def _add_clock(ad, g: RE6Switch, gm: int, seconds: float = 0.0, absolute=None) -> dict:
    """The round clock moved as the game's own time-add handler moves it: seconds added (negative takes) or set to
    `absolute`, kept within CLOCK_MIN..CLOCK_MAX, read back (the HUD's copy follows it). Only while a round is playing.
    No "+N" notice: the guessed notice fields (+0x46A0 / +0x46A4) hold other data (live 14:41: a float at +0x46A0)."""
    import math
    phase = struct.unpack("<i", ad.read_memory(gm + R.GM_PHASE, 4))[0]
    before = struct.unpack("<f", ad.read_memory(gm + GM_CLOCK, 4))[0]
    if phase != R.PHASE_PLAYING or not (math.isfinite(before) and 0.0 < before <= CLOCK_MAX + 1):
        return {"verified": False, "reason": "no round playing (phase %s, clock %s)" % (phase, round(before, 2)),
                "applied_seconds": 0.0}
    wanted = float(absolute) if absolute is not None else before + float(seconds)
    target = min(CLOCK_MAX, max(CLOCK_MIN, wanted))
    try:
        ad.write_memory(gm + GM_CLOCK, struct.pack("<f", target))
    except RuntimeError:                                     # the countdown ran a frame between the write and the read
        pass
    after = struct.unpack("<f", ad.read_memory(gm + GM_CLOCK, 4))[0]
    verified = math.isfinite(after) and target - 0.5 <= after <= target + 0.01
    delta = target - before
    return {"verified": verified, "clock_before": round(before, 2), "clock_after": round(after, 2),
            "applied_seconds": round(delta, 2) if verified else 0.0, "clamped": target != wanted,
            **({} if verified else {"reason": "the clock write was not read back"})}


def kill_time(g: RE6Switch, on: bool, seconds=None, seconds_max=None) -> dict:
    """The per-kill time bonus (RE5's kill_time): `seconds` a kill (a random whole number up to `seconds_max` when that
    is given); maintain adds them on the round clock for every new kill of sGameMan's count while a round is playing."""
    state = g.state.setdefault("kill_time", {})
    if seconds is None:
        low, high = state.get("seconds", KILL_TIME_S), state.get("seconds_max", state.get("seconds", KILL_TIME_S))
    else:
        low = float(seconds)
        high = float(seconds_max) if seconds_max is not None else low
    low, high = float(low), float(high)
    if not 0 < low <= high <= KILL_TIME_MAX_S:
        raise ValueError(f"kill_time seconds: more than 0, at most {KILL_TIME_MAX_S:g}, and the minimum first")
    state.update(on=bool(on), seconds=low, seconds_max=high, gm=None, kills=None)
    return {"kill_time": state["on"], "seconds": low, "seconds_max": high, "verified": True,
            "note": "+%g s on the round clock for every kill (the game's own time-add path, the HUD's bonus notice)"
                    % low if high == low else "+%g-%g s a kill" % (low, high)}


def _kill_seconds(state) -> float:
    import random
    low, high = state.get("seconds", KILL_TIME_S), state.get("seconds_max", state.get("seconds", KILL_TIME_S))
    if high <= low:
        return low
    if float(low).is_integer() and float(high).is_integer():
        return float(random.randint(int(low), int(high)))
    return round(random.uniform(low, high), 1)


def _maintain_kill_time(ad, g: RE6Switch, st: dict) -> dict:
    state = st.get("kill_time") or {}
    if not state.get("on"):
        return {}
    gm = _gm(g)
    if not gm:
        return {}
    kills = struct.unpack("<i", ad.read_memory(gm + R.GM_KILLS, 4))[0]
    if not 0 <= kills <= 2000:
        return {"verified": False, "reason": "kill count out of range"}
    last = state.get("kills")
    if state.get("gm") != gm or last is None or kills < last:   # a new round: count afresh
        state.update(gm=gm, kills=kills)
        return {}
    if kills == last:
        return {}
    added = sum(_kill_seconds(state) for _ in range(kills - last))
    res = _add_clock(ad, g, gm, added)
    if res.get("reason", "").startswith("no round"):
        state["kills"] = kills                               # time up: these kills are past the clock
        return {}
    state["kills"] = kills
    st["kill_time_added"] = round(st.get("kill_time_added", 0.0) + res.get("applied_seconds", 0.0), 2)
    return res | {"kills": kills, "added": added}


def add_time(g: RE6Switch, seconds=60.0) -> dict:
    """Add to (negative: take from) the round clock, read back; added time shows the HUD's bonus notice."""
    try:
        n = int(round(float(60 if seconds is None else seconds)))
    except (TypeError, ValueError):
        raise ValueError("add_time seconds: a number") from None
    if n == 0 or not ADD_TIME_RANGE[0] <= n <= ADD_TIME_RANGE[1]:
        raise ValueError("add_time seconds: -3600 .. 3600, not 0 (negative takes time away)")
    gm = _gm(g)
    if not gm:
        return {"verified": False, "reason": "no sGameMan (between rounds)", "added_seconds": 0}
    res = _add_clock(g.ad, g, gm, n)
    return res | {"requested_seconds": n, "added_seconds": int(round(res.get("applied_seconds", 0.0)))}


def set_time(g: RE6Switch, seconds) -> dict:
    try:
        n = int(round(float(seconds)))
    except (TypeError, ValueError):
        raise ValueError("set_time seconds: a number") from None
    if not SET_TIME_RANGE[0] <= n <= SET_TIME_RANGE[1]:
        raise ValueError("set_time seconds: 1 .. 3600")
    gm = _gm(g)
    if not gm:
        return {"verified": False, "reason": "no sGameMan (between rounds)"}
    return _add_clock(g.ad, g, gm, absolute=n) | {"set_seconds": n}


def struggle_units(g: RE6Switch, index: int = 0) -> list[dict]:
    """Player `index`'s live action-button units: in sActionButton's ButtonMgr for the player, active, its button a
    cActionButton - {unit, button, type, outcome, new, target, progress}."""
    import math
    sab = R.u64(g.m, g.base + S_ACTBTN)
    if not R.ptr_ok(sab) or R.class_name(g.m, sab) != "sActionButton":
        return []
    mgr = sab + AB_MGRS + AB_MGR_STRIDE * index
    if R.class_name(g.m, mgr) != "sActionButton::ButtonMgr":
        return []
    out = []
    for off in MGR_UNITS:
        u = mgr + off
        raw = g.ad.read_memory(u, 0x48)
        btn = struct.unpack_from("<Q", raw, UNIT_BUTTON)[0]
        if not raw[UNIT_ACTIVE] or not R.ptr_ok(btn) or R.class_name(g.m, btn) != "cActionButton":
            continue
        target, prog = struct.unpack_from("<2f", raw, UNIT_TARGET)
        out.append({"unit": u, "button": btn, "type": struct.unpack_from("<I", raw, UNIT_TYPE)[0],
                    "outcome": struct.unpack_from("<I", raw, UNIT_OUTCOME)[0], "new": raw[UNIT_NEW],
                    "target": target if math.isfinite(target) else None, "progress": prog if math.isfinite(prog) else None})
    return out


def _complete_struggle(ad, g: RE6Switch, player: int) -> int:
    """While a zombie holds him (action 8 / 9 / 25): each live struggle unit given the game's own escape - a chance
    button's rolled outcome set to 0 (free at once) once the roll is done, a mash button's progress up to its target."""
    try:
        state = ad.read_memory(player + R.P_STATE, 1)[0]
    except (ValueError, OSError):
        return 0
    if state not in R.HELD_STATES:
        return 0
    n = 0
    for x in struggle_units(g):
        if x["type"] in CHANCE_TYPES:
            if x["new"] or x["outcome"] == 0 or x["outcome"] > 4:
                continue
            addr, data = x["unit"] + UNIT_OUTCOME, struct.pack("<I", 0)
            rolled = g.state.setdefault("qte_rolled", [])    # what the game had rolled (4: the bite)
            rolled.append(x["outcome"])
            del rolled[:-QTE_ROLLED_N]
        elif (x["target"] is not None and x["progress"] is not None and 0.0 < x["target"] <= QTE_TARGET_MAX
              and x["progress"] < x["target"]):
            addr, data = x["unit"] + UNIT_PROGRESS, struct.pack("<f", x["target"])
        else:
            continue
        try:
            ad.write_memory(addr, data)
        except RuntimeError:                                 # the game took it from there (granted, the unit reset)
            pass
        n += 1
    return n


def auto_qte_ram(g: RE6Switch, on: bool = True) -> dict:
    g.state["auto_qte_ram"] = bool(on)
    p = R.snapshot(g.m).get("player")
    units = struggle_units(g) if p else []
    return {"auto_qte_ram": bool(on), "verified": True, "units": len(units),
            "note": "while a zombie holds him, the grab's action button gets the escape the game itself grants: a "
                    "chance button's rolled outcome set to 0 (free at once), a mash button's progress up to its target"}


def unlock_characters(g: RE6Switch, on: bool = True) -> dict:
    """Every character and costume in the Mercenaries select: only the mask's two u32 in cSystemInfo (copy A, copy B)
    are written, each read first and read back after; nothing to do once both hold every bit. Off changes nothing
    (an unlock is the save's: the game's own next save keeps it)."""
    from ... import re6_switch_unlock as U
    info = U.system_info(g.m, g.base)
    if info is None:
        return {"unlock_characters": bool(on), "verified": False, "reason": "no cSystemInfo yet (still booting)"}
    before = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in CHARACTER_MASK]
    writes = 0
    if on:
        for off, value in zip(CHARACTER_MASK, before):
            if value & ALL_CHARACTERS != ALL_CHARACTERS:
                g.ad.write_memory(info + off, struct.pack("<I", value | ALL_CHARACTERS))
                writes += 1
    after = [struct.unpack("<I", g.ad.read_memory(info + off, 4))[0] for off in CHARACTER_MASK]
    g.state["unlock_characters"] = bool(on)
    return {"unlock_characters": bool(on), "verified": not on or all(v & ALL_CHARACTERS == ALL_CHARACTERS for v in after),
            "before": [hex(v) for v in before], "after": [hex(v) for v in after], "writes": writes,
            "note": "the character select's mask in both cSystemInfo copies; the select lists every character and "
                    "costume from its next opening, and the game's own next save keeps it"}


# Quick attacks x10 (operator 2026-10-27 15:31: "for the quick attack in RE6, allow the bot to do it 10x faster and in rapid
# succession"): a unit's own clock rate is cUnit::mDeltaTime (Ghidra: cUnit's property registration main+0x1240228
# names it at this + 0x30; live 1.0 on the player), and the unit's current action sits at +0x13F0 (live: the player's
# cEmActionGrap_PL while held). While his action is a quick shot or a physical attack (QUICK_ACTIONS) quick_attack
# keeps his mDeltaTime at the multiplier - the whole move, its recovery included, runs that much faster - and puts 1.0
# back as soon as he is in any other action; it only ever writes over 1.0 or its own value (a game's slow-motion is left
# alone), each write read back. status quick_attacks counts the quick attacks it sped up.
UNIT_DELTA, UNIT_ACTION = 0x30, 0x13F0
QUICK_ACTIONS = frozenset({"cPlAction_pl_act_attack_ex", "cPlAction_pl_act_weapon_comn_quick_shot",
                           "cPlAction_pl_act_jake_hand_quick_attack"})
QUICK_MAX = 10.0


def quick_attack(g: RE6Switch, mult=10.0) -> dict:
    try:
        k = float(10.0 if mult is None else mult)
    except (TypeError, ValueError):
        raise ValueError("quick_attack multiplier: 1..10 (1 = the game's)") from None
    if not 1.0 <= k <= QUICK_MAX:
        raise ValueError("quick_attack multiplier: 1..10 (1 = the game's)")
    g.state["quick_attack"] = k
    from . import re6_switch as B
    B.QA_FAST = k > 1.0
    return {"quick_attack_x": k, "verified": True,
            "note": "his quick shots and physical attacks run %gx (cUnit mDeltaTime +0x30 while his action +0x13F0 is "
                    "one of them, 1.0 back after)" % k}


def weapon_names(g: RE6Switch) -> dict:
    """{id: name} for the weapons: the game's own message table (mes_item) when it can be found, else WEAPON_NAMES."""
    names = dict(WEAPON_NAMES)
    try:
        sr = R.u64(g.m, g.base + R.SRES)
        blk = g.ad.read_memory(sr, R.SRES_SIZE)
        seen = set()
        for o in range(0, len(blk), 8):
            v = struct.unpack_from("<Q", blk, o)[0]
            if v in seen or not R.ptr_ok(v) or g.base <= v < g.base + 0x3000000:
                continue
            seen.add(v)
            path = g.ad.read_memory(v + 0xC, 0x30).split(b"\0")[0]
            if not path.startswith(b"soft\\message\\mes_item_"):
                continue
            n = struct.unpack("<I", g.ad.read_memory(v + 0xA0, 4))[0]
            arr = struct.unpack("<Q", g.ad.read_memory(v + 0xC0, 8))[0]
            if not (41 <= n <= 4096 and R.ptr_ok(arr)):
                break
            ptrs = struct.unpack("<41Q", g.ad.read_memory(arr, 8 * 41))
            for i in WEAPON_NAMES:
                txt = g.ad.read_memory(ptrs[i], 64).split(b"\0")[0].decode("utf-8", "replace").strip()
                if txt and "dummy" not in txt:
                    names[i] = txt
            break
    except (ValueError, OSError, struct.error):
        pass
    return names


def weapon_list(g: RE6Switch, player: int | None = None) -> list:
    """Every weapon the live switch knows: [{id, type, name, kind, loaded (in his weapon slots now), wheel_index}]."""
    names = weapon_names(g)
    loaded = {}
    if player:
        try:
            loaded = R.inventory_guns(g.m, player)
        except (ValueError, OSError):
            loaded = {}
    return [{"id": i, "type": 0x100 + i, "name": names.get(i, WEAPON_NAMES[i]), "kind": WEAPON_KIND.get(i, "weapon"),
             "loaded": (0x100 + i) in loaded, "wheel_index": loaded.get(0x100 + i)} for i in sorted(WEAPON_NAMES)]


def _resolve_weapon(weapon) -> int:
    if isinstance(weapon, int) or (isinstance(weapon, str) and weapon.strip().lstrip("-").isdigit()):
        wid = int(weapon)
        wid = wid - 0x100 if wid >= 0x100 else wid
    else:
        want = str(weapon or "").strip().casefold()
        wid = next((i for i, n in WEAPON_NAMES.items() if n.casefold() == want), None)
        if wid is None:
            wid = next((i for i, n in WEAPON_NAMES.items() if want and want in n.casefold()), None)
    if wid not in WEAPON_NAMES:
        raise ValueError("live_weapon: one of %s (an id 0-40 or a name)" % ", ".join(sorted(set(WEAPON_NAMES.values()))))
    return wid


def live_weapon(g: RE6Switch, weapon) -> dict:
    """The weapon he fights with, now: a gun in his weapon slots (loaded at the round's set-up) is switched to at once by
    the game's own weapon switch (the bot's D-pad, WANT_WEAPON); one not loaded goes into every loadout for the next
    round (merc_loadout spread / next_weapon) - never written into a slot now (its model would not be loaded)."""
    wid = _resolve_weapon(weapon)
    t = 0x100 + wid
    from . import re6_switch as B
    g.state["live_weapon_sets"] = g.state.get("live_weapon_sets", 0) + 1
    snap = R.snapshot(g.m)
    p = snap.get("player") or {}
    guns = R.inventory_guns(g.m, p["ptr"]) if p.get("ptr") else {}
    name = WEAPON_NAMES[wid]
    if t in guns:
        B.WANT_WEAPON, B.WANT_WEAPON_AT = guns[t], time.monotonic()
        return {"verified": True, "weapon": name, "type": hex(t), "loaded": True, "wheel_index": guns[t],
                "live_weapon_sets": g.state["live_weapon_sets"],
                "note": "loaded this round: the bot switches to it now (the game's own weapon switch)"}
    g.state["next_weapon"] = t
    ASKED.add((t, WEAPON_MAG.get(t, 10)))
    return {"verified": True, "weapon": name, "type": hex(t), "loaded": False, "next_round": True,
            "live_weapon_sets": g.state["live_weapon_sets"],
            "note": "not loaded this round: in every loadout from the next round set-up (then switched to)"}


def magnum_speed(g: RE6Switch, mult) -> dict:
    """The magnum's fire and recoil at mult (his mDeltaTime while weapon_fire runs with a magnum in hand); 1 = off."""
    try:
        k = float(mult if mult is not None else MAGNUM_SPEED_X)
    except (TypeError, ValueError):
        raise ValueError("magnum_speed multiplier: a number 1..%g (1 = off)" % MAGNUM_SPEED_MAX) from None
    if not 1.0 <= k <= MAGNUM_SPEED_MAX:
        raise ValueError("magnum_speed multiplier: 1..%g (1 = off)" % MAGNUM_SPEED_MAX)
    g.state["magnum_speed"] = k
    return {"verified": True, "magnum_speed_x": k}


def _keep_quick(ad, g: RE6Switch, player: int, st: dict, weapon=None) -> int:
    """mDeltaTime at the multiplier while his action is a quick attack, at the magnum's while the gun's fire runs with a
    magnum in hand, 1.0 otherwise (only over 1.0 or one of its own values)."""
    k = st.get("quick_attack") or 1.0
    mk = (st.get("magnum_speed", MAGNUM_SPEED_X) or 1.0) if st.get("fire_rate") else 1.0
    tk = (st.get("throw_speed", THROW_SPEED_X) or 1.0) if st.get("fire_rate") else 1.0
    try:
        act = R.u64(g.m, player + UNIT_ACTION)
        name = None
        if R.ptr_ok(act):
            vt = R.u64(g.m, act)
            names = st.setdefault("qa_names", {})
            if vt not in names:
                names[vt] = R.class_name(g.m, act)
            name = names[vt]
        cur = struct.unpack("<f", ad.read_memory(player + UNIT_DELTA, 4))[0]
    except (ValueError, OSError):
        return 0
    quick = name in QUICK_ACTIONS
    if quick and not st.get("qa_in"):
        st["quick_attacks"] = st.get("quick_attacks", 0) + 1
    magnum = mk > 1.0 and name in MAGNUM_FIRE_ACTIONS and weapon in MAGNUM_RECORDS
    throw = tk > 1.0 and name in MAGNUM_FIRE_ACTIONS and weapon in THROW_RECORDS
    if magnum and not st.get("mag_in"):
        st["magnum_fast"] = st.get("magnum_fast", 0) + 1
    if throw and not st.get("throw_in"):
        st["throw_fast"] = st.get("throw_fast", 0) + 1
    st["qa_in"], st["mag_in"], st["throw_in"] = quick, magnum, throw
    want = k if quick else mk if magnum else tk if throw else 1.0
    if abs(cur - want) < 1e-4 or not any(abs(cur - v) < 1e-4 for v in (1.0, k, mk, tk)):
        return 0
    try:
        ad.write_memory(player + UNIT_DELTA, struct.pack("<f", want))   # read back by the adapter
    except RuntimeError:
        return 0
    return 1


def bot_options(g: RE6Switch, nades=None, bomb_drop=None, aim_lock=None, flash=None) -> dict:
    """The bot's switches a profile turns on (playing_ops): nades - the flash at 3+ within 4 m with the melee fever after
    it, the hand / incendiary grenade into a cluster; bomb_drop - the remote bomb dropped while backing out of a crowd;
    aim_lock - the RAM aim lock (the player camera's yaw / pitch written onto the target; off: the camera keys). None
    leaves a switch as it is. Nothing is written to the game here."""
    from . import re6_switch as B
    if nades is not None:
        B.NADES = bool(nades)
    if bomb_drop is not None:
        B.BOMB_DROP = bool(bomb_drop)
    if aim_lock is not None:
        B.AIM_LOCK = bool(aim_lock)
    if flash is not None:
        B.FLASH = bool(flash)
    return {"verified": True, "nades": B.NADES, "bomb_drop": B.BOMB_DROP, "aim_lock": B.AIM_LOCK, "flash": B.FLASH}


def down_fire(g: RE6Switch, mult) -> dict:
    """The factor on fire_rate's multipliers while he is down (maintain applies and restores it); 1 = off."""
    try:
        k = float(mult if mult is not None else DOWN_FIRE_X)
    except (TypeError, ValueError):
        raise ValueError("down_fire multiplier: a number 1..%g (1 = off)" % DOWN_FIRE_MAX) from None
    if not 1.0 <= k <= DOWN_FIRE_MAX:
        raise ValueError("down_fire multiplier: 1..%g (1 = off)" % DOWN_FIRE_MAX)
    g.state["down_fire"] = k
    return {"verified": True, "down_fire_x": k}


def is_down(p: dict | None, was: bool = False) -> bool:
    """Down by his action: one of re6_switch.DOWN_ACTIONS, or one of DOWN_KEEP while already down (or at 1 health)."""
    from . import re6_switch as B
    act = (p or {}).get("action")
    return act in B.DOWN_ACTIONS or (act in B.DOWN_KEEP and (was or (p or {}).get("hp") == B.DYING_HP))


def _keep_down_fire(ad, g: RE6Switch, p: dict, st: dict) -> int:
    """The weapon table at down_fire x fire_rate's multipliers while he is down, fire_rate's own once he is up; written
    only on the change, each cell read back by the adapter."""
    down = is_down(p, bool(st.get("down_on")))
    if down == bool(st.get("down_on")):
        return 0
    k = st.get("down_fire", DOWN_FIRE_X) or 1.0
    base, mag, thr = st.get("fire_rate", 1.0), st.get("fire_magnum"), st.get("fire_throw")
    if down:
        want_k, want_mag = min(FIRE_MAX, base * k), min(FIRE_MAX, (mag or base) * k)
    else:
        want_k, want_mag = base, mag
    recs = fire_records(g)
    if recs is None:
        return 0
    n = 0
    try:
        for i, addr, cur in recs:
            want = _f32(fire_interval(i, want_k, want_mag, thr))
            if cur != want:
                ad.write_memory(addr, struct.pack("<f", want))   # read back by the adapter
                n += 1
    except RuntimeError:
        return n
    st["down_on"] = down
    st["down_fire_switches"] = st.get("down_fire_switches", 0) + 1
    return n


def fire_interval(index: int, k: float, magnum: float | None = None, throw: float | None = None) -> float:
    """Record index's seconds between shots at multiplier k: this build's value / k for a gun (never below FIRE_FLOOR),
    / magnum for the magnums when that is given, / throw for the three grenades when that is given; the build's own for
    the remote bomb, the knife and the melee weapons (and at k=1 with neither)."""
    orig = FIRE_ORIGINAL[index]
    if index in THROW_RECORDS and throw and throw > 1.0:
        return max(FIRE_FLOOR, orig / throw)
    if index in MAGNUM_RECORDS and magnum and magnum > 1.0:
        return max(FIRE_FLOOR, orig / magnum)
    if k == 1.0 or index in FIRE_SKIP or not 0.0 < orig < FIRE_GUN_MAX:
        return orig
    return max(FIRE_FLOOR, orig / k)


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def fire_records(g: RE6Switch) -> list[tuple[int, int, float]] | None:
    """The weapon table's interval cells [(index, address, seconds)], or None when this is not the build's table: the
    interval's reader at FIRE_SITE must be its ldr, every record must carry the table's tag and the same first word,
    and every interval must be the build's own or one fire_rate writes (at most the build's)."""
    try:
        if struct.unpack("<I", g.ad.read_memory(g.base + FIRE_SITE, 4))[0] != FIRE_SITE_WORD:
            return None
        raw = g.ad.read_memory(g.base + FIRE_TABLE, FIRE_STRIDE * FIRE_RECORDS)
    except (ValueError, OSError):
        return None
    first = raw[:4]
    out = []
    for i in range(FIRE_RECORDS):
        o = FIRE_STRIDE * i
        if raw[o:o + 4] != first or struct.unpack_from("<i", raw, o + FIRE_TAG)[0] != FIRE_TAG_VALUE:
            return None
        cur = struct.unpack_from("<f", raw, o + FIRE_INTERVAL)[0]
        if not (cur == _f32(FIRE_ORIGINAL[i]) or FIRE_FLOOR * 0.999 <= cur <= FIRE_ORIGINAL[i] * 1.0001):
            return None
        out.append((i, g.base + FIRE_TABLE + o + FIRE_INTERVAL, cur))
    return out


def fire_rate(g: RE6Switch, mult, magnum=None, throw=None) -> dict:
    try:
        k = float(mult if mult is not None else FIRE_MAX)
        magnum = float(magnum) if magnum is not None else None
        throw = float(throw) if throw is not None else None
    except (TypeError, ValueError):
        raise ValueError("fire_rate multiplier / magnum / throw: numbers 1..80 (1 = the game's)") from None
    if not 1.0 <= k <= 80.0 or any(x is not None and not 1.0 <= x <= 80.0 for x in (magnum, throw)):
        raise ValueError("fire_rate multiplier / magnum / throw: 1..80 (1 = the game's)")
    k = min(k, FIRE_MAX)                                     # the operator's cap per weapon (2026-10-28: 5x): clamped
    magnum = min(magnum, FIRE_MAX) if magnum is not None else None
    throw = min(throw, FIRE_MAX) if throw is not None else None
    recs = fire_records(g)
    if recs is None:
        return {"fire_rate_x": g.state.get("fire_rate", 1.0), "verified": False, "writes": 0,
                "reason": "the weapon table is not this build's (its reader at main+%#x or a record differs): nothing "
                          "written" % FIRE_SITE}
    writes = 0
    for i, addr, cur in recs:
        want = _f32(fire_interval(i, k, magnum, throw))
        if cur != want:
            g.ad.write_memory(addr, struct.pack("<f", want))      # read back by the adapter
            writes += 1
    g.state["fire_rate"] = k
    g.state["fire_magnum"], g.state["fire_throw"] = magnum, throw
    rifle = _f32(fire_interval(0x0F, k))
    return {"fire_rate_x": k, "magnum_x": magnum, "throw_x": throw, "verified": True, "writes": writes,
            "assault_rifle_interval_s": round(rifle, 4),
            "magnum_interval_s": round(_f32(fire_interval(0x07, k, magnum)), 4),
            "grenade_interval_s": round(_f32(fire_interval(0x13, k, magnum, throw)), 4),
            "note": "the game's own seconds between shots (weapon table +0x1C) at the build's / %g for every gun; the "
                    "grenades, the remote bomb, the knife and the melee weapons keep theirs" % k}


def _top_up(ad, g: RE6Switch, player: int) -> int:
    n = 0
    for slot, rounds, cap in g.slots(player):
        if 0 <= rounds < cap:
            _put_count(ad, slot + SLOT_ROUNDS, cap)
            n += 1
    return n


def maintain(ad, snap=None, *, enabled: bool = True, clock=time.monotonic) -> dict:
    """Each driver snapshot: infinite_ammo's magazines topped up, infinite_tablets' case and infinite_stamina's gauge kept
    (at most every CHECK_S), only into the snapshot's own player; never raises."""
    with _LOCK:
        st = ORIG.get(id(ad))
        out = {"active": False, "writes": 0, "verified": True}
        down_fire_on = bool(st and st.get("fire_rate") and ((st.get("down_fire", DOWN_FIRE_X) or 1.0) > 1.0
                                                            or st.get("down_on")))
        keeping = st and any(st.get(k) for k in ("infinite_ammo", "infinite_tablets", "infinite_stamina",
                                                 "infinite_grenades", "auto_qte_ram")) or \
            st and ((st.get("kill_time") or {}).get("on") or (st.get("quick_attack") or 1.0) > 1.0) or down_fire_on
        mag_on = bool(st and st.get("fire_rate") and ((st.get("magnum_speed", MAGNUM_SPEED_X) or 1.0) > 1.0
                                                      or (st.get("throw_speed", THROW_SPEED_X) or 1.0) > 1.0
                                                      or st.get("mag_in") or st.get("throw_in")))
        keeping = keeping or mag_on
        if not keeping or not enabled:
            return out
        try:
            p = (snap or {}).get("player")
            now = clock()
            if p and ((st.get("kill_time") or {}).get("on") or st.get("auto_qte_ram")
                      or (st.get("quick_attack") or 1.0) > 1.0 or st.get("qa_in") or down_fire_on or mag_on):
                g0 = RE6Switch(ad)
                if down_fire_on:
                    out["writes"] += _keep_down_fire(ad, g0, p, st)
                if (st.get("quick_attack") or 1.0) > 1.0 or st.get("qa_in") or mag_on:
                    out["writes"] += _keep_quick(ad, g0, p["ptr"], st, p.get("weapon_id"))
                if (st.get("kill_time") or {}).get("on"):
                    kt = _maintain_kill_time(ad, g0, st)
                    if kt.get("applied_seconds"):
                        out["writes"] += 1
                        out["kill_time"] = kt
                if st.get("auto_qte_ram"):
                    done = _complete_struggle(ad, g0, p["ptr"])
                    st["struggles_completed"] = st.get("struggles_completed", 0) + done
                    out["writes"] += done
            if p and now - st.get("ammo_at", -1e9) >= CHECK_S:
                st["ammo_at"] = now
                g = RE6Switch(ad)
                if st.get("infinite_ammo"):
                    out["writes"] += _top_up(ad, g, p["ptr"])
                if st.get("infinite_tablets"):
                    kept = _keep_tablets(ad, g, p["ptr"])
                    st["tablets_kept"] = st.get("tablets_kept", 0) + kept
                    out["writes"] += kept
                if st.get("infinite_grenades"):
                    out["writes"] += _keep_thrown(ad, g, p["ptr"])
                if st.get("infinite_stamina"):
                    kept = _keep_stamina(ad, p["ptr"])
                    st["stamina_kept"] = st.get("stamina_kept", 0) + kept
                    out["writes"] += kept
            out["active"] = True
        except Exception as e:                               # noqa: BLE001 - a missed top-up never stops a tick
            out.update(verified=False, reason=f"{type(e).__name__}: {e}"[:160])
        return out


def run(ad, op: str = "status", multiplier=None, on: bool = True, g: RE6Switch | None = None, **_extra) -> dict:
    with _LOCK:
        g = g or RE6Switch(ad)
        op = (op or "status").strip().lower().replace(" ", "_").replace("-", "_")
        op = {"fire": "fire_rate", "rapid_fire": "fire_rate", "rain_fire": "fire_rate", "ammo": "infinite_ammo",
              "unlimited_ammo": "infinite_ammo",
              "no_ammo": "infinite_ammo", "tablets": "infinite_tablets", "infinite_heal": "infinite_tablets",
              "heal_keep": "infinite_tablets", "stamina": "infinite_stamina", "combat_gauge": "infinite_stamina",
              "unlimited_stamina": "infinite_stamina", "characters": "unlock_characters", "loadout": "merc_loadout",
              "loadouts": "merc_loadout", "no_rocket": "merc_loadout", "grenades": "infinite_grenades",
              "infinite_mines": "infinite_grenades", "remote_bombs": "infinite_grenades", "stages": "unlock_stages",
              "all_stages": "unlock_stages", "qte": "auto_qte", "auto_action": "auto_qte",
              "kill_time_bonus": "kill_time", "time_per_kill": "kill_time", "qte_ram": "auto_qte_ram",
              "auto_struggle": "auto_qte_ram",
              "all_characters": "unlock_characters", "unlock_all": "unlock_characters"}.get(op, op)
        if op == "status":
            return g.status()
        if op == "infinite_ammo":
            return infinite_ammo(g, bool(on))
        if op == "infinite_tablets":
            return infinite_tablets(g, bool(on))
        if op == "infinite_stamina":
            return infinite_stamina(g, bool(on))
        if op == "infinite_grenades":
            return infinite_grenades(g, bool(on))
        if op == "unlock_characters":
            return unlock_characters(g, bool(on))
        if op == "kill_time":
            return kill_time(g, bool(on), _extra.get("seconds"), _extra.get("seconds_max"))
        if op == "add_time":
            return add_time(g, _extra.get("seconds", 60))
        if op == "set_time":
            return set_time(g, _extra.get("seconds"))
        if op == "auto_qte_ram":
            return auto_qte_ram(g, bool(on))
        if op == "unlock_stages":
            return unlock_stages(g, bool(on))
        if op == "auto_qte":
            return auto_qte(g, bool(on))
        if op == "merc_loadout":
            return merc_loadout(g, bool(on), rocket=_extra.get("rocket", True) not in (False, "keep", "off"),
                                thrown=_extra.get("thrown", THROWN_MAX), seed=_extra.get("seed"),
                                magnum=_extra.get("magnum", False) not in (False, None, "off", 0),
                                spread=_extra.get("spread", False) not in (False, None, "off", 0))
        if op == "quick_attack":
            return quick_attack(g, 1.0 if on is False else (multiplier if multiplier is not None else 10.0))
        if op == "bot_options":
            return bot_options(g, nades=_extra.get("nades"), bomb_drop=_extra.get("bomb_drop"),
                               aim_lock=_extra.get("aim_lock"), flash=_extra.get("flash"))
        if op in ("live_weapon", "weapon", "set_weapon"):
            return live_weapon(g, _extra.get("weapon", multiplier))
        if op in ("weapons", "weapon_list"):
            snap = R.snapshot(g.m)
            p = snap.get("player") or {}
            return {"verified": True, "weapons": weapon_list(g, p.get("ptr")),
                    "next_weapon": hex(g.state["next_weapon"]) if g.state.get("next_weapon") else None}
        if op == "magnum_speed":
            return magnum_speed(g, 1.0 if on is False else multiplier)
        if op == "throw_speed":
            k = float(1.0 if on is False else (multiplier if multiplier is not None else THROW_SPEED_X))
            if not 1.0 <= k <= THROW_SPEED_MAX:
                raise ValueError("throw_speed multiplier: 1..%g (1 = off)" % THROW_SPEED_MAX)
            g.state["throw_speed"] = k
            return {"verified": True, "throw_speed_x": k}
        if op == "down_fire":
            return down_fire(g, 1.0 if on is False else multiplier)
        if op == "fire_rate":
            if on is False:
                return fire_rate(g, 1.0)
            return fire_rate(g, multiplier, magnum=_extra.get("magnum"), throw=_extra.get("throw"))
        if op == "revert_all":
            return {"infinite_ammo": infinite_ammo(g, False), "infinite_tablets": infinite_tablets(g, False),
                    "infinite_stamina": infinite_stamina(g, False), "infinite_grenades": infinite_grenades(g, False),
                    "kill_time": kill_time(g, False), "auto_qte_ram": auto_qte_ram(g, False),
                    "fire_rate": fire_rate(g, 1.0),
                    "merc_loadout": merc_loadout(g, False)}
        raise ValueError(f"re6_switch_mods: unknown op {op!r} (status, infinite_ammo, infinite_tablets, "
                         "infinite_stamina, infinite_grenades, unlock_characters, unlock_stages, auto_qte, auto_qte_ram, "
                         "kill_time, add_time, set_time, fire_rate, merc_loadout, revert_all)")
