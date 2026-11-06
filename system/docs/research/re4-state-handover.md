# RE4: state of the work (handover)

Written 2026-11-06 for the agent that owns the next request guide. Everything here is measured on the Spark
(`lilspark`, 10.89.1.246, aarch64 Linux) during this session; nothing is inferred from documentation. Where something
was ruled out, the measurement that ruled it out is included so it is not tried again.

## 1. What is already proven to work

| layer | evidence |
|---|---|
| Catalog entry and inventory | `game_id 270a15eb98dab4d7`, title id `010099A00BC1E000`, platform switch, adapter **citron** |
| ROM access verification | `mercmode` tool `op=prepare` → inventory reports `re4 playable=True` |
| Launch | `@launch {game_id 270a15eb98dab4d7, node lilspark}` → session up, adapter `citron` |
| Rendering | captured frames 960×540, brightness steady 58.5–58.7 for two minutes (the title screen) |
| Frame capture accuracy | gBox's `frame.jpg` matched the emulator's X root within ~1 unit on 6 of 8 paired samples (measured on RE5) |
| RAM read path | `POST /api/decrypt-lab/scan {mode:"module"}` works on RE4: module base `0x3ca7c04000` on that boot |
| Driver scaffolding | `gbox/mercs/titles/re4_switch.py`: `module_base()` (64-byte signature at `SIG_OFF=0x100000`), `units()` (vtable scan at `VTABLE_OFF=0xAE7050`), `snapshot()`, `own_screen()` |

## 2. What blocks it, in the order it blocks

### 2.1 Input does not reach the emulator (the wall)

`session_op {op:"send_input"}` returns `succeeded` with `{"sent": 6}` — no keys skipped — and the captured frame is
**byte-identical** before and after (`diff 0.00`).

Four independent paths were tried, all failing:

| path | result |
|---|---|
| `xdotool key` to the focused window (window activated first, `getwindowfocus` confirms the same id) | frame unchanged (`diff 0.04–0.25`, the idle animation) |
| `xdotool key --window <id>` (targeted synthetic events) | unchanged (`0.38`) |
| a real **uinput keyboard** (an evdev device, so SDL cannot dismiss it as synthetic) | unchanged (`0.26`) |
| a window hotkey (`f11`) instead of a pad key | unchanged |

Environment facts that matter:
- the session display is `:100`, `QT_QPA_PLATFORM=xcb`;
- there is **no window manager** on it: `xprop -root _NET_SUPPORTING_WM_CHECK` → "not found", and none of
  openbox/matchbox/fluxbox/twm/i3/xfwm4 is installed;
