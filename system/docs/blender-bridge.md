# Blender bridge

The Blender round trip: any collection character out to Blender with its armature, weights, textures and rig role
names; edited or brand-new characters back in as first-class donors every writer can build; attachments (hats, props,
weapons) carried into each game within its budget; and Live Link, which puts a saved edit into the running game.

Status: control-plane side, the bridge protocol and the import path are tested without Blender
(`tests/test_blender_roundtrip.py`, `tests/test_blender_addon_protocol.py`, `tests/test_blender_copy_paste.py`). The
add-on's `bpy` side (`clients/blender/gbox_addon.py`) is written against the Blender 3.6 / 4.x API and has not been run
in Blender on the build host.

## Operator workflow

The game's **Models** page keeps **Animations** beside the preview. The clip list
scrolls and filters independently, including in the embedded desktop page.

Right-click an image, a model preview, or an Assets library entry:

- **Copy image to clipboard** copies the displayed image/frame as PNG to the system
  clipboard. The desktop app supports this directly; a standalone browser needs a
  secure connection and clipboard permission.
- **Copy model to Blender** prepares the model for Blender's native **Ctrl+V**.
- For sprites/images, choose **Image plane** (textured mesh with transparency) or
  **Image empty** (reference image). Both pack the still image into the clipboard
  file and use the displayed sprite frame, rather than the whole sprite sheet.
- Select a sprite animation, then right-click its preview and choose **MP4 image
  plane** when that clip has an MP4 export. In Blender, paste in a 3D viewport and
  play the timeline. MP4 has an opaque background; it does not preserve sprite
  alpha. Movie media stays at a content-addressed path under the local worker's
  `data_dir/blender-media` because Blender cannot pack movie files. Keep that file
  with the saved project (and copy it when moving the project to another PC).

Blender paste runs only on the desktop's identified local worker. An offline or
unidentified local PC produces an error instead of copying to another attached
computer. No add-on is needed for these native Ctrl+V actions. Other asset types
retain the gBox asset clipboard action.

The worker's `blender_copy` tool additionally accepts `asset_url` (an authenticated
gBox asset file API path without a host or token), `image_b64` (current PNG frame),
and `paste_as`: `model`, `image_plane`, `image_empty`, or `movie_plane`. Still images
are limited to 16 megapixels; movie/media inputs to 64 MB. Library glTF copies
bundle companion buffers and textures before import. The three media modes are
verified by loading isolated native copybuffer files in Blender 4.0; this does
not exercise the separate Live Link add-on.

1. **Copy a character to Blender.** Any of:
   - In gBox, right-click a character (the pick whip / collection) > *Copy to Blender*: `POST
     /api/characters/{slug}/blender/copy` puts the round-trip GLB on the gBox clipboard; in Blender press
     **Ctrl+Shift+V** (gBox add-on). With `{"native": true}` it also queues `blender_copy`, so a plain **Ctrl+V** in any
     Blender viewport on that PC pastes it.
   - In Blender: sidebar > gBox > gBox Live Link > *Connect*, pick the character, *Pull into Blender*.
   - `characters op=blender character=<name>` (agents / MCP): the same GLB onto the gBox clipboard.

   Whichever way, the character lands in its own collection `gBox/<slug>`: armature with its skin weights, textures
   packed into the .blend, every role bone tagged `gbox_role` (hip, chest, neck, head, clavicles, upper / fore / hand,
   thigh / shin / foot), the armature tagged `gbox_slug` / `gbox_base` / `gbox_roles`, body meshes `gbox_part=body`,
   existing attachments `gbox_prop` / `gbox_bone`.
2. **Edit.** Reshape or repaint the body, change materials, scale the head bone in pose mode (sent as the head scale).
   **Add attachments:** model a hat / sword / glasses, parent it to a bone (Ctrl+P > Bone, or select it and use
   *Bind* in the gBox panel, or leave it in the collection: it binds to the nearest bone on send). Each attachment keeps
   its own material and texture.
3. **Send to gBox** (sidebar > gBox). The control plane (`characters op=add`, `gbox/blender_roundtrip.py`) decides:
   - **variant** - the skeleton is unchanged: a new collection entry with `variant_of` = the original, the original's rig
     roles, attachments recorded in `meta.props` as rigid parts bound to their bone (`node`, `bone`, `role`,
     `triangles`) and marked in the stored model (`gbox_prop` / `gbox_bone` extras), the original's targets inherited
     as "needs rebuild". *Update* (or a Live push) re-sends the same variant (`revision` + 1).
   - **derived** - bones were added / renamed / re-parented: a new character with `derived_from` = the original, roles
     from the bones that kept their `gbox_role`, the rest detected. (*Send back as variant* refuses this case: game
     skeletons can't change for a variant.)
   - **new** - a model made in Blender. With an armature, its rig is recognised from the bone names (Mixamo, Rigify
     `DEF-*`, VRoid / VRM `J_Bip_*` or the VRM humanoid extension, UE mannequin, 3ds Max biped, the Blender metarig),
     else from the joint tree's shape (`gbox/rig_detect.py`). Without an armature it is **auto-rigged** (an 18-joint
     humanoid placed from the mesh's own shape, T or A pose; rigid weights, left / right never mixed) unless *Auto-rig*
     is unticked. Objects parented to bones are attachments.

   Any of these with a `hip` role passes the cast build's donor gate (`cast_swap.retarget_check`): a first-class donor
   for every writer (`characters op=use`, `op=match`, `op=cast_swap`). The status box says which case it was, the
   rig, the attachments and anything missing.
4. **Use in game** once (pick the running session), or let Live find it: **Live (on save)** + Ctrl+S. Saves less than
   1.5 s apart coalesce into one push (`DEBOUNCE_S`); a save during a push queues one more push of the newest save. The
   panel shows the countdown, the stage (`building -> validating -> reloading -> live ✓`), the checks and the
   attachments report.

## Live Link (`live_link op=push`, `gbox/live_link.py`)

- Target: the session picked with *Use in game*; else the newest running session whose model belongs to the
  character's family (the character, its original, the original's other variants: the session's `live_mod` / `mod`
  against their built mods, or the character the pick whip put there). None running: the edit is stored ("stored").
