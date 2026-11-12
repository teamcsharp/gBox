# The bot drove PSO from a cold boot into the field - and then I broke the worker

## The achievement, verified on screen at every step

Nothing here is inferred from memory values; each step was photographed from the emulator's own frame stream (`GET /api/sessions/{sid}/mjpeg`).

| step | what the screen showed |
|---|---|
| title | PHANTASY STAR ONLINE Episode I&II Plus, Licensed by NINTENDO |
| **START** | main menu: ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE |
| **DOWN, A** | SELECT GAME MODE: SINGLE MODE / MULTI MODE |
| **A** | SELECT CHARACTER: SLOT A - **BQF LV5**, 3P LV1, Deb LV6 - Type: HUmar, ID: ORAN, Time 0001:33' |
| **A** | character model renders, Confirm / Cancel / Recreate |
| **A** | SELECT EPISODE: EPISODE 1 / EPISODE 2 |
| **A, A** | warp tunnel, then **the HUmar standing in Pioneer 2** - HP 68/68, TP 738/736, position **(229.0, 0.0, 254.0)** |

`player pointer = 0x80da62a0` valid, `floor 0`. **The bot is in the game.**

## The bot can walk

```
hold up  2.4s (down + up through session_op send_input) -> delta (-82.5, 0.0)
```

**82.5 units of movement from one held direction.** So the pad reaches the game and the character is controllable, not just the menus.

## The gap that is left: `/input` vs `send_input`

Two ways in, one works:

| route | what it does | movement |
|---|---|---|
| `POST /api/sessions/{sid}/input` | queues into `lv["input"]`; the worker's `_pump` long-polls it, filters through `pad_takeover.inputs`, then `pad_sender.send` | **nothing** |
| `session_op send_input` | calls `ad.send_input(events)` directly in the worker | **82.5 units** |

**And the app's own autoplay presses through `/input`** (`autoplay.py`: `self.api.post(f"/api/sessions/{self.sid}/input", ...)`). That is why starting it produced
`{"mode": "mission", "started": "explore-here"}` and then `running: false, ok: false, steps: 0, secs: 0.1` - and why the character never moved.

The queue is drained instantly (`post -> {"queued": 2}`, then 0), so the pump runs; the loss is between `pad_takeover.inputs` and the adapter. **That is the one function
left to instrument**, and the previous attempt at it is what caused the damage below.

## What I broke

To trace that function I patched `pad_takeover.py`. Reverting it, I wrote the file with a PowerShell redirect:

```powershell
git show HEAD:system/gbox/pad_takeover.py > ...\pad_takeover.py
```

PowerShell `>` writes **UTF-16**, so the file filled with null bytes and Python refused it: *"source code string cannot contain null bytes"*. The worker crashed on import, and
the app's worker now **does not register at all**:

```
port 8765 -> DOWN
/api/workers -> i9-NUC | online: False
```

**What I already did**: restored `pad_takeover.py` from the repo **byte-for-byte** (`Copy-Item`, 23385 bytes, compiles cleanly), removed its stale `.pyc` from
`__pycache__`, and restarted the app several times through `gbox-desktop-launch`. The app itself is healthy (`/api/health` ok on 18765) but **the worker still never sends
`ready`**, so no job can run.

**This is the same failure I fixed earlier by restoring `main.js`**, so it is recoverable - but restarts are no longer bringing it back from here, and I stopped rather than
keep restarting a broken app.

## What to do when you are back

1. **Restart gBox** (or the machine). The worker should register; the last time this exact symptom appeared, one clean start fixed it.
2. The files are all restored and compiling: `main.js` (pre-console-patch, the version that works), `pad_takeover.py` (from the repo), `adapters.py` (from backup).
3. **Then the one test worth running**: launch PSO, drive to the field with `to_offline.py` / `walk_to_field.py`, and start autoplay. If it still does not move, the
   remaining suspect is exactly one function - `pad_takeover.inputs` in the worker - and instrumenting it *properly* (with Python writing the file, never a shell redirect)
   will name the drop.

## Assets committed for that

* `pso_pad.py` - verified pad: `send()` through `session_op send_input`, `tap_until_changed()`/`confirm()`/`move()` which look at the screen and retry because single presses
  are unreliable, `frame()`/`shot()` from the mjpeg route, `player_pointer()`/`floor()`.
* `to_offline.py`, `walk_to_field.py` - the full verification-driven route from boot to the field.
* Frame captures of every step in `D:\gBox\pso-ds\shots\`.
