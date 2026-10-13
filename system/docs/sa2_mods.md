# Sonic Adventure 2: finish the stage, A rank, all emblems (`sonic_adventure_2`, #217)

`gbox/sa2_mods.py` gives the agent one tool for Sonic Adventure 2 on a live session:

| op | what it does | proof in the result |
| --- | --- | --- |
| `finish_level` | ends the current stage now. The game itself clears it, and its results screen grades and saves the mission that was being played. | `finished`, `verified` (LevelCleared read back as 1, mission and rings read back as they were) |
| `rank rank=A` | finishes the stage with an A. "S rank" means A, because SA2's grades are E D C B A. `finish=false` only writes the score or clock. | `grade_now` (the grade the results screen gives for the values read back), `codes` |
| `emblems` (`count=0` = all) | marks every missing emblem as earned in the save in RAM and sets EmblemCount to the game's own recount. The memory card or VMU gets it the next time the game saves. | `emblems`, `verified` |
| `status` | stage, character, mission, score, time, rings, lives, emblems (count, earned/180), LevelCleared, the grade the results screen would give now, and whether `finish_level` can run | read only |

The agent prompt sends "skip to the end of this level", "give me an S rank" and "give me all the emblems" straight to
this tool for both owned builds (`d95ed7ed1e40552a`, Dreamcast USA; `732106c0ef8df816`, GameCube USA). It skips the
cheat database and web search. Other regions are refused with a gap note. Each build is checked first: City Escape's
rank-table row must be at the build's address, and on GameCube the disc id must be `GSNE8P`.

## How "finish" works (no code patch, no foreign call)

Every frame the game's main loop runs the "collect 100 rings" mission check:

```
if (MissionNum == 1 && !TwoPlayerMode && (CurrentLevel <= 46 /* GC: 60 */ || CurrentLevel == 70)
    && Rings[0] >= 100 && !LevelCleared)
    AwardWin(0);
```

`AwardWin(0)` is the same level-clear that the goal ring and the emerald hunts call. It stops the timer, sets
LevelCleared and starts the win pose and the results. gBox sets MissionNum = 1 and Rings = 100, then polls
LevelCleared (every 20 ms, up to `timeout_s`, default 3 s). It then writes the real mission number and ring count
back before the results screen reads them. If the game is paused or not in a stage, nothing fires within the timeout:
the values are put back and the result says why. The check does not cover boss fights 60+ (Big Foot ... Finalhazard),
kart races, 2P battles or Chao World, so these are refused. Boss fights with ids up to 46 (Sonic vs. Shadow,
Tails vs. Eggman, Knuckles vs. Rouge) go through the same check, and the result marks them "untested".

A CodeBreaker or Gecko code cannot do this. A constant "mission 2 + 100 rings" code would end every stage as mission 2.

## How the A rank is set

The results screen grades every stage from the per-level rank tables. These tables are identical in both builds:

* Missions 1, 4 and 5 are graded on score. The screen takes (Score + time bonus) / 100 and compares it with
  `{s16 level, D, C, B, A}` from Mission1/4/5Scores. The time bonus is 10000 - 20 x (seconds - 60), with a floor of 0.
  If Rings >= PerfectRings, the grade is A outright.
* Missions 2 and 3 are graded on the clock. The screen takes min x 60 + sec (+1 if frames > 0) and compares it with
  `{u8 level, 4 x {min, sec}}` from Mission2/3Times.

`op=rank` first finishes the stage, which stops the timer. On a score mission it then writes Score = A x 100. On a
time mission it writes the clock as A - 1 s. The game's own grading then gives an A and saves it, along with the
emblem. Route 101/280, bosses and races have no such table, so they are refused.

## How emblems are counted

The game recounts EmblemCount from the save itself. Both builds have a recount routine that walks the same 180 bytes:

* 29 action stages x 5 missions. The stage list is identical in both builds: `13 10 3 28 22 30 9 17 23 24 16 5 7 25
  32 14 4 6 40 11 21 27 12 43 18 26 8 44 34`, and all of Cannon's Core saves under 34. A rank byte that is not zero
  counts. The results save writes rank + 1, so 1 = E ... 5 = A.
* Route 101 and Route 280, 5 missions each.
* 25 one-byte flags: 3 kart race emblems (13-byte kart records, flag at +12) and 22 others (boss attack and chao race
  emblems; the exact meaning of each byte is not mapped).

`op=emblems` writes 5 (A) into each missing rank byte and 1 into each missing flag, then sets EmblemCount to the
recount. It leaves ranks that are already earned alone. At 180 emblems the game's unlock check opens Green Hill.

