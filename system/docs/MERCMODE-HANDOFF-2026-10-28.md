# MercMode handoff — 2026-10-28

This is for the next agent continuing the operator's MercMode work. The previous agent (Claude) stopped at its usage limit; its subagents are stopped until 2026-11-02. Read the whole document before acting.

## 0. Start here (if you were told "continue from here")

Run this loop until the operator says stop. Don't wait to be asked for each step.

1. **Check the live state** on the Spark (section 3: API and round data).
   - Is MercMode playing on lilspark (`GET /api/mercmode`: current_run phase `playing`, and the predecessor-to-playing handover under 3 s)?
   - Is the i9 online and looping?
   - Read the last 5 RE5 and RE6 rows in `curriculum/*/rounds.jsonl`: kills, combo_best, bonuses_taken, deaths, wall_push_s, unaims_in_5m, flashes and flash_qtes.
2. **Take the top open item** in section 5, in order: stream, RE5 navigation, RE6 S rank, RAM swaps, panels, i9.
   - Fix it with a small, tested PR, merge it, and let the 15-minute auto-deploy ship it (or run `~/bin/gbox_autodeploy.sh`).
   - Then compare the next rounds' counters with the ones before. If a number got worse, revert.
3. **Every operator message is a directive.**
   - Act on it in the bot code when it's a quick fix; otherwise file a Hermes ticket (section 3) with their exact words and metrics.
   - Record standing rules in this file's section 1.
4. **Merge finished work.** Merge other open PRs (Hermes drafts included) when their tests pass and they match the operator's taste (section 6). Use `gh pr ready N`, then merge.
5. **Keep the operator informed** in short, plain updates: what changed live, what the numbers show, and anything only they can do (relaunch a PC, close a game).

## 1. What the operator wants

**MercMode:** gBox's endless Mercenaries mode. It plays RE5 and RE6 on Switch ("No Mercy") back to back, streamed by gBox to the operator's app and PiP:
- no loading screens or waiting between rounds;
- the autobot plays well and improves every round;
- the operator steers the bot live.

**The operator's goals, in their own words (keep them as the yardstick):**
- *"Combo to 300 due to a delicate ballet of dispatch, exploration and time bonus acquisition."* The only way to win No Mercy is max kills (300) with the combo never dropping, bosses recognised and dispatched, and S rank.
- **Two strategies the bot swaps between, every character, every game:**
  1. **Crowd control, first.** When surrounded: clear space and get out.
     - Flash and fight: throw a flash, then use the stunned state at once.
     - Grenades.
     - Rapid-fire magnum or shotgun (20x, infinite ammo), with a graceful aimbot clearing a frontal cone.
     - Mines dropped while leaving, so the regrouped crowd gets dispatched.
     - Never stand still.
  2. **The run, second but vital:** time bonus to time bonus (RE6: yellow capsules for time, green ones for combo time), navigating area to area, banking time to stay in the round.
- **"If there's one thing you will never see someone do in mercenaries is put their face in a wall."** No wall-facing, no wall-hugging, no running blind into crates. The bot maps each level as it goes (like a robot vacuum) and runs it with growing confidence.
- **Never idle:** *"If I activate the Autobot, I need the Autobot playing the game."* No sitting on title, menu or result screens, in any game.
- **Live control:** *"the bot automatically plays while I control the Autobot dynamically on the fly."* Every behaviour gets toggles, intensity sliders and a priority order in the PiP. The bot must visibly act on the operator's quick commands.
- **A stable stream:** no stutter; frames must never jump back.
- **Changes are kept only if they help:** a higher score or efficiency. Everything must be revertible.
- **The i9-NUC:** loops Mercenaries 3D and Resident Evil 4 VR, alternating, autoplayed and learned, visible in that PC's PiP.

## 2. The machines

