# RE6 native launcher ring research, 2026-11-13

Build: Switch main `061D2A06`, ELF SHA-256
`441516ee1a4f26720e92956ecdb6cedcf253022cad7cbae239ad7e8ba002dd78`.
Addresses below are main-relative. Ghidra exports add `0x100000`.

The former shell branch called the thrown-grenade initializer with a shell DTI,
relocated the returned object, and counted it as a detonated, verified grenade.
That initializer writes bomb fields and requests bomb throw action 7. It does not
implement the shell launch or impact path. The controller now refuses this path
before attaching or allocating, including `allow_unverified` probes and direct
`_ring_one` calls. `allow_unverified` only bypasses missing live evidence for an
implemented operation. It cannot turn an allocation into a blast receipt.

Validation: 54 ring, scatter and class-image tests passed. This includes three
regressions that prevent native calls or writes for the unsupported shell kinds.
A stale hand-spawn test now checks the absolute DTI pointer required by the
parameterized wrapper, matching the previously shipped address correction.

## Native launch and impact evidence

- `F72760`, the grenade launcher's firing method, resolves the chosen ammo class,
  allocates it through the item factory with mode **14**, calls `F6B500` to set up
  muzzle position, orientation and previous position, detaches it through its
  vtable `+0x98`, clears flags `0x2800` at `+0x14`, assigns player ownership at
  `+0x1300` and launcher identity at `+0x38E0`, and registers the projectile through
  `1ED840`. The bomb initializer uses mode 13 and a different action lifecycle.
- `F6B500` writes position `+0x60`, prior position `+0x3890`, the initialized-history
  byte `+0x38A0`, rotation `+0x70` and origin `+0x38D0`. It requires a real launcher's
  bone data; calling it on a player or fabricated launcher is not a valid shortcut.
- `F59F30` advances launcher shells from local velocity `+0x3870`, world velocity
  `+0x3880`, rotation and the frame delta. It applies delayed gravity using
  `+0x3960/+0x3964`. These fields are not the bomb initializer's velocity fields.
- `F45AB0` performs shell movement and collision. `F45340` dispatches its native
  impact to action 17, 18 or 19 according to collision flags. The shell-explode
  action's DTI is `296A160`, vtable `288C660`, allocator `11310B0` (0x1F0 bytes),
  start `11311C0`, tick `11314E0`, and cleanup `1132060`.
  **Correction:** the earlier note's `296A128` / `288C6C8` identified `throw_wep`,
  action 16. Cross-checking the action table returned by `6F9340` against the
  `_INIT983` registrations resolved this before the probe was installed or used.
  A requested shell action must not be reported as an enemy hit.
- Constructors `F5A3D0/F5A110/F59C80` allocate **0x3970 bytes** for
  `uWp1302/uWp1303/uWp1304`. Their final vtables are
  `283AD18/283A880/283A3E8`. The DTI metadata value `0xE5C` is not the byte allocation
  size. There is no established out-of-bounds write merely from the old wrapper's
  offsets being above `0xE5C`; the defect is incompatible field/action semantics.
- `B2BC70` maps grenade launcher item `0x112`, inventory mode 0/1/2, to shell items
  `0x133/0x134/0x135`. It maps rocket launcher `0x11B` to `0x136` (`uWp1305`), **not**
  to `uWp1304`. `LAUNCHER_ROUNDS` now has that correction; the rocket DTI and
  metadata match the existing weapon tree. This does not enable a rocket control.

Targeted exports are retained on Spark under
`gBox_alt/analysis/merc-full/re6-shell-research-20261113/`. The project requires
Ghidra 12.2; `/tmp/gbox-re6-shell-phase2.py` through `phase13.py` record the targeted
decompiler calls. Nothing in this investigation modified a running game.

## Payload evidence and remaining verification

The extracted `Msg_eng.arc` contains the native labels “40mm Explosive Rounds”,
“40mm Acid Rounds” and “40mm Nitrogen Rounds”. The three `uWp1302/1303/1304.arc`
archives each contain distinct hit resources and distinct sound/effect resources.
The `0x6E45FABB` hit resource's `attack_em` entry has these serialized values:

| Class | Damage | Attribute0 | Attribute1 |
| --- | ---: | ---: | ---: |
| uWp1302 | 1000 | 0x1142 | 1 |
| uWp1303 | 250 | 0x08000022 | 4 |
| uWp1304 | 300 | 0x00020022 | 4 |

The executable registers `cEm1000ActDmgIce`, `cEm3000ActDmgIce`,
`cEm3100ActDmgIce`, `cEm3200ActDmgIce`, `cEm5000ActDmgIce`,
`cEm5700ActDmgIce`, `cEm8100ActDmgIce`, and `cPlAction_pl_act_damage_ice`.
The nitrogen candidate therefore has its own damage payload; it must never be
replaced by flash or inferred successful because an object was allocated. An
implemented shell-only probe still needs a native explosion/effect receipt and
observed ice-state evidence on a susceptible enemy before the user control is
advertised as working. Boss susceptibility must be measured separately.

## Isolated shell-only probe

`native/re6_061d2a06/shell_probe.c` and its pinned Python image module use factory
mode 14, a whitelisted shell DTI/vtable, verified player generation and positive
HP. The spawn initializes a stationary shell at a supplied point, using the native
position/history/origin and velocity fields. It detaches the actor and assigns its
player owner. The constructor's null launcher pointer is supported by `F45AB0`,
which then obtains ownership directly from `+0x1300`. No launcher bone data or
bomb initializer is borrowed.

