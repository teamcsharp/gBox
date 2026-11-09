# MercMode character replacement: where it stands and the path to finish it (2026-11-09)

For the operator, DeepSeek and any agent picking up a piece. It follows
[the project-manager handover](PROJECT-MANAGER-HANDOVER-2026-11-09.md) and
[the RE6 Switch handover](re6-switch-handover.md); where it disagrees with them, this is newer. Where a live reading
disagrees with this, the live reading wins.

The goal, in the operator's words (2026-11-09): MercMode and the character swapper "fully assembled and working in
mercmode for RE 4/5/6"; "a different mario / sonic character per round"; "the zombies need to be replaced with random
characters from the database"; "instead of building roms over and over and over, I want the system patching a build or
series of builds across titles"; "multiple characters and stages transitioning"; the ROMs "on the lilspark itself so it
is ironclad".

---

## 1. What is proven today

Every line is a live observation on lilspark with its session, or says it is not.

| What | State | Evidence |
|---|---|---|
| Sonic as the player (RE5 Switch, Chris BSAA slot) | live, accepted earlier | build `recovery-sonic-native-grip-v15-20261109`, archive `d96c9c9e…` |
| **Mario as the enemy (RE5 Switch, town Majini)** | **live for the first time** | build `recovery-mario-em10-v1-test-20261109` (uEm10.arc `322c58a1…` + the v15 player archive); session `a66b9d370de14727-98b48cb5b2b74d45` booted first try, 199 kills in 9 min; frames in the artifact store: `ae1cfd35…`, `5d5915e4…`, `a2ae198e…`, `630b28b9…` (real gameplay frames: two textured SM64 DS Marios attacking Sonic) |
| Rounds change stage with no restart | live | same session `…98b48cb5b2b74d45`: Public Assembly, then The Mines (selection job 17:14:15 UTC), then Village (17:17:12), MercMode counting rounds 1 and 2 |
| A round ends by itself after six minutes of play | deployed (`56388d99`), first rounds ended by death before the cap; cap write itself is unit-tested, not yet seen live | `doctrine.ROUND_CAP_S` |
| Mines: bomb 0x10A in every loadout, planted about every 30 s | live | probe on session `…5849b9f202a449ad`: inventory `(0x10a, 5, 5, grid 1)`, four new native `uWp0a` actors in 127 s (gaps 12.9 / 29.2 / 7.7 s), kills 21 to 78; one self-blast cost 350 hp, so the standoff was raised to 15 m afterwards (not re-measured) |
| The bot fights instead of idling | live | before: 10 kills in 183 s, 46 % of the time in a restarted quick turn; after `365ad370`: 26 to 29 kills a minute; one round reached 392 kills / 263,120 |
| Sonic in RE6 Switch (geometry) | live earlier (RE6 handover §2.1) | colours wrong; RE6 stage loads on the Spark were failing at that handover |
| Anything in RE4 Switch | nothing yet | no writer exists |
| Other Sonic-family / Mario-family player slots | offline work in flight (§5) | not booted |
| Enemies other than the town Majini (uEm10) | stock | Village and The Mines draw other classes |

Not proven, and not to be described as done: a different character per round; random zombies; RE6 colours; RE4; the
six-slot cast; any hot swap of an archive inside a running session.

---

## 2. The path

**One tracked overlay per title, filled once, and rounds that pick from it. No ROM is ever rebuilt.**

1. **The build is an overlay, not a ROM.** `switch_mods` keeps a folder of only the changed files per build; Eden lays
   it over the untouched NSP at boot (LayeredFS), ExeFS patches included. That part of the goal already exists and is
   what every result above used. A "series of builds across titles" is a set of such folders, one or a few per title.
2. **A different player character per round = a different roster slot of the same boot.** Each Mercenaries character
   and costume is its own archive. Fill every slot of one overlay with a different donor (RE5: six slots on Switch,
   RE6: 51 body slots) and the bot's ordinary character pick at the menu shows a different character each round, in the
   same session, with no restart. The MercMode queue already carries a character and a stage per entry, and since
   `58006c6f` an entry whose build is the one already loaded plays on in the same session.
