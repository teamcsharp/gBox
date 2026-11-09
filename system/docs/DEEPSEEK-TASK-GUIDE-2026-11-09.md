# DeepSeek task guide: MercMode cast replacement and the bot, parallel work packages (2026-11-09)

Written for DeepSeek sessions the operator dispatches in parallel. Each package below stands on its own: take one,
do it to its acceptance test, report with ids and hashes. Read §1 to §3 once, then your package.

Background, with every result's session id and hash: [the replacement plan](CHARACTER-REPLACEMENT-PLAN-2026-11-09.md).
Older context: [the project-manager handover](PROJECT-MANAGER-HANDOVER-2026-11-09.md),
[the RE6 Switch handover](re6-switch-handover.md), [the continuation guide](DEEPSEEK-LIVE-REPLACEMENT-HANDOFF.md).
Where they disagree with this guide, this guide is newer; where a live reading disagrees with any of them, the live
reading wins.

---

## 1. What the operator wants (their words, 2026-11-09)

- "I want mercmode and the character swapper fully assembled and working in mercmode for RE 4/5/6."
- "I want rounds to alternate who is the zombie and who is the player. I want to see all the different types of
  characters extracted showing up in the game randomly ... multiple different characters in a round instead of just
  one single enemy type. Sometimes I want the player to be Mario and other times, Snake or DOA characters. Everyone
  extracted should be randomly showing up in matches of merc mode across all titles and all stages and characters."
- "Instead of building roms over and over and over, I want the system patching a build or series of builds across
  titles for mercmode."
- The bot, on every title: never idle; always moving and engaging; "on sight, shoot, always shoot"; the combo extended
  every 2 to 5 seconds; bosses on sight; attack wind-ups shot or interrupted; explosives into mobs.
- "The bot needs to identify on the map where enemies are and go dispatch them. If they are high or low. Aim at them
  and dispatch them. Throw grenades at them. Place mines around them. Spray them with magnum fire."
- "Mines are non negotiable ... I want it placing mines. Then flashbanging and running away and getting distance. I
  want the bot always placing mines." "The bot should place themself at least 15 meters from the mine." "Have him force
  his way out." "The bot needs to learn and improve and self improve."
- Rounds: "mercenaries typically ends with either death or the kill goal ... If they dispatch all foes, the match will
  end." No artificial round timer.
- "For the titles in merc mode, I want those roms on the lilspark itself so it is ironclad."

Approved by the operator on 2026-11-09: short test boots that interrupt the RE5 stream, and moving the RE6 save aside
(kept as a backup) to fix its stage-load crash. spark2's Hermes lanes stay on the replacement tickets first.

---

## 2. State when this was written (2026-11-09, about 18:30 UTC, main at `6ba84682` or later)

**Live on lilspark** (`http://10.89.1.246:8765`, the one Switch emulator): MercMode, RE5 Switch No Mercy, repeating
queue of six stages on build `recovery-enemy-mix-v1-test-20261109` (queued; it loads at the next round boundary; the
running session was still on `recovery-mario-em10-v1-test-20261109`). Rounds change stage inside one session.

**Proven live today**
- Sonic (SA2) as the player, Chris (BSAA) slot: `recovery-sonic-native-grip-v15-20261109`, archive `d96c9c9e…`.
- Mario (SM64 DS) as the town Majini: `recovery-mario-em10-v1-test-20261109`, `uEm10.arc` `322c58a1…`, session
  `a66b9d370de14727-98b48cb5b2b74d45`; frames `ae1cfd35…`, `5d5915e4…`, `a2ae198e…`, `630b28b9…` in the artifact store.
- Seven rounds over six stages in one session, no restart.
- Mines read from the game's memory (bomb 0x10A in inventory, new `uWp0a` actors), `system/scripts/re5_mine_probe.py`.
- The bot at 26 to 29 kills a minute after the quick-turn fix; routes on the stage's own nav mesh; goes to find enemies
  when none is in sight.

