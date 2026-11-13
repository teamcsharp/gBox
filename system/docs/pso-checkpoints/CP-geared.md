# The best weapons are in, the character is immortal, and Ultimate is really set

## What `pso_mods` turned out to be

I had been treating gear as unavailable - `pso_item_search` returns 404 and `pso_inventory` said *"inventory not found (equip a weapon first)"*. The actual machinery was
`pso_mods`, whose own input model documents everything needed:

```
op:     give | stat | floor_clear | equip_any | crit_always | key_bypass | move_speed | rare_drops | meseta | item_set
code:   give: item code hex (e.g. 000105 = DB's Saber) or name
equip:  give: also equip the first created item
name:   stat: atp | mst | evp | hp | dfp | ata | lck
factor: move_speed: the player moves N times faster (1 = off)
```

and `pso_loadout op=plan` resolved the class's best weapon **from the disc's own item database** rather than from a guess:

```
HUmar, preset=atp, measured ATP ranking:
  DARK FLOW            009d00   ATP 756-900   11 stars
  TSUMIKIRI J-SWORD    003200   ATP 700-756 (+50 grind -> 856)
  ... eight more, with codes
```

## What was done

```
give DARK FLOW (equip)          -> {"created": 1, "equipped": true, "ids": [15728640], "verified": true}
give TSUMIKIRI J-SWORD (equip)  -> {"created": 1, "equipped": true, "ids": [15728641], "verified": true}
survival                        -> {"permanent_scape": true, "verified": true,
                                    "note": "Virtual Scape Doll: native revival on death, no inventory slot required."}
```

and the character's sheet now reads **HP 8 / 1234** where it was **68 / 68** - the max-HP raise landed even though `stat hp` reported *"memory write not confirmed by
read-back"*, and `stat atp`/`ata`/`evp` were refused with *"This value cannot be represented with the current equipment and level"*, which is the game's own bound rather
than a failure of the call.

**So the operator's requirement is met in the way the game allows**: the two strongest HUmar weapons are equipped and verified, and the character **revives natively on
death** - a permanent virtual Scape Doll - which is what makes an endless cycle survivable at level 5.

Entering the field again found **no enemies left in the room**: it had cleared them.

## Ultimate, actually applied this time

* the sidebar selection had **never reached anything**: `pso-launch-config.json` did not exist, so the file `pso_coop` reads was missing;
* the difficulty global **`0x805D5550` read 0 = Normal**.

Both set and verified: the config written in the shape `pso_launch_config.normalize()` returns (`episode 1`, `difficulty ultimate`, `difficulty_index 3`), and the global
written **0 -> 3**, holding across four samples two seconds apart.

**The honest limit**: PSO offers Ultimate at **level 80**; BQF is **level 5**. The flag is set, but whether the game spawns Ultimate content for a level-5 character is a
separate question - and if it does, 1234 HP with a Scape Doll is a very different proposition than the 68 HP it started with.

## The typing bug that exited the game

```
Dolphin.ini [Interface] BackgroundInput = True   ->   False
```

Dolphin was taking keyboard input **while its window was unfocused**, so typing to me went into the game. Now the keyboard only drives the game when its window is focused.
**The bot is unaffected**: its input is gBox's virtual pad, an XInput device, which is focus-independent - as is the operator's controller relay.

## Still open

* **`autoplay_speed`** in `pso_mods` advertises the exact thing asked for - **choices `[1, 2, 4, 8, 10]`** - but reports `available: false, known: false`, so the native
  10x autoplay path needs a patch that this build does not carry. Fast-forward remains the working route at 5.5x median / 7.3x peak.
* **`move_speed` with `factor`** ("the player moves N times faster") is documented and untried - that would speed up traversal itself, not the emulation, and is the next
  honest lever for "fastest rate".
* the app's **UI still reacts to keystrokes** in places (`index.html:2337`, the settings panel's restart control).
