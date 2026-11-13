# DeepSeek takeover: RE4/5/6 MercMode, Spark decompilation and live replacement

Prepared 2026-11-12 America/Chicago (latest live check 2026-11-13 00:22 UTC).
Workspace: `C:\_tools\gBox`. HEAD at preparation: `f8b13f2742481ccd20ae87c329fe76f6cea824e8`.

**Current ownership: Codex continues implementation, testing, deployment and live validation.** The operator
superseded the earlier immediate DeepSeek takeover: "do the work i asked for" and "I want all the work i described
done by you until your usage is exhausted". DeepSeek receives the remaining work only when this continuation ends. This file records the current task; older handoffs supply evidence and implementation context.
It supersedes conflicting older task directions, including RE5-only playback, a pinned single-title queue,
quick-death exemptions from round counting, and shared enemy-class replacements as the final result.

## Start here

1. Read the operator requirements and clarifications below before dispatching work.
2. Preserve the dirty working tree. Review the in-progress local changes before editing or deploying them.
3. Inspect current Spark jobs, Ghidra program ownership and MercMode state. Do not launch competing analysis against
   the shared bridge, stop another terminal's work, or assume this document's worker/session IDs remain current.
4. Dispatch the independent packages below. Serialize operations that switch the shared Ghidra program.
5. Keep a durable checklist and receipts. Report incomplete coverage and failed probes explicitly. The user wants
   the actual behavior in the running games, not just flags, exporters, partial casts or successful job submission.

## Operator clarifications: authoritative answers

These were answered directly during handoff preparation:

| Question | Operator's answer / required behavior |
|---|---|
| Who continues? | Earlier: DeepSeek after handoff. **Latest instruction: Codex continues until its usage is exhausted; preserve this document for eventual DeepSeek continuation.** |
| What counts toward five rounds? | **Every completed attempt counts, including deaths.** Remove the current quick-death retry exemption. Failed launches that never enter a round are not completed attempts. |
| May titles restart between rounds? | **Yes: "do whatever you have to in order to complete the task. yes."** Restarts are an allowed intermediate mechanism; true live replacement remains requested. This does not establish that a restart is live hot reload. |
| Which enemies get replaced? | **Every enemy type, including bosses, dogs, parasites and other nonhuman enemies.** Humanoid-only coverage is incomplete. |
| Shared donor per enemy class? | **Each individual enemy should draw its own model.** A class-wide archive replacement alone does not satisfy this. |
| Round counts? | **Separate counts for RE4, RE5 and RE6, initially five each, set through GBox's right-click menu.** One shared setting alone is incomplete. |

Independent per-instance random draws are required. Global uniqueness across all enemies was not separately
specified; do not silently substitute one donor per class. Persist the actual instance assignments for inspection.

## The user's requests, preserved in their own words

The user asked that their "rantings" be included so DeepSeek can continue where this session stopped. These are
product requirements and observed failures, not optional suggestions. Preserve their emphasis on complete coverage,
visible changes every round, and a bot that survives and improves.

> So I want RE4/5/6 cycling in merc mode playing 5 rounds apiece. Every round in every match in every game, I want the models being used for the character and the enemies being randomized and swapped out showing different models from the library. Gbox should be extracting the models of every game marked favorite and those models should be cycled into rotation for merc mode as either the characters of zombies. I need the character to have a random loadout and weapon each and every round. If they are given a pistol make sure they have a 20x fire rate with no recoil and infinite ammo. I want the bot learning and prioritizing enemies who killed them in previous rounds seeking to dispatch them quickly and to avoid the same termination. I need the bot able to learn and understand and prioritize decimating boss level opponents so they dont use an instant kill move on them. I want to specify in the right click menu of gbox during merc mode how many matches are played per title and make sure that it plays across all the titles. A handoff document has been prepared in 07c0e8a01710cf1d60b2e6d3810e076fa2688781

> across all titles in all games, I need all zombies replaced, for characters I want random characters on 4 and 5. For 6, I like the randomized costumes. Keep that but replace every zombie with a model and make sure all characters are swapped.

