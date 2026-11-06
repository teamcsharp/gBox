
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
## Promoted into the repo: `gbox.re4gc_zombies`

The Sonic-zombies swap was a scratch script; it is now a module with a CLI, injectable collaborators and six tests:

```
python -m gbox.re4gc_zombies --iso <disc> --model <collection .glb> --out <dir> [--packs em10,em11]
```

* `derive_rig(model)` - roles from geometry (`gbox.rig_roles`), and it **refuses** a rig with fewer than ten roles rather than
  retargeting a partial map into a mangled enemy
* `attempts(counts)` - the fitting ladder as data: every primitive, then the biggest one, then small textures
* `swap_ganados(...)` - per pack: retarget, write glTF, pack to GLB, swap with the spare bodies collapsed, and **pad to the
  original disc size**; a pack that cannot fit reports its best size instead of vanishing
* `summary(report)` - one line per pack plus a count

Verified against the disc after the refactor:

```
em10: fits with keep=4 tex=64 (10340608 <= 10628000)
em11: fits with keep=1 tex=64 ( 6248608 <=  6260192)
2/2 packs fitted
```

Six tests cover the ladder order, the padding rule (a shorter rebuild is padded, and the original's tail cannot survive), the
"cannot fit" report, that spare bodies are always collapsed, and that a partial rig is refused. One numpy truth-value bug fell
out of the refactor (`p.get("pos") or []` on an array) and is fixed.
## In the app now: `characters op=use slot=enemies`

The swap is wired into the tool the sidebar and the lab already use, replacing the "enemy swaps need
`re4gc_enemies.Builder` run by hand" gap that the code itself used to report:

```
POST /api/jobs {"tool": "characters", "input": {"op": "use", "character": "sonic",
                                                "game_id": "78ab9efa2e310db4", "slot": "enemies"}}
-> mod re4_sonic_enemies, status built
   31/31 packs fitted, none rejected
   em10 keep=4 tex=64, em11 keep=1 tex=64, em14 keep=1 tex=64, em19 keep=1 tex=64, em1a keep=1 tex=64, ...
```

The path (`characters.build_re4_enemies`): resolve the vanilla disc, resolve the collection model and its body roles (or derive
them by geometry when the entry has none), `re4gc_zombies.swap_ganados` over every ganado pack, then `filemods.build_image`
with an image named for the character and a marker carrying `slot: enemies`. It returns what fitted, what did not, and how each
pack was made to fit, so a partial result is visible rather than silent.