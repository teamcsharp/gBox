# MercMode continuation: 2026-10-30

This checkpoint supersedes the older October 28/29 status sections. The full
operator request is **not complete**. Preserve the requirements below instead
of treating a merged hook or synthetic test as gameplay acceptance.

## Authorization and operating rules

The operator authorizes GBox implementation, merges, deployment, remote
administration and owned-session recovery. Use the existing authenticated APIs
and exact process/player lifetime guards for RAM work. Never launch games on
JAYBUILTFINALE. Do not bypass missing i9 credentials or application permissions.
Do not message Pine: the operator plans to request its client integration later.
No agent delegation is authorized by this handoff.

GitHub destination is `teamcsharp/gBox`, the existing origin and repository of
operator-requested PR1576. Root main contains an unrelated scratch commit and
user scratch changes: **do not push root main**. Use feature branches from
origin/main. Native QTE prototypes in the worktree are uncommitted research,
not delivered production hooks.

## Merged work and evidence

- PR1605 (`993fb7fc`) waits for engine input release before native RE5 weapon
  commit. Production Hydra replacement confirmed in961.9ms end to end/59.6ms
  native, without inventory UI. The subsequent round failed: zero shots and
  kills, then death within about a minute. It does NOT verify a120-second lock
  or useful combat. Receipt `re5-primary-production-1793350061006858623.json`,
  round `3e7d3ee26b2f4944beb3816df6eaf53a`. The `primary_weapon` stats dictionary
  is currently filtered out by tools.TELEMETRY_BLOCKS; a null API field alone
  does not prove the policy was absent.

## i9 recovery and PiP checkpoint, 2026-10-30 09:34 UTC

**SSH works as `maste@10.89.1.43` with the existing key.** Earlier attempts used
the wrong account. Do not ask the operator for a password or another walkthrough.
The installed interpreter is `C:\Users\maste\AppData\Local\gbox\venv\Scripts\python.exe`.

The i9 now runs the tested branch `fix/desktop-authority-reconnect-20261030`,
head `837263e9ccad40b3f29d503013c1ea8ed14069f6`. It is pushed but **NOT merged**:
GitHub PR creation returned a secondary content-creation rate limit at09:08
and09:15 UTC. Root main and Spark remain at993fb7fc; never push root main.
The repair branch contains:

- `3d3b6484`: replace an expired paired worker transport after30seconds while
  preserving old native-session evidence. The former1800-second fence caused
  the i9's observed half-hour blackout. Superseded workers cannot retake control;
  verified administrative closure still permits immediate replacement.
- `fa9d53ce`: rebuild children use DEVNULL input. On the i9, a disposable
  process inheriting a pipe with a pending read hung at startup; the same
  command with DEVNULL finished in375ms. Seventeen rebuild tests pass,
  including the real Windows pipe regression.
- `837263e9`: a fresh local PiP dispatch can supersede an older pinned stream;
  old dispatches on reload and newer manual selections remain protected.
  Forty-seven stream-picker/MercMode tests pass. Federation/admin coverage:
  75passed plus the corrected source/RPC test; its previous expectation also
  failed unchanged on main.

Independent per-user recovery task `GBox Recovery 2141adfbccd2e0d6` is installed,
paired with DPAPI, and connected. Actual admin relaunch request
`d434f8cc21f14419ae47bb64a931aec6` reached **recovered**, with an exact native
closure witness and new worker `3f1fe9e383e84ed3`, epoch
`68690c7c095985ddb3685653216f91bd`. Request1793352516.29, returned1793352560.77.
Controller `537bb37dd9e6aeb7d4fd0921f09dfb0f` lives independently of Electron.

Current Merc3D session at observation:
`3f1fe9e383e84ed3-112a70229ad0428e`, native PID60544. Its local scheduler is
autoplaying and has recorded a completed round. Five-match setting is retained.
The app's saved view records that SID with compact=true. A frame from the i9's
own `/api/workers/{wid}/desktop/stream?view=app` visually confirms Merc3D inside
the1031x580 PiP. Local evidence `.scratch-merc-20261028/i9-app-pip-20261030.jpg`.
The game uses Chromium capture: its native source is at(-16000,-16000), not a
child HWND. That is expected capture behavior; do not reparent it manually.

Old rebuild `a9ca2b83b9284b5e` was canceled and is failed, not successful.
Its pip subprocess PID12300/birth1793350706.516010 was identity-checked and
terminated after cancellation to unblock the old Console implementation.
Local job `0a5f50f309ef415c` required explicit local cancellation: central
cancellation did not propagate. Direct SSH git pull succeeded in seconds.
The new branch is loaded, but a full subsequent production rebuild is untested.

