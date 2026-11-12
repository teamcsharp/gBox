# Correction: `set_id` is not a stable template id

Round 8 concluded that `set_id` identifies a room template, because rooms 50, 51, 52 and 53 in `map_cave01_00` share `198293` with identical bounds. **Testing that across
all 17 cave layouts refutes the general claim.**

## What the data says

```
distinct set_id values (>= 0x1000):  69
used by more than one layout:        36
  byte-identical placement sets:      6
  DIFFER between layouts:            30
```

**Thirty of thirty-six shared ids hold different placements in different layouts.** So `set_id` is **not** a globally stable template identity - it behaves as a grouping
id whose content is layout-specific.

And many ids carry a single placement in a single room (`264037`, `264038`, … each with one placement in room 1), which is not a room grouping at all.

## What still holds

**Within one layout, the grouping is real**: rooms 50-53 of `cave01_00` genuinely share `198293` with identical bounds and 21 placements each - one placement set
instantiated four times. That observation stands.

**What does not:** that the same id means the same room elsewhere. **Keying learned knowledge on `set_id` would be wrong**, and would silently transfer one layout's
walls and gates onto a different room in another layout.

## Why this is the right outcome to record

I was about to build the knowledge-store key on `set_id`. That would have been a plausible, tidy design built on a claim that **30 counter-examples falsify**. The
correction costs one round; the bug would have cost the bot's trust in its own map.

**`pso_knowledge` is already right to key on a geometry/digest fingerprint** rather than an id: the fingerprint is computed from the actual loaded geometry, so it
cannot confuse two rooms that merely share an id. This round's job is to say so with evidence, not to replace it.

## The map facts that survive

| fact | evidence |
|---|---|
| 17 cave layouts, 10-35 room numbers each | room inventory |
| 69 distinct `set_id` groupings in the caves | this analysis |
| a `set_id` group is consistent **within** a layout | rooms 50-53, identical bounds |
| a `set_id` group is **not** consistent **across** layouts | 30 of 36 differ |
| collision grids, 51 rooms, routing verified at 1.08x | round 2 |

**So the map model stands as: geometry is authoritative, ids are not.** That is what the codebase already assumed, and it is now tested rather than assumed.
