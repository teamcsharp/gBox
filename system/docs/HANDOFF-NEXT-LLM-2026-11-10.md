# Handoff to the next LLM: finish MercMode + the character swapper for RE 4/5/6

> Written 2026-11-10 as a single paste-in brief. You are the *next* LLM: you were handed this
> document cold, with no other context. Everything you need to start is here; the deep details and full
> history are in the linked documents on this disk. Where this document and a linked one disagree, the
> linked one (dated later) is newer; where a live reading disagrees with both, the live reading wins.

## Who and what

This is the gBox project. The operator runs an automated retro-game modding + bot-playing system. The
work you are being asked to continue is one effort with one goal, in the operator's own words:

> "I want mercmode and the character swapper fully assembled and working in mercmode for RE 4/5/6."
> "A different Mario/Sonic character per round." "The zombies need to be replaced with random characters
> from the database." "Instead of building roms over and over, I want the system patching a build or series
> of builds across titles." "Multiple characters and stages transitioning." "The ROMs on the lilspark itself
> so it is ironclad."

The games are the Switch ports of Resident Evil 4/5/6, played inside Mercenaries ("MercMode") by an
automated bot, in a custom emulator called Eden, all running on a machine called **lilspark**
(`http://10.89.1.246:8765`, its one Switch emulator). Playback is driven by a control plane that exposes
`POST /api/mercmode` and related endpoints.

## The strategy: overlays, not ROMs

Nothing is ever re-encrypted or re-flashed. Each "build" is a folder of *only the changed files*, laid over
the untouched NSP at boot via LayeredFS (ExeFS code patches included). A "series of builds across titles" is
just a set of those folders, tracked per-file with backups and revert (the `switch_mods` tool). This already
works — every result below used it.

- **A different player character per round = a different roster slot of the same boot.** Each Mercenaries
  character/costume is its own archive. Fill every slot of one overlay with a different donor, and the bot's
  normal menu pick shows a different character each round, no restart.
- **Different zombies = one donor per enemy-class archive.** A stage draws a handful of enemy classes at once,
  so several donors appear on screen together.
- **Random zombies per round without a reboot** is one untested experiment (the "hot-swap" experiment, package
  B below): Eden holds one open file handle on the overlay and reads on demand, so an *in-place, same-size*
  overwrite of an enemy archive between rounds may change the next round with no reload. Untested.
- **Live changes mid-round are RAM, not files.** Fire rate, weapons, loadouts, clock, health already go through
  live controls. Swapping a mesh mid-round is research, not a build step.

## What is proven vs. not

**Proven live on lilspark (with session ids / hashes / frame artifacts on record):**
- Sonic (SA2) as the player in RE5, Chris (BSAA) slot — build `recovery-sonic-native-grip-v15-20261109`.
- Mario (SM64 DS) as the town Majini enemy in RE5 — build `recovery-mario-em10-v1-test-20261109`, `uEm10.arc`
  `322c58a1…`, session `a66b9d370de14727-98b48cb5b2b74d45` (199 kills / 9 min, real gameplay frames).
- Rounds change stage inside one session, no restart (seven rounds, six stages).
- Ryo Hazuki (Shenmue) drawn live as the player by the *generic* cast writer — session
  `0a61e625f9d844d6-3ddd04616ed846de`, build `recovery-cast-pool-03-chris-test-20261109`.
- The first-ever edited `uEm11` (Amy and Claude) loaded; enemy pool overlays with ten donors on one class.
- The bot fights instead of idling (26–29 kills/minute), routes on the stage's own nav mesh, seeks enemies,
  plants mines read from the game's memory.
- One observed map-to-enemy goal: the operator clicked an enemy and the bot ran to it and killed it
  (`0a61e625f9d844d6-c7110e927fb64024`).

**Not proven / not to be described as done:** a *different* character per round from a full roster; *random*
zombies every match; RE6 colours (only solved on paper); *anything* in RE4 (no writer yet); a six-slot cast;
hot-swap of an archive inside a running session.

## Current live state (what lilspark is doing right now — verify before acting)

MercMode, RE5 Switch No Mercy, a repeating queue over six stages. Builds move at round boundaries; the
control plane ("main", commit `a828db36` or later, plus bot commits `e70fad25`, `7211ca76`, …) carries all the
recent work. `doctrine.ROUND_CAP_S = 0` — rounds end by death or the kill goal, not a timer.

Started but unfinished at handover: QUEUE a fixed build for the six-slot cast and enemy-pool overlays;
the enemy-mix "several donors in one round" test; the RE6 colour probe boots; the RE4 first boots; the
hot-swap experiment. See the packages below.

## The exact work, as parallel packages (A–I)

These are the bounded packages from the DeepSeek task guide (`DEEPSEEK-TASK-GUIDE-2026-11-09.md`), condensed.
Each has an acceptance test. "LIVE" means it needs lilspark's one emulator lane — only one at a time.

- **A (LIVE, highest value first).** Boot what's already built: `recovery-enemy-mix-v1-test-20261109`, then the
  RE4 candidates in the order in `research/re4-switch-model-replacement.md` (control → rewrite → native swap →
  Sonic on Leon), then each cast/enemy/RE6 overlay the other agents deliver. *Accept:* session id + build + two
  stored gameplay frames + the receipt's predicted observation answered yes/no.
