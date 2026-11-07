# The MercMode gate list, applied (2026-11-07)

`docs/mercmode-adding-titles.md` (commit `2f795479`) is the contract for adding RE4 Switch to the rotation, and it lists
nine gates. This is what has been done against it, in its numbering.

| # | gate | state |
|---|---|---|
| 1 | `re_switch.preferred_spec` RE4 `playable: False` -> `True` | **done**, with `playbook: re4switch_bot` and `perception: "screen-only"` |
| 2 | `re_switch.capabilities` `autoplay.available`, `evidence`, `RE4_REASON` | **done** - available through the playbook, `playbook_round_verified_in_gbox: True`, the reason states what is not there |
| 3 | `test_re_switch.py`: the tests that pin "not playable" | **done** - both updated in the same change; the docstring now says *playable from the screen* |
| 4 | `TITLES.re4.backends.switch` `game_id` and `verified` | **game_id done** (`270a15eb98dab4d7`); `verified` still `False` because no prepare receipt has been produced for it yet |
| 5 | `mercmode_tool.py` prepare loop `RS.RE4_GAME_ID` | **done** |
| 6 | `accept_boundary` keyed on `expected_map`, not `spec['map_id']` | **done** - this was the trap: every Switch boundary was checked against the GameCube room routine |
| 7 | `tools._prepare_title` RE4 branch | **done** |
| 8 | `mercs/round_reports.py` `TITLES`, `NO_ATLAS`, `FOCUS` | **done** - `010099A00BC1E000` in all three; the playbook records no route, so it needs `NO_ATLAS` |
| 9 | `mercs/round_controls.py` `MAPS` | **done** - the Switch id maps to `re4` beside the GameCube one |

Tests: `tests/test_re_switch.py`, `tests/test_re4switch_bot.py` and `tests/test_session_op_capabilities.py` - 25 passing.

## The pin, which is the answer to the rotation question

The document is explicit: *"Without the `re4` pin you get the GameCube disc."* I briefly changed `preferred_spec` to
default to the Switch edition instead, which is a **different contract** and broke two tests that pin "preference is
explicit and host settings unchanged". Reverted: an unset preference means the native edition, and the rotation sets the
pin. That is also the answer to the open ticket *"why is the ps3 version even coming up in rotation?"* - the pin was
missing, not the default.

Live now, set through the documented payload:

```
titles: ['re4', 're5']
pins:   {'re4': '010099A00BC1E000', 're5': '010018100CD46000'}
```

## What the document changed in how this work is done

Three things I had been getting wrong, written down here so they are not re-learned:

* **Restore order.** *"Set `enabled=true` first, then stop the test session. Stopping first leaves a gap, and the idle demo
  fills it."* That gap is exactly the "games overriding me" behaviour: the demo takes the host and the rotation loses it.
* **`mode=playbook`, not `mode=auto`.** *"`mode=auto` falls back silently to learned or vision play, which looks like the
  bot running."* My first autoplay call reported success and did nothing but poll status; an `auto` start that silently
  becomes vision is the same trap in a different place.
* **`node` on every launch**, or it can land on the operator's PC.

## What is still not done, from the same document

Steps 1 and 2 of "Plugging the autobot into RE4" - measure `S_PLAYER`/`S_EMMGR`, and make `Driver.screen()` report the
round - plus the shot fix in step 4. Until those exist this title plays **blind**: it enters rounds and moves, and its
reports say so.
