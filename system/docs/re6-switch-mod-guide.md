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

Built offline on 2026-11-09 and **never loaded by the game** (they are under
`C:\_tools\gBox\.scratch-merc-recovery\assets\re6\<build>\romfs` on the automation PC, each with a `receipt.json` that
lists every file's sha256 and says what a live frame must show):

| build | files | what it is |
|---|---|---|
| `re6sw_probe_albedo_solid` | 7 | native Leon; only the jacket albedo (USA body) is pure blue and only the vest albedo (Asia body) is orange. Proves the colour encoding and per-material targeting, and shows which body costume 1 is |
| `re6sw_sonic_leon_ycc` | 17 | the colour fix: the installed Sonic bodies unchanged, his atlas written as Y'CbCr into the one albedo his material samples |
| `re6sw_probe_sonic_luma` / `re6sw_probe_sonic_vtf_white` | 17 | controls: the same Sonic with a neutral colour block (must be greyscale), and with `pl_VTF` = 1 and white `_MVTF` on top (must look the same) |
| `re6sw_roster_mix_s15` / `_s27` / `_core_s1` | 45 | seeded mixed-franchise rosters, geometry only: one donor per character on the costume-1 bodies (Mario, Solid Snake or Lei Fang on Leon) |

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

1. `0x2B` albedo colour: explained offline, fix not live-verified. The format is BC3 with luma in the alpha block and
   (Cr, opacity, Cb) in the colour block; the old encoder put RGB there, hence teal and pink. `pl_VTF`/`_MVTF` are the
   cloth displacement curve and mask, not colour. Next step: run `re6sw_probe_albedo_solid`, then
   `re6sw_sonic_leon_ycc` (Leon, COSTUME 1, a gameplay frame).
3. Which body Mercenaries draws as costume 1 is not measured (Leon: most likely the Asia body). A build that covers one
   campaign body only can show a native human; the 2026-11-09 overlays cover both of Leon's.
4. A donor that does not rest in a T-pose (Snake, Mario HD, the DOA and PSO models: 77-135 degrees off on the arms) is
   turned into the native bind pose before binding (`bind_mode="pose"`). That path has never been loaded by the game.
2. The autobot's own menu walk needs the deployed code (`fast_start`, plain D-pad keys, save-aware stepping). Verify with
   `autoplay op=start` at the title and check `stats["fast_start"]` (segments, presses, seconds).
