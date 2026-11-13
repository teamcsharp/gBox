# RE4 native Garrador aim and discharge evidence

Round `aa770748789a40b9b1ec9c1eb194ef2e` on Spark showed repeated shots toward a generic chest point while the operator was watching a Garrador's exposed back. Archived audit: `gbox-data/analysis/merc-tuning-20261113/re4-aa770748-garrador-audit.json`. Its 2600-HP boss received 235 recorded trigger requests over 72.46 seconds; the 3000-HP boss received 312 over 112.27 seconds. These are requests, not measured bullet counts. All 606 sampled ledger records were unconfirmed. Concurrent grenade rings make the observed HP decreases unsuitable as proof of gun impacts.

## Pinned native provenance

Image: Switch RE4 `c8e8f22f`; existing local ELF `.scratch-merc-recovery/re4-existing-main.elf`. Full Ghidra exports on Spark: `/home/ehm_eckx/gBox_alt/analysis/merc-full/re4-c8e8f22f-20261113`.

- `0008f470`: model type byte `unit+0x119` identifies Garrador types `0x0a`/`0x0d`. Damage through hit part `0x25` is doubled; other body and armor paths divide damage. The selected hit-part pointer is `unit+0x3e0`.
- `001cea50`: linked `YARARE_INFO` begins at `unit+0x3e8`. Active flag is bit 0 at `+0x24`; part number is the one-based short at `+0x26`; next link is `+0x30`. Local center `+0`, radius `+0x18`, height `+0x1c` are transformed through the selected live part matrix.
- `002b4f90`: part root `unit+0x108`. Packed parts use stride `0x1f0` when flag `0x2000` is set; otherwise next-part links are at `part+0x108`. The matrix is at `part+0x18`.
- The helper reads only the exact active sphere for part `0x25`, checks native class/type, live flag, owner ID, list consistency, finite matrix, plausible scale/reach, and freshness. It does not substitute a bind-pose chest when the swapped model's native geometry is missing or invalid.

## Native discharge boundary

The current weapon routine handler pointer is global RVA `0x1265a28` (GOT slot `0xb27d90`). Three verified handlers are admitted:

| Family | Handler | r2 table entry 2 | r3 table entry 0 | Native fire routine |
| --- | --- | --- | --- | --- |
| Shotgun | `3351a0` | `b0a100[2] = 3355e0` | `b0a168[0] = 336510` | `336510` |
| Magnum | `3270f0` | `b09ce8[2] = 3274d0` | `b09d68[0] = 328190` | `328190` |
| Killer7 (class6 only, magnum aim family) | `31cc60` | `b09758[2] = 31cfe0` | `b097c8[0] = 31ddd0` | `31ddd0` |

All three fire routines call native weapon trace/emission `0033b770` before storing `player+0x117 = 1`. The reader requires a double-read coherent player ID, weapon chain/object ID, exact held item, native weapon class, active handler, and routine. Only an observed same-identity `[0,6,2,0]` to `[0,6,2,1]` transition with object state 3 confirms a recent matching request. Missing reads, owner/weapon changes, long gaps, and mere fire entry do not confirm. Host sampling can miss complete rapid-fire cycles and will undercount; this is not a complete bullet counter or proof of an impact.

The later HUNK/Base round `b96ab13521f44b0ba3753d1bd5afbe7b` measured
Killer7 item42/class6 with handler `31cc60`. The original two-handler reader
therefore rejected it even after allowing the owned native-hook vtable.
Handler admission is now class-specific: this additional handler admits only
class6, retaining magnum aim partitioning. It does not authorize other
handguns merely because they share that handler.

For Killer7, the exact pinned ELF calls trace/emission at `31dfe4`, writes
weapon object state3 at `31e000`, then writes fire step1 at `31e03c`.
The optional asset regression executes this actual fire00 routine with
external callees stubbed and checks that order, plus the two real dispatch
tables. It proves native invocation and state ordering, not an impact or
live fire rate. The binary is read from `RE4_MAIN_ELF`; no game bytes are
included in the tests. Spark proof archive:
`gbox-data/mercs/analysis/re4-killer7-discharge-native-20261113.json`.
Follow-up validation: 119 behavior/aim regressions passed locally, with the
asset test skipped there. The native asset test then passed separately on
Spark using the exact `c8e8f22f` ELF and isolated Unicorn 2.1.4. Its log is
`gbox-data/mercs/analysis/re4-killer7-native-proof-test-20261113.txt`.

## Behavior and validation

The aim plan uses the live sphere rather than generic chest/body offsets and keeps exact held-item and native-pose metadata for the shared aim book. A Garrador shot requires the finite observed native laser to reach that sphere and name that enemy. Scatter offsets are suppressed for this precision target. When its back is inaccessible or the sphere cannot be read, the bot prefers another valid nearby enemy; otherwise it makes a bounded rear-position attempt through the native mesh and Walker collision guard. A missing route never authorizes direct movement through the boss. The prior gun-facing request is cleared during repositioning.

Discharge confirmation precedes ledger resolution. Learning is refused while owned explosives or throw/ring actions are active and for six seconds after ring, throw, or mine-detonation events. Event timestamps are opaque IDs because existing producers mix wall and monotonic clocks. HP changes remain correlated outcomes, not certified gun impacts.

Validation: 96 tests passed across `test_re4_garrador_aim.py`, `test_re4_garrador_policy.py`, `test_re4_discharge_witness.py`, existing `test_re4_switch_aim_ram.py`, and `test_re4_boss.py`. Fixtures cover current animated geometry, disabled/deformed rigs, stale/reused identities, finite laser occlusion, no blind miss spray, alternate-target recursion, bounded verified routes, native completion matching, and explosive-learning exclusion. The active RE4 round was frozen at its intro during implementation; this batch has not yet demonstrated weakpoint contact or confirmed emissions in a newly activated live round.