| Machine | Role |
|---|---|
| **lilspark** (Spark, 10.89.1.246, user ehm_eckx, CST) | gBox control plane plus its own worker. MercMode plays here: RE5 Switch `010018100CD46000` and RE6 Switch `01002A000CD48000` on Citron. Share: `~/gBox/system`. Service: `gbox.service`. |
| **spark2** (lilspark2) | The model server Hermes uses (lane `sparkDeux`). |
| **i9-NUC** (10.89.1.43) | Windows worker with its own local scheduler (federation `scheduler_owner: local`). No SSH; its local API listens only on itself. Reachable only through the Spark's job and federation path. |
| **JAYBUILTFINALE** | The operator's own PC: the desktop app runs from `C:\_tools\gBox\system`. Never start agent sessions or emulators here. |

## 3. How to operate

**Deploy (automatic since 2026-10-27, operator OK):**
- The Spark's crontab runs `~/bin/gbox_autodeploy.sh` every 15 min:
  1. `deploy_main.sh --deploy --no-restart` copies merged main to the share, with a backup in `gbox-data/deploy-backups/`.
  2. `~/bin/gbox_reload_bots.py 230` hot-reloads changed bot modules (no loading screen).
  3. If `gbox-data/deploy-restart-pending` exists, it restarts `gbox.service` at 05:00-05:14 CST only.
- Log: `gbox-data/autodeploy.log`. Run the script by hand to deploy at once.
- Server and core files (server.py, screensaver.py, adapters.py, mercmode*.py, tool schemas, profiles) need the restart. Bot modules (`gbox/mercs/titles/*`, `bot_logic.py`, `tuning.py`) hot-reload.
- Windows PCs load code at app launch (the operator pulls and relaunches).

**PRs:**
1. Branch from origin/main and commit with tests.
2. `git push origin <branch>`.
3. Write the PR body to a file, `scp` it to the Spark, and run `gh pr create -R teamcsharp/gBox --body-file`.
4. Merge with `gh pr merge N -R teamcsharp/gBox --merge`.

**Tests:** `python -m pytest -q -p no:cacheprovider tests/<file>` from `system/`; `node --test tests/<file>.cjs`.