> also look into the autobot with RE4 and why its unable to rapid fire with the pistol on crowds to protect itself. I notice it will fail to control crowds or use a grenade ring to protect itself every minute and a half. I need the bot learning and improving and capable of using first aid sprays and also using randomized weapons each and every round of RE4 with it learning more towards shotguns, magnums and late game campaign weapons. The bot should be depoloying a grenade or mine thrower ring of bombs every minute and a half.

> this is why these games are supposed to be decompiled fully on the spark so they can have their game data and models replaced more fluidly without rebuilding the game all the time. I want to eventually combine these titles and make and insert custom levels in them so the gbox system needs to decompile them fully on the spark and have them fully capable of live model replacement and gidra hooking.

> when you are handing the tasks back off to deepseek for dispatch mention my rantings so it is able to continue where you leave off or are unable to

> i want to be able to handoff the decompiling to the deepseek terminal who is also working on the project.

The current runtime targets are the Switch editions of RE4/5/6 on lilspark. Extracting assets from **every favorite
game** is a separate library-wide requirement. Preserve RE6's existing costume randomization while replacing its
entire player roster's models; randomize native player choices in RE4/5. Combining titles and inserting custom levels
is the stated longer-term goal: retain level-loader, collision, navigation, spawn and resource findings for that work.

## Current implementation checkpoint (continuing, not a completed handoff)

Local code now includes separate default-five title counts, every completed attempt counting (including quick deaths),
preserved cold next-round donor promises, RE4/5 native-character randomization, first-death lessons with duplicate
suppression, RE4 pitch stabilization when yaw is already aligned, shorter fire input holds, persistent per-round weapon
selection with bounded retries, crowd shotgun selection and exclusive Mine Thrower ring ownership. The ring has a
10 m defense radius, failed equip does not fire the wrong weapon or consume its 90-second cooldown, and success
restores the previous weapon. Actual projectile/effect observations still require live verification.

Native research found **player update `0x311400` explicitly calls vtable slot `+0xA0`**, whose pinned callback is
`0x312600`. The old `+0x20` transform trigger produced zero ticks live. The new dispatcher uses `+0xA0`, preserves
player tracking while its clone is installed, and is serialized across automatic healing and manual blasts.

The actual item-use function is `0x297AB0(cItemMgr*, cItem*)`; manager is `main+0x124D918`, item records are 14 bytes,
and First Aid Spray is ID 5. It adds 2400 HP up to the maximum, consumes one item, and clears the slot if empty.
Recipient is manager `+0x1A` (distinct from inventory owner `+0x1B`). The new `first_aid.S` wrapper validates player
identity, active Mercenaries state, inventory allocation/slot/type/owner/count, and living damaged HP on the game thread.
It temporarily selects the player recipient, calls native use, restores recipient, and retains one spray in reserve.
Automatic low-health use replaces the old threshold direct-HP write; explicit Unlimited life remains a separate mod.
The new First aid button uses durable intervention receipts. No live native-heal success is claimed yet.

Ghidra title routing no longer chooses RE5 first for every session. Queries pin the correct executable path and SHA.
The resumable exporter records every discovered function, checkpoints success/error/timeout separately, verifies
cached files and loaded/source identity, resumes strings, and never treats failed pseudocode as success. The latest
RE5 analysis job `c1c2bd3d7f1045f5` succeeded with 20,835 discovered functions after about 41 minutes. Export remains
pending. RE4's correctly mapped existing Ghidra 12.2 project is `~/gBox_alt/ghidra-projects/re4elf`, program `main.elf`,
9,550 discovered functions; its older `re4sw/main.bin` raw-NSO project has wrong offset mapping and must not be used.
RE4 ELF SHA-256: `c8e8f22f9996b7d6de8913133c791579dc0e6df43d32ef9478dd13781c303433`.

Validation checkpoint: 174 focused combat/native tests; 55 Ghidra target/export/harness tests; 22 MercMode UI tests;
23 existing stream-intervention tests. Broader suite found two stale assertions for existing roster fallback and the
expanded grenade-kind catalogue; those are being updated and rerun. Native ARM64 tests also need a clean Spark run
because Windows Unicorn emits handled access-violation diagnostics despite returning passing results.

