
# SONIC AS THE ENEMIES - RE4 GameCube Mercenaries

![Leon grabbed by a Sonic, a second Sonic behind](evidence/sonic-zombies-in-re4gc.jpg)

The player is **Leon** (the queued character was honoured this time) and the ganados are **Sonic** - one grappling him, another
standing behind in the same shot. HUD reads "3 in a row", the round clock is running, so this is live Mercenaries gameplay.

![the grapple up close](evidence/sonic-zombie-grapple.jpg)

Same round a moment earlier: blue quills, orange arm, white glove and the SHAKE OFF prompt.

## What made it work

1. **All 31 ganado packs** (`GANADO_FILES`) carry Sonic, each fitted to its own disc slot. The per-pack search that does it:
   collapse the pack's spare bodies, then keep only Sonic's biggest primitive, then shrink textures. Result: 31 of 31 fit.
   Three shapes were needed -
   ```
   collapse + all primitives + tex 64      em10, em12, em13, em15, em16, em17, em1b, em1c
   keep only the biggest primitive, tex 64  em11, em19, em1a, em1d..em1f, em20, em46, em4c, em4d, em4f, em50, em56,
                                            em5c, em5d, em5f, em60, em66, em6c, em6d, em6f, em70
   collapse + tex 16                        em14
   ```
2. **Roles by geometry** - Sonic's glTF has no anatomical names, so `gbox.rig_roles` finds the limb pairs from the rest pose
   and the retargeter fits them onto each ganado skeleton.
3. **Pad every replacement to the disc size** - a shorter file written in place leaves the original's tail readable, and the
   game then draws the original (this is what hid Sonic for five rounds on the player swap).
4. **The mod must carry the enemy packs** - `char_swap.build_mod` globbed only `pl*.drs`, so enemy mods were silently empty.

## Reproduce

```
python gc_fit_everything.py      # fits Sonic into all 31 packs (skips ones already done)
python gc_zombies_play.py        # builds the mod, launches, autoplay start {title re4, character Leon}, captures
```