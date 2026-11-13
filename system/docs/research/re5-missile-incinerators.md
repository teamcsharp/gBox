# RE5 Missile Area incinerator exclusions — 2026-11-13

Round `560e1d847094444d925a5aaa63abb70f` died by entering the native
`incineratorC` volume. The flight records establish full-health loss at the
same boundary as the operator's reported corridor flames. Floor collision
alone does not identify this lethal scene trigger.

The round lasted about 1,498 seconds, finishing at 337 kills, 233,660 points
and 572.08 seconds remaining. At UTC epoch `1794570681.340` the player was
`(-2713.07, 470.00, -22676.37)` with 1,000 HP, holding run/forward. At
`1794570681.569` they were `(-2713.36, 470.00, -22750.08)` with zero HP.
The native volume starts at z `-22743.439453125`; the fatal sample is 6.64 cm
inside it, and the preceding sample is outside. The recorded decision was
walking around blocked floor toward an enemy about nine metres away, not a
mine retreat. No nearby enemy was attributed to the fatal damage.

The preceding traversal prompt (label 9) was pressed at `1794570672.508`
from `(-2785.32,900.00,-19550.64)`. The player then reached the y=470 corridor,
travelled south at about 430 cm/s and retained heading -pi despite intermittent
right-turn commands. This is evidence of ineffective steering on that route;
the flight alone does not prove the conveyor's exact force or control rules.

## Source and geometry

The operator-owned `.scratch-merc-recovery/stage/inputs/s405.arc` is
99,443,101 bytes, SHA-256
`2466a7a73a792c7e43e8825a3f0d0a4b01ba3a8c56e8219aff32ab516ddb319b`.
Each `stage\s405\soft\{merce,mercedc,merceex,vsm,vss}\s405_sce` resource
decompresses to the same 4,226-byte XFS object tree, SHA-256
`c5574a7a1227c4c47e241f5d19d97a6b69a53a0e8cacc031997b553cda2f4116`.
The tree version is 16, kind 11. Its property descriptors and value encoding
match the existing kind-4 layout reader; the source verification test changes
only that admission tag in a private byte copy and requires complete parsing.
No archive is modified or included in Git.

All three named shapes have `mBootType=3`, `mSceNo=99999`, `mDetectAttr=16`
and `Box.mHeight=100`. The meaning of scene ID 99999 is not independently
claimed; it is recorded as source evidence. Bounds below are centimetres in
the observed native world frame, x/y/z:

| Shape | x low..high | y low..high | z low..high |
|---|---|---|---|
| incineratorA | -1220.184..-458.797 | 60..160 | -13689.041..-12664.557 |
| incineratorB | -6996.508..-6487.573 | 49.234..149.234 | -22339.643..-21639.301 |
| incineratorC | -3017.599..-2421.919 | 461.107..561.107 | -23308.725..-22743.439 |

The code retains full precision. A/B's north edges have less than four
centimetres of skew; their conservative bounding boxes include that strip.
C is rectangular, and its exact native boundary matches the fatal crossing.
Only native geometry signature `1350-1664-ff6314937b448650` enables this
catalogue. A requested stage name, different geometry or missing mesh does
not enable a stale coordinate set.

## Routing contract

`re5_stage_hazards.blocked_segment` checks complete 3D segments against these
prisms, with a 100 cm horizontal route clearance and 50 cm vertical clearance.
The margins are deliberate navigation padding, not measurements of flame
radius. They leave unrelated storeys clear. `blocked_path` also checks action
links' approach and landing legs. The catalogue stays excluded because no
live off-state has been verified; it does not claim to decode current flame
activity.

Use the check on proposed routes and again after all movement rewrites,
including mine escapes, room-map detours and wall recovery. A final guard
must not turn a blocked direction into an unvalidated side step. The
`departing=True` option permits short movement out of an inflated clearance
margin only while a separating horizontal axis moves farther from the real
volume. It never permits a route through the native volume to reach the
other side. A learned walked cell cannot erase these exclusions.

`route(mesh,start,goal,...)` first preserves a safe native route. Otherwise it
excludes hazard-crossing transitions and reuses the mesh's explicit action
links; if a smoothed segment still crosses a volume, it searches directed
shared floor portals and triangle interiors. The returned fallback legs must
all have native floor support and pass the 3D hazard check. It can choose a
real alternate corridor; if the full supported corridor is lethal, it returns
no route. It does not create a bridge or turn a jump into an ordinary walk.

The old `_hazard_hit` path reacts after damage, only when no close enemy is
attributed, and stores a routing cost. That mechanism cannot prevent a first
1000-to-zero incinerator crossing. It remains separate from the measured
hard exclusions.

Validation: **25 tests passed** in `tests/test_re5_stage_hazards.py`, including
the operator's source archive. The suite replays the observed fatal
segment, cross-volume paths with both endpoints outside, action-link
landings, safe departure, other floors, invalid coordinates and exact
identity admission. An optional test reads the operator's archive (or
`GBOX_RE5_S405_ARC`) and verifies the bounds in all five mode resources.
The native scene source and recorded death are verified; successful live
avoidance after integration remains to be observed.
