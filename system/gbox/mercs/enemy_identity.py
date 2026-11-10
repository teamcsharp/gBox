"""Who each enemy is, per title (operator 2026-11-10: "make sure that the map and the bot enemy analysis is able to
identify what enemy is who in the game and have the bot prioritize dispatching boss level foes and dangerous
opponents ... profile pictures of the enemies with names in the live map ... a sidebar with listings and details on
each and every enemy type and what the wiki says about them").

    from gbox.mercs import enemy_identity as EI
    EI.tier(title_id, cls)                       # "boss" / "dangerous" / "normal" / "harmless" (None: not known)
    EI.weight(title_id, cls)                     # TIER_WEIGHT of that tier (1.0 when not known)
    EI.resolve(title_id, enemy_row, stage=None)  # {cls, name, tier, weight, level, ...} for a snapshot / frame row
    EI.identity(title_id, cls)                   # the full entry (name, aliases, danger, weak point, tactics, ...)
    EI.listing(title_id)                         # every entry of the title (the API's sidebar listing)
    EI.stage_info(title_id, stage) / EI.next_heavy(title_id, stage, kills)   # RE5's per-stage table: the heavies

**The key** is what the title's bot reads: RE5 and RE6 the enemy's RAM class (its vtable's DTI name: `uEm20`,
`uEm3200`); RE4 Switch an identity key (`salvador`, `jj` ...) from the unit's type byte (+0x3CE) and its maximum
health, because every Ganado of RE4 Switch is one RAM class (0xAE7050) - the set lists (`etc/omake0N.esl`) give each
stage's types and health and RE4's type byte selects them (`re4_switch_enemies.read_esl`).

**How sure** (`level`): "verified" - seen and named live (a frame, the reviewer); "matched" - the game's own data
agrees with the guide: the stage set lists' per-class counts (docs/research/re5-enemy-cast.md, re6-parity.md, the RE4
ESLs) equal the guide's spawns, and the maximum health the bot read live equals the guide's; "inferred" - one such fact;
"unconfirmed" - a reading of the stage it appears on and its model, nothing more. `confirmed` is level in (verified,
matched). The model portraits (gbox/mercs/enemy_portraits.py, rendered from each class archive) are the check anyone
can repeat for the rest.

**Sources** (the text is ours, paraphrased in a line or two; each entry lists its URLs): evilresource.com's enemy pages
(names, what they do), the RE5 Mercenaries data post that cites the official guide (health, spawns by kill count, time
bonuses, the combo table) and the Steam Mercenaries guide (tactics, per-character notes). The neoseeker stats FAQ the
operator named refused the fetch (HTTP 403) on 2026-11-10; its URL stays in SOURCES so a later fetch can fill in.

**Bot priority** (`TIER_WEIGHT`, boss > dangerous > normal > harmless). The shared target scorer (gbox/mercs/core/
combat.py, branch mercs-universal-core) and each title's own pick should call `weight(title, cls)` (or
`resolve(title, enemy)["weight"]`) where they rank targets - see CALL_SITES.
"""
from __future__ import annotations

import re

RE5, RE6, RE4 = "010018100CD46000", "01002A000CD48000", "010099A00BC1E000"
ALIASES = {"BLUS30491": RE5, "G4BE08": RE4}         # RE5 PS3 reads the same uEm classes; RE4 GameCube the em/type keys

TIERS = ("boss", "dangerous", "normal", "harmless")
TIER_WEIGHT = {"boss": 3.0, "dangerous": 2.0, "normal": 1.0, "harmless": 0.0}
UNKNOWN_WEIGHT = 1.0
LEVELS = ("verified", "matched", "inferred", "unconfirmed")
#: A class not in the table is tiered by its maximum health (title: (boss at or above, dangerous at or above)).
HP_TIERS = {RE5: (4000, 1500), RE6: (3000, 900), RE4: (2000, 1200)}

ER5 = "https://www.evilresource.com/resident-evil-5/enemies/"
ER6 = "https://www.evilresource.com/resident-evil-6/enemies/"
ER4 = "https://www.evilresource.com/resident-evil-4/enemies/"
MERCS5_DATA = "https://residentevil5zone.blogspot.com/2010/11/resident-evil-5-mercenaries-info.html"
MERCS5_STEAM = "https://steamcommunity.com/sharedfiles/filedetails/?id=1224696225"
NEOSEEKER5 = "https://www.neoseeker.com/resident-evil-5/faqs/241725-mercenaries-stat.html"
SOURCES = {
    ER5.rstrip("/"): "enemy names and what they do (fetched 2026-11-10)",
    ER6.rstrip("/"): "enemy names and what they do (fetched 2026-11-10)",
    ER4.rstrip("/"): "enemy names and what they do (fetched 2026-11-10)",
    MERCS5_DATA: "RE5 Mercenaries health, spawns by kill count, time bonuses, combo table - cites the official guide",
    MERCS5_STEAM: "RE5 Mercenaries rules, boss tactics, per-character notes",
    NEOSEEKER5: "RE5 Mercenaries stats FAQ (operator's link) - refused the fetch, HTTP 403, 2026-11-10",
}

#: Where each bot should weigh its targets by tier (the minimal hook; this module never edits a bot).
CALL_SITES = {
    RE5: "gbox/mercs/titles/re5_switch.py Bot._choose (the threat-first pick) and Bot._threat_d (divide the threat "
         "distance by weight(RE5, e['class']) so a boss at 8 m outranks a Majini at 3 m only past THREAT_NEAR_R)",
    RE6: "gbox/mercs/titles/re6_switch.py Bot._choose: the BIG_HP focus list (`big = [...]`) becomes "
         "`tier(RE6, e['class']) in ('boss', 'dangerous') or hp_max >= BIG_HP`, ranked by -weight then distance",
    RE4: "gbox/mercs/titles/re4_switch.py Bot._choose (rank by -resolve(RE4, e)['weight'] then distance) and "
         "Bot._heavy_keep (a 'boss' tier replaces hp_max >= HEAVY_HP: the chainsaws, J.J., the Garrador)",
    "shared": "gbox/mercs/core/combat.py (branch mercs-universal-core): score = base / weight, weight from "
              "resolve(title, enemy)['weight']; harmless (0.0) are never chosen while anything else lives",
}


def _e(cls, name, tier, danger, weak, tactics, *, aliases=(), hp=None, stages=(), level="unconfirmed", evidence="",
       sources=(), variants=(), spawns=None, kind=None, notes=None, ram_class=True) -> dict:
    assert tier in TIERS and level in LEVELS, (cls, tier, level)
    out = {"cls": cls, "name": name, "aliases": list(aliases), "tier": tier, "danger": danger, "weak_point": weak,
           "tactics": list(tactics), "hp": hp, "stages": list(stages), "level": level,
           "confirmed": level in ("verified", "matched"), "evidence": evidence, "sources": list(sources),
           "variants": [dict(v) for v in variants], "ram_class": ram_class}
    if spawns:
        out["spawns"] = spawns
    if kind:
        out["kind"] = kind
    if notes:
        out["notes"] = notes
    return out


