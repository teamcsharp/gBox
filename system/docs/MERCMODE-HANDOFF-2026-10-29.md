# MercMode continuation — 2026-10-29

Read `MERCMODE-HANDOFF-2026-10-28.md` for standing authorization, machines, API and the complete operator requirements. Do not reuse historical worker/process identities for writes. The current checkpoint below supersedes the historical sections farther down.

## Latest checkpoint: 2026-10-30, 01:00 UTC (October 29 on the operator's PC)

This section supersedes the historical checkpoint below. The full request is **not complete**. PR [1584](https://github.com/teamcsharp/gBox/pull/1584) has now merged the guest-state responsiveness fix and this handoff; main is `85940a897bcb3b45dffda9fa9b0cfecb884197d4`. The earlier rate-limit and pending statements below describe prior checkpoints.

**Blender normal-route acceptance now passed:** after changing both headless subprocess calls to `stdin=subprocess.DEVNULL` and restarting only the idle local service, central job **ce45796b5f8e4694** succeeded on worker **3325378af4304698**, epoch **050275ea3ea446876e8704d13ff45688**. Bayman fetched from Spark and produced 2 objects, 7013 triangles and 40 packed textures in the local clipboard. The earlier second job `ea9c706d18ee4ec2` timed out after 300 seconds. Do not replay those failed job IDs. The exact Windows-level wait mechanism is not established, but the normal worker path succeeded after isolating headless Blender from the desktop control-input pipe. The follow-up also skips inaccessible users' temporary directories rather than aborting before checking writable fallbacks; 32 tests passed, three optional tests skipped. Branch `fix/blender-child-stdin-20261030` holds these changes. The desktop UI is still PID75180; the service alone restarted through its existing watchdog without closing games. Read current state before any further restart.

- Main is `c807ea992ea9ff00ff0b41017f42657246a97a91`. PR [1581](https://github.com/teamcsharp/gBox/pull/1581) merged the RE5/RE6 native equipment and rebuild timeout branches listed below. Spark deployed it at 00:07:48 UTC and reported both bot modules reloaded, one active bot resumed in 1.4 seconds. Native attachment trials remain the evidence; normal-round firing/hit acceptance is still outstanding.
- PR [1582](https://github.com/teamcsharp/gBox/pull/1582), merge `bacd16b04a817fb4cad40b2c380ec7124a1079d8`, moves visible PiP geometry ahead of the slow native caption helper and avoids waiting for/navigating a hidden guest for remote PiP. 38 JS tests passed. Desktop activation is confirmed by the new process below; actual interactive transition timing is unmeasured.
- PR [1583](https://github.com/teamcsharp/gBox/pull/1583), merge `c807ea992ea9ff00ff0b41017f42657246a97a91`, fixes federated Blender assets: the local clipboard worker fetches from the verified originating server, not its own absent character library. Missing character models return 404 instead of uncaught 500. 50 tests passed, three optional Blender tests skipped. Spark deployed files at 00:30:11 UTC. Distinguish deployed files from already-imported core modules.
- `fix/desktop-local-startup-20261030`, commit `72844080`, is pushed but **not merged**. It bounds guest-state IPC to 250 ms, coalesces repeated polls, and discards old-frame replies after navigation. 42 guest/PiP tests passed. PR creation was rate-limited at **00:41:45 UTC** (HTTP403 secondary content-creation limit). Back off; do not bypass or repeatedly retry. This is not proof that every streaming UI bottleneck is fixed.

### Local desktop recovered; Blender outcome

The exact idle desktop PID76548 was replaced through the existing scoped recovery function, with no session witnesses and **no game sessions closed**. New desktop PID **75180**, launched about 00:33 UTC, uses the original app path. Its app-owned local service and worker are online: worker **6715c199a4ca459b**, epoch **b69edbadf5d3d08f4bcdf24f7e573381**, same installation authority as below. Supervisor health was connected/running at 00:39 UTC. Recheck identities before mutations. The cause of the prior desktop's missing worker was not established; do not assert it was elevation or a restricted process token (both were checked and ruled out).

Bayman's original local failed job was `7242f1529d0444db`, central `9f5b177c6b314a00`. Source Spark had the model; local `D:\gBox\cache\characters` did not. After PR1583, validation job **dfe446a6330e4d8d**, local **31050080de244769**, reached headless Blender but ended `TimeoutError`. Its headless processes exited; the operator's open Blender was untouched. A separate direct invocation of the SAME `blender_copy.to_blender` then succeeded on the same PC/build: **2 objects, 1 mesh, 7013 triangles, 80 materials, 40 packed textures**, Bayman armature with 15 role mappings. It wrote the actual local `copybuffer.blend`; Ctrl+V is now available. Receipt: `.scratch-merc-20261028/blender-direct-result-20261030.json`. A fresh normal-route validation **ea9c706d18ee4ec2** is pending at this checkpoint. Do not claim the desktop copy flow is consistently fixed until that result is checked.

Blender startup experiments: the exact 4.5.15 LTS build starts headlessly in roughly one second with the worker environment, both with stdin closed and an open pipe. Thus neither inherited PYTHONPATH nor stdin alone reproduced the worker timeout. Do not invent a root cause. Native UI tooling failed to initialize (`kernel.js` missing in Node REPL); no visual UI/paste verification occurred. Direct clipboard creation is verified separately.

### Latest operator requirements still to implement

The flash button must create and immediately detonate a flash **at the player's current position through verified RAM/native hooks**, across all Mercenary titles. Every rapid click must be distinct. No equip/drop/throw-animation substitute. After a confirmed flash, choose a defensive response among quick attacks, mines plus retreat, and grenades. Current code still uses a throw directive, overstates success in its toast, overwrites rapid clicks in `_LATEST`, and can replay a one-shot when a new Reader sees old stats. None of these satisfy the requested native intervention.

Add a weapon icon/dropdown beside flash. User chooses any weapon as the first equipped/main slot for this match, with at least a two-minute no-swap lock and a retained match-long primary preference. Existing native equip only attaches already-created inventory objects; RE6 `live_weapon` schedules unloaded weapons for the NEXT round. Neither is an implementation of arbitrary current-match replacement. Verify resource loading, native object creation, attachment, subsequent usable firing, and match/player identity before publishing success. Preserve emergency item use without losing the chosen primary.

Other open requirements: no wall-facing or wall-running while threatened, responsive tabs/models during streaming, instant PiP entry, reliable local Blender copies, 15-minute live LAN input/stream acceptance, i9 Merc3D/RE4-VR five-match rotation, and survival with native S-or-better rank. Latest read-only sample: RE5 session `8b14a71472484560-86a2f2cb358047af` was playing with hits increasing and 1.92 seconds accumulated wall-push; RE6 `8b14a71472484560-2161a51e76eb4110` was prepared/parked. These are diagnostics, not acceptance. No native all-title flash or arbitrary weapon spawning hook was delivered.

## Historical checkpoint: 2026-10-30, 00:01 UTC

The operator confirmed repeated connection interruptions are in the **GBox desktop app or PiP**. Stability and completed tickets 5972 and 6102 through 6107 remain the current request. Full GBox remote administration, merges and deployment are authorized. Never launch games on JAYBUILTFINALE. Do not claim this entire request is complete.

### Merged and deployed

`main` is `99e2e558882ebda1079c231ea5618e8843cccdb7` at this checkpoint.

- PR [1576](https://github.com/teamcsharp/gBox/pull/1576), merge `915d11f6576bd61e7f171915abf52821d74cf2b6`: preserved newer main's aim gates and added regressions; **149 tests**. It does not prove live damage or S-rank.
- PR [1578](https://github.com/teamcsharp/gBox/pull/1578), merge `88afcc868efc89596a34b2d1ffcdd9f10a6723b0`: transient health-probe exceptions no longer immediately revoke an established desktop connection; actual advancing video frames prevent watchdog reconnect loops. Explicit offline responses and ended streams remain authoritative. **41 JS tests and a real-browser MJPEG regression passed**. A 15-minute live desktop/input acceptance run is still missing.
- PR [1579](https://github.com/teamcsharp/gBox/pull/1579), merge `507d68159d3aba70938ab13766b988ae40619cbc`: RE5 critical-HP escape no longer rearms indefinitely; RE6 death is recorded before round finalization. **253 tests**, including persisted death evidence. Assimilates 6121's death-accounting finding.
- PR [1580](https://github.com/teamcsharp/gBox/pull/1580), merge `99e2e558882ebda1079c231ea5618e8843cccdb7`: RE6 wall-command routing no longer consumes a fresh emergency-flash command before its controller reads it. **251 targeted tests**. This is not native instant flash detonation.

### Tested commits preserved on remote branches, NOT merged/deployed

GitHub PR creation returned HTTP 403 secondary content-creation rate limits at 23:09:48, 23:15:16 and **23:32:13 UTC**. Back off; do not repeatedly retry or use another identity to bypass the limit. No PR number exists for these three branches yet.

| Branch | Commit | Evidence |
| --- | --- | --- |
| `feat/re6-native-equip-6107-20261029` | `824bf218` | 232 targeted tests; guarded live magnum attachment in about 37 ms |
| `feat/re5-native-equip-6104-6106-20261029` | `1fd0ce503fd2d90660884d6435f8dd7cb5f9fbaf` | 109 targeted tests; guarded live magnum attachment in about 411 ms |
| `fix/rebuild-process-timeout-20261029` | `35151440` | 16 tests, including real Windows child/wrapper timeout cases |

All three were pushed. `.wt-merge-1576` now holds combined branch `integrate/mercmode-native-and-recovery-20261029`: RE5 original commit plus RE6 cherry-pick `919d7d6f` and rebuild cherry-pick `68220d33`. Combined validation: 347 passed, one relative-profile-path case failed because the command ran from the repo root; rerunning that sole case from `system` passed (348 cases verified overall). No implementation change was necessary. The RE6 and RE5 files introduce guarded native action requests and bot integration; they do not directly replace the active object/index. Native attachment is verified, but actual subsequent firing/hit/damage acceptance and production deployment are not. RE5 healing retains its existing quick-slot path because that lifecycle is unverified. Research documents live with each feature branch.

The rebuild timeout fix launches Windows commands suspended into an owned kill-on-close Job Object before resuming, so descendants cannot retain stdout after timeout. It also flushes the command line before launch. Linux uses a process group. The prior implementation killed only the wrapper and could block forever draining a child's pipe.

### Urgent desktop recovery state (recheck before acting)

JAYBUILTFINALE installation authority: `772ec831bb3881c8fe5cadbf2ca43f0458ee18131c4358fcb8969861c322d5f0`.

The original rebuild request `c98966d7ddb544108e5666bbb6a0d529`, job `14773b28e5c14c99`, belonged to worker `72ae7024a4454f91`. Git and pip steps hung; the old worker then exited without a final receipt. A replacement worker `af3201da25744442` appeared at about 23:31 UTC. The old request nevertheless remained `rebuilding` and blocked further administration.

After host-side confirmation that PIDs 5636, 37776, 66772, 59184, 90428 and 53476 were absent, the exact job was canceled through the API and reconciled as **failed, completion unverified** with backup and audit **218108**. Backup: `/home/ehm_eckx/gBox_alt/scratch/agent/abandoned-rebuild-14773b28e5c14c99-before.json`. The one-shot maintenance script is in the same directory. No successful rebuild receipt was fabricated.

The per-user outbound recovery task was explicitly installed and paired using the existing credential. Task: `GBox Recovery 772ec831bb3881c8`; state: `system/gbox-data/desktop-admin`. DPAPI pairing is saved. The supervisor connected independently of Electron. It runs Limited, and both it and the desktop were verified non-elevated; this incident was NOT an elevation mismatch. Do not print pairing or tokens.

Supervised relaunch request **`826ea70606664db2b3b65e35f53afdd8`**, worker `af3201da25744442`, epoch `285a49373c403a68f0d96423eb12c753`, ended with durable acknowledged **unknown: relaunch outcome uncertain**. It must not be replayed. The local service became unavailable. No remote game session was closed; the request's native session list was empty.

Desktop PID **20928**, birth **1793316682.599627**, executable `%LOCALAPPDATA%/gbox/app/gBox.exe`, exact repo app argument, remains listed with only two threads after termination was requested. Windows PowerShell reported `HasExited=true`, but **psutil `is_running=true` and `wait(timeout=0)` timed out**. Thus do NOT use PowerShell HasExited alone as proof that the profile lock is released. The GBox profile `lockfile` remains held (Electron error 32). CancelSynchronousIo on the two identity-checked threads returned ERROR_NOT_FOUND (1168) for both; no cancellation occurred.

A first direct restoration inherited `ELECTRON_RUN_AS_NODE` and exited. The corrected restoration clears that variable plus GBox control/token environment variables, uses the fixed app/executable, and records startup output. PID **56496**, born about 23:50:27 UTC, reported `Lock file can not be created! Error code: 32`. By about 23:55 both it and 20928 had finally disappeared. A guarded fresh launch then restored the desktop: PID **76548**, birth **1793318131.540**, observed responsive with a real main-window handle. The prior lock error in the log is historical, not a new failure of 76548.

The restored app's local service still was not available. A foreground diagnostic with the installed interpreter, exact config, and `--no-worker` successfully served 18765, proving imports/config can start. It was stopped at 00:00:51 UTC (exact diagnostic PIDs 43388/92380, no worker/games) to free the port for the app's watchdog. **Desktop UI is restored, but local-worker/PiP end-to-end recovery is not yet verified.** Recheck the app-owned service and supervisor health before any further action. Do not reboot the active workstation, delete its profile, or spawn duplicate desktops.

Local diagnostic/operational scripts and sanitized log: `.scratch-merc-20261028/{desktop_recovery_local_20261029.py,desktop_relaunch_20261029.py,supervised_status_20261029.py,retire_abandoned_rebuild_20261029.py,restore_desktop_20261029.py,process_liveness_20261029.py,cancel_stopped_desktop_io_20261029.py,desktop-restore.log}`. Corresponding API scripts are staged under `/home/ehm_eckx/gBox_alt/scratch/agent/`. The relaunch script has a fixed old-worker guard and a stable request ID: read it before use, do not blindly rerun it.

### Tickets and outstanding acceptance

Opaque ticket IDs: 5972=`9b62ade91d2b4aed`; 6102=`d7045c402d574582`; 6103=`ebb2fbc17c54480c`; 6104=`e94655b56a334118`; 6105=`bc39fb3dc88d61af`; 6106=`bd415a485a244111`; 6107=`2a755e634b9c4acf`; 6121=`ac17041357701388`.

- 6105's requested run analysis was delivered and closed, receipt at 1793312332.5442324/audit 217593. Round `653febf84bac4b69bf1ce3234bc2bbc8`: RE5 Wesker Midnight, completed timer zero, score/kills zero, rank missing (not a pass), 97 escapes. Report distinguished missing observations from zero and left three advisory proposals unapplied. PR1579 implements the separately verified escape-loop fix.
- 6121's run analysis was already delivered; PR1579 fixes the verified RE6 death-finalization ordering. Do not infer all attacks were melee from incomplete shot telemetry.
- 5972/6102/6103: **native immediate flash spawning/detonation remains unimplemented**. Current throws are not equivalent. PR1580 fixes one routing loss, but the server still stores only the latest directive, so rapid clicks can overwrite each other; fresh bot Readers can also replay stale one-shots. Completion receipts/queue/expiry remain needed.
- 6104/6106/6107: native-equipment commits above await merge, deployment and actual usable-weapon proof. Do not close solely on attachment or unit tests.
- Twenty actual grenade projectiles in two seconds, native remote detonation while holding a gun, comprehensive verified enemy variants, live targeting/damage/S-rank, and i9 five-match Merc3D/RE4 VR rotation remain unverified or unfinished.

Latest Spark sessions were RE5 `8b14a71472484560-d5e3ec9d7aa94c9b` and RE6 `8b14a71472484560-2161a51e76eb4110`, agent-owned and running. Re-observe before mutation. i9 worker `4a3cd49611f447ea` was online with Merc3D session `4a3cd49611f447ea-9ad2bcd2205f433b`, marked **agent_owned=false**, scheduler current_run null. It was not restarted/adopted this continuation. RE4 VR readiness and local PiP progression are still not proven.

## Historical orientation (superseded where the checkpoint above differs)

## Latest operator priorities

- Finish merging PR #1576. The operator clarified: **she must hit the targets or the bot will be overwhelmed**. Input counts and holding the trigger are not hit evidence.
- Assimilate tested work into the default branch (`main`, not `master`) and leave a usable handoff. Preserve newer changes already integrated by other sessions.
- Survival plus native S-or-better rank is the acceptance criterion. Death or a lower rank fails; missing rank is unverified.
- No inventory/wheel/pickup interruptions. Native equip must complete the game's attachment lifecycle and prove the weapon is usable.
- Rapid-fire magnums, reactive quick attacks, mines, flash stuns, and completed grenade throws; requested burst remains twenty actual projectiles in two seconds. RE6 remote detonation while holding a gun needs a verified native path.
- Accurate enemy variants and hazards in the live map and run database; tailored strategies. Wiki names do not prove a native class binding.
- i9 local PiP autoplay and learning, Merc3D / RE4 VR rotating every five matches, with dependable authenticated remote administration.

## Repository checkpoint

On resuming this conversation, local `main` and cached `origin/main` were `ef207b17796bace4b480859dfb1ce0716c38d218` (PR #1575), substantially ahead of the previous session. Newer commits include native navigation guards, enemy labels, reactive RE6 quick shots, healing, dynamite awareness and an emergency flash command. Commit presence alone is not live acceptance.

PR #1576 originally proposed unconditional firing within 45 degrees. It conflicted with newer crowd aim logic and would admit magnum misses and missing aim evidence. Integration worktree: `.wt-merge-1576`, branch `integrate/pr-1576-20261029`; remote PR branch: `hermes/request-5181-1793172988611889988`.

Resolution preserves main's newer firing logic, health handling, wall/floor guards and weapon readiness. It retains the incident fixture and adds sixteen regression cases for a shotgun and all three magnums: reject off-target, blocked, floor and missing-ray shots, then sustain aligned fire without slot cycling. The final delta against the checkpoint is regression coverage, not a new live firing algorithm.

Validation: **149 tests passed** across `test_re5_switch_crowd.py`, `test_re5_switch.py`, `test_re5_switch_rampage.py`, `test_re5_switch_aim.py`, and `test_re5_switch_wall.py`. The incident enemy layout uses explicitly synthetic aim observations. This does not establish actual damage, hit rate, survival or rank. Check GitHub PR #1576 for the final merge receipt before continuing.

## Earlier unfinished research — reconcile before resurrecting

Earlier worktree registrations remain in Git, but their files and uncommitted edits must be checked before assuming they are recoverable. Several may have been removed or superseded after the earlier session. Do not replace newer main files wholesale with old worktree copies.

- `.wt-re6-throw-confirmation-20261028`: native projectile census plus throw-completion accounting. Reader commit `d3bdaf8f` (original `a21d1f99`); later controller/journal edits were uncommitted at the earlier boundary. Live read-only probing showed the original 64-unit census cap was insufficient. A 512-unit diagnostic was pending; no usable completion result was retained. Do not ship the 64-unit implementation as functional or count animation/consumption as projectile birth.
- `.wt-re6-native-equip-20261028`: native weapon-change request action `0x26`, manager request function main+`F8C7C0`, pending byte manager+`3C`. Request consumer installs the native action; attachment work runs through `B230B0`. Verify exact build, player generation, ownership, action context, pending/busy state and actual active slot/object. Active flash object `uWp1094` was observed; enabled state uses object+`12F4` bit 0. A direct index write is not equip proof. No verified production writer was delivered in that session.
- `.wt-re5-native-equip-20261028`: native weapon-change action `0x20`, request `790FE0`, player pending byte+`1B4C`, requested action+`1B40`, target grid+`3F70`; action applies through `7AB380`. Player generation+`1A00` derives from allocator counter main+`1CF1CA0`. Guard request override fields+`3BD8`,+`3BE8`,+`3EF4` and native context side effects. Static/native identity evidence exists; a working live equip writer was not established.
- RE6 remote bomb `uWp1097` action-7 update `F852F0` requests its action `0xA` under native conditions. The player's remote-input producer was not fully proven. Do not guess a detonation flag from this partial chain.
- `.wt-enemy-catalog-20261028`: earlier catalog/identity-sidecar work reported 289 Python tests passing and focused JS regressions passing, but had no commit at the boundary. Newer main already adds enemy labels and portraits. Compare approaches before porting; preserve learned class keys and distinguish verified species from unbound roster entries.

RE6 projectile proof: pinned build `061d2a06cd700785e987c42ce2d72231`; grenade consumption at `1098D24` precedes allocation, which can fail. Projectile classes `uWp1091/1093/1095/1097` represent frag/incendiary/flash/remote; owner+`1300`, allocation generation+`1308`, native unit line 13. Count new owned allocation generations only after a complete bounded census; incomplete observations are unknown, not zero. Reader uses monotonic time, while the bot clock may use wall time.

## i9 recovery evidence from October 28 — stale until rechecked

The second rebuild request `4c18891fff61481a89cc9d4caa89351b`, central job `b1092eb59b6c449f`, remained at Code on worker `2bbd5b6ca1c84cf8`. A Git subprocess exited while a descendant appeared to retain its stdout pipe; `Console.run` killed only the direct child then blocked draining output. Registry timeout did not stop the callable. Avoid duplicate rebuilds until current process/job state is established.

Autoplay settings had been restored (`enabled=true`, Merc3D, five rounds, local PiP), but the active rebuild still blocked scheduling. This was not resumed gameplay. A read-only REA diagnostic was denied by the worker's configured `Permission.FILE_MUTATION` admission gate. The operator has already authorized remote administration; the issue was tool/config capability, not missing consent. No process kill, central cancellation or gate bypass was performed.

RE4 VR readiness reported missing Refract runtime/setup evidence at `D:\gBox\refract`. Source APK/OBBs existed elsewhere; do not claim the game source was missing. Native gameplay/read-memory/match-boundary readiness and five-match title rotation were not proven.

## Continue with evidence

1. Confirm #1576's final GitHub merge receipt and current `main`; preserve any concurrent operator edits.
2. Read current Spark/i9 state and recent native round outcomes. Never reuse historical process IDs for writes.
3. Measure actual shots hitting enemies, damage/kills, wall recovery and survival. Existing test passes cannot close these gameplay requirements.
4. Reconcile remaining native-equip/projectile/enemy work with newer main, then make small tested changes. No speculative RAM writes or fabricated species/throw counts.
5. Verify i9 recovery and local PiP progression before claiming autoplay; RE4 VR only joins rotation after native readiness is established.

Never launch games on JAYBUILTFINALE. Keep tokens private and retain rollback evidence. Full i9 GBox administration is authorized. The previous generic no-touch rule does not negate that authorization.
