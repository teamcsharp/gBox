# DeepSeek PM hand-off, 2026-11-11: run gBox, keep MercMode playing, keep the bot improving

You are the project manager for gBox while the operator is mostly away. This document is your operating manual. It
supersedes the "what to do" parts of `DEEPSEEK-HANDOFF-2026-11-10-NIGHT.md`. Keep appending your merge log to that
document's Log section, and keep the night doc's ground rules: they still hold.

Contents:
0. What is live now
1. Ground rules
2. The machines and how code goes live
3. Keep MercMode playing and swapping on lilspark
4. The i9: decryption lab, live mode, and the request daemon
5. Hermes: tasking, assimilating and judging branches
6. The bot's auto-improvement goals
7. One bot for RE4, RE5 and RE6, reusable for other titles
8. The immediate priorities, in order
9. Work in flight at hand-off

---

## 0. What is live now (2026-11-11 ~00:00)

- **Pine Box shows the Spark's MercMode 24/7.** gBox's broadcast program is pinned to the PC `lilspark`. That pin
  plays lilspark's MercMode turn, never a warm/paused game, and shows a slate between turns. Pine's broadcast lock is
  `program`.
  - Before this, Pine's lock was "Follow PC: spark1", and Pine's `plan()` fell back to the first live game in device
    order (the i9's PSO) whenever spark1 had no row. Two things caused the missing row: MercMode sessions are
    `agent_owned` and Pine hides agent sessions, and lilspark briefly has no session during a title handover.
  - Do not change the program pin or Pine's lock. If the operator says the stream jumped, check:
    - `GET /api/broadcast/feeds`: program `mode` should be `pc` and `target` `lilspark`;
    - Pine's `GET :8096/api/gbox/state`: `settings.broadcast` should be `program` and `locked` should be true.
- **The 2026-11-10 assimilation is merged** (section 5.3): 30 MercMode Hermes branches merged or ported, all
  PSO checkpoint branches still open, and three older Hermes re-runs.
- **The rotation:** titles re4 / re5 / re6, `rounds_per_title` 5, `blueprint_look` on. The default builds were one
  per title (re4 `recovery-re4-fit-v4-20261110`, re5 `recovery-series-01-20261110`, re6
  `recovery-re6-enemy-cast-01-20261110`). See section 3.3 for the donor rotation that replaces them.

## 1. Ground rules

Unchanged from the night doc:
- **Hands off lilspark.** No ssh / sudo / systemctl / kill there, and no launches or stops.
- **Every gBox API call carries `x-gbox-actor: agent`.**
- **Never print keys.**
- **Never stop or reset an operator session.** Check the session's label owner and the launch actor first.
- **You may merge to main through the gate** (section 5.3).
- **Code that needs a service restart goes live at the 05:00 window.** Write that in your merge note. Bot-only
  modules hot-reload on their own.

Also:
- **Automation never moves the broadcast program.** The route refuses the actors `agent`, `hermes` and `mcp`.
- **Never delete operator files:** firmware, keys, saves, or games they placed.
- **No heavy transfers through JAYBUILTFINALE**, the operator's Wi-Fi PC.
- **Ask for live checks you cannot make.** Write the exact probe and post it on the ticket, or in this doc's log for
  the operator.

## 2. The machines and how code goes live

| Machine | Role |
|---|---|
| **lilspark** (the Spark, 10.89.1.246) | The control plane (`gbox.service`, :8765), the MercMode worker (Eden for Switch RE4/5/6), Pine Box (its own containers; gBox gameplay is relayed by `gbox-pine-media.service`), the Hermes gateway. **Only Switch RE builds live here.** |
| **lilspark2** (10.89.1.20:8101) | The Hermes inference node (Qwen, 12 lanes; 16 overloaded the gateway). |
| **i9-NUC** | A gBox Windows client and the kiosk/service node with the eGPU (RTX 3090). Runs PSO (Dolphin + ViGEm pads) and your harness. |
| **JAYBUILTFINALE** | The operator's PC. Never used for agent work or test launches. |

**Deploy path:**
1. You push to main.
2. Every 15 minutes the Spark's cron runs `~/bin/gbox_autodeploy.sh`. It syncs main to the share, then
   hot-reloads changed bot modules at each title's next session.
3. A change to runtime/server code leaves `deploy-restart-pending`, and `gbox.service` restarts at 05:00-05:14.

Since `95e4ab18`, bot-only merges still hot-reload while a restart is pending.

**Hot-reload traps:**
- Only modules loaded at worker start are reloaded. Import a new shared bot module at the top of a module that is
  loaded at start, never first inside a tick.
- `gbox.mercs.directives` is `NOT_BOT`, so it needs a restart. Bots read commands through `doctrine.Reader`, which
  does reload.
- A worker with any job in flight counts as busy, and MercMode will not start its next round. Never leave probes
  polling across rounds.

## 3. Keep MercMode playing and swapping on lilspark

### 3.1 Healthy looks like
- `bot_sessions` (MCP) shows one RE session on `lilspark`, with `bot.running` true and `screen` playing / select.
  Telemetry `age_s` should be under ~5 s.
- `GET /api/broadcast/feeds`: the program is `live` with `why` "pinned to lilspark (its MercMode turn)", at a frame
  rate near 60 fps.
- Titles change every 5 matches and builds change per block (section 3.3).

### 3.2 When it is not playing (ask the operator for the lilspark-side fixes; you cannot ssh)
- **"lilspark is not running a game" for minutes:** usually the NAS ROM mounts dropped (every launch fails with
  "ROM not reachable"). The fix needs ssh, so ask:
  `sudo systemctl restart mnt-gbox-quickswap2.mount mnt-gbox-hyperspin.mount`.
  A gbox.service restart does not remount them.
- **A round never starts:** look for jobs in flight on lilspark (`get_game_work_queue`, `list_workers`). Any job
  blocks the scheduler.
- **After any restart,** `GET /api/mercmode` must show the run adopting its session.
- **`mcp__gbox__job_mercmode op=status` is huge.** Use `bot_sessions` to see what plays, and
  `GET /api/mercmode` → `hosts[name=lilspark].settings` for settings.

### 3.3 Swapping characters (the operator, 2026-11-10: "I want to continue seeing new and randomized characters from the database ... swapped frequently ... changing on rounds if hot swapping is possible")
- **Builds** are LayeredFS overlays on the Spark: `/home/ehm_eckx/gBox_alt/gbox-cache/mods/<game_id>/<build>/`.
  - RE5 `52d15709be0fda1a`: ~130 builds, the newest casts being `recovery-series-01..04-20261110`.
  - RE6 `115f9cdbba115432`: ~18 builds.
  - RE4 `270a15eb98dab4d7`: ~96 builds, mostly `recovery-re4-fit-v4-*` per-slot variants.
- **The rotation is MercMode settings** (`POST /api/mercmode {host:"lilspark", ...}`):
  - `default_mods` maps each title to a build;
  - `queue` holds entries `{title, mod}`, with `repeat_queue` on. Queue in **5-round single-build blocks**: never
    interleave titles round by round (the operator's rule).
  - `blueprint_look` plays each build's `<build>-blueprint` companion, falling back to the plain build.
- **The donor fit gate:** no oversized or stretched donor ever goes into rotation. Check the receipt bboxes
  (`gbox/donor_fit_audit.py`, `gbox/donor_rejects.py`) before you queue a build.
- **The donor rotation work** (branch `wt-donorrot-20261110`, section 9) adds a pool/fresh rotation, so each block
  draws a different verified build and new random casts get generated from the library. It also records whether a
  build can change between rounds without relaunching Eden.
- **Normals:** some donors render inside-out (the operator saw Aerith in the RE6 enemy cast). The fix is in branch
  `wt-normals-20261110`. Rebuild the affected builds after it merges, then put them back in rotation.

## 4. The i9: decryption lab, live mode, and the request daemon

The i9 has two modes, and gBox must follow whichever it is in.

**1. Operator client.** The operator plays or uses the gBox app on it (PSO modding through the app, for example).
- The operator's own desktop-app view never steers the broadcast program (`9e25bae2`).
- The pad belongs to the operator.
- Only non-pad jobs run, on a dedicated PC (`a59da474`: background testing covers ownership for non-pad jobs while
  the operator plays).

**2. Service node / request daemon.** gBox dispatches work to the i9 when it is **available**. Available means all
of these hold:
- `service_work` is on;
- `nvidia-smi -L` lists the 3090;
- gBox is running;
- each installed service answers its health check.

When any of them fails, the i9 is a plain client and its work falls back to Hermes alone. The design is
`DEEPSEEK-HANDOFF-2026-11-10-EVENING.md` §1 / §1b; the measurements are in `system/docs/i9-service-node.md`.
To finish it:
- **Registration + readiness:** in the worker heartbeat or `/api/service-nodes`, removed within one heartbeat when
  not ready.
- **One routing table: task kind → service.** The task kinds are decrypt, analyse binary, extract assets, vision and
  LLM. Pass the kind in `context`, and attach the result to the request.
- **The local LLM as a Hermes node:**
  - add `[hermes.local.nodes.i9]` in the i9's own overlay `system/gbox.local-i9-nuc.toml`. **Never** add it to the
    shared gbox.toml, or the Spark would proxy "i9" to its own Ollama;
  - use `max_parallel_jobs = 2` (the measured Ollama slots), `qwen2.5-coder:14b-16k`, with the 32b-16k for hard
    reasoning;
  - for real concurrency, move to vLLM (WSL2) or `llama-server --parallel 8 --cont-batching` and measure again
    before raising capacity.
- **Gate everything on readiness:** no eGPU means no node.

**The decryption lab** (`gbox/decrypt_lab.py`, `system/docs/decrypt-lab.md`, `/api/decrypt-lab/*`) is the reusable
reverse-engineering pipeline for every title:

> adapter → stages (identify / extract / disassemble / fields / verify / driver) → fields
> (candidate / confirmed / rejected, with evidence) → verification → driver

It introspects the title modules in `gbox.mercs.titles` (TITLE_ID, BUILD_ID, SIG_OFF, SIGNATURE, the S_* anchors,
DRIVER), so a new title is one adapter entry, not a new tool.
- **Use it** to build the RAM map and driver for any new title the bot should play (section 7.4), and to confirm
  fields the RE4/5/6 bots still guess.
- **Run the heavy parts as service-node jobs on the i9:** disassembly, binary analysis with the 3090's model, and
  decryption of titles the operator owns.

**Live mode on the i9:** live sessions with live controls. For PSO that is `gbox/pso_live.py`: bounded, audited
commands over the session channel (give, equip, floor_warp, boss_warp, survival, autoplay_speed, ...), plus the
`pso_chords` turbo/walk chords and ViGEm virtual pads.
- **Before debugging input:** four ghost ViGEm pads can occupy every XInput slot. Clear them first (CP04 round 142).
- **PSO's player 1** uses PSO's vpad by default, or the operator's controller when `GBOX_DOLPHIN_VPAD=off`.

## 5. Hermes: tasking, assimilating and judging branches

### 5.1 How Hermes works
Hermes works inbox requests (tickets) on local nodes and publishes one branch per run: `hermes/request-<N>-<run>`.
- **Nodes:** `GET /api/hermes/local/nodes`. Capacity is set with `POST /api/hermes/local/nodes/{name}/capacity`, and
  a node is switched with `POST /api/hermes/local/nodes/{name}`.
  - lilspark2 runs at 12 lanes and claude at 4;
  - deepseek is off (its credit is for your harness), and Z.AI is off (quota).
- **Priority:** `POST /api/hermes/queue/priority` with request ids first. It is saved under the queue's lock.
  The operator's critiques (the PiP "Critique the bot…" box, or ⚠ Flawed) arrive as `operator_requested`
  "Improve <title>: coaching note N" requests and are worked right after the priority list.
- **Automatic tickets from the bots:**
  - damage clusters (`gbox/mercs/damage_clusters.py`, batches appended after the operator's list);
  - incident replays (`incident.py`, `incident_replay.py`);
  - death lessons (`mercs/core/death_lessons.py`, #9525);
  - wall-stuck reports, when `wt-wallreport-20261110` is merged.

### 5.2 Writing a ticket Hermes can finish
- **Say it is a CODE-CHANGE ticket.** Tickets once got a "docs only / read-and-report" rules block copied in from
  research tickets, and Hermes then only read and reported. Never reuse research RULES for code tickets.
- **Give it evidence:**
  - title, build, session id and time, the telemetry numbers;
  - the bot_trace excerpt (`system/scripts/bot_trace.py`);
  - the room / nav facts;
  - the operator's words, verbatim.
- **Give the acceptance as numbers and a test:** "a regression test built from this evidence; wall_stuck_events 0 on
  the replay; no new failure in the gate subset".
- **Name the files** (section 7) and the title's profile knobs. One behavior per ticket.

### 5.3 Assimilating: the procedure, and how to judge a branch
Hermes branches are often 250-2500 commits behind main. Main may already have fixed the same complaint another way:
DeepSeek, Claude or the operator often fix things directly. Judge each branch against main **as it is now**.

**1. List** the unmerged branches:
```
git for-each-ref refs/remotes/origin/hermes --format='%(refname:short)' |
  while read r; do [ "$(git rev-list --count origin/main..$r)" != 0 ] && echo $r; done
```
For each, collect its files since the merge-base. Then classify:
- **MercMode:** paths under `mercs/`, `re[456]_switch`, `mercmode`, `screensaver`, `room_map`, `doctrine`;
- **research probes:** everything else.

**2. One branch per ticket:** take the newest by commit date; older runs of the same ticket are superseded.

**3. Check whether main already has it.**
- `git cherry origin/main <ref>` finds identical patches. Also look for the same subject on main: #6782 was already
  on main as `b0526e88`.
- Read main's code around the change. #9560 / #9527 / #9152 / #5483 had been solved on main differently: tangent
  unwall, room-scaled probe, TARGET_GIVEUP / REACH_FIRST, QTE_INSTANT.

**4. Work in an integration worktree from origin/main and merge one branch at a time:**
`git merge --no-ff <ref>`.
- **Clean merge:** keep it.
- **Conflict only in test files** (both sides appended tests): keep both sides (`git merge-file --union`). Then
  check for duplicate `def test_` names, since Python keeps only the last one, and run the branch's tests.
- **Code conflict:** if main already covers the intent, skip it as superseded. If one piece is still missing, port
  that piece onto main's code in your own commit, crediting the ticket and with its tests. Example: `c66d9b31` ported
  #9560's boot fire-table retry.

**5. Gate** (from the night doc): run `system/tests/test_{mercmode,mercs_,re4_,re5_,re6_switch,screensaver,tactical}*`,
plus every test file the merges touched, on the integration branch **and** on main. Merge only when the branch adds no
failure.
- Known red on main as of 2026-11-10 night (14):
  - test_mercs_combat_throws (1);
  - test_mercs_damage_clusters::test_queue_priority_appends... (1);
  - test_mercs_flash_window (1);
  - test_re4_dispatcher (1);
  - test_re5_switch_bonus (1);
  - test_re5_switch_bonus_giveup (5);
  - test_re5_switch_smooth (2);
  - test_re5_switch_threat (2).

**6. A new failure means bisecting by reverting.** For each suspect merge, run `git revert -n -m 1 <merge>`, run the
failing test, then `git reset --hard HEAD`. Revert the culprit with a message saying which test it broke.
**Main's behavioral tests encode the operator's rules.** When a Hermes change breaks one, the Hermes change loses,
unless the operator explicitly changed that rule. Tonight's examples:
- #6816's broader grab-panic broke RE6's surround grenade burst;
- #9526 stopped crowd fire raising the shotgun;
- #6810 broke the sweep's never-reverse rule;
- the line-of-sight half of #9560 broke the never-stand idle guard.

**7. Finish:**
- merge current origin/main into the integration branch;
- push it as a plain merge (the pre-push guard refuses `system/tools/`, so move scripts to `system/scripts/` in the
  merge commit);
- log it here;
- **reply on each skipped or reverted ticket with the reason**, so Hermes does not redo it the same way.

**Judging quality,** beyond the tests:
- **Reject** a branch that weakens an existing test's assertion without the operator's say-so, touches shared
  runtime code (server, worker, broadcast, mercmode, hermes) for a bot ticket, adds per-tick work that scans the map
  (the Spark's CPU also carries Pine), reads the whole store on a hot path (e.g. `store.all()` per pick, as #3903
  did), or only "records that it is already implemented".
- **Prefer** changes that land in `mercs/core/` with a TitleProfile knob over a copy in one title (section 7).

### 5.4 The 2026-11-10 assimilation, for reference
- **Merged (MercMode):**
  - RE4: #9534 (ladder escape), #9401 (pl07 TPL), #7435 (no sniper in the random pool);
  - RE6: #9529 (shots without target), #6080 (down: fire x5, turn x5), #5487, #6151;
  - shared: #9525 (death lessons), #9528 (mercs_map generator), #9345 (RE4 spawn parser doc), #9360 (RE5 collision
    data), #5326 (directive queue), #5023 (handgun last resort), #7527 (Merc3D live mods), #7425 (PSO buddy advice),
    #3919 (leave-this-area command), #3871 (web "Tell the bot…" menu), #8735 (RE4 reader output dir);
  - RE5 coach notes: #8551, #8550, #6042, #5711, #5710, #5706, #5671, #5670, #5667, #5666, #5665.
- **Ported:** #9560 (the boot fire-table retry only).
- **Reverted:** #7097, #6816, #6810, #9526, #3903, #3347. Re-ticket the intents that still matter against main's
  current code:
  - #9526: proactive crowds, without losing crowd shotgun fire;
  - #6810: never idle among foes, without reversing the sweep;
  - #7097: no grenade veto of the bomb, with main's `_clusters`.
- **Skipped as superseded or conflicting:** #9527, #9152, #6782, #5483, #3945, #3851, #5250, #4847.
- **DeepSeek PSO checkpoints merged:** cp13-library-donors, cp14-room-added, cp04-jump-state, cp-status, menu-learn,
  imitate-play (its `system/tools` script moved to `system/scripts`), gbox-play, live-platform.
- **The ~274 non-MercMode research branches** were judged by a separate pass, branch
  `assim-hermes-research-20261110` (section 9).

## 6. The bot's auto-improvement goals

The operator's doctrine, the same in every title (`gbox/mercs/core/doctrine.py` holds the words, the weights and the
urgencies):
- **Never stand.** Idle or passive past the hard floor is a violation, and "fight" goes out at once.
- **The combo must never drop:** extend it every 2-5 s. Enemies before statues and time bonuses.
- **On sight, shoot, always shoot.** Relentless magnum / shotgun fire at the 20x fire rate.
- **Never fire at nothing** (`shots_without_target`).
- **Never walk into a wall or a corner.** Wall pressing means navigation is broken, so a wall-stuck report goes to
  Hermes.
- **Explosives on crowds:**
  - grenades, the launcher, mines (RE5) and remote bombs;
  - grenades land on floor, never lava;
  - RE6's flash at most once a minute, in tight spots only (FlashGate), never at heavies.
- **Interrupt wind-ups; dispatch bosses on sight; know where every enemy is** and go and locate them.
- **Every death makes him stronger** (death lessons).

**The loop that improves him without a person in it:**
1. Every round's telemetry and traces feed the automatic reports: damage clusters, incidents, death lessons, and
   wall-stuck reports (pending branch).
2. The operator's critiques arrive as coaching requests.
3. Hermes branches → your gate → main → autodeploy hot reload → the next block plays the change.
4. The tier-a tuner adjusts knobs inside bounds, with a code-change gate and auto-revert (`mercs/tuner.py`,
   `learning.py`; see `gbox-mercs-learning-loop` notes). The loop was "churning, not winning" before: judge every
   change by the numbers below over whole blocks, not single rounds.

**The numbers to watch per title** (bot_sessions / round reports): kills per minute, `max_combo` and
`doctrine_combo_drops`, deaths per block, `hit_rate` / hits, `shots_without_target`, `doctrine_idle_s` /
`doctrine_passive_s` / `stand_breaks`, `walls_pressed` / `unwalls` / `wall_stuck_*`, `nade_choices` and grenade kills,
flank count, and time to the first kill. A merge that moves these the wrong way over a block gets reverted, whatever
its tests say.

## 7. One bot for RE4, RE5 and RE6, reusable for other titles

The operator, 2026-11-10: *"I want the same aimbot I am critiquing in RE4 to improve across 5 and 6 despite their
differences."* The design is `system/docs/research/universal-mercs-architecture.md` (read §9 and §10).

### 7.1 The shape
- **`gbox/mercs/core/`: the universal bot**
  - `combat.py`: bodies, NotInControl, Threats, the target scorer, IdleGuard and `TitleProfile`;
  - `doctrine.py`: the goals, weights and Director;
  - `respond.py`: the doctrine's answer to a threat;
  - `room_map.py`: walls, floor, walk_block and line of sight;
  - `aim_book.py`: per-shot truth and learning from every miss;
  - `fire_pattern.py`: the PS3 magnum's rapid repeat and scatter on every title;
  - `flash_window.py`, `menu_pace.py`, `control_axes.py` (the behavior wheel), `death_lessons.py`.
- **`gbox/mercs/titles/re4_switch.py`, `re5_switch*.py`, `re6_switch.py`: thin title adapters.** Each provides the
  RAM driver (snapshot), its `combat_profile()`, the controls, and only the rules that differ. Each has
  `UNIVERSAL_CORE = True`.
- **Dispatch:** the `mercs_bot` playbook → `gbox/mercs/engine.py` → the title's driver and Bot, picked by the running
  title.
  - MercMode's warm pool keeps the next title prelaunched, so a title swap is seamless.
  - The engine and the core are shared, so an improvement in core lands in all three on their next session.

### 7.2 What differs (the only things a title should own)
| | RE4 Switch | RE5 Switch | RE6 Switch |
|---|---|---|---|
| Units | mm (×10 cm) | cm | cm |
| Controls | tank: left stick turns the body; aim with ZL + right stick; quick turn | Type D: right stick turns the body (gun down) / aims (gun up) | camera-relative left stick; right stick camera/aim |
| Aim model | body heading, no laser ray, no pitch; learned turn sign | laser ray (RAM) | laser / camera line / geometry fire |
| Trigger | tapped (`FIRE_GAP_S`) | held | tapped / held, native cooldown |
| Enemy reads | one Ganado class; heavies by hp_max | motion byte + attack flag | action names (wind-ups) |
| Rules | Mercenaries time bonuses; melee follow-up; knife; Krauser's bow; ladders / drops as nav links | mines (always), statues / time bonuses, dynamite, flash on crowds, character specials | quick shot / kick, QTE finishers, remote bombs, the grenade burst, lava (floor-only throws), FlashGate |
| Grenades | the grenade lane (G3: hand 0xB05B00, incendiary 0xB05B58, flash 0xB05BB0 in the class table) | flash / frag / incendiary on the crowd; FLASH_WINDOW | burst of 5 at burst speed when surrounded; one flash a minute |

**Rule for every change:**
- A behavior that is the operator's universal advice goes in `core/`, with the per-title numbers in `TitleProfile`.
- A title file only translates: units, keys and RAM.
- When you change core, run all three title suites.
- When a title has a capability the others lack (RE5's threat memory, RE6's no-hit line-of-sight block, RE4's
  shots-without-effect page), the next step is to lift it into core (the "Stage B" plan in §9.5 of the architecture
  doc).

### 7.3 Efficient dispatch across titles
- **One engine:**
  - keep per-tick work bounded, since the Spark also runs Pine and the encoder;
  - cache map queries;
  - never scan the store on a hot path;
  - never add a second capture.
- **Read title constants through the profile,** so a knob turned live is in the next profile and no title needs a
  restart.
- **New shared modules** are imported at load (the hot-reload trap).
- **Prefer RAM writes for instant effects** (weapon / item swaps: the operator never wants to see the item screen).
  Write tables once per boot and verify they read back: the boot fire-table retry exists because a write that read 0
  was marked done.

### 7.4 Bringing the bot to another title
1. **Decryption lab** (section 4): an adapter entry, then identify / extract / disassemble / fields / verify, to get
   a confirmed RAM map (player pos/rot/hp, enemy list, combo/score/clock, weapon/item tables).
2. **A driver:** a snapshot in the common shape (player pos, enemies with pos/hp, kills, combo) plus
   `doctrine_view` if it differs.
3. **A `TitleProfile` / `combat_profile()`:** units, sticks, aim model, raise time and tolerance, trigger, bodies,
   level height, specials, the page key.
4. **Controls through `control_axes`;** a room map from the stage collision (`mercs_map_gen.py`, #9528, makes the
   one `gbox.mercs_map/1` format).
5. **A title adapter of rule differences only;** then a MercMode catalog entry (modes, characters, stages).

Merc3D (3DS) and the PS3 / GC editions are the next candidates. The operator parked PS3 / GC for rotation, but the
universal core must still drive them.

## 8. The immediate priorities, in order

1. **Never face a wall.** Merge and verify the wall-stuck auto-reports (section 9) and keep the reported tickets at
   the top of Hermes' list. Verify RE4's tangent unwall live: no swivel, `walls_pressed` down, no corner deaths.
2. **Grenades at the enemies,** every title. Finish the grenade lane (`DEEPSEEK-GRENADE-RING-CHECKPOINTS-2026-11-10.md`:
   E/G checkpoints, the RE4 harness after the restart). Measure grenades thrown per crowd and kills per grenade.
   Never a self-blast, never lava.
3. **The combo never lost:** `doctrine_combo_drops` toward 0. Kill every ~3 s, enemies before statues.
4. **Relentless heavy fire:**
   - RE4: a magnum or shotgun every round at 20x, with the fire tables verified per boot and per round;
   - RE5 / RE6: the aim books;
   - never fire at nothing.
5. **Characters:**
   - merge the normals fix, then rebuild the affected builds;
   - merge the donor rotation and apply its settings;
   - keep new random casts coming from the library (fit gate always).
6. **Re-ticket the reverted intents** (5.4) against main's current code.
7. **PSO** (CP0-CP19) and the **i9 service node / local LLM** (section 4).

## 9. Work in flight at hand-off

Each item is a branch on its own worktree. Review it, gate it (5.3), merge it, and log it.

- **`wt-wallreport-20261110`**: wall pressing for more than 3 s files a CODE-CHANGE report to Hermes, with the map,
  nav and bot-logic evidence, deduped per spot and rate-capped.
- **`wt-normals-20261110`**: the donor normals root cause and fix, plus the list of builds to rebuild and the exact
  rebuild calls.
- **`wt-donorrot-20261110`**: donor rotation per block (pool / fresh), the hot-swap verdict, and the live settings
  body to apply after deploy.
- **`assim-hermes-research-20261110`**: the non-MercMode Hermes research branches merged by the procedure above.

The status of each is in the log entry dated 2026-11-11 in `DEEPSEEK-HANDOFF-2026-11-10-NIGHT.md`.
