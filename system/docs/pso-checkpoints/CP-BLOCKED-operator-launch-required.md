# Blocked: the remaining checkpoints need a game only the operator can launch

## What is blocked

**CP19** - *"Episode I unattended, with the mastery build"* - and **re-running CP17 and CP18 against their stated criteria**, which say *"with both players"*
and *"with both players alive"*. The evidence recorded for CP17 (nine floor changes) and CP18 (the Dragon from 1191 HP to zero) is **single-player**.

## Why it cannot proceed from here, with the measurements

**1. Every session the agent launches is headless and receives no input.**

A fresh normal launch (no co-op) was made specifically to test this:

```
session bcd14c8d972940b2-d18847779f834e63, pid 59832
windows owned by that pid: Temp Window, DIEmWin, "Dolphin 2609"
  all IsWindowVisible = False, all positioned at -32000
```

gBox starts Dolphin with **`-b`** every time and renders the framebuffer itself. The window objects exist but are hidden off-screen. So
`send_input`'s fallback (`win_send_keys` on the emulator window) has nothing to send to, and every `session_op send_input` reports success while
delivering nothing - which is exactly what was observed: 14 presses "ok", player pointer still `0x0`, floor still `0`.

**2. Input is relayed by gBox itself, and only for operator-owned sessions.**

That is the single sentence behind every input problem in this session. The keyboard reached the operator's game because **gBox** received it and
forwarded it into the emulator; the same keyboard never reached an agent-owned session because gBox does not relay agent input. `remote_input` is not an
alternative - it is RetroArch's network gamepad, and Dolphin has no such port.

**3. The one agent-capable driver cannot boot a cold title.**

`autoplay` drives through the session's **debugger**, so it is not subject to the relay. Both ways to use it fail for reasons outside the game:

* the deterministic mission `pso-boot-from-title-a` ("break the attract loop and reach the field from a cold title") starts and then fails every step
  with **`"no player in semantic state"`** - it requires a character, and creating one is what the mission was for;
* the campaign that creates one, `pso-coop-episodes-1-2`, fails with **`"PSO route planner model 'qwen2.5vl:7b' is not available"`**;
* that model **cannot be installed**: the ollama **server** answers *"Please download the latest version"* to a pull, so only the two text-only
  `deepseek-r1` models exist; LM Studio has no models and its daemon will not start;
* an inline `{"steps":[{"op":"press","key":"start"}]}` mission is **ignored** - `start` falls back to `vision: make progress`, which fails with
  `'choices'` because there is no vision model behind it.

**4. The mission definitions are not editable from here.** `pso-boot-from-title-a` is not in any file under `system/gbox` or `system/gbox-data`; only
recorded operator segments are there, so the assumption that a character already exists cannot be corrected locally.

## What a single operator action unblocks

**Launch PSO from the gBox app.** A game launched from the app is **operator-owned**, and on such a session the keyboard path works - that is how the
Dragon was fought, the floor changed nine times, and hundreds of units were walked in this session.

Then **F3**: `f3_takeover.py` is **armed and running** and takes the screen and plays immediately.

## What is complete and verified

| item | evidence |
|---|---|
| CP0-CP16 | delivered in earlier rounds |
| **CP17** | **9** floor transitions recorded with position and elapsed time, `floor_warp` never issued |
| **CP18** | Dragon HP **1191 -> 814 -> 727 -> 652 -> 468 -> 390 -> 202 -> 0**, entity vanished, player alive |
| map pipeline | 159 collision maps, **14 floors, 244 rooms**, heights validated to **0.16 units**, layout identified at **94/94 live objects** |
| navigation | audit per floor; Cave 3 and Mines 2 fully navigable after door-aware pathing |
| minimap | live at `:8802`, rooms shaded by height, click-to-move, click-to-target |
| tooling | weapon advisor (unit-tested on six situations), play loops, supervisor, exit seeking |
| PiP toolbar | **21 PSO mod icons**, game-aware, RPC-driven so they work mid-play |
| F3 | armed |
| self-test | 8 of 9 checks pass; the ninth needs a running session |

## State

| item | state |
|---|---|
| goal | blocked on an operator-owned game |
| F3 takeover | armed (pid 25988) |
| sessions | two headless agent-owned sessions at the attract loop |
| model backend | ollama too old to pull; no vision model; LM Studio unavailable |