The arm function checks actor/player generations, ownership, the native action
manager and its shell-explode action, then sets only `+0x3954` bit 2. The native
launch raycast uses this bit for immediate collision, and `F45AB0` consumes it on
its next update. Return 1 means collision **requested**. It is not a blast receipt.

`re6_switch_shell_probe.inspect_shell` checks allocation identity before and after
sampling, checks the active action's own table entry and owner, then requires both
native explode phase `action+0x28 == 2` and the observed `(4,4)` enemy attack entry
in the bounded queue at `unit+0x2060`, count `+0x2308`. `11314E0` reaches phase 2
after native effects/sound dispatch and queueing attack entries 3 through 7.
Flight attack `(1,1)`, an arm flag, an action request or phase 2 without the enemy
attack entry cannot satisfy the receipt. Missing a short-lived queue entry remains
uncertain, rather than inventing success. Emission still does not establish a hit.

`probe_one` is separate from normal viewer grenade controls and bot tactics. It permits one
shell submission per player generation, requires launcher resources and at least
601 cm clearance from every player, and never sets `verified=True`. A timeout is
not replayed. Only its private mailbox packet is written from the controller;
actor changes happen in the guarded native functions. It does not change health,
equipped weapons or animation speed. No running game has received this probe.
The receipt also records up to eight nearby living targets before submission and
new `DmgIce`/`DeadIce` reactions afterward, with matching vtable/generation. Existing
ice states, flash reactions and recycled enemies do not qualify. Concurrent game
attacks prevent treating this correlation as exclusive kill or hit attribution.
The native shell retains its normal flight timeout; an allocated shell can still
explode if a later observation or arm call fails. The one-submission limit and
clearance checks therefore apply before allocation, not only before arming.

Static evidence: reconstructing the executable's load segments from the pinned ELF
and running `verify_re6_classes.scan` found zero padding and no direct B/BL, ADR,
ADRP+ADD or 64-bit literal references in the proposed ranges:

| Function | Main offset | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| spawn_shell | 0x18F2DB0 | 344 | faef57d8d6125c0911251a057ef776bf0b9126b41d5c45269465a85e796172f8 |
| arm_shell | 0x18F2F08 | 248 | 61f7f1a733d1c455d8b4b5e715de7bf74b16e6e8fe8d7e81440c7e4da96f952f |

The second range ends exactly at the text padding boundary, `0x18F3000`. The images
were compiled with clang 18.1.3, linked against the verified native symbols and
executed under ARM64 emulation at two ASLR bases. All 34 ABI tests passed, including
callee register preservation, ownership/generation/HP refusal, wrong-action refusal
and zero effect claims from arm alone. The full probe/ring/scatter/class suite
passed 115 tests before the separate rocket metadata correction.
The checked-in build script subsequently reproduced both images exactly in an
isolated Spark temporary directory. No generated image was installed in a game.

`scripts/verify_re6_shell_collision.py` additionally executes the actual extracted
`F45AB0` and `F45340` instructions in isolated Unicorn memory. Both local and world
velocity are zero, position remains unchanged, and geometric collision returns no
hit. At two ASLR bases, the forced-collision bit reaches native impact and requests
shell action 17; without that bit no impact/action request occurs. All four cases
passed. This validates the stationary launch path without inventing an epsilon
movement or borrowing another title's collision assumptions.

## Supervised live validation through the shared worker

The durable intervention queue accepts an agent-only `re6_shell_probe` operation,
with exactly `kind`, `point`, and `allow_unverified: true`. Sources `agent`,
`gbox-agent`, `mcp` and `probe` qualify; default viewer/operator submissions are
refused. This is a deliberate research opt-in, not a separate authorization role:
HTTP requests require the existing bearer token and select their actor with the
existing `x-gbox-actor` header. A JSON `source` field does not select the actor.
No count, raw pointer, custom
function or arbitrary code argument is accepted. Only the exact RE6 controller
advertises it; RE5's inherited transport does not. Normal grenade-kind rows remain
unverified. The worker uses its existing controller and lock, checks the claimed
round/player, and refuses while remote bombs still need detonation or the operator
owns input. It persists the full bounded receipt using the existing archive path.

After root review and deployment, select an active RE6 round with a loaded grenade
launcher, no outstanding remote bombs, and a susceptible enemy at least 601 cm
from every player. Capture a frame, select the enemy's current position as the
point, and submit one UUID through the existing session intervention endpoint,
with the normal bearer authorization and `x-gbox-actor: probe` header:

```json
{"op":"re6_shell_probe","request_id":"<one new UUID>",
 "args":{"kind":"shell1304","point":["<x>","<y>","<z>"],"allow_unverified":true}}
```

Replace the point placeholders with finite numeric coordinates. Do not invoke a
second independent controller. The probe waits at most 0.75 seconds for native
flight/action initialization before one arm call; all waits share an overall
3-second allocation budget plus the observation budget, and recheck the active
round, positive HP, claim expiry and ownership. A stale claim or missing effect
does not replay the shell. Check the archived per-shell phase/attack evidence,
new stable-identity Ice reactions, player HP and rendered effect before enabling
any ring. No such live submission has yet been made by this agent.

Remaining rollout gate: execute a single, supervised nitrogen probe, capture its
per-shell emission and a newly observed enemy `DmgIce`/`DeadIce` transition with
stable target identity, verify player clearance and inspect the rendered effect.
Only then consider a ring, with a receipt for each shell. The phase/attack observer
may need a native sampling callback if the queue clears between Python reads;
reducing the evidence requirement is not a substitute.
