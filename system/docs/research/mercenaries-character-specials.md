# Mercenaries character specials: RE4 (Switch) and RE5 (Switch)

These are research notes for the MercMode autoplay bot. They cover every playable Mercenaries character's special,
melee and finisher moves, the triggers on Switch controls, the enemy states each move needs, the payoffs, the scoring
and time rules, the loadouts, how expert players use each character, and how to kill each boss fast.

They were compiled on 2026-11-09 from web sources, plus a few facts the gBox repo measured live (tagged [R1]/[R2]).
Nothing here was tested in-game for this document.

**How to read it.** `[Sx]` is a source key, and section 8 lists every URL. **UNCONFIRMED** means that no source was
found, or that only a forum post or search snippet supports the claim. When sources disagree, both values are given.
GameFAQs, Supercheats, Neoseeker and kouryakutsushin.com refused automated fetches (HTTP 403). Where they are cited,
the claim comes from a search-result snippet or from the repo's earlier meta doc [R3], and the entry says so.

---

## 0. The facts that matter most for the bot

1. **The RE4 Switch default controls come from the official Capcom manual [S37]:**

   | Action | Switch input |
   |---|---|
   | Ready weapon | ZL |
   | Fire | ZL + ZR |
   | Reload | ZL + B |
   | Knife | L + ZR |
   | **Action, including every melee prompt** | **Y** |
   | Run | Left stick up + B |
   | 180-degree turn | Left stick down + B |
   | Give orders (Ashley's command, **which is Krauser's arm button**) | **R** |
   | Map | X |
   | Status | + |

   The kick prompt appears at the lower left of the screen as "(Y) KICK".
   - **Repo conflict:** `system/gbox/mercs/titles/re4_switch.py` sets `RELOAD_BTN = "r"` [R2]. The manual puts reload
     on ZL + B and gives R to "Give orders". As Krauser, R raises the Plaga arm when it is charged.
2. **RE5 Switch does not have a public manual.** The mapping here is inferred: the PS4 default is Type D [S38], and the
   repo's live measurements [R1] fit it by button position.

   | Action | Switch input | Status |
   |---|---|---|
   | Aim | ZL | live |
   | Fire | ZL + ZR | live |
   | Knife | L + ZR | live |
   | Action and melee prompts | **Y** | live: the time-bonus prompt reads "press:y" |
   | Self-revive | A, mashed | live |
   | Break free | shake the left stick | live |
   | Run, quick turn and reload | B | inferred, not yet live-confirmed |

   **Wesker's dash** starts with a right-stick click (R3), and some sources say both sticks. His Knee Cannon is on the
   fire button (ZR); one source says the action button instead (Y on Switch). See 3.4.
3. **The RE4 melee moves come in a fixed pair per character.** A head stun (the Ganado holds its face) or a leg stun
   (the Ganado kneels) is followed by the action button. HUNK's head-stun Neckbreaker always kills [S1][S5].
   Wesker's two melees deal 2,000 damage each [S8]. Krauser's Plaga arm kills everything in its path, bosses included.
   It is ready at the start of a stage and then recharges in 45 s [S1][S9], or about 30 s [S43].
4. **RE4 gives no documented time for melee kills.** Time comes only from the hourglass "Time Extensions" (UNCONFIRMED
   as a negative; [R3] says the same). The combo window is 11 s on screen [S1]; the RAM routine uses 300 frames,
   which is 10 s [R3]. Bosses pay their 4,500 combo bonus only at a 10+ combo [S1].
5. **RE5 melee kills add 5 s each** (knife kills excluded) [S2]. A melee animation makes the player invincible
   [S34][S55]. The rear-leg melees of Chris, Sheva, Jill, Josh and Excella instantly kill regular Majini, and no Plaga
   emerges [S2][S3][S5]. The combo window is 10 s [S2][S46].
6. **On Switch, RE5 Mercenaries is "The Mercenaries United"** (all 18 costumes, all stages unlocked), and the operator
   plays it in No Mercy [S4][S38][R1]. Two consequences:
   - In United, Chris and Sheva use the **base** Mercenaries melee set even in their Reunion costumes [S4].
   - In a solo game no partner-specific Reunion melee can ever appear [S3].
7. **Several RE5 bosses accept solo melee chains,** driven by their own stagger states: Big Man, Giant, Executioner,
   Gatling and Chainsaw [S20][S22][S23][S25][S26]. Regular Majini get a finisher only from a partner chain [S5].

---

## 1. Controls

### 1.1 RE4 (2005) on Switch, compared with other platforms

The Switch column is from the official Switch web manual, pages 6-7 and 10 [S37]. The other columns are from
StrategyWiki [S40]. The Switch port follows the HD layout by button position: the Xbox left face button X becomes
Switch Y.

| Function | GameCube | PS2 | PC UHD, XInput Type 1 | **Switch (default)** |
|---|---|---|---|---|
| Ready weapon / aim | R | R1 | RT (LT on Type 2, RB on Type 3) | **ZL** (aim with the right stick while ZL is held) |
| Fire | R + A | R1 + X | RT + X (LT + RT on Type 2) | **ZL + ZR** |
| Reload | R + B | R1 + Square/Circle | RT + A | **ZL + B** |
| Action, incl. all melee prompts and the 2x tap that kicks a door | A | X | X | **Y** ("Press the action button when the prompt appears", e.g. "(Y) KICK") |
| Knife | L, then L + A | L1, then L1 + X | LT + X (LB + RT on Type 2) | **L, then L + ZR** |
| Command Ashley = **Krauser's arm** in Mercenaries | X | R2 | RB (RT on Type 3) | **R** ("Give orders") |
| Run / 180-degree turn | B + up / B + down | Square or Circle + up / down | A + up / down | **B + left stick up / down** |
| Map / Status | Z / Y | Triangle / Start | Y / Start | **X / +** |
| Menu confirm / cancel | A / B | X / Square or Circle | A / B | **Y or A / B** |

- The Switch port has no motion controls [S37]. Reviewers note that it offers several control schemes; only the
  default is documented above (web manual [S37]).
- **Mercenaries costume selection on Switch** is made by holding a button at the character select [S1]. No source says
  a costume changes moves or loadout, so treat them as cosmetic (UNCONFIRMED).

  | Character | Hold X | Hold R | Hold X + R |
  |---|---|---|---|
  | Ada | Separate Ways outfit | Assignment Ada outfit | - |
  | Leon | RPD uniform | jacket | suit |

### 1.2 RE5 on Switch, compared with other platforms

| Function | PS3 (StrategyWiki table [S39]) | Xbox 360 [S39] | PS4, Type D default [S38] | **Switch** |
|---|---|---|---|---|
| Ready weapon | L1 | LT | L2 | **ZL** [R1, live] |
| Fire | L1 + R1 | LT + RT | L2 + R2 | **ZL + ZR** [R1, live] |
| Knife | L2, then L2 + R1 | LB, then LB + RT | L1, then L1 + R2 | **L, then L + ZR** [R1, live] |
| **Action (melee prompts, time bonus, doors)** | Square | X | Square | **Y** [R1, live: the hourglass prompt is "press:y"] |
| Co-op action / call. Solo: mash it in Dying to self-revive [S2] | Circle | B | Circle | **A** [R1: "Resuscitate", A mashed] |
| Run (stick up +), quick turn (stick down +) | X | A | Cross | **B** (by position; UNCONFIRMED live) |
| Reload | L1 + X | LT + A | L2 + Cross | **ZL + B** (by position; UNCONFIRMED live) |
| Item menu / map / locate partner | Triangle / R2 / R1 | Y / RB / RT | Triangle / R1 / R2 | **X / R / ZR alone** (by position; UNCONFIRMED) |
| Grab escape | - | - | - | **shake the left stick** ("Break free") [R1] |

- **The PS4 default swaps the shoulder buttons.** The PS4 manual states that Type D is the default and that it swaps
  L1/L2 and R1/R2 relative to PS3 [S38]. The repo's PS3-to-Switch table is position-based:
  `l1→zl, r1→zr, l2→l, r2→r, square→y, cross→b, circle→a, triangle→x` (`re5_switch_brain.py`) [R1].
- **RE5 has four control types** [S60]:
  - Type A: move with the left stick, fire with RT + X.
  - Type B: move with the left stick, fire with LT + RT.
  - Types C and D: strafe with the left stick, turn with the right stick.

  These are 360 names; the file is in-game, and its Fandom transcript is the source. The Switch's default type is
  UNCONFIRMED, but it behaves as Type D: ZL aims and ZR fires.
- **The PS4 manual adds an "Action Assist" option** [S38]. It is On by default, and it makes "scenes that require you
  to press buttons rapidly or with a specific timing" easier. Whether Switch has the same default is UNCONFIRMED.
- **Wesker's dash inputs** are in 3.4. Sources disagree on them, and they are not yet measured on Switch.

---

## 2. Resident Evil 4: The Mercenaries, per character