# --- Resident Evil 5 (Switch 010018100CD46000; the PS3's BLUS30491 reads the same classes) ------------------------------
_RE5_TOWN = ("Public Assembly", "The Mines", "Missile Area", "Ship Deck", "Prison")
_RE5 = [
    _e("uEm10", "Majini", "normal",
       "Comes in crowds; one holds you while the others swing, and the throwers (dynamite, bottles, crossbows) hit "
       "from range.", "head (stagger) or a knee",
       ["Head or knee shot to stagger, then melee (+5 s)", "Shoot a lit dynamite stick in his hand: it takes out "
        "the group", "A clump: grenade or an explosive barrel", "Head criticals can hatch a Cephalo - a knee shot "
        "and melee avoids it"],
       aliases=("Town Majini", "Kijuju Majini", "Dynamite Majini", "Bowgun Majini"), hp=800, stages=_RE5_TOWN,
       level="verified", evidence="named live (gbox/mercs/enemy_kinds.py); live maximum 800, the guide's male "
       "Majini; the bulk of every town stage's set list (Public Assembly 121, Prison 130 ...)",
       sources=(ER5 + "town-majini", MERCS5_DATA), kind="majini"),
    _e("uEm11", "Majini (female)", "normal",
       "The town women: fast grabs in a crowd; some carry bottles to throw.", "head or a knee",
       ["Stagger with a head or knee shot, then melee", "The red- and green-dress women at the start hatch a "
        "Cephalo half the time: kill them cleanly"],
       aliases=("Town Majini", "Female Majini"), hp=700, stages=("Public Assembly",), level="verified",
       evidence="named live (enemy_kinds); live maximum 700 (the guide's women); Public Assembly's set list 24",
       sources=(ER5 + "town-majini", MERCS5_DATA), kind="majini"),
    _e("uEm12", "Wetlands Majini", "normal",
       "Long jumps and high endurance; spears and explosive arrows from range, shield bearers block shots.",
       "head; the legs around a shield",
       ["Head shot, then melee", "Kill the explosive-arrow archers first", "A shield bearer: shoot his legs or "
        "wait for the shield to drop", "Torch Majini (1500): shotgun or magnum, a flash ready for its Plaga"],
       aliases=("Ndipaya Majini", "Torch Majini", "Shield Majini"), hp=700, stages=("Village", "Ancient Ruins"),
       level="matched", evidence="the Village (125) and Ancient Ruins (144) set lists' bulk class, the only two "
       "stages the guide gives Wetlands Majini; live maximum 700 / 900 / 600 (the guide's 670-700, 900 at the "
       "Village start, 620 archers)", sources=(ER5 + "wetlands-majini", MERCS5_DATA),
       variants=({"name": "Torch Majini", "hp_max": 1500, "tier": "dangerous"},), kind="majini"),
    _e("uEm13", "Big Man Majini", "dangerous",
       "Huge strength, punches and grabs; gets straight back up and cannot be knocked down while his arms are up.",
       "head and legs (no armour); melee while he kneels",
       ["Keep your distance: shotgun or magnum", "Stagger him with a leg or head shot, then melee while he kneels",
        "Never trade blows while his arms are raised"],
       aliases=("Big Man",), hp=4000, stages=("The Mines", "Prison"), level="matched",
       evidence="Prison's set list has 14 = the guide's 14 Big Men; The Mines 7 (the guide's 2 + 3 by region, one "
       "in the upper tunnel, more waiting); live maximum 4000 = the guide's", sources=(ER5 + "big-man-majini",
       MERCS5_DATA), spawns="by region (The Mines: A 2, B 3, +1 upper tunnel); Prison 14 through the round",
       kind="majini"),
    _e("uEm14", "Base Majini", "normal",
       "Armed soldiers in squads: handguns, grenades, stun rods and rocket launchers; armour and shields soak shots.",
       "the unarmoured head and face",
       ["Aim at exposed parts - armour deflects", "Kill the rocket-launcher soldiers on sight (kills 10-80)",
        "Strafe sideways when one aims a rocket"],
       aliases=("Rocket Launcher Majini", "Armored Majini", "Stun-rod Majini"), hp=800,
       stages=("Experimental Facility",), level="matched",
       evidence="the Experimental Facility's set list 77 = the guide's 60 by region + 9 rocket soldiers + 8 at the "
       "start; live maximum 800 (the guide's Base Majini)", sources=(ER5 + "base-majini", MERCS5_DATA),
       notes="the rocket-launcher variant (1000 health) is the stage's heavy, nine of them by kill count",
       kind="majini"),
    _e("uEm20", "Executioner Majini", "boss",
       "A giant axe whose swing takes most of your health; it shrugs off normal hits.",
       "head (extra damage); stun it, then melee",
       ["Stun it - flash grenade, an explosive barrel, head shots - then finish with a magnum or melee",
        "Never stand in front of the overhead swing: circle and keep range", "Proximity mines on its path",
        "Public Assembly: only one is alive at a time (kills 20, 50, 70); the bus is a safe spot"],
       aliases=("Executioner", "Axe Man"), hp={"Public Assembly": 8000, "Prison": 15000},
       stages=("Public Assembly", "Prison"), level="verified",
       evidence="a live frame identified uEm20 in Public Assembly as the executioner (re5-enemy-cast.md); set "
       "lists 3 (Public Assembly) and 2 (Prison) = the guide's; live maximum 8000 / 15000 = the guide's",
       sources=(ER5 + "executioner", MERCS5_DATA, MERCS5_STEAM),
       variants=({"name": "Executioner Majini", "hp_max": 8000}, {"name": "Executioner Majini (Prison)",
                                                                   "hp_max": 15000}), kind="heavy"),
    _e("uEm21", "Agitator Majini", "normal",
       "The tougher megaphone Majini who rouses the crowd; no extra attack of his own.", "head",
       ["Head shots, then melee", "He has twice a Majini's health: a shotgun or magnum shot first"],
       aliases=("Megaphone Majini",), hp=1400, stages=("Public Assembly",), level="matched",
       evidence="one per Public Assembly round in its set list, live maximum 1400 = the guide's Agitator (1400), and "
       "its model (em2100, rendered) is the Agitator's sunglasses and dark shirt; the bot lists the class among the "
       "dynamite carriers (re5_switch.DYNAMITE_CLASSES)",
       sources=(ER5 + "agitator-majini", MERCS5_DATA), kind="majini"),
    _e("uEm22", "Chainsaw Majini", "boss",
       "One chainsaw hit kills outright, whatever your health.", "head",
       ["Grenade or flash to stun, head shots, then melee - only once the saw has stopped (it fakes stuns)",
        "A rocket launcher or magnum ends it fastest", "It jumps to the upper level: the stairs are no refuge",
        "Keep a long escape line and never let it close"],
       aliases=("Chainsaw Man",), hp={"red": 7000, "blue": 15000}, stages=("Ship Deck",), level="matched",
       evidence="Ship Deck's set list 7 = the guide's 7 chainsaw drops; live maximum 7000 / 15000 (the guide's "
       "red 7000, blue 13500-15000)", sources=(ER5 + "chainsaw-majini", MERCS5_DATA, MERCS5_STEAM),
       variants=({"name": "Chainsaw Majini (red)", "hp_max": 7000}, {"name": "Chainsaw Majini (blue)",
                                                                     "hp_max": 15000},
                 {"name": "Chainsaw Majini (blue)", "hp_max": 13500}), kind="heavy"),
    _e("uEm23", "Gatling Gun Majini", "boss",
       "Constant gatling fire shreds your health at any range once it has a line on you.",
       "head (a stun); the backpack is bulletproof",
       ["Break line of sight, use cover, keep moving", "Magnum head shot, then melee while it is stunned",
        "Proximity mines - it shrugs off incendiary and electric rounds", "Missile Area: kills 20, 60 (yellow) "
        "and 90 (red)"],
       aliases=("Gatling Majini",), hp={"yellow": 4000, "red": 6000}, stages=("Missile Area",), level="matched",
       evidence="Missile Area's set list 3 = the guide's 3 (two yellow, one red); live maximum 4000 / 6000",
       sources=(ER5 + "gatling-gun-majini", MERCS5_DATA, MERCS5_STEAM),
       variants=({"name": "Gatling Gun Majini (yellow)", "hp_max": 4000},
                 {"name": "Gatling Gun Majini (red)", "hp_max": 6000}), kind="heavy"),
    _e("uEm24", "Giant Majini", "boss",
       "Nearly 3 m tall with a spiked mace; its shout calls the others.", "torso and legs (the mask is invulnerable)",
       ["Shoot the legs or torso until it kneels, then melee", "Shotgun or magnum from range", "Fire hurts it"],
       aliases=("Giant",), hp=4000, stages=("Village", "Ancient Ruins"), level="matched",
       evidence="set lists Village 4 and Ancient Ruins 5 = the guide's Giants; live maximum 4000",
       sources=(ER5 + "giant-majini", MERCS5_DATA), kind="heavy"),
    _e("uEm26", "Executioner Majini (red)", "boss",
       "The Prison's red Executioner: the same axe, far more health.", "head; the pink zone on its back",
       ["Stun it, then a magnum or melee", "Shoot the pink zone on its back", "Mines on its path; never in front "
        "of the swing", "Prison: one at the start, then at kills 50 and 120"],
       aliases=("Red Executioner",), hp=20000, stages=("Prison",), level="matched",
       evidence="Prison's set list 3 = the guide's 3 red Executioners; live maximum 20000; the live crop shows "
       "the red figure", sources=(ER5 + "executioner", MERCS5_DATA, MERCS5_STEAM), kind="heavy"),
    _e("uEm32", "Licker β", "dangerous",
       "Climbs walls and ceilings, pounces in packs and lashes with a long tongue.",
       "its heart, once it is flipped over",
       ["Head shot to flip it, then stomp or stab the exposed heart", "Group them and grenade from range",
        "Never stand inside tongue reach - they hunt by sound"],
       aliases=("Licker Beta", "Licker"), hp=900, stages=("Experimental Facility",), level="verified",
       evidence="named live (enemy_kinds); set list 72 = the guide's 30 + 42 by region; live maximum 900",
       sources=(ER5 + "licker-beta", MERCS5_DATA), kind="bow"),
    _e("uEm34", "Reaper", "boss",
       "Its scythe grab can kill outright; it spits acid and its shell deflects bullets.",
       "the pale sacs on its belly (and back)",
       ["Wait until it rears up, then shoot the belly sac", "A flash grenade stuns it", "Stay at range: it can "
        "strike while dying", "The Mines: kills 30, 70 and 90"],
       hp=1500, stages=("The Mines",), level="matched",
       evidence="The Mines' set list 3 = the guide's 3 Reapers; live maximum 1500", sources=(ER5 + "reaper",
       MERCS5_DATA, MERCS5_STEAM), kind="heavy"),
    _e("uEm0b", "Bui Kichwa", "normal",
       "Small spider-like Plagas in packs that leap and cling.", "any hit",
       ["One bullet or a stomp", "A flash grenade clears a group", "Keep moving so they cannot cling"],
       hp=200, stages=("Village",), level="matched",
       evidence="the Village set list 26 = the guide's 10 + 16 Bui Kichwa; live maximum 200 = the guide's; the "
       "live crop shows a many-legged crawler (the bot's LOW_BODIES note calls it a dog)",
       sources=(ER5 + "bui-kichwa", MERCS5_DATA), kind="plaga"),
    _e("uEm0c", "Kipepeo", "dangerous",
       "A flying Plaga whose tail whip hits very hard.", "light (a flash grenade)",
       ["Flash grenade", "Shotgun or machine gun while it hovers slowly"],
       hp=1000, stages=("Village",), level="matched",
       evidence="seen live only in the Village (the guide's only Kipepeo stage, 0-6 a round), maximum 1000 = the "
       "guide's, and its model (em0c00, rendered) is a winged flyer; not in the set lists (they hatch)",
       sources=(ER5 + "kipepeo", MERCS5_DATA),
       kind="plaga"),
    _e("uEm0d", "Cephalo", "dangerous",
       "A Majini's head bursts into a whipping Plaga with long reach and more power than its host.",
       "light (a flash grenade kills it)",
       ["Flash grenade", "Shotgun at close range", "Avoid head criticals where they hatch (Missile Area, Ship "
        "Deck late in the round)"],
       aliases=("Cephalo Plaga",), hp=600, stages=("Prison", "Public Assembly"), level="inferred",
       evidence="seen live only on town-Majini stages (Prison, Public Assembly), maximum 600; its model (em0d00, "
       "rendered) is a whip-tentacle Plaga; not in the set lists (it hatches from a host)",
       sources=(ER5 + "cephalo", MERCS5_DATA), kind="plaga"),
    _e("uEm0e", "Duvalia", "dangerous",
       "A Plaga with an armoured shell that opens at close range and swallows you.",
       "the parasite while the shell is open; light",
       ["Flash grenade", "Shoot it while the shell is open", "Keep your distance"],
       hp=600, stages=("Ancient Ruins", "Experimental Facility"), level="inferred",
       evidence="its model (em0e00, rendered) is a great fleshy petal mass - the Duvalia's open shell; seen live in "
       "the Experimental Facility at 600 (the guide gives Ancient Ruins hosts, ~7000 with the host)",
       sources=(ER5 + "duvalia", MERCS5_DATA), kind="plaga"),
    _e("uEm62", "Chicken", "harmless",
       "Harmless.", "any hit", ["Never a target while anything else lives"],
       aliases=("Critter", "Crow"), hp=1, stages=("every stage",), level="matched",
       evidence="its model (em6200, rendered) is a chicken; health 1; one in every stage's set list and two in The "
       "Mines = the guide's chickens", sources=(MERCS5_DATA, MERCS5_STEAM), kind="animal"),
    _e("uEm30", "Adjule", "dangerous",
       "A Plaga dog: fast lunges, worst in tight spaces.", "its split head",
       ["Shotgun as it leaps", "Fight it in open ground"], stages=("The Mines (Reunion)",), level="inferred",
       evidence="its model (em3000, rendered) is a black dog with bone spikes; placed only by The Mines' Reunion set "
       "(13)", sources=(ER5 + "adjule",), kind="animal"),
    _e("uEm92", "Jill Valentine (enemy)", "boss",
       "Mind-controlled Jill: fast acrobatic melee and gunfire.", "the device on her chest",
       ["Restrain her, then hit the device on her chest", "Do not trade fire with her body"],
       stages=("Public Assembly (another mode)",), level="unconfirmed",
       evidence="its model (em9200, rendered) is a blonde woman in a black suit; one placement in a Public Assembly "
       "set", sources=(ER5 + "jill-valentine-enemy",), kind="boss"),
]

