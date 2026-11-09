# RE6 Switch mods: operator guide (build, install, verify)

This is the manual procedure for the RE6 Switch model-replacement work, so it can be driven from the gBox UI or a shell
without the automation node. Everything here is measured on lilspark (Eden, title `01002A000CD48000`, gBox game
`115f9cdbba115432`).

## 0. Recovery when the game dies on every stage load

Symptom: the title and menus work, then any stage (Mercenaries or Campaign) goes black and the session ends — also with a
vanilla launch and no overlay selected. Cause: orphaned Eden/Vulkan processes and/or a save left half-written (a
scripted menu drive pressed A through a "Now saving…" dialog). Fix, on the Spark:

```bash
SAVE=~/gBox/system/gbox-data/runtime-linux-aarch64/eden-linux/data/eden/nand/user/save/0000000000000000/01002A000CD48000
mv "$SAVE" "$SAVE.bak-$(date +%s)" 2>/dev/null || true   # fresh save; the title's unlock-on-load reopens the main menu
pkill -f eden 2>/dev/null || true
pkill -f gbox 2>/dev/null || true
sleep 2
sudo systemctl start gbox.service
```

Then deploy the current main once: `~/bin/deploy_main.sh --deploy`.

## 1. The builds

| build | files | what it is |
|---|---|---|
| `re6sw_sonic_leon_keep_plain` | 30 | **stable live build**: Sonic mesh on every Leon costume, native bind pose kept, native (Leon) textures — the model is right, colours are Leon's |
| `re6sw_sonic_leon_keep` | 37 | same mesh + the donor atlas written into Leon's `0x2B` albedos — colours come out teal/pink (the `0x2B` colour path is not solved yet) |
| `re6sw_smash_cast` | 255 | **51-slot roster**: every RE6 character × costume body replaced by a different Smash fighter (geometry only), 204 head/hand parts blanked |
| `re6sw_probe_red` / `re6sw_probe_quad` | 12 | calibration probes: one costume, all albedos a solid colour / four quadrants (red renders exactly red; the quad probe is for the UV question) |

The camera-facing character only appears in **gameplay**; the Mercenaries/Campaign lobbies draw a separate menu model and
will always show the native character.

## 2. Install and select (UI)

In the gBox app on the spark host: **Mods → RE6 Switch → Builds**. Pick the build, press *Select* (only one load entry
may be enabled; gBox disables the others). The load directory is
`…/eden-linux/data/eden/load/01002A000CD48000`, entries are symlinks into `~/gBox_alt/gbox-cache/mods/115f9cdbba115432/<build>/romfs`.

## 3. Install and select (API)

```
POST /api/artifacts?name=<rel path>            (raw body; one per file) -> {"sha256": …}
POST /api/jobs  {"tool":"switch_mods","require_worker":"lilspark",
                 "input":{"op":"write","game_id":"115f9cdbba115432","build":"<name>",
                          "changes":{"romfs/<rel>":{"artifact":"<sha>"}, …}}}
POST /api/jobs  {"tool":"switch_mods","require_worker":"lilspark",
                 "input":{"op":"select","game_id":"115f9cdbba115432","build":"<name>"}}
POST /api/games/115f9cdbba115432/launch?node=lilspark&mod=<name>
```

`C:\_tools\gBox\.tmp\install_switch_build.py <build> --launch` does all four from the automation node.

## 4. Getting to a round by hand (fast route)

From the title: A (load notice) → A (autosave) → A (intro plays; it returns to the title) → A (main menu) →
A (PLAY GAME) → **down ×3** → A (EXTRA CONTENT) → **down ×2** → A (THE MERCENARIES NO MERCY) → A (SOLO) → A (stage) →
A (character) → round. Use the plain `down`, not aliases; the menus wrap at the edges. **Never press A while "Now
saving…" is on screen.**

## 5. What a correct result looks like

- `keep_plain`: Sonic's silhouette and quills in the player's position, moving with the character; colours are Leon's
  (dark).
- `keep`: same shape, atlas colours applied but tinted (currently teal quills / pink gloves) — the known open issue.
- `smash_cast`: whichever character/costume the round draws shows its assigned Smash fighter.

## 6. Known open issues

1. `0x2B` albedo colour: the native second half is a constant block in every tile, so the colour is not per-tile; `pl_VTF`
   (format `0x0E`, 128x4) reads as a float ramp and is the most likely colour multiplier. Next probe: neutralise
   `pl_VTF`/`MVTF` and see if the atlas colours show through.
2. The autobot's own menu walk needs the deployed code (`fast_start`, plain D-pad keys, save-aware stepping). Verify with
   `autoplay op=start` at the title and check `stats["fast_start"]` (segments, presses, seconds).
