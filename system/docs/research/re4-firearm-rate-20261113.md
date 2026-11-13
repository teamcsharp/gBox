# RE4 Switch firearm recoil and pump pacing — 2026-11-13

The reported slow shotgun was real. A read-only 20-second trace from round
`aa770748789a40b9b1ec9c1eb194ef2e` sampled native RAM 992 times, at approximately
20 ms intervals. The held shotgun was item44/class7. Player motion speed at
`+0x304` remained **1.0 throughout**, although the configured fire tables were
20x. Firing routine `[0,6,2,1]` occupied 451 samples; individual observed firing
episodes lasted approximately 1.21 seconds and advanced through frames0–36.
This includes the full shotgun firing/pump cycle. Changing the handgun-style
fire-rate table alone did not accelerate it.

The original evidence is on Spark at
`gbox-data/mercs/analysis/re4-rapid-native-20261113.json`, relative to the runtime
`/home/ehm_eckx/gBox/system`. The reader opened the emulator memory read-only;
it did not alter the round. These samples establish animation pacing, not a
count of bullets or hits.

## Native basis

Build `82C2A04A21D3E0B850F273D4149C9003`, ELF SHA256
`c8e8f22f9996b7d6de8913133c791579dc0e6df43d32ef9478dd13781c303433`:

- `main+0x311400` dispatches the current player routine, then invokes the
  player's virtual callback at vtable slot`+0xA0`.
- `main+0x2B7C60` propagates player motion speed`+0x304` into the animation
  update. The weapon object is player`+0x938 -> +0x38`, with speed`+0x304`.
- `main+0x31E060` is the handgun-style frame-crossing gate. Keeping its
  three-frame floor preserves that native gate; it does not remove the
  shotgun's recoil/pump animation.
- The independent native shotgun investigation identified
  `main+0x336510`: it calls the weapon trigger`0x2E8EA0`, traces the pellets,
  and advances player routine byte`+0x117` to1. The rate guard does **not**
  treat entering this routine as a shot receipt.

Ghidra exports are under
`/home/ehm_eckx/gBox_alt/analysis/merc-full/re4-c8e8f22f-20261113/`, named by
eight-digit function offset. No game code or level assets are included here.

## Change and ownership

The existing player callback now invokes an authored 508-byte guard in the
already vetted executable cave, before tail-calling the character's original
callback. The original call mailbox fields are unchanged; an appended passive
rate section ends before the existing scratch object. Private vtable clones
remain in the private data page, outside executable storage.

The host refreshes a lease of60 native updates. The guard only applies a
bounded1–20x rate in a living player's gun routine `[0,6,0..3,*]`, for measured
firearm classes1–15,17,33,46. Bow, knife, egg, grenade, reload/use, movement,
damage and traversal routines do not acquire this gun rate. Bow/throwable
settings remain separate.

Only baseline1.0 or the guard's own previously applied value can be changed.
Leaving the admitted routine or expiring the lease restores only the value
still owned. An external slow-motion/write is preserved. Player unit identity,
current weapon-object pointer and object unit identity protect recycled
allocations. Detach stops the process briefly, restores still-owned speeds,
then removes the callback. A fresh binding clears old passive leases.

The callback runs after the native routine dispatcher. It observes that
routine's transition and restores before the next routine update; this is
stronger than a Python polling-only rate, but is not evidence that every
possible asynchronous interruption has zero transitional animation effect.
The patch accelerates recoil/pump animation; it does not delete animation
states or claim a literal20 bullets per second for every weapon.

## Verification and activation

The assembly is reproduced with Keystone, checked with Capstone, and executed
with Unicorn. Tests cover every admitted class/action, excluded actions and
classes, original call ABI, lease expiry, death, external rates, actor/object
reuse, invalid multiplier, pointer rejection, coherent observations, busy
controller admission, and detach restoration. Existing native calls, first
aid, mine darts, weapon replacement and bow behavior are also regressed.

The upgraded dispatcher requires a **fresh RE4 process**. The controller
refuses to replace an older nonzero cave image inside an already-running
process. A backend restart alone cannot activate it there.

