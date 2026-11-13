# The aggro switch: mechanism not found yet, and what it would take

## What was tried, and what it ruled out

The operator's idea is a clickable gBox switch that makes enemies in a room stop noticing the character. That needs a **field to flip**, so the search went in three steps:

**1. The entity struct, calm vs hot.** Put the character next to an enemy so it notices, then dumped its struct repeatedly. Everything that differed from the calm sample was a position or a counter:

```
+0x38: 4361c6c9 -> 43668bfa   (position x, 11 distinct values)
+0x3C: 41b8534d -> 41b856da   (position y)
+0x40: 439f4803 -> 439d7627   (position z)
+0x60: 00005a8d -> 00005a8e   (a counter, +1 per tick)
```

**No state word flips when the enemy aggros.** The struct is: three position triples (`+0x38`, `+0x44`, `+0x50`), pointer-shaped words at `+0x00`, `+0x08`, `+0x10`, `+0x18`, `+0x24`, `+0x34`, one counter at `+0x60`.

**2. The linked structs**, followed from those pointers:

* `+0x10` -> `0x80DAA3C0`: a block of pointers, no small values;
* `+0x24` -> `0x81423220`: **the enemy's name string** - `62 32 35 36 5f 72 65 62 74 30 31` = **`b256_rebt01`** - which is a genuinely useful find (a per-enemy identity), but not a state;
* `+0x34` -> `0x81423280`: first word **`0x7`**, the only small value attached to the enemy.

**3. The candidate, tested.** Watched `0x7` from a state where the enemy was **982 units away and idle**:

```
  0: dist 981.8 | state words ['0x7', '0x81423d50', '0x0', '0x0']
 15: dist 982.5 | state words ['0x7', '0x81423d50', '0x0', '0x0']
```

**Constant.** So `0x7` is not aggro either - it is a type/kind field, not a behaviour state.

## Honest conclusion

**The aggro state is not in the entity struct or its immediate children.** It is either in the AI controller for the enemy family (reached through the function pointer at `+0x00`, not through data pointers), or it is recomputed each frame from the distance and never stored - which would make a "de-aggro flag" impossible as a single write and would need the AI update patched instead.

**I did not ship the switch, because a switch with no verified field behind it is exactly the kind of thing that looks done and does nothing** - and this session already has three conclusions that had to be retracted for that reason.

**What it needs** is the Ghidra half of the objective: find `TObjEneBeast`'s update routine in the analysed `pso_v3.elf`, find the aggro test, and read the field it tests (or patch the branch). That is a focused, tractable piece of work on a binary that is already decompiled and queryable - and it is the right way to get the operator's switch rather than guessing at offsets.

## What did get delivered this round

```
[22:42:50]   difficulty: Normal (already, hp_max 68)
[22:47:11]   relocation freed it (311.4 units)
```

* **automatic difficulty**: Normal while `hp_max < 250`, Ultimate above - so the bot levels where it can actually kill and switches itself to Ultimate when it can survive (Ultimate beasts are 1556 HP, level 5 is 68);
* **the relocation reliably frees a wedged character** - 311.4 units this run;
* the **name string** `b256_rebt01` is a new handle on enemies: it identifies the species per entity, which is a better key than the shared base class (`TObjEneBeast`).
