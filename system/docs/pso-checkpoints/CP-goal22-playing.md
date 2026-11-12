# Round 22: the bot is playing - and the fixes that got it there

## Two bugs that mattered, both found by playing

**1. `send` was waiting for a receipt the bot never needed.** `session_op` jobs succeed, but not inside `send`'s four-second window, so `send` returned
False and the loop treated every press as failed - the character stopped moving while the presses were being applied anyway. Fixed: **fire and forget**.
The queue preserves order, and a press only needs delivering.

Proof: `moved: 30.97 units` after four presses.

**2. The route to a switch was three legs of a longer path.** `press_switches` walked `route[1:4]`, so it stopped 70 units away and pressed A at nothing.
Fixed: walk the **whole** route, stopping early only within 8 units.

## Reading the live entity dump properly

The dump of the room the bot was in showed exactly what separates a usable door from a phantom:

```
 66.9  TObjDoorKey        state=1129705297  hp=0        <- phantom: garbage state AND no hit points
108.5  TObjDoorKey        state=224         hp=32987    <- real
175.3  TObjDoor           state=224         hp=32987    <- real
220.8  TObjDoor           state=0           hp=16256    <- real, closed
 75.2  TOCapsuleAncient01 state=garbage     hp=0        <- the capsule in the screenshot
```

**`hp > 0` is the reliable test for a door.** The phantom that sent the bot walking 92 units away had `hp == 0`; every real door carries tens of thousands.
The state field alone could not tell them apart, because it is garbage on non-door entities too (the player's own reads -1688555871).

Also learned: doors appear with **states beyond 0/2/224/240** in practice - `880`, `176` - so the filter was widened to what has actually been observed.

## The operator's rule, implemented

*"anytime they see an indicator for the switch, they need to press it."*

The indicator is a glow **around the character**, so the switch is often **at its feet** - and the code only pressed after walking to a chosen target. Now:

* **A is pressed every cycle while a door is within 40 units**, which costs nothing and catches the switch underfoot;
* **an enemy within 15 units takes priority**, because the log shows the bot being knocked around (distances jumping 79 → 101 → 71 → 118) while it walked at
  a door and pressed nothing. A room is not opened while being hit.

## Where it is now

```
20:40:06   pressed A near TObjDoor (state 224, 18 units)
20:40:20   switch TObjDoorKey state 224 at 25 units
player: (-151.9, 26.6, 139.2)  hp 27  floor 1
```

**It is playing, pressing doors and staying alive.** What it is not yet doing is **progressing reliably**: it still gets knocked around, and a key door
(state 224) needs a **key** the bot has not learned to find.

## Honest state

| item | state |
|---|---|
| input | **works** (fire-and-forget jobs) |
| moving | **works** - 30+ units per press series |
| pressing switches | **works** - presses within 40 units of any door |
| fighting | works, but ranged enemies knock it around |
| **finishing a room** | **not reliable** - key doors need a key |
| game | live, floor 1, hp 27, operator-owned |