Remaining major acceptance work: deploy and observe native hook/first aid/rings/aim/fire behavior; full durable
RE4/5/6 exports; favorite-library extraction backlog; independently bound donor models for every actor. Class-wide
archive swaps and one donor per archetype do not satisfy individual-enemy replacement. Keep that gap explicit.

## Verified changes and current limitations

### Live configuration changed in this session

Authenticated `POST /api/mercmode` changed **lilspark only** to:

```json
{
  "host": "lilspark",
  "enabled": true,
  "titles": ["re4", "re5", "re6"],
  "rounds_per_title": 5,
  "queue": [],
  "repeat_queue": false,
  "donor_rotation": "fresh",
  "donor_rounds": 1
}
```

The prior repeating singleton RE4 queue was preventing title rotation. It was cleared; RE6 was subsequently observed
playing. This is evidence of leaving RE4, **not** an acceptance run of five attempts across all three titles.
At the latest 00:22 UTC check the desired settings above remained present, but `current_run` was null and the scheduler
reported `busy with jobs`. Inspect current jobs before diagnosing or changing that state.

Still configured: `skin_swap=random`, `cast_swap=on`, `blueprint_look=true`, `keep_warm=1`, `coop_ratio=off`.
The current schema has a shared `rounds_per_title`; the newly clarified separate title counts are **not implemented**.
The existing quick-death counting policy is also **not changed yet**.
`repeat_queue: false` disables replay of the explicit queue, not the normal enabled multi-title scheduler; do not
restore a repeating singleton queue as a supposed fix for continuous rotation.

| Title | Switch title ID | Game ID | Current default build |
|---|---|---|---|
| RE4 | `010099A00BC1E000` | `270a15eb98dab4d7` | `recovery-re4-fit-v4-20261110` |
| RE5 | `010018100CD46000` | `52d15709be0fda1a` | `recovery-series-01-20261110` |
| RE6 | `01002A000CD48000` | `115f9cdbba115432` | `recovery-re6-enemy-cast-01-20261110` |

Latest observed worker: `e52a71a399f840dd` / `lilspark`. Refresh this ID before dispatch.
Local full state receipt: `system/gbox-data/mercs-handoff-live-20261112.json` (runtime artifact, not a Git dependency).
No new decompilation/export job or favorite-library scan was submitted by this Codex session.

### Local code changes: in progress, not deployed by this session

Review `git diff` rather than assuming these are finished. Existing files were edited directly in the shared workspace.

| Files under `system/` | Draft change / next requirement |
|---|---|
| `gbox/mercmode.py` | Default shared rounds changed from 1 to 5. Extend to separate per-title counts with migration and correct attempt accounting. |
| `clients/web/viz/mercmode.js`, `clients/desktop/index.html` | Shared round-count input moved into the visible PiP context menu, integer normalization, and "Cycle RE4 / RE5 / RE6" action clearing the pinned queue. Replace/extend with separate counts per new clarification. |
| `gbox/mercmode_tool.py`, `gbox/screensaver.py` | `cast_weights` admitted in tool/API schemas. Actual weighted donor selection remains unfinished. |
| `gbox/mercs/round_controls.py`, `gbox/mercs_bot.py` | Consume launch random-character/stage flags; avoid immediately repeating a stage when choices exist. |
| `gbox/mercs/titles/re6_switch.py` | Preserve established RE6 player/costume behavior unless an explicit control requests a character. Review interaction with managed controls. |
| `gbox/mercs/titles/re4_switch.py`, `gbox/re4switch_bot.py` | Draft per-round selection redraw, pending redraw after round accounting, and B/cancel out of Continue when random selections are enabled. **The actual B/menu route has not been verified live.** |
| `gbox/mercs/core/death_lessons.py`, `gbox/mercs/core/combat.py` | Learn after the first attributed death; move the dead latch into `died()` to avoid HP + terminal-event double counting. Requires updated tests and duplicate/new-round verification. |