**Built offline, never booted** (all under `C:\_tools\gBox\.scratch-merc-recovery\assets\`, each with `receipt.json`)
- `enemy-mix-v1/` : ten donors on the pants option groups of the ONE class `uEm10` (`a8b7fdde…`). Queued for its first
  boot as `recovery-enemy-mix-v1-test-20261109`. Read its receipt for what a live frame must show.
- `re4/sonic-on-leon-v1/`, `re4/native-swap-v1-control/`, `re4/native-rewrite-v1/`, `re4/native-swap-v1/` : RE4 Switch
  candidates (`system/docs/research/re4-switch-model-replacement.md` gives the boot order and what each must show).
- In progress by other agents (do not duplicate; their branches are `wt-re5-cast-20261109`, `wt-re5-enemy-20261109`,
  `wt-re6-switch-20261109`): six-slot RE5 player cast pools, ranked Sonic alternatives, enemy pools and per-stage
  archive table, RE6 colour path and roster.

**Hermes / spark2**: one node `lilspark2`, 12 lanes; tickets #9074 to #9079 (archive catalogues and the donor audit)
are first in its queue and write only under `system/docs/research/`.

**Known broken or unverified**: Eden hangs black on roughly 4 of 9 boots (the scheduler recovers in about two
minutes); RE6 stage loads on the Spark; RE4's bot walks to a round but cannot fight; mine self-damage with the new
flash is not measured; `doctrine_idle_s` still ran about 40 % of play; red tests on main that predate today (11 in
`test_re5_switch_(bonus|bonus_giveup|rampage|smooth|threat).py`, 17 in `test_re6_switch.py`, 3 in the PS3 mine files,
1 in `test_mercs_tuner.py`).

---

## 3. Rules for every package

**Parallel work without collisions**
- One git worktree and branch per session: `git worktree add ../gBox-ds-<package> -b ds-<package>-<date> origin/main`.
  Never edit the shared checkout another session uses. Merge to `main` with a merge commit only after the tests named
  in your package pass on the merged result; push; say what you pushed.
- **One live lane.** lilspark has one Switch emulator, and the operator watches it. Only packages marked LIVE may use
  it, one at a time. Take it through MercMode's queue (`POST /api/mercmode`, an entry with your build) so the next
  round boundary loads your build and MercMode resumes by itself afterwards. A direct swap is refused while the
  operator watches the stream; that is intended. Never stop a session whose launch actor is `operator`.
- Offline packages need no coordination.

**The system**
- API: `Authorization: Bearer <system/gbox-data/api_token>` and `x-gbox-actor: agent` on every call. Never print the
  token. In Git Bash set `MSYS_NO_PATHCONV=1` before passing `/api/...` paths.
- Python: `.venv-session-audit\Scripts\python.exe`; tests from the repo root with
  `PYTHONPATH="system;system/tests"` and `-m pytest -q -p no:cacheprovider --disable-warnings`.
- Deploy: `ssh spark '~/bin/gbox_autodeploy.sh'` syncs `main` to the Spark and hot-reloads changed bot modules with no
  loading screen. Control-plane files (server, scheduler, tools, `switch_mods`) take effect at the 05:00 CST restart;
  restart by hand only when nothing is playing, and never while an emulator of the operator's runs.
- **Hot-reload trap**: the reload only tracks modules loaded when the worker started. Import a new shared bot module at
  the top of a module that loads at start; a symbol first needed from an untracked module raises on every tick and
  ends the run (it did, at 290 kills). `gbox.mercs.directives` never hot-reloads.
- **A worker with a job in flight is "busy" to MercMode**, which then starts no next round. Do not leave polling jobs
  running across rounds; stop them when the session ends.
- Builds: only through `switch_mods` (`op=write` with artifacts), always a separate `recovery-*` test build, never into
  an accepted build. Upload files with `POST /api/artifacts`. No ROM is ever rebuilt.
- Do not run the recovery block of the RE6 handover as written (wrong save path; `pkill -f gbox` kills the service).

**The bot**
- The universal rules live in `system/gbox/mercs/core/doctrine.py` (goals, weights, the measures `doctrine_*`). A bot
  change that makes any bot stand still, hold position, hold fire or stop healing among enemies is not acceptable; say
  so instead of merging it. New universal advice becomes a rule there, not a constant in one title.
- Judge every bot change by numbers over at least five minutes of play before and after: kills a minute,
  `doctrine_idle_s`, `doctrine_passive_s`, `doctrine_engaged_pct`, `mine_blast_hp_loss`, deaths.

**Honesty**
- A boot is not acceptance, a title screen is not gameplay, a structural check is not a visible replacement, an
  offline render is not a live frame. Every claim carries the session id, the build, the hashes and frames.
- Say what you ran and what you inferred. Report anything you changed that the package did not ask for.

---

## 4. The packages

### A. LIVE - first boots of what is already built (highest value, smallest work)

1. `recovery-enemy-mix-v1-test-20261109` (queued). Wait for it to load, then count the town Majini by character over a
   Public Assembly round. Right: several different whole characters at once, none doubled, none body-less. Wrong: all
   one character, enemies with hits but no body, two characters in one enemy, or stock parts. The receipt in
   `enemy-mix-v1/` lists each outcome and what it means. Tell the enemy agent's branch owner the result.
2. RE4 Switch, in the order of `re4-switch-model-replacement.md`: control, rewrite, native swap, Sonic on Leon. Upload
   `em/pl08.udas` (and for Sonic `imagepackhd/01000008.pack.fen`) as artifacts, `switch_mods op=write` under the RE4
   Switch game id with paths `romfs/bio4/…`, queue one MercMode entry for RE4 with the build, read a frame once the bot
   has walked into the round as Leon.
3. Each cast, enemy-pool and RE6 overlay the other agents deliver: same procedure.

Accept each on: session id, build, two gameplay frames stored as artifacts, and the receipt's predicted observation
answered yes or no.

### B. LIVE - the hot-swap experiment, then the op for it

Question: does a changed overlay file show at the next stage load without restarting the title? Known: Eden holds one
open handle on the overlay archive and reads it from disk on demand; a rename would not be seen, an in-place overwrite
of the same size would. Unknown: whether the game re-reads the archive each round.

- Probe build `recovery-hotswap-probe-20261109` exists (player archive: the accepted Sheva-in-Chris, 51,175,777 bytes).
  The v15 Sonic archive is 42,754,831 bytes and fits when padded with zeros to the same size.
- Boot the probe through the queue, play a round, and at the results screen overwrite the file in place on lilspark
  (`dd conv=notrunc`, then zero-fill to the original length; same inode, same size), never during a round.
- Accept on two frames of ONE session, before and after, with no process restart between them. Report both ways.
- If it holds: add `switch_mods op=hotswap` (refuses during a round, refuses a larger file, keeps the manifest and the
  history true), and build-time padding of every slot to one fixed size per slot.

### C. OFFLINE then LIVE - the cast playlist (what makes rounds differ)

A generator that turns a registry of booted-and-accepted rows (title, build, player slot, donor, stage) into MercMode
queue entries: a different player character every round, stages in rotation, titles in turn, and the franchise that
supplied the player last round supplying enemies this round. Seeded and recorded so a round can be named and replayed.
It lives beside `gbox/mercmode.py` (control plane) with tests in `system/tests/test_mercmode*.py`. Use only accepted
rows; an unbooted overlay never enters the playlist. Accept on a live queue that plays three rounds with three
different player characters inside one title without a restart, and one hero/horde swap across two builds.

### D. LIVE - RE6 on the Spark

1. Move the save aside (approved): the directory is
   `~/gBox/system/gbox-data/runtime-linux-aarch64/eden-linux/data/eden/nand/user/save/0000000000000000/86D8304D23A3AC808BC2AA4890B84EF9/01002A000CD48000`;
   rename it with a `.bak-<date>` suffix, never delete.
2. One vanilla launch: title, then a Mercenaries stage load that does not end the session.
3. The bot through the menus to a round (`re6_switch.fast_start`; plain `up/down/left/right` keys).
4. A live frame for each probe the RE6 agent delivers, and the colour decision that follows.
5. RE6's bot only takes the `explore` / `next_area` commands; make it take `fight`, `score`, `hunt` and `mine` the way
   RE5's does, so the doctrine steers it.

Accept on: a No Mercy round played by the bot with Sonic on Leon, score and kills advancing, in a MercMode queue that
alternates RE5 and RE6 entries.

### E. OFFLINE then LIVE - the bot finds and finishes everything (RE5 first, then shared)

The operator's measure: rounds end by the kill goal, not by standing. Today's state: the bot routes on the native mesh
(`re5_switch._mesh_waypoint`), goes to the nearest enemy by the game's enemy table when none is on his floor
(`_locate`), and for another floor heads for a remembered ladder, ledge or door.

- Route across floors on the mesh itself: `NavMesh.route` returns `Traversal` links (ladders, drops); take them (walk
  to `approach`, the prompt rule presses) instead of only the remembered spots. Record which links the player can take.
- Enemies above or below: aim pitch, grenades and the magnum for the ones he cannot reach.
- Pursue until the stage is empty: the round's remaining count is in the snapshot; the last five enemies are the test.
- Bring `doctrine_idle_s` under 10 % of play. Today's contributors: the mine cycle's pauses, aim waits ("waiting for
  aimed motion"), gun raises that flicker (about 200 a minute), walking that the wall governor strips to a turn.
- Tie the doctrine's measures into the learning loop (`gbox/mercs/tuning.py`, the tier-a tuner with its revert gate):
  trials are judged on kills a minute, `doctrine_idle_s`, deaths and `mine_blast_hp_loss`, so the bot "learns and
  self-improves" on the operator's own goals.

Accept on: three consecutive Public Assembly rounds that end on the kill goal or with every enemy dead, with the
before and after numbers, and no operator command sent.

### F. LIVE measurement - mines with the flash

In force since `6ba84682`: a bomb every 30 s whatever his health, a native flash the moment a bomb is down, a flash to
open the way when an overdue bomb is blocked, the run out by the mesh to 15 m. Measure over ten rounds: bombs planted,
gaps, `mine_flashes`, `mine_preflashes`, health lost per bomb (`mine_blast_hp_loss`), deaths within five seconds of a
bomb. If the flash does not stop the crowd reaching the bomb, propose the next step with the numbers (a longer stun
window, planting ahead of the crowd's path, grenades thrown from range). Do not make mines rarer: the operator's word.

### G. OFFLINE - every remaining enemy class and every stage

When ticket #9074 and the enemy agent's per-stage table are in: tables for the classes each stage draws, donors for
each, overlays, then package A's live frames per stage. The executioner and the other specials are part of it.

### H. OFFLINE - the ROMs stay playable without the NAS

`catalog.local_copy` (merged) makes a launch use the Spark's staged copy when the share is down. Still to do: mark
`~/gBox_alt/switch/` and the three titles' cache copies never-purge in the storage policy, with a test; a second copy
off the NVMe; and, in a window, unmount the NAS share on purpose and watch one launch of each title.

### I. OFFLINE - getting finished Hermes work onto main

136 open pull requests and 32 branches never reached main: the reviewer cannot read files over 150 KB (the big bot
files are 300 to 430 KB), the pull-request pause is still armed, seven queue items are stuck "queued" since October,
and the Hermes config still names a node that no longer exists. Fix the pipeline, not the backlog by hand. Held on
purpose because they make a bot stand, hold fire or stop healing: #5051, #5128, #5126, #5127, #5077, #5137.

---

## 5. What to send back for each package

The branch and commits; what was pushed to `main`; for live work the session ids, builds, hashes and frame artifact
ids; the acceptance test answered yes or no; the numbers before and after for anything touching the bot; what you
could not do and why; and anything you changed that the package did not ask for.
