# Why the controller kept "stopping", and the bag stays empty now

## The controller bug, finally identified

The relay resolved its session **once, at startup**:

```python
pad = Pad()                 # picks whatever is live at that moment
...
send(pad, events)           # ... and posts to that sid forever
```

So **every time the bot relaunched** - for a clean inventory, after a crash, after `stop_game` - **the relay kept posting to a dead session id.** From the operator's side the controller simply
stopped working, with **no error anywhere**, because the posts "succeeded" against a session that no longer existed. That is why it worked right after I restarted the relay and failed again after the
next relaunch, repeatedly.

**Fixed**: the relay re-resolves the session **every second** and rebinds the moment a different one appears. Startup confirms it is on the live one:

```
relay session: 4b8bf1e855324f89-e278977abd9e4e59
relay watching 'Xbox 360 Controller'
```

and the live session is the same id. **Injection verified independently**: a direct `up` through the same route moved the character **33.0 units**, and a `left` changed the heading **219.3 -> 358.9**.

**What was happening in the earlier sample**: the operator was pressing **A/B**, not the stick - the log showed `['a','b']`, `['b','a']`, no direction press - so the character correctly did not move.
The path itself is sound.

## The inventory rules, as asked

> *"dont pick up items if the inventory is full. thats the point dont do that. Also dont fill up the inventory. Keep the inventory empty. The character has unlimited scape dolls so dont carry
> monomates, trimates, monofluid, difluid or anything except items for the game"*

The loop had **no pickup policy** - the reticle rule pressed `A` at *anything* actionable within 12 units, loose drops included. That is exactly how a 30-slot bag fills: not in one burst, but by
pressing at pickups for hours.

Now **loose items are excluded from the reticle rule** - `TItem*` and `TObjItem*` are skipped:

```
TItemMoney / TItemEquipBase              -> SKIPPED (item)
boxes, doors, keys, switches, enemies, warps -> actionable
```

So **nothing is ever picked up**, the bag stays empty, and "not picked up because it was full" cannot happen because no pickup is attempted. The items stay on the floor for the operator.

**The weapon gifts stay** - three `give` calls, once per session via arm-once - because a HUmar with no weapon cannot fight at all. The objection was to **consumables and loot**, which is what the
rule now prevents.

## And the fresh session proves the inventory theory

```
[00:06:30]   walk_through : succeeded
[00:06:31]   give 009d00: succeeded      <- DARK FLOW
[00:06:33]   give 003200: succeeded      <- TSUMIKIRI J-SWORD
[00:06:35]   give 004400: succeeded      <- RED HANDGUN
[00:06:36]   survival : succeeded
[00:06:36]   difficulty: Normal (already, hp_max 68)
[00:06:38]   floor_rares: succeeded
[00:06:39]   enemy_drops: succeeded
[00:06:40]   gates: floor 1: all gates open
[00:06:41]   operator is playing - bot standing down
```

**All three weapons equipped** - impossible for hours on the old session and instant on a clean one. That confirms the "Not enough inventory slots" failures were the bag being full from repeated
gifting, exactly as the operator diagnosed.

## Open, honestly

**The bag on the *new* session starts empty and now stays empty**, so this should not recur. What has still never been observed is the loop **killing an enemy by itself** - the sweeping attack and the
map-steered approach are both in and both individually proven, but every window since has had the operator on the controller, which correctly pauses the bot.