Unrelated changes already present before this task: `system/gbox/mcp_server.py`,
`system/integrations/pinebox/frontend/pine-hls.js`, and untracked `CLAUDE.md`. Preserve them; do not include them blindly
in your task commit or reset them. Other terminals may add further changes after this handoff.

Validation run in this session:

- Python subset (`test_mercs_death_lessons.py`, `test_merc_round_controls.py`, `test_re4switch_bot.py`,
  `test_re6_menus.py`): **76 passed, 4 failed**. Two death tests still expect the old two-death threshold.
  `test_replaced_or_cancelled_prepare_cannot_clear_another_sessions_pick` and
  `test_boot_walks_selects_to_a_round_with_a_random_stage_and_character` also failed. Their baseline status was
  **not established**; investigate rather than declaring them pre-existing.
- `node tests/test_mercmode.cjs`: **20 passed, 1 failed**; expected save body lacks `cast_weights: {}`. Review desired
  schema/serialization, then update the meaningful assertion. JS syntax check passed.
- No native/gameplay acceptance was performed for these local draft code changes.

Working test interpreter: `C:/_tools/gBox/.venv-session-audit/Scripts/python.exe`; plain `python` here is Python 2.7.
From `system`, use `../.venv-session-audit/Scripts/python.exe -m pytest ... -p no:cacheprovider`.
Git on this Windows checkout needs `git -c safe.directory=C:/_tools/gBox ...`; do not change global Git configuration.

## Package A: full Spark binary and asset analysis

At 00:22 UTC, `GET /api/harness/ghidra` returned `status: available` with:

- Ghidra: `/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC`
- Python: `/home/ehm_eckx/gBox/system/gbox-data/runtime-linux-aarch64/pyghidra-venv/bin/python`

This confirms availability, not that all three games are fully analyzed or that an export exists.
Read [ghidra-service.md](ghidra-service.md), `gbox/ghidra_bridge_tool.py` and `gbox/ghidra_bridge_server.py`.

1. Inventory the exact installed executable version, NSO build IDs, every executable module, RomFS/assets, update/DLC
   composition, SHA-256 hashes and analysis artifacts for each title. Resolve roots from configuration. Do not confuse
   the historical `gBox_alt` scratch tree with the active checkout, or apply one build's offsets to another build.
2. Reuse valid saved projects. Analyze every in-scope module, identify remaining unanalysed executable regions, and
   export every discovered function with pseudocode, address, signature, callers/callees, references and available
   type information. Retain a persistent project plus machine-readable indexes on Spark.
3. Record totals, successful functions, failures, timeouts, remaining regions and reasons. Retry failures with bounded
   per-function work and checkpointed progress. "All discovered functions attempted" and "all succeeded" are different
   states. Neither establishes recovery of complete original, compilable source.
4. Inventory/extract game data separately: models, rigs, animations, textures/materials, maps, collision, navigation,
   enemy spawn/set data, scripts and resource tables where present. Record format/read/write coverage and gaps.
5. Produce a per-title analysis manifest with input hashes, tool versions, image bases, module/address translation,
   project/export locations, coverage, failures and resumable next actions. Keep giant binaries/exports out of Git;
   check in the manifest, analysis notes and reusable tooling.

Known RE5 starting evidence, **historical** from 2026-11-08:

- NSO: `/home/ehm_eckx/gBox_alt/scratch/agent/switch/re5/main-EBFFDB223149A725A93CD9B60979F6AA.nso`
- ELF: `/home/ehm_eckx/gBox_alt/scratch/agent/switch/re5/ghidra/re5main.elf` (30,360,176 bytes).
- Prior analyzed project: AARCH64 little-endian, image base `0x100000`, 20,835 functions;
  ELF MD5 `003b064c2f13456b1a7a2c658e541133`. Compute SHA-256 now; do not invent it from this MD5.
- For that ELF, Ghidra address = module offset + `0x100000`. Do not generalize this to other imports.
- `mVertexNum` at `0x0188df9f`, registration function `0x011537b0`; `em1000` model path at `0x01cfbd28`,
  pointer table at `0x00803874`. Find the table consumer and GPU mesh-buffer creation path.