3. **Different zombies = several enemy class archives, each a different donor.** A stage draws a handful of enemy
   classes (Public Assembly: uEm10 most, uEm11, plus specials). One donor per class archive gives several characters
   on screen at once. Which archives each stage loads is being read from the RomFS (§5, ticket #9074).
4. **Random zombies per round, without a reboot, depends on one experiment.** Eden keeps the overlay file open and
   reads it from disk on demand (observed: one open handle on the overlay archive, none cached copies). If the game
   re-reads an enemy archive at each stage load, then overwriting that file in place between rounds, same size, shows
   a different donor next round with no restart. Build archives padded to one fixed size per slot so any donor fits.
   **This is untested.** The test: in a probe build, at a round boundary, overwrite `uEm10.arc` in place with another
   donor of the same padded size and look at the next round. If the game caches instead, the fallback is what works
   today: a different build per playlist entry, which costs a ~50 s title restart when the build changes.
5. **Live changes inside a round are RAM, not files.** Fire rate, weapons, loadouts, clock, health already go through
   the live controls. A mesh cannot be swapped mid-round by a file write; if that is wanted later it needs the game's
   resource manager driven from RAM, per title, and is research, not a build step.

Why not "decrypt everything and patch the ROM": the ROMs are already decrypted and broken out on lilspark (§4), and
the overlay gives the same result without ever writing a ROM. Rebuilding ROMs would add minutes per change and remove
the per-file tracking, backups and revert that `switch_mods` has.

### 2a. The random cast (operator, later the same day)

> "I want rounds to alternate who is the zombie and who is the player. I want to see all the different types of
> characters extracted showing up in the game randomly. I want the system able to vary and show multiple different
> characters in a round instead of just one single enemy type. Sometimes I want the player to be Mario and other times,
> Snake or DOA characters. Everyone extracted should be randomly showing up in matches of merc mode across all titles
> and all stages and characters."

What that adds to the path above, and who is on it:

1. **One donor survey for every writer.** The library on lilspark has 1,483 entries; a donor is usable for a title when
   its rig resolves the roles that title's skeleton needs. One shared module answers "which donors, for which title,
   and why not the rest" for the player writers and the enemy writers of all three titles (RE5 player-cast agent;
   ticket #9077 audits the Sonic and Mario families first).
2. **A seeded planner.** `plan(seed, slots or classes, donors)`: no donor twice in one overlay, donors used by the
   last few overlays avoided, an optional filter by franchise. The seed is in the receipt, so a round can be named
   and replayed.
3. **A pool of overlays per title, built ahead.** Each overlay fills every player slot and every enemy class it can
   with different donors (RE5: `cast-pool-NN`, `enemy-pool-NN`; RE6: roster overlays). MercMode's playlist then
   draws (overlay, slot, stage) per round. Inside one overlay a new player character costs nothing (a different
   roster slot); a new overlay costs one title restart, or nothing if the hot swap of §2 item 4 holds.
4. **Several characters in one round.** Two routes, both being built by the RE5 enemy agent: a different donor per
   enemy class archive (works by construction: Public Assembly draws uEm10 and uEm11 together), and different donors
   on different option groups of ONE model, so a single class spawns as several characters. The second depends on
   how a spawn picks its groups, which is not known; candidate `enemy-mix-v1` is the test.
5. **Hero and horde swap sides.** A playlist rule, not a build rule: the franchise that supplied the player last
   round supplies enemies this round, drawn from the pool. It needs item 3 first.

None of 1 to 5 is live. What is live is one donor (SM64 DS Mario) on one enemy class and one donor (SA2 Sonic) in one
player slot.

---

## 3. Are the emulators equipped

| Capability | Eden on lilspark | Note |
|---|---|---|
| File replacement at boot (RomFS overlay) | yes, in daily use | every build above |
| Code patches (ExeFS IPS) | yes, used | the measured uEm11 to uEm10 class rebind |
| Guest memory read / write while running | yes | all bot reading, the live mods, the mine probe |
| Changed file picked up without reboot | unknown | §2 item 4, one experiment |
| Two Switch titles at once on one PC | no | one Switch emulator per PC; RE5, RE6 and RE4 take turns |
| Reliable boot | no | Eden hung black about 2.6 s into boot on 4 of 9 starts on 2026-11-09; the scheduler recovers after ~2 min. Fewer boots is the mitigation (same-session rounds), not a fix |
| RE6 stage loads | failing at the RE6 handover | needs the save moved aside; the path in that handover is wrong (§7) |
| RE4 Switch | boots; bot walks to a round; cannot fight yet | no replacement writer |

Switch 2 titles are out of scope (no emulator for this hardware).

---

## 4. The ROMs on lilspark

Already local, on its own NVMe, none of it on the NAS:

- NSPs: `~/gBox_alt/switch/titles/` (RE4 `010099A00BC1E000`, RE5 `010018100CD46000`, RE6 `01002A000CD48000`) and the
  launch copies under `~/gBox_alt/gbox-cache/<game id>/`.
- Decrypted NCAs: `~/gBox_alt/switch/work/game-<title>-*.nca`.
- Full RomFS break-outs: `~/gBox_alt/switch/romfs/<title>/` (RE5 19 GB / 17,483 files, RE6 18 GB / 60,645, RE4 13 GB / 5,275).
- Asset indexes: `~/gBox_alt/switch/assets/<title>.json`. Keys: `~/gBox_alt/switch/prod.keys`.

What was not ironclad: the library still names the NAS path for each title (`/mnt/gbox/quickswap2/Emulation/_switch/…`),
and every launch asked the share for the file before using the copy it had already staged, so a dropped mount ended
launches with "ROM not reachable" beside a complete local copy. `catalog.local_copy` now stands the staged copy in
when the share does not answer, in the launcher and in MercMode's reachability check (active from the next service
restart). Still to do: (a) mark these folders never-purge in the storage policy; (b) a second copy off the NVMe;
(c) pull the NAS mount once on purpose and watch a launch. Disk: 326 GB free of 3.7 TB.