- **B (LIVE).** The hot-swap experiment with probe build `recovery-hotswap-probe-20261109`, then a
  `switch_mods op=hotswap` if it holds. *Accept:* two frames of ONE session, before and after, no process
  restart.
- **C (OFFLINE→LIVE).** The cast playlist generator (beside `gbox/mercmode.py`): turns accepted rows into queue
  entries, different character per round, hero/horde swap across franchises. *Accept:* three rounds, three
  characters, one title, no restart.
- **D (LIVE).** RE6 on the Spark: move the save aside at its real path (see corrections below), one vanilla
  stage load, bot through menus, live frames for the colour probes. *Accept:* a bot-played No Mercy round with
  Sonic on Leon, score/kills advancing, in a queue alternating RE5 and RE6.
- **E (OFFLINE→LIVE).** The bot finds and finishes everything: route across floors on the mesh itself, mount the
  last-five-enemies, get `doctrine_idle_s` under 10 %, tie measures into the tuner. *Accept:* three consecutive
  Public Assembly rounds ending on the kill goal with before/after numbers, no operator command.
- **F (LIVE).** Measure mines-with-flash over ten rounds. *Accept:* numbers on bombs, gaps, flashes, health lost
  per bomb, deaths within 5 s of a bomb; a concrete next-step proposal with numbers if the flash is insufficient.
- **G (OFFLINE).** Every remaining enemy class / stage, once ticket #9074's archive tables are in.
- **H (OFFLINE).** ROMs stay playable without the NAS: never-purge flags, second off-NVMe copy, one deliberate
  unmount + launch test.
- **I (OFFLINE).** Get finished Hermes work onto main (136 PRs / 32 branches stuck; reviewer caps at 150 KB).

## Rules you must not relearn the hard way

- **One live lane.** One Switch emulator on lilspark; only LIVE packages use it, one at a time, and only
  through the queue so MercMode resumes by itself. Never stop a session whose launch actor is `operator`.
- **Do not rebuild ROMs.** Builds only through `switch_mods op=write`, always a separate `recovery-*` test
  build. Upload files via `POST /api/artifacts`.
- **Do not test on the operator PC.** Agent test sessions run only on lilspark or the Spark box while idle, at 2 %
  audio. Preserve original games and saves.
- **Never print the API token.** Use `Authorization: Bearer <sys...>` + `x-gbox-actor: agent`; in Git Bash set
  `MSYS_NO_PATHCONV=1` before `/api/...` paths.
- **Hot-reload trap:** the reload only tracks modules loaded at worker start; import new shared bot modules at the
  top of a start-loaded module. `gbox.mercs.directives` never hot-reloads.
- **A worker with a job in flight is "busy"** and MercMode starts no next round. Stop polling jobs at session end.
- **Honesty:** a boot is not acceptance; a title screen is not gameplay; an offline render is not a live frame.
  Every claim carries session id, build, hashes, and frame artifacts.
- **Bot safety:** never merge a change that makes the bot stand still, hold fire, or stop healing among enemies.

## Corrections to earlier handovers (these cost real hours)

- The RE6 handover's save path and its `pkill -f gbox` recovery are **both wrong** — do not run them. The real
  RE6 save dir is `…/eden/nand/user/save/0000000000000000/86D8304D23A3AC808BC2AA4890B84EF9/01002A000CD48000`.
- On the Spark's share there are files `main` does not have (`gbox/mercs/tactical.py`, `re5_switch_nav.py`
  edited 2026-10-31, since restored). Before relying on a deployed change, hash the share's file against `git
  show HEAD:…` and read the share version first — it may be newer.
- `doctrine.ROUND_CAP_S = 0` (the earlier six-minute cap was withdrawn).
- The mine probe must read one job per sample and be stopped across rounds; don't leave probes running.
- Eden hangs black on ~4 of 9 boots (scheduler recovers ~2 min). Fewer boots is the mitigation, not a fix.

## Where the details live (on this disk)

- `CHARACTER-REPLACEMENT-PLAN-2026-11-09.md` — the master "what is proven / the path / open problems" (fresh as of
  `c5972da2`).
- `DEEPSEEK-TASK-GUIDE-2026-11-09.md` — the full packages A–I with acceptance tests, op-by-op (this document
  condenses it; read §1–§3 once, then your package).
- `PROJECT-MANAGER-HANDOVER-2026-11-09.md`, `re6-switch-handover.md`, `DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md` —
  older context, superseded where they disagree with the above.
- `research/re4-switch-model-replacement.md`, `research/…` under `system/docs/research/` — per-title boot order
  and expected observations.
- `switch_mods`, `mercmode.py` (control plane), `gbox/mercs/core/doctrine.py` (bot universal rules),
  `gbox/mercs/titles/re5_switch*.py` — the code.

## What "done" means

The operator's sentence, satisfied: MercMode and the character swapper fully working for RE 4/5/6; random
characters from the database as both player and zombies, different every round, across all stages and titles;
the ROMs local and ironclad on lilspark; the bot never idle, always engaging, extending the combo, with mines.
Each package's acceptance test is the concrete check. A PR or a boot is not acceptance — the acceptance is the
live frame or the measured round, with ids and hashes on record.