# --- Resident Evil 6 (Switch 01002A000CD48000) -------------------------------------------------------------------------
_RE6_ZOMBIE = ("Urban Chaos", "Mining the Depths", "The Catacombs", "Rooftop Mission")
_RE6_JAVO = ("Rail Yard", "Requiem for War", "High Seas Fortress", "Steel Beast", "Creature Workshop", "Liquid Fire")
_JAVO_KILL = ["Head shot to stagger, then melee or a finisher before the damage mutates it",
              "Kill the rocket and sniper J'avo first", "Fire or explosives kill without a mutation"]
_ZOMBIE_KILL = ["Head shot, or a leg shot to drop it, then a finisher", "Counter the lunge",
                "Quick-shot crowds and never get surrounded"]


def _javo(cls, name, stages, evidence, level="unconfirmed"):
    return _e(cls, name, "normal",
              "Armed (rifles, rockets, blades) and in groups; it survives head shots, heals, and mutates where hurt.",
              "head (a stagger), then melee", _JAVO_KILL, aliases=("J'avo",), stages=stages, level=level,
              evidence=evidence, sources=(ER6 + "javo",), kind="javo")


def _zombie(cls, name, stages, evidence, level="unconfirmed", tier="normal", danger=None, aliases=("Zombie",)):
    return _e(cls, name, tier, danger or "Lunges and grabs; dangerous in numbers.", "head", _ZOMBIE_KILL,
              aliases=aliases, stages=stages, level=level, evidence=evidence, sources=(ER6 + "zombie",),
              kind="zombie")


_MUTATION = ("A J'avo mutated where it was hurt: the new limb is its weapon and its weak point.",
             "the mutated part")