---

## 5. Work in flight (2026-11-09)

**Agents (each in its own worktree and branch off main `b6015760`, offline only, nothing pushed):**

| Branch / worktree | Task | Delivers into `.scratch-merc-recovery/assets/` |
|---|---|---|
| `wt-re5-cast-20261109` (`C:\_tools\gBox-wt-re5-cast`) | every Sonic donor compared side by side and ranked; six different donors in the six roster slots as one overlay; generic player-slot writer | `cast-a-v1/` |
| `wt-re5-enemy-20261109` | enemy writer for any donor; uEm11 and em1001; two or three enemy-cast overlays; per-stage archive table | `enemy-cast-*-v1/` |
| `wt-re6-switch-20261109` | RE6 colour path (VTF / MVTF), encoders, probe builds, roster skeleton check, small roster | `re6/…` |
| `wt-re4-switch-20261109` | RE4 Switch RomFS map, formats, a native-to-native swap candidate, donor plan | `re4/…` |
| `hermes-collect-20261109` (`C:\_tools\gBox-hermes-collect`) | finished Hermes branches merged and tested on current main, for review before pushing | a branch |

**Hermes / spark2 (tickets first in the queue, lanes raised from 8 to 12):** #9074 stage to enemy archives (RE5),
#9075 enemy archive catalogue (RE5), #9076 player archive catalogue (RE5), #9077 Sonic / Mario donor audit,
#9078 RE6 body and texture archive catalogue, #9079 RE4 RomFS inventory. All are read-and-report tasks that add JSON
and Markdown under `system/docs/research/`; none may change bot code.

**For DeepSeek, if the operator sends them** (each is bounded, with an acceptance test):

1. *Hot-swap experiment and, if it holds, a `switch_mods` op for it.* Probe build `recovery-hotswap-probe-20261109`
   exists (the accepted Sheva-in-Chris archive, 51,175,777 bytes; v15 Sonic is 42,754,831 and fits padded). Boot it,
   overwrite the file in place between rounds, look at the next round. Accept on two frames of one session, before and
   after, with no process restart between them. Then: fixed-size slot padding at build time and an op that refuses a
   write during a round.
2. *The cast playlist.* A generator that turns a registry of accepted (title, build, slot, stage) rows into MercMode
   queue entries: a different character every round, stages in rotation, titles in turn. Accept on a queue that plays
   three rounds with three characters without a restart inside one title.
3. *RE6 on the Spark.* Recover stage loads (the save moved aside at its real path, §7), get the bot through the menus,
   then give each of the RE6 agent's probe builds its live frame. Needs a window when RE5 is not on the emulator.
4. *RE5 enemy classes per stage*, once #9074 is in: tables for the classes Village, The Mines and the rest draw, one
   donor each, live frame per stage.