A central PiP dispatch `ad1f447d8dbd41bc` stayed queued behind ongoing work.
It was canceled before directly applying the same authorized request through
the i9 loopback API. Local dispatch `cadbcda349e54193a500deab55900419` is applied.
Central desktop-stream capture timed out; local desktop-stream capture works.
Follow up both bridge gaps rather than treating SSH as their permanent fix.
RE4 VR/Refract remains unready; the requested two-title rotation is unfinished.

## Earlier merged work

- PR1576 preserved target-confirmed RE5 crowd fire; 1578 stopped transient
  health-probe errors from revoking advancing streams. Neither proves S rank.
- PR1579 corrected critical-health escape/death accounting; 1580 corrected
  command consumption. Request6121's death-accounting finding is assimilated.
- PR1581 added native attachment of already-created RE5/RE6 inventory weapons.
  Live attachment was measured; full arbitrary-weapon acceptance remains unfinished.
- PR1582 moved visible PiP geometry ahead of slow caption/guest work. PR1584
  reduced guest-state polling contention. Actual desktop transition latency is
  unmeasured because the computer-use runtime failed twice with missing kernel.js.
- PR1583/1585 fixed remote model origin and isolated headless Blender stdin.
  Bayman's normal worker job ce45796b5f8e4694 succeeded: 2 objects, 7013 triangles,
  40 packed textures in the local clipboard. Visual paste acceptance is unverified.
- PR1588 added run enemy census. PR1590 delivered the native RE6 flash queue,
  viewer/PiP/MCP controls, shared mod sidebar, following map page and PiP Tasks.
- PR1591 removed damage-query/database contention; PR1594 removed repeated
  MercMode alias-snapshot work. PR1592 allowed a new flash after a reclaimed
  projectile only when the previous call completed and original dispatch returned.
- PR1593 reconciled stale desktop rebuild reservations. PR1595 recorded Windows
  exit receipts; PR1596 removed inherited Python environment from app relaunches.
- PR1597 (`49db6aebcb53f876ab66b5c7205236f0e65a1381`) added native RE5 flashes.
  PR1598 (`424dfc4aa742601414ba04c1ad94aac5aade6e57`) prepares RE5 dispatch before
  advertising the button. Both are merged, assimilated locally and deployed.
  See [RE5 native evidence](research/re5-native-flash.md) and
  [RE6 native evidence](research/re6-native-flash.md).
- PR1602 (`7954c1eb4fdaa3dee27cc88b6627bcf50788cf5f`) added native RE5
  weapon construction/commit helpers and the24-record inventory reader. It is
  merged and deployed with a fresh emulator. A live Hydra was constructed,
  equipped at grid0 in51.7ms and observed in firing motion; no enemy health
  reduction was observed in that short trial. See
  [weapon evidence](research/re5-native-weapon-construction.md). The follow-on
  viewer/MCP selector and120-second primary-lock policy have automated tests;
  live queue/lock and other weapon families still need acceptance.

RE5 deployed API acceptance before1598: session
`5cb6330c56514413-079bf401635a4f94`, PID1584702, birth1793342305.54,
Sheva Cos1 generation1. **20 distinct requests confirmed 20 native explosions
in 2325ms**, native calls25.6-195.3ms. Seven enemies were observed in DmgFlash.
Inventory selection was identical and original vtable restored. First cold click
took1848.8ms overall,1139.9ms native; this motivated1598. Native resources were
not represented by an equipped flash. Receipts on Spark:
`re5-production-flash-1793342427225756360.json` and
`re5-production-flash-1793342443371018469.json`.
Post1598 fresh-process acceptance passed: Jill Cos2 generation1 in session
`611d2fa684d545c1-9d058a82c73f4c90`, PID1652982, birth1793342773.07,
with no flash in inventory. First click442.5ms overall/120.4ms native;
subsequent20/20 effects in2505.1ms, with seven observed DmgFlash enemies,
unchanged inventory and original dispatch restored. Receipts
`re5-production-flash-1793342949121516917.json` and
`re5-production-flash-1793342975883739932.json`. A strict20/two-second guarantee
is not established. Ticket6102 closed with audit220617 at1793343113.0215154.

RE6 production API acceptance after1595: 20 confirmed explosions in1391.1ms,
individual effects20.2-146.9ms. Receipt
`production-flash-burst-1793338628335373721.json`. Earlier burst20/1039.6ms.
RE6 still requires flash resources already represented in inventory; removing
that restriction needs native resource-loader validation. Do not hide it.

LAN sample after1594/1595: **600 seconds,31043 frames,26205 changed,one connection,
zero stream errors,798 controls with zero errors**. Largest frame gap953ms;
control p95 94ms,max3422ms. During20 RE6 effects,another90-second sample had
4978 frames,one connection,zero stream/control errors,129 successful controls.
These are real LAN HTTP/video probes, not actual desktop click-through acceptance.
Local receipts: `.scratch-merc-20261028/lan-stream-controls-after-1595-20261030.json`
and `lan-stream-intervention-20261030.json`.

