# Boss reach: the path is open, the damage is not landing

## What this round settled

**The progression path is solved.** `pso_mods op=bosses` names Episode 1's four bosses from the game's own data, and `op=boss_warp target=<id>` acts on it - the bot stood in the
Dragon's arena with `TBoss1Dragon hp 1300` and moved freely there, because the arena floor is flat (`y = 0.1`). **Four named warps cover the whole Episode 1 spine.**

**The combat still does not land**, and three attempts this round narrowed it rather than solved it:

| attempt | result |
|---|---|
| enlarge melee reach to 220 for a boss body | Dragon stayed at 1300 across 30 rounds |
| walk **into** the body with `walk_through` (reach 70) | Dragon stayed at 1300 across 26 rounds; distance *grew* 196 -> 399 |
| stack DARK FLOW via `multi_equip` | `multi_equip` needs a weapon slot ("Choose a weapon slot from the current inventory"); one extra `give` succeeded, the next three failed - so no stacking |

**The controller is the visible problem now**: heading error oscillates between **-65 and +174 degrees** round after round - it is not converging, it is swinging past the target.
That is a control-loop failure on my side, not the game refusing input: the same `send_input` path moves the character freely everywhere else.

**And the Dragon hits hard**: the bot's HP cycles 34 -> 10 -> 34 as the Scape Doll revives it, while dealing nothing.

## What would actually fix it

* **read the native hit range out of the decompilation** - the reason the operator asked for it. `TBoss1Dragon`'s damage check is a constant in the analysed `pso_v3.elf`, and
  guessing 220 then 70 from outside is exactly what has not worked;
* **or drive combat through the app's own engine** - `pso_coop_combat.py` (19 KB) exists and is built for this, but this build exposes no tool that runs it, which is why my
  hand-rolled swing is what has been tried.

## Honest objective position

| clause | state |
|---|---|
| decrypt / analysed | **done** - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| map analysed and internalised | **done** - sha-verified city REL -> 1497 triangles, 5626 walkable / 4959 safe, plus a learned-area index from the live map API |
| used for path-guiding | **done** - the 29-waypoint route and the warp-trigger cell `(361.2, 28.8)` both came from it |
| walk through the gate | **done** - `walk_through`, verified passing one for 211 units |
| fastest rate | **4.8-7.3x measured** (median 5.5x); `move_speed`, native autoplay-speed and EFB tuning all unavailable or harmful |
| **every level / boss reachable** | **done** - four named warps, Dragon arena verified |
| **defeat every enemy** | **not done** - hits do not land on the boss; the control loop oscillates and the true hit range is unknown |
| never stand around | **done where the ground is flat**; ledges are handled by the measuring unstick |
