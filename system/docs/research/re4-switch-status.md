# RE4 (Switch): what works, what does not, and what each thing needs

Updated after the rounds that took the model path to a drawn result on both sides, closed the three routes to a *character replacement*, and
mapped the texture containers. Every claim is either measured (with the round) or marked unproven.

## The pipeline that works today

```
any extracted .glb  ->  gbox.glb_donor      (keeps the skeleton; picks a container with room for it)
                    ->  gbox.re4hd_affine   (per-band proportions; blend, ceiling, or target_factor)
                    ->  gbox.re4hd_edit     (in place, slot size kept)
                    ->  gbox.switch_mods    (LayeredFS build under the catalog game id)
                    ->  a drawn change in a live round
```

Entry points:

* `POST /api/decrypt-lab/replace` — one call behind the panel's operations; `write=false` previews.
* `python -m gbox.glb_donor <model.glb> <out.bin>` — any collection model becomes a donor.
* `system/tools/probes/fix_boot_state.py` — puts the save back to a menu so the next boot is clean.
* `system/tools/probes/walk_and_capture.py` — walks the menus, waits for the round timer, captures in-round.
* `system/tools/probes/vulkan_device_check.py` — proves the GPU/Vulkan stack works before blaming the emulator.

## Measured facts

| claim | round | evidence |
|---|---|---|
| The camera's player mesh is **`pl08.udas`** | 112-113 | scaling that one pack distorts the player; every other halving left him stock |
| `pl08`'s visible surface is essentially **material 0** | 113 | vanishing materials 1..24 leaves the player unchanged |
| A **per-band affine** transfer is drawn, on the player and on enemies | 100-136 | Sonic proportions on the player; a reshaped Ganado in frame |
| Strength is a property of the **target** - per slot and per pack | 106-136 | `em16` reads at 0.15, `em10` does not; `auto` turns `em16` into a mass |
| The pack's TPL is a **descriptor table only** | 116 | 9 descriptors in 608 bytes, zero `DDS ` magics |
| Texture ids map **local -> global -> imagepackhd** | 117 | materials use 0/2/3; the TPL entry carries the global id |
| `imagepackhd` has **nothing below id 6** | 118 | 1,813 archives, ids 6 .. 0x4b000005 |
| The material header's colour field is **not writable** | 133 | three tint builds (1, 17, all materials) all stop the stage loading; stock does not |
| A player pack in an enemy slot **hangs the load** | 137 | `em10..em16 <- pl00` never reaches a round |
| Within-family pack swapping **destabilises** | 138 | `pl08 <- pl07`: one run "playing" with no frames, one hung at `loading` |
| After a reboot the **driver needs a minute** before Vulkan works | 132 | the same launch fails at `up 0 min` and succeeds minutes later |

## The three routes to a character replacement, all measured

| route | result |
|---|---|
| edit the mesh in place | **draws**, but only same-topology edits: a proportion transfer, never a different character |
| swap the texture | **blocked**: player surfaces absent from `imagepackhd`, TPL holds descriptors only, header tint stops the load |
| swap the whole pack | **blocked**: player-into-enemy hangs; within-family destabilises |

**So this pipeline can reshape a character but cannot substitute one for another on this title.** A true replacement needs an engine-level hook
or the surface swap below.

## The one open route

**The surface address RAM can supply.** The emulator exposes `read_memory`, the lab page has a hex scanner, and MercMode records round RAM, so
the pieces exist; what is needed is a GPU command-stream read - find the texture bind in the frame's draw stream and take the address. That
names the surface directly and cannot be wrong, and every texture question above collapses once it is known.

## The procedure that makes a run cost one boot

1. `fix_boot_state.py` — answer "Cancel loading?" with Yes, wait for the title screen, stop the session there.
2. Launch with `?mod=<build>`; the build must be filed under the **catalog game id** (`270a15eb98dab4d7`), not the title id.
3. `walk_and_capture.py` — stops at `playing` only when the round timer is on screen, **waits up to 90 s for it**, then captures standing still.
4. After a reboot: wait for the driver (see the fact above), and restart `mnt-gbox-quickswap2.mount` if the share is missing.

## Known traps

* `sed -i 's/\r$//'` through PowerShell into SSH becomes `s/r$//` and strips every letter `r`. Ship scripts LF-only, written on this side.
* `authorization: Bearer <token>` gets mangled in long quoted one-liners; use `?token=` and put bodies in a file (`-d @body.json`).
* Any command with a pipe or `grep "two words"` inside a quoted `ssh '...'` is unreliable - put it in a script file.
* A build filed under the title id is invisible to `launch?mod=`.
* A per-pack edit aimed at a pack the game is not drawing does nothing, silently - that is what cost five rounds of `pl00` builds.
* Run the **stock control** before concluding a build broke something; it is one boot and it separates the build from the harness.