### 2.1 Shared rules

- **Two melee moves per character.** One follows a head stun, when the Ganado "hold[s] onto their faces in pain"; the
  other follows a leg stun, when the Ganado falls to its knees after a lower-leg shot. Both are performed with the
  action button when the prompt appears [S1][S5][S37].
- **What sets up a stun:** handguns, the TMP and well-placed knife slashes produce these states [S5]. A flash grenade
  dazes nearby Ganados, which also opens a melee [S32].
- **Bosses:** only the Bella (Chainsaw) Sisters on Stage 1 can be hit with melee [S1]. Garrador, Gatling Man and the
  Giant Chainsaw Man never show a melee prompt, but a melee on a nearby Ganado can knock them over [S28][S30][S31].
- **Grabs:** shaking off a Ganado's grab sometimes ends in a grapple-breaker that briefly stuns it, but it gives no
  melee prompt [S5].
- **Invincibility:** melee animations grant invincibility frames (general series statement [S5]). Their length in RE4
  is UNCONFIRMED.
- **Time:** item menus, item pickups and cutscenes do not consume Mercenaries time [S45].
- **Running speed:** equipping a grenade makes the character run faster [S45]. A bot that must "never stand still" can
  keep a grenade in hand while it travels.
- **Health:** Krauser has 10 bars, Leon and Wesker 7.75, HUNK 7 and Ada 6.5 [S1].
- **Speed:** sources disagree. Krauser runs fastest and Ada second according to [S1] and [S9]; the Ada page calls her
  "the best speed" [S11].

### 2.2 Leon S. Kennedy (default)

| Move | Switch trigger | Enemy state needed | Effect | Cost | Sources |
|---|---|---|---|---|---|
| Roundhouse kick | Y at the prompt | head stun (holding its face) | sends the target back and hits anyone in the radius (crowd knockdown) | none | [S12][S5][S6] |
| Side kick (Stage 1 villagers) | Y | leg stun (kneeling villager) | knocks it onto its back and makes enemies behind it stumble | none | [S1][S12] |
| Suplex (Stages 2-4: zealots and soldiers) | Y | leg stun (kneeling zealot or soldier) | about 3.6 FP on zealots and 4.4 FP on soldiers, or a decapitation (instant kill) | none | [S6] (low-reliability page); [S12] |
| Knife | L + ZR | any | about 1.74 FP; can produce a stun | none | [S6][S5] |
| Grapple breakers (jump kick if grabbed from the front, elbow from behind) | grab escape | being grabbed | brief stun, no prompt | - | [S12][S5] |

- **Loadout:** Blacktail, Riot Gun, 30 handgun rounds, 10 shotgun shells, First Aid Spray and the knife [S1][S12][S43].
  [S41] and [S44] add a Green Herb.
- **How experts use him:** floor groups with the Blacktail, then finish the pile with the Riot Gun. The Riot Gun is
  his only answer to the Bella Sisters, J.J. and Super Salvador. Avoid the Garrador with Leon [S43]. He is "the
  hardest character to achieve a five star rating with" [S43] and "the most balanced" [S12].

### 2.3 Ada Wong (4 stars on Village)

| Move | Switch trigger | Enemy state | Effect | Sources |
|---|---|---|---|---|
| Fan kick (*senpukyaku*) | Y | head stun | knockdown kick | [S1][S11][S5] |
| Back kick (*kaitenkyaku*) | Y | leg stun | knockdown kick | [S1][S11] |
| Knife | L + ZR | any | she has a knife from the Wii version onwards, so on Switch too | [S1][S11] |

- **Loadout:** Punisher, TMP, semi-auto rifle with scope, 5 rifle rounds, 30 handgun rounds, 100 TMP rounds,
  3 incendiary grenades and a First Aid Spray [S1][S11][S43].
- **How experts use her:**
  - The rifle pierces many enemies, so line up headshots; the Punisher pierces five [S43].
  - For a large group, shoot out their kneecaps with the TMP, then throw an incendiary grenade into the pile [S43].
- **Risk:** she has the lowest health and dies one hit earlier to these attacks [S1]:
  - crossbows;
  - on the Castle, the mace, crossbow and scythe;
  - on the Base, the axe and shock attacks.

### 2.4 Jack Krauser (4 stars on Castle)

