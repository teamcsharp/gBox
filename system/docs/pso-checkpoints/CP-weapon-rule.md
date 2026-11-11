# Live session: the weapon rule, the rotation, and where the spells stand

Session `25cacd834981410c-b3ca7fc2a1864b4c` - operator-owned, docked, character live in Forest 1.

## The operator's new rule, implemented and holding

> "When you give me a new weapon, put it in all of the weapon slots, replacing the ones I have equipped."

`weapon_rule.py` enforces it, and the measured result was:

```
target weapon SWORD (007100) - inventory {'000100': 6, '00a905': 4, '007100': 1}
  give 4 more: {"created": 4, "verified": true}
  equip slot 18: Weapon effects stacked.
  equip slot 19: Weapon effects stacked.
  equip slot 20: Weapon effects stacked.
  equip slot 21: Weapon effects stacked.
  result: 5 equipped [(14,'SWORD'), (18,'SWORD'), (19,'SWORD'), (20,'SWORD'), (21,'SWORD')]
  single family True
```

It runs as a **loop every 120 s**, so after each rotation the newest weapon fills all five slots and every other equipped weapon is removed
(`multi_equip on=false` calls the game's own unequip routine - verified: "Weapon effects removed.").

## Two mechanics that had to be discovered

* **`multi_equip` takes the SLOT of a copy**, not an item id (422) and not `"0"` (which is just slot 0 and reports "already equipped"). One call
  per copy.
* **A given weapon can be unusable**: the AXE needs **ATP 800** and the character has **410**, which drops effective ATP to 210 and shows
  "ATP Needed: 800" in red. `equip_any on=true` (verified) removes that restriction, so rotation-given weapons always work.

## What is armed on the live character

| item | state |
|---|---|
| build rotation every 2 min | `{"on": true, "interval": 120, "categories": ["weapon","armor","shield","mag"], "verified": true}` |
| weapon rule (all slots, newest only) | loop running, last pass `single family True` |
| equip_any | `{"equip_any": true, "verified": true}` |
| survival (cannot die) | `{"permanent_scape": true, "verified": true}` |
| crit / always_hit | both `verified: true` |
| MST | raised 29 -> **999** (`verified: true`), so TP max is **732-999** |

## The spells: why they are grey and what remains

The technique menu shows **Foie, Zonde, Barta, Gifoie, Gizonde** (and Shifta/Deband/Jellen/Zalure/Ryuker earlier) - they are **known**, and grey
because **TP is 29** against a max of 732-999. MST 999 fixed the ceiling; the current TP must be refilled in-game (a fluid or the nurse) before
they light up.

Raising them to **maximum level** needs a write to the technique array (`+0x2E7` currently reads `[1,0,...,5,0,...,5,0]`), and **the job
channel is timing out on this session**:

```
poke hp=40  -> timeout
poke tp=999 -> timeout
```

Session RPCs still answer in milliseconds (that is how every change above landed), but `write_memory` / `poke` / `freeze_memory` are jobs, and
they hang while the game is busy. So HP, TP and technique levels cannot be set from here right now.

## Autoplay

`autoplay_speed` is **unsupported for GameCube** - the plane answers that speed controls require the dedicated PSO co-op autoplay session. The
bot can still drive the character through injected input (proven: an injected START opened the title menu), and `pso_input` yields whenever the
operator has been on the pad within 3 s.
