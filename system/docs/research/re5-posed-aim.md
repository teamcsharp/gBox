# RE5 live posed target aiming — 2026-11-13

The operator reported shots passing over a living enemy lying on the floor.
The previous final aim controller used a standing chest 110 cm above the enemy
anchor and a standing hit-test capsule. The disabled `DOWNED_MOTIONS` guesses
could not safely fix this: `E_MOTION` at +0x8F8 is the low byte of a **16-bit**
motion ID, and different motion banks reuse those low values.

## Native layout and read-only evidence

Existing full exports under
`/home/ehm_eckx/gBox_alt/analysis/merc-full/re5-674c8828-20261113`
corroborate these EBFFDB22 offsets:

| Native field | Evidence |
| --- | --- |
| uModel +0x8C0 joint count, +0x8C8 joint array, stride 0xC0 | `00eccf90.json` traverses the current joint array |
| uModel +0x8D0 animation-ID-to-joint-index byte mapping | `00e14290.json` resolves a requested animation ID |
| Joint +0x50 world XYZ | `00e14290.json` copies the resolved joint translation into an attached world effect |
| Joint +0xA8 owning uModel | `00ece3c0.json` checks this owner before applying constraints |
| Actor +0x1B60 current action | `008037b0.json` destroys the current action; live RTTI resolves WaitSearch, Walk, Run, DmgFlash, RiseFaceDown and traversal actions |

The human animation IDs (spine 2, head 4, upper arms 6/11, thighs 16/20, knees 17/21)
were previously measured from native models in `mercs-enemy-aim-heights.md`.
Live current skeleton indices differ from bind-pose file order, so the reader
uses the native conversion table. It does not assume model bone indices.

At Unix time **1794571598.2396886**, session
`af3d25f1f3b34383-be7e51a4c58f4efd`, a living uEm10 (HP 260,
generation 41) had native action `cEm10ActRiseFaceDown`, full motion ID 1365:

- Anchor: `[-3631.7534, 1100.0, -13273.5234]`.
- Current spine: `[-3647.4006, 1118.4041, -13264.3154]`.
- Current head: `[-3678.7698, 1118.0641, -13248.7119]`.

The old aim point was **91.6 cm above the current spine**, and missed its
horizontal displacement too. The captured eight-joint record is retained in
`tests/fixtures/mercs_incidents/re5_downed_pose_20261113.json` and exercised by
a regression. Other read-only samples verified walking, running, leaning,
ladder and flash-reaction poses. No live memory was written for this research.

## Change and limits

The late selected-target read samples eight posed joints, then revalidates actor
generation/vtable, model, array/count, conversion table and current action.
Every joint must belong to that actor and have finite, nearby geometry. A
missing or torn pose replaces any old pose with `None`. The existing total
150 ms freshness budget includes these reads and still guards camera writes.
Creature layouts retain their class profiles; human IDs are not applied to dogs
or other unmeasured skeletons.

The final controller normally aims at the current spine, mapping existing head
and knee/stagger preferences onto the corresponding current joints. It follows
capsules between current knees/hips/shoulders plus the current head sphere. The proxy uses
the existing 36 cm torso/22 cm head radii; these are aiming estimates, **not
native collision-volume or damage proof**. A finite observed ray must reach
that posed geometry. Camera correction alone never grants contact. The
standing point-blank shotgun shortcut cannot override an available posed body;
the existing measured spread cone remains. Learned movement lead and camera
compensation are retained without restoring a standing body-height point.

`target_feedback_pose` records source, native action, current aim point and
height above the anchor for per-round analysis. This change does not label
commands as bullets or infer learning outcomes from camera writes.

## Native pitch authority follow-up

Round `7bceb6173a6e480f81fa08ca20908eec` retained a living prone uEm14 with
spine Y 41.51 cm while the laser passed Y 175-179 cm. Recorded yaw was nearly
aligned, but pitch error remained about -28 degrees and QFPS pitch repeatedly
returned to -0.0011226 despite accepted camera writes. The detailed evidence is
on Spark at `gbox-data/analysis/merc-tuning-20261113/re5-7bce-defense-window.json`.

