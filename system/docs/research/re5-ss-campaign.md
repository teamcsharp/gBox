# RE5 Switch No Mercy: the SS campaign, 2026-11-09

The operator, 2026-11-09: "the goal in RE5 is to get the bot to 400 kills as fast as possible with a combo being
maintained the entire time. I need that to be done faster and faster with the bot auto improving until it has SS rank
on every level for every costume for every character for the entire game."

Branch `wt-ss-campaign-20261109`. What was built: a ledger of every game round (`gbox/mercs/ss_ledger.py`), the board
it adds up to, the results' rank (from the game's own table, and from RAM from now on), an analysis of why he dies with
two bot changes, the tuner's objective changed to the operator's goal, and a MercMode queue planner with the queue
validator fix for the Switch roster.

**What was run and what is inferred.** Run: every number in sections 1, 3 and 5 is computed by this branch's code (or
a short read-only script in the scratchpad) over the live Notebook on the Spark
(`~/gBox/system/gbox-data/mercs/curriculum/010018100CD46000/rounds.sqlite`, 1,693 rows at 23:19 UTC) and its run maps
(`round_maps/010018100CD46000`, 1,351 maps), read with `ssh spark` and nothing written; the rank table is read from
the RE5 Switch main ELF on the Spark (`gbox-data/analysis/switch/re5/re5_switch_main_EBFFDB22.elf`) and the rank code
disassembled there with capstone. Tests: the branch's own and the touched suites (section 9). **Not run**: nothing here
was played in the game; the bot changes (sections 4 and 6) and the RAM rank read are offline-tested only, and they reach
the Spark by the normal deploy - the bot with its next reload or restart, the tuner and the queue validator (both in
the control plane) only after a service restart.

## 1. The board, as of 2026-11-09 23:19 UTC

`python -m gbox.mercs.ss_ledger` (section 7) over the live Notebook and run maps:

```
RE5 Switch No Mercy - the SS board: 1524 game rounds (died 1072, timeout 261, unfinished 188, won 3); 3 won at 400;
SS on 2 of 112 stage x character cells
fastest 400: 20:55 (Public Assembly, Chris (BSAA), max combo 86, score 563,822, rank SS [derived], round 772df2e1)

                         1   2   3   4   5   6   7   8   9  10  11  12  13  14
Public Assembly         SS   B   A  SS   -   D   D   -   D   -   .   .   .   .
The Mines                B   -   -   -   -   -   A   A   -   -   .   .   .   .
Village                  A   -   -   A   -   -   A   -   -   -   .   .   .   .
Ancient Ruins            B   -   -   B   B   -   B   B   -   -   .   .   .   .
Experimental Facility    A   -   -   A   -   -   D   A   -   -   .   .   .   .
Missile Area             A   -   -   B   D   -   B   C   -   -   .   .   .   .
Ship Deck                D   D   -   -   -   -   B   -   -   -   .   .   .   .
Prison                   C   -   -   S   -   -   -   -   -   -   .   .   .   .
   1=Chris BSAA  2=Chris Saf  3=Chris STARS  4=Sheva BSAA  5=Sheva Club  6=Sheva Trib  7=Jill BSAA  8=Jill Btl
   9=Wesker Mid  10=Wesker STARS  11=Josh BSAA  12=Excella  13=Barry STARS  14=Rebecca STARS
```

The three wins (all Public Assembly; real play seconds from the first playing tick to the 400th kill, pauses out):

| ended (UTC) | round | character | play to 400 | max combo | combo breaks | score | rank | fragments |
|---|---|---|---|---|---|---|---|---|
| 10-31 17:01 | bcc39e69 | Sheva (BSAA) | 23:03 | 77 | - | 515,071 | SS (derived) | 3 |
| 11-09 20:45 | 772df2e1 | Chris (BSAA) | **20:55** | 86 | 21 | 563,822 | SS (derived) | 2 |
| 11-09 22:13 | 5b2ac874 | Chris (BSAA) | 20:58 | 40 | 34 | 499,288 | SS (derived; the operator saw SS) | 2 |

