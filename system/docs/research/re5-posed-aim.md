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

Validation: `test_re5_switch_pose.py`, `test_re5_switch_aim.py` and
`test_re5_target_feedback.py` pass with the session audit Python, plugin
autoload disabled. Tests cover the captured grounded body, continuous aimed
fire on it, correction away from its old standing capsule, blocking geometry,
pose transitions, pointer reuse/model swaps, malformed joints and preserved
learned lead. Live effectiveness after deployment still needs observation.