## Addresses

### Dreamcast USA (`1ST_READ.BIN` sha1 `0817898aac799a8de5e8a9021d817bd7ef33a9e3`, loaded at 0x8C010000)

Source: SH-4 disassembly of the operator's disc, cross-checked against the published CodeBreaker (USA) raw codes at
almarsguides.com. In those codes `0TAAAAAA VVVVVVVV` means T = 0/1/2 for an 8/16/32-bit write at 0x8C000000 + AAAAAA.
`gbox/cheats.py` previously read T from the first nibble, which turned "Max Score" into an 8-bit write. This change
fixes that.

| field | address | type | evidence |
| --- | --- | --- | --- |
| global block G | 0x8C0DB20C | | timer tick 0x8C052BDC (`mov.l @(PC)` literal) |
| TimerStopped | G+0x1A = 0x8C0DB226 | u8 | TimerStart 0x8C052BCC / TimerStop 0x8C052BD4 |
| minutes / seconds / frames | 0x8C0DB227 / 228 / 229 | s8 | tick; CodeBreaker "Stop Timer" `01052C18 0009` nops the seconds store at 0x8C052C18 |
| TwoPlayerMode | 0x8C0DB22A | s8 | 100-ring check, AwardWin |
| MissionNum (0-based) | 0x8C0DB22E | s8 | 100-ring check `== 1`; grading `== 3 / 4` picks Mission4/5Scores |
| CurrentLevelRank (0..4) | 0x8C0DB24E | s8 | written by both grading functions (G+0x42) |
| LevelCleared | 0x8C0DB24F | s8 | AwardWin 0x8C027E40 sets it; the 100-ring check tests it |
| Lives | 0x8C0DB26C | s16[2] | GetLives 0x8C052BC0; CodeBreaker `010DB26C` |
| Rings | 0x8C0DB270 | s16[2] | CodeBreaker `010DB270 03E7`; the grading compares it with PerfectRings 0x8C0DB276 |
| Score | 0x8C0DB294 | s32 | CodeBreaker `020DB294 05F5E0FF`; score grading 0x8C054350 reads G+0x88 |
| GameState | 0x8C24EE60 | s16 | 3 at level load (0x8C023EE0), compared with 16 / 17 (the PC enum: in game / paused) |
| CurrentLevel | 0x8C24EE64 | s16 | CodeBreaker "Level Modifier" `0024EE64`; compared with 35..38, 70, 90 |
| CurrentCharacter | 0x8C24EE6C | s32 | CodeBreaker "Always Tails" `0124EE6C 0006`; the level loader compares it with 6 / 7 |
| AwardWin(player) | 0x8C027E40 | code | callers: the 100-ring check 0x8C026A2A, the emerald hunt 0x8C0860B2, 0x8C047C74 / 0x8C048888 |
| rank tables | Mission1/4/5Scores 0x8C0E5ABC / 5BEA / 5D18, Mission2/3Times 0x8C0E5E46 / 5F79 | | grading 0x8C0543E8 / 0x8C054FE8 |
| save (RAM) | 0x8C26A664 | | EMBLEMGET overlay (0x8C500000) reads +0x0D; play-time-to-180 counter 0x8C0BC960 |
| EmblemCount | 0x8C26A671 | u8 | recount loop 0x8C0BC5A0..0x8C0BC872 (180 -> unlock 98) |
| mission ranks | save+0x6C + level x 0x88 + mission | u8 | results save 0x8C0BB7E0 / 0x8C0BBD0A |
| Route 101 / 280 | save+0x18DC / +0x1964 | u8 x 5 | same |
| other emblem flags | save+0x1BAC (10), kart save+0x19F8 + 13i (3), save+0x1E14 (12) | u8 | recount loop |

### GameCube USA (SA2 Battle `GSNE8P`, main.dol from the operator's disc)

Source: PowerPC disassembly. The global block has the same layout as the PC port's (X-Hax sa2-mod-loader
`SA2Variables.h`, PC 0x174AFC0 = GC 0x801CC168). The save matches the PC `SaveData`: Levels at +0x38, 0xC4 bytes each.