**The API:** `http://127.0.0.1:8765` on the Spark. Token in `~/bin/dc_memtest.py` (`TOKEN`); never print it. Send the header `x-gbox-actor: agent`, or launches are recorded as the operator's.
- `GET /api/mercmode`: hosts, current_run, settings, handover predecessor.
- `POST /api/mercmode`: per-host settings and dispatch (#1405).
- `GET /api/workers`.
- `POST /api/requests`: Hermes tickets. Set `context.handoff`, then put the id at the head of `POST /api/hermes/queue/priority`.

**Round data on the Spark:**
- `gbox-data/mercs/curriculum/<title>/rounds.jsonl`: one row per round with every bot counter.
- `gbox-data/mercs/lessons/<title>/runs/`.
- `round_maps/` (#1414 capture, #1431 reviewer).
- `GET /api/mercs/damage-clusters`.
- `GET /api/mercs/learning`.

## 4. What is live (merged)

| Area | What's live |
|---|---|
| **MercMode continuity** | RE5 and RE6 alternate, 5 rounds each, from a warm pool. Handovers measured at **0.8-1.9 s**; 53 rounds in 3 h. Gaps in `rounds.jsonl` are round lengths, not breaks. |
| **Learning loop** | Cause clusters with batch tickets to sparkDeux (#1397), round faults and change tracking (#1403), automatic per-stage tuning with revert-on-worse (#1407 / #1417), the keep-or-revert gate for code changes (#1432), run maps and the reviewer (#1414 / #1431). |
| **Live bot control** | PiP sidebar, #1454: hover the PiP's right edge, an arrow slides the panel out. Code: `gbox/mercs/bot_logic.py`, `clients/desktop/bot-logic-sidebar.js`, `re5_mods` op `bot_logic`. Whitelisted constants are set live and saved in `gbox-data/mercs/bot-logic.json`; `tuning.apply` reapplies them each round. |
| **RE5 bot** (`gbox/mercs/titles/re5_switch*.py`) | Prompts (#1390), crowd shotgun fire (#1394), random no-pistol loadout every round (#1395), near focus (#1399), quick turn (#1401), wind-ups first and real-grab-only holds (#1408), stage cycle (#1415), wall governor (#1420), aim report (#1425), infinite spray and 5 s per kill (#1430), keep firing when crowded (#1436), no stick during or 0.15 s after the x80 shot (#1442; it caused teleports). The RAM aim lock exists but is **off** (#1438): it snapped the view. |
| **RE6 bot** (`re6_switch*.py`) | Nav-mesh sight and threat-only targets (#1387), wind-ups (#1389), live weapon panel and no pistols (#1392), capsule mid aim (#1393), pitch guard (#1402), held grenades thrown (#1409), deaths work with flash push-through (#1423). |
| **RE6 grenades** | Throw held 0.3 s and flurries (#1437), facing the group (#1439), any gun after (#1440), ZR released before ZL (#1441, the likely cause of "lifts but never throws"), QTE prompt pressed in holds (#1445), flash then fight with a 5 s gap and flurries only at 5 within 3 m (#1446), no grenade camera writes (#1447; they turned her to walls), 20x fire for every gun, magnum and throws (#1451, at the 05:00 restart), remote bombs off (profile). |
| **Merc3D on the i9** | 3DS RAM reader (#1375), bot (#1386), cheap attach (#1391), wide heap scan off (#1443; it likely starved the worker's heartbeat), player node (#1406), fire-key probe (#1426), PiP local instance (#1398), dispatch "Run on a PC" (#1405). |

## 5. Open and unresolved: the work queue

The Hermes tickets are at the head of the priority list. Do the most visible first.

1. **#5246 Stream freezes, rewinds and jumps forward** (app and broadcast).
   - Hypothesis: two picture sources taking turns. When the session MJPEG stalls, the client shows an older still or `last_frame` (rewind), then the MJPEG resumes (jump forward).
   - Look at `clients/web/viz/session-live.js` (`last_frame_age`, `session_stills`), the compact PiP (`#compact-stream` in `clients/desktop/index.html`, `gboxStreamWatchdog`) and `adapters.MjpegStream`.
   - Frames must be monotonic.
2. **#5242 RE5 navigation:** no wall-hugging, statue to statue.
   - `bonuses_taken` is ~0 of 8-24 per round.
   - Build a persistent per-stage occupancy map, seeded from the PS3 bot's data in `gbox-data/mercs/learned/BLUS30491`, then A* routes in GameFAQs statue order.
   - Unfinished agent work is in worktree `re5-guided-runs` (`docs/research/re5-mercenaries-strategy.md`, `gbox/data/re5_merc_routes.json`).
3. **#5299 RE6 S rank and 300 kills:** capsules are seen but skipped.
   - Live: the capsule run runs (`phase bonus_run`), but `bonus_unseen` and `bonus_skips` increase while `bonus_shots` stays at 0. A weapon switch interrupted the run.
   - Fix the capsule line-of-sight test, walk to unseen capsules by nav mesh, and allow no weapon switch mid-run.
   - Kills are 8-97 per round (target 300); combo 8-20.
4. **#5276 Instant weapon and grenade swaps through RAM:** no wheel, no menu.
   - Find the equipped-weapon state and the game's equip request in both Switch builds.
   - Deliberate situational swaps only, e.g. the rapid-fire magnum when swarmed. No random swaps.
5. **#5250 Strategy panel and #5300 quick-command sub-panel:** extend the #1454 sidebar.
   - Strategies with on/off, intensity and drag-reorder priority.
   - Each quick command shows which behaviours it drives and lets the operator tune them.
   - The bot must visibly obey quick commands, fast.
6. **#5247 i9 worker goes offline about 20 min into Merc3D;** "Relaunch worker" does nothing while a native session is owned.
   - #1443 may fix the wedge. Verify after the operator's relaunch.
   - Make "Relaunch worker" work.
   - At 04:54 the i9 waited because "a game is already running there": likely a leftover RetroArch window. Only the operator closes games on their PCs.
7. **#5249 i9:** alternate Merc3D and RE4 VR; Merc3D progresses level to level through RAM; a never-idle watchdog for every game; Merc3D into the learning loop.
8. **#5248** 3DS inside gBox: main screen large, small screen beside it, scalable.
9. **#5243** RE5 aim: track falling and downed targets. Do it without camera writes that snap.
10. **#5244** RE5 flash flurries and mines; finish PR #1429, keeping the spray in every loadout.
11. **#5245** RE6 flash navigation; **#5251** learning follow-ups (rebase #1422, the RE6 kill-time slider, RE5 healing without a spray); **#5252** mods parity (RE5 aimbot, auto parry, instant QTE, knife knockback, live weapon), RE4 flash bursts, RE6 taunts and climb links, and co-op 6:1 after a verified P2 test.

**Open PRs:** #1429 (RE5 flash; must keep the first aid spray) and #1422 (Bot learning view; conflicts, rebase it).

## 6. Rules: don't break these

- **Never stop or touch an operator session.** Check the worker name and launch actor before any stop.
- **Private emulator runs:**
  - Never on JAYBUILTFINALE.
  - On the Spark only in a MercMode-down window, with `~/gBox_alt/scratch/agent/switch/guard.py` (nice 19, little cores 0-4 and 10-14). The operator sees every boot as stutter.
- Keys and tokens only in root-600 env files; never print them.
- **Restarts:** the operator has given a standing OK to restart `gbox.service`, but restarts kill the warm pool and show loading, so batch them. The 05:00 cron does this.
- **Before any bot change,** check it against the operator's taste:
  - no camera whips or snaps, no spinning, no aiming up without a threat;
  - no facing walls or wall shots;
  - no standing on its own mines or idling among foes;
  - QTEs taken immediately.
- RAM camera writes (aim locks) have repeatedly caused snaps: RE5 #1438, RE6 #1447. Prefer the game's own inputs, rate-limited, and the heading governors.
- **The x80 fire-rate time scale (RE5 player +0x1A08) and the RE6 mDeltaTime boosts** speed up everything during the boosted motion. No stick input then (RE5 #1385 / #1442; the RE6 governor).
- **Measure every change on live round counters** (`curriculum/<title>/rounds.jsonl`); the gate reverts regressions.
- Commit messages end with `Co-Authored-By: <your model line>`. PR bodies have Why, What and Tests sections.

## 7. Key RAM facts

| Title | Facts |
|---|---|
| RE5 Switch | Player +0x1A08 time scale (fire_rate); aim pitch is an output at +0x3F5C; enemy motion byte +0x8F8 (80/81 grab lunge, 60/91 swings); attack flag +0xA23 bit 0x40; sActionButton main+0x1CEFB78 (hourglass prompt label 112, press Y); uCameraQFPS at uCameraCtrl+0xDB0 (pitch +0x1B0). |
| RE6 Switch | Camera = player+0x3A28 (uCameraQFPS camera+0x16A0; +0x2C4 yaw, +0x2C0 pitch); rNavigationMesh decoded (`re6_switch.NavMesh`, A*); sActionButton main+0x28E7AF0 (B 0x4000 climb/grab QTE, Y 0x8000 pickup, R1 0x800, L1 0x400, R2 0x200, L2 0x100); enemy action at +0x13F0; mDeltaTime at unit+0x30; bomb uWp1097 +0x60; clock at sGameMan+0x4698. |
| Merc3D (3DS, RetroArch citra) | `gbox/citra_memory.py`; title 0004000000038B00; player node +0x10. |

## 8. Where the history is

- PR descriptions #1312-#1454 on teamcsharp/gBox.
- `system/docs/research/*`.
- The handoff docs in `system/docs/` (`RE6-MERCMODE-HANDOFF.md`, `resume-2026-10-22-handoff.md`).
- The Hermes tickets above, each with the operator's exact words and acceptance metrics.