So tonight's win was not the first: the ledger finds one on 10-31 (Sheva (BSAA), three 10-minute evidence fragments
with the game paused between them; the row of the win itself names neither stage nor character). Nearest misses: Prison
/ Sheva (BSAA) S (389 kills, 378,110), Public Assembly / Chris (STARS) A (398 kills), The Mines / Sheva (BSAA) 350 kills
with a 173 combo at 23:16 tonight (397,860 - died). Columns 11-14 are empty: **the bot has never played the select's
second page** (`gbox-data/mercs/re5-switch-cycle.json`: `character_slots` 0, characters counted 0-9 only). 237 game
rounds of 10-27 to 10-31 name neither stage nor character (159 of them the 120-second timeouts of the first days):
they count in the totals, not on the grid.

## 2. What a round is, and what the ledger records

**A Notebook row is an evidence fragment, not a round.** A bot reload, a stopped autoplay or a lost read closes the
evidence ("interrupted", "lost", "ended") while the game plays on, and the next `play_round` opens a new row in the
middle of the round. Both 400-kill wins tonight are the second fragment of their round (a42dda7d at 393 kills, then
5b2ac874; b28ea396 at 275, then 772df2e1), and the second fragment's row names neither the stage nor the character
because it never saw the selects - that is the "unknown" the win showed. `ss_ledger.stitch` joins a non-terminal
fragment to the next fragment of the same session that starts at its kills (the run map's first clock row, or the
bot's new `ss_t0_kills`), else one starting within 180 s. Of the 1,524 game rounds in the 1,693 rows, 100 have 2
fragments and 30 have 3 or more.

Per game round: stage name, character (inherited across fragments), outcome (`won` = 400 and the results; `timeout`
= the clock ran out, results and a rank; `died`; `unfinished` = the evidence stopped and nothing followed), kills,
score, max combo, combo breaks (the bot's `round_combo_breaks`, summed), deaths, dying episodes, holds, heals, real play
seconds and the time to 400, the rank, and what the tuner needs (`tuning`: each fragment's version and tuning_params).

**Stage names.** `rounds.stage` is the stage's navigation signature. Over the 582 rows that carry both it and the
cycle-confirmed `data.stage`, each signature appears with exactly one name (`ss_ledger.SIGNATURES`):

| signature | stage |
|---|---|
| 1636-2187-d3a75164ca01dcaa-e1163f7867c9 | Public Assembly |
| 1152-1565-d7cf9f4b54c4a7fb-1624cb963fc4 | The Mines |
| 1186-1572-0b4558ee57f63925-594262a20d44 | Village |
| 907-1033-cb4639c6c8490575-e18ef1ac1659 | Ancient Ruins |
| 754-906-9c9fd6b418e2f567-8ff65fd20a50 | Experimental Facility |
| 1350-1664-ff6314937b448650-a383d0a7b930 | Missile Area |
| 1411-1783-0e2aca27a1246fdf-8120ec8d2f85 | Ship Deck |
| 1411-1725-7fee6ff36812b399-0fb005b38d0c | Prison |

**The character capture fix** (`RE5Switch._identity`, every playing tick): a fragment with no confirmed character takes
the cycle's last confirmed start (persisted in the cycle file) when its stage agrees with the signature and the player
object's RAM class is of that character (`uPl00Chris...`, `uPl01Sheba...`: `PLAYER_FAMILIES`), else the class's
character alone ("Chris"); a confirmed character is never replaced. The stage comes from the signature (which also
corrects a stage left over from another round). `player_class`, `ss_stage_source` and `ss_character_source` say where
each came from. The costume is not in the class number; the full class string is recorded so it can be mapped later.

**Real play seconds.** From now on the bot keeps its own round clock (`ss_ledger.RoundClock`, fed by
`RE5Switch.screen` on every tick): wall seconds of the playing ticks from the round's first; a gap over 1 s counts for
as much as the game's own clock fell over it (the round clock counts real time and stops in a pause or a frozen read),
so a pause adds nothing; it carries over a fragment boundary (one round = one player object of one boot) and survives a
bot reload (`RELOAD_KEEP`). Stats `ss_round_play_s`, `ss_fragment_play_s`, `ss_t0_kills`, `ss_t0_timer`,
`ss_kill400_s` (at the 400th kill: the results come up on it), `ss_round_key`. For the old rows the ledger uses the run
maps (the 5 Hz samples' intervals, each at most 2.5 s, and the clock's fall between fragments), else `explore_seconds`;
`time_source` says which. 1,219 rounds are timed by their run maps.

## 3. The rank: the game's own No Mercy table, and where it sits in RAM

Static analysis of main (build EBFFDB22..., the ELF on the Spark): main+0x17C1B7C holds three rows of six s32
thresholds (stride 0x18), each SS, S, A, B, C, D:

| row | SS | S | A | B | C | D |
|---|---|---|---|---|---|---|
| 0 (solo; the guides' table) | 90,000 | 60,000 | 40,000 | 20,000 | 10,000 | 0 |
| 1 (duo; the guides' table) | 150,000 | 120,000 | 80,000 | 40,000 | 20,000 | 0 |
| **2 (No Mercy)** | **400,000** | **300,000** | **150,000** | **60,000** | **30,000** | 0 |

The rank code at main+0xECD38: `ldrb w10, [cGameSys, #0xA76]; cmp w10, #0; mov w10, #2; csel w20, wzr, w10, eq` -
cGameSys +0xA76 is the No Mercy flag (re5_switch's split-screen notes), so No Mercy takes row 2. It adds the pending
+0x958 to the score (+0x990), walks the row down, and stores the rank index (0 SS ... 5 D) at **cGameSys +0x994** and
the exchange points (main+0x17C1BC4: 5,000 / 3,000 / 1,500 / 1,000 / 600 / 200) at +0x998. A non-zero +0xA7C takes
another path (rank = 5 - that value); not seen yet.

The board's ranks are **derived** from the final score with row 2 and marked `derived`. The night's win agrees (499,288:
SS). From the next round on, the driver reads +0x994 and +0xA76 at the results (phase over) beside the score
(`result_rank_ram`, `result_rank_derived`, `result_rank_source`), and `result_rank` - the Notebook's observed rank - is
set only when the two agree (`result_rank_verified`); the board then marks the rank `ram`. **Still to see live**: one
results screen between 90,000 and 400,000 points (a 393-kill timeout at ~254,000 must read A, not SS) - it settles
both the row choice and the offset. A death has no results screen: no rank (the guides' rule; the ledger gives none).

## 4. A bug the ledger turned up: the bot learned every stage under another stage's name

`Bot._new_round` asked `stage_target()` for the stage's tuning, learned grid and remembered doors - but by the round's
first tick the cycle has already drawn the NEXT round's target (and the unmanaged cycle never draws the stage just
played). The rows show it: **1,257 of the 1,308 rows that name both carry a `tuning_stage` they were not played on
(96 %)**. So the per-stage tuning, the occupancy grid (`nav_grids/<stage>.json`), the doors "seen here before"
(`door_spots.json`) and the dead-end notes the tuner's avoid spots come from were all another stage's - the live
`tuning.json` has avoid spots on every stage built from such notes (coordinates like (-5942, -21529) on Public
Assembly), and the night's win played with Ship Deck's tuning. Changed:

- `Bot._stage_now`: the stage this round is played on (the driver's `ss_stage`: the signature, else the selects);
  `_stage_learning` puts that stage's tuning, grid and doors in force; `_stage_sync` re-applies once the signature reads.
- The grid and the doors live under `STAGE_KEY` ("<stage>#round"); the old entries are left unread.
- `tuning.STAGE_V` (RE5 Switch: 2): dead-end notes carry `stage_v`, the tuner counts only those, writes `avoid_v`, and
  `apply()` steers by avoid spots only from a file of that version; the tuner drops the per-stage overrides, avoid spots
  and per-stage trials made under the old key once (log status `migrated`), keeping the pooled values.
- `re5_switch_mines.BLAST_CM` tuning bounds 1500-2000 cm: the old 800-1200 left **9 m in force on two stages** (the
  live file: Ship Deck and The Mines) after the operator's 15 m standoff; a tuned value can no longer go under 15 m.

## 5. Why he dies, and why the rounds that get far do not finish

**Deaths since 11-03 (270; the current bot family) and tonight since 17:00 UTC (13).** Kills at death: median 51
(p25 26, p75 78); tonight median 89 (73-103).

| measure | since 11-03 | tonight |
|---|---|---|
| the round ended held or dying (`combat_reason` dying / prompt dying / motion) | 191 / 270 (71 %) | 10 / 13 (77 %) |
| no heal left at the end (`heal_status` "critical retreat ... (no heals)") | 183 / 270 (68 %) | 9 / 13 (69 %) |
| no heal used in the round | 182 / 270 (67 %) | 9 / 13 |
| two or more dying episodes in the round (`round_dying`) | 189 / 270 (70 %), mean 2.56 | 10 / 13, mean 3.62 |
| health lost inside his own bombs' blast windows (`round_mine_blast_hp_loss` > 0) | 11 / 270 (4 %), 4,183 hp | **6 / 13 (46 %), 2,587 hp** (up to 1,545 in one) |
| the bomb guard's last word "in the blast and a close Majini first: the gun up" | 73 / 270 (27 %) | 1 / 13 |
| `crowd_max` (Majini near him at once), median | 11 | 9 |

From the 79 deaths with a run map death record: 7 Majini within 3 m at the death (median; 3+ in 86 %); 70 % were already
at 3 hp or less 10 s before (dying, or revived at a few hp); only 8 % were killed outright from 700+ hp; 64 of 79 were
held at the end. Over the 9,522 hits in the run maps since 11-03 (1,386,181 hp): **87 % of the health lost was lost with
3+ Majini within 6 m**; of the 361 hits of 400+, 49 % landed while he was held with 3+ near; by what he was doing,
quick turn 28 %, aim 21 %, held 14 %, mine 13 %, heal 11 %, walk 6 %. Where: deaths spread over each stage; two hot
spots stand out - Missile Area, 7 of its 12 mapped deaths within 5 m of (-62, -215) m, and Prison, 6 of 12 within 5 m of
the spawn (0, 0).

**The top three, as the bot experiences them:**

1. **Swarmed and held.** He goes down in the crowd: held (a Majini holds him for another's swing), the dying state,
   revived at 1-3 hp, down again. The grenade burst that exists never fires there: it needs a verified firing
   follow-through, and the gun is down while he is held, healing or running.
2. **Nothing left to heal with.** 68 % of the deaths came with no heal item left; the existing answer is a 1.2 s run
   ("critical retreat"), which the crowd follows.
3. **His own bombs.** Since bombs are "always planted" (today 12:18 local), 6 of tonight's 13 deaths lost health inside
   his own bombs' blast windows; the guard gives up the run out of the blast when a Majini is within 3 m ("the gun
   up"), which is what the operator's "flashbanging and running away" answers.

**What changed (implemented, offline-tested; the operator's rules kept - never standing, never holding fire, the mines
untouched):** `CRIT_FLASH` (`re5_switch.Bot._critical_flash`): one native flash - the same native spawn the mine flash
and the operator's flashbang use, which stuns every Majini around him, the one holding him included
(docs/research/re5-native-flash.md) - when he is held with another Majini within 3 m, at 30 % health or less with two
within 3 m, or the moment the bomb guard gives up the run for a close Majini; at most every 4 s; never while dying (the
native controller refuses a dying player: "Unavailable: player is dying or dead"). It is a side effect like the grenade
burst: the tick's pad action is unchanged. A confirmed flash gives the bomb guard `FLASH_S` (3.5 s) of reeling Majini,
and the guard (`re5_switch_mines._clear`) then runs him out of the blast instead of fighting inside it; unconfirmed, the
guard behaves as before. Stats `crit_flashes` (confirmed), `crit_flash_requests`, `crit_flash_reason`, both per round
(`round_crit_flashes`). The native flash is assistance like the other mods; turn it off with `CRIT_FLASH = False`.

**The rounds that get far do not die - they cannot find the last Majini.** Tonight every round that reached 380 kills
spent the end hunting:

| round | 380 kills at | then | the end |
|---|---|---|---|
| 772df2e1 (won) | 227 s into its 2nd fragment | 395 at 324 s, 399 at 672 s | 400 at ~702 s: the last 20 kills 475 s, the last 5 378 s |
| 5b2ac874 (won) | 1,008 s | 393 at 1,115 s, 2nd fragment 395 at +51 s | 400 at +141 s: the last 20 ~250 s |
| 305d111f | 720 s | 391 at 758 s | **640 s more without a kill: lost** |
| 5f90031c | 1,099 s | 398 at 1,166 s | **~630 s more without a kill: lost** |
| 5c80e6bc | 765 s | 393 at 839 s | **~500 s without a kill: the clock ran out** |
| 63ca2900 | 258 s | 393 at 297 s | the clock cut from 1,329 s to 0.3 in a second: the 6-minute round cap live that hour (since removed: "no round cap") |

After kill 380 his time went to walking (the hunt, "hunt: the nearest 28-39 m", "wall: returning along an observed
movement segment") and to the bomb guard ("in his own bomb's blast: out before it detonates", over and over with nobody
near: 95-123 s a round). That is the single biggest lever on time to 400 - both wins lost a fifth to two fifths of
their time there, and three near-misses lost the win to it.

**Proposed, not implemented** (each touches navigation or the mine rules the operator owns; each is measurable on the
ledger by time from kill 380 to 400):

- the endgame hunt: with few alive (the census says where every one is), route to the nearest by the stage's own nav
  mesh and its action links, and treat a hunt that gains no ground for N s as a dead end to route around;
- a quiet bomb on his hunt route (no Majini within 8 m of it): walk past it rather than turn back (today's guard turns
  him back after 4 s beside one), or no new bomb on the trail once only a handful are left - the operator's call;
- heal supply: pick up the herbs and sprays the Majini drop when the census is clear (no pickup is taken today:
  `prompts_seen_pickup` 0 in the win), so the second cause has an answer besides running;
- the Missile Area (-62, -215) and Prison spawn hot spots: look at the frames of those deaths.

## 6. The objective the tuner learns on

`gbox/mercs/tuner.py` `OBJECTIVES` (RE5 Switch): a numeric trial (the pooled constants: RELOC_CROWD_N, HEAL_CRITICAL,
BEHIND_R, BLAST_CM) is judged on the ledger's game rounds by `ss_ledger.round_cost` (seconds, lower is better):

- won: its seconds to 400;
- not won: the projected time to 400 at its pace (play_s x 400 / kills) + `NOT_WON_S` 2,400 + `SHORT_S` 10 per kill short
  of 400, and a death `DEATH_S` 1,800 more - any win beats any loss, a death costs more than the same round run out of
  time, dying at 135 kills beats dying at 50;
- every round: + `COMBO_BREAK_S` 10 per combo break, - 0.5 s per step of max combo (at most 60 s).

Judged **per stage**: each trial round's cost over its own stage's mean cost before the trial (the last 10 judged rounds
of each stage), the ratios pooled over every stage - so the trial confirms on a day's rounds, not a stage's handful.
Kept unless the mean ratio is more than 10 % (`WORSE`) above 1; **reverted** (and that constant blocked 24 h) when it
is, or when deaths per round rose more than 0.25 over the baseline's (the hard penalty). Confirmed by **6** game rounds
that played the trial's value; expired after 30 judged rounds without them, or 72 h. The rules' cause metrics still
pick which constant to try. Today's per-stage baselines (mean cost of the last 80 judged rounds): Public Assembly
5,890 s (45 rounds), Experimental Facility 6,306, Village 7,347, The Mines 7,982, Missile Area 8,251, Ancient Ruins
8,329, Prison 9,610, Ship Deck 10,264; the two wins cost 1,422 and 1,578.

**Why the old trials expired unconfirmed**: a round confirmed a trial only when it carried the tuning file's version, and
the per-stage avoid trials rewrote the file - a new version - every few minutes, so no round ever carried a numeric
trial's version ("0 of 8 rounds confirmed it in time", every pooled trial of the day). Every numeric trial (every title)
is now confirmed by the value a round played (its `tuning_params`, `tuning.in_force`).

The code-change gate (`gbox/mercs/gate.py`, the auto-revert of a bot PR by score and kills per minute) is unchanged.

## 7. How to read the board

```
python -m gbox.mercs.ss_ledger                        # the board (the Notebook and run maps under gbox-data)
python -m gbox.mercs.ss_ledger --rounds 20            # ... and the last 20 game rounds
python -m gbox.mercs.ss_ledger --plan re5_stock       # ... and the next MercMode queue with that build
python -m gbox.mercs.ss_ledger --json                 # every round and cell as JSON
python -m gbox.mercs.ss_ledger --db rounds.sqlite --maps round_maps/010018100CD46000   # another copy
```

The grid shows each stage x character's best rank: `SS`..`D`, `-` played but no rank yet (every round died or did not
finish), `.` never played. The table under it: tries (game rounds), wins (400), died, best rank, best score, best kills,
best time to 400 (m:ss of real play). A rank is `ram` (the results screen's, read and agreeing with the score's table) or
`derived`; a time is `bot clock`, `run map` or `run capture` (`--rounds` and `--json` say which). "SS on N of 112" is
the operator's goal: 8 stages x the 14 names of the select (more if the second page holds more; such an entry shows as
"character N").

## 8. The coverage planner and the queue

`ss_ledger.plan_queue(board, build, n=20)` returns the next MercMode queue entries (`{"title": "re5", "mode":
"no_mercy", "character", "stage"(, "mod": build)}`): the pairs without SS first, the least-tried first (never, 1-2,
3-9, 10+ tries) and the nearest to SS inside a tier; then the SS pairs, the slowest time to 400 first. Each pick is the
pair whose stage and character the plan has used least, never the stage or the character of the entry before it. A
character with no round on the board at all is a **probe**, at most once per plan: the select's second page has never
been reached, so four rounds find out whether it can be, not twenty. Tonight's plan opens Josh (BSAA) / Public
Assembly, Excella / The Mines, Barry (STARS) / Village, Rebecca (STARS) / Ancient Ruins, then Jill (BSAA) / Prison,
Wesker (STARS) / Experimental Facility, Wesker (Midnight) / Missile Area ... (`--plan`). To play it, the queue goes into
the host's MercMode settings with `repeat_queue` (POST /api/mercmode `{"host": ..., "queue": [...], "repeat_queue":
true}`); regenerate it as the board fills.

**The validator fix** (`gbox/mercmode.py`): `catalog(cfg)` / `queue_entry(entry, cfg)` / `resolve_selection(entry, rng,
cfg)` take the host's settings; where `preferred_editions` makes RE5 the Switch No Mercy edition, RE5's first mode is
`no_mercy` with `re5_switch.CHARACTERS` (all 14), and a random mode is `no_mercy`. The PS3 rosters stay valid so a stored
queue still reads. **It is control-plane code: in force after a service restart.**

## 9. What the operator should expect

- The next rounds carry `ss_*`, `player_class`, the stage and character sources, and at the results `result_rank_ram`;
  the first results screen settles the RAM rank (section 3). Rows from before stay as the ledger reconstructs them.
- The bot's learning starts clean per stage: the grid and the doors fill again under the round's own stage, the old
  per-stage tuning and avoid spots are dropped once (`tuning-log.jsonl` status `migrated`); the pooled values stay.
- `crit_flashes` per round: a flash when he is held in a crowd or low with two on him. Expect fewer "held" deaths; the
  measure is deaths per round and kills at death on the board. Flashes the native controller refuses ("awaits recovery
  after an uncertain operation") cost nothing but a request.
- Tuner trials on RE5 Switch (after the service restart) confirm on about six game rounds - a few hours of MercMode -
  and keep or revert on the goal; the first pass drops the old per-stage tuning once (`migrated`).
- The first four queued rounds of a plan test the second page; if the walk cannot reach it the round plays the entry
  the cursor stops on, and the ledger records the character that was actually played.
- The time to 400 will not fall much until the endgame hunt (section 5) is fixed: today the last 20 kills cost 4-8
  minutes when he finds them, and the round when he does not.

Commits: a795c231 (the ledger), 94e6ea44 (the bot: identity, clock, rank, stage key, CRIT_FLASH), ec6c2d54 (the tuner),
4070f866 (the queue validator), 96952009 (the planner's probes), 2a2401ef (this document), 5a2fdb58 (a round's
identity carries the player object's generation). Tests: `tests/test_re5_ss_ledger.py` (15),
`tests/test_re5_switch_ss_campaign.py` (7), `tests/test_mercs_tuner.py` (15, the pooled-trial test that was red on main
now expects the pooled file), `tests/test_mercmode.py::test_dj_queue_takes_the_switch_no_mercy_roster_when_re5_means_switch`;
the RE5 Switch, tuner, learning and MercMode suites pass but for the 11 known-red RE5 tests (bonus, bonus_giveup,
rampage, smooth, threat).