Status distinguishes `gun_rate_configured_x`, `gun_rate_applied_x`,
`gun_rate_scaled_frames`, `gun_rate_restores`, and a bounded coherent
`gun_rate_observation`. Scaled frames and routine observations are never
discharge/hit evidence. Live post-activation pump/recoil cadence remains to
be measured; offline instruction tests alone do not prove gameplay cadence.

## Fresh-process observations and readback repair

Round `b96ab13521f44b0ba3753d1bd5afbe7b` ran on worker `e41fad8986bf40a5`
after backend `c1a97781`. The guard recorded 172 scaled frames and seven
restorations. The host also reported `memory write not confirmed by read-back`:
the native update can consume the countdown between its publication and the
adapter's equality check. A successful countdown write must not cause the
three-second error backoff to outlast its 60-update lease.

Only this countdown now accepts an already-consumed publication. It requires
the exact adapter equality error, unchanged controller ownership, coherent
before/after native sequence readings, bounded forward sequence progress,
and a remaining positive lease consistent with at most those native updates.
A missing write, expired lease, identity change or unrelated failure still
fails. Tests execute the actual authored ARM64 guard between publication and
readback, including sequence wraparound.

The native discharge reader also accepts the currently attached controller's
private player vtable clone after checking its process, build, player,
original class and exact clone identity. Previously its original-vtable-only
test excluded the very player carrying the gun-rate/defense hook. This does
not broaden discharge proof: the same-owner native post-emission step edge
is still required, and explosion-confounded damage does not train aim.

Focused validation: 232 tests passed across `test_re4_discharge_witness.py`,
`test_re4_weapon_rate.py`, `test_re4_native.py` and
`test_re4_switch_bow_rate.py`. The live sample contained no measured firing
cycle suitable for a post-fix cadence claim. Eighteen of the round's twenty
observed kills were attributed to rings; those are not a firearm accuracy
measurement.

## Separate stalled-round investigation

The same round stopped advancing its clock, player position and callback
counter with item54 (Mine Thrower) selected. The equipment refresh mailbox
had already completed. Two bounded read-only debugger captures found
CPUCore_0 inside the model skinning loop `main+0x4EC530`, at offsets
`0x4EC67C` and `0x4EC5FC`. Both sessions detached successfully; the process
was verified sleeping with `TracerPid: 0`, not left debugger-stopped.

The session records `cpu_backend=nce` and `address_mode=direct`. The read-only
signature scan found main at `0x3CA7C04000`; the debugger's actual instructions
at the sampled PC match the pinned ELF skinning instructions at that offset.
These observations identify guest-native execution, not a host JIT routine.

Offline instructions establish that caller `0x4EC39C` loads the loop count
as an unsigned halfword from the mesh header at `+0x42`, then calls at
`0x4EC3AC`. The callee copies that count into `w22` at `0x4EC560` and advances
12-byte weight records until its outer index equals it. The saved thread
instead held `x22=0x5511FBD8` and outer index `x24=3198906`; this is inconsistent
with an intact call from that 16-bit count. The location of the stall is
proved, but the source of the corrupted runtime state is unresolved. It is
not established that REFRESH itself hung, that a particular donor caused it,
or that the gun-rate guard caused it. No asset was quarantined and no loop
bound or game memory was patched on this evidence.

The closed session used overlay `recovery-re4-fit-v4-20261110` (22 files), with
HUNK on Base. An offline audit of all nine modified UDAS packs parsed 244 BIN
models. Every model's byte weight count at `+0x28` matched its halfword count
at `+0x42`, and all were below 256. Those on-disk headers therefore do not
select the stalled large-count skinning path. The HUNK pack `pl06.udas` hashed
to `23f02629d763b5b03adfc68582452473567ed205655891f3efe041bb4a8368ed`.
This validates those count fields, not every runtime object or resource
lifetime. The metadata-only audit remains on Spark.

Spark-only archives, relative to `/home/ehm_eckx/gBox/system`:

- `gbox-data/mercs/analysis/re4-c1-native-cadence-20261113.json`
- `gbox-data/mercs/analysis/re4-c1-freeze-native-20261113.json`
- `gbox-data/mercs/analysis/re4-c1-freeze-gdb-20261113.txt`
- `gbox-data/mercs/analysis/re4-c1-freeze-gdb-registers-20261113.txt`
- `gbox-data/mercs/analysis/re4-c1-model-build-audit-20261113.json`