# RE6 settled from the game files by #9343 (docs/research/re6-switch-enemy-identities.md, checked 2026-11-10 against
# the RomFS on lilspark: every archive entry it cites is in that class's archive, uEm3300.arc and uEm3301.arc are
# byte-identical, and Msg_eng.arc's mes_file_eng holds each cited string at the cited index): "verified" where the
# class archive spells the name (juavo, zonbie, parachute); "matched" where the game's own creature name (that file's
# creature list, strings #6297-#6362) is tied to the class by class-specific entries (motions, sounds, textures). The
# four it leaves not determined (uEm2010, uEm2230, uEm3320, uEm4100) keep their old rows. Tiers are not in the files:
# they stay the table's own judgement.
_M9343 = "#9343: "
_MSG = "Msg_eng.arc mes_file_eng string "
_RE6 = [
    _javo("uEm1000", "J'avo", ("Rail Yard", "Requiem for War", "High Seas Fortress", "Steel Beast",
                               "Creature Workshop", "Liquid Fire"),
          "named live (enemy_kinds); the J'avo sets' bulk (Rail Yard 506 No Mercy placements)", level="verified"),
    _javo("uEm1200", "J'avo", ("Requiem for War", "Steel Beast"),
          _M9343 + "uEm1200.arc carries em1200_juavo_mask_break (the romanised name) and the jvupper / jveye / "
          "jvpants textures; the bulk of Requiem for War (298) and Steel Beast (286); the old '(Lanshiang)' "
          "qualifier is not determined (stage placement only)", level="verified"),
    _e("uEm1370", "Chrysalid", "dangerous",
       "A J'avo's cocoon (the pupa stage); left alone it hatches into a heavy B.O.W. (Strelats, Napad, Gnezdo).",
       "the shell (lots of ammo)", ["Destroy it before it hatches", "Explosives on the shell"],
       aliases=("Kokon",), stages=("Liquid Fire",), level="matched",
       evidence=_M9343 + "uEm1370.arc's em1370_mayu ('cocoon') textures and its kneedown_after_pupa / hukurami "
       "('swelling') cues; " + _MSG + "#6297 'Chrysalid', #6911 'Hatching Chrysalids'; uEm3000 / 3100 / 3200 / 3300 "
       "each embed its em1370 pupa body. Liquid Fire's set: 3", sources=(ER6 + "chrysalid",), kind="mutation"),
    _javo("uEm1400", "J'avo", ("Creature Workshop", "Liquid Fire"),
          _M9343 + "uEm1400.arc carries em1400_juavo_mask_break (the romanised name); the bulk of Creature Workshop "
          "(284) and Liquid Fire (321); the old '(Neo-Umbrella)' qualifier is not determined", level="verified"),
    _e("uEm2010", "J'avo mutation (head)", "dangerous", *_MUTATION, ["Shoot the mutated head", "Back off its reach"],
       aliases=("Glava",), level="unconfirmed", evidence="spawns only after a J'avo is hurt (no set list places it); "
       "the 20xx family read as the head mutations by its numbering", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2030", "Glava-Dim", "dangerous", *_MUTATION, ["Shoot the mutated head", "Back off its reach"],
       aliases=("Glava", "J'avo mutation (head)"), level="matched",
       evidence=_M9343 + "uEm2030.arc's em2030_smoke_attack and mutation_a / b cues ('Dim' = smoke); " + _MSG +
       "#6301 'Glava-Dim', the kill medal #4895 'Kill 30 Glava-Dims.'", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2100", "Ruka-Srp", "dangerous", *_MUTATION, ["Stay out of the sickle arm's reach"],
       aliases=("Ruka", "J'avo mutation (arm)"), hp=1000, level="matched",
       evidence=_M9343 + "uEm2100.arc's em1000_gkama motion ('kama' = sickle, as Serbian 'srp') and its arm attack "
       "cues; " + _MSG + "#6302 'Ruka-Srp'; maximum 1000 in MercMode's census (re6_switch BIG_HP note)",
       kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2120", "Ruka-Khvatanje", "dangerous", *_MUTATION, ["Stay out of the arm's reach: it grabs"],
       aliases=("Ruka", "J'avo mutation (arm)"), level="matched",
       evidence=_M9343 + "uEm2120.arc's punch / grab and ground-impact motions; " + _MSG + "#6303 'Ruka-Khvatanje' "
       "('grabbing'), by elimination among the three arm names (Srp uEm2100, Bedem uEm2140)",
       kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2140", "Ruka-Bedem", "dangerous", *_MUTATION,
       ["Shoot past the shield arm to the head or legs", "Stay out of the arm's reach"],
       aliases=("Ruka", "J'avo mutation (arm)"), level="matched",
       evidence=_M9343 + "uEm2140.arc's em2140_21_shield textures and its guard_on cue; " + _MSG + "#6304 "
       "'Ruka-Bedem' ('rampart')", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2200", "Noga-Trchanje", "dangerous", *_MUTATION, ["Counter or shotgun it as it runs in"],
       aliases=("Noga", "J'avo mutation (legs)"), level="matched",
       evidence=_M9343 + "uEm2200.arc's run motion (the only leg class with one) beside a prejump cue; " + _MSG +
       "#6305 'Noga-Trchanje' ('running') - the weakest of #9343's matches", kind="mutation",
       sources=(ER6 + "javo",)),
    _e("uEm2210", "Noga-Let", "dangerous", *_MUTATION, ["Shoot it down before it dives", "Counter it as it lands"],
       aliases=("Noga", "J'avo mutation (legs)"), hp=1000, level="matched",
       evidence=_M9343 + "uEm2210.arc's wingborn / wingmove motions and a bodycatch grab; " + _MSG + "#6306 "
       "'Noga-Let' ('flight'); maximum 1000 in MercMode's census", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2230", "J'avo mutation (legs)", "dangerous", *_MUTATION, ["Counter or shotgun it as it lands"],
       aliases=("Noga",), level="unconfirmed", evidence="as uEm2200 (#9343: a leg mutation; Skakanje or Oklop not "
       "determined)", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm2300", "Telo-Eksplozija", "dangerous",
       "A J'avo whose body mutated into a bomb: it bursts.", "the swollen body, from range",
       ["Kill it at range", "Never let it reach you"], aliases=("Telo",), hp=1000, level="matched",
       evidence=_M9343 + "uEm2300.arc's em2300_00_bomb01 / maku ('membrane') textures and its em2300_exp explosion "
       "entries; " + _MSG + "#6309 'Telo-Eksplozija' ('explosion'). It was 'Chrysalid' here: the cocoon evidence is "
       "uEm1370's. Maximum 1000 in MercMode's census", kind="mutation", sources=(ER6 + "javo",)),
    _e("uEm3000", "Strelats", "dangerous",
       "Fires a spray of needles from its neck fins at long range; the fins steam just before it shoots.",
       "head; close the distance", ["Dodge when the fins steam", "Chase it down so it cannot shoot",
                                    "Close in with a shotgun or melee"],
       aliases=("Strelat",), stages=("Mining the Depths", "The Catacombs"), level="matched",
       evidence=_M9343 + "uEm3000.arc's needle-shot cues (NIIDLE1, large_needle_shot) and the embedded em1370 pupa "
       "body; " + _MSG + "#6312 'Strelats', #5799 'Mutated into a Strelats.', the tip #7073. Placed on Mining the "
       "Depths (3) and The Catacombs (2)", sources=(ER6 + "strelat",), kind="bow"),
    _e("uEm3100", "Mesets", "dangerous",
       "A winged B.O.W. that circles, then dives; the dive cannot be countered.", "any hit while it flies",
       ["Shoot it down before it dives", "Dodge the dive"], aliases=("Meset",), stages=("Liquid Fire",),
       level="matched", evidence=_M9343 + "uEm3100.arc's glide, hovering, hit-ceiling and pupaborn cues; " + _MSG +
       "#6313 'Mesets', #5800 'Played as Mesets.'; Liquid Fire's set: 6", sources=(ER6 + "meset",), kind="bow"),
    _e("uEm3200", "Napad", "boss",
       "An armoured charger whose punch grabs and slams you; normal fire barely marks it.",
       "inside the shell on its back, once the armour plates break",
       ["Sidestep or counter the charge", "Break the plates off its back, then shoot the flesh", "Explosives"],
       stages=("Rail Yard", "Urban Chaos", "High Seas Fortress", "Steel Beast", "Rooftop Mission",
               "Creature Workshop", "Liquid Fire"), level="matched",
       evidence=_M9343 + "uEm3200.arc's shell impact, charge, palm strike and neck-hang grab cues; " + _MSG +
       "#6314 'Napad', the tips #7072 'A Napad's weak point is inside the shell on its back.' and #7101, #5801 "
       "'Mutated into a Napad.'. Placed in seven sets, 3-6 each (Steel Beast 20)", sources=(ER6 + "napad",),
       kind="bow"),
    _e("uEm3300", "Gnezdo", "boss",
       "A core hidden inside a wasp swarm; it shows only after the swarm takes enough damage.",
       "the core, once the swarm disperses",
       ["Break the swarm with fire, explosives or a shotgun", "Then shoot the core before it re-forms"],
       stages=("Requiem for War", "High Seas Fortress", "Steel Beast"), level="matched",
       evidence=_M9343 + "uEm3300.arc's swarm / bee loop / player-bitten cues; " + _MSG + "#6315 'Gnezdo' ('nest'), "
       "#5802 'Mutated into a Gnezdo.'; exactly one in three sets; its model is a placeholder point (a swarm "
       "drawn by effects); uEm3320 seen live beside it", sources=(ER6 + "gnezdo",), kind="bow"),
    _e("uEm3301", "Gnezdo", "boss",
       "A core hidden inside a wasp swarm; it shows only after the swarm takes enough damage.",
       "the core, once the swarm disperses",
       ["Break the swarm with fire, explosives or a shotgun", "Then shoot the core before it re-forms"],
       level="matched", evidence=_M9343 + "uEm3301.arc is byte-identical to uEm3300.arc (the same SHA-1, "
       "b323d181...): the same enemy. It was 'J'avo mutant (em1370 body)' here, from the embedded pupa model only",
       sources=(ER6 + "gnezdo",), kind="bow"),
    _e("uEm3320", "Gnezdo (core)", "boss", "The Gnezdo's core, out of its swarm.", "the core itself",
       ["Shoot it before the swarm re-forms"], level="unconfirmed",
       evidence="seen live only; numbered beside uEm3300; its model (em3320, rendered) is a ragged winged body",
       sources=(ER6 + "gnezdo",), kind="bow"),
    _e("uEm4100", "Lepotitsa", "dangerous",
       "Sprays a gas that turns people into zombies; a shot body bursts into a cloud that hurts up close.",
       "fight it from range", ["Only from range", "Stay out of its gas and back off after each hit",
                               "Explosives or a sniper shot"],
       stages=("The Catacombs",), level="unconfirmed",
       evidence="its model (em4100, rendered) is a long-haired female figure with a swollen body; three in The "
       "Catacombs' set (a zombie stage from Leon's campaign)", sources=(ER6 + "lepotitsa",), kind="bow"),
    _e("uEm4300", "Ubistvo", "boss",
       "Its chainsaw arm kills outright however it connects.", "head; keep it at range",
       ["Never let it close in - it is easy to sidestep", "Explosives and heavy weapons from range",
        "Kite it in a loop"],
       stages=("Rail Yard", "Rooftop Mission", "Creature Workshop"), level="matched",
       evidence=_M9343 + "uEm4300.arc's chainsaw loop and stab cues; " + _MSG + "#6318 'Ubistvo' ('murder'), the "
       "event title #6773 'Ubistvo on the Attack'. Placed in three sets (Rooftop Mission 5 - the guides' three "
       "Ubistvo there)", sources=(ER6 + "ubistvo",), kind="bow"),
    _e("uEm4700", "Rasklapanje", "dangerous",
       "Its only attack is a grab; shot apart, its pieces keep crawling at you.",
       "practically unkillable by gunfire; a stage hazard (lava) ends it",
       ["Do not spend ammo on it - keep moving", "Mash free of the grab (a partner knocks it off)",
        "Push or shoot it into the lava where the stage allows"],
       stages=("Liquid Fire",), level="matched",
       evidence=_M9343 + "uEm4700.arc's recombine, rip-arm and arm-throw voice cues; " + _MSG + "#6319 "
       "'Rasklapanje' ('disassembly'), #5794 'Played as a Rasklapanje.'. Liquid Fire's set: 3; one archive family "
       "holds a whole body (em4700), an upper body (em4701) and a crawling hand (em4710)",
       sources=(ER6 + "rasklapanje",), kind="bow"),
    _e("uEm4701", "Rasklapanje (torso)", "dangerous", "A Rasklapanje's upper body, still crawling.", "a hazard",
       ["Keep moving"], level="matched", evidence=_M9343 + "uEm4701.arc shares 220 entries with uEm4700.arc (the "
       "same voice cues); its model is the em4700 body's upper half", sources=(ER6 + "rasklapanje",), kind="bow"),
    _e("uEm4710", "Rasklapanje (hand)", "normal", "A crawling Rasklapanje hand.", "any hit", ["Keep moving"],
       level="matched", evidence=_M9343 + "its model (em4710) is a crawling hand of the em4700 family (the same "
       "texture entries)", sources=(ER6 + "rasklapanje",), kind="bow"),
    _e("uEm4800", "Ogroman", "boss",
       "A giant that swipes and stomps; every attack is avoidable from range.", "the exposed weak spot on its back",
       ["Keep far away", "Break its plates, then pour heavy fire or explosives into the weak spot"],
       stages=("Requiem for War",), level="matched",
       evidence=_M9343 + "uEm4800.arc's child models em4801 / em4802 and core textures, the largest enemy model "
       "(11 m); " + _MSG + "#6362 'Ogroman' ('huge'), #5974 'Sent a Ogroman over ...'. Requiem for War's set: 3 - "
       "the guides' stage with two Ogroman", sources=(ER6 + "ogroman",), kind="bow"),
    _zombie("uEm5000", "Zombie", ("Mining the Depths", "Rooftop Mission"),
            _M9343 + "the verified zombies' 25-bone skeleton, civilian clothing textures; " + _MSG + "#6330 "
            "'Zombie'; the bulk of Mining the Depths (159)", level="matched"),
    _zombie("uEm5050", "Zombie", ("Urban Chaos", "Rooftop Mission"),
            _M9343 + "armour and helmet textures; " + _MSG + "#6330 'Zombie' (#6351 'Zombie - Helmet'); its model "
            "(em5050, rendered) wears a headlamp - the old 'miner' label rests on no entry", level="matched"),
    _zombie("uEm5060", "Zombie", ("Mining the Depths",),
            _M9343 + "armour and helmet textures; " + _MSG + "#6330 'Zombie'; its model (em5060, rendered) wears a "
            "headlamp - the old 'miner' label rests on no entry", level="matched"),
    _zombie("uEm5181", "Zombie", ("Urban Chaos",),
            _M9343 + "cap and pouch textures; " + _MSG + "#6330 'Zombie'; its model (em5181, rendered) wears a "
            "police cap - the old 'police' label rests on no entry", level="matched"),
    _zombie("uEm5191", "Zombie", ("Urban Chaos", "Mining the Depths", "Rooftop Mission"),
            _M9343 + "helmet and glove textures; " + _MSG + "#6330 'Zombie'; its model (em5191, rendered) wears a "
            "yellow fire helmet and coat - the old 'firefighter' label rests on no entry", level="matched"),
    _zombie("uEm5200", "Zombie", ("Urban Chaos", "Rooftop Mission"), "named live (enemy_kinds)", level="verified"),
    _zombie("uEm5210", "Zombie", ("Urban Chaos", "Requiem for War", "Creature Workshop"),
            "named live (enemy_kinds)", level="verified"),
    _zombie("uEm5400", "Zombie", ("The Catacombs",),
            _M9343 + "uEm5400.arc carries wp1240_zonbie_eat_dynamite (the romanised name; " + _MSG + "#6350 "
            "'Zombie - Dynamite'); the bulk of The Catacombs (307)", level="verified"),
    _zombie("uEm5500", "Shrieker", ("Mining the Depths",),
            _M9343 + "uEm5500.arc's scream cues and its em5000_shr ('shr') motion; " + _MSG + "#6357 'Shrieker', the "
            "tip #7056 'A Shrieker's weak point is its throat.'; set list only (7)", level="matched",
            tier="dangerous", danger="A zombie whose scream calls the others and staggers you.",
            aliases=("Zombie special (uEm5500)",)),
    _zombie("uEm5600", "Whopper", ("Urban Chaos", "The Catacombs", "Rooftop Mission"),
            _M9343 + "uEm5600.arc's bone-break, eat and large-impact cues; " + _MSG + "#6358 'Whopper', the tip #7057 "
            "'A Whopper can't hurt you if it can't use its legs.'; its model (em5600, rendered) is a huge, fat "
            "zombie; placed on three zombie stages (Rooftop Mission 14)", level="matched", tier="dangerous",
            danger="A super-sized zombie: hits hard, barely flinches at counters, blocks escape routes.",
            aliases=("Super-sized zombie",)),
    _e("uEm5700", "Zombie Dog C", "normal", "Very fast and hard to hit; it pounces.", "any hit - it dies fast",
       ["Shoot or counter it mid-pounce", "A shotgun's spread"], aliases=("Zombie Dog",),
       stages=("Urban Chaos", "Mining the Depths", "Rooftop Mission"), level="matched",
       evidence=_M9343 + "uEm5700.arc's bark, bite and growl cues; " + _MSG + "#6360 'Zombie Dog C'; its model "
       "(em5700, rendered) is a dog; 18-52 in three zombie sets", sources=(ER6 + "zombie-dog",), kind="animal"),
    _e("uEm9906", "Parachute", "harmless", "Not an enemy: a dropped parachute.", "-",
       ["Never a target"], level="verified", evidence=_M9343 + "uEm9906.arc carries sm5051_Parachute (the name); its "
       "model is sm5051, a parachute canopy", kind="object"),
]

