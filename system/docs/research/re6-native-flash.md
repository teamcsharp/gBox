# RE6 Switch native flash: 2026-10-30

Build `061D2A06CD700785E987C42CE2D72231`, Linux Citron direct/NCE.
The production controller executes native allocation and explosion functions on
the player's game thread. It sends no pad input, changes no inventory slots, and
does not equip a flash grenade. Other builds/backends refuse this capability.

## Live evidence

Owned Spark session `8b14a71472484560-2161a51e76eb4110`, PID 998673,
process birth 1793304228.05; module base `0x3ca7c04000`.

- Native completion trial, player generation 35: 13 nearby enemies entered
  `cEm1000ActDmgFlash`; equipped slot 0, magnum weapon ID 7 and HP 900 were
  unchanged across the sample. The manager's original vtable was restored.
- Production-controller single effect: native completion 44.2 ms, whole call
  73.9 ms including snapshot/bootstrap work.
- Production-controller burst: **20 distinct projectiles, generations
  15535–15554, 20 confirmed explosion transitions in 1310.7 ms**. Individual
  native calls took 29.5–99.4 ms. Original manager vtable restored afterward.
- These timings measure the native controller, not browser-to-worker latency.
  The evidence is under Spark `gBox_alt/scratch/agent/re6-production-flash-*.json`
  and `re6-flash-native-completion-trial-998673-35.json`.
- HTTP queue/worker validation in fresh session `8b14a71472484560-3f0e1f54a2ce4db4`,
  PID 3964875 (birth 1793329309.91): initial installation and 20 effects all
  confirmed. With completion receipts batched, **20 HTTP requests reached 20
  native explosion receipts in 1596.4 ms**, generations 304–323. Equipped slot
  0, magnum ID 7, and HP 900 remained unchanged; original vtable restored.
  This used a loopback test API and the live game, not a simulated memory image.
  A later run with the reduced preflight took 2026.4 ms for 20 confirmed effects
  (generations 389–408), with the same unchanged hand/HP. Game-thread scheduling
  still affects latency; a strict two-second burst guarantee is not established.

### Deployed production API acceptance

PRs #1590 and #1592 are merged and active on Spark. The first production
20-click test confirmed only three effects before a projectile allocation was
lost. That loss now carries allocation evidence, and the controller can accept
a **new** click after confirming the previous native call completed and the
original manager vtable was restored. It never retries the lost click or clears
an unfinished/uncertain native call.

After deployment, session `30af953d95d24274-6070fe126cad45d2`, PID 538105,
confirmed **20 distinct HTTP requests in 1039.6 ms** through the production
queue, worker and native explosion path. Individual effects took 30.8–98.0 ms.
Receipt: Spark `gBox_alt/scratch/agent/production-flash-burst-1793334856314086402.json`.
This is one measured burst, not a universal latency or success guarantee; the
underlying allocation-loss cause still needs diagnosis if it recurs.

The ten-minute LAN sample after PR #1591's damage-event indexes/read-lock fix
received 29,713 frames (23,966 changed), used one connection, and reported no
stream-read errors. The largest frame gap was 719 ms. Of 751 control requests,
one `/api/mercmode` request timed out; successful requests had p95 297 ms.
The remaining timeout means full interaction/stability acceptance is outstanding.
Local receipt: `.scratch-merc-20261028/lan-stream-controls-after-1592-20261030.json`.

## Native path and guards

Player inline action manager `+0x13A8`, original vtable `main+0x2858318`;
update slot `+0x48` calls `main+0xF8CE10`. Bootstrap allocates a private 1024-byte
vtable/mailbox through the native allocator, preserving integer and FP inputs.
Mailbox publication is consumed once on the game thread, with owner/generation
guards. The original update runs after each dispatch. The allocation is reused
for later clicks and player lives; its lifetime is the emulator process.

Code occupies verified unused padding at `main+0x18F2640`, `+0x18F2880`, and
`+0x18F29C0`; bootstrap clone at `+0x25A3100`. Install pauses the exact process
only for first installation, validates all stopped threads, the exact HostMemory
mapping/inode/FD/preimage, and writes through that mapping's backing file.
Subsequent effects do not pause the game or rewrite code. Occupied padding or
different asset checksums refuse installation. Existing executed code is never
rewritten. Shipped sources and standalone ARM64 ABI tests live beside the assets.

Spawn repeats the ordinary throw's native constructor/setup/registration path:
`3BCF90(sItem, DTI 2951500, line 13, 0, 0)`, owned by the player, at their position,
with zero velocity. Wait for native `cWpAction_wp_act_throw` initialization.
The completion wrapper checks projectile class, owner, both generations, manager
and current action. It requests action 10 and runs the native manager update;
only the resulting native bomb action earns a confirmed receipt. This proves the
explosion path ran, not that every enemy in the level was stunned.

**Current resource limitation:** the player's inventory must already carry flash
ID `0x115`, proving its resources are loaded. Unsupported resources return
unavailable; preloading arbitrary weapons/resources remains separate work.
RE5, Merc3D, RE4 VR, all-QTE completion and five-second AI diversion are not
implemented by this controller. Do not close their tickets from this evidence.

## Interface contract

- `POST /api/sessions/{sid}/interventions` with
  `{"op":"flash_now","request_id":"a fresh UUID per click"}`.
- `GET /api/sessions/{sid}/interventions` returns capability availability and
  recent receipts. `queued`/`claimed` are not successful game effects.
- `confirmed` requires a verified native result. Lost claims become `uncertain`
  and are never replayed. Deadlines and player-life fences prevent delayed
  clicks reaching a later round. Retried UUIDs remain deduplicated after history
  pruning and application restart.
- MCP `game_intervention` uses the same queue. `game_mod_ops` / `game_mod`
  expose the Switch title's actual active mod operations.
- MCP `live_run_map` resolves the selected computer's playing run and returns
  current tactical data, stream path, and `/mercs-live.html?worker=<id>`.
  The map page follows title changes and offers document PiP where supported.
- `clients/web/viz/stream-interventions.js` is the shared viewer/desktop adapter.
  Pine can mount it with its authenticated GBox API wrapper and current session;
  no Pine message or deployment has been performed.
- The viewer toolbar's **Live controls** button opens the same bounded,
  session-checked mod/behavior sidebar as desktop PiP. The map page offers it
  too. Changing a setting waits for worker readback. Disposing the viewer
  invalidates in-flight preflight checks before they can submit another change.
  The real-browser regression exercised fire-rate readback and twenty distinct
  flash clicks without changing the displayed image's attributes.
- Actual desktop transition/interaction acceptance is still outstanding: the
  Windows computer-use runtime failed to start twice with a missing `kernel.js`.
  Browser regression results do not substitute for that desktop acceptance.

## User requirements still being implemented

RE5 native instant flash; any-weapon native resource construction/attachment with
the two-minute primary lock; five-second clicked-point enemy diversion with
automatic return to player pursuit; native QTE completion beyond the existing
grab handlers; door/fence navigation; sustained stream/input stability validation.
Tickets 5972, 6102–6104, 6106–6107 remain open until their full live acceptance.
6105 is the already-completed run analysis and must not be reopened.