- The canonical copy is described in the old doc as `gBox-data/analysis/switch/re5/re5_switch_main_EBFFDB22.elf`;
  resolve the real path and capitalization on Linux instead of copying that spelling blindly.

### Existing dispatch interface

Use the GBox API at `http://10.89.1.246:8765`, authenticated with the existing token file (do not print it), and
`x-gbox-actor: agent`. The local Windows token is `system/gbox-data/api_token`.
Refresh `/api/workers` and check jobs before submitting. Filter output to needed fields.

```json
{
  "tool": "ghidra_bridge",
  "require_worker": "CURRENT_LILSPARK_WORKER_ID",
  "input": {"op": "status"}
}
```

Submit through `POST /api/jobs`, follow `GET /api/jobs/{job_id}`, and retain the full `ghidra_bridge.json` artifact.
The bridge holds one program per worker; `open` switches it. Coordinate with the other terminal before switching
an already owned program. Separate isolated projects/processes are needed for truly parallel title analysis.

After an identified program is open, use guards for queries, scripts and exports:

```json
{
  "tool": "ghidra_bridge",
  "require_worker": "CURRENT_LILSPARK_WORKER_ID",
  "input": {
    "op": "export",
    "export_dir": "ABSOLUTE_NEW_SPARK_EXPORT_DIRECTORY",
    "export_limit": 0,
    "expected_binary_path": "ABSOLUTE_VERIFIED_BINARY_PATH",
    "expected_sha256": "VERIFIED_64_HEX_SHA256"
  }
}
```

These are templates; replace placeholders with observed values. Guards are supported for queries/scripts/exports,
not `open`. They fail closed against older bridge protocols. Do not drop guards just to get an export to run.

Current implementation gaps to address for a complete resumable export:

- `export` writes per-function JSON, `_index.json` and `_strings.json`; `export_limit=0` means all functions.
- It currently writes `data_refs: []`, so it does **not** establish data-reference coverage.
- Its aggregate function count includes failure-comment outputs. Add machine-readable success/failure accounting.
- It is sequential and does not implement robust resume; worker operation timeout is roughly one hour (request 3500s,
  tool 3600s). Checkpoint/chunk long work and distinguish a timeout from a stopped background operation.
- `adapters/ghidra/DecompileAll.java` emits one C file with failure comments and a 120-second per-function timeout.
  Its final "wrote N functions" counts attempts, not successful decompiles. It is useful, but not a coverage report.
- `tools/export_decompiles.py` is a hard-coded **PSO gold-set experiment**, not the RE4/5/6 full exporter.

## Package B: per-instance live replacement and complete donor coverage

Static decompilation is a foundation. Ghidra does not itself supply runtime hooks or asset reload. Build and verify
each title's actual path through resource lookup, archive/cache loading, entity construction, render/model binding,
rig/material ownership, GPU upload, reference counts and safe release/rebind.

The user's per-individual-enemy clarification means shared resource pointers must be handled explicitly: replacing
one shared class archive gives every instance the same model. Find an instance-level binding or clone/namespace path,
retain native combat behavior and skeleton compatibility, and prevent one instance's swap corrupting another.
Cover transformed forms, spawned helpers/parasites, bosses, nonhuman rigs and later-spawned enemies.

Required deliverables:

- A required-slot/type/variant census for each title, including every player/costume and enemy form.
- Independent per-instance assignment receipts: title/build/round, stable entity identity plus generation, enemy type,
  donor slug/source/hash, target resource/binding and result. Account for pointer reuse and despawn.
- Verified safe hooks with exact build guards, addresses/signatures, calling convention, thread/frame requirements,
  ownership and rollback. Native callback execution must be observed, not assumed from attaching a vtable.
- A validated staging/activation path that retains the last working installation on failed candidates and reports
  incomplete coverage. Between-round title restarts are allowed while implementing true live replacement.
- Gameplay evidence of different models on individual enemies of the same type, all player slots, later spawns,
  transformations, bosses, and changes across rounds. Label relaunch-based swaps and no-restart live swaps accurately.

Current boundaries found in code/live catalog:

- `donor_rotation.py` offers fresh in-service redraw only for RE5, samples three player slots, and sends `enemies: []`.
  Current RE4 and RE6 each have only one usable audited build; RE5 had seven. One build cannot prove per-round variety.
- `donor_swap.py` enemy handling removes overlays to restore native models. **That is not enemy replacement** and must
  never count as successful coverage. Its player redraw does not implement per-instance enemy bindings.
- The current fit gate can pass with one donor and no rejects. Add a separate completeness gate over required slots;
  "fits correctly" and "every required model replaced" are independent properties.
- RE4 writers: `re4_switch_models.py` / `re4_switch_enemies.py`. Known humanoid pools do not cover every nonhuman,
  parasite or boss carrier. Preserve native rigs/behavior and implement missing carriers rather than hiding them.
- RE5 writers: `re5_cast_writer.py`, `re5_enemy_cast.py`, `re5_enemy_writer.py`.
- RE6 writers: `re6_switch_cast.py` (51 character/costume body slots), `re6_enemy_cast.py`, `re6_switch_enemies.py`.
  Skipped slots, shared texture collisions and humanoid-only enemy recipes remain coverage failures.
- Read `donor_fit_audit.py` and the current rejection records before selecting donors. Do not reintroduce rejected
  fit/rig combinations just to inflate coverage.

## Package C: every favorite game contributes extractable models

`GET /api/character-collection/policy` previously reported enabled, parent request `c395ccae343f4789`.
This does not prove every favorite has been extracted. Use `favorite_capabilities` (`gbox/favorite_capabilities.py`):
`op: scan`, `schedule_collection: true`, and deliberate `retry_failed` handling. It paginates all favorites and tracks
unsupported readers. Inspect existing collection jobs and deduplication before queuing another scan.

Produce a per-favorite inventory of extracted models, provenance, rigs/textures, supported donors and explicit gaps.
Implement missing extractors where feasible. Do not claim unsupported favorite formats are covered because a collection
policy is enabled. Feed compatible donors into both player and enemy rotation, including the new nonhuman work.
`cast_weights` is accepted in draft schemas but still needs wiring through candidate selection and fresh builds.

## Package D: scheduler, menu and each-round randomization

- Add independent persisted counts for RE4/5/6, default five each, to the right-click menu, API/tool schemas and scheduler.
  Migrate the old scalar count without losing settings. Make the effective current count visible.
- Count each completed played attempt once, including short deaths; do not count an HP death and results screen twice.
  Remove the current policy where deaths under roughly 75 seconds are retries and three short deaths count as one.
- Rotate through all three selected titles at their configured counts, preserve counts through donor relaunches and
  avoid a repeating single-title queue bypassing the user's requested rotation.
- Redraw player choices in RE4/5 and loadouts in all titles each round. Preserve RE6 costume randomization and replace
  the full roster's model slots. No fixed weapon override should silently defeat round randomization.
- Verify on real boundaries: death, time expiry, success/results, relaunch and reconnect. Keep one round identity across
  events so counts, loadouts, model draws and learning cannot fire twice or be skipped.

## Package E: bot combat, healing, pistols and protective rings

The original handoff is [HANDOFF-2026-11-12-GRENADE-RING-PM.md](HANDOFF-2026-11-12-GRENADE-RING-PM.md), supplied in
commit `07c0e8a01710cf1d60b2e6d3810e076fa2688781`. Its live receipts are historical; some conclusions need renewed checks.

RE4 investigation leads from code (not all experimentally confirmed):

- `re4switch_bot.Keys.apply` sends ordinary gun taps down/up in one batch; only the bow receives a nonzero hold.
  Check adapter/controller sampling before attributing missed pistol shots to rate tables. Measure actual shots/projectiles
  and crowd response; button-request counters are not proof of fire rate. Respect aim acquisition and frame sampling.
- Inspect `mercs/titles/re4_switch.py` mine-ring state machine. Its equip-timeout branch clears the ring but lacks an
  immediate return, allowing stale local state to continue toward firing. `_mine_ring_done` advances the cooldown on
  failure, potentially suppressing another attempt for 90 seconds. The cadence is measured after completion rather than
  necessarily start-to-start. Validate all three behaviors and fix them with receipts/tests.