| field | address | type | evidence |
| --- | --- | --- | --- |
| global block G | 0x801CC168 | | time grading 0x8005FFE8, score grading 0x80060F84 (`lis 0x801D; addi -0x3E98`) |
| TimerStopped / min / sec / frames | 0x801CC182 / 183 / 184 / 185 | | grading reads +0x1B..+0x1D |
| TwoPlayerMode / MissionNum | 0x801CC186 / 0x801CC18B | s8 | 100-ring check 0x8001E57C |
| CurrentLevelRank / LevelCleared | 0x801CC1A9 / 0x801CC1AA | s8 | `stbu r0,0x41(G)`; AwardWin 0x8001C810 returns early if +0x42 is set |
| Lives / Rings / PerfectRings | 0x801CC1CC / 0x801CC1D0 / 0x801CC1D6 | s16 | score grading |
| Score | 0x801CC1F8 | s32 | `lwz r0,0x90(G)` in the score grading |
| GameState / CurrentLevel / CurrentCharacter | 0x803AD81A / 0x803AD820 / 0x803AD828 | s16 / s16 / s32 | r13 = 0x803B52C0 (`__init_registers` 0x80003264); -0x7AA6 compared with 16, -0x7AA0 with 60 / 70, -0x7A98 with 6 / 7 |
| rank tables | 0x801B34C8 / 35F8 / 3728, times 0x801B3858 / 398C | | same data as the Dreamcast |
| save | 0x801F2340 (0x801E7820 + 0x10000 - 0x54E0) | | recount 0x80057EB4..0x8005A4B4 |
| EmblemCount | 0x801F234D | u8 | compared with 180 -> unlock 0x62 |
| mission ranks | save+0x38 + level x 0xC4 + mission | u8 | recount (stage list 0x801B33E8) |
| Route 101 / 280 | save+0x2E28 / +0x2EEC | u8 x 5 | recount |
| other emblem flags | save+0x3224 (5), +0x3231 (4), kart +0x2FBC + 13i (3), +0x348D (13) | u8 | recount |

Gecko equivalents use `00/02/04AAAAAA` for 8/16/32-bit writes (`cheats op=add`). The result's `codes` lists them for
rank and small emblem writes.

Confidence: Dreamcast is high. The globals are tied to code and to three published codes. GameCube is high for the
global block and save, and medium for GameState / CurrentLevel / CurrentCharacter, which are SDA reads matched by
their use. Neither build is live-checked yet, so `live_checked: False`.

## Live check (maintainer; agent-owned session only, never the operator's)

Run each step with `run_tool sonic_adventure_2` (or the chat) on a session that the agent launched itself. Dreamcast
runs in RetroArch Flycast. GameCube needs the Spark's Dolphin, because RetroArch's Dolphin core gives gBox no memory.

1. Load a save and start City Escape, mission 1, as Sonic. Run `op=status`. Expect `level_name` City Escape, `character_name`
   Sonic, `mission_number` 1, `state_name` "in game". The rings, score and time should match the HUD, `rank_table.A`
   should be 18000, and `emblems.count` should equal the emblem count on the stage select or title.
2. Pause, then run `op=finish_level`. Expect `finished: false` and "paused". Mission and rings are unchanged (`op=status`).
3. Unpause, then run `op=finish_level`. Expect `finished: true, verified: true`. Sonic does the win pose, and the results
   screen says Mission 1 (not mission 2). The rank matches step 1's `grade_now` at the moment of the call. The rings
   bonus uses the ring count from before.
4. Start City Escape mission 1 again and run `op=rank rank=S`. Expect `rank: "A"`, the "no S rank" note and
   `grade_now: "A"`, and the results screen shows A. On the stage select, City Escape mission 1 shows an A emblem.
5. Start City Escape mission 2 (100 rings), then run `op=rank`. The clock should be 1:19.00 after the call, and the
   results screen should show A.
6. Run `op=emblems count=1` and then `op=status`. `emblems.count` should go up by 1. Then run `op=emblems` and expect
   `emblems: 180`. Finish any stage so the game saves, and return to the stage select. Expect 180 emblems and Green
   Hill unlocked. Reset the console, reload the save, and the 180 should still be there.
7. Optional: run `op=finish_level` in Sonic vs. Shadow 1 (boss id 19), which tests the "untested" path.

Afterwards, set `live_checked: True` for each build that passed in `gbox/sa2_mods.py`. Record the addresses with
`re_dossier op=record` for both game ids.

## Gaps

* Europe and Japan (both consoles) are not mapped and are refused.
* Boss fights 60+ (Big Foot, Hot Shot, Flying Dog, King Boom Boo, Egg Golem, Biolizard, Finalhazard), kart races,
  2P battles and Chao World cannot be finished this way.
* 22 of the 25 extra emblem bytes are not named (boss attack / chao race). The tool sets them the way the recount
  reads them.