| Move | Switch trigger | Enemy state | Effect | Cost / cooldown | Sources |
|---|---|---|---|---|---|
| **Plaga arm blade thrust** | **R** (Ashley's command button; X on GameCube), aim left or right with the stick, then attack. The attack was A on GameCube; **on Switch it is UNCONFIRMED: try Y, then ZR**. Cancel with B (GameCube) | none (free use); ready when **the arm glows red** | Krauser lunges forward and "will destroy all enemies and objects in one hit, even all the stage bosses". It also kills any Ganado about 1 m beyond the visible arm | **45 s** to recharge per [S1][S9], **about 30 s** per [S43]. Ready at the start of every stage | [S1][S9][S43] |
| Double kick (roundhouse, then hook) | Y | head stun | both kicks hit and usually catch nearby enemies too; almost always decapitates. It is the only RE4 melee that hits more than once | none | [S9][S5] |
| Knee | Y | leg stun | almost always decapitates | none | [S9] |
| Knife | L + ZR | any | more range and power than Leon's knife, more likely to stun, kills a Ganado in a few hits | none | [S1][S9] |

- **Loadout:** Krauser's Bow, flash grenades x3, a First Aid Spray and the knife [S1][S9]. Arrows: x30 per
  [S1][S9][S43], x20 per [S41][S44].
- **The bow:**
  - It has a laser sight, no arc, and a fresh arrow after every shot [S33].
  - Fire faster by releasing and re-pressing aim, which skips the reload animation but resets the aim to
    neutral [S9].
  - It one-shots most Ganados on GameCube, but "in other console releases enemies sometimes need to be shot twice or
    even thrice" [S33]. That covers the Switch's HD lineage.
- **Mobility:** 10 health bars, faster running than Leon, and a backward get-up [S9].
- **How experts use him:**
  - Flash a group, then melee it or use the arm [S9].
  - Save the arm for big groups and for the Bella Sisters, Garrador, J.J. and Super Salvador [S43].
  - On Waterworld, gather both Super Salvadors and kill them with one arm thrust [S41].
- **Weakness:** once the flashes are spent and the arm is recharging, he cannot control a crowd [S9].

### 2.5 HUNK (4 stars on Base / "Island")

| Move | Switch trigger | Enemy state | Effect | Sources |
|---|---|---|---|---|
| **Neckbreaker** | Y | head stun | **always fatal**; stops a Plaga from erupting; works on the Bella Sisters | [S1][S5][S10][S43] |
| Kick ("football kick" / "Riot Kick") | Y | leg stun | knocks the enemy back several yards. Also used on stunned shield Ganados and on Ganados whose Plaga has emerged | [S10][S5][S41] |

- **Loadout:** Custom TMP, 50 TMP rounds, 3 hand grenades and a First Aid Spray. He has no knife [S1][S10][S43].
- **Expert loop:** pepper the Ganados with the TMP, shoot one in the head, then walk in for the Neckbreaker [S43].
  - **Bella Sisters:** "Shoot the first sister in the face with your TMP so she recoils and use the neck breaker." It
    kills instantly [S43].
  - **Groups:** kneecap them with the TMP, then throw a hand grenade into the pile [S43].
- **Risk:** "the slight delay after using it leaves him open to attack if he uses it in a large group" [S43]. Use the
  Neckbreaker only on isolated targets.

### 2.6 Albert Wesker (4 stars on Waterworld)

| Move | Switch trigger | Enemy state | Effect | Sources |
|---|---|---|---|---|
| Thrust punch (*shotei*) | Y | head stun | **2,000 damage**, extremely fast; sends the target flying, "an instant death in most cases". It can catch bosses standing nearby and can be used on the Bella Sisters directly, though "most will survive" | [S8][S1] |
| *Chikyo chagi* (axe kick) | Y | leg stun | **2,000 damage**; "instantly crushing their skull". It cannot instantly kill the Bella Sisters | [S8][S1] |

- **Loadout:**
  - handgun with silencer, Killer7, semi-auto rifle and a First Aid Spray [S1][S8][S43];
  - grenades: 4 hand grenades, 3 flash grenades and 1 incendiary [S1][S8][S43]. [S41] and [S44] list "four flash
    grenades" instead;
  - no spare ammo for any of his guns [S8];
  - no knife [S1].
- **How experts use him** (he is the TAS pick) [S45]:
  - He has the best weapon selection.
  - His silenced handgun lands a critical headshot about 50 % of the time.
  - The Killer7 pierces 3 enemies and the rifle 5; both are used on the Bella Sisters.
  - A flash grenade can kill Plagas.
- **Community advice:** drop the silencer, because noise attracts enemies; use the rifle all the time and save the
  Killer7 for bosses [S43].

---

## 3. Resident Evil 5: Mercenaries, Reunion and United, per character

### 3.1 Shared rules

- **Stun sites:** head, arms and legs. Arm and leg moves differ depending on whether the player is in front of the
  enemy or behind it, which gives five basic melees, plus a ground melee and the combo finishers. Enemies are much
  harder to stun with the knife than with guns [S5][S7].
- **Rear-leg instant kills:** the rear leg-stun melees of Chris (Neckbreaker), Sheva (Throat Slit), Jill (Head Grab),
  Josh (Suplex) and Excella (First Aid) **instantly kill regular Majini** (Town, Wetland and Base) "and prevent their
  Plaga from emerging" [S5][S2][S3][S16][S17].
- **Ground melee:** a melee on a downed enemy "can cause critical damage and instantly kill enemies if the player is
  standing directly over their head", but it does not prevent a Plaga [S5].
- **Finishers:** a regular Majini gets a finisher only from a **partner** chain. One player's arm-stun melee pushes it
  back, the partner melees, and the first player gets a finisher prompt [S5]. Some sub-bosses take a finisher directly
  or by solo chain (section 5.2).
- **Time:** **+5 s per melee kill**, and a multi-kill by one melee adds 5 s for every kill. Knife kills do not
  count [S2]. **Stun Rod kills** (Heavy Metal Chris) also add 5 s [S35].
- **Invincibility:** melee prompt attacks, item pickups, climbing and jumping down, and context dodges grant
  invincibility for "a few seconds" [S34]. "The melee animation makes you temporarily invincible", so a group can be
  meleed one at a time without taking damage [S55].
- **Cephalo risk:** head kills on Majini can roll a random Cephalo. "Always avoid any type of melees that hit the head
  of a Majini" (Missile Area) [S52], and avoid headshots or head melees on female Majini on Public Assembly [S49].
- **Solo self-revive:** in Dying status, mash the partner-action button [S2]. On Switch that is A [R1].
- **Mode differences:**
  - **Reunion:** melees are stronger, and Chris's Straight and Uppercut and Sheva's Roundhouse and Somersault were
    raised [S3]. Partner-specific "special melees" exist only in Duo [S3].
  - **United (the mode on Switch):** Chris and Sheva use the **base** set in every costume, because the Reunion moves
    have "completely different damage values and hitboxes". Time Bonus statues and Combo Time pickups sit in their
    Reunion locations [S4]. Whether Josh, Excella, Barry and Rebecca keep their Reunion values in United is
    UNCONFIRMED.
- **Player health:** all base Mercenaries characters start with 1,000 HP [S47].
- **Sunglasses:** Chris (Safari) and Wesker (both costumes) wear sunglasses and do not flinch from flash grenades. The
  glasses can fall off when the character is knocked down [S2].

### 3.2 Base melee table: Chris, Sheva, Jill, Wesker (all costumes share it)

Damage values (HP) are from [S2]. Where Berserker's stat list [S47] or another page differs, both are given.

| Position | Chris | Sheva | Jill | Wesker |
|---|---|---|---|---|
| Head stun | Straight 400 | Roundhouse 350 | High Kick 350 | **Cobra Strike 1,200** |
| Arm stun, front | Hook 300 | Twist Kick 250 ([S47]: 225) | Roundhouse 250 | Panther Fang 300 |
| Arm stun, back | Kick 300 | Knee 250 ([S47]: 225) | Reverse Roundhouse 250 | Jaguar Kick 300 |
| Leg stun, front | Uppercut 400 | Somersault 350 | Sweep Kick 350 | Tiger Uppercut 400 |
| **Leg stun, back** | **Neckbreaker: instant kill, no Plaga** | **Throat Slit: instant kill** | **Head Grab: instant kill** | Mustang Kick 500 |
| Finisher, front | Haymaker 3,000 | Skull Crusher: instant kill per [S2]; 3,000 per [S47] | Flip Kick 2,000 x2 ([S47]: 2,000) | Ghost Butterfly 4,000 |
| Finisher, back | Backhand 3,000 | Spinning Back Kick 3,000 per [S2]; "instant kill" per [S7] | Cartwheel Kick 2,000 x2 | Rhino Charge 4,000 |
| Grounded | Stomp 600 (head critical) | Impale 800 | Double Knee Drop 1,200 | Windfall 600 |
| Grapple breaker | Top-down Punch 500 | Pivot Kick 450 | Double Kick 350 x2 | Ram Horn 500 |
| Licker knockdown | Uppercut 600, then Stab (instant kill) | Somersault 600, then Stab 900 | Sweep Kick 600, then Stab 900 | Tiger Uppercut 600, then Stab 1,200 |

Licker-row sources: [S13][S8][S47].

- **Scale:** regular Majini have 700-900 HP (Town 800, female 700, Wetland 700-900, Base 800) and the Agitator has
  1,400 [S47]. **Wesker's head-stun Cobra Strike (1,200) is therefore a one-hit kill on any regular Majini.** This is
  derived from the two tables; Berserker's Mines route uses "flash grenade, then Cobra Strike melee kill" [S50].
- **Jill's knife** is "an extremely fast stabbing attack" [S2]. That helps with knife stun attempts, but knife kills
  give no time.

### 3.3 Reunion characters' melee: Josh, Excella, Barry, Rebecca

Values are from [S3]. Per-character pages that differ are noted. Partner-only moves are omitted, since they never
appear in solo.

| Position | Josh | Excella | Barry | Rebecca |
|---|---|---|---|---|
| Head stun | Hammer Blow 700 ([S17]: 500) | High Heel 400 | Headbutt 400 | **Flame Spray 900** ([S19]: 800); kills most normal Majini and hits several at once [S19] |
| Arm stun, front | Backhand 400 ([S17]: 300) | Slap 50 ([S16]: 100) | Barry Sandwich 300 | Tear Gas 200 |
| Arm stun, back | Iron Tackle 800 ([S17]: 500) | Back Hand 50 | Knee 300 ([S18]: 250) | Rump Shaker 200 |
| Leg stun, front | Power Kick 400 | Humiliate 800 ([S16]: 750) | Burton Boot 400 ([S18]: 250) | Jump Hit 300 |
| **Leg stun, back** | **Suplex: instant kill** | **First Aid: instant kill, no Plaga, the corpse explodes** [S16] | Gun Bash 600 ([S18]: 800, "instant death but parasites may appear") | Head Cracker 400 |
| Finisher, front | Chokeslam: instant kill per [S3]; 4,000 per [S17] | Disco Spin 3,000 x2 ([S16]: 4,000) | Hurricane 2,000 x4 ([S18]: 1,500 x4) | Stun Gun 8,000 ([S19]: 5,000) |
| Finisher, back | Dynamite Kick 3,000 ([S17]: 4,000) | Disco Spin | Hurricane | Stun Gun |
| Grounded | Elbow Drop 1,000 ([S17]: 1,200) | Heel Stomp 500 x4 ([S16]: 600 x2) | **Miranda Rights 5,000** ([S18]: 1,200, head critical) | Kick 500 |

Chris (Warrior and Heavy Metal) and Sheva (Business and Fairy Tale) use the 3.2 moves. In Reunion, Chris's Straight
and Uppercut become 500 and Sheva's Roundhouse and Somersault 600 [S3]; in United they keep the base values [S4].

### 3.4 Albert Wesker's dash and Knee Cannon (Mercenaries and United only)

| Item | Detail | Sources |
|---|---|---|
| Start the dash | **Click the right stick (R3)** [S2][S54][S57]. Other sources say "click both thumbsticks at the same time" [S56] or "both analog sticks" [S59, snippet]. **Switch: R-stick click, with L+R stick click as a fallback (UNCONFIRMED live).** PC: Shift + X | [S2][S54][S56][S57][S59] |
| Steer | Tilt the right stick to steer "to a limited extent" | [S2] |
| Change direction | Up to **3 times**: push the left stick left, right or down together with the run button (A on 360, X on PS3; **B on Switch, inferred**) within 2 s of the dash start or of the previous turn. [S56] describes the right stick + A instead | [S2][S56] |
| **Knee Cannon** | The fire button: RT on 360, R1 on PS3, left mouse on PC [S2]; "fire" [S56]. One tip says Square, the PS3 action button [S57]. **Switch: try ZR first, then Y.** It deals **1,000 damage**, "will usually kill any normal Majini in a single hit, or knock them down", and ends the dash | [S2][S5][S47][S48][S57] |
| Dash contact | Running through Majini deals **200 damage** and briefly stuns them, which can set up a melee | [S5][S47] |
| Stopping | Running into a wall or structure stops the dash | [S2] |
| Cost | Health. Sources disagree: "a small amount of health" [S2]; "drains quite a bit of health each time" [S8]; about **15 % each time you begin it** (GameFAQs board post, search snippet only [S58]) | [S2][S8][S58] |
| Invincibility | "immune to all forms of attack while dashing" (a forum reply [S54]). **UNCONFIRMED**: the Fandom i-frame list does not mention the dash [S34] | [S54][S34] |
| Score use | A dash kill counts as a melee kill; Berserker uses it to kill the chicken [S49][S50] | [S49][S50] |
| Healing | Neither Wesker costume lists a First Aid Spray in its loadout [S2][S8], so the dash's health cost must be budgeted against drops | [S2][S8] |

### 3.5 Loadouts per costume (RE5)

Where Fandom [S2][S3] and other sources differ, both are given. Every costume is unlocked in United [S4][S38]. The
unlock requirements listed are for vanilla Mercenaries [S2].

| Costume | Loadout | Character-specific notes |
|---|---|---|
| Chris (BSAA) | Ammo varies by source (below); Ithaca M37 x20, hand grenades x5, First Aid Spray. **Switch live [R1]:** handgun ammo 50, hand grenades 5, machine-gun ammo 30, M92F 50/50 (capacity level 10), Ithaca 20, First Aid Spray, knife | Default character. Ammo by source: [S2] M92F x20, handgun ammo 50, shotgun ammo 10; [S42] M92F 50, shotgun ammo 30 |
| Chris (Safari) | SIG P226 x16, M3 x10, handgun ammo 30, shotgun ammo 10, **2 Rocket Launchers** [S2][S51] | Sunglasses make him immune to flash grenades [S2]. Unlock: A on Village |
| Chris (S.T.A.R.S.) | SIG 556 x65 + machine-gun ammo 150, S&W M29 x12 + magnum ammo 6, Grenade Launcher x12 (electric rounds) [S2] | His M29 is "the weakest" magnum [S51]. Unlock: A on Experimental Facility |
| Chris (Warrior) | H&K P8 x25 + handgun ammo 30, PSG-1 x15, Hydra x10 + shotgun ammo 15 [S3] | Reunion |
| Chris (Heavy Metal) | Gatling Gun (infinite), **Stun Rod**, hand grenades x3, proximity bombs x3, melee vest, bulletproof vest [S3] | A Stun Rod kill adds 5 s and prevents a Plaga [S35]. Community reports put him at about 60-70 melee kills a run [R3] |
| Sheva (BSAA) | M92F x40 + handgun ammo 50, VZ61, Dragunov SVD x13, First Aid Spray | Default character; aims left-handed [S2]. VZ61 by source: x150 + machine-gun ammo 150 [S2]; 260 + 30 [S42][S47] |
| Sheva (Clubbin') | AK-74 x50 + machine-gun ammo 100, S75 x20 + rifle ammo 10, Jail Breaker x8 + shotgun ammo 20 [S2] | Unlock: A on Ancient Ruins |
| Sheva (Tribal) | Longbow (infinite arrows [S47]), Grenade Launcher x6 (nitrogen rounds), incendiary grenades x3, flash grenades x3, First Aid Spray [S2] | Unlock: A on Missile Area |
| Sheva (Business) | SIG P226 x16 + handgun ammo 50, L. Hawk x8 + magnum ammo 12, proximity bombs x5, First Aid Spray [S3] | Reunion |
| Sheva (Fairy Tale) | SIG 556 x80 + machine-gun ammo 100, S&W M500 x6 + magnum ammo 6, Ithaca x25 + shotgun ammo 10, Gold Chicken Eggs x5 [S3] | Reunion; the eggs are full heals [R3] |
| Jill (BSAA) | Px4 x25 + handgun ammo 50, MP5 x150 + machine-gun ammo 150, flash grenades x5, First Aid Spray [S2][S42] | Fast knife [S2]. Unlock: A on Public Assembly |
| Jill (Battle Suit) | VZ61 x300 + machine-gun ammo 150, PSG-1 x9 + rifle ammo 30, hand grenades x3, herb (green + green per [S54]) [S2] | Unlock: A on Ship Deck |
| Wesker (Midnight) | H&K P8, S&W M500 x6 + magnum ammo 6, hand grenades x5, proximity bombs x5, handgun ammo 50 | Sunglasses; dash. P8 count by source: x15 [S2]; x21 [S8] (the capacity is 21 [S47]). Unlock: A on The Mines |
| Wesker (S.T.A.R.S.) | Samurai Edge x15 + handgun ammo 30, L. Hawk x8, Hydra x6 + shotgun ammo 10 [S2][S8] | Sunglasses; dash. His Hydra "will make mincemeat out of a stunned Chainsaw Majini" [S51]. Unlock: A on Prison |
| Josh | M92F x100 + handgun ammo 10, M3 x10 + shotgun ammo 10 ([S17]: 7 loaded), Rocket Launcher, hand grenades x3 [S3][S17] | Reunion |
| Excella | M93R x30 + handgun ammo 50, AK-74 x50 + machine-gun ammo 150, Grenade Launcher x12 **flash** rounds, First Aid Spray [S3][S16] | "one of the best" Reunion characters for her melees and flash launcher [S16] |
| Barry | Samurai Edge x30 + handgun ammo 50, S&W M29 x12 + magnum ammo 6, Dragunov SVD x18. No healing item [S3][S18] | He can finish a Chainsaw Majini or an Executioner after another player's melee (duo) [S18] |
| Rebecca | MP5 x120, Jail Breaker x10, machine-gun ammo 300, shotgun ammo 60, **First Aid Spray x2** [S19]. [S3]'s table lists one of each item twice | Weak leg melees; "high kill counts" [S19] |

### 3.6 How experts play each RE5 character

- **Wesker (Midnight or S.T.A.R.S.)** is Berserker's route character on Public Assembly and The Mines [S49][S50].
  - Dash kills count as melee kills; the dash also kills chickens [S49][S50].
  - Use "flash grenade, then Cobra Strike" on scripted Cephalo Majini [S50].
  - Use the M500 or L. Hawk on bosses.
  - A forum duo tip pairs him with Jill (BSAA), "Weskers Handkanon against Bosses" [S54].
  - Magnum leg shots kill the Chainsaw Majini on Ship Deck [S51].
- **Chris (BSAA, Warrior, Heavy Metal):**
  - Leg-shoot with the gun until the enemy kneels, walk in, then Uppercut from the front or Neckbreaker from behind.
    The Neckbreaker is an instant kill and adds 5 s [R3, citing community guides].
  - S.T.A.R.S. Chris is Berserker's Missile Area character [S52].
  - Use the Haymaker on a downed Gatling Majini [S23].
- **Sheva:** handgun headshot or leg shot, then Throat Slit from behind (instant kill). Business and Fairy Tale add a
  magnum for bosses [R3][S3]. Tribal has a grenade launcher and an infinite longbow [S2][S51].
- **Jill:** Head Grab from behind is an instant kill, and Double Knee Drop (1,200) kills a downed regular Majini.
  Battle Suit's VZ61 x300 is a leg-stun hose. No expert route was found (UNCONFIRMED).
- **Rebecca** is the solo world-record character in Reunion on several stages, because her head-stun Flame Spray kills
  normal Majini outright and adds 5 s [R3, citing community leaderboards].
- **Excella:** each of her 12 flash rounds kills Plaga forms, which makes her the Village and Ruins choice [R3][S16].
  First Aid makes the corpse explode on a crowd [S16].
- **Barry:** Headbutt from the head stun (high critical) and Miranda Rights on the ground. Use the M29 on bosses [R3].
- **Josh:** strong but slow melees, a rocket for one boss and the Suplex as his instant kill [R3][S17].
- **Shared stage advice** [S49][S50][S51][S52]:
  - "DON'T STAND STILL for too long or you risk the chance of getting grabbed."
  - Fight in narrow strips and tunnels where Majini line up for "multiple melee kills".
  - Shoot distant enemies to keep the combo.
  - Late in the round, "always make sure there are two before you kill one".

---

## 4. Scoring, time and combo rules

### 4.1 RE4 Mercenaries

| Rule | Value | Sources |
|---|---|---|
| Start time / end | 2:00. The round ends when the evacuation helicopter arrives (time runs out) or on death | [S1][S45] |
| Time Extensions (hourglasses) | **30, 50, 60 or 90 s each**, used with the action button (Y). Totals per stage: Village 5:30 (30, 90, 90, 90, 30 [S41][S44]); Castle 6:50; Base 6:00 (12 x 30 s); Waterworld 7:30. The map screen marks each one with a star labelled "Treasure" | [S1][S36][S41][S44] |
| **Melee kills and time** | **No source documents a time bonus for melee kills in RE4** (UNCONFIRMED as a negative; [R3] states RE4 gives none). Time comes only from the hourglasses | [S1][R3] |
| Points | Ganado 300; Bella Sister 5,000; Garrador 7,000; Gatling Man (J.J.) 10,000; Giant Chainsaw Man (Super Salvador) 5,000 | [S1][S44] |
| **Combo window** | Kills within **11 s** of each other [S1][S44]. In-house RAM finding: 300 frames, i.e. 10 s, in the add-kill routine [R3]. Plan with 10 s | [S1][S44][R3] |
| Combo bonus, normal enemy | 2nd kill 20, 3rd 50, 4th 100, 5th 200, 6th 250, 7th 300, 8th 350, 9th 400, **10th and later 700**. So a Ganado at a 10+ combo is worth 1,000 | [S1] |
| Combo bonus, boss (by its place in the combo) | 2nd 500, then +500 per place, up to **4,500 at the 10th and later**. "Kill bosses only during a 10+ combo." A Bella at 10+ is worth 9,500, a Garrador 11,500, a J.J. 14,500 | [S1][S45] |
| Payout | The bonus is added when the combo is lost | [S1] |
| **Bonus Time chest** | For **30 s** (the TAS measures 31 s) "each kill in combos ... will be worth 1,000 points instead of their usual amount", including the first kill, but not boss kills. The TAS breakdown shows 1,300 per Ganado during a chest. Each stage has 3 chests ([S44] gives Castle 2) | [S1][S45][S44] |
| Ranks | 1 star below 10,000; 2 stars at 10,000; 3 at 20,000; 4 at 30,000; **5 at 60,000** | [S1][S44] |
| Unlocks | 4 stars on Village unlocks Ada, Castle unlocks Krauser, Base unlocks HUNK, Waterworld unlocks Wesker. 5 stars with every character on every stage unlocks the Handcannon | [S1] |
| Caps | At most 10 Ganados on the map at once (bosses can exceed it). Village: 124 kills maximum | [S45] |
| Death | No points | [S41] |

### 4.2 RE5 Mercenaries (vanilla), Reunion, United and No Mercy

| Rule | Value | Sources |
|---|---|---|
| Start time | 2:00, with no upper limit | [S2] |
| Time crystals (statues) | +30 to +90 s each, usable once. They are taken by "smashing" the statue (a melee near it). On Switch the statue shows a **Y** prompt [R1]. In United every character uses the Reunion melee on the crystals [S4] | [S2][S4][R1] |
| **Melee kill** | **+5 s per kill.** Knife kills excluded; a multi-kill counts every kill; Stun Rod kills count | [S2][S35] |
| **Combo window** | Kills within **10 s** of each other; every enemy counts, chickens included | [S2][S46][S54] |
| Combo bonus, normal / boss | 2nd kill: 20 / 500; 3rd: 50 / 1,000; 4th: 100 / 1,500; 5th: 200 / 2,000; 6th: 250 / 2,500; 7th: 300 / 3,000; 8th: 350 / 3,500; 9th: 400 / 4,000; 10-19: 500 / 4,500; 20-29: 600 / 5,000; 30-39: 700 / 5,500; 40-49: 850 / 6,000; 50+: 1,000 / 7,000 | [S2][S46] |
| Payout | The bonus is banked when the combo breaks or the run ends | [S46] |
| Combo Timer pickups | While one runs, each combo kill gives 1,000. Sources disagree: "in addition to all other points" [S2], or in place of the normal bonus [S46]. Duration: 30 s per [R3, citing kouryakutsushin; not re-verified] | [S2][S46][R3] |
| Points (base) | Town Majini 300; Wetland and Base Majini 400; Bui Kichwa 400; Kipepeo 700; Licker beta 800; Cephalo 800; Duvalia 900; Adjule 900; Big Man 1,000; Chicken 2,000; Giant 5,000; Executioner 5,000; Reaper 6,000; Chainsaw 7,000; Gatling 10,000; Red Executioner 15,000 | [S2][S54][S55] |
| Enemy count | 150 per stage, at most 12 in play; one dies, another spawns | [S2] |
| Clearing all 150 | **1,000 points per second left** in vanilla, **300** in Reunion. United: UNCONFIRMED ([R3] asserts 300) | [S2][S3][S55] |
| Ranks (solo / duo) | D below 10k / 20k; C 10k / 20k; B 20k / 40k; A 40k / 80k; **S 60k / 120k; SS 90k / 150k**. Death means no rank, and the score is not recorded | [S2][S42] |
| Reunion changes | Sub-bosses spawn after 50 kills instead of 30, more enemy types appear, melees are stronger, and leftover time pays 300/s. [R3] also records that Reunion's combo bonus keeps rising past 50, citing community transcriptions; that is unverified here | [S3][R3] |
| **United (Switch)** | All 18 costumes and all stages are selectable from the start. Chris and Sheva use the base melee set. Statues and Combo Time pickups are in their Reunion locations | [S4][S38] |
| **No Mercy (Switch, inside United)** | Original PC No Mercy: 400 enemies, about 40 on the stage at once, boss spawns doubled after the first, at least 4 Rocket Launchers per stage, player damage +50 % and damage taken -30 % [S2]. **United's No Mercy caps kills at 300** [S4], and the damage bonuses **do not apply in United** ("likely oversight") [S2]. Switch live: 40-47 enemies alive at once [R1] | [S2][S4][R1] |
| Difficulty scaling (Reunion) | A hidden "Player Rank" changes during play and drives enemy dodge chance, knockdown recovery and grab-escape inputs. Per [R3], citing the official guidebook via stv-tribute | [R3] |

---

## 5. Bosses and special enemies: how to kill them fast

### 5.1 RE4

| Stage | Enemy | Facts | Fastest kill per character | Sources |
|---|---|---|---|---|
| 1 Village | **Bella (Chainsaw) Sisters** | 4,000 HP. One chainsaw hit kills. Pairs spawn after 10, 27 and 39 kills, 6 in total. A damage limiter means about 8 hits from a powerful weapon. **They are the only meleeable bosses** | **HUNK:** TMP to the face, then the Neckbreaker, an instant kill. **Krauser:** one arm thrust. **Wesker:** Killer7 to the head (the thrust punch hits, but most survive). **Ada:** rifle to the face, grenade when she is floored. **Leon:** Riot Gun to the head, plus grenades and barrels. Kill them only inside a 10+ combo (9,500 each) | [S1][S29][S43][S45][S8] |
| 2 Castle | **Garrador** (3 per stage) | Blind and hunts by sound: gunfire and running draw him, walking does not. Armored (normal type 3,500-4,000 HP, full-armor type 5,500). **No melee prompt.** Spawns: one by the staircase near the spawn, one in the end area, and the armored one bursts from a wall at about 95,000 points per [S28]; the first appears after 25 kills per [R3] | Stand by a wall and let him charge so his claws stick, then shoot the **back Plaga** with a rifle or magnum (Killer7). **Krauser:** the arm is an instant kill. Walking quietly behind him also works. [S28] warns that a flash makes him see you | [S1][S28][S41][S43] |
| 3 Base | **Gatling Man / J.J.** (up to 3) | 10,000 points; HP 1,600 or 5,000; drops a First Aid Spray. **No melee prompt.** Weak attacks don't stagger him; a strong headshot does | Stun-lock with headshots (shotgun, rifle or magnum), shooting again *after* each stagger animation ends. Knife him out of the air as he leaps up a ladder. **HUNK:** a TMP clip to the face, then a flash and reload while he recoils. **Wesker and Ada:** rifle or Killer7 headshots. **Krauser:** save the arm for him | [S1][S30][S43] |
| 4 Waterworld | **Giant Chainsaw Man / "Super Salvador"** (2) | 5,000 points; HP 3,500 or 4,000. A berserk swing is an instant death. Very flinch-resistant, no melee prompt. One spawns at **30 consecutive kills**; the other is triggered by entering his area or attacking him | Hit him as he lands from a ladder jump to knock him back down. A zipline gives escape distance. **Krauser:** one arm thrust kills both if they are close together. **HUNK:** a grenade, then the TMP while he is stunned. **Wesker:** Killer7. **Ada:** incendiary grenade, then rifle headshots. Flash grenades, explosions, fire and dynamite Ganados can stun him | [S1][S29][S31][S41][S43][S44] |

### 5.2 RE5 (Mercenaries / United)

Stage bosses [S2][S3]:

| Stage | Boss or special enemy |
|---|---|
| Public Assembly | Executioner (Reunion adds Big Man, Bui Kichwa and Duvalia) |
| The Mines | Reaper (Reunion adds Adjule) |
| Village and Ancient Ruins | Giant Majini, plus Kipepeo, Bui Kichwa and Duvalia |
| Experimental Facility | Licker beta swarm (vanilla, after a while); Lickers mixed with Base Majini (Reunion) |
| Missile Area | Gatling Majini |
| Ship Deck | Chainsaw Majini, red and blue (Reunion adds a Gatling) |
| Prison | Executioner and Red Executioner |

**Melee words used below:**
- **Leg-front melee:** Chris's Uppercut, Sheva's Somersault, Jill's Sweep Kick, Wesker's Tiger Uppercut.
- **Head melee:** Straight, Roundhouse, High Kick, Cobra Strike.
- **Front and back finishers:** the rows in 3.2 and 3.3.

| Enemy | Facts | Fastest safe kill (state, then melee) | Sources |
|---|---|---|---|
| **Executioner** (5,000 points; Public Assembly 8,000 HP, Prison 15,000) | One on the map at a time. Public Assembly spawns at about 20, 50 and 70 kills (vanilla). He can leap onto roofs in Mercenaries, but he **cannot enter the bus**. His grab is a QTE, and failing it is an instant death | **Kneel**, caused by a hand grenade, proximity bomb or most grenade-launcher rounds (always), or by magnum shots, leads to the **leg-front melee**. Barry uses Burton Boot, Excella Disco Spin, Rebecca Jump Hit and Josh Backhand. He then enters **"Recovering from melee"**, which leads to the **head melee**. Barry uses Hurricane, Excella High Heel, Rebecca Flame Spray and Josh Hammer Blow. After the second melee he often answers with an Axe Swing or Berserk, so step away, especially if his back is turned. Transformers and gas tanks on Public Assembly stun him | [S2][S20][S47][S49] |
| **Red Executioner** (15,000 points; 20,000 HP) | Overhead swing about 40 % faster. A Plaga sticks out of his back, and any damage to it staggers him. Prison (vanilla): 2 black and 3 red | Shoot the back Plaga, or magnum-shoot his head to stun him, then melee and repeat (the "magnum hold" loop). Use rockets on him in No Mercy | [S2][S21][S53] |
| **Chainsaw Majini** (7,000 points) | Red: 7,000 HP, swells and explodes when killed. Blue: 15,000 HP, always gets up berserk after its first "death" (berserk HP 1,500), and only that second kill counts. Swings are instant deaths; standing behind him invites a 180-degree swing | **Kneel**, caused by an explosion, a flash or a leg shot, leads to the **leg-front melee**. A **headshot stun** leads to the **arm-front melee** (Chris Hook, Sheva Twist Kick, Jill "Spin Kick" as [S22] calls it, which is her Roundhouse in 3.2; Wesker Panther Fang), then "Recovering", then the **head melee**. A flash stops a berserker. Wesker: magnum leg shots. Hydra on a stunned one. Line two up for magnum piercing | [S22][S47][S51] |
| **Gatling Majini** (10,000 points; yellow 4,000 HP, red 6,000; 8,000-14,000 in the campaign) | **Takes a finisher without a partner.** The ammo pack on his back is bulletproof. He taunts by firing into the air after downing a player, which is an opening. Missile Area spawns: yellow at 20 combo, yellow at 60, red at 90 | **Block** (a shotgun hit to the upper body) leads to the leg-front melee. A **headshot stun** (rifle or magnum to the head or upper chest) leads to the **front finisher**. **Kneel** (lower-body damage) or "Recovering" leads to the **back finisher**. Run sideways to dodge the gatling. "Try to use the deathblow melee on him" when he falls | [S23][S47][S52] |
| **Reaper** (6,000 points; 1,500 HP in Mercenaries) | Its grab is an instant death; destroying an arm stops the grab. Mines spawns: 30, 70 and 90 kills ("always a few kills before") | It "will ALWAYS expose its chest weak point when it turns", so shoot the chest sac (Hydra burst). Shooting the back sacs stuns it. Explosives roll it and drop its internal HP to about 1, after which any bullet kills. A direct rocket kills | [S24][S47][S50] |
| **Giant Majini** (5,000 points; 4,000 HP) | The mask is bulletproof. Lunge war cry, club swing, and a stomp that is an instant death on a Dying player | A lower-body shot (one magnum shot is enough) causes a **Kneel**, which leads to the **arm-front melee**. "Recovering" then leads to the **front finisher**. **Block** (arms crossed, sliding back) leads to the leg-front melee. Grenades and proximity bombs work | [S25][S47] |
| **Big Man Majini** (1,000 points; 4,000 HP) | Punches knock the player flying; may berserk; sometimes explodes when he dies in Mercenaries | A leg shot, Stun Rod or grenade causes a **Kneel**, which leads to the **head melee**. He goes to **Block**, which leads to the **leg-front melee**. He falls back a few steps, which leads to the **back finisher** (Backhand, Spinning Back Kick, Cartwheel Kick, Rhino Charge). An M500 shot to the head kills him | [S26][S47] |
| **Licker beta** (800 points; 900 HP) | Experimental Facility. The heart takes +300 % damage | Shoot the exposed brain so it coils, then the heart; it is knocked down, which gives the **Stab** instant-kill prompt. There is also a counter melee when it leaps (600). Use grenades or a shotgun on hordes | [S27][S47][S48] |
| **Plaga forms**: Cephalo (800 points / 3,000 HP), Kipepeo (700 / 1,000), Bui Kichwa (400 / 200), Duvalia (900 / 6,000), Adjule (900) | - | **A flash grenade almost always kills them immediately.** Excella's flash rounds work too. Use a machine gun on the whip-heads and the flyers. Rear-leg instant-kill melees and Stun Rod kills keep the Plaga from emerging at all | [S2][S32][S42][S47][S55][S5][S35] |
| **Chicken** (2,000 points) | Holds an enemy slot | A grenade or flash; Wesker's dash also kills it as a melee kill | [S2][S49][S50] |

---

## 6. Bot implementation notes (ranked by value)

### 6.1 RE4 (Switch): moves ranked

| # | Character: move | Detectable trigger state | Button sequence (Switch default [S37]) | Expected payoff | Main risk |
|---|---|---|---|---|---|
| 1 | **Krauser: Plaga arm** | The arm glows red, which means ready. It is ready at stage start and recharges in 45 s (or about 30 s). The cooldown should be found in RAM (UNCONFIRMED where it lives). Target: a boss within reach, or 3+ Ganados in a line ahead | **R** (raise the arm), then the left stick left or right (aim), then **attack**: UNCONFIRMED on Switch, so try **Y**, then **ZR**. **B** cancels | One-hit kill on everything in the line plus about 1 m, bosses included. A boss at a 10+ combo pays its base plus 4,500 | Wasting it on one Ganado; R pressed by mistake (R is not reload) |
| 2 | **HUNK: Neckbreaker** | Head stun: the Ganado clutches its face and the prompt "(Y) ..." appears at the lower left. Works on the Bella Sisters | TMP head shot (ZL, aim at the head, ZR), walk in, **Y** | Guaranteed kill, no Plaga; a Bella at 10+ combo = 9,500 | The recovery delay in a crowd: take it only with no other enemy within arm's reach |
| 3 | **Wesker: thrust punch** (head) / **chikyo chagi** (leg) | Head stun, or a kneel after a lower-leg shot | Silenced-handgun headshot or leg shot (ZL + ZR), step in, **Y** | 2,000 damage, usually a kill; the punch knocks nearby enemies back | Keeping the Killer7 for bosses |
| 4 | **Krauser: double kick** (head) / **knee** (leg) | Head stun or kneel, set up by an arrow, a knife slash (L + ZR) or a flash | Set up, then **Y** | Near-certain decapitation; the double kick hits several enemies | Slow bow aim |
| 5 | **Leon: suplex** (kneeling zealot or soldier) / **roundhouse** (head) / **side kick** (village kneel) | Kneel or head stun | Blacktail to a leg or the head, then **Y** | The suplex can decapitate; the roundhouse knocks down a crowd | Thin boss answers: avoid Garradors |
| 6 | **Ada: fan kick / back kick** | Head stun / kneel | Punisher or TMP shot, then **Y** | Knockdown, possibly a kill | Lowest HP: avoid crossbows and the Castle's heavy weapons |
| 7 | **Any character: flash, then chain melee** | A daze on a group [S32]; flash grenades also kill exposed Plagas [S45] | Select the flash grenade, throw it (ZL + ZR), then walk the group pressing **Y** at each prompt | A crowd cleared with no ammo, combo maintained | Bosses are not dazed for melee |
| 8 | **Ada / HUNK: kneecap, then grenade** | 3+ Ganados kneeling | TMP sweep at the legs, then a grenade (incendiary for Ada) | Group kill, combo steps | Self-damage at close range |

**RE4 policy rules** (from sections 4.1 and 5.1):
- Keep a kill at least every 10 s.
- Open a Bonus Time chest at the start of a dense chain.
- Hold the bosses until the combo is 10+.
- Take the hourglasses on the route, because melee gives no time.
- Keep moving, and equip a grenade while travelling for extra run speed [S45].
- Never stand in a chainsaw enemy's reach: the Bella Sisters and Super Salvador kill in one hit.
- On the Castle, walk, don't run, around Garradors.

### 6.2 RE5 (Switch, United / No Mercy): moves ranked

| # | Move (who) | Detectable trigger state | Button sequence (Switch, section 1.2) | Expected payoff | Main risk |
|---|---|---|---|---|---|
| 1 | **Rear leg-stun instant kill**: Chris Neckbreaker, Sheva Throat Slit, Jill Head Grab, Josh Suplex, Excella First Aid | Leg stun: the Majini drops to a knee or stumbles from a leg shot. The player must be **behind** it, and the prompt is shown. The repo reads prompts from RAM (`re5_switch_prompt`, sActionButton) [R1] | Leg shots (ZL + ZR at the thigh; aim can be rough, "sweep the gun downward while firing" [R3]), circle behind it, **Y** | Kill, +5 s, no Plaga, i-frames; Excella's corpse also explodes on the crowd | Getting behind takes time: if the front prompt appears first, the front leg melee is the fallback (row 6) |
| 2 | **Head-stun kill melee**: Wesker Cobra Strike (1,200), Rebecca Flame Spray (800-900, multi-target), Barry Headbutt (high critical), Excella High Heel (after the M93R burst) | Head stun: the Majini stumbles holding its head, and the prompt shows | Headshot (ZL + ZR), step in, **Y** | A regular Majini dies, +5 s | A head kill can roll a Cephalo: prefer row 1 on female Majini and on Missile Area |
| 3 | **Wesker: dash + Knee Cannon** | A target in a straight lane within dash range; Wesker's HP above the dash cost (about 15 % per [S58]) | **R-stick click** (or both sticks), steer with the right stick, then **ZR** (fallback **Y**) for the Knee Cannon. Turns: left stick + **B** within 2 s, at most 3 | 1,000 damage, usually a kill, which counts as a melee kill (+5 s); fast repositioning that also satisfies "never stand still" | HP cost with no First Aid Spray in either loadout; walls stop the dash. Inputs not yet live-measured |
| 4 | **Boss solo chains** (Big Man, Giant, Executioner, Gatling, Chainsaw) | The boss's state: **Kneel**, **Block** (arms crossed, sliding back), **Headshot stun**, or **Recovering from melee** (stepping back after a melee). Map these to the enemy motion ids in RAM (UNCONFIRMED) | Follow the per-boss state-to-move table in 5.2; **Y** at each prompt | Finishers of 2,000 x2 to 8,000. A boss at combo 10-19 pays its base plus 4,500 (50+: plus 7,000) | The Executioner's answer after two melees; chainsaw instant deaths: never stand behind a Chainsaw Majini |
| 5 | **Ground melee**: Barry Miranda Rights (5,000 or 1,200), Jill Double Knee Drop (1,200), Josh Elbow Drop (1,000-1,200), Sheva Impale (800), Chris Stomp (600) | The enemy is lying down after a knockdown melee, a shotgun blast or an explosion. Stand **over its head** for the critical | Move over the head, **Y** | Usually a kill, +5 s | A Plaga can still emerge |
| 6 | **Front leg / arm melee** (Uppercut, Somersault, Sweep Kick, Tiger Uppercut, etc.) | Leg or arm stun, with the player in front | **Y** | Knockdown, i-frames; chain into row 5 or a gun kill | It is not a kill by itself for most characters |
| 7 | **Licker: knockdown, then Stab** | A Licker on its back after a heart shot | **Y** | Instant kill (800 points) | Licker swarms in vanilla Experimental Facility |
| 8 | **Flash grenade on Plaga forms** | Cephalo, Kipepeo, Bui Kichwa or Duvalia visible | Equip the flash, throw it (ZL + ZR) | Instant kills, 400-900 points each | It blinds the player too, except Chris (Safari) and Wesker [S2] |

**RE5 policy rules** (from sections 4.2 and 5.2, and [S49]-[S52]):
- Every melee kill is +5 s; keep the combo under 10 s; never trade the combo for a melee.
- When the combo window is short, shoot.
- Do not stand still.
- Take crystals (Y) right after a kill.
- Hold bosses until a higher combo bracket only when it is safe.
- Late in the round, keep two enemies alive before each kill.
- Mash A in Dying (solo self-revive); shake the left stick when grabbed.

### 6.3 Open questions to measure live before trusting the tables

1. **RE4 Switch:**
   - Krauser's arm attack button after R (Y or ZR), its exact recharge (45 s or 30 s), and its RAM cooldown and
     ready flag.
   - Whether R does anything for the other characters in Mercenaries.
   - Fix `RELOAD_BTN = "r"` to ZL + B [S37][R2].
2. **RE4:** the combo window (10 s in RAM or 11 s on screen); the grab-escape prompt on Switch; how long the melee
   i-frames last; whether costumes are cosmetic.
3. **RE5 Switch:**
   - The Wesker dash start (R3 or L3 + R3), the Knee Cannon (ZR or Y), direction changes (left stick + B or the right
     stick), the HP cost per dash, and whether he is invincible during the dash.
   - That B runs and turns and ZL + B reloads; which control type is the default; whether Action Assist is on by
     default.
4. **RE5 United:** the leftover-time rate (300/s or 1,000/s); whether Josh, Excella, Barry and Rebecca keep their
   Reunion damage values; how long a Combo Timer lasts; where the enemy stun-state motion ids are, so a bot can see
   "Kneel / Block / Recovering" without waiting for the prompt.

---

## 7. Where sources disagree (index)

### RE4

| Topic | Values and sources |
|---|---|
| Combo window | 11 s [S1][S44]; 10 s, i.e. 300 frames [R3] |
| Bonus Time | 30 s [S1][S44]; 31 s [S45] |
| Castle bonus chests | 3 [S45]; 2 [S44] |
| Krauser arm recharge | 45 s [S1][S9]; about 30 s [S43] |
| Krauser arrows | 30 [S1][S9][S43]; 20 [S41][S44] |
| Wesker's flash grenades | 3, plus 4 hand grenades and 1 incendiary [S1][S8][S43]; "four flash grenades" [S41][S44] |
| Leon's Green Herb | listed by [S41][S44]; not listed by [S1][S43] |
| Speed | Krauser fastest, then Ada [S1][S9]; Ada "the best speed" [S11] |
| First Garrador spawn | by staircase position [S28]; after 25 kills [R3] |

### RE5

| Topic | Values and sources |
|---|---|
| Combo Timer pickup | adds to all other points [S2]; replaces the normal bonus [S46] |
| Sheva Twist Kick / Knee | 250 [S2]; 225 [S47] |
| Sheva Skull Crusher | instant kill [S2]; 3,000 [S47] |
| Sheva Spinning Back Kick | 3,000 [S2]; instant kill [S7] |
| Wesker P8 | x15 [S2]; x21 [S8] |
| Chris (BSAA) M92F and ammo | M92F 20 and shotgun ammo 10 [S2]; M92F 50 and shotgun ammo 30 [S42]; M92F 50/50 live [R1] |
| Sheva VZ61 | 150 [S2]; 260 [S42][S47] |
| Reunion move values, [S3] vs the character pages [S16]-[S19] | Josh: Hammer Blow, Backhand, Iron Tackle, Chokeslam, Dynamite Kick, Elbow Drop. Excella: Slap, Humiliate, Disco Spin, Heel Stomp. Barry: Knee, Burton Boot, Gun Bash, Hurricane, Miranda Rights. Rebecca: Flame Spray, Stun Gun. See 3.3 for each pair of values |
| Wesker dash cost | "a small amount" [S2]; "quite a bit" [S8]; about 15 % [S58] |
| Dash start | R3 [S2][S57]; both sticks [S56][S59] |
| Knee Cannon | the fire button [S2][S56]; Square [S57] |
| Executioner spawns, Public Assembly vanilla | after ~20, 50 and 70 kills [S2]; at 20, 50 and 70 combo [S49] |
| Gatling HP | 8,000-14,000 in the campaign [S23]; 4,000 / 6,000 in Mercenaries [S47] |
| Reaper HP | 2,000-3,000 in the campaign [S24]; 1,500 in Mercenaries [S47] |

---

## 8. Sources

### Official and primary

| Key | Source | URL |
|---|---|---|
| S37 | Capcom, RE4 official web manual, **Nintendo Switch**, English. Pages 6-7 (Controls) are image `.../en/switch/5.jpg`; pages 10-11 (Actions, Game Screen) are `.../en/switch/7.jpg` | https://game.capcom.com/manual/bio4/manual/en/switch/5.html and https://game.capcom.com/manual/bio4/manual/en/switch/7.html (index: https://game.capcom.com/manual/bio4/) |
| S38 | Capcom, RE5 official web manual, PS4, English. Page 1: Controls, Type D default. Page 2: Action Assist, The Mercenaries United, No Mercy | https://game.capcom.com/manual/bio5/manual/en/ps4/1.html and https://game.capcom.com/manual/bio5/manual/en/ps4/2.html |

### Resident Evil Wiki (residentevil.fandom.com, read through its MediaWiki API)

| Key | Page | URL |
|---|---|---|
| S1 | The Mercenaries (RE4) | https://residentevil.fandom.com/wiki/The_Mercenaries_(RE4) |
| S2 | The Mercenaries (RE5) | https://residentevil.fandom.com/wiki/The_Mercenaries_(RE5) |
| S3 | The Mercenaries Reunion | https://residentevil.fandom.com/wiki/The_Mercenaries_Reunion |
| S4 | The Mercenaries United | https://residentevil.fandom.com/wiki/The_Mercenaries_United |
| S5 | Melee | https://residentevil.fandom.com/wiki/Melee |
| S6 | Melee (RE4). Tagged "Unreferenced, August 2026": low reliability | https://residentevil.fandom.com/wiki/Melee_(RE4) |
| S7 | Melee (RE5). Same tag | https://residentevil.fandom.com/wiki/Melee_(RE5) |
| S8 | Albert Wesker/gameplay | https://residentevil.fandom.com/wiki/Albert_Wesker/gameplay |
| S9 | Jack Krauser/gameplay | https://residentevil.fandom.com/wiki/Jack_Krauser/gameplay |
| S10 | HUNK/gameplay | https://residentevil.fandom.com/wiki/HUNK/gameplay |
| S11 | Ada Wong/gameplay | https://residentevil.fandom.com/wiki/Ada_Wong/gameplay |
| S12 | Leon Scott Kennedy/gameplay | https://residentevil.fandom.com/wiki/Leon_Scott_Kennedy/gameplay |
| S13 | Chris Redfield/gameplay | https://residentevil.fandom.com/wiki/Chris_Redfield/gameplay |
| S14 | Jill Valentine/gameplay | https://residentevil.fandom.com/wiki/Jill_Valentine/gameplay |
| S15 | Sheva Alomar/gameplay | https://residentevil.fandom.com/wiki/Sheva_Alomar/gameplay |
| S16 | Excella Gionne/gameplay | https://residentevil.fandom.com/wiki/Excella_Gionne/gameplay |
| S17 | Josh Stone/gameplay | https://residentevil.fandom.com/wiki/Josh_Stone/gameplay |
| S18 | Barry Burton/gameplay | https://residentevil.fandom.com/wiki/Barry_Burton/gameplay |
| S19 | Rebecca Chambers/gameplay | https://residentevil.fandom.com/wiki/Rebecca_Chambers/gameplay |
| S20 | Executioner Majini/gameplay | https://residentevil.fandom.com/wiki/Executioner_Majini/gameplay |
| S21 | Executioner Majini (Red)/gameplay | https://residentevil.fandom.com/wiki/Executioner_Majini_(Red)/gameplay |
| S22 | Chainsaw Majini/gameplay | https://residentevil.fandom.com/wiki/Chainsaw_Majini/gameplay |
| S23 | Gatling Gun Majini | https://residentevil.fandom.com/wiki/Gatling_Gun_Majini |
| S24 | Reaper/gameplay | https://residentevil.fandom.com/wiki/Reaper/gameplay |
| S25 | Giant Majini/gameplay | https://residentevil.fandom.com/wiki/Giant_Majini/gameplay |
| S26 | Big Man Majini/gameplay | https://residentevil.fandom.com/wiki/Big_Man_Majini/gameplay |
| S27 | Licker β/gameplay | https://residentevil.fandom.com/wiki/Licker_%CE%B2/gameplay |
| S28 | Garrador/gameplay | https://residentevil.fandom.com/wiki/Garrador/gameplay |
| S29 | Chainsaw Sisters, and Chainsaw Ganado gameplay | https://residentevil.fandom.com/wiki/Chainsaw_Sisters and https://residentevil.fandom.com/wiki/Chainsaw_Sisters/gameplay |
| S30 | Gatling Man/gameplay | https://residentevil.fandom.com/wiki/Gatling_Man/gameplay |
| S31 | Giant Chainsaw Man/gameplay | https://residentevil.fandom.com/wiki/Giant_Chainsaw_Man/gameplay |
| S32 | Flash Grenade (RE4) and (RE5); Duvalia | https://residentevil.fandom.com/wiki/Flash_Grenade_(RE4), https://residentevil.fandom.com/wiki/Flash_Grenade_(RE5), https://residentevil.fandom.com/wiki/Duvalia |
| S33 | Krauser's Bow | https://residentevil.fandom.com/wiki/Krauser%27s_Bow |
| S34 | Resident Evil 5/gameplay (invincibility frames) | https://residentevil.fandom.com/wiki/Resident_Evil_5/gameplay |
| S35 | Stun Rod (Resident Evil 5) | https://residentevil.fandom.com/wiki/Stun_Rod_(Resident_Evil_5) |
| S36 | Time Bonus | https://residentevil.fandom.com/wiki/Time_Bonus |
| S60 | Control Types (RE5 in-game file) | https://residentevil.fandom.com/wiki/Control_Types |

### StrategyWiki (read through its MediaWiki API)

| Key | Page | URL |
|---|---|---|
| S39 | Resident Evil 5/Controls. Its Switch column is empty | https://strategywiki.org/wiki/Resident_Evil_5/Controls |
| S40 | Resident Evil 4/Controls | https://strategywiki.org/wiki/Resident_Evil_4/Controls |
| S41 | Resident Evil 4/Mercenaries | https://strategywiki.org/wiki/Resident_Evil_4/Mercenaries |
| S42 | Resident Evil 5/The Mercenaries | https://strategywiki.org/wiki/Resident_Evil_5/The_Mercenaries |

### FAQs, guides, TAS and community

| Key | Source | URL |
|---|---|---|
| S43 | Adam Miller ("Mill"), *Resident Evil 4 Mercenaries Walkthrough*, 2005; a GameFAQs-era FAQ hosted by VGM with permission | https://www.video-games-museum.com/en/faqs/GameCube/31688-Resident-Evil-4.pdf |
| S44 | Steam guide for RE4 (2005) Mercenaries, id 234937519; now author-only | https://steamcommunity.com/sharedfiles/filedetails/?id=234937519 |
| S45 | TASVideos 6501S, RE4 Mercenaries Village (Wesker, 210,400) | https://tasvideos.org/6501S |
| S46 | Berserker, RE5 Mercenaries combo / scoring system | http://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-combo.html |
| S47 | Berserker, characters and enemy stat list | http://berserkersblog.blogspot.com/2011/07/resident-evil-5-mercenaries-full-stat.html |
| S48 | Berserker, Wesker damage listing | http://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-wesker.html |
| S49 | Berserker, Public Assembly solo | http://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-public.html |
| S50 | Berserker, The Mines solo | http://berserkersblog.blogspot.com/2011/11/resident-evil-5-mercenaries-mines-solo.html |
| S51 | Berserker, Ship Deck | https://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-ship-deck.html |
| S52 | Berserker, Missile Area | http://berserkersblog.blogspot.com/2012/01/resident-evil-5-mercenaries-missile.html |
| S53 | Berserker, Prison solo | https://berserkersblog.blogspot.com/2012/03/resident-evil-5-mercenaries-prison-solo.html |
| S54 | residentevil.org, "RE5 Mercs Guide" thread | https://residentevil.org/threads/re5-mercs-guide.1347/ |
| S55 | residentevilforums t2261, "RE5 tips and tricks for maxing the score" | https://residentevilforums.forumotion.com/t2261-re5-tips-and-tricks-for-maxing-the-score-on-mercenaries-re5 |
| S56 | Steam RE5 discussion, "WESKER" | https://steamcommunity.com/app/21690/discussions/0/3563973363484602560/ |
| S57 | cheat-database.com, "Mercenaries mode: Wesker's Dash move (PS3)" | http://www.cheat-database.com/display/switch.php?id=83379 |
| S58 | GameFAQs board, "Wesker Dash: how to do it properly". **Search snippet only**: GameFAQs refuses automated fetches | https://gamefaqs.gamespot.com/boards/958470-resident-evil-5/53121867 |
| S59 | Supercheats, Wesker tip. **Search snippet only** (HTTP 403) | https://www.supercheats.com/playstation3/resident-evil-5/2444/wesker/ |

### gBox repo (local; live measurements and earlier research)

| Key | Location |
|---|---|
| R1 | `system/gbox/mercs/titles/re5_switch_brain.py` (`PS3_TO_SWITCH`)<br>`system/gbox/mercs/titles/re5_switch_prompt.py` (`KEYS`; `LABEL_TIME_BONUS = 112`, "press:y")<br>`system/gbox/mercs/titles/re5_switch.py` (`MASH` "Resuscitate", A; `WIGGLE` "Break free"; knife L + ZR)<br>`system/docs/research/re5-switch-ram.md` (United menu path, No Mercy enemy count 40-47, live Chris (BSAA) loadout) |
| R2 | `system/gbox/mercs/titles/re4_switch.py` (`AIM_BTN, FIRE_BTN, RELOAD_BTN = "zl", "zr", "r"`; aim and fire live-confirmed 2026-11-04) |
| R3 | `system/docs/mercenaries_re5_meta.md`, the earlier deep meta doc: RE5 Reunion section 2, RE4 section 7, and its own source list (stv-tribute, kouryakutsushin, RE5 Zone, residentevilforums t3924, TASVideos, Cyberscore) |