## Interfaces already available

`POST /api/sessions/{sid}/interventions` takes `op: flash_now` or
`op: equip_primary, args: {item: <catalogue low-byte ID>}` and a fresh
UUID `request_id` for each click. GET returns capabilities and receipts.
Only a verified native result is confirmed; queued is not success. Lost/expired
requests never replay into a later player life. MCP `game_intervention` shares
this queue (weapon item is a top-level MCP argument); status.options.weapons
lists offered choices. `game_mod_ops`/`game_mod` expose supported active mods.

PiP/web viewer and map share `clients/web/viz/stream-interventions.js` and the
live controls sidebar. Browser tests verified distinct clicks and setting
readback without replacing the video image. PiP right-click includes Tasks.
`/mercs-live.html?worker=<id>` follows that computer's active run across title
changes and offers document PiP where available. MCP `live_run_map` resolves
the same active session. Five-second map-point enemy diversion is NOT wired.

## Machines: reobserve before mutations

Spark SSH `ehm_eckx@10.89.1.246`; deployed system
`/home/ehm_eckx/gBox/system`; venv `.venv-linux-aarch64/bin/python`.
API127.0.0.1:8765, token file `gbox-data/api_token` (never print it).
Scratch/evidence `/home/ehm_eckx/gBox_alt/scratch/agent`.
`bash ~/bin/gbox_autodeploy.sh` deploys merged main; new core worker code may
need `sudo -n systemctl restart gbox.service`. Restart kills warm sessions;
batch changes and allow several minutes for autoplay recovery. Five-match
RE5/RE6 rotation remains configured. Session/PID identities above are historical.

JAYBUILTFINALE desktop recovered with clean interpreter environment: PID52568,
birth1793338039.2785914 at last observation. Local API18765 and bridge healthy;
worker65566a22f858493d,installation772ec831bb3881c8fe5cadbf2ca43f0458ee18131c4358fcb8969861c322d5f0.
Zero local game sessions. Do not rerun the recovery script against a healthy app.
The test venv injects PYTHONHOME; do not use it to launch the desktop.

i9 historical worker4a3cd49611f447ea resumed Merc3D session
`4a3cd49611f447ea-5a2f6bffab094a45`; two completed native rounds and advancing
nonblack video were observed. Its old rebuild jobb687b9946e9e4b1d failed after
a one-hour git-pull timeout; requestaa3ab08d3f494037b19d2d6b509ca4cb did not install
the supervisor. `local_window:true,viewers:0` does NOT prove PiP containment.
RE4 VR/Refract runtime `D:\gBox\refract` is not ready, so the requested two-title
five-match loop is unfinished. Earlier SSH attempts, SMB and DCOM credentials were rejected;
WinRM/RDP/local API unreachable. The operator answered that they relaunched
the app and there was no special login. At1793348658 the i9 had not returned:
last heartbeat1793348290, current_run null. Recheck the existing GBox connection
before requesting access again; authorization already exists. A port probe
after that reply still found22/135/445 reachable and5985/5986/3389/18765 unavailable.
This access paragraph is historical; the recovery checkpoint above supersedes it.

## Ticket acceptance and next work

| Ticket | API ID | Remaining requirement |
| --- | --- | --- |
|5972|9b62ade91d2b4aed|All-title flash, defensive mine/grenade/quick-attack roulette, actual desktop interaction, remaining viewer hooks|
|6102|d7045c402d574582|DONE: repeated native flashes and fresh-process first click verified; audit220617|
|6103|ebb2fbc17c54480c|RE6 repeated native flashes proven; arbitrary character/resource availability unfinished|
|6104|e94655b56a334118|Any RE5 weapon constructed and equipped now, usable firing, primary lock|
|6105|bc39fb3dc88d61af|DONE: exact-run analysis653febf84bac4b69bf1ce3234bc2bbc8; do not reopen|
|6106|bd415a485a244111|Same RE5 any-weapon acceptance; native mines/usable gun firing unfinished|
|6107|2a755e634b9c4acf|Any RE6 weapon constructed now, usable firing, primary lock|

User-selected weapon must replace the first/main slot now, forbid bot swaps for
at least two minutes and remain preferred for the match. Existing next-round
templates and attachment of existing objects do not satisfy this.

All-QTE native success, five-second enemy diversion/return, native mines and
grenade bursts, door/fence navigation, consistent target hits/boss dispatch and
survival with native S-or-better remain unfinished. Missing rank is unverified;
death or below S is failure. Do not close tickets on synthetic flags alone.

RE6 `qte.c`/`test_qte.c` in the feature worktree are ABI-tested prototypes with
ZERO live invocations. They do not prove all-QTE success. Do not mix an old
scratch dispatcher with a production controller in the same emulator process.