5. *Navigation by the game's own mesh.* The bot now routes its walking by a learned grid (`re5_switch_nav`); the native
   mesh reader (`re5_switch_native_nav`) only steers it off walls. Route on the native mesh, with the remembered
   ladders and ledges as edges between floors. Accept on a round where the last enemies on another floor are found and
   killed without an operator command.

---

## 6. How MercMode is set right now

- lilspark, RE5 Switch No Mercy only, `repeat_queue`, six entries: Chris (BSAA) on stages 1 to 5 then 0, all on build
  `recovery-mario-em10-v1-test-20261109` (Sonic player, Mario town Majini). One build, so no restart between rounds.
- Rounds: at most six minutes of play (`doctrine.ROUND_CAP_S`), then the clock is cut to five seconds.
- The bot plays by the universal doctrine (`gbox/mercs/core/doctrine.py`): seven goals weighed every half second
  (engage, combo, explore, explosives, interrupt, boss, locate), each a dot on the behavior wheel (`goal_*`), measured
  in the stats as `doctrine_*`. Mines: 15 m from a bomb a Majini can reach, 4 m from one nobody is near.
- To go back to Sonic alone: post the queue of the DeepSeek guide ("MercMode: keep the exact modified build playing").

---

## 7. Corrections to the two handovers

- **PM handover §4.6** called the 10 failing repeat-queue tests noise. They were a real regression: merge `cf0f400f`
  took the RE6 side only for `mercmode.py` and `worker.py` and dropped `repeat_queue`. Restored in `7b96f0b7`. The
  Spark only kept repeating because its share copy predated the merge.
- **PM handover §4.1** ("recipe drift"): there was none. The v15 builder reproduces `d96c9c9e…` on x86; lilspark's
  different bytes are float32 rounding from a different BLAS kernel in the skeleton tables. `re5_sonic_residue`
  settles it (`8587a1bb`); not yet run on lilspark, and the BC7 atlas may still differ there.
- **The mine probe** as handed over could not see a planted mine (it took a unit pointer for a vtable), defaulted to
  a stale worker id, and counted the bomb stack's own dormant unit as a placement. Fixed; it now reads one job a sample
  (`re5_mods op=mine_probe`). Do not leave any probe running across rounds: a worker with a job in flight is "busy" to
  the scheduler and the next round does not start.
- **RE6 handover §5.1**: the save path lacks the user-id directory. The real path is
  `…/eden/nand/user/save/0000000000000000/86D8304D23A3AC808BC2AA4890B84EF9/01002A000CD48000` (its `mv … || true` would
  have done nothing, silently). Its `pkill -f gbox` would also kill the service and anything with gbox in its command
  line; do not run it. A scan on 2026-11-09 found no orphaned Eden process.
- **RE6 handover §2.5** says the Spark's control plane rejects `repeat_queue` and `default_mods`. Since the 16:22 UTC
  restart on `5020b32d` it runs main, which has both.
- **A service restart with a launch queued** left MercMode idle for 15 minutes (the run kept the old worker id).
  Fixed in `7d74b564`.
- **A bot hot reload only tracks modules loaded with the worker.** A module first imported inside a running round is
  never reloaded; a bot change that needs a new symbol from it breaks every tick (it ended a 290-kill round on
  2026-11-09). New shared bot modules must be imported at the top of a module that is loaded at start.

---

## 8. Open problems

1. Eden's black boot (4 of 9). Fewer boots hides it; nothing fixes it yet.
2. The bot still stands more than the doctrine allows: `doctrine_idle_s` ran about 40 % of play in the rounds
   measured, mostly gun-down walking against geometry, the mine cycle's pauses and aim waits. Kills are up ninefold
   but the meter says it is not there.
3. Self-damage from mines: one 350 hp blast seen at the old 8 m; the 15 m rule is not re-measured.
4. 11 RE5 Switch tests, 17 RE6 Switch tests, 3 RE5 PS3 mine tests and 1 tuner test fail on main and did before today.
5. Hermes finishes work that never reaches main (32 branches without a pull request, 136 open pull requests, the
   reviewer cannot read the large bot files). The collect branch above is the first pass.
6. `hermes_work_queue.REPORT_NODE` still names the old spark2 node, so the "RE reports first" rule is dead. Left as it
   is on purpose: turning it back on would move spark2's lanes from tickets to automatic round reports. Operator's call.
