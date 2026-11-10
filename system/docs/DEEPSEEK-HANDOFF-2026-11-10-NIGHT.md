# DeepSeek hand-off, 2026-11-10 night: you run the project until 2026-11-16

The coordinating Claude session is offline until 2026-11-16 (the operator's usage). The operator, 18:20:

> "bring all the completed progress of the branches and hermes together and prepare to hand it off to the deepseek harness for completion ... I want the i9 to complete and finish the PSO task work fully in the meantime and to dispatch all work through hermes and the i9 gbox kiosk for completion for bot improvements based on my critique. In RE4 the bot is still turning back and forth and is stuck in the same room. I need the bot firing relentlessly with any weapon type magnum or shotgun with rapid fire at these threats instead of getting decimated by them."

## Ground rules: what changes now that you are the PM

**Hands off lilspark still holds:**
- no ssh / sudo / systemctl / kill on the Spark;
- no launches or stops there;
- every gBox API call carries `x-gbox-actor: agent`;
- never print keys.

**New: you may merge to main.** The Spark deploys main itself:
- `~/bin/gbox_autodeploy.sh` runs from cron every 15 minutes and hot-reloads bot modules at each title's next session;
- it restarts gbox.service at 05:00-05:14 when a restart is pending.

So a tested merge to main goes live with nobody touching lilspark. The gate for every merge:
1. Merge current origin/main into the branch.
2. Run the MercMode / RE subset (`system/tests/test_{mercmode,mercs_,re4_,re5_switch,re6_switch,screensaver,tactical}*`, plus the ticket's own tests) on the branch AND on main. Merge only when the branch adds no failure. Known red on main: 10 in RE5 Switch (bonus / giveup / smooth / rampage / threat) and `test_mcp_queue_checkpoint_roundtrip`.
3. Use a plain merge commit. The pre-push guard refuses `system/tools/`; put scripts in `system/scripts/`. No game assets or binaries.
4. Push. If the guard fails on an unknown remote sha, fetch, merge and push again.
5. Note the merge in this doc's log section at the bottom.

**Code needing a restart** (worker or control-plane modules, new modules) goes live at the 05:00 restart. Write that in your note.

## 1. RE4 Switch first (Hermes #9560, `077fe2a1606b4cbc`; fix it yourself if Hermes has not by 2026-11-11)

**Movement: he swivels and stays in the first room.**
- Seen in a bot_trace of session 25385f8f4eb94342-6eb677c2f1194dea: the room map's unwall ("a wall ahead, along it instead") sends a pure sideways stick (lleft, deg 90, no lup).
- RE4 is tank controls, so he turns in place and the walker turns him back.
- Fix in `core/room_map.py` and `titles/re4_walk.py` / `re4_switch.py`:
  - turn to the wall's tangent, then push forward;
  - a probe scaled to the room;
  - no unwall while the route leg is clear (extend ROOM_LEGS to unwall);
  - hysteresis of about 0.8 s on the chosen side;
  - the never-stand step walks forward instead of turning.
- Measure with `system/scripts/bot_trace.py record|draw` replays: facing reversals per minute, net metres per minute.
- The plan is also on #9527.

**Weapons and fire.**
- `gbox-data/mercs/re4-mods.json` is right: fire_rate 20, random_weapon, infinite_ammo, max_level, aim_lock.
- Live telemetry is not: `mods_weapon_given` was 4 for a whole session, and there is no fire-table stat.
- Fix `re4_switch_mods._round_weapon` / `_give_weapon` / `_apply_fire_rate` (rf_applied_boot) so every round gets a magnum or a shotgun (MAGNUM_SHARE toward 1.0, shotguns in the draw) with the 20x tables. Krauser's bow uses the motion-rate route (0d93ebf2).
- The bot fires relentlessly at any Ganado in line of sight within range, and flanks only when there is no line of sight at all.
- Report per round in telemetry: the weapon given, the fire tables written.

## 2. PSO: finish it

Work `DEEPSEEK-PSO-CHECKPOINTS-2026-11-10.md` (CP0-CP19) to the end on the i9, the operator's PSO master goal: all zones and bosses, the combat / build spec, 4 players. Use the 3090. Merge each finished checkpoint to main with the gate above.

## 3. The i9 kiosk: service node + local LLM

Build `DEEPSEEK-HANDOFF-2026-11-10-EVENING.md` sections 1 and 1b:
- service-node readiness (eGPU, gBox running, service_work), registration, and central routing of inbox decryption / analysis tasks;
- the strongest local model on the 3090, measured, serving with high concurrency, registered as a Hermes local node.

Then send it the heavy analysis work.

## 4. Hermes: keep it doing the operator's bot critiques

- **The operator-critique path works since today's merge (258279f8).** A note in the PiP "Critique the bot…" box (or ⚠ Flawed) becomes an `operator_requested` "Improve <title>: coaching note N" request, worked right after the priority list, and not held while that game plays.
- **The Hermes priority list,** set via `POST /api/hermes/queue/priority` with request ids first (saved under the queue's lock since 53cc8962). These are code-change tickets. The "read-and-report" lines in their attached rules block do NOT apply; that was clarified on each ticket.

| Ticket | Work |
|---|---|
| #9560 | RE4 movement + weapons |
| #9531 | model-transfer QA: the RE4 pl0d far body inside-out; the whole donor's normals look inverted to the operator |
| #9533 | universal rig transfer + comparison window |
| #9534 | ladders as nav links; inventory merged |
| #9525 | death lessons; evidence merged: the killer class must be joined from the player_damage logs |
| #9526 | proactive crowds; baseline merged |
| #9527 | no wall hugging / straight runs |
| #9529 | RE5 / RE6 never fire at nothing |
| #9528 | one map format |

- **Each check-in:**
  - read `GET /api/hermes/local/nodes`; `~/.hermes/cron/executions.db` is the Spark's, so ask for counts through gBox's API, not ssh;
  - review the published `hermes/request-*` branches, and merge the good ones with the gate;
  - put new critiques on the list.
- **Nodes:**
  - lilspark2 at 12 lanes (16 overloaded the gateway) and claude at 4;
  - deepseek off (your own harness uses the credit);
  - Z.AI off (quota).

## 5. What is live now (main 76708784)

- RE4: the doorway / detour fixes, the aim book (RAM aim line, sway zeroed, every shot learned), Krauser's bow at the fire_rate multiplier.
- RE5: the flash on the crowd, the flash window (mine, grenade, move, fire), the barrage under the flash clock (your scatter cap), the aim book.
- RE6:
  - FlashGate: one flash a minute, tight situations only, no flash at heavies;
  - fire-first;
  - grenades only onto floor (never lava);
  - quick commands;
  - the aim book.
- Everywhere:
  - the menu pace (the bot starts the tick a game is up);
  - the ComfyUI render-only freeze (for Pine Box);
  - `excluded_platforms`: no PS3 / Xbox / Xbox 360 on lilspark;
  - the patch atlas (`system/docs/patch-atlas/`);
  - the coach pipeline (outbox, retry, operator-first);
  - your grenade CP0.
- The Spark keeps only Switch RE builds. The others are archived in `gbox-data/patch-library` with their manifests and payloads.

## Log (append your merges here)

- 2026-11-10 18:25: hand-off written by the Claude session; main 76708784.
