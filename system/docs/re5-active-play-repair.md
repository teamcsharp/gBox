# RE5 active-play repair — October 26, 2026

## October 30 update: Switch target feedback and bounded acquisition

PR [1614](https://github.com/teamcsharp/gBox/pull/1614) repairs the current Switch
driver. The October 26 RPCS3 findings below describe a different controller.

The Switch crowd rule could keep the gun raised indefinitely while four nearby
enemies also suppressed ordinary escape. The new final firing gate uses the
owned QFPS camera, the actual muzzle origin and a live reachable enemy body.
Yaw/pitch corrections use elapsed time, capped at 50 ms, and release digital aim
sticks, including during camera transitions. Read-back proves a write only;
fresh observed geometry must authorize a shot. A reachable front target takes
precedence over turning toward an enemy behind the player.

A blocked acquisition now gets 0.75 seconds before a 0.65-second reposition.
Retargeting does not restart that deadline. Forward, backward and sideways
directions are checked against available navigation geometry; movement still
passes through the wall and shot-animation guards. A new clear shot returns to
aiming/firing. Throws, mines, healing, QTEs, human control and native equipment
handover retain priority. This fixes indefinite combat aiming; it is not a claim
that every possible wait in every title has been eliminated.

RE5 requests a 30 Hz decision budget, subtracting actual work instead of sleeping
a full interval after it. Telemetry exposes decision rate/work/p95, combat action
and held keys, aim waiting/repositions, target error and write/fire refusals.
Spark already has all 20 CPUs available with no CPU quota. No Pine service or
resource policy was changed. More cores alone do not correct aiming geometry.

Validation and activation at approximately 15:28 UTC:

- 178 targeted tests passed after the final camera-transition correction,
  covering aim, crowds, walls/navigation, animation priorities and weapon locks.
  The preceding aim/scheduling/reload suite passed 187 tests.
- Hash-checked candidate installation preserved the separate Pine/native-hook
  edits and kept backups. Reload job `a3ab674c07724ddf` activated the final aim
  module with a measured 0.78-second bot handover; no game/service restart.
- Spark session `30e9b63ca2ee4375-3b50bd73d65b4a35` showed explicit repositioning,
  real position changes, gunfire and enemy HP losses. Decision rates in the first
  live sample were about 22-30 Hz. Later samples also contained slower ticks.
- Ship Deck round `9e1350b1d64a4e6dadac79045f5220eb` **died**, score 10,730:
  failure under the operator's rule. Increased hit counters do not make it pass.
- The following Mines fragment `cee21687e50e485ca76cb13103477ac0` reached 75
  kills, two recorded mine placements and one bonus before the final hot reload
  recorded it as interrupted. Native S rank was not verified. Reload fragments
  must not be counted as completed successful rounds.
- After that reload, fresh native samples showed the resumed Mines session
  progressing from 90 to 103 kills, with sampled QFPS pitch near -3 to -11 degrees
  rather than pinned to the floor. This is not proof of final survival or S rank.

Private receipts: Spark `gBox_alt/scratch/agent/re5-aim-trace-1793373816054466517.json`,
`re5-aim-trace-1793374091734601677.json`,
`feedback-watch-1793373865136536173.json`,
`feedback-watch-1793374054607933378.json`, and
`active-outcomes-1793374124040366864.json`. Final scoped rollback copies are under
`re5-keep-active-v2/before-1793374050187070292` in that same scratch directory.
The controller lives in the established `re5_switch_aim.py` module because the
worker's initial reload registry did not reliably discover the first new helper.

Remaining acceptance: uninterrupted S-or-better survival, boss/close-crowd
dispatch, confirmed mine detonations, and equivalent no-stall verification for
RE6 and Mercenaries 3D. Keep autoplay running; do not launch games on JAYBUILTFINALE
or overwrite the concurrent Pine integration while continuing this work.

## Findings

The running bot was receiving fresh telemetry and issuing input. A retained
`mines_only=true` setting suppressed both nearby combat candidates and ordinary
enemy targets, even when a loaded gun was equipped. Mine safety simultaneously
deferred placement because no supported escape route was available. This made
the bot unable to shoot its way out of the situation.

The restriction originated in a successful operator mine-only command on an
earlier session and persisted into subsequent sessions. Recent completed reports
included scores of 0–3,020, usually no confirmed time bonus, and recorded accuracy
of 0–20%. Their analysis requests remained queued; filing a report had not applied
an implementation change.

Navigation was partially functional. The first observed round had collected two
hourglasses and had supported routes to the remaining goals. Combat, recovery,
and repeated mine deployment interrupted that movement. The deployed navigation
source contains changes absent from the checkout, so it was preserved.

Two additional combat defects were reproduced with regression fixtures:

* Nearby bow/egg targets renewed the aim timeout purely because of distance. An
  off-target camera could therefore hold aim forever without a trigger press.
* A gun could lower and turn because of body heading even when its ready pose and
  measured laser contact already placed the shot on a living enemy.

The round-report endpoint also sorted by mutable SQLite row order. Reconciliation
updates could promote an old report over newer completed rounds.

## Corrections and verification

Live mine-only mode was disabled. Mixed combat immediately resumed gunfire, and
the observed Public Assembly round progressed from 12 to 69 kills, reaching
33,240 points. Frequent mine deployment still interrupted routes, so deployment
was subsequently disabled as well. Existing mine safety was retained.

The resumed session is `b162dd0559f44fed-bf05f8a4bc4147e2`, Josh in Missile Area.
At **01:38:28 CDT**, fresh telemetry recorded:

| Measurement | Observed value |
| --- | ---: |
| Kills | 23 |
| Score | 9,280 |
| Recorded shots / hits | 21 / 16 |
| Confirmed hourglass pickups | 1 |
| Confirmed bonus clock gain | 28.95 seconds net of observation timing |
| Stuck events this round | 0 |
| Activity | Moving toward another time bonus |
| Mine-only / mine deployment | Both disabled |

The hourglass actor was marked taken and the dedicated pickup counter increased;
kill-added clock time was kept separate. These measurements validate the runtime
settings changes. They do not establish complete-stage collection or a perfect
hit rate. The existing damage, ammunition, fire-rate and kill-time assistance
remained enabled; health protection remained disabled.

Source fixes in `re5_combat.py` bound off-target bow/egg acquisition and preserve
a ready gun's measured on-target shot. `round_reports.py` now orders by immutable
report creation time before applying the limit. Six combat regression cases and
one report-ordering regression were added. The combined focused suite passed
**162 tests**; `git diff --check` passed.

## Activation status

The shared service restart was explicitly approved and performed. The installed
combat, report-ordering, input-handoff, native-read retry, upload-timeout, and
restart/autoplay continuity fixes are active on lilspark.

The desktop's automatic reconnect loop unexpectedly issued a second service
restart while the first was recovering. SSH session and sudo journal evidence
match its 12-second timeout. The original activation and failed pre-launch
reload receipts were preserved; a separate reconciliation verified the current
service and source hashes without another restart.

The first restored RPCS3 instance suffered an RSX.W5 null-pointer crash during
shader-interpreter precompilation. It stayed alive while streaming a static
picture. A single-game restart through the normal API recovered it; the shared
service was not restarted again. The saved modifiers and team configuration were
verified and autoplay started with continuous recovery enabled.

First activation's verified session: `dbe13c8517674dfe-de44b3d95f894492`, emulator PID
`1778324`, service PID `1728744`. Fresh telemetry showed active gameplay, five
kills, three recorded hits from four shots, and no stuck events in the early
sample. Video frames were current, but sampled delivery still included occasional
large gaps; this is not a claim that stream pacing is solved.

Private receipts are under
`system/gbox-data/re5-audit-20261026/continuity-activation/`, including
`boot-retry-restore.json`. The latest session is recorded in `current-session.txt`.
The follow-up changes were subsequently installed with exact file hash guards,
backups, and a fresh settings snapshot. One approved service restart loaded the
checkpoint-aligned mine routes, per-weapon shot attribution, native warm-game
readiness, cached-frame watchdog, and encoder frame-age correction. The operator
confirmed refreshing the desktop, loading the automatic reconnect fix. Automatic
reconnects no longer restart the shared service.

The first follow-up activation exposed a deployment dependency omission:
`re5_ps3` required `re5_mines.SPAWN_MATCH_CM`, but the server retained its older
mine helper. The bot exited at round start while the service and stream stayed
healthy. This was a deployment error, not player takeover. The complete matched
mine helper was then reviewed, including its verified mine-list observations,
600 cm escape margin, pending-placement acknowledgement, and retained route.

To verify the actual dependency combination, all 909 deployed Python sources
were captured privately and 442 focused checks were run against that source copy
plus the corrected mine helper. All passed. The related navigation and warm
preparation dependencies were independently audited; no other missing required
symbols were found.

The corrected service is PID `2161364`, worker `78c5c9dcb732486e`. Its exact RE5
successor is `78c5c9dcb732486e-8cfd53d2abb04f3b`; modifier and team readback passed,
and autoplay job `23b84ff229f2459e` restored `continuous=true`. Private phase
receipts are under `dependency-activation/`. The original failed queue guard is
preserved: it submitted only a read-only status request. A separately recorded
continuation recognized the same two unclaimed jobs' changed waiting reason,
preserved both jobs, and completed the stop/restart/restore sequence.

The corrected runtime passed an active-combat observation over 42 seconds in one
round: shots increased 10 → 15 → 21, temporally correlated hits 7 → 12 → 17, and
kills 9 → 16 → 24. One time bonus was confirmed, telemetry stayed fresh and
running, and service PID `2161364` remained unchanged. A later sample reached
29 kills, 9,470 points, and no stuck events. These are live observations, not a
claim of perfect native shot attribution or a completed stage.

A 45-second MJPEG sample during active combat delivered 2,106 frames (46.8 fps).
The 95th percentile arrival gap was 47 ms versus the prior 78 ms baseline, but
the maximum gap remained 954 ms versus 985 ms. HLS reported no restarts, late
segments, or errors; measured audio lag was at most 67 ms. Occasional stutter
therefore remains. Earlier host sampling showed substantial CPU/GPU contention;
unrelated workloads were not stopped. Evidence is in
`after-dependency-samples-1793003577894556500.json` and
`stream-after-dependency-fix-1793003579272557800.json`.

Mixed mine deployment was then enabled through job `74c1976001d043e9`, with
verified settings `enabled=true`, `interval_s=10`, `only=false`. Its game-created
loadout changes take effect on the next round. Live placement, retained-route
escape, and mine-confounded shot attribution remain observation work until
recorded below.

## Continuity investigation

Two recorded Restart operations launched a replacement RE5 session without
carrying over autoplay. The replacement's status showed `running=false` and
`mission=null` until a separate manual Start command arrived:

| Restart job | Replacement session suffix | Delay until manual autoplay Start |
| --- | --- | ---: |
| `72820083010c423d` | `284ea3539bb94658` | 211.680 seconds |
| `00d6812f677b4f11` | `1e4d895c3d5f45f9` | 335.364 seconds |

Both jobs recorded `mode=restart`, actor `operator`, and the desktop Node client
as their origin. Their emulator exit code `-9` followed the restart's explicit
`stop_game` operation; it is not evidence of a spontaneous emulator crash.
A separate fresh launch following an explicit Stop was excluded from these
intent-carryover examples.

Reconnect commands also reached obsolete sessions. Job `0a6cf58a5e93409e`
requested `restart_stream` for the already replaced session ending `5dbecc975d834278`
and failed with `SessionGone`. An autoplay Start sent to that same ended session
also failed before execution.

The current session's sampled stream had fresh frames, one viewer, and no
recorded stalls or encoder events. Its bot was running at 46 kills and 18,670
points. This rules out an active stream outage during that sample; it does not
explain every historical interruption. An older stopped run retained
`mercmode_boundary_error="timed out"`, which remains an observation rather than
a proven cause for all interruptions.

## Active continuity corrections

The source changes preserve a verified solo autoplay run across the exact
same-game restart replacement. A newer Stop, a real player takeover, or another
input owner prevents automatic resumption. Explicit continuous mode also permits
the existing recovery path to replace a persistently unreadable game and resume
its bot; it is not a promise of uninterrupted operation under every failure.

The input handler now distinguishes a new player press from neutral button
releases sent while reconnecting a viewer. Releases still reach the emulator
without claiming control from a bot. Transient native RAM reads receive bounded
retries with the bot's held keys released. A persistent failure remains visible
and can trigger recovery only when continuous mode is enabled.

Stream upload writes now have a timeout, allowing a stalled upload connection to
reconnect without restarting the emulator. Desktop reconnect requests resolve the
current same-game replacement before sending `restart_stream`; compact-window
commands also use that window's session. These backend corrections have been loaded; the desktop still needs its renderer
refreshed to load its reconnect and command-target corrections.

## Prepared activation procedure

The independent helper is
`gbox-data/re5-audit-20261026/continuity-activation/activate_continuity.py`, with
`recover_re5_aim.py` beside it. It must run through an independent SSH process
outside `gbox.service`, using the existing gBox Python environment. The deployment
manifest and every staged file must be present in that same activation directory.
The helper reads the API token on Spark and does not copy it into receipts.

Run `snapshot` first and retain its printed SHA256. Confirm it identifies the
current session ending `bf05f8a4bc4147e2`, a running bot, and disabled mine
deployment. Then run `install`, `stop`, `activate`, `reload`, and `restore` in
that order, each with `--apply --snapshot-sha256 <printed hash>`. The snapshot
path is fixed to `original.json` beside the helper. An existing phase journal
prevents repeating an operation whose outcome needs inspection.

The snapshot records current modifier and team settings and the exact successful
autoplay Start input. Reload addresses the captured session ID explicitly;
another game's Last Played entry cannot redirect it. Source installation checks
all old and new hashes before replacement, permits new files only when the old
hash is null and the target is absent, and stores backups by full relative path.
Manifest targets are confined to `gbox/` and `clients/` and cannot traverse
symlinks. The helper's 13 local guard regressions passed.

Before stopping, the helper rechecks settings against the fresh snapshot. Restore
keeps mine deployment disabled, verifies modifier and team readback, then starts
autoplay with `continuous=true` and checks that the bot reports that mode. Existing
guards still reject unrelated active local jobs, busy conversations, and
service-owned Hermes executions. Live gameplay, stream progress, and successful
recovery remain acceptance work after activation; none is claimed by these
preparation checks.

Private continuity receipts and the bounded historical job/session evidence are
under `system/gbox-data/re5-audit-20261026/continuity/`.

## Expanded platform request

The operator prioritizes Switch RE5 with native-hooked Mercenaries/No Mercy,
then prepared rotation across titles, while retaining aiming, route, mine,
co-op demonstration, and streaming requirements. The supplied `_switch/Resident
Evil 5/CUSA04284.pkg` is actually PS4: its header is `7f434e54` and content ID is
`EP0102-CUSA04284_00-RE5HDPS400000000`. The operator confirmed the wrong version
was copied and will supply Switch files later; testing the PS4 package is now
authorized. No Switch or PS4 native bot parity has been verified. The existing
PS3 bot remains running while the separate PS4 attempt is prepared.

Validation so far includes 217 focused Python checks, 57 intent/recovery checks,
36 claim/handoff checks, 32 interface checks, 19 F3/PiP checks, and 36 watchdog
checks (these suites overlap). The existing stream pacing suite passed all 11
checks on Linux; a 25-millisecond timing expectation fails on Windows (two
frames instead of three), without any change to that stream implementation.

## Activated warm-launch correction

The previous warm-launch path paused as soon as the emulator exposed guest
memory. That can freeze shader compilation before a usable title screen, while
the scheduler mistakes the pause receipt for a prepared game. The replacement
observer lets boot continue and waits for a stable, verified native menu before
pausing. Launch work returns immediately; observation is bounded to ten minutes
and runs separately from input, capture, and session polling. A native menu
confirms boot readiness, not that every later stage shader has been compiled.

Readiness is currently verified only for the supported RE4 GameCube and RE5 PS3
builds. The observer rechecks live instruction signatures, tracks the exact
emulator process and generation, and rejects loading screens. Unsupported,
failed, or still-loading sessions are not advertised as ready. New preloads
require a native readiness receipt; an older worker's bare `paused=true` receipt
does not qualify. Previously played and parked sessions retain their existing
reuse path.

Manual input, session replacement, and mutating controls cancel preparation.
Autoplay Start and Stop now cancel under the same lock used for the final pause,
before driver construction or setup can acquire input. If preparation has just
paused that exact session, Start resumes only its own pause and verifies the
resume before setting up the bot. Stop does not resume, read-only status/list
requests do not cancel, and manually owned or replaced-process pauses are not
changed. An unsuccessful resume blocks setup and remains available for an
explicit retry. A claimed background load or successfully resumed prepared
game also returns to normal process priority before bot setup.

If native preparation fails after its pool entry has been claimed, fallback
re-resolves the exact launch, worker, and game before closing it. This retains
the session identity needed to remove the failed emulator and permit the cold
retry. A cancelled or human-owned session remains untouched. The observer also
closes its independently opened native RAM reader on exit.

The combined readiness/control, warm scheduler, launch, priority, autoplay
intent, stream-supervisor, and stream-watch suites pass 217 checks. Regressions
cover a simultaneous pause/Start handoff, cached-but-changed RE4 signatures,
failed-preparation cleanup with both known and late-arriving session IDs,
revoked ownership, and RAM reader cleanup. These warm changes are active on
lilspark; a live multi-game rotation has not yet been validated.

An isolated live RE4 warm trial subsequently passed on worker
`78c5c9dcb732486e`, preserving the running RE5 session ending
`8cfd53d2abb04f3b`. Launch `6a6ceab810d44c30` reused the cached G4BE08 Disc 1
and existing menu jump, taking 14.094 seconds. The observer then took 2.124
seconds to confirm `select_stage`, publish native readiness, and pause. The
debugger independently reported `PAUSED`; the emulator processes were at
niceness 10. Autoplay Start `65951c8ccefb4ada` resumed that same preparation,
published `resumed_by=autoplay_start` with `paused=false`, and restored niceness
0. RE4 progressed through loading into a native round during four spaced
samples; that brief sample did not establish RE4 combat effectiveness.

Cleanup `28f3d38d6b3d4ed4` stopped only the test RE4 session. RE5 remained live
and advanced from round 2 to round 3; its sampled stream advanced from sequence
33835 to 35217 with 0–20 ms frame age and no recorded stalls. The p95 frame gap
was 47–56 ms, with occasional 0.5–1.3 second gaps still present. The preflight
had 51.09 GiB available and 58% memory used. MercMode settings were unchanged.
Private receipts are under `gbox-data/re5-audit-20261026/warm-validation/`.

The stream review also found that an explicit encoder reconnect reset the
reported frame timestamp while retaining the old picture. The active fix
preserves that picture's actual age; the separate encoder-start timestamp still
provides startup grace. A regression covers both freshness and startup timing.

The final broad Python regression run passed **1,640 tests**. The combined
interface run passed 85 checks, and its browser recovery check passed separately
with the required browser process permissions (86 interface checks in total).
These checks validate the covered behavior, not uninterrupted real-world service
or complete native bot support on another platform.
