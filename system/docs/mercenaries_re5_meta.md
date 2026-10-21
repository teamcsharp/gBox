# The Mercenaries meta: RE5 Reunion first, then RE4 / RE6 / Mercenaries 3D

Research for the Mercenaries bot (`gbox/mercs`, title #2 `gbox/mercs/titles/re5_ps3.py`), 2026-10-21. Web sources only
(no game sessions were run for this document); every number carries its source, and anything the community disagrees
on, or that only one old post says, is marked **(uncertain)**. Where the bot can read the real value from RAM (the
combo window, the clock, the hourglass positions) the RAM wins over any number here.

Operator's brief, verbatim: "every round played needs to be S rank / 5 stars in mercenaries. If there are S rank guides
for RE mercenaries mode, read them and internalize them and actuate them in gameplay." and "make sure that for Resident
Evil 5 you're utilizing every tip and trick that's used in the speedrunner scene". Section 1 is the S-rank answer; the
rest is the material behind it and the other games.

Access notes for whoever extends this: residentevil.fandom.com, gamefaqs.gamespot.com, steamcommunity guides,
nexusmods and fearlessrevolution refuse the PC's fetcher (402/403/429). The Spark's `curl` reaches Fandom's MediaWiki
API fine; the wikitext of the pages used here is kept in `~/gBox_alt/scratch/mercs-meta/wiki/` on the Spark, and the
community stage maps in `~/gBox_alt/scratch/mercs-meta/maps/` (section 4.1 lists them).

---

## 1. S rank every round (RE5 Gold, The Mercenaries Reunion, Solo)

### 1.1 The rank table (score only; same table on every stage, same in Reunion)

| Rank | Solo score | Duo score | Exchange points |
|---|---|---|---|
| D | 0 - 9,999 | 0 - 19,999 | 200 |
| C | 10,000+ | 20,000+ | 600 |
| B | 20,000+ | 40,000+ | 1,000 |
| A | 40,000+ | 80,000+ | 1,500 |
| **S** | **60,000+** | 120,000+ | 3,000 |
| **SS** | **90,000+** | 150,000+ | 5,000 |

Sources: Fandom [The Mercenaries (RE5)](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5)) "Grades" and the
[score guide](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5)_score_guide); the same table on the Japanese
[kouryakutsushin Mercenaries page](https://kouryakutsushin.com/bio5/mercenaries.htm) (D up to 9,999 ... SS 90,000+);
[GameFAQs Q&A "Is there an S Rank"](https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/answers/50572-is-there-an-s-rank-in-mercenaries-mode)
(SS 90,000 solo / 150,000 duo); [residentevil.org Mercs guide](https://residentevil.org/threads/re5-mercs-guide.1347/).

* The rank is a function of **score alone**. Time left and the kill count only matter through the score (leftover
  seconds are paid as points, kills are points). There is no per-stage table: every source gives one table for all 8
  stages, and the Reunion SS videos found (221k-387k, section 3) sit far above 90k on every stage. **(uncertain)**: no
  source states in so many words that Reunion's thresholds equal vanilla's; every rank statement about Reunion uses
  the same 90k / 150k figures, and the mode only changed what the points are worth.
* **Dying ends the round with no rank** and the score is not recorded (Fandom "Grades"). Solo has a self-revive: in
  Dying status, mash the partner-action button (Fandom "Rules"). The bot's "Continue? Yes" after death starts a fresh
  round; it never rescues the rank.
* B or better unlocks the next stage; the Reunion stages and characters are already unlocked by `re5 op=unlock_all`
  (docs/mercenaries.md).
* The game's own records: the Reunion stage x character score and rank are in the Gold block of DATA0.DAT
  (docs/mercenaries.md, "The Gold block"); a stage shows the rank at the results screen and in STAGE SELECT.

### 1.2 What a score is made of (Reunion solo)

Score = base points per kill + combo bonus per kill (banked when the combo ends or the round ends) + 1,000 per kill
during a combo chest's 30 s (replaces the normal combo bonus) + **300 x seconds left** when the 150th enemy dies
(vanilla: 1,000 x seconds). Sources: section 2.1; the 300/s rule from Fandom
[The Mercenaries Reunion](https://residentevil.fandom.com/wiki/The_Mercenaries_Reunion) "Rules" and the
[leaderboard guide](https://residentevilforums.forumotion.com/t3924-mercenaries-reunion-guide-to-leaderboard-runs-re5).

Base points (Fandom, kouryakutsushin): Town Majini 300, Wetland / Base Majini 400, Bui Kichwa 400, Kipepeo 700, Licker
beta 800, Cephalo 800, Duvalia 900, Adjule 900, Big Man 1,000, chicken 2,000, Executioner / Giant 5,000, Reaper 6,000,
Chainsaw 7,000, Gatling 10,000, Red Executioner 15,000.

Combo bonus per kill, Reunion (two independent transcriptions agree: the
[Resident Evil 5 Zone Reunion post](http://residentevil5zone.blogspot.com/2010/11/mercenaries-reunion-info.html) and
[residentevilforums t2261](https://residentevilforums.forumotion.com/t2261-re5-tips-and-tricks-for-maxing-the-score-on-mercenaries-re5);
vanilla stops at the 50+ row, per Berserker's
[scoring post](http://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-combo.html)):

| combo kill # | normal | boss | | combo kill # | normal | boss |
|---|---|---|---|---|---|---|
| 2 | 20 | 500 | | 50-59 | 1,000 | 7,000 |
| 3 | 50 | 1,000 | | 60-69 | 1,200 | 8,000 |
| 4 | 100 | 1,500 | | 70-79 | 1,400 | 10,000 |
| 5 | 200 | 2,000 | | 80-89 | 1,700 | 12,000 |
| 6 | 250 | 2,500 | | 90-99 | 2,000 | 15,000 |
| 7 | 300 | 3,000 | | 100-109 | 3,000 | 20,000 |
| 8 | 350 | 3,500 | | 110-119 | 4,000 | 30,000 |
| 9 | 400 | 4,000 | | 120-129 | 6,000 | 40,000 |
| 10-19 | 500 | 4,500 | | 130-139 | 10,000 | 50,000 |
| 20-29 | 600 | 5,000 | | 140-149 | 15,000 | 60,000 (one source: 69,000) |
| 30-39 | 700 | 5,500 | | 150 (and 151+) | 50,000 | 100,000 |
| 40-49 | 850 | 6,000 | | | | |

Cumulative normal-enemy bonus of one unbroken chain (RE5 Zone): 2,170 at combo 10, 7,270 at 20, 13,370 at 30,
20,520 at 40, 29,170 at 50, 39,370 at 60, 51,570 at 70, 83,170 at 90, 177,170 at 120, 346,170 at 140, **531,170 at
150**. Vanilla (fixed 1,000 after 50): about 129,170 for a full 150 (RE5 Zone).

**The arithmetic the bot should plan with (Public Assembly, Reunion, solo):**

| plan | kills | combos | base | combo bonus | leftover | total | rank |
|---|---|---|---|---|---|---|---|
| today's bot (live 2026-10-21) | 11-18 | best 12 | 3.5k-8.6k | - | 0 | 3,490-8,640 | D |
| kill 100 Majini in chains of 5 | 100 | 20 x 5 | ~33k | 20 x 370 = 7.4k | 0 | ~40k | A |
| clear the stage, chains of 5 only | 150 | 30 x 5 | ~68k* | 11k | 0 | ~79k | S |
| clear the stage, chains of 10-19 | 150 | 10 x 15 | ~68k | 10 x 4,670 = 47k | 0 | ~115k | SS |
| one 60-combo + the rest in 5s | 150 | 60 + 18 x 5 | ~68k | 39k + 7k | 0 | ~114k | SS |
| clear with 100 s left, chains of 10 | 150 | 15 x 10 | ~68k | 15 x 2,170 = 33k | 30k | ~131k | SS |
| the human ceiling (full 150 combo) | 150 | 1 x 150 | ~68k | 531k + 3 bosses at 100k | 20-60k | 846k (WR) | SS |

\* PA base: ~146 Majini-class at 300-1,000 (Town 300, Big Man 1,000, Duvalia 900, Bui Kichwa 400), 3 Executioners x
5,000, 1 chicken 2,000; about 68k if the Town/Big Man mix is the vanilla one. Numbers are estimates from the tables
above, not measured.

So on Public Assembly: **reaching 150 kills is an S by itself; SS needs the kills to come in chains of ten or
better** (or one long chain). The gate is not the score, it is time and kill rate.

**The time budget:** the clock starts at 2:00; PA's 9 hourglasses add 7:00 (4 x 30 s + 5 x 60 s, section 3.1); every
melee kill adds 5 s (knife kills do not; the stun rod does). 150 kills in 540 s is one kill every 3.6 s; with 50 melee
kills (+250 s) one every 5.3 s; with 70 melee kills (what Heavy Metal Chris players report, section 2.6) one every
6 s. The bot's live rate on 2026-10-21 was one kill every 8-10 s with no hourglass taken: **it needs every hourglass
and roughly twice the kill rate**, and the melee +5 s is what makes the budget close (a top human on PA finishes 150
kills in 9-11 minutes with 60-70 melee kills; the Reunion WR run, 846,708, is Rebecca whose head-stun Flame Spray kills
a normal Majini outright).

### 1.3 What the S-rank guides say, distilled

Guides read: Fandom [The Mercenaries (RE5)](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5)) and
[Reunion](https://residentevil.fandom.com/wiki/The_Mercenaries_Reunion); the Steam guide
[The Mercenaries](https://steamcommunity.com/sharedfiles/filedetails/?id=1224696225) (snippets only);
[GameFAQs "Guide to High Score on Mercenaries Reunion"](https://gamefaqs.gamespot.com/boards/929198-resident-evil-5/56220529);
[residentevilforums "Tips and tricks for maxing the score"](https://residentevilforums.forumotion.com/t2261-re5-tips-and-tricks-for-maxing-the-score-on-mercenaries-re5)
and the [leaderboard guide](https://residentevilforums.forumotion.com/t3924-mercenaries-reunion-guide-to-leaderboard-runs-re5);
Berserker's [Public Assembly solo strategy](http://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-public.html)
and [scoring system](http://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-combo.html);
stv_tribute's [PA route](https://stv-tribute.hatenadiary.org/entry/20091115/1258287503) (JP);
[kouryakutsushin](https://kouryakutsushin.com/bio5/reunion.htm) (JP); the
[residentevil.org Reunion character ratings](https://residentevil.org/threads/the-mercenaries-reunion-characters-rated-best-to-worst.2661/).
What every one of them says, in the order they say to do it:

1. **Time first.** Take the 2-3 nearest hourglasses before the first kill and build a 4-5 minute buffer; kill only
   what blocks the path (every kill now is one fewer for the combo later) (t2261). Berserker's PA route takes two 30 s
   bonuses (the north shack, the waterway) before the first fight. The remaining hourglasses are taken mid-run when no
   enemy is within reach, and one or two are **saved for the end** (the roof / south-building 60 s on PA) so the last
   kills happen with time on the clock.
2. **Melee is the clock.** Shoot the thigh with the machine gun (5-6 rounds on Veteran, 2-3 to knock down), take the
   prompt, melee: +5 s and invincibility frames for the whole animation; a melee every 4-5 s holds the clock steady
   (t2261). Aim does not need to be precise: "sweep the gun downward while firing".
3. **Keep the combo.** Kills within 10 s of each other (Fandom); never trade the combo for a melee ("dropping the
   combo costs far more than a melee gains", t3924); move when spawns slow (about every 20 kills on PA, stv_tribute);
   wake the camping Majini (they do not move until shot or approached, Berserker).
4. **The stand.** PA: by the bus (Executioners cannot enter it; GameFAQs, kouryakutsushin), or the waterway strip
   between the ramp and the north wall (Berserker), or the flat ground between the two buildings near the transformer
   where Majini come only from front and back (Berserker). Prison: the front corridor of the 1F central room (enemies
   one at a time). Mines: the long tunnel's south end. Ship Deck: the middle crate corridor.
5. **Plaga heads: flash.** A flash grenade (or Excella's flash rounds) kills Cephalo, Kipepeo, Bui Kichwa and Duvalia
   outright; after kill ~50 in Reunion mutations start, none in the first wave (Fandom Reunion, t2261,
   kouryakutsushin creature page). Avoid head kills on Majini that are not stunned (random Cephalo).
6. **Bosses.** For an S rank just kill them safely: Executioner from range with the strong weapon, stun (flash, acid,
   barrel, head/leg shots) then melee or magnum; never double-melee (wild swing). For a high score hold them until
   the combo is 120+ (section 2.5).
7. **Never die.** "Survival is always first priority" (residentevil.org). A death is a D-less nothing.

### 1.4 Per-character S-rank route (Reunion solo; loadouts from Fandom Reunion and kouryakutsushin)

| character | loadout (x = count) | the S-rank way | notes |
|---|---|---|---|
| **Chris, Heavy Metal** (the bot's current pick) | Gatling Gun (infinite, 350/bullet, spin-up, heavy recoil, slow walk), Stun Rod (350; x5 vs Plaga; cancels a Plaga spawn if the Majini dies before mutating), Hand Grenade x3, Proximity Bomb x3, Melee Vest (-50 melee dmg), Bulletproof Vest (-50 projectile dmg); the ammo backpack blocks rear grabs and rear hits | Gatling the legs at 3-6 m until the kneel, walk in, **Uppercut** (front, 500) or get behind for **Neckbreaker** (instant kill, +5 s). Stun-rod kills count as melee (+5 s): use it on the stragglers the Gatling already wounded. Proximity bombs on the approach to the stand; grenades for the Executioner or a pack. Pre-spin the Gatling when a group is 10 m out. | Community rates him last for score (slow, inaccurate, long boss fights) but "the best for making combos" and "60-70 melee kills a run"; one player's no-gun run: 116 kills, 65,740 = S (residentevil.org). KrossH solo PA PBs 757k and 843k with him (section 3). |
| **Sheva, Business** | SIG P226 x16 (+50; 480 dmg), L. Hawk x8 (+12; 3,000, level-8 piercing), Proximity Bomb x5, First Aid Spray x1 | Handgun headshot / leg shot -> Roundhouse (600) / Somersault (600) / **Throat Slit** (back leg, instant kill); L. Hawk on Executioners (chest then legs, then melee). Ranked best overall by several players ("handgun and magnum strong enough to kill almost anything"). | |
| **Sheva, Fairy Tale** | SIG 556 x80 (+100; 180), S&W M500 x6 (+6; 4,500), Ithaca M37 x25 (+10; 400 x7), Gold Egg x5 | MG legs -> Somersault / Throat Slit; M500 for bosses; eggs are full heals. The "balanced" pick; SS videos at 221-222k on Village / Exp. Facility (section 3). | |
| **Chris, Warrior** | H&K P8 x25 (+30; 300, level-3 piercing), PSG-1 x15 (1,200, scope 8), Hydra x10 (+15; 400 x3) | Hydra at close range, P8 legs -> Uppercut / Neckbreaker; rifle for Executioners / campers. Same melees as Heavy Metal; "clears S/SS easily" (aintnoscrub). | |
| **Josh** | M92F x100 (+10; 250), M3 x10 (+10; 900 x7), Rocket Launcher x1, Hand Grenade x3 | M92F head -> **Hammer Blow** (700); leg from behind -> **Suplex** (instant kill); ground -> Elbow Drop (1,000); RL for the Executioner at high combo. Strong but slow melees. | |
| **Excella** | M93R x30 (+50; 400, 3-round burst), AK-74 x50 (+150; 220), Grenade Launcher x12 FLASH rounds, FAS x1 | M93R headshot -> **High Heel** (400; "a one-hit kill on Majini" after the burst), leg from behind -> **First Aid** (instant kill); 12 flash rounds = 12 free Plaga kills and crowd stuns. | Slow melees; the 12 flashes make her the Reunion Village / Ruins choice (t3924). |
| **Barry** | Samurai Edge x30 (+50; 350, piercing 2), S&W M29 x12 (+6; 3,000), Dragunov SVD x18 (1,300) | Headshot -> **Headbutt** (400, ~75 % critical, never spawns a Plaga); back leg -> **Gun Bash** (600-1,200, 100 % critical); ground -> Miranda Rights (5,000). M29 for bosses. "The Wesker of this group." | No healing items at start. |
| **Rebecca** | H&K MP5 x120 (+150; 120, piercing 3), Jail Breaker x10 (+30; 300), First Aid Spray x1 (one source: x2) | MP5 headshot -> **Flame Spray** (900): kills a normal Majini outright, +5 s; flash a group then flame-spray each; Jail Breaker at point blank. The Reunion solo WR character (PA 846,708; Prison 924,555; Ship Deck 1,043,176; Missile 733,303; Exp. Facility 678,125 - section 3). | Weak non-head melees; "high kill counts". |

Duo-only moves (Rising Upper, Hammer Elbow, Double Fang, Maximum Straight, Cross Slap, Lights Out, Double Flame
Spray) do not exist in Solo.

**For the bot, in order of expected S-rank per hour of engineering:** stay with Heavy Metal Chris (no ammo logic, two
vests, the backpack cancels the grab that costs it the combo), add the hourglass tour and the leg-stun -> Uppercut /
Neckbreaker loop; then Rebecca (MP5 head -> Flame Spray kills, +5 s each) once ammo and reload are driven; then Sheva
Business for the magnum on bosses.

### 1.5 The S-rank checklist (what the strategy engine executes; PA first, the other stages in 3.x)

Phase / condition / action. `T` = clock, `K` = kills, `C` = combo, `W` = combo window left (RAM `merc.combo_timer`),
`N` = enemies in play (max 12).

| # | phase | condition | action |
|---|---|---|---|
| 1 | round start | always | read the hourglass list (RAM, uOm0100 units) and the start point; pick the tour that takes the 2-3 nearest hourglasses first along the navmesh, the far ones later, and reserve one 60 s (roof / south building) for the end |
| 2 | gather | no hourglass within 15 m and T > 60 s | walk the tour; shoot only what blocks the path (leg shot, melee if it kneels); do not chase |
| 3 | gather | an hourglass within 15 m on the same level | go, face it, press square on "Time bonus"; a Majini within 7 m: stun it first (leg) and melee, then take it |
| 4 | fight | T buffer >= 4 min (or the first 3 hourglasses taken) | go to the stand (PA: the bus side / the strip between the two buildings); fight there |
| 5 | fight, each target | nearest Majini in front, 3-8 m | Gatling / MG at the thighs until it kneels; walk in; if behind it: Neckbreaker (instant kill); else Uppercut; press the prompt; the gun stays down for the press |
| 6 | fight, clock | T < 90 s and an hourglass within 25 m | take it now, even mid-combo, as long as W > 4 s |
| 7 | fight, combo | W < 4 s and a Majini is reachable in W | shoot it dead (body shots, grenade if a group); forget the melee |
| 8 | fight, combo | W < 4 s and nothing reachable | let it drop; do not run into a crowd for it |
| 9 | fight, pacing | no kill in 15 s and N < 4 | move 20-30 m toward the next spawn region / unaggroed camper (PA: north shack <-> alley <-> buildings); shoot campers once |
| 10 | fight, Plaga | a Cephalo / Kipepeo / Bui Kichwa / Duvalia emerges | flash grenade if held; else Gatling from 6+ m (Cephalo), back off from Duvalia (6,000 HP) and leave it unless it blocks the stand |
| 11 | fight, boss | Executioner within 12 m | back off out of axe reach, Gatling the head/legs; when he kneels: melee once (never twice); grenade when 2+ Majini stand with him; S rank: kill him; high score: hold him until C >= 120 |
| 12 | fight, grab | player action 4 ("Break free") | wiggle; after breaking free step back 3 m before the next shot |
| 13 | fight, health | hp < 40 % | step out of the crowd; eat the egg / spray if held; proximity bomb behind |
| 14 | finish | K >= 140 | make sure 2 Majini are alive before each kill (the last spawn can be far); take the reserved 60 s; kill the last with a gun, not a melee, so the combo holds |
| 15 | finish | K = 150 | nothing: the round ends; leftover time pays 300/s |
| 16 | always | hp = 0 | "Continue? Yes" restarts the stage; the rank is lost; log it as a lesson |

Minimums for the rank, PA solo: S = 150 kills with any combos (or ~120 kills with chains of 10); SS = 150 kills in
chains of 10+, or a 60-combo somewhere in the round, or ~100 s left at the end with chains of 10.

---

## 2. RE5 Reunion: the facts behind section 1

### 2.1 Scoring and the combo

* **Base points** per enemy and the **combo table**: section 1.2. Points are awarded when an enemy's full HP is gone;
  a blue Chainsaw Majini must lose its HP in berserk mode (Berserker scoring post). Kills past 150 by piercing /
  explosions / one melee still add points (Fandom RE5 "Scoring").
* **Combo window: 10 s between kills** (Fandom, kouryakutsushin, Berserker). The bot reads it directly:
  cGameSys `+0x404` f32 (`merc.combo_timer`, `re5_ps3.py` GS_COMBO_T). An older guide's "11 s" is the display.
* **Payout**: the combo bonus is banked when the combo breaks or the round ends (Berserker: "not added to the score until
  the combo is broken or until the run ends at 150 combo"). So `merc.score` in RAM (cGameSys `+0x418`) lags the true
  total by the pending chain bonus; the strategy engine should add the pending bonus from the table when it estimates
  the rank mid-round. **(uncertain)** whether the PS3 build banks per kill into a separate field: not looked for.
* **Combo chest** ("Combo Bonus", a chest opened with the action button): for **30 s** every combo kill's bonus
  becomes 1,000 instead of the table value (kouryakutsushin: "each enemy killed during the next 30 seconds is worth
  1,000"; Berserker's chest table). Net gain per kill = 1,000 - table bonus: +980 at combo 2 ... +500 at 10-19,
  +300 at 30-39, +150 at 40-49, **0 at 50+**. A 55-combo test (stv_tribute,
  [impressions post](https://stv-tribute.hatenadiary.org/entry/20100316/1268751267)): no chest 34,170; chest during
  kills 1-5: 37,800; during 46-50: 34,770; during 51-55: 34,170. Rule: open a chest right after the first kill of a
  chain (the bonus starts at combo 2), never after 50. During chest time, extra kills by gun / grenade beat melee.
* **Boss bonus** is a flat value per 10-kill bracket: a boss at combo 121 pays the same as at 129 (t3924). A boss at
  150 = 100,000 + base. Top runs hold the stage's bosses until 120-150 (section 2.5).
* **Leftover time**: 300 points per second in Reunion (and United), 1,000 in vanilla; paid only when the 150th enemy
  dies. A 2 s Neckbreaker that adds 5 s nets +900 at the end (t3924).

### 2.2 Time

* Clock starts at **2:00**; no upper limit; each hourglass ("time crystal" / "Time Bonus") works once and adds **30, 60
  or 90 s** (Fandom "Rules"). In RE5 the hourglass is **taken with the action button** at the object ("□ Time bonus",
  live frame `docs/evidence/re5-merc-bot/gbox-time-bonus-prompt.jpg`); Fandom says "smashing (perform a melee attack
  while nearby)" - that is the same square press. Gunfire at it, knife slashes and walking over it do not take it
  (live, docs/mercenaries.md). Community guides write "hit / break the 30" for the same action.
* **+5 s per melee kill**, including kills by the stun rod and multi-kills (each kill adds 5, the HUD shows one
  "+05 Sec."); knife kills do not count (Fandom "Rules"; live frames `gbox-finisher-pressed-plus-5-sec.jpg`).
* Per-stage hourglass inventory and par (RE5 Zone Reunion post; PA from Berserker's route; Reunion keeps the same
  positions on Village and Ship Deck, "partly changed" on the others per kouryakutsushin):

| stage | hourglasses | total | par (2:00 + all) |
|---|---|---|---|
| Public Assembly | 4 x 30, 5 x 60 (9; matches the 9 uOm0100 units the bot sees) | 7:00 | 9:00 |
| The Mines | 1 x 90, 2 x 60, 5 x 30 (8) | 6:00 | 8:00 |
| Village | 1 x 90, 4 x 60, 3 x 30 (8) | 7:00 | 9:00 |
| Ancient Ruins | 2 x 90, 2 x 60, 6 x 30 (10) | 8:00 | 10:00 |
| Experimental Facility | 4 x 60, 4 x 30 (8) | 6:00 | 8:00 |
| Missile Area | 1 x 90, 5 x 60, 5 x 30 (11) | 9:00 | 11:00 |
| Ship Deck | 1 x 90, 6 x 60, 4 x 30 (11) | 9:30 | 11:30 |
| Prison | 5 x 60, 7 x 30 (12) | 8:30 | 10:30 |

* Opening the inventory does not pause the game; **menu reload** (drag the ammo onto the gun) has no animation and is
  done during melee animations, ladder climbs, window hops and drops; a melee during a reload animation cancels it
  and the gun is still reloaded (Fandom RE5 gameplay, kouryakutsushin tips, t3924). Picking up an item is a dodge
  (the pickup animation has i-frames; Berserker uses the mid-stairs boxes on Exp. Facility).

### 2.3 Spawns, caps and aggro

* **150 enemies per stage, at most 12 in play**; one dies, one spawns (Fandom "Rules"; Berserker's Prison and Ship
  Deck pages: "12 or fewer in the stage the entire time"). Chickens, campers and bosses occupy slots; a camper that is
  never woken sits in a slot all round (Berserker Prison duo: "occupies one of the 12 enemy slots for the whole run").
  Village and Ancient Ruins exceed 150 (Kipepeo hosts count twice; Village = 80 + 60 + 4 bosses + 12 start + Kipepeo).
* **Spawn regions**: each stage is split into regions that spawn only while the player stands in them (Berserker's
  region maps; identical in Reunion per RE5 Zone). Counts: Mines north 75 / south 60 + 3 Reapers + 12 start; Village
  bottom 80 / top 60; Exp. Facility top 72 / south 60 + 9 start (+3); Missile upper A/B 40 (overlapping), bottom
  ~46-50, final 24; Ship Deck A 52 SW / B 40 SE / C 40 N with a dead zone in the south gap; Prison one region, 134 +
  5 Executioners + 11 start. PA: the north region feeds the middle until the player passes the Executioner platform;
  the back alley is a dry zone (Berserker PA solo).
* **Pacing**: staying put slows spawns; top players move about every 20 kills on PA (stv_tribute) and "search out"
  enemies on Village's slow bottom. Spawns come over walls / fences / ledges ("wall spawn", "fence spawn", "ceiling
  spawn"); the next enemy often arrives 5-8 s after a kill, which is why W (the window) is what the bot watches.
* **Campers** do not move until shot or until the player enters their detection range (the hill Majini at PA's start,
  the columns Majini, the long-pipe + female pair by the NW chest, Ship Deck's tower bowguns). Shoot once, then leave.
* **Scripted enemies**: some Majini always become a Cephalo on a headshot ("fixed" Cephalo: 5 body shots instead of 3,
  stv_tribute), some always Duvalia (Exp. Facility's armored one, Ruins' explosive-arrow one); kill those with a leg
  stun + rear instant-kill melee, a ground melee, an explosion or a rocket, never a headshot (Berserker, RE5 Zone).
* **Reunion**: no Plaga in the first wave; mutations after ~50 kills (Fandom Reunion "Rules": "sub-bosses spawn in
  after 50 kills, whereas previously 30" - the page uses "sub-bosses" for the Plaga types); Duvalia on every stage
  except Mines and Missile Area; Town Majini can become Duvalia; Big Man packs of 3-4 on PA / Mines, one magnum shot
  each (Fandom Big Man notes); Bui Kichwa on PA + Village; Adjule in the Mines (900); Lickers mixed with Base Majini
  from the start on Exp. Facility. **Bosses one at a time and on a timer**: PA "a certain amount of time after the
  round begins, the Executioner will arrive ... if he is killed, more Executioners will eventually spawn in"; Mines
  Reapers "show up every now and then after a certain amount of time" (Fandom Reunion). Vanilla used kill counts
  (section 3). **(uncertain)** the exact Reunion timers: nobody has published them; the bot should log the clock at
  each boss spawn (`enemies.type` change) and learn them.
* **Difficulty scaling**: the official guidebook says Reunion's "Player Rank" changes during play and drives enemy
  dodge chance, knockdown recovery, flash-blind duration, wait-before-rush time, run-to-walk distance and grab-escape
  inputs (stv_tribute, [guidebook notes](https://stv-tribute.hatenadiary.org/entry/20100328/1269751620)). A
  RAM-visible knob worth finding: enemies get harder as the player does well.

### 2.4 Melee: stuns, finishers, instant kills

* Three stun sites: **head** (one shot "always stuns" a walking Majini per Fandom's melee page; a Steam tester:
  guaranteed only while walking / attacking / grabbing; not on armored Base Majini), **arm** (hard to hit, not always
  a one-shot stun), **leg** (easiest to hit, 1-4 shots; "thigh with the MG, 2-3 rounds to knock down" per t2261).
  Body shots never stun. Front vs back decides the move. Stuns are guaranteed while the player is being grabbed.
* Head kills roll a **random Cephalo** (more on Missile Area and PA's female Majini); the stun-then-melee route and
  the rear instant kills do not (Berserker, RE5 Zone, stv_tribute). Hence the guides' "legs, not head" for the
  characters without a head-kill melee.
* **Melee = invincibility for the animation** (t3924, t2261, Fandom gameplay). A long finisher is a 12 s safe spot in
  which the next spawn arrives (stv_tribute).
* Reunion melee table (Fandom Reunion; HP = damage; partner moves omitted):

| stun | Chris | Sheva | Josh | Excella | Barry | Rebecca |
|---|---|---|---|---|---|---|
| head | Straight 500 | Roundhouse 600 | Hammer Blow 700 | High Heel 400 | Headbutt 400 (~75 % crit, no Plaga) | Flame Spray 900 (kills a Majini) |
| arm, front | Hook 300 | Twist Kick 250 | Backhand 400 | Slap 50 | Barry Sandwich 300 | Tear Gas 200 |
| arm, back | Kick 300 | Knee 250 | Iron Tackle 800 | Back Hand 50 | Knee 300 | Rump Shaker 200 |
| leg, front | Uppercut 500 | Somersault 600 | Power Kick 400 | Humiliate 800 | Burton Boot 400 | Jump Hit 300 |
| leg, back | **Neckbreaker: kill** | **Throat Slit: kill** | **Suplex: kill** | **First Aid: kill** | Gun Bash 600 (RE5 Zone: 1,200, 100 % crit) | Head Cracker 400 (~25 % crit) |
| ground | Stomp 600 | Impale 800 | Elbow Drop 1,000 | Heel Stomp 500 x4 | Miranda Rights 5,000 | Kick 500 |

  Vanilla Chris/Sheva values are lower (Straight 400, Uppercut 400, Roundhouse 350, Somersault 350). Majini HP:
  Town 800 (female 700, Agitator 1,400), Wetland 700-900, Base 800, Big Man 4,000 (Reunion 3,000), Cephalo 3,000,
  Duvalia 6,000, Kipepeo 1,000, Bui Kichwa 200, Licker beta 900 (Berserker stat list, RE5 Zone).
* **Lag shot** (Berserker, [post](http://berserkersblog.blogspot.com/2012/04/resident-evil-5-mercenaries-lag-shot.html)):
  fire the instant before the melee lands so the bullet's damage plus the melee kills a Majini the melee alone would
  not. Leg-stun, rush to the prompt, aim (L1), R1 then square at once; the square must land after the shot leaves and
  before the bullet hits. Aim at the body, not the head (random Cephalo / crit) or the leg (fall, missed melee).
  Chris's and Sheva's front leg melees connect on grounded enemies, which is what makes it work for them.

### 2.5 Bosses and Plaga types (handling that the guides agree on)

| enemy | HP (vanilla) | handling |
|---|---|---|
| Executioner (PA 8,000; Prison black 15,000, red 20,000; 5,000 / 15,000 pts) | stays out of axe reach; stun with flash, acid, an explosive barrel, head or leg shots, then one melee (a double melee triggers the wild swing); magnum "chest then legs, then melee" (stv_tribute); the red one's back Plaga staggers him on any hit (Fandom Prison); **cannot enter PA's bus** (kouryakutsushin); his swelling corpse explodes: shoot it to detonate it harmlessly or let it kill Majini near him (no melee bonus) |
| Chainsaw Majini (red 7,000; blue 15,000, berserk 1,500; 7,000 pts) | leg shot stuns; a blue one gets up berserk after its first "death" and only then counts; flash stuns a berserker; rocket / magnum through a lined-up pair (Berserker Ship Deck) |
| Reaper (1,500; 6,000 pts) | when it drops it turns and shows its chest sac: a burst into the chest; a flash exposes the white sacs (Fandom, Berserker Mines) |
| Gatling Majini (yellow 4,000 / red 6,000; 10,000 pts) | hand grenades do ~30 % and machine guns ~25-30 % to him (Berserker Chris guide); magnum 2 leg shots + melee (red: 3) (stv_tribute); fight him where he has to come down a ladder or walkway |
| Big Man / Giant (4,000; 1,000 / 5,000 pts) | the mask is invulnerable: torso and legs until the kneel, then melee; shotgun knockback sets up melee; one magnum shot in Reunion (Fandom) |
| Licker beta (900; 800 pts) | approach from the side, use railings as cover, bullet-kill; the counter prompt when it leaps (Chris Uppercut Counter 600) |
| Cephalo (3,000; 800) / Kipepeo (1,000; 700) / Bui Kichwa (200; 400) / Duvalia (6,000; 900) | **a flash grenade kills all four outright** (Fandom Duvalia, kouryakutsushin creature page, StrategyWiki); Duvalia also dies to a hand grenade under it; a Majini killed on the ground cannot become a Duvalia; Josh's Suplex, Chris's Neckbreaker, Sheva's Throat Slit, Excella's First Aid and the stun rod cancel the mutation |
| Chicken (HP 1; 2,000) | counts as one of the 150 and takes a slot until killed; drops a gold egg (full heal); grenade it or flash it when it runs; it appears ~9 s into the round (4gamer) |

High-score boss rule (t3924): a boss at combo 50 is +7,000, at 150 +100,000; PA: kill Executioner 1 at ~140, let #2
"die as it enters", #3 at 150; stages with more than 3 bosses: kill at 120 as the safety net; Prison: the first at 130
only if the last can still spawn at ~148. Holding a boss at 145: do not magnum the crowd, the next boss may spawn far
away and the 10 s window runs out (stv_tribute).

### 2.6 Reunion characters (community verdicts)

From [residentevil.org's rating thread](https://residentevil.org/threads/the-mercenaries-reunion-characters-rated-best-to-worst.2661/),
[GameFAQs 56220529](https://gamefaqs.gamespot.com/boards/929198-resident-evil-5/56220529) and the WR table in section 3:
Rebecca, Barry and Sheva Business top most lists; Heavy Metal Chris is last on most lists but his defenders report
"60-70 melee kills a run" and the highest personal scores; Excella's 12 flash rounds make her the pick where Plaga
types matter (Village, Ruins); Josh's melees are strong but slow; Warrior Chris's Hydra is strong, his rifle slow.
Loadouts: section 1.4.

---

## 3. RE5 Reunion stage by stage (layout, hourglasses, route, stand, bosses, records)

Each stage: the layout as the community maps draw it (so the bot can match landmarks to its navmesh; the RAM hourglass
positions are the truth, these are the names), the hourglass route top players use, the stand, the bosses, and the
best known solo scores. Vanilla routes are Berserker's (same geometry; Reunion moved a few hourglasses and chickens).
WR rows are self-reported video titles unless marked; the speedrun.com Reunion boards hold only a handful of runs
(Steam game 369po01l / category zdnp7e7k); the real top runs are on YouTube and nicovideo.

### 3.1 Public Assembly

**Layout** (official guide map p.178 via Fandom; kouryakutsushin Reunion map; Berserker; stv_tribute). A walled
rectangle, long axis north-south, about 70 m. **North edge**: a raised wooden walkway with the shack over the
waterway (30 s inside the shack; a window drops into the waterway). **West edge**: the waterway (sunken channel)
running south from the shack, then bending east along the south-west (the Reunion chicken is at the bend / by the
hut; a 30 s is in the waterway to the west of the shack). **Centre**: two buildings side by side with a narrow alley
between them and a transformer at its end (flat ground: Majini come only from front and back) - the "central house"
has a cracked wall that a hand grenade opens (60 s inside) and the other has a ladder to its roof (60 s on the roof);
the ramp from the back alleys climbs onto the west rooftops. **East-centre**: the Executioner platform with the fence
spawn behind it, and the columns (30 s by the columns). **East edge**: the side buildings where the green-dress and
red-dress females camp (60 s up the ladder near the car). **South**: the bus (60 s inside; Executioners cannot enter;
oil canisters beside it) and the south building with a ladder to its top (60 s, saved for the end). Combo chests: one
near the chest-spawn start, one in the bus, one NW by the long-pipe / female campers. Start points: the platform
(solo: best, wakes the campers on the way north) and the chest spawn.

**Hourglasses (9 = 7:00)**: 30 s north shack, 30 s west waterway, 60 s back alley, 30 s columns, 60 s rooftop, 60 s
bus, 60 s cracked-wall house, 60 s south building top, 30 s by the ramp / platform side (Berserker solo + duo pages).
Reunion moved some of these "partly" (kouryakutsushin); the JP Reunion map shows 4 x 30 and 5 x 60, which matches.

**Route (Berserker solo, vanilla; stv_tribute JP route in brackets)**: start on the platform, shoot the hill Majini
once (he never moves otherwise) [or throw the grenade at the central house's wall before moving], drop north between
the two buildings (not over the roofs: that leaves the ramp Majini asleep), north shack 30 s, out the window, waterway
30 s, grenade the chicken (+2,000) [the chicken is the first enemy], melee the opening crowd as it drops into the
waterway (the Agitator has 1,400 HP: shoot him first), stand in the strip between the ramp and the north wall and
keep moving; at ~27 combo leave the waterway to meet Executioner 1 in the shade below the western building; then the
alley 60 s and the columns 30 s when few are near; roof at 50-70 combo for the two 60 s (roof, bus), drop off the
bus's east side with a Majini (shoot one at the bus edge so you land on it and melee it); fight between the buildings
near the transformer; grenade the cracked wall when quiet, take the 60 s right after a kill; cocktail Majini from
~100 combo in the south (kill at once, avoid the oil canisters); fight the middle until ~90 combo so the north region
empties; at 147 make sure two Majini are alive; before the last kill climb the south building's ladder for its 60 s;
gun the last Majini (no melee) so the combo holds.

**Stand**: the waterway strip (early), the alley by the transformer (middle), the bus side (late, Reunion).

**Bosses**: vanilla Executioners at 20 / 50 / 70 kills (first from the hill fence SW, second from behind the platform,
third from the gate by the NW chest); Reunion: time-triggered, one at a time, more after a kill. High score: #1 at
140, #2 as it enters, #3 at 150.

**Records (solo)**: Reunion 846,708 Rebecca, R0DEATH, Steam 120 fps, 2023 (speedrun.com #1, video
[SnbgCfagkHQ](https://youtu.be/SnbgCfagkHQ)); 845,701 Rebecca, poyoyon46 ([EC-tueePgbQ](https://www.youtube.com/watch?v=EC-tueePgbQ));
843k Chris Heavy Metal, KrossH ([rntM3ymgeSU](https://www.youtube.com/watch?v=rntM3ymgeSU)); 832K Excella (nicovideo
sm18309033); 778,527 Sheva Business, AbsoluteJusticeX 2011; 729,907 Excella, JermTheWorm26. Mercenaries United
(PS4 remaster, Reunion rules): 916,108 Chris HM, Seb Mercenary. Duo Reunion 920,402 Barry + Chris HM. Vanilla solo
805,273 (JP video "Biohazard5 the mercenaries SOLO Public Assembly").

### 3.2 The Mines

**Layout** (JP map, Berserker): a long north-south cave. **South**: start S1 in a small cave with a 30 s; the lower
tunnel runs north-west with a red-wrench camper at its far end, a 60 s in a side pocket on the west wall, a dead-end
cave with a 30 s and a combo chest; the "long tunnel" to the north has its south end sitting between the two spawn
regions. **Middle**: the upper cave with a 30 s (reached by the north tunnel from the platform start), the ledge drop
outside the tunnel, a wooden bridge with a ladder at its south end. **North-east**: a raised loop (the wooden
platforms) around a central block: 90 s on the tall platform (a ladder up), 30 s in the loop's middle room, 30 s on
the loop's north side, S2 start at the east, a 60 s at the loop's south-west. Open north area with bridges / ledges
(cocktails from above), a 60 s in the west dead-end tunnel. Chickens: vanilla 2 (upper north tunnel, mid lower
tunnel); Reunion 1 in the central plaza by the passage. Mines Majini have 700 HP (cocktail, bowgun, dynamite).

**Hourglasses (8 = 6:00)**: 30 upper cave, 90 tall platform, 30 near the bridge ladder (skipped first), 60 dead-end
tunnel, 30 dead-end cave (with the chest), 30 back cave, 60 west dead-end tunnel (north area), 30 wooden bridge (end).

**Route (Berserker solo)**: platform start, drop right, north tunnel (kill chicken 1 with a dash / melee), 30 s mid
upper cave, stagger the long-pipe Majini by the red barrel, melee the dynamite Majini outside the exit before he
lights it (an exploding one gives no +5 and kills your melee set-ups), drop, climb to the 90 s, back down the ladder,
over the wooden bridge, down its south ladder, skip the 30 and the dead-end 60 for now; bottom tunnel: pass the
red-wrench camper on his left, chicken 2, 30 s in the dead-end cave + chest after the first kill (optional), fight in
the narrow corridor (enemies line up); three scripted Cephalo green-bottle Majini from the north ledge; keep moving
south, flash grenade from the crates; **Reaper 1 at 30 kills** from the back-fence ledge (chest burst as it turns);
campers (dynamite + Big Man) in the back area at ~35; 30 s in the back cave; leave at ~60 (enemies run out ~70), 60 s
by the back chest on the way; return to the long tunnel's south end so the north region keeps spawning; **Reaper 2 at
70** from the right ledge at the tunnel's north end; stay inside until ~90; **Reaper 3 at 90** from the ledge above the
tall platform; flash from the mine cart; open north area only when Majini stop grouping at the tunnel mouth (strafe
bowguns, never run straight at them; cocktails from the bridges: keep moving, go back to the tunnel mouth); 60 s west
dead-end; four scripted left-handed Cephalos (2 sickle from above the 90 s, 2 pick from the upper-cave fence) late in
the north; climb at 120-140 (back ledge ladder or wooden-platform ladder), 30 s on the wooden bridge before the last
kills; the remaining enemies spawn slowly from above. Regions: north 75, south 60.

**Stand**: the narrow lower corridor (early), the long tunnel's south end (middle), the tunnel mouth (late).

**Reunion**: Adjule added (900 pts; the split-head form dies to a flash), Reapers on a timer one at a time, Big Man
packs of 3-4 (one magnum shot each), one chicken (central plaza).

**Records**: 810k Josh, DuskyThrush03 ([AvZVqkAlIkw](https://www.youtube.com/watch?v=AvZVqkAlIkw)); 803k Rebecca,
poyoyon46 (missed one hourglass); 769k Excella (sm10116020); 712k Rebecca, FluffyQuack (PC).

### 3.3 Village

**Layout** (JP map, Berserker): two levels. **Top (north)**: the start, a 60 s straight ahead (skipped at first), the
bridge to the right over the gap, the cave at the back (60 s saved for the end), the rooftop with the 90 s under it,
the middle walkway with a 60 s, the top cave. **Bottom (south)**: the fenced chicken area below the start, the east
walkway reached by zipline or drop (30 s on its left side, 30 s below it with a green herb), the central altar with
three flash grenades, the stairs and the building across them (window hop, 60 s inside), the south-west hut (60 s
behind it, three more flashes), the west building with its alley on the north side, the north-east hill wall and the
narrow path between the hill route and the walkway structure. Spike traps: two, triggered by a kick on the trigger
button, kill whatever stands on them. Reunion chicken by the cave.

**Hourglasses (8 = 7:00)**: 60 top start (skip), 60 back of cave (end), 90 under the rooftop, 30 walkway left, 30
below the walkway, 60 building across the stairs, 60 behind the SW hut, 30 near the north bridge wall (+ the middle
walkway 60 s per the JP map; the RE5 Zone count is 1 x 90, 4 x 60, 3 x 30).

**Route (Berserker solo)**: top: skip the first 60, cross the bridge, leave the cave 60, hop the gap, 90 s under the
rooftop, kill the chicken in the pen below before dropping (dash, grenade, electric round, or after landing); bottom:
zipline or drop to the east walkway, 30 s + 30 s + herb, three flashes at the altar, stairs, window hop, 60 s inside,
back out, three flashes + 60 s behind the SW hut; chest after the first kill; the opening crowd is 12 Wetland Majini
(900 HP shieldless, 700 otherwise): one attacks at a time, kill the attacker, kill wooden-shield Majini first (they
ignore grace periods); scripted spear Cephalos before 20 (wall behind the west building's south), ~30 (NE hill wall,
west building, below the north building by the 30 s), ~60 (two from the NE hill, one below the north building): a
flash kills two at once; **Giants at 20 / 40 / 60 / 70** (east walkway wall, south gate, NE hill wall, high wooden
ledge above the west building); stands: the alley north of the west building, the chicken pen, the narrow path by
the hill route; bottom spawns are slow: search; cross the bridge at ~90 (the regions overlap on the north bridge; if
bottom enemies still come at 95 you stand too close to the bridge); 30 s at the bridge wall with a strong weapon
ready, up the stairs; top: never fight on the bridge, fight in the narrow outside strips by the building walls,
shield Majini in numbers at 100-110 (legs from range), 60 s middle walkway and 60 s top cave before ~146, scripted
Cephalos from 120 (top cave, three bowguns from the NE wall, a spear below the north building); the stage has more
than 150 enemies (Kipepeo), so enemies remain on screen at the end.

**Reunion**: hourglasses unchanged, Bui Kichwa + Duvalia + Kipepeo; combos above 150 are legitimate here (flash several
Plaga at 149, save Bui Kichwa for the last flash; t3924).

**Records**: 1,071K Sheva Business (nicovideo sm17625175); 710k Sheva Fairy Tale (sm18754491); United 1,222k Seb
Mercenary (PS4). Duo 1,285k Sheva / Excella.

### 3.4 Ancient Ruins

**Layout** (JP map, Berserker duo): a split level. **Bottom start (S1, south)**: a corridor to a combo chest on the
left path, a tunnel with a 30 s (skip), the "first stairs" up to the south-west 90 s guarded by a scripted Duvalia
(explosive-arrow Majini) with two flashes behind it, the corridor above the stairs (the bottom stand), the wooden
walkway around the north-east corner (60 s), a 30 s below the side bridge, a 30 s behind the south wall structure;
a vase on the upper walkway always drops a green herb. **Top start (S2, north-east)**: the stairs with a 30 s mid-way,
the bridge area with a 90 s and the chicken (Reunion: east altar) and vases with herbs, the alcove outside the bridge
(30 s, often missed), the west stairs with a 90 s at the top, the west walkway path with a 30 s at its end (after 80
combo), the water spawns top-middle (most Duvalias), the right side of the bridge (nothing spawns on the chest path:
the 100-150 stand). Wetland Majini 700 HP; torch Majini (fire breathers, a scripted Cephalo camps the tunnel: headshot
it to expose the Cephalo, run past, flash it later).

**Hourglasses (10 = 8:00)**: 30 tunnel, 90 SW stairs, 60 NE walkway, 30 below the bridge side, 30 behind the south
wall, 30 mid-stairs, 90 bridge area, 30 alcove, 90 west stairs top (one of the three 90s here must be a 60 per RE5
Zone's count of 2 x 90 + 2 x 60: **(uncertain)** which), 30 west path end.

**Route (solo, assembled from the duo page; no solo write-up exists)**: bottom start, chest, 90 s (cancel the Duvalia
with a rear instant kill or a ground melee, or plant a proximity bomb on the stairs and leave), two flashes, fight the
"90-second area" corridor until ~40 when it dries, NE 60 s, then up to the bridge area: 90 s, herbs, chicken, 30 s
alcove on first leaving the bridge, 30 s mid-stairs, stay below the stairs until ~80, west 30 s, back to the bridge at
~100 for the bridge spawns and the right-side stand to 150; Giants from the ledge above the NW 90 s (10 combo, ~60,
more); about six Duvalias (water spawns); the ending is a crowd of Wetland Majini on the bridge: practice it.

**Records**: 1,338,705 Josh, max combo 158, Seb Mercenary ([N38WxyeID-Y](https://www.youtube.com/watch?v=N38WxyeID-Y));
1,064K Sheva Business (sm18727142); United 1,344,704 Sheva Fairy Tale, Seb Mercenary.

### 3.5 Experimental Facility

**Layout** (JP map, Berserker): three floors in a Tricell lab. **Top floor**: the start (S1 top-left on the JP map with
a 60 s), the elevator doors with a 30 s across the railing (vanilla chicken next to the elevator; Reunion chicken on
the lowest floor), the corridor with a 60 s and the ladder down (an enemy usually climbs it: melee it, drop). **Stairs
floor (ground)**: the alcove below the ladder, the garden side, the middle of the stairs with boxes (pickups =
dodges), the platform with a 60 s, the bottom elevator door with a 60 s. **Second / lower floor**: the long corridor
and the ramp (the late stand), the spike trap room (60 s in the trap; the trap panel kills a wave), the hopping
platforms (Licker jumps hit you mid-hop), the ladder down to the bottom area with the 90 s (saved to 130-140). Base
Majini wear armor: rifles / SMGs do nothing to the armor, magnums and explosives do; head stuns rarely work here.

**Hourglasses (8 = 6:00)**: 30 elevator (top), 60 top corridor, 60 platform, 60 bottom elevator door, 60 spike trap,
90 bottom area; plus two 30s on the JP map (bottom-left room, the lower corridor). RE5 Zone counts 4 x 60 + 4 x 30
with no 90: **(uncertain)** which of Berserker's "90 s bottom" and the count is right.

**Route (Berserker solo)**: top: 30 s, chicken, hold the combo on the top floor toward the corridor 60 s, melee the
ladder climber, drop; a fully armored scripted Duvalia Majini appears at the drop: kill it on the ground (>250 damage
while down) so it never opens; stairs floor until ~70: a Base Majini wave, then Lickers from ~40 to 72 (bullet-kill
them from the side, railings as cover); **Rocket Launcher Majini at 10 / 30 / 40 / 60 x2 / 70 x2 / 80 x2** (kill each
wave completely or the next does not spawn; bullet-kill the out-of-reach ones); transition down the corridor at ~70
(luck; a proximity bomb before leaving helps); second floor: corridor and ramp, Lickers from above, rockets from the
last pair; the 60s mid-run once Lickers make bullet-killing easy (~100+); 90 s at 130-140 by hopping down the ladder.
Only 4 scripted Duvalias. Regions: top 72, south 60, 9 at start + 3.

**Reunion**: Lickers mixed with the Base Majini from the start, a machine-gun Majini, chicken on the lowest floor;
**(uncertain)** boss: a JP wiki says none, Fandom's Gatling page says a Gatling appears here after enough points.

**Records**: 678,125 Rebecca, poyoyon46; 647K Sheva Business (sm17407108); 637,801 Sheva Fairy Tale; SS at 221k Sheva FT.

### 3.6 Missile Area

**Layout** (stv_tribute T1-T11 map, JP map, Berserker): a factory hall on two levels. **Office start (S1, top-left)**:
60 s + a flash on the control panel; two doors out; the walkway with a 30 s and the camping Majini near the 60 s
platform (shoot him or he never moves); the chicken below the left walkway (Reunion: in the 2F small room with a 30 s,
grenades and incendiaries). **Lower floor**: the right stairs, the upper conveyor belt (30 s, two explosive canisters
ahead), the ladder at its end, the walkway over the lower conveyor, the 90 s with a ladder near it, the middle
drop-off onto the lower conveyor, the 60 s at the conveyor's end, the platform and stairs to a door (kick it open: 2
flashes then the combo chest), the conveyor ladder (stay north of it until 50 to stay in the bottom region), the
storage-room walkway (another region). **Centre shaft**: its ladder up (make a kill first, strong weapon ready); the
overhead doorway (Gatling 2 spawn); the explosive canister on the table below the walkway. **Upper floor (regions A/B,
40 enemies, spawn only on the walkways)**: the storage room with a 60 s (kick the door with an enemy in view), the
office walkway (long-pipe / weaponless scripted Cephalos), the bridge; "spawn switches" (floor triggers) near the
island room make enemies drop from the ceiling above T5/T6: step on them early. **Final region C**: past the stairs in
front of the 60 s platform; the 30 s by the explosive barrel on the bridge, the 30 s in the middle area, the 60 s on
the platform, the last 60 s by the south conveyor furnace (incinerator), the 30 s by the first-aid spray (taken last).

**Hourglasses (11 = 9:00)**: 60 office, 30 walkway, 30 conveyor, 90 lower area, 60 conveyor end, 60 storage room, 30
bridge barrel, 30 middle, 60 platform, 60 furnace, 30 first-aid spray.

**Route (stv_tribute Reunion, Orochi's Barry 720k run; Berserker vanilla)**: office 60 s + flash; dynamite Majini by
the start: stop 5 m away and let him throw; conveyor and furnace TB, pass the second dynamite Majini with a flash;
combo 0-20 fast kills on the conveyor, shoot the two Molotov Majini on the walkway above; 25-30: leave one Majini
close behind, jump off the conveyor, magnum; kill any Cephalo at once; 30-40 (the hardest): the longest ladder: TB and
the landmine first, climb, shoot the Majini at the bottom, drop a mine on landing, dynamite Majini by the top TB,
check the crossbow Majini above the conveyor; 40-80: the "island" TB stepping on the spawn switches on the way, TB +
chicken in the room (the chicken escapes when a Majini opens the door and makes no noise); shoot from behind before
opening doors; 80-150: keep re-stepping the switches; **Gatling 2 at ~80** (Reunion; vanilla Gatlings at 20 yellow,
60 yellow from the shaft doorway, 90 red from the office ceiling walking down the office walkway); the red Gatling is
the stop point; the sabotage Majini by the stairs must be approached; the TB by the spray last (the 149th may not have
spawned). Vanilla rule: once up top you must stay for 46 kills (climb at 50 = drop at 96); stop the combo and take the
furnace 60 s before 145 (a dynamite blast can end the run after that). Barry: Gatling = 2 magnum leg shots + melee
(red 3); Cephalo: magnum anywhere but the legs.

**Records**: 733,303 Rebecca, poyoyon46 ([8C5N_tu-qtI](https://www.youtube.com/watch?v=8C5N_tu-qtI)); 720k Barry,
Orochi (sm9769008, the route above).

### 3.7 Ship Deck

**Layout** (JP map, Berserker, Fandom): a tanker's cargo deck, long axis north-south. **South start (S1, bottom)** by
two flash grenades; the first stairs (30 s on the way down); the north crate ladder, the far side drop, the second
ladder to the 60 s above the crate tunnel; the crates to the west with the grenade launcher (Reunion: explosive
rounds, moved near the zipline, flash rounds beside it; nitrogen rounds on the north tower top); the 90 s west of the
stairs; the central ladder to the lower north tower, the middle ladder to the top (30 s + a rocket launcher; Reunion
moved one of the two east rockets to the west high ground); the far-north ladder (60 s + chest + chicken; Reunion
chicken on the high ground by the rocket near S1, wandering to the plaza); the left stairs (30 s) at ~40; the south
ladder to the middle crate corridor (the main stand to ~85, 60 s there); the west side and the tunnel; the crane
tower (60 s below it, 30 s by the explosive barrel behind the gate, 60 s at the crane top, four bowgun campers on top
late); the hopping crates; the zipline to the rocket launchers. Regions: A 52 SW, B 40 SE, C 40 N; the south gap
between A and B spawns nothing.

**Hourglasses (11 = 9:30)**: 30 first stairs, 60 above the crate tunnel, 60 (+60?) by the GL crates (west), 90 west
of the stairs, 30 tower top, 60 far-north ladder, 30 left stairs, 60 middle corridor, 60 below the crane / across the
hopping crates, 30 gate barrel, 60 crane top (Berserker's "the 60 s bonuses there" at the crates may be one or two:
**(uncertain)**).

**Route (Berserker solo)**: flashes, 30 s down the stairs, melee the area below; **blue Chainsaw 1 at the start**
drops from the crane tower: knock him down with the strongest weapon; crate ladder, drop, second ladder, 60 s; GL
optional; 90 s; tower ladders, 30 s + rocket; drop north, far-north ladder, 60 s, chest, chicken (flash if it runs);
~40: left stairs 30 s; south ladder to the middle path (spawns start when entering the corridor from the north); hold
the middle crate corridor with its 60 s until ~85; west, keeping an enemy in view, fight before the tunnel; ~140: 60 s
below the crane, kick the gate, 30 s by the barrel, up to the crane, 60 s on top, melee the four bowguns to end; if the
run does not end a Majini sits on the north tower top (snipe, or a rocket from the zipline). Chainsaw waves (vanilla):
blue at start; blue 2 + red 1 at 20 (middle crane); red 2 at 30 (crate tower); red 3 at 40 (crane tower); red 4 + blue 3
at 50 (overhead crane; a magnum pierces both if they line up in the corridor, stand with your back to the north end).
Reunion waves (Fandom): red, red, 2 red, then 2 blue + a Gatling; red and blue never together; after the last wave no
more. Scripted Cephalos: red wrench, long pipe, green bottle, dynamite, bowgun, spiked club (legs + rear melee, a strong
weapon, or flash). Four Majini (3 bowgun, 1 dynamite) try to climb the north tower before 40 kills: shoot them before
they reach the top.

**Records**: 1,043,176 Rebecca, poyoyon46 ([S5WpX0-o93U](https://www.youtube.com/watch?v=S5WpX0-o93U)); 1,031K Excella
(sm18947349); 851k Barry (sm9832596); 700k Excella, Seb Mercenary (PC).

### 3.8 Prison

**Layout** (JP map, Berserker duo, GameFAQs route): a tall, narrow prison on several floors with lava below. **Top
(S1, the catwalk)**: a 60 s beside the start, the catwalk, the stairway corridor door (an aggressive Majini behind
it), the rail tracks (60 s; drop off its left side), the hand grenade by the tracks (blows the wooden door below),
the window hop into the hall (60 s at its end), the doorway across the hall and a 30 s, the gap hop to the chicken
house roof (60 s, flash in the crate), the chicken pen (combo chest, chicken, NE behind the fence). **Cells (1F)**: the
central room ("1F central room": the front corridor is the solo stand, enemies arrive one at a time; the outer 1F
corridor is easier but multi-directional), the first cell on the left (combo chest), the wooden door across it (30 s
inside), the south end of the corridor (30 s at the window, saved for the dynamite phase). **South start (S2, the
flash counter)**: a ladder to the window, the right corridor's wooden door, the iron door (cocktail camper), the left
corridors (two 30s, breakable walls), the far-right room, the broken wall drop to the wooden walkway (30 s on the
ledge), the basement ramp (**Red Executioner 1 starts here**), the 90 s ("mega-time bonus") in the lava pit area, the
first basement cell (two flashes), the cliffside with the gas tank on the wall (the duo combo keeper's stand), the
ledge spawn above it. Dotted walls on the JP map are breakable. One spawn region for the whole stage (134 + 5
Executioners + 11 at start).

**Hourglasses (12 = 8:30)**: 60 catwalk, 60 tracks, 60 hall, 30 doorway, 60 chicken house, 30 cell, 30 south window,
30 + 30 left corridors, 30 ledge, 90 lava pit, 30 cliffside (RE5 Zone counts 5 x 60 + 7 x 30 with no 90; the GameFAQs
route calls the lava-pit one "the mega-time bonus": **(uncertain)** 60 or 90).

**Route (GameFAQs 49684739 + Berserker)**: from the chest spawn drop into the prison, the two timers (one in the
window, one behind the door), deal with Red Executioner 1 there, the chicken-house roof timer, inside for the chest
and the chicken, the plank timer, the basement 90 s in the lava pit, the two adjacent cells (timer + chest), loop the
corridors and return to the Executioner spot before the second red one; "30 s left is the absolute minimum before you
leave for the next timer". Executioners (vanilla): red at start; black 2 at 20 (ledge above the cliffside); red 3 at 50
(ceiling spawn at the end of the cell corridor); black 4 at 90 (above the stairs, through the side window or from the
chicken area); red 5 at 120 (ceiling spawn), the hardest, with Town and Big Man Majini. Eight scripted Cephalo machete
Majini fall from the corridor's ceiling spawn (leg stun + rear instant kill). ~140: dynamite Majini (one scripted
Cephalo among them); 138-150 is the dangerous window: heal before it. Reunion: Duvalia added, hourglasses partly
changed, one Executioner at a time, red and black alternating.

**Records**: 929,701 Sheva Fairy Tale, keck ([erY7PDg_Du4](https://www.youtube.com/watch?v=erY7PDg_Du4)); 924,555
Rebecca, poyoyon46; 894k Barry (sm9920018, "headbutt rampage"); SS at 387k Rebecca; United 949k Wesker STARS, Seb
Mercenary. Duo 1,048,457.

---

## 4. Maps, exploits and tricks (RE5)

### 4.1 Community maps downloaded (Spark, `~/gBox_alt/scratch/mercs-meta/maps/`, not in the repo)

| file | what | source |
|---|---|---|
| `re5_reunion_<stage>_kouryakutsushin.gif` (8 stages) | Reunion stage maps with the hourglasses as numbered circles (30/60/90), start points S1/S2, combo chests (blue stars), the chicken (red dot), herbs, grenades / flashes / incendiaries, explosive barrels, ladders; dotted walls = breakable (Prison) | kouryakutsushin.com/bio5/re-*.htm |
| `re5_public_assembly_route_stv_tribute.gif` | PA route map: T1-T8 hourglass numbering, routes 0-9, the fence (red) to grenade over | stv-tribute.hatenadiary.org 2009-11-15 |
| `re5_missile_area_map_stv_tribute.gif` | Missile Area: T1-T11, spawn switches (red circles), the four fight zones (green / orange / red / blue), dash arrows | stv-tribute 2009-12-07 |
| `re5_fandom_public_assembly_map_2.jpg` | the official guide's PA map (p.178) with the legend icons (time bonus, combo bonus, chicken, grenade, herbs) | Fandom (static.wikia.nocookie.net) |
| `re5_fandom_village_map.jpeg`, `re5_fandom_ship_deck_map.jpg`, `re5_fandom_prison_map.jpeg`, `re5_fandom_experimental_facility_17.jpg`, `re5_fandom_mines_danskyl7_1.jpg` | Fandom's stage images (Village is a large annotated map; Prison and Ship Deck are small) | Fandom |
| `re5_fandom_public_assembly_*.jpg` (area_1-6, time_bonus, combo_bonus, chicken, trap) | the legend icons only (tiny) | Fandom |

Not retrievable: Berserker's imageshack time-bonus and spawn-region maps (imageshack purged them; the links are in
his [Info Database](http://berserkersblog.blogspot.com/2011/10/resident-evil-5-mercenariesmercenaries.html)); their
content survives as text in his stage pages (section 3) and in BerserkerSTARS' "Time Bonus Locations" videos
(PA yMnaSidWVvc, Mines m5lYcO4ZObw, Village RZ-MdEoIS-k, Ruins q-iSkGG6mSE, Exp. Facility eoVeTwshwOI, Missile
wxGoiODryjE, Ship Deck zzkM2NpPBNw, Prison F2wccF-uyrE on YouTube). GameFAQs has sephirosuy's stage maps (e.g.
`/ps3/929198-resident-evil-5/map/6119-mercenaries-prison-map`) behind its bot wall.

Matching to the navmesh: the bot already has every hourglass's world position (uOm0100 units) and the AI navmesh
(`re5_nav.py`), so the maps serve to name things: order the RAM hourglasses by the route in section 3, label the stand
polygons (PA: the bus side, the alley by the transformer, the waterway strip), and mark the region boundaries
(Berserker's counts) once a round's spawn positions have been logged against the player's position.

### 4.2 Exploits and tricks catalogue (what top Reunion players do)

Melee and time
1. **Stun -> finisher chains**: leg (thigh) shots until the kneel, then the prompt; +5 s, i-frames, no ammo. Rear leg
   stun = instant kill for Chris / Sheva / Josh / Excella (and cancels any Plaga). Head stun = kill for Rebecca (Flame
   Spray), near-kill for Excella (High Heel after the M93R burst) and Barry (75 % crit Headbutt).
2. **Stun rod** (Heavy Metal Chris): a kill with it is a melee kill (+5 s), x5 damage to Plaga, cancels a mutation.
3. **Lag shot**: shoot just before the melee lands (section 2.4).
4. **Melee during a reload** cancels the reload and still reloads; **menu reload** during any animation.
5. **The pickup dodge**: picking up an item (boxes, herbs) is an animation with i-frames.
6. **Flash grenade -> group flame-spray / melee**: flash a pack, then melee each (Rebecca, Excella's 12 rounds).

Combo
7. **Open the combo chest after the first kill** of a chain (worth +980 ... +500 per kill for the first 20 kills, zero
   after 50).
8. **Never trade the combo for a melee**; when W is short, shoot.
9. **Two alive before each kill past 140**; the last spawn can be across the map.
10. **Village / Ruins past 150**: hosts and their Plaga both count; flash several at 149 (Seb Mercenary's Ruins combo
    158).
11. **Gun the last enemy** (a melee's animation can outlast the clock / the window).

Bosses
12. Hold bosses to 120-150 (flat per-10 brackets); PA #1 at 140, #2 as it enters, #3 at 150.
13. Executioner: PA bus is a safe room; shoot the swelling corpse to defuse it; magnum chest-then-legs then melee;
    the red one's back Plaga staggers him on any hit; a flash stuns him.
14. Gatling: 2 magnum leg shots + melee (red 3); fight where he has to climb down.
15. Chainsaw blue: the first "death" is not a kill; leg stun; flash the berserker.

Spawns and aggro
16. 12 in play: kill the chicken and wake the campers early so they stop holding slots.
17. Move every ~20 kills on PA; stand at region seams (Mines tunnel south end, Village north bridge) so two regions
    feed you; avoid dead zones (PA back alley, Ship Deck south gap).
18. Missile Area: step on the spawn switches before clearing the area; shoot the camper by the 60 s platform.
19. Last enemy hiding: listen (voice), grenade over the fence (PA), rocket the north tower (Ship Deck).
20. Dropping a weapon changes the drop table toward the ammo you keep.

Inputs
21. **Quick turn**: left stick down + the action button (cross on PS3 Type A, the same button that runs); the right
    stick while the weapon is ready turns 20-30 degrees. **(uncertain)** the exact Type-A chord: verify live.
22. **Weapon switch while holding fire** on the D-pad skips the raise animation (rifle / rocket ~half the time to
    fire); Josh's rocket fires before the scope opens; aim first, then D-pad.

### 4.3 Reunion vs vanilla, the differences that change the plan

| | vanilla Mercenaries | Reunion |
|---|---|---|
| leftover second | 1,000 | 300 |
| combo table past 50 | flat 1,000 / 7,000 | rises to 50,000 / 100,000 at 150 |
| bosses | by kill count (section 3), several per stage | one at a time, time-triggered, more after each kill |
| Plaga | random Cephalos; scripted ones | none in the first wave, mutations after ~50; Duvalia on 6 stages, Town Majini can become Duvalia |
| extra enemies | - | Big Man packs (PA, Mines), Bui Kichwa (PA, Village), Adjule (Mines), Kipepeo (Ruins), Lickers from the start (Exp. Facility) |
| hourglasses | - | same positions on Village and Ship Deck; partly moved elsewhere; chickens moved (PA waterway bend, Mines plaza, Exp. Facility lowest floor, Missile 2F room, Ship Deck high ground, Ruins east altar) |
| priority | time first, then combo | combo first ("takes priority over everything", Berserker), time second |
| melee values | Straight 400, Uppercut 400 ... | Straight 500, Uppercut 500, Roundhouse 600, Somersault 600 |
| difficulty | fixed solo / duo rank | Player Rank changes during the round |

---

## 5. Hacks the community uses, and what to map in RAM (for the mods agent)

No code here; names and effects, with where the structure is known. RE5 is MT Framework; the PS3 RAM map
(`profiles/gamedata/BLUS30491-ram.json`) already has the Mercenaries state as **cGameSys through sBioMain +0x182D4**:
`+0x3E0` f32 clock, `+0x3E4` clock at start, `+0x3F4` s32 kills, `+0x3FC` s32 combo, `+0x404` f32 combo window left,
`+0x418` s32 score (`re5_ps3.py` GS_* constants), plus sPlayer (position, rotation, action, aim pitch, hp), sEnemy,
sActionButton (prompts), sUnit (hourglasses), sAI (navmesh). The PC cheat tables' features map onto those and onto
structures not yet located:

| hack (PC tables / trainers) | what it does | PS3 structure to map | source |
|---|---|---|---|
| Mercenary Timer / Freeze Timer | sets or freezes the Mercenaries clock (works in Reunion and No Mercy) | cGameSys +0x3E0 (known) | [Steamworks table](https://residentevilmodding.boards.net/thread/4273/resource-resident-steamworks-cheat-table), FLiNG +16 (Ctrl+Num1), Nexus trainer F11 |
| Freeze Combo Timer / Infinite Combo | holds the 10 s window (counter "still flickers"); "150 combo becomes easy" | cGameSys +0x404 (known) | Steamworks table; REMADE v1.0.7.3 table ("infinite combo", unstable, crashes mid-match) |
| Infinite Combo Bonus | keeps a combo chest's 30 s running (collect a chest first) | the chest timer: not located (near +0x404?) | REMADE table |
| Mercenary Score / Infinite Score / Max Combo | writes the score / combo | +0x418 / +0x3FC (known) | Steamworks, FLiNG (Ctrl+Num2 / Num3) |
| Infinite Clip / Infinite Ammo / No Reload | clip never drops; reload does not consume reserve; no reload animation | the player's weapon unit (uWeapon / cItem: clip count, reserve count, reload state) - not located on PS3 | Steamworks, FLiNG (Num4 / Num5) |
| Infinite Grenades / Eggs | items not consumed | inventory item counts (cInventory) - not located | Steamworks |
| No Recoil / No Spread / No Sway / Rapid Fire / No Overheat | weapon parameter edits (reticle growth, recoil kick, fire interval, Gatling heat) | the weapon parameter table (per-weapon stats: firepower, capacity, reload, critical, piercing, range) - static data in the weapon arc, patched in memory by the trainers; not located | Nexus "Trainer (Menu)" option list (via search), Gamepressure +16 |
| One Hit Kill | enemy HP or damage multiplier | sEnemy entries' hp (known per enemy) | FLiNG (Num0) |
| Infinite Health / Partner Health / Invincibility | player hp frozen ("instant kill attacks still kill", does not leave Dying) | sPlayer hp (known; gBox never writes it) | all tables |
| Super Speed / Teleport / Save location | position writes | sPlayer position (known; never written by gBox) | FLiNG |
| Points / Exchange Points / Unlock All Bonuses | save or global counters | the save (DATA0.DAT offsets in docs/mercenaries.md) | FLiNG, Apollo save patches |

Notes for mapping: the tables moved to AOB scans in 2015 because the executable changed per patch ("AoBScan only cares
about the AoB"); the PS3 BLUS30491 01.01 build is one fixed image, so the same routines can be found by the MT
Framework class names (`getDTI` slot 5) the RAM map already uses. The weapon stats on PC live in per-weapon data
files that modders edit (wp##.arc), so an in-memory copy exists after load; find it by searching for a known tuple
(Gatling firepower 350, M92F 250 / 50 cap) near the uWeapon units. RPCS3's own patch database has only an FPS unlock
for this id. gBox's rule stands: hacks are values in the game's own tables, never writes to the player.

Trainers found (option lists only): FLiNG +16 (Gold v1.0: health, partner health, money, exchange points, unlock all
bonuses, one hit kill, super speed, infinite ammo, no reload, grenades, no overheat, teleport, freeze Mercenaries
timer, infinite score, max combo; [gamepressure](https://www.gamepressure.com/download/resident-evil-5-gold-edition-v10-v11-16-trainer/zfe190),
[vgtimes](https://vgtimes.com/games/resident-evil-5/files/2824-trainer-16-1.0-fling.html)); Nexus "Resident Evil 5
Gold Edition Trainer (Menu)" (No Recoil, No Spread, No Sway, Rapid Fire, No Overheating, Freeze Mercenary Timer;
[nexus 1077](https://www.nexusmods.com/residentevil5goldedition/mods/1077)); FearLess tables t=1954 / t=30482 (health,
ammo, grenades, money, freeze timer; CE 7.0+); the Steamworks and REMADE tables above.

---

## 6. Bot rules beyond the S-rank checklist (high-score mode)

Once section 1.5 holds an S every round, the next tier is the combo. Ordered, as additions to 1.5:

| # | phase | condition | action |
|---|---|---|---|
| H1 | plan | stage known | load the stage record: hourglass order, stands by phase, region seams, boss list, the chest positions |
| H2 | gather | at the first kill of the round | open the nearest combo chest within 10 m right after it (bonus from combo 2); never after combo 50 |
| H3 | fight | C >= 10 | prefer the stand at a region seam; move every 20 kills on PA |
| H4 | fight | an Executioner / boss alive and C < 120 | do not kill him: keep 8+ m, stun and walk away; use the bus (PA) if he closes |
| H5 | fight | boss alive and C >= 120 (or K >= 140 on PA) | kill him now (magnum / grenades / Gatling head); #2 as it enters, #3 at 150 |
| H6 | fight | W < 3 s and a boss is the only target in reach | shoot the boss (its death keeps the chain) |
| H7 | fight | a Plaga type emerges and a flash is held | flash it (instant kill, keeps the chain) |
| H8 | fight | K between 50 and 150 and a Majini is stunned by a head shot | prefer the melee over a second head shot (random Cephalo) |
| H9 | finish | K = 149 on Village / Ruins and Plaga are up | flash them for 151+ |
| H10 | finish | last enemy not visible for 10 s | go to the stage's known hiding spots (PA fence, Ship Deck north tower), grenade / rocket |
| H11 | learn | every boss spawn, every hourglass taken, every chain end | log (clock, kills, combo, position) to the lessons file; derive the Reunion boss timers and the real region seams from the logs |

Stage DB fields this needs (`profiles/gamedata/mercs/<map id>/<stage>.json`): `bonuses` (the 9 PA hourglasses with
their value once each is taken and the clock jump measured), `chests`, `stands` (by phase, polygons on the navmesh),
`seams`, `bosses` (type, trigger: kills or seconds, spawn point), `hides`, `campers`.

---

## 7. Resident Evil 4 (2005) Mercenaries: GameCube / PS2 / Wii (title #1, `G4BE08`)

Shorter: scoring, items, best stages, records, hacks. In-house facts (docs/mercenaries.md) win where they overlap.

**Scoring** ([Fandom RE4 Mercenaries](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE4)),
[Steam complete guide](https://steamcommunity.com/sharedfiles/filedetails/?id=234937519),
[TAS 6501S](https://tasvideos.org/6501S)): Ganado / Zealot / Soldier 300; Bella sister 5,000; Garrador 7,000; J.J.
(Gatling Man) 10,000; Super Salvador 5,000. Combo bonus per kill: 2nd 20, 3rd 50, 4th 100, 5th 200, 6th 250, 7th 300,
8th 350, 9th 400, **10th and every later kill 700**; specials 500 at the 2nd, +500 per position, capped 4,500 from the
10th. So a Ganado at 10+ combo = 1,000, a Bella 9,500, a Garrador 11,500, J.J. 14,500. **Combo window 10 s** (in-house:
300 frames in the add-kill routine; Fandom's "11 s" is the display). **Bonus-time chest**: 30 s (TAS measures 31) of
1,000 per regular kill, applies to the first kill too, bosses keep the table (Fandom, [Castle TAS](https://tasvideos.org/Forum/Topics/25749?CurrentPage=1&Highlight=532436#532436)).
Castle formula (Ubercapitalist): score = 30,200 + 1,000 x kills + 300 x chest kills. **Kill caps**: Village 124, Castle
348, Base 101 (NTSC GC) / 117 elsewhere, Waterworld 156; at most 10 Ganados in play (bosses can exceed)
([GameFAQs](https://gamefaqs.gamespot.com/boards/925156-resident-evil-4/53365945), TASVideos). **Ranks (stars)**: 1
<10,000; 2 at 10,000; 3 at 20,000; 4 at 30,000; **5 at 60,000** ([GameFAQs](https://gamefaqs.gamespot.com/boards/369498-resident-evil-4/80404818)).
4 stars unlock Ada (Village), Krauser (Castle), HUNK (Base), Wesker (Waterworld).

**5 stars every round (60,000)**: 60 Ganados at 10+ combo = 60,000 by themselves, or one Bella pair in combo + 40
Ganados. Every melee is free of time (RE4 gives no +5 s), so time comes only from the hourglasses: Village 5:30
(+90, +90, +90, +30, +30; in-house), Castle 6:50, Base 6:00 (12 x 30), Waterworld 7:30 (Fandom). Start 2:00; the
item menu, pickups and cutscenes do not run the clock (TAS). Combo chests: Village 3, Castle 3 (alcove with pillar 3,
tower 3rd floor, room past two iron doors), Base 3 (top platform, tunnel-ladder chest by a breakable box, after the
zipline), Waterworld 3.

**Stands and bosses**: Village: the big house's roof / the barn; Bella sisters come in pairs (6 total; leaving a pair
alive spawns two more); kill them only inside a 10+ combo (9,500 each). Castle: upstairs away from the Garradors
(first after 25 kills, two normal + one armored, one rifle / magnum shot to the back Plaga while it is stuck in a
wall after a charge). Base: 5 per zone, no respawn, a zone spawns when <= 10 exist (TAS watched 0x81283606); J.J.: 4
rifle shots or 2 magnum, grenade when he reels. Waterworld: two Super Salvadors from fixed triggers (house past the
start, second house far side), they do not climb ladders; the "spawn glitch": leave a zone with exactly one Ganado
left and five spawn on return (needed in every zone for 156).

**Characters**: Wesker is the TAS pick on all four maps (fastest, Killer7, flash kills Plagas); HUNK's neckbreaker (head
stun) always kills, Bellas included; Ada / Wesker top community tiers, Leon bottom. Melees: head stun -> Leon
roundhouse / Ada senpukyaku / Krauser double kick / HUNK neckbreaker / Wesker thrust punch; leg stun -> Leon side kick
(Village) or suplex / Ada kaitenkyaku / Krauser knee / HUNK kick / Wesker chikyo chagi.

**Records (real-time)**: Village 207,700 98krauser (Wii), 207,400 Derek Taylor (PS3) and PeachyMike (HUNK, Wii),
TAS 210,400; Castle 369,370 Math (Steam 2022), 366,070 Derek Taylor (GC 2010), TAS 415,100 (ceiling 483,000); Base
168,500 Head Minerve (2009), TAS 170,900; Waterworld 205,400 dxm8975 (PS4), TAS 210,200 (sources:
[6501S](https://tasvideos.org/6501S), [9338S](https://tasvideos.org/Forum/Topics/25749), [9639S](https://tasvideos.org/9639S),
[6832S](https://tasvideos.org/6832S), [Cyberscore](https://cyberscore.me.uk/game/185)). Village TAS route: Wesker,
incendiary opens each chest, ~40 kills per 31 s chest with silenced-handgun crits and hand grenades on groups,
Killer7 / sniper on Bellas, three roof Ganados lured off the big house before chest 1, max combo only 46 (waiting for
spawns beats chaining).

**Hacks** (GC): Gecko "Infinite Combo Time (Mercenaries Mode)" (Jay007: NOP of the combo-timer store, the same site
gBox's `combo_time` patches), Dr.Pepper's score / time modifiers and unlimited ammo, ~Kasumi~'s "Kill 1 enemy for
9,999,999 points", Action Replay "Freeze Timer", "Unlimited Combo Time", "Mercenaries Have Perfect Stats", "Enemy
Size Modifier" ([gamehacking 54170](https://gamehacking.org/game/54170), [Almar's](https://almarsguides.com/retro/walkthroughs/gamecube/games/ResidentEvil4/actionreplay/us/)).
Known RAM from TAS: Base on-screen enemy count 0x81283606; headshot crit base ~50 %.

**2023 remake, one paragraph**: ranks B 50k / A 100k / S 200k / S+ 500k / S++ 1,000,000; a combo multiplier up to
x1.5 (100-150), a 15 s window, 1,000 per leftover second, Gold Chicken Egg 50,000, Mayhem mode, a fourth map (Docks),
WRs around 2.3-2.75 M ([Gamerant](https://gamerant.com/resident-evil-4-remake-re4-mercenaries-highest-score-guide/)).

## 8. Resident Evil 6 Mercenaries (X360 `0871eee3b68cdea3`, Xenia)

**Scoring** ([GameFAQs "numbers ver.2"](https://gamefaqs.gamespot.com/boards/605603-resident-evil-6/64262414),
[kouryakutsushin RE6](http://kouryakutsushin.com/bio6-wiki/)): ~300 per regular zombie / J'avo; combo bonus per
kill (normal / boss): 2: 40 / 750; 3: 100 / 1,500; 4: 200 / 2,250; 5: 400 / 3,000; 6-9: 500-800 / 3,750-6,000;
10-19: 1,000 / 6,750; 20-29: 1,200 / 7,500; 30-39: 1,400 / 8,250; 40-49: 1,700 / 9,000; 50-59: 2,000 / 10,500;
60-69: 2,400 / 12,000; 70-79: 2,800 / 15,000; 80-89: 3,400 / 18,000; 90-99: 4,000 / 22,500; 100-109: 6,000 / 30,000;
110-119: 8,000 / 45,000; 120-129: 12,000 / 60,000; 130-139: 20,000 / 75,000; 140-149: 30,000 / 90,000; **150: 60,000 /
150,000**; paid per kill; a boss's bonus replaces the normal one. **Window 15 s** (17 s under 0:30 with Go for Broke).
**Cap 150**; clearing pays 200 per leftover second. **Ranks**: solo E <40k, D 40k, C 60k, B 80k, A 100k, **S
140,000**; duo S 220,000 ([Neoseeker](https://www.neoseeker.com/forums/56257/t1819522-mercenaries-general-discussion-thread/)).
A 60-70 combo is about an A; a 150 combo about 1.1 M; a hidden boss as kill 150 about 1.3 M+.

**S every round (140,000)**: 150 kills with chains of 20+ (a 20-chain = 2,170 + 10 x 1,200 ... the 10-19 bracket pays
1,000 a kill), or any single 60+ combo; counters (+10 s) and coups de grace (+7 s) are the clock (melee +5 s).

**Time**: start 2:00; yellow hourglasses +30/+60/+90, only breakable by melee, slide or explosions; green crystals
(shot) start 30 s of >= 1,000 per combo kill. Per stage (time / combo): Urban Chaos 6/3, Steel Beast 7/3, Mining the
Depths 5/2, Rail Yard 6/3, High Seas Fortress 11/3, Requiem for War 8/3, Liquid Fire 6/3, Catacombs 6/2, Creature
Workshop 8/2 (Fandom stage pages). Route meta: all time pickups, herbs and sprays before the first kill (except Liquid
Fire, Steel Beast, Mining the Depths where timers sit on the combo path); don't pop green crystals early (Urban Chaos:
~40 for the firemen, ~85 for the Bloodshot packs); the JP wiki uses them at combos 2-9 ([residentevil.org tips](https://residentevil.org/threads/mercenaries-tips-thread.5305/)).

**Stage scripts and hidden bosses** (counters before kill 80): Urban Chaos: MG police at combo 10-20 (red-herb corner),
dogs 20-35, firemen, armoured zombies ~48 (overpass top, barrel / C4), Whopper at 50 and two at ~105, Bloodshots
70-150, magnum police 100-130; hidden Napad after 15 counters. Steel Beast (hardest): 0-20 second floor middle, ~25
para-zombies top, ~50 armoured Napads from the bottom (count as bosses after 50), base floor safe to ~120; hidden
Gnezdo 25 CDG. Mining the Depths: Strelac at 70 kills within 10:00; Shriekers die to one sniper headshot. Rail Yard:
Ubistvo 25 quick-shot kills. High Seas Fortress: Gnezdo 40 melee kills. Requiem for War: Gnezdo 70 kills in 10:00.
Liquid Fire: Napad 25 CDG. Catacombs: Strelac 20 quick-shots ("easiest 150"). Creature Workshop: Ubistvo 40 melee
kills. Kill the hidden boss as kill 150 (+150,000).

**Mechanics**: counters cost no stamina and can be pre-empted by tapping fire as the arm starts its swing; coup de
grace = frontal heavy-stun finisher (arm / leg stun + slide, two light stuns, a flash on Bloodshots); back heavy-stun
melee is an instant kill; every physical attack drains stamina, the taunt refills it; "grenade / CDG trick": flash,
throw a grenade, start the finisher ~2 s later (invulnerable) so the blast clears the crowd while the +7 s lands
([jagaimo blog](https://www.jagaimogameblog.com/entry/2017/01/09/025211)). No Mercy (PC / PS4 / XB1 / Switch, not the
X360 disc): 300-cap, 40 at once, ~2.4-2.6 M duo runs.

**Characters**: Jake default (Martial Arts Master) leads leaderboards, Sherry costume 1 and Chris default close; Ada /
Helena with Target Master one-shot rifle quick-shots; Carla with Power Counter; skills Limit Breaker (+50 / kill past
50), Time Bonus+ (+10 s per hourglass), Combo Bonus+ (+10 s combo time). gBox's `re6` tool already gives any loadout.

**Records (solo, 150 combo, video titles)**: Urban Chaos 1,347,208 Carla, 1,338,001 Jake, 1,334,904 Sherry; Steel
Beast 1,309,841 Carla (X360); Mining the Depths 1,383,706 Chris (PC, "WR since 2013"); Rail Yard 1,188K Chris EX1;
Requiem 1,189K Chris EX1; Catacombs 1,281,599 Carla; Creature Workshop 1,293,701 Agent; High Seas 1,146,605 Chris;
Rooftop (DLC) 1,458K Carla ([residentevil.org scores](https://residentevil.org/threads/highest-score-in-mercs.6518/)
and the YouTube titles listed there). Best-documented route: Urban Chaos, all 6 hourglasses + sprays first, 15
counters before kill 80, the overpass / arcade stand through the Bloodshots, crystals at ~40 and ~85, Whoppers late in
a 10+ bracket, the Napad as kill 150.

**Hacks**: FearLess tables (Steve Andrew / l0wb1t: health, one hit kill, ammo / no reload, herbs, skill points, auto
button mash, no recoil, fly / teleport, zombie vacuum, **Freeze Mercenaries Mode Timer**; RELOADED +5: **Infinite
Combo Gauge**); X360: no public struct docs; RE6SE save editor (S on all stages), XPG +9 / 360haven +16 trainers (JTAG /
RGH). RE.NET flags manipulated scores. gBox's X360 RAM work (docs/re6.md) is the only open map.

## 9. Resident Evil: The Mercenaries 3D (3DS `0ed22ae742e1b56b`, Citra)

**Scoring** ([Sephirosuy's data](http://sephirosuy.blogspot.com/2011/07/rem3d-enemy-creature-stats.html)): Villager
Majini 300, Army / Zealot 400, Big Man 1,000, Cephalo 800, Duvalia 900, Bui Kichwa 400, chicken 2,000, Executioner
black 5,000 / red 15,000, Chainsaw 7,000, Gatling 10,000 (full damage only from grenade launchers), Garrador 10,000
(Plaga 100 %, body 10 %), Dr. Salvador 15,000, Popokarimu 35,000. Combo chests: 30 s of +1,000 per combo kill. The
per-kill combo table, the combo window and the rank formula are **not published** (community: most missions need
>100,000 for S / SS, 4-5 about 150-200k; factors: kills, max combo, time left, maybe accuracy); ranks SS / S / A / B /
C / D; no in-game leaderboard. Time crystals 30 / 60 / 90 / 120 s broken by melee; melee kills +5 s; skills modify
the window (Toughness Lv3 +0.5 s per kill, Adrenaline +2 s when hit, Close Range +2-3 s, Extension +3 s when low,
Lucky 7 +1-3 s when a 7 is on the clock).

**Missions**: 30 (21 + EX); 1-1 2:30 tutorial; 4-1..4-4 and 5-1..5-4 2:00 survivals; 4-5 ten waves (~180 enemies);
EX-9 fifteen waves; kill-count missions in chapters 1-3; 3-5 / 5-5 Popokarimu. Stages are RE4 / RE5 maps (Public
Assembly again, day and night).

**Characters and skills**: instant kills HUNK The End (front leg) / Executioner (back leg), Krauser Stinger / Throat
Slit, Chris Neckbreaker (back leg), Jill Head Grab; Wesker Cobra Strike 1,200, Barry Miranda Rights 5,000 (downed),
Rebecca Stun Gun 8,000. Meta: Krauser (Stinger, lowest damage taken) and Wesker (dash, crits); Barry's or Rebecca's
loadout on EX; three skills equipped from 30.

**Records** ([Cyberscore 977](https://cyberscore.me.uk/games/977)): EX-9 1,576,029; 4-5 1,482,914; 4-1 598,541; duo
EX-9 1,683,795. No route write-ups found.

**Cheats**: CTRPF / NTR (USA 0004000000035900): Freeze Timer, Set Timer 0, x99 enemies routed, Max Score 9,999,999,
unlock all missions / characters / weapons ([GitHub archive](https://github.com/JourneyOver/CTRPF-AR-CHEAT-CODES/blob/master/Cheats/Resident%20Evil%20-%20The%20Mercenaries%203D%20(USA)/0004000000035900.txt));
Action Replay: skill points, points, infinite ammo ([gamehacking 115456](https://gamehacking.org/game/115456)). The
Citra core in gBox exposes no memory map (docs/mercenaries.md), so live reads need Azahar's RPC or a different core.

Open gaps to resolve from RAM: RE4 Castle / Waterworld per-pillar values; RE6 boss base points and per-stage hourglass
values; Mercs 3D combo table, window and rank thresholds.

---

## 10. Open-source aimbot / navigation systems usable with an emulator (survey)

Headline: **no open-source RE4/5/6 Mercenaries bot, trainer or aim-assist exists on GitHub**; everything usable is
generic infrastructure or design reference. Licence IDs from the GitHub API where available; "last push" as of
2026-10-21.

| project | licence | what it adds to gBox | fit |
|---|---|---|---|
| [recastnavigation](https://github.com/recastnavigation/recastnavigation) (Detour, DetourCrowd) | Zlib | `findStraightPath` (funnel / string-pulling) over the RE5 navmesh corridor so routes hug corners instead of edge midpoints; `moveAlongSurface` for wall-sliding without re-planning; `raycast` as a cheap line-of-walk test; DetourCrowd obstacle avoidance + separation to steer around Majini whose positions and velocities come from RAM | **1st**: no maintained Python binding (wow-navmesh is Windows / WoW-only; recast-rs, detour-sys, waymark are Rust) - a ~300-line nanobind shim, plus converting the game's navmesh triangles into a dtNavMesh tile |
| [ioquake3 `ai_dmq3.c` BotAimAtEnemy](https://raw.githubusercontent.com/ioquake/ioq3/main/code/game/ai_dmq3.c) | GPL-2.0 | a complete humanised aim model: reaction delay by skill, 0.5 s target resample, reversal penalty, linear lead, jitter and angular spread scaled by (1 - accuracy), distance factor | **2nd**, design only: reimplement the formulas, do not copy (GPL) |
| [AssaultCube bot](https://github.com/assaultcube/AC/tree/master/source/src/bot) | "zlib-like" per README, no header in the bot files (**uncertain**) | skill-tier aim offsets scaled by distance, target scoring (visible, FOV, nearest), first-shot delay, waypoint navigation | 3rd; confirm the licence before copying |
| [RVO2](https://github.com/snape/RVO2) / [Python-RVO2](https://github.com/sybrenstuvel/Python-RVO2) | Apache-2.0 | ORCA local avoidance: each RAM enemy as an agent with velocity, ask for the player's collision-free velocity each tick (the "don't get grabbed" layer) | 4th; Python-RVO2 last pushed 2024, old Pythons |
| [py-dolphin-memory-engine](https://github.com/randovania/py-dolphin-memory-engine) / Dolphin `MemoryWatcher` + `Pipes` | MIT / GPL (used over a socket, no contamination) | a drop-in Dolphin reader (MEM1/MEM2 base discovery, pointer chains); change-driven updates; a second pad path (`PRESS A`, `SET MAIN x y` over a named pipe) | 5th; [Felk/dolphin](https://github.com/Felk/dolphin) adds in-process Python with `event.frameadvance()` (78 stars, 2025) |
| [polyanya](https://github.com/vleue/polyanya) | Apache-2.0 | any-angle navmesh paths without a funnel pass (Rust, PyO3 needed) | alternative to Detour's funnel |
| [PINE](https://github.com/GovanifY/pine) (PCSX2, DuckStation) | MIT (PCSX2 GPL-3.0) | Read8..64 / Write8..64 over a socket (`$XDG_RUNTIME_DIR/pcsx2.sock`), savestates; **no pad input** | for RE4 PS2 reads if /proc is not wanted |
| [RPCS3](https://github.com/RPCS3/rpcs3) | GPL-2.0 | no scripting / IPC; guest memory is a 4 GiB reservation whose base is the first free 4 GiB-aligned host address (not fixed at 0x3'0000'0000): keep resolving it from /proc/<pid>/maps | what gBox does now |
| [xenia-canary](https://github.com/xenia-canary/xenia-canary) | BSD-3-Clause (unverified) | guest memory is one file mapping `xenia_memory_<tick>`; TOML `[[patch.be8]]` static patches; no IPC | RE6 X360 reads: external process memory only |
| [Azahar](https://github.com/azahar-emu/azahar) (Citra successor) | GPL-3.0 | ZeroMQ scripting RPC with read / write memory (`dist/scripting/AzaharRPC.py`); input injection **unconfirmed** | the route to Mercs 3D RAM |
| [BizHawk](https://github.com/TASEmulators/BizHawk) | MIT (cores vary) | Lua memory + joypad + frameadvance; no GC / Wii / PS2 / PS3 / X360 | not for these titles |
| [stable-retro](https://github.com/Farama-Foundation/stable-retro), [PyBoy](https://github.com/Baekalfen/PyBoy), [libmelee](https://github.com/altf4/libmelee) | MIT / LGPL-3.0 / LGPL-3.0 | the RAM-dict -> reward pattern; libmelee is the only working Dolphin agent stack (Slippi Gecko codes for state, named pipes for input) | pattern only |
| [sunone_aimbot](https://github.com/SunOner/sunone_aimbot) (MIT), [RootKit AI-Aimbot](https://github.com/RootKit-Org/AI-Aimbot) (GPL-3.0, archived), Aimmy (source-available, not open source) | - | YOLO screen aimbots: slower than RAM, only a fallback for an enemy without a resolvable pointer | not needed |
| [re4_tweaks](https://github.com/nipkownix/re4_tweaks) (Zlib), [emoose/re4-research](https://github.com/emoose/re4-research) (BSD-3) | | RE4 UHD struct headers and an IDA DB (>80 % functions named), a GC debug `.sym` parser: the fastest way to label the GC / Wii build's player / enemy objects (offsets differ) | for the RE4 title |
| [REFramework](https://github.com/praydog/REFramework) (MIT) | | RE Engine only (RE2/3/4R/7/8); nothing for MT Framework RE5 / RE6 | no |

Recommendation: Detour's funnel + `moveAlongSurface` on the RE5 navmesh (Zlib) and the ioquake3 aim formulas
(reimplemented) are the two that change the bot's play; RVO2 for the grab-avoidance layer; py-dolphin-memory-engine
only if the hand-rolled Dolphin reader ever needs pointer chains. Licence note: gBox's own licence was not checked
for this survey; the GPL rows are design references, not code to copy.

---

## 11. Sources (the ones cited by name above)

* Fandom: [The Mercenaries (RE5)](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5)),
  [The Mercenaries Reunion](https://residentevil.fandom.com/wiki/The_Mercenaries_Reunion),
  [score guide](https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5)_score_guide),
  [Melee (RE5)](https://residentevil.fandom.com/wiki/Melee_(RE5)),
  [Public Assembly](https://residentevil.fandom.com/wiki/Public_Assembly_(Mercenaries_stage)),
  [Prison](https://residentevil.fandom.com/wiki/Prison_(Mercenaries_map)),
  [Duvalia gameplay](https://residentevil.fandom.com/wiki/Duvalia/gameplay),
  [Gatling Gun Majini](https://residentevil.fandom.com/wiki/Gatling_Gun_Majini) (wikitext kept on the Spark).
* Berserker's blog: [scoring system](http://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-combo.html),
  [full stat list](http://berserkersblog.blogspot.com/2011/07/resident-evil-5-mercenaries-full-stat.html),
  [lag shot](http://berserkersblog.blogspot.com/2012/04/resident-evil-5-mercenaries-lag-shot.html),
  solo strategies: [Public Assembly](http://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-public.html),
  [The Mines](https://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-mines-solo.html),
  [Village](https://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-village.html),
  [Experimental Facility](https://berserkersblog.blogspot.com/2011/12/resident-evil-5-mercenaries.html),
  [Missile Area](https://berserkersblog.blogspot.com/2012/01/resident-evil-5-mercenaries-missile.html),
  [Ship Deck](https://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-ship-deck.html),
  [Prison](https://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-prison-solo.html); duo:
  [Public Assembly](http://berserkersblog.blogspot.com/2011/10/resident-evil-5-mercenaries-public.html),
  [Ancient Ruins](http://berserkersblog.blogspot.com/2011/10/resident-evil-5-mercenaries-ancient.html),
  [Prison](http://berserkersblog.blogspot.com/2011/10/resident-evil-5-mercenaries-prison-duo.html);
  [Info Database](http://berserkersblog.blogspot.com/2011/10/resident-evil-5-mercenariesmercenaries.html).
* Resident Evil 5 Zone: [Mercenaries info](https://residentevil5zone.blogspot.com/2010/11/resident-evil-5-mercenaries-info.html),
  [Reunion info](http://residentevil5zone.blogspot.com/2010/11/mercenaries-reunion-info.html).
* residentevilforums: [leaderboard guide (t3924)](https://residentevilforums.forumotion.com/t3924-mercenaries-reunion-guide-to-leaderboard-runs-re5),
  [maxing the score (t2261)](https://residentevilforums.forumotion.com/t2261-re5-tips-and-tricks-for-maxing-the-score-on-mercenaries-re5).
* residentevil.org: [RE5 Mercs guide](https://residentevil.org/threads/re5-mercs-guide.1347/),
  [Reunion characters rated](https://residentevil.org/threads/the-mercenaries-reunion-characters-rated-best-to-worst.2661/).
* GameFAQs (snippets): [Reunion high score guide](https://gamefaqs.gamespot.com/boards/929198-resident-evil-5/56220529),
  [Prison help](https://gamefaqs.gamespot.com/boards/929197-resident-evil-5/49684739),
  [S rank Q&A](https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/answers/50572-is-there-an-s-rank-in-mercenaries-mode),
  [highest scores](https://gamefaqs.gamespot.com/boards/929198-resident-evil-5/60681285).
* Japanese: [kouryakutsushin Mercenaries](https://kouryakutsushin.com/bio5/mercenaries.htm),
  [Reunion](https://kouryakutsushin.com/bio5/reunion.htm) and the per-stage `re-*.htm` pages;
  stv_tribute: [PA route](https://stv-tribute.hatenadiary.org/entry/20091115/1258287503),
  [Missile map](https://stv-tribute.hatenadiary.org/entry/20091207/1268131864),
  [Missile Reunion route](https://stv-tribute.hatenadiary.org/entry/20100302/1268132051),
  [impressions / chest test](https://stv-tribute.hatenadiary.org/entry/20100316/1268751267),
  [guidebook notes](https://stv-tribute.hatenadiary.org/entry/20100328/1269751620).
* Records: speedrun.com RE5 Steam (`369po01l`) Reunion solo boards; YouTube and nicovideo titles as linked in section 3.
* Hacks: [Steamworks cheat table thread](https://residentevilmodding.boards.net/thread/4273/resource-resident-steamworks-cheat-table),
  [REMADE table thread](https://residentevilmodding.boards.net/thread/4644/remade-resident-steam-patch1-cheattable),
  [FLiNG +16 (gamepressure)](https://www.gamepressure.com/download/resident-evil-5-gold-edition-v10-v11-16-trainer/zfe190).
* RE4 / RE6 / 3D and the survey: as linked inline in sections 7-10 (TASVideos, Cyberscore, GameFAQs, Fandom,
  residentevil.org, kouryakutsushin, Sephirosuy, gamehacking.org, GitHub).
