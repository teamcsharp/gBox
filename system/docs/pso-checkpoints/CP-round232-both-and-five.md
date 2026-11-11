# Round 232: both-players boss observation, and the five-slot equip sequence

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (fourth round without a session), so both are tooling.

## `boss_both.py` - CP18 without the co-op blind spot

Last round's caveat was that "both players alive" was unmeasured because the observer watched player slot 0 only. This one:

* enumerates **every `TObjPlayer`** in the entity table each sample;
* writes one row per second carrying the boss's HP **and** each player's HP (pointer, hp, hpmax, player count);
* when the boss's HP reaches 0 it logs, at that instant, how many players have hp > 0 and prints an explicit verdict:

```
accept condition 'both players alive': MET / NOT MET (single player or a death)
```

So the series can no longer satisfy half the contract while the other half goes unmeasured - it either contains two living players at the
moment the boss reaches 0, or it says why not.

## `five_slots.py` - the operator's five-copy rule, verified

Requirement: when the equipped weapon is replaced, it must appear in **all five weapon slots**, and the old sabres must not remain in the
others.

The GameCube plane has the pieces, confirmed in `pso_gc_live.py`:

* `give(code, count)` - count up to **20**, creating real items through the game's own create-item routine;
* `multi_equip(target, on)` - verified earlier to stack the weapon's effects;
* `list` - the live inventory in menu order, so the equipped weapon's **code** is read rather than assumed.

Sequence: `list` -> take the equipped weapon's code (or `--code`) -> `give count=5` -> `multi_equip target=0` -> `list` again and count how
many copies of that code are equipped. It only claims success at **five or more equipped copies**, and prints the slots and item ids it
found. Dry run by default.

This is also the missing half of the randomizer: `randomized` gives **one** item per category, so without this step a swap leaves four old
weapons in place. Pairing them is: `randomized` swaps, then `five_slots.py --apply` fills the slots with the new code.

## State

No game running. Everything physical for the mastery block is staged:

* CP17: 9 certified-clear legs, 999 units, 37 s;
* CP18: `boss_both.py` captures the exact accept condition;
* CP19: needs both of the above plus `apply_master.py` for the build;
* the operator's requests: five-slot equipping (`five_slots.py`), all spells (`tech_finder.py` + the write channel), Ultimate
  (`apply_master.py ultimate`).

## Files

* `boss_both.py` - boss + all players HP series with the explicit co-op verdict
* `five_slots.py` - five-copy weapon equipping with inventory verification
