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

- PR1576 preserved target-confirmed RE5 crowd fire; 1578 stopped transient
  health-probe errors from revoking advancing streams. Neither proves S rank.
- PR1579 corrected critical-health escape/death accounting; 1580 corrected
  command consumption. Request6121's death-accounting finding is assimilated.
- PR1581 added native attachment of already-created RE5/RE6 inventory weapons.
  Live attachment was measured; arbitrary weapon creation remains unfinished.
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

`POST /api/sessions/{sid}/interventions` takes `op: flash_now` and a fresh
UUID `request_id` for each click. GET returns capabilities and receipts.
Only a verified native result is confirmed; queued is not success. Lost/expired
requests never replay into a later player life. MCP `game_intervention` shares
this queue; `game_mod_ops`/`game_mod` expose supported active mods.

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

i9 worker4a3cd49611f447ea resumed Merc3D session
`4a3cd49611f447ea-5a2f6bffab094a45`; two completed native rounds and advancing
nonblack video were observed. Its old rebuild jobb687b9946e9e4b1d failed after
a one-hour git-pull timeout; requestaa3ab08d3f494037b19d2d6b509ca4cb did not install
the supervisor. `local_window:true,viewers:0` does NOT prove PiP containment.
RE4 VR/Refract runtime `D:\gBox\refract` is not ready, so the requested two-title
five-match loop is unfinished. SSH keys, SMB and DCOM credentials were rejected;
WinRM/RDP/local API unreachable. An async question asks for an existing
authenticated i9 admin connection. No answer yet; authorization already exists.

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