- `_boss_weapon` in `mercs/titles/re4_switch_mods.py` runs before temporary ring weapon handling and may compete with the
  Mine Thrower. Give the ring and boss weapon swaps explicit ownership, bounded timeouts, and a reliable return path.
- The documented "10 m" ring defense threshold and its units need checking against the actual coordinate conversion.
- Existing `heal_below` directly refills HP. **That is not proof the bot can use first aid sprays.** Implement/verify actual
  item use and receipts. Keep any permitted emergency heal fallback distinguishable from inventory consumption.
- Existing RE4 weapon weighting already favors magnums/shotguns (about 70%) and high-power guns. Check round epoch,
  saved flags, fixed overrides, failed give retries, inventory/equip verification and menu transitions before rewriting it.

For all applicable titles, pistol requirement is **20x fire rate, zero recoil, infinite ammo**. The existing RE5/RE6
generic fire-rate cap is 5 in relevant paths; changing a label or requesting 20 is insufficient. Verify native weapon
tables/animation limits and recoil paths for each actual pistol. Do not invent offsets to fill unsupported gaps.
RE5 already has a round-loadout operation in its profile; RE6 already calls `merc_loadout`, but its ordering biases the
same magnum. Correct the current implementation rather than relying on the older claim that no round loadout exists.

Persistent learning must record attributed killers and relevant type/attack context across rounds, prioritize those
threats and instant-kill bosses, and change positioning/weapon/defense choices. Do not invent a killer for unknown or
environmental deaths. Verify persistence, single counting, decay, boss lock until HP zero and reduced repeat failures.

The periodic grenade/Mine Thrower defense requirement is 90 seconds. Preserve the clock through appropriate round/run
boundaries; distinguish paused/loading time from active play deliberately. Verify a full 360 sweep and actual ordnance,
failed-equip retries, weapon restoration, player safety radius, boss interruption and cooldown evidence.

Known native blockers from the prior handoff:

- RE4 attached vtable harness recorded zero ticks. The current weapon-driven Mine Thrower path is the previously
  demonstrated fallback; find an actually executed callback before calling the native harness repaired.
- RE6 launcher shell spawn stalled with mailbox state 2 at offset `0x18f2bc0`; flash had successful receipts. Recovering
  a mailbox while its callback may still execute requires evidence and safe ownership, not a blind state reset.

## Completion and deployment evidence

Use the existing tracked job/build/deployment workflow. Prior docs describe `origin/main` deployment on a roughly
15-minute cron, bot hot reload, and service-restart requirements for non-bot modules; verify current rules before acting.
Avoid interrupting operator-owned sessions or another terminal's jobs. Earlier SSH here failed host-key verification;
the authenticated GBox API worked. Do not disable host verification to work around that failure.

Keep the MercMode broadcast selected. A service restart may reset its program pin; inspect and restore the intended
MercMode feed after any necessary restart. Do not confuse saved settings with imported running code.

Acceptance must separately demonstrate:

1. Each title plays its configured number of attempts; short deaths count once; all three titles continue cycling.
2. Right-click edits independently persist and affect the intended title's future rounds.
3. Per-round player/loadout changes and per-instance enemy donor assignments actually render, including every enemy
   type/form and every player slot. No native fallback or skipped slot is reported as a replacement.
4. Pistol behavior, first aid use, boss handling and 90-second protection are observed in gameplay with useful receipts.
5. Death learning survives restart/next round and changes behavior without duplicate or fabricated attribution.
6. All three titles have durable Spark analysis/asset manifests, complete attempted exports with failure accounting,
   and documented working runtime hooks. Any remaining decompilation or format gaps are plainly listed.
7. True live replacement is demonstrated without a title restart before marking that requirement complete; interim
   restart-based results remain labeled as such. Keep future custom-level/composite-title findings organized.

Continue updating this handoff or link a successor with actual job IDs, commit IDs, paths, hashes, test outcomes,
coverage and gameplay evidence. The operator's latest clarifications above take precedence over older dispatch plans.
