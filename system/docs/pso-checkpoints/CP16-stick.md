# CP16: focus-free movement

Session identity: DeepSeek    Branch: ds-pso-cp16-stick-20261110    Commits: this branch
Goal: 4 (P3-P5 cannot fight the operator for the window)

## The test, and what happened

CP16 asks: "with the character free in the lobby (CP4) and `padstate.RELAY` off for that session, hold `up` through the
virtual pad for 2 s, then read the position. **Accept:** the position moves."

**The prerequisite could not be reached** - not the lobby, but the input path itself. Round 96 had a live session (launch
admitted, `83202f53e9cd4aa5-1b349dbb3ee94db4`, `gBox Dolphin` pid 33928) and measured three routes:

| route | attempts | result |
|---|---|---|
| local `SendInput` after `win_bring_to_front` | 1 | `focus lost before pressing` - the foreground is taken back before the press |
| local `SendInput` **unfocused** | 4 | no reaction (`mode` stayed 0) |
| worker relay `POST /api/sessions/<sid>/input` (agent and autoplay) | 6 | `{"queued": 1}` each, no reaction |

All three fail on the same condition: `adapters._win_input_in_front` only lets pad input through while the game's top-level
window is the **foreground** window, and an agent-side process cannot hold the foreground while the harness window owns it.
The game is not headless (its window exists and is docked) - it simply receives no keys while another window is in front.

## Verdict, by the guide's own rule

CP16's "if blocked" clause says: *"keep the keyboard walker, live only under rule 7."* That is the honest state now - and it is
stronger than "blocked": the stick/relay path was **measured** and does not deliver at all in this configuration, so the
2-second-hold test could not even begin. Nothing about the character's movement was tested because no input arrived.

## What would make CP16 testable

1. the operator clicking the game window once, so the game holds the foreground for the session (the input then lands - the
   rule is only about which window is in front);
2. a worker op that activates the window and injects in one step (the same thing `pso_coop` does internally with
   `win_bring_to_front` + `controller`);
3. a launch carrying a **pad binding** so the relay has a map to inject through.

Any of the three also unblocks CP4's boot walk, CP5, CP10's confirmation and CP12's character-select frame.

Tests: none (a live measurement; the probes are kept as `docs/research/pso-cp4-{local-driver,unfocused-probe,relay-probe}.py`).