# --- Resident Evil 4 (Switch 010099A00BC1E000; the GameCube's G4BE08 reads em/type keys) --------------------------------
_RE4_ESL = "etc/omake01.esl / omake02.esl (gbox/re4_switch_enemies.read_esl): "
_RE4 = [
    _e("ganado", "Ganado (villager)", "normal",
       "Axes, sickles, pitchforks and thrown dynamite; they grab and hold you for the others.",
       "head or a knee (a stagger), then melee",
       ["Head or knee shot, then kick or suplex", "Shoot a lit dynamite stick in a hand: it blows up the group",
        "Fight at chokepoints; shotgun the crowds"],
       aliases=("Ganado", "Villager"), hp="1200-1800", stages=("Village",), level="matched",
       evidence=_RE4_ESL + "the Village's em16 types 3, 4, 11 and 12 at 1200-1800 health: 118 placements (124 "
       "with the six 6500-health chainsaws of types 11 and 12; #9345)",
       sources=(ER4 + "village-ganado",), kind="ganado", ram_class=False),
    _e("salvador", "Dr. Salvador", "boss",
       "A chainsaw that kills outright up close; far tougher than a Ganado.", "head",
       ["Never let him close: back off and keep a long line", "Shotgun or magnum to the head, then knock him "
        "down", "Grenades or mines on his path"],
       aliases=("Chainsaw Ganado", "Chainsaw Man"), hp=6500, stages=("Village",), level="matched",
       evidence=_RE4_ESL + "em16 type 11 at 6500 health, three a round; the GameCube bot read his chainsaw attack "
       "on that exact key (em16.0b.hp6500)", sources=(ER4 + "dr-salvador",), kind="heavy", ram_class=False),
    _e("bella", "Bella Sisters", "boss",
       "Two chainsaw women with the same instant kill; tougher than a Ganado.", "head",
       ["Track both at once and keep your distance", "Head shots with the strongest gun; grenades"],
       aliases=("Chainsaw Sisters",), hp=6500, stages=("Village",), level="inferred",
       evidence=_RE4_ESL + "em16 type 12 at 6500 health, three a round (type 12's others are women at 1400-1800)",
       sources=(ER4 + "bella-sisters",), kind="heavy", ram_class=False),
    _e("colmillos", "Colmillos", "dangerous",
       "Plaga wolves that pounce; tentacles burst from the back for a second attack.", "the body",
       ["Shotgun as it pounces"], aliases=("Plaga dog",), hp=1000, stages=("Village",), level="inferred",
       evidence=_RE4_ESL + "em28 types 0 and 1 at 1000 health, six a round; em28's model is a quadruped (the Switch "
       "census reads only class 0xAE7050 units: a dog may not show)", sources=(ER4 + "colmillos",), kind="animal",
       ram_class=False),
    _e("zealot", "Zealot", "normal",
       "Castle cultists with maces, crossbows, scythes and full-height shields.", "head; the legs past a shield",
       ["Kill the crossbow zealots first", "Shotgun or grenade a shield, or shoot around it",
        "Stay out of scythe reach"],
       aliases=("Castle Ganado", "Cultist"), hp="400-1000", stages=("Castle",), level="matched",
       evidence=_RE4_ESL + "the Castle's em1c types 7 and 9 at 400-1000 health: 112 placements (87 of type 7, 25 "
       "of type 9; 114 with the two leaders; #9345)",
       sources=(ER4 + "castle-ganado",), kind="ganado", ram_class=False),
    _e("zealot_leader", "Zealot leader", "dangerous",
       "A robed leader, much tougher than the others.", "head", ["Focus heavy fire on him; a Plaga may follow"],
       aliases=("Leader Zealot",), hp="2200-2500", stages=("Castle",), level="unconfirmed",
       evidence=_RE4_ESL + "em1c type 9 at 2200 and 2500 health, one each", sources=(ER4 + "castle-ganado-leader-zealot",),
       kind="ganado", ram_class=False),
    _e("garrador", "Garrador", "boss",
       "Blind, with huge claws; it hunts by sound and feels pain only in the back.", "the Plaga on its back",
       ["Get behind it and shoot the back Plaga", "Move quietly - it homes in on noise", "Shotgun or magnum to "
        "the back"],
       hp="2500-2600", stages=("Castle",), level="unconfirmed",
       evidence=_RE4_ESL + "em1c type 10 at 2500 and 2600 health, two a round; the pack's one odd 31-bone figure "
       "(slot 640) is read as the Garrador (re4-parity.md)", sources=(ER4 + "garrador",), kind="heavy",
       ram_class=False),
    _e("garrador_armored", "Garrador (armoured)", "boss",
       "A Garrador in armour: the same claws, harder to hurt.", "the Plaga on its back",
       ["Get behind it", "Explosives or a magnum to the back"], hp=3000, stages=("Castle",), level="unconfirmed",
       evidence=_RE4_ESL + "em1c type 13 at 3000 health, one a round", sources=(ER4 + "garrador",), kind="heavy",
       ram_class=False),
    _e("militia", "Ganado soldier", "normal",
       "Island militia with stun rods, crossbows, maces, shields and rocket launchers.", "head",
       ["Kill the rocket soldiers before they fire", "Break shields with a shotgun or grenade",
        "Stagger, then melee"],
       aliases=("Militia", "Soldier Ganado"), hp="400-1000", stages=("Base", "Waterworld"), level="matched",
       evidence=_RE4_ESL + "em1d (Base) and em20 (Waterworld) types 14-21 at 400-1000 health, 133 and 79 "
       "placements (#9345); the live census read ordinary Ganados at 400 (Base 2026-11-10: 400, 600, 800, 1000)",
       sources=(ER4 + "soldier-ganado",), kind="ganado", ram_class=False),
    _e("jj", "J.J.", "boss",
       "A gatling gun that fires only with a line of sight, after a short spin-up.", "head",
       ["Break line of sight", "Hit him with the strongest weapon during the spin-up", "Grenades"],
       aliases=("Gatling Ganado",), hp="2000-3000", stages=("Base",), level="inferred",
       evidence=_RE4_ESL + "em1d type 2 at 2000 (three) and 3000 (two) health; the base pack's one 6,614-vertex "
       "body carries a weapon in its mesh (re4-parity.md: J.J., inferred)", sources=(ER4 + "jj",), kind="heavy",
       ram_class=False),
    _e("super_salvador", "Super Salvador", "boss",
       "A giant chainsaw man with a twin blade; the same instant kill.", "head",
       ["Magnum, rifle or explosives from range", "Keep a long escape route"],
       hp="3500-5000", stages=("Waterworld",), level="matched",
       evidence=_RE4_ESL + "em20 type 22 at 3500 (three) and 5000 (two) health; the GameCube bot read chainsaw "
       "attacks on those keys (em20.16.hp3500, em20.16.hp5000)", sources=(ER4 + "dr-salvador",), kind="heavy",
       ram_class=False),
    _e("plaga", "Las Plagas", "dangerous",
       "A Plaga bursts from a badly hurt host's neck: a whip or a biting head that can decapitate.",
       "light (a flash grenade kills it at once)", ["Flash grenade", "Shotgun or magnum to the Plaga"],
       stages=("Village", "Castle", "Base", "Waterworld"), level="unconfirmed",
       evidence="no RAM class seen; it grows from a host (the packs' parasite model, slot 629)",
       sources=(ER4 + "las-plagas",), kind="plaga", ram_class=False),
]