- When a worker registers `pick_replace` (`gbox/pick_tool.py`, docs/live-inject.md), it runs first on the session's
  worker: `{session_id, pick, character, mode: "live", fallback: true, ...}`. The pick is the one that put the
  character there when recorded (session `live_pick` / `pick` / `last_pick`, learned profile `picks[slot]` /
  `last_pick`), else a slot-only pick (slot, game, backend, replaceable). Status `live` or `swapped` = done; a failed
  build there ends the push; `not_replaceable` / refused falls through to the paths below.
- SM64 / RE4 GC player: their dedicated path (SM64 RetroArch hot swap in RDRAM, else save state -> relaunch -> load).
- Every other writer: `characters op=use rebuild=true launch=false` for the slot, then `POST /api/sessions/{sid}/swap
  {mod, keep_state: true}` (session swap: same PC, same moment). A failed swap leaves the game on the previous model.

## Attachments in builds (`gbox/attachments.py`)

The shared rig loaders (`sm64_swap.load_rig` - SM64, OoT, PE1/2, FF7, SA2 / JGR / PSO through `ninja_swap`,
SmackDown! 2, No Mercy / WCW, Def Jam, Enter the Matrix, DOA++, MGS VR - and `doa2_weighted_retarget.load_rig` - DOA2,
007 Agent Under Fire) flag every marked node as a prop, whether or not the writer passes `meta.props`. The shared
retargets keep a prop rigid on ONE joint (its bone's) with weight 1, move it with that bone's fit, and keep it out of
the height / head-size fit. A prop's material is named `gbox_prop:<node>:<n>` in the fitted intermediate, so after a
Blender decimate `read_rigged` still knows its triangles. Every `characters` call reports
`result.attachments`: per prop the triangles loaded and kept and the state `kept` / `simplified` / `dropped`, measured
after the budget pass where the writer goes through `read_rigged`, else after the fit; a dropped prop is named in the
message. SM64 additionally reports when its texture budget flattened a prop's texture; RE4 GC reports props decimated
with the pack.

Limitation: variants stored before attachments were stamped into the model file are found only by writers that pass
`meta.props`; re-send them once from Blender.

## Routes and tools

| | |
|---|---|
| `GET /api/characters/{slug}/blender` | the round-trip GLB: textures embedded, scene / asset extras `gbox` {slug, name, base, variant_of, roles, props, source_game, revision}, joint extras `gbox_role`, mesh extras `gbox_part` / `gbox_prop` + `gbox_bone` |
| `POST /api/characters/{slug}/blender/copy` | `{native?: bool, worker?: str}` -> the GLB on the gBox clipboard (+ a `blender_copy` job with native) |
| `POST /api/characters/blender/import` | `{name, artifact \| b64 \| from_clipboard, base?, replace?, props?, rig_roles?, scale?, auto_rig=true, derived_ok=true}` -> a `characters op=add` job on the control plane; its `output.result`: `status`, `mode` (variant / derived / new), `entry`, `roles`, `rig`, `props`, `donor_ready` |
| `blender_copy character=<slug>` | Blender's own clipboard (copybuffer.blend) with the role / Live Link properties set |
| `characters op=add` | the import (`auto_rig`, `derived_ok`, `rig_roles`, `base`, `replace`, `props`, `scale`) |
| `live_link op=push` | `character`, `target?`, `game_id?`, `slot?`, `auto_target=true`, `method` auto / live / hotswap / relaunch |

## Headless bridge (UAP packages)

`open_in_blender {package_dir}` validates the UAP, converts it to glTF and runs:

```
blender --background --factory-startup --python clients/blender/gbox_bridge.py -- model.gltf scene.blend report.json unit_scale
```

The script imports the file (a UAP glTF or a round-trip GLB), scales root objects from game units to metres, tags
objects with `gbox_source` and, for a character, the Live Link properties above, saves `scene.blend` and reports
objects, vertex / bone / role-bone counts and actions; the control plane validates the counts against the UAP.