The pinned RE5 ELF SHA-256
`674c88288eda98b8974e4185853d0b7c2f3fe6b623c823124326d14834856f5c`
proves a second pitch owner. Runtime RVA `249518..249578` checks QFPS+195.
When set, it copies **-player+3A48** into QFPS+1B0 every native update; the
alternate input flags at sPad+8D0C or configuration+A74 select player+3F60.
The normal persistent input is **player+3A4C**. RVA `79BA64..79BA7C` integrates
that input, and `79CB80..79CBD8` clamps it and derives +3A48 with a native offset.
Thus immediate read-back of QFPS+1B0 does not establish persistent correction.

The writer now rechecks the owned camera and normal mode, preserves the
observed derived offset, and writes only +3A4C in that mode. Both accumulator
and resulting derived pitch are bounded by the intersection of the native
limit pairs at the aim parameters +440..44C and the existing [-1,1] bound.
Unknown pointers, changed source/configuration, stale reads and changed
read-back refuse the correction; no mode flag is overwritten. Alternate mode
uses the separately verified controller input described below. The actual
later camera/ray still controls trigger admission.
`target_feedback_pitch_source` records the selected source, offset, bounds,
request, accepted input, failure reason and total writer time in milliseconds.

The optional `test_re5_native_pitch_source.py` asset regression runs on Spark
with `RE5_MAIN_ELF` set to the pinned ELF, using the production writer and the
actual native instructions in isolated Unicorn emulation. It reproduces a
camera-only -0.4 correction resetting to -0.0011226, then verifies that the
persistent-source correction produces -0.4 on the next native update while
preserving a +0.01 derived offset. It also exercises the alternate controller
integrator, native clamp, action-output copy and camera consumer.
The independent native proof is archived at
`gbox-data/mercs/analysis/re5-pitch-counterwriter-native-20261113.json`.
This establishes the native mechanism; improved live accuracy after deployment
still requires observation.

### Alternate controls observed in the fresh round

The read-only trace of round `464e7196555a45b2ab71221e15960efd` captured
991 samples, including 847 with stable player/camera identities. Of 454 aimed
samples, 450 selected the alternate branch: QFPS+195 and sPad+8D0C were both
1, configuration+A74 was 0. Normal-only input correction therefore refused
the mode actually in use. Evidence stays on Spark at
`gbox-data/mercs/analysis/re5-native-pitch-56729904a35049a6-1794585102.json`.

Native `7D91B0` integrates the persistent field at the player's owned input
controller +350+4C8, or **controller+818**. `7D9830` loads that value;
`7D9984..7D99D0` normalizes and clamps it to [-1,1] and aim parameters +29C.
The action dispatcher copies that accumulator to **player+3F60**, for example
`7BD0EC..7BD0F0`, before the camera negates it. Player+3F5C is a different
animated output including sway. Writing +3F5C would not fix the camera source.

The alternate writer validates player+3EE8, the controller's exact vtable
`1C31460`, its player backlink at +48, embedded aim vtable `1C31420` at +350,
and local-control mode 0 at +34C. It writes only +818 within the native bound;
the player's copied output, camera pitch, animation output, sway and recoil
fields remain native-owned. Controller/configuration changes are rechecked
before and after mutation alongside the existing player generation, owned
camera and 150 ms sample deadline. A missing or unsupported controller refuses
the write instead of falling back to the camera field.

The pinned-ELF regression executes native `7D9830..7D99D4`, then the actual
action copy and camera update. Positive and negative corrections, plus the
.997 native clamp, survive three consecutive updates with neutral stick input.
This is isolated emulation, not measured live accuracy.
The first live trace measured only the read-only source helper (median .0122 ms,
maximum .0769 ms); those values are not the full writer's timing.

A second read-only trace of the next session `323a54165d0848cf` validated the
new controller guards in 104 aimed samples. All 104 copied player angles
matched controller+818; 90 camera samples matched its negation, while the old
camera writer was still running. The helper read cost was .0353 ms median and
.0686 ms maximum. This trace is
`gbox-data/mercs/analysis/re5-native-pitch-323a54165d0848cf-1794585722.json`.
The new writer was not activated or used for those live reads. Combined focused
regressions passed 212 tests locally, with the optional native test skipped;
the isolated Spark native-source suite passed all 51 tests.

Validation: `test_re5_switch_pose.py`, `test_re5_switch_aim.py` and
`test_re5_target_feedback.py` pass with the session audit Python, plugin
autoload disabled. Tests cover the captured grounded body, continuous aimed
fire on it, correction away from its old standing capsule, blocking geometry,
pose transitions, pointer reuse/model swaps, malformed joints and preserved
learned lead. Live effectiveness after deployment still needs observation.
