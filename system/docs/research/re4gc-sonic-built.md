
# SONIC IS IN THE GAME - RE4 GameCube Mercenaries

![Sonic as the Mercenaries player](evidence/sonic-in-re4gc-mercenaries.jpg)

A Mercenaries round as **Sonic**, castle stage, HUD, mission banner. He is on Leon's own rig (the game's skeleton and
animations), in the player slot, drawn by the game.

## The bug that hid him for five rounds

The swapped pack is **smaller** than the original on the disc:

```
em/pl00.drs   original 2,221,088   swapped 2,089,760
```

Writing it into the image in place leaves the original file's **tail** behind (131,328 bytes of the original body), and the
disc's file table still says the original size - so the game parses the original body out of that tail and draws Leon. Every
check I ran said the mod was installed (sha of the new pack matched, Dolphin booted the right image) and every check was
right; the game was reading past what I wrote.

**The fix is one line: pad the replacement to the original file's size with zeros.** The item table inside the new pack never
references the padding, so the pack is exact and nothing of the original survives:

```
swapped 2,089,760 -> padded to 2,221,088 (= disc size)
mod re4pad1458, launched, autoplay prepare {title re4, character Leon, stage Village}
-> a Mercenaries round with Sonic as the player
```

That is the same class of mistake as the arc writer's in-place patch on RE5: **a shorter replacement must not leave the old
bytes readable**, and a container that records a size must have that size honoured.

## What this opens

The RE4 GC pipeline works end to end now: `swap_packs` -> pad -> `build_mod` -> launch -> `autoplay prepare` with a queued
selection (`mercs_bot`'s new RE4 branch) -> a round. Swapping any character, and swapping the *enemies* (em10-em1c) the same
way, is the next step, and the padding rule applies to both.
## The enemy swap (zombies as Sonic): the missing piece is a role map

The player swap does not carry over to the ganados. `re4gc_enemies.retarget(rig, tmpl)` takes a rig dict with
`{joints, parent, roles, prims}` and maps it onto the ganado skeleton through `GANADO_ROLES`, and the source side needs a
`roles` map naming which joint plays hip / chest / neck / head / each upper arm, forearm, hand, thigh, shin and foot.

**Sonic's glTF has no anatomical names to build that from.** Measured: 66 nodes, and not one name contains hip, spine, chest,
neck, head, arm, hand, thigh, leg, foot, shoulder, elbow or knee - `characters.tree_roles` therefore returns nothing, and
`retarget` fails `KeyError: 'pos'` because the rig comes back empty.

Two routes, both concrete:

1. **Derive roles from joint positions.** The rig dict wants rest-pose world positions, so hip/head/limbs can be found
   geometrically: highest joint = head, its parent chain = neck/chest/spine, and the four limb chains split by X sign and
   distance from the spine. That is a small function and it is reusable for every unnamed rig in the collection.
2. **Go through Leon.** `sonic_on_leon.glb` already has Sonic on Leon's bones named `b<id>`, and Leon and the ganado are both
   RE4 GC skeletons - so a role map for **Leon's** bone ids (derivable the same geometric way, on a template whose ids are
   known) plus `retarget` onto the ganado template would fit Sonic to a ganado without touching his own joint names.

Route 2 is less work and reuses the rig that already exists; the geometric derivation in (1) is what supplies Leon's map.

The rest of the pipeline is unchanged and proven: swap into the enemy pack, **pad to the disc size** (the rule that made the
player visible), `build_mod`, launch, `autoplay prepare` with a queued selection, capture.