- citron's windows are correctly sized (Qt shell 1280×720, render surface 1280×720; the `citron-neo: The switch fell
  off` children are 1×1 / 853×1 / 853×24);
- the keyboard bindings are correct and identical in meaning to eden's:
  `player_0_button_a="toggle:0,code:67,engine:keyboard"` vs eden `"engine:keyboard,code:67,toggle:0"`, same codes
  (a=67, b=88, plus=77);
- the uinput device itself was created successfully (the first attempts failed with `EINVAL` because
  `uinput_user_dev` must be written at its full size, 80+8+4+4·(64·4) bytes).

Conclusion: no keyboard input reaches citron on this host. This is inside the emulator's input/video backend or its
"active" state handling without a window manager — **not** in gBox's key table, focus handling or bindings.

### 2.2 The driver cannot see a round

`re4_switch.py` `snapshot()` returns a fixed skeleton:

```python
snap = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, ...}
```

There is no player anchor, so no hp, no position, no timer, no enemies; `Bot.tick()` is a stub. MercMode's `adopt`
requires live gameplay telemetry (`screen == "playing"`, `team_role == "solo_p1"`, `running` true, age ≤ 8 s), which
this driver can never supply.

The known lead, unverified because it cannot be sampled outside a round: a game-state pointer-to-pointer read at
`module + 0xc25d78` (found from the input consumers `FUN_00360d70` / `FUN_0035f680` / `FUN_00360fc0`). At the title
screen that address reads sixteen zero bytes, which is the expected shape outside a round.

### 2.3 MercMode configuration gates (trivial, but real)

- `titles` for lilspark is currently `["re5"]` — RE4 is not in the rotation;
- the ROM-access receipt expires: `valid_preparation` accepts it only while `0 ≤ now − checked ≤ 1800` s, so RE4 reads
  `playable: False` ("ROM access has not been verified on this PC") roughly half an hour after each `prepare`;
- `adopt` also accepts only adapters in `('rpcs3','dolphin','eden','citron')` (RE4's citron is fine) and requires the
  launch job's identity to match the running worker.

## 3. A recommendation worth deciding before more work

There are two RE4 builds in reach and they are not equally blocked:

| build | emulator | input | model writer | verdict |
|---|---|---|---|---|
| RE4 Switch | citron | **broken (2.1)** | none (MTF 2.0) | blocked at the emulator |
| RE4 GameCube/Wii | dolphin | **works** — `gbox/vpad_linux.py` exists precisely for Dolphin, and eden/dolphin input paths are proven | **exists**: `re4gc_models.gltf_to_bin` / `swap_body`, `re4gc_enemies.retarget(roles=GANADO_ROLES)` | much closer |

If the objective is "RE4 playing under the autobot in MercMode", the GameCube/Wii edition on Dolphin removes the wall
in 2.1 entirely, keeps a working model-import path for the zombie-replacement work, and leaves only 2.2 (the player
anchor) to solve — which is solvable once a round is reachable. The Switch build remains valuable for the asset
pipeline (it is decrypted and inventoried) but is the harder path to autoplay.

## 4. Decisions the next request guide should make

1. **Which RE4 build** MercMode should target for autoplay: Switch/citron (needs the emulator input fixed) or
   GameCube/Wii/dolphin (input proven).
2. **May a window manager be run on the games' displays** (e.g. a minimal one per session display), and may the
   citron launch environment/flags be changed (`SDL_VIDEODRIVER`, windowed vs `-f`, a keyboard controller config)?
   Both are emulator-level changes and were deliberately not made.
3. **Is one operator-driven pass acceptable** for the anchor work: a human presses through to a Mercenaries round once
   while gBox samples `module+0xc25d78` and the vtable census, after which the driver has its anchor and the bot can
   take over. This avoids needing input at all for step 2.2.
4. Which of the two Mercenaries paths the bot should drive on RE4 (the Switch build's `Extra Content → Mercenaries`
   chain versus the GC/Wii selects), so the menu walk can be written against the right screen IDs.

## 5. Concrete next steps, with acceptance criteria

| step | acceptance |
|---|---|
| choose the build (§4.1) | written decision in the guide |
| reach one round by any means (operator pad, WM, or input fix) | `screen == "playing"` telemetry from an RE4 session |
| sample `module+0xc25d78` in that round | a non-zero pointer whose target resolves to a player object (hp at `+0x3c2` in `0x1..0x64`) |
| write the anchor into `re4_switch.snapshot()` | `player` non-None with `hp`, `pos`; `timer` an int in a round |
| add RE4 to `titles` and prepare | `adopt` returns 200 on a live RE4 round |
| one autoplayed Mercenaries round | rounds counter increments in `mercs_rounds`, no "showed only black" entry |

## 6. Loose ends noted while working (not blockers)

- The `rank_not_verified` ticket class (round analyses) is pinned to `sparkDeux`, which was the same server as
  `lilspark2`; the node was collapsed and legacy labels are still admitted (`round_reports.LEGACY_TARGETS`).
- A donor **mesh** written into an object archive hangs the title's load (measured twice, with and without retagged
  materials) — relevant because any future MTF writer must be byte-correct, not approximately correct.
- Report evidence for Switch titles carries screenshot + tactical map + RAM witness (player 12 KiB and four nearest
  enemies, content-hashed); save states do not exist on eden/citron and each incident says so explicitly.
