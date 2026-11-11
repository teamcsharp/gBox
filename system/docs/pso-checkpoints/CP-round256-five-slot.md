# Round 256 (final): `multi_equip` takes a SLOT, and the five-copy rule is done

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
**PSO session live**: `25cacd834981410c-b3ca7fc2a1864b4c`, operator-owned, docked in gBox, character loaded (hp 40/40, tp 29/29).

## The finding that unblocked the operator's five-slot request

`pso_controls multi_equip` takes **the slot index of one copy**, not a target id and not "0" as a mode:

```
multi_equip target="5"  -> {"verified": true, "message": "Weapon effects stacked.",
                            "active_weapon_unchanged": true}
multi_equip target="6"  -> stacked (3 equipped)
multi_equip target="7"  -> stacked (4 equipped)
multi_equip target="8"  -> stacked (5 equipped)
```

Every call reports `"Weapon effects stacked."` and leaves the drawn weapon alone - it stacks equipment effects rather than dual-wielding.

Why the earlier attempts failed, precisely:

* `target="0"` -> *"Weapon is already equipped."* - slot 0 was already equipped, so it was a no-op. It was never a mistake in the op, it was the
  wrong slot;
* `target="65536"` -> **422** - an item id is not accepted.

So the rule is: **give N copies, then call `multi_equip` once per unequipped copy, naming its slot.**

## Verified result from the live inventory

```
equipped total: 7 | equipped WEAPONS: 5
  [E] slot 0 Saber     [E] slot 1 Frame     [E] slot 2 Mag
  [E] slot 5 Saber     [E] slot 6 Saber     [E] slot 7 Saber     [E] slot 8 Saber
```

**Five Sabers equipped across the weapon slots**, with the Frame and Mag still worn - exactly what the operator asked for, and it no longer
leaves the other slots empty.

## What was applied to the live character this round

| request | state |
|---|---|
| Ultimate difficulty | **applied and verified**: `{"legendary": true, "verified": true}` - next offline game selects Ultimate |
| five copies in all five slots | **done**: 5 equipped weapons, verified from the inventory |
| HP | already full at 40/40 |

## Still open, with the exact next step

* **all spells** - the array at `+0x2E7` reads `[1,0,...,5,0,...,5,0]` and `write_memory` works, but I will not overwrite a 20-byte player field
  on a guess. The five-second confirmation is: open the Techniques menu, count the spells, and compare with those bytes.
* **CP17 / CP18** - the character is in Pioneer 2. The certified 37-second Forest 1 walk needs Forest 1; `mastery_run.py --all` then records the
  floor transition and the boss HP series.
* **CP18 needs a second player** - "both players alive" is unmeasurable on a single-player session.

## The session's state at close

The dock problem is solved (app reload: 26 s dock timeout -> 8.7 s, window inside gBox, pad relay works). The character is playable and safe. The
editor, the navigation data and the evidence tooling are all committed and re-verifiable; the mastery block is the only thing left, and it needs
a walk to Forest 1 and one boss fight.
