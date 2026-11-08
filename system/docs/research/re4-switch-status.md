# RE4 (Switch): what works, what does not, and what each thing needs

Written after the rounds that identified the player pack, proved the shape-transfer mechanism, and mapped the texture containers. The point
of this page is that the next attempt costs one boot instead of six: every claim here is either measured (with the round it was measured in)
or marked as unproven.

## The pipeline that works today

```
any extracted .glb  ->  gbox.glb_donor      (keeps the skeleton; picks a container with room for it)
                    ->  gbox.re4hd_affine   (per-band proportions, blend 0.0-1.0 or "auto")
                    ->  gbox.re4hd_edit     (in place, slot size kept)
                    ->  gbox.switch_mods    (LayeredFS build under the catalog game id)
                    ->  a drawn, coherent change in a live round
```

Entry points:

* `POST /api/decrypt-lab/replace` — one call for all four panel operations (preview with `write=false`).
* `python -m gbox.glb_donor <model.glb> <out.bin>` — any collection model becomes a donor.
* `system/tools/probes/fix_boot_state.py` — puts the title's save back to a menu so the next boot is clean.

## Measured facts

| claim | round | evidence |
|---|---|---|
| The camera's player mesh is **`pl08.udas`** | 112-113 | scaling that one pack distorts the player; every other halving left him stock |
| `pl08`'s visible surface is essentially **material 0** | 113 | vanishing materials 1..24 (23 of them) leaves the player unchanged |
| A **per-band affine** transfer is drawn | 100-104 | slab donor: the camera ends up inside the ballooned mesh; Sonic donor: big head, small body |
| Bone-only and global-surface transfers are **not** drawn usefully | 86-99 | invisible, and shards respectively |
| Strength must follow the target's band sizes | 100-106 | the same blend loads a player pack and hangs an enemy pack; `auto_blend` fixes it |
| A donor's skeleton survives only as far as the **container's weight table** allows | 103-104 | `em16` has 4 weight records, `pl04` has 256; Sonic kept 62 joints only with `pl04` |
| The pack's TPL is a **descriptor table only** | 116 | 9 descriptors in 608 bytes, zero `DDS ` magics, no payload slot |
| Texture id mapping is **local -> global -> archive** | 117 | materials use 0/2/3; the TPL's 8-byte entry carries the global id; `imagepackhd` is keyed by that |
| `imagepackhd` has **nothing below id 6** | 118 | 1,813 archives, ids 6 .. 0x4b000005 |
| A RomFS **file swap reaches the game** | 117 | surface replaced in `00000009.pack.fen`, stage ran |

## What does not work yet, and the one thing each needs

**The player's textures are unreachable by the routes tried.** Global ids 1, 2, 5 (his body) have no HD archive; supplying
`bio4/imagepack/<id>.pack.fen` from the overlay changed nothing (round 119). What is left:

* the **update NCA** — the loader asks for a patch RomFS (`PatchRomFS update lookup ... found_best=false` in the emulator log), and an update
  partition commonly carries the lower-resolution assets. Extract it and re-check whether `imagepack/` exists there;
* or **RAM**: read the texture address the frame's display list samples, which names the surface directly and cannot be wrong.

**"Remove clothes" as a material hide is dead** (material 0 is the whole visible surface). It is a texture edit, and it is blocked on the
line above - not on a mechanism.

**Live replacement during a round** (swap a model without restarting) is not supported by the emulator: Citron has no save states and
`fast_forward`/`rewind` are unsupported. The working cycle is build -> launch -> one boot -> capture.

## The procedure that makes a run cost one boot

1. `probes/fix_boot_state.py` — answer "Cancel loading?" with Yes, wait for the title screen, stop the session there. A session stopped
   mid-load writes the prompt back and the next three boots fail.
2. Launch with `?mod=<build>`; the build must be filed under the **catalog game id** (`270a15eb98dab4d7`), not the title id.
3. `probes/walk_and_capture.py` — walks the menus with the driver's per-screen gaps and stops at `playing` **only when the round timer is
   on screen** (top-left 30%x14% box, >300 near-white pixels; measured: rounds 947-1020, briefing/menu/prompt 0).
4. It stands still while capturing: enemies path to the player, and walking away kept the frame empty for a dozen rounds.

## Known traps

* `sed -i 's/\r$//'` through PowerShell into SSH becomes `s/r$//` and strips every letter `r` from a file. Ship scripts as **base64** or
  write them LF-only on this side.
* `authorization: Bearer <token>` gets mangled in long quoted one-liners; `?token=` on the URL works, and bodies belong in a file
  (`-d @body.json`).
* A build filed under the title id is invisible to `launch?mod=` and silently does nothing.
* A per-pack edit pointed at a pack the game is not drawing also silently does nothing - that is what cost five rounds of `pl00` builds.