TABLE = {RE5: {e["cls"]: e for e in _RE5}, RE6: {e["cls"]: e for e in _RE6}, RE4: {e["cls"]: e for e in _RE4}}
TITLE_NAMES = {RE5: "Resident Evil 5", RE6: "Resident Evil 6", RE4: "Resident Evil 4"}

# --- RE5 Mercenaries stages (the data post citing the official guide; start times there, unverified) -------------------
STAGES = {RE5: {
    "Public Assembly": {"code": "s400", "start_s": 510, "kills": 150,
                        "heavies": [(20, "uEm20", "SW fence"), (50, "uEm20", "east fence behind the platform"),
                                    (70, "uEm20", "NW fence")],
                        "time_bonuses": [(60, "the middle building")], "items": ["two flash grenades in the east "
                                                                                 "building"],
                        "notes": "one Executioner alive at a time; the red- and green-dress women at the start "
                                 "hatch a Cephalo half the time"},
    "The Mines": {"code": "s401", "start_s": 480, "kills": 150,
                  "heavies": [(30, "uEm34", "SW high platform at the back of the bottom tunnel"),
                              (70, "uEm34", "east platform, middle of the bottom tunnel"), (90, "uEm34", "high NE "
                                                                                                        "platform")],
                  "time_bonuses": [(30, "by the bottom tunnel's combo chest (south)"), (60, "the middle"),
                                   (30, "a dead-end tunnel")],
                  "notes": "Big Men by region (A 2, B 3, +1 in the upper tunnel); two chickens"},
    "Village": {"code": "s402", "start_s": 540, "kills": 150,
                "heavies": [(20, "uEm24", "east high wall by the 30 s statues"), (40, "uEm24", "SE front gate"),
                            (60, "uEm24", "east hill wall, opposite the combo chest"), (70, "uEm24", None)],
                "time_bonuses": [(30, "east high wall"), (30, "east high wall"), (60, "the south building")],
                "notes": "Bui Kichwa A 10 / B 16; 0-6 Kipepeo at random; the bridge splits the regions"},
    "Ancient Ruins": {"code": "s403", "start_s": 630, "kills": 150,
                      "heavies": [(0, "uEm24", "SW near the 90 s statue"), (10, "uEm24", None), (40, "uEm24", None),
                                  (60, "uEm24", None), (70, "uEm24", None), (0, "uEm12", "Torch Majini, east tunnel"),
                                  (10, "uEm12", "Torch Majini"), (40, "uEm12", "Torch Majini"),
                                  (60, "uEm12", "Torch Majini"), (70, "uEm12", "Torch Majini"),
                                  (80, "uEm12", "Torch Majini"), (90, "uEm12", "Torch Majini")],
                      "time_bonuses": [(90, "SW, with a combo bonus"), (30, "east tunnel"), (30, "behind the SE wall"),
                                       (90, "the staircase")],
                      "notes": "Duvalia hosts: the explosive archer below the 90 s stairs and the west / east Wetlands "
                               "Majini at kills 1-20"},
    "Experimental Facility": {"code": "s404", "start_s": 540, "kills": 150,
                              "heavies": [(k, "uEm14", "Rocket Launcher Majini") for k in
                                          (10, 30, 40, 60, 60, 70, 70, 80, 80)],
                              "time_bonuses": [(90, "the bottom floor"), (60, "the floor-1 platform")],
                              "notes": "Licker β A 30 / B 42; the high area is good for combos"},
    "Missile Area": {"code": "s405", "start_s": 660, "kills": 150,
                     "heavies": [(20, "uEm23", "yellow, the ledge above the north tall ladder"),
                                 (60, "uEm23", "yellow, the central shaft doorway"),
                                 (90, "uEm23", "red, the top-floor office ceiling")],
                     "time_bonuses": [(30, "the middle platform"), (30, "the south walkway"), (90, "the 3rd floor")],
                     "notes": "head criticals hatch Cephalos here: avoid head hits"},
    "Ship Deck": {"code": "s406", "start_s": 690, "kills": 150,
                  "heavies": [(0, "uEm22", "blue, from the crane"), (20, "uEm22", "red, from the crane"),
                              (20, "uEm22", "blue, from the crane"), (30, "uEm22", "red"), (40, "uEm22", "red"),
                              (50, "uEm22", "red"), (50, "uEm22", "blue")],
                  "time_bonuses": [(60, "the far north"), (90, "the alcove")],
                  "notes": "west-side Majini late in the round hatch Cephalos unless killed outright or blown up"},
    "Prison": {"code": "s407", "start_s": 600, "kills": 150,
               "heavies": [(0, "uEm26", "red, B1"), (None, "uEm20", "after the first red dies, above the top combo "
                                                                     "chest"),
                           (50, "uEm26", "red, above the bottom stair corridor"), (90, "uEm20", None),
                           (120, "uEm26", "red")],
               "time_bonuses": [(60, "the top"), (30, "the cell corridor")],
               "notes": "14 Big Men through the round; grenades open shortcuts through some walls"},
}}
RULES = {RE5: {
    "combo_window_s": 10.0, "melee_kill_bonus_s": 5, "time_statues_s": [30, 60, 90], "combo_bonus_s": 30,
    "combo_bonus_points": 1000, "all_kills_points_per_second": 1000, "solo_level": 6, "duo_level": 8,
    # (from the combo's kill number, points added, extra for a boss kill)
    "combo_points": [(2, 20, 500), (3, 50, 1000), (4, 100, 1500), (5, 200, 2000), (6, 250, 2500), (7, 300, 3000),
                     (8, 350, 3500), (9, 400, 4000), (10, 500, 4500), (20, 600, 5000), (30, 700, 5500),
                     (40, 850, 6000), (50, 1000, 7000)],
    "sources": [MERCS5_DATA, MERCS5_STEAM],
}}


