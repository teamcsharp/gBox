# CP19 groundwork: the bot now earns EXP (Lv 1 / 0 pt -> Lv 3 / 365 pt)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: mastery (CP19 preparation)
Live: session `75cf966f35164149-4ec5d512e3484b02`, Forest 1 (floor `0x805D5FC0` = 1)

## Measured

Character panel before (round 178): `BQF Lv 1, Total EXP 0 pt, HP 40/40`.
Character panel after the entity-driven hunts (round 181): **`BQF Lv 3, Total EXP 365 pt, HP 54/54, TP 94/94`**.

So the character gained **two levels and 365 EXP** in the forest. That is the first time all night the game's own scoreboard
confirms the automation is playing rather than walking, and it is the number to use from now on.

## What made it work

- **Entity-based targeting.** The semantic profile's entity table (`0x8050D460`) names every scene object; `TObjEneBeast` entries are
  the Boomas, with `hp` u16 @ `0x32C` and `hp_max` @ `0x2B8` (the same offsets CP18 used for the Dragon). The hunt loop reads the
  nearest living enemy's position from RAM and walks at it.
- **Melee range was the bug.** The earlier loop struck at 15-25 units and did nothing; a saber's reach is a few units, so the
  Boomas were never in range. The Dragon died first because its hitbox is enormous - a large target hid a small-range problem.
- The chase uses the probe-and-turn controller (measure where "up" actually sends the character, turn until the bearing is inside
  25-30 degrees, stride), which survives the camera rotating with the character.

## Also found in Forest 1's entity table (for CP17)

88 entities, including `TObjDoor` x9 at concrete world positions and **`TObjDoorKey` x5** (`(-482.8, 2.7, 227.5)`,
`(277.0, 11.2, 7.4)`, `(-126.9, 22.9, 70.9)`, `(-95.0, 33.5, 213.9)`, `(6.6, 11.1, 362.4)`), plus `TLazerFenceSw` x4 and
`TObjLazerFenceNorm` x5. The key doors are the strongest candidates for room/area transitions that CP17 still needs, and they are
now addressable as walk targets rather than guesses.

## Needs

Nothing blocking: the hunt is repeatable, the EXP signal is real, and the same loop can be pointed at the key doors for CP17 and at
each arena for CP19. A single run that clears Forest 1's enemies, opens a key door and walks through it would settle CP17's accept.
