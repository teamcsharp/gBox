# gBox Report — Operator Requests Ledger (PSO autoplay task)

Every request the operator made across the engagement, with status and evidence. Companion to `HANDOFF.md`.

Legend: ✅ done and evidenced · ⚠️ partial · ❌ not done · 🔒 blocked on something external

## A. Core objective

| # | Request | Status | Evidence / note |
|---|---|---|---|
| A1 | Fully decompile and analyse PSO | ✅ | Ghidra: `pso_v3.elf`, 25,980 functions, entry `0x8000c040` |
| A2 | Understand the game deeply (objectives, room-to-room progress) | ⚠️ | entity classes, stage flags, warps, keys and doors decoded; **full level-goal semantics not yet mapped** |
| A3 | Autoplay and speedrun to end credits | ❌ | not reached; see §4 of HANDOFF |
| A4 | Complete the game on Ultimate, sequentially, level to level | ❌ | gated at level 80; character is level 5 |
| A5 | Autoplay without stopping | ✅ | loop relaunches, re-arms, plays, survives session death |
| A6 | Play at the fastest rate | ✅ | measured median 5.54×, peak 7.31× |
| A7 | End state: Forest → Caves → Mines → Ruins, every difficulty | ❌ | this is the north star; only Forest entered so far |
| A8 | Weapon changes every 2–5 minutes | ❌ | not implemented; policy question for PM (§8.4) |

## B. Map and navigation

| # | Request | Status | Evidence |
|---|---|---|---|
| B1 | Analyse, scan, internalise the map | ✅ | city 1,497 tris / 5,626 walkable; Forest 1 **90,986 safe cells**; Forest 2 98,671 |
| B2 | Use the map to path-guide the bot | ✅ | A\* + position-write navigation: **115 → 5.4 units in one call** |
| B3 | Know where elements are and go straight to them (no zigzag) | ✅ (by teleport) | 5 steering algorithms failed on unreliable heading; map+teleport works |
| B4 | Know to go to a button / a box / an enemy | ✅ | classes recognised: `TObjDoorKey`, `TLazerFenceSw`, containers, enemies, `Warp*` |
| B5 | Scan the whole map to pathfind to a destination | ✅ | A\* across the full area (629 waypoints / 1,902 units tested) |
| B6 | Understand what it takes to get there | ⚠️ | keys → doors → warp chain modelled; not yet validated end-to-end |

## C. Combat

| # | Request | Status | Evidence |
|---|---|---|---|
| C1 | Learn and master combat | ✅ (now) | **10 hits, 5 enemies destroyed** in the final driver |
| C2 | Practise on boxes, then move to Boomas | ✅ | 14 boxes destroyed; then Boomas/wolves/flies killed |
| C3 | "If they never swing the sword, they will never learn" | ✅ | 132 swings logged, HP deltas verified |
| C4 | Destroy every enemy | ⚠️ | killing works; not yet exhaustive/unattended |
| C5 | Destroy all boxes | ✅ | 14 destroyed (59 → 45) |
| C6 | Grab all rare items | ⚠️ | rares spawn and drop; **pickup deliberately disabled** per C8 |
| C7 | Destroy floating traps | ✅ (targeted) | `Trap*` classes included in the destructible branch |
| C8 | Never pick up when full; keep inventory empty; no consumables | ✅ | `TItem*` excluded from the reticle rule; bag stays empty |
| C9 | Unlimited scape dolls (no mates/fluids carried) | ✅ | `survival` = permanent Scape Doll; no consumables given |

## D. Recognition and interaction (RAM, not vision)

| # | Request | Status | Evidence |
|---|---|---|---|
| D1 | Detect boxes/enemies via RAM and know which is which | ✅ | entity `kind` + `class` from the profile |
| D2 | Act when the targeting reticle appears | ✅ | reticle rule; `acted on TItemEquipBase (6.9 units)` |
| D3 | Never talk to townsfolk | ✅ | `Npc`/`NPC` excluded by class |
| D4 | Flip switches "with its mind" via RAM | ✅ | `DOOR KEY … detected … going to press it`; flags set + verified |
| D5 | Unlock doors as it walks up to them | ✅ | stage-flag write `0x80515CC8 + floor*32`, verified read-back |
| D6 | Detect the level-exit teleporter and go to it | ⚠️ | `Warp*` family prioritised and approach coded; **entry not yet observed unattended** |
| D7 | De-aggro switch (clickable in gBox) | ❌ 🔒 | field not found; needs enemy-AI decompilation |

## E. Operator control

| # | Request | Status | Evidence |
|---|---|---|---|
| E1 | Take over with a physical controller at any time | ✅ (code) / 🔒 (hardware) | SDL relay → vpad; **130+ units driven by operator**; pads found faulty in test |
| E2 | Bot must yield to the operator | ✅ | `operator-playing.flag`; bot suspends/stands down |
| E3 | Type notes/chat and have the bot act on them immediately | ✅ | `NOTE from operator: kill the wolves` → `note internalized: prioritising enemies` |
| E4 | A text box in the gBox UI for notes | ❌ | file channel proven; UI control not built |

## F. Environment and process

| # | Request | Status | Evidence |
|---|---|---|---|
| F1 | Run locally via gBox; use local GPU/services | ✅ | all work local; gBox/Dolphin local |
| F2 | Keep builds cycling endlessly | ✅ | endless loop with relaunch |
| F3 | Research the game on the internet | ✅ | speedruns, forums, weapon FAQs cited in HANDOFF §10 |
| F4 | Understand weapon nuances and types | ⚠️ | per-item reach/cone decoded from the PMT (13–30 units, 26–45°); **class-specific tactics not yet implemented** |
| F5 | Condense goals and file reports so the PM can find where we went wrong | ✅ | `HANDOFF.md` §5 post-mortem + this ledger |

## Blockers requiring an owner

1. **Character power.** Level 5 / 68 HP against content gated at level 80. Needs sustained kills (see A8/B/C priorities).
2. **Operator hardware.** One pad silent, one with A/B stuck, in testing. Blocks E1 in practice.
3. **De-aggro switch.** Requires locating the enemy AI routine in the decompilation (D7).
4. **Product decision.** Boxes-first (practice) vs enemies-first (levels). Currently boxes win within 60 units.