# --- lookups -----------------------------------------------------------------------------------------------------------
def canonical(title) -> str:
    t = str(title or "")
    return ALIASES.get(t, t)


def identity(title, cls) -> dict | None:
    """The entry of this class (RE5 / RE6 RAM class, RE4 identity key), or None."""
    if cls is None:
        return None
    return TABLE.get(canonical(title), {}).get(str(cls))


def listing(title) -> list[dict]:
    """Every entry of the title, bosses first."""
    rows = list(TABLE.get(canonical(title), {}).values())
    return sorted(rows, key=lambda e: (TIERS.index(e["tier"]), not e["ram_class"], e["name"]))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _variant(entry: dict, hp_max) -> dict | None:
    hp = _num(hp_max)
    if hp is None:
        return None
    for v in entry.get("variants") or ():
        if abs(hp - v["hp_max"]) <= max(1.0, 0.02 * v["hp_max"]):
            return v
    return None


def _hp_tier(title, hp_max) -> str | None:
    hp = _num(hp_max)
    lim = HP_TIERS.get(canonical(title))
    if hp is None or lim is None:
        return None
    if hp <= 1:
        return "harmless"
    return "boss" if hp >= lim[0] else "dangerous" if hp >= lim[1] else "normal"


def tier(title_id, cls, hp_max=None) -> str | None:
    """The tier of this class (its variant's, when the maximum health names one), else by the health (HP_TIERS) when
    given, else None."""
    entry = identity(title_id, cls)
    if entry is not None:
        v = _variant(entry, hp_max)
        return (v or {}).get("tier") or entry["tier"]
    return _hp_tier(title_id, hp_max)


def weight(title_id, cls, hp_max=None) -> float:
    """TIER_WEIGHT of the tier (boss 3 > dangerous 2 > normal 1 > harmless 0); UNKNOWN_WEIGHT without one."""
    t = tier(title_id, cls, hp_max)
    return TIER_WEIGHT.get(t, UNKNOWN_WEIGHT) if t else UNKNOWN_WEIGHT


# --- RE4: the identity of a unit from its type byte and health ----------------------------------------------------------
_RE4_KEY = re.compile(r"^em(?P<em>[0-9a-f]{2})\.(?P<type>[0-9a-f]{2})(?:\.hp(?P<hp>\d+))?$")
RE4_STAGE_TYPES = {"Village": {3, 4, 11, 12, 0, 1}, "Castle": {7, 9, 10, 13}, "Base": {2, *range(14, 22)},
                   "Waterworld": set(range(14, 23))}
