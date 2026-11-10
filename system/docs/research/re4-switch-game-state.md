# RE4 Switch: where the game is, from the game's own state (2026-11-10)

The operator, watching RE4 Switch in MercMode (Krauser on Waterworld, session `5a68e96bfd1447a2-86b4b4f28dc1451d`):
the round's intro card "Eliminate as many Ganados as you can before your evac chopper arrives!" waited for A for 5+
minutes while the bot reported "fire: crowd fire: 4 within 6 m" (620 shots, 0 hits, 0 kills) and the live map showed
"Fire", a target and a clock that read 94.9 -> 95.4 -> 93.1 in 12 s.

## Root causes, by layer

| Layer | What it believed | Why it was wrong |
|---|---|---|
| frame classifier (`re4_switch_screens`) | the intro card is `unknown`, and often `playing` | no reference names the card; `has_hud` fires on Waterworld's sky and horizon (live 04:18:38: `playing` during the intro, no HUD drawn) |
| runner (`re4switch_bot`) | after a stage pick, 6 s of an unnamed picture is the round (`UNKNOWN_ROUND_S`) | a timeout's guess; the card can wait forever. The HUD rule (`playing`) skipped the entry presses outright |
| fight (`re4_switch.Bot`) | a player and Ganados in RAM are a fight | the round places its Ganados before the intro; nothing asked whether the player was in control |
| clock (`ClockFinder`) | any bss f32 that falls at wall rate is the round clock | its 2026-11-05 "cluster of copies 0x30 apart" at module + 0x1274710 is pG + 0x3D8, inside `mtxPalette` (pG + 0x190, 0x30-byte matrices): matrix floats, not the clock |
| map / now_playing / telemetry | the runner's `screen` and the Bot's `doing` | they relayed the two guesses above ("playing" was hard-coded for the tactical frame) |

The stopgap 20162e1d (`Bot._frozen`: A after 8 shots in 5 s unmoved and without a hit) now only runs without the
game's state.

## The fields

Found by static analysis of the decrypted main (`~/gBox_alt/switch/work/re4-nsp/main.bin`, capstone) against the
GameCube decompilation (`~/gBox_alt/reference/re4-gc-decomp`: `include/global.h` GLOBAL_WK / `STA_*` / `SPF_*`,
`src/game/mercenaries.cpp`, `src/game/cockpit.cpp` CountDown, `src/game/sce_com.cpp` SceEventStart); flag words count
their bits from the top (MSB first), as on the GameCube (System_flg 0x40000000 = SYS_OMAKE_ETC_GAME, index 1). Module
offsets; add `re4_switch.module_base()`.

| Field | Where | Static proof | Live proof (lilspark, session `5a68e96bfd1447a2-780e877d92ec4151`, Krauser / Waterworld) |
|---|---|---|---|
| pG | `*(0xB1AE08)` = 0x1274338 | `re4_weapons.GAME_PTR_VAR` | the pointer read 0x1274338 |
| System_flg | pG + 0x78 | MercSysSetPoint (0x2AB320) tests byte +0x7B bit 6; SceEventStart ORs 0x800 (SYS_SCISSOR_ON) | 0x40000804 in the round (Mercenaries bit on) |
| frame step | pG + 0xA4 (f32) | CountDown::move (0x200C0) subtracts it from the clock | 0.5 (60 fps) |
| Stop_flg | pG + 0x1A8 | SceEventStart (0x4A1B60) ORs 0x00400100 (SPF_ACTBTN, SPF_SCE_AT); CountDown::move pauses on byte +0x1AB bit 4 (SPF_PL) | intro 0x80400100 (SPF_KEY: the pad masked), round 0, death 0x80400100 |
| Status_flg[4] | pG + 0x5090 | SceEventStart: `[+0x5090] |= 0x1000` (STA_EVENT), `[+0x5094] |= 0x10000000` (STA_SUSPEND), KeyStop(0x00F12000EFCF1000); MercSysMoveMain tests byte +0x5092 bit 4 (STA_DIEDEMO); CountDown::move tests +0x5097 bit 4, +0x5092 bit 2 (STA_SUB_SCRN), +0x509A & 0x0A | intro 0x3001310 / 0x18000200; round 0x3000310 / 0x8000200; grabbed +0x5094 & 0x8000 (STA_PL_CATCHED) as his life fell 2400 -> 2112, 1458 -> 1255; death +0x5090 & 0x00100000 |
| MercSysWk | 0x124F690 (0xF0 bytes) | MercSysInitRoom (0x2A6B10) loads it from GOT 0xB277E0, clears +0x28..+0xF0, stage +0x70 from the room, mode +0x6C from pl_type | mode 2 (Krauser), stage 3 (Waterworld) |
| intro run / step | MercSysWk + 0xD4 / + 0xD5 | MercSysMoveStart (0x2A7290): `[+0xD4] = 1`, switch on +0xD5, step 1 = SceMesSet (waits for the message to close) | 1 / 1 through the card, 0 / 2 after it |
| round run | MercSysWk + 0xD9 | MercSysMoveMain (0x2A6DE0): set to 1 only after MercSysMoveStart returns; 0 when the clock reaches 0 | 0 in the intro, 1 from the first live frame |
| results run / step | MercSysWk + 0xE0 / + 0xE1 | MercSysResultMove (0x2A95D0): `[+0xE0] = 1`, switch on +0xE1 | (no round ran out yet: death after 20 s) |
| score / combo / kills | MercSysWk + 0x28 / + 0x2C / + 0x48 | MercSysSetPoint: score += base points, combo + 1, `[+0x48] += 1` | 0 / 0 / 0 (no kill in that round): **to confirm** against a kill |
| the HUD clock | CountDown = Cckpt (0x1132F10) + 0xB0: state u32 (1 alive, 8 paused), frames left f32 at +8 | initTime (0x20AF0): (m*60+s)*100+c, x3/10 frames into +8/+0xC; MercSysMoveMain reads +0xB0 bit 0 and +0xB8 > 0 | intro: state 9, 3600.0 (2:00) held; round: state 1, falling **30.06 a wall second** over 20 s; death: state 0 |

