# Round 291: every agent-launched session is headless - so input must come from the app

## What was tried this round, and what it established

**A normal (non-co-op) launch was attempted**, on the theory that a windowed emulator would make `send_input`'s fallback work:

```
session bcd14c8d972940b2-d18847779f834e63, pid 59832
windows for that pid:  Temp Window, DIEmWin, "Dolphin 2609", ... all IsWindowVisible = False, all at -32000
```

**Every session is headless.** gBox starts Dolphin with **`-b`** and renders the framebuffer itself - the window objects exist but are hidden off-screen.
That is not a property of the co-op launch; it is how gBox always runs the emulator, which explains something seen earlier: `app_window()` finds the
**gBox** window, not a Dolphin one, because the app is the thing that receives input and forwards it into the emulator.

**And it forwards only for operator-owned sessions.** That is the whole story of this session's input problems in one sentence: the keyboard reaches the
game because gBox relays it, and gBox will not relay agent input into a session it did not launch for the operator.

**The debugger route was examined too.** `autoplay` drives the game "through the session's debugger", which is not the keyboard and therefore not
subject to that relay:

* its deterministic mission `pso-boot-from-title-a` starts and then fails every step with **"no player in semantic state"** - it wants a character,
  and its job was to create one;
* the campaign that would create one (`pso-coop-episodes-1-2`) fails with **"PSO route planner model 'qwen2.5vl:7b' is not available"**;
* that model cannot be installed: the ollama **server** answers "please download the latest version" to a pull request, so only the two text-only
  `deepseek-r1` models exist, and LM Studio has no models and will not start its daemon;
* the mission definitions are not in any file under `system/gbox` or `system/gbox-data`; only recorded operator segments are there.

## The conclusion, stated plainly

**The agent cannot launch a game it can play.** Every launch it makes is `agent_owned`, every emulator is headless, and the app only relays input for
operator launches. The debugger-driven autoplay is the one agent-capable driver, and the two ways to use it on a cold title both fail for reasons
outside the game - a mission that assumes a character exists, and a missing vision model that cannot be installed on this machine.

**A game launched from the app is the only playable surface.** That is one click, and it is the only step in this whole chain that requires the
operator.

## Then

`f3_takeover.py` is **armed and running** (pid 25988). With an operator-owned game up, F3 takes the screen and plays immediately; F3 again stops.

## State

| item | state |
|---|---|
| agent-launched sessions | **headless, undrivable** - verified with a fresh normal launch |
| input relay | gBox only, only for operator sessions |
| autoplay (debugger) | works in principle; blocked by a mission assumption and a missing vision model |
| F3 takeover | **armed** |
| operator game | not running |
| everything else | 14 floors mapped, fight loop, weapon advisor, mod icons, minimap, click-to-order |