# Each stage's set list as (type, maximum health) -> identity: #9345 (docs/research/re4-switch-mercs-spawns.md / .json,
# checked 2026-11-10 against the RomFS's etc/omake01.esl and omake02.esl - the same sha256, every (stage, pack, type,
# health, count) row equal). The list has no wave or kill-count field (placements are positional).
_RE4_ROWS = {
    "Village": {"ganado": {3: (1300, 1400, 1500, 1600, 1700, 1800), 4: (1400, 1600, 1700, 1800),
                           11: (1200, 1400, 1600, 1700, 1800), 12: (1400, 1500, 1600, 1700, 1800)},
                "salvador": {11: (6500,)}, "bella": {12: (6500,)}, "colmillos": {0: (1000,), 1: (1000,)}},
    "Castle": {"zealot": {7: (400, 500, 600, 700, 800, 900, 1000), 9: (600, 700, 800, 900, 1000)},
               "zealot_leader": {9: (2200, 2500)}, "garrador": {10: (2500, 2600)}, "garrador_armored": {13: (3000,)}},
    "Base": {"jj": {2: (2000, 3000)}, "militia": {t: (400, 600, 800, 1000) for t in range(14, 22)}},
    "Waterworld": {"militia": {14: (400, 600, 800, 1000), 15: (400, 600, 1000), 16: (400, 600, 800),
                               17: (400, 600, 800), 18: (400, 800, 1000), 19: (400, 600, 800, 1000),
                               20: (400, 600, 800), 21: (400, 600)},
                   "super_salvador": {22: (3500, 5000)}},
}
RE4_SET_LISTS = {stage: {(t, hp): key for key, types in rows.items() for t, hps in types.items() for hp in hps}
                 for stage, rows in _RE4_ROWS.items()}
# The Switch census's "type" (unit + 0x3CE) is NOT the set list's type: #9345's static scan of main finds only two
# direct writers of that byte (an AI state switch storing 0x16, a reset storing 0) and a 45-entry jump table indexed by
# it - a state code, not the list's type - and live it reads 0 on every Ganado (tests/fixtures/re4sw_units_live.json:
# a 3500-health one too; the live map of 2026-11-10 named Base's 1000-health soldiers Colmillos through it). A census
# unit is named by its maximum health within its stage's list instead (re4_unit_key); its type byte only settles a
# tie, and only when it is a row of that list with that health (0 never: it is the reset value).


def _re4_stage(stage) -> str | None:
    if not stage:
        return None
    s = str(stage).strip().lower()
    rooms = {"r400": "Village", "r402": "Castle", "r403": "Base", "r404": "Waterworld"}
    return next((k for k in RE4_SET_LISTS if k.lower() == s), None) or rooms.get(s)


def re4_unit_key(hp_max, stage=None, etype=None) -> str | None:
    """A Switch census unit's identity: the set-list identities with that maximum health in its stage (every stage
    when unknown) - the one there is, else the one its type byte names among them (a list row with that health; 0 is
    never one), else None (its health tiers it: HP_TIERS)."""
    hp = _num(hp_max)
    if hp is None:
        return None
    st = _re4_stage(stage)
    lists = [RE4_SET_LISTS[st]] if st else list(RE4_SET_LISTS.values())
    rows = [(t, key) for rows_ in lists for (t, h), key in rows_.items() if h == hp]
    keys = {key for _t, key in rows}
    if len(keys) == 1:
        return keys.pop()
    if isinstance(etype, int) and not isinstance(etype, bool) and etype:
        named = {key for t, key in rows if t == etype}
        if len(named) == 1:
            return named.pop()
    return None


def re4_key(etype, hp_max, em=None) -> str | None:
    """RE4's identity key from the set list's type byte and the unit's maximum health (em: the GameCube's pack id)."""
    if not isinstance(etype, int) or isinstance(etype, bool):
        return None
    hp = _num(hp_max) or 0
    if em == "em28" or (em is None and etype in (0, 1) and hp == 1000):
        return "colmillos"
    if etype == 11 and hp >= 5000:
        return "salvador"
    if etype == 12 and hp >= 5000:
        return "bella"
    if etype in (3, 4, 11, 12):
        return "ganado"
    if etype == 10:
        return "garrador"
    if etype == 13:
        return "garrador_armored"
    if etype == 9 and hp >= 2000:
        return "zealot_leader"
    if etype in (7, 9):
        return "zealot"
    if etype == 2:
        return "jj"
    if etype == 22:
        return "super_salvador"
    if 14 <= etype <= 21:
        return "militia"
    return None


def class_of(title, enemy: dict, stage=None) -> str | None:
    """The table key of a snapshot / frame enemy: RE4 from a GameCube class key ("em16.0b.hp6500"), a Switch census
    unit (its RAM class a vtable number) from its maximum health in its stage's set list (re4_unit_key; stage, or the
    row's own "stage"), else from a set list's type byte and health (re4_key); RE5 / RE6 its RAM class name."""
    if not isinstance(enemy, dict):
        return None
    t = canonical(title)
    if t == RE4:
        for k in ("cls", "class_id", "class"):
            v = enemy.get(k)
            if isinstance(v, str):
                if v in TABLE[RE4]:
                    return v
                m = _RE4_KEY.match(v)
                if m:
                    return re4_key(int(m["type"], 16), int(m["hp"]) if m["hp"] else enemy.get("hp_max"),
                                   "em" + m["em"])
        cls = enemy.get("class")
        if isinstance(cls, int) and not isinstance(cls, bool):          # the Switch census (re4_switch.read_unit)
            return re4_unit_key(enemy.get("hp_max"), stage or enemy.get("stage"), enemy.get("type"))
        return re4_key(enemy.get("type"), enemy.get("hp_max"))
    for k in ("cls", "class_id", "class"):
        v = enemy.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def resolve(title, enemy: dict, stage: str | None = None) -> dict:
    """What the map and the bots need of one enemy row: {cls, name, tier, weight, level, confirmed, known}; a class
    outside the table keeps its class as its name and is tiered by its health (tier_source "health"). stage: RE4's
    stage (its set list names a census unit by its health)."""
    cls = class_of(title, enemy, stage)
    hp_max = (enemy or {}).get("hp_max") if isinstance(enemy, dict) else None
    entry = identity(title, cls)
    if entry is None:
        t = _hp_tier(title, hp_max)
        out = {"cls": cls, "name": cls or "unknown", "tier": t or "normal", "weight": TIER_WEIGHT.get(t, UNKNOWN_WEIGHT)
               if t else UNKNOWN_WEIGHT, "level": "unconfirmed", "confirmed": False, "known": False}
        if t:
            out["tier_source"] = "health"
        return out
    v = _variant(entry, hp_max)
    t = (v or {}).get("tier") or entry["tier"]
    return {"cls": cls, "name": (v or {}).get("name") or entry["name"], "tier": t, "weight": TIER_WEIGHT[t],
            "level": entry["level"], "confirmed": entry["confirmed"], "known": True}


def name(title, cls) -> str:
    entry = identity(title, cls)
    return entry["name"] if entry else (str(cls) if cls else "unknown")


# --- RE5's stage table: the heavies by kill count --------------------------------------------------------------------
def _stage_key(stage) -> str | None:
    if not stage:
        return None
    s = str(stage).replace("_", " ").strip().lower()
    for t in STAGES.values():
        for k, v in t.items():
            if s in (k.lower(), v["code"].lower()):
                return k
    return None


def stage_info(title, stage) -> dict | None:
    """The stage's row (code, start_s, kills, heavies [(kill count or None, cls, where)], time_bonuses, notes) with
    each heavy's name, or None."""
    rows = STAGES.get(canonical(title)) or {}
    key = _stage_key(stage)
    row = rows.get(key) if key else None
    if row is None:
        return None
    heavies = [{"kills": k, "cls": c, "name": name(title, c), "tier": tier(title, c), "where": w}
               for k, c, w in row["heavies"]]
    return {"stage": key, **{k: v for k, v in row.items() if k != "heavies"}, "heavies": heavies}


def next_heavy(title, stage, kills) -> dict | None:
    """The next heavy the stage sends at or after this kill count ({kills, cls, name, tier, where, in_kills}), for the
    planner to be ready (mines, a flash, the magnum) a few kills before; None when none is left or unknown."""
    info = stage_info(title, stage)
    k = _num(kills)
    if info is None or k is None:
        return None
    later = sorted((h for h in info["heavies"] if h["kills"] is not None and h["kills"] >= k), key=lambda h: h["kills"])
    if not later:
        return None
    return dict(later[0], in_kills=int(later[0]["kills"] - k))


def stages_of(title) -> list[str]:
    return list((STAGES.get(canonical(title)) or {}).keys())
