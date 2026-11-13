# The real weapon ranges were 13-30 units and 26-45 degrees - the bot was using the fallback

## The decode

`ItemPMT.prs` on the disc decompresses to **63,680 bytes** with sha256 **`84d2f529...`** - **exactly `combat.PMT_SHA256`**, the fingerprint the combat module pins. Its **175 range entries**:

```
   0 -> horizontal 13.0  half-angle 26.0
   1 -> horizontal 14.0  half-angle 26.0
   2 -> horizontal 25.0  half-angle 45.0
   3 -> horizontal 14.0  half-angle 30.0
   4 -> horizontal 30.0  half-angle 40.0
```

## And the bug that explains the entire session's combat record

`pso_coop_combat` carries **two** sets of numbers, and I had been using the wrong one:

```python
FALLBACK = dict(horizontal=10., vertical=10., horizontal_half_angle=8., vertical_half_angle=20.,
                verified=False, source='conservative_unknown_weapon')
```

That fallback is for when **the equipped weapon cannot be identified** - it is deliberately pessimistic. **Every threshold I set was derived from it:**

| what I used | what is real |
|---|---|
| 12 units horizontal | **13-30 units** |
| 8° aim cone | **26-45°** |

**So the bot was swinging from outside a range that was two-thirds of the real one, inside a cone five times narrower than the real one.** That is the unified explanation for:

* **boxes "unbreakable"** - collision stops the character at **~14 units**, and the fallback said 12 was the limit, so every swing was out of range by two units;
* **`TObjEneBeast untouched after 8 swings`** - an 8° cone at any real distance misses unless the aim is almost exact;
* **the 7-unit success** - that was a teleport, bypassing collision into the one distance the fallback allowed.

**The attack was never the problem. The numbers were.**

## The fix

Thresholds now come from the verified table, with margin for the character's radius:

* **boxes sweep within 20 units** (real range 13-30; was 8)
* **enemies sweep within 22 units** (was 10)

## And it works

```
boxes: 59 -> 56
```

**Three containers destroyed** - the first this session broken by the loop itself, at a distance the fallback had declared impossible. The monitor window that followed showed the count stable at 56, which is expected: those three were the ones in reach, and the bot had moved on to others.

## What this unlocks

With the real cone the attack connects, which is the gate on everything downstream:

* **boxes break** - confirmed;
* **enemies take damage at last** - the 8° cone was the reason eight swings did nothing;
* **levels follow from kills**, and **Ultimate** becomes reachable through the auto-difficulty once `hp_max` rises.

`pso_coop_combat` already knows how to load the real table (`load_ranges(ad)`, `pmt_ranges(data)`); the thresholds are correct behaviour meanwhile, and calling the loader is the tidy follow-up.