## The phases (`re4_switch.decode_state`)

`none` (no round's scenario task) | `intro` (startSt running: the card, A) | `playing` (in control: round running, no
event / suspend / pad mask / player stop / death / case / grab) | `grabbed` (STA_PL_CATCHED: the mash, A) | `held` (an
event, a suspend, the pad masked or the player stopped inside the round: A) | `case` (STA_SUB_SCRN: B) | `dead`
(STA_DIEDEMO: A answers Continue) | `results` (rsltSt running: A). `clock` = frames / 30 while the CountDown is alive;
`clock_running` = alive, not paused, the case closed.

Stale fields: MercSysWk is cleared only by the next stage's MercSysInitRoom, while a soft reset (You Are Dead -> No,
the results' end) clears pG from Rno0 on and re-makes the cockpit (decomp `systemRestartInit`, `Cckpt.gameInit`). So
the intro and round run bytes count only with the CountDown alive (it is started before the intro's run byte is set);
the death clears the clock but sets STA_DIEDEMO, which the reset clears too.

The probe's 53 samples replayed through `decode_state`: none (load) -> intro x 10 s (the old bot fired 10 shots there)
-> playing at 04:18:48 (clock 119.42, running) -> grabbed / playing x 3 -> dead at 04:19:09. Every frame from the
intro on read `playing`.

## What uses them

* `re4_switch.snapshot`: `snap["game"]`, `timer` from the CountDown (`clock_source: countdown`; ClockFinder only when
  the state cannot be read), `score` / `combo`, `mercenaries_phase`; `own_screen` maps the phase.
* `re4_switch.Bot.tick`: not in control -> `_not_in_control` (the phase's key at its pace, never the trigger, the aim
  lock's request withdrawn, `doing` / `why` name the phase); the operator's map mark waits too (`re4_walk.attach`).
* `re4switch_bot.play`: a round is the game's (intro included, no entry presses, no 6 s rule); while it is not live, a
  named reference menu or the death screen still wins (stale fields); `stats.screen` is the phase (`intro`,
  `playing`, `held`, `dead`, `results`), `frame_screen` the classifier's, `game_phase` / `in_control` / `game_clock` /
  `clock_running` beside them; the tactical frame takes the same screen; the results boundary needs the round seen live
  and the game's results run (`state_source: ram`).
* `CrossCheck`: a disagreement (RAM says X, the frame says Y) is counted (`state_disagreements`, `last_disagreement`)
  and logged to `gbox-data/mercs/re4-state-disagreements.jsonl`, one row per pair per 5 s.

## Still open

* kills / score / combo: statically proven, not yet seen moving (the live round had no kill); `snap["kills"]` stays
  the census until a round confirms `MercSysWk + 0x48` against kills.
* the results phase and what MercSysWk / the CountDown read at the title after a round (stale-field rule above).
* `has_hud` false positives on bright sky (the disagreement log will show where).
