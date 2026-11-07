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

## The two documented pointer leads, tested (2026-11-07)

`docs/mercmode-adding-titles.md` says the player-pointer leads disagree between notes and to test both:
`module+0xb25d78` and `module+0xb25d88`. On a live round, with the module base confirmed by the signature
(`0x3CA7C04000`, `fd7b07a9…` at `+0x100000`), both were read and followed:

| lead | slot | value | what it points at |
|---|---|---|---|
| a | `module+0xb25d78` (`0x3CA8729D78`) | `0x3CA871EE08` | a heap object whose head is **eight pointers into `0x3CA8E7xxxx`** - a vtable-and-table shape, like a manager |
| b | `module+0xb25d88` (`0x3CA8729D88`) | `0x3CA8D3F398` | a heap object whose first word is `0x5D55A5C680` (not a guest pointer) beside module-adjacent pointers |

**Neither is the player unit.** Reading 2 KB at each object found no `u16` equal to 100 or 1000 anywhere (the two values
the notes report for player and enemy health), and no run of three floats in a plausible world range - so neither object
carries a position or a health field in its first 2 KB. Lead a is the more structured of the two: a pointer table, not a
character.

That is a negative result, and worth recording as one: the next attempt should not re-read these two slots expecting a
player. What it does confirm is that `base + offset` addressing and the heap band (`0x3CA8…`) are exactly where the notes
said they would be.

## The restore order in the document, verified

The same document says: *"To restore: set `enabled=true` first, then stop the test session. Stopping first leaves a gap,
and the idle demo fills it."* Followed literally, after a test session on RE4 Switch:

```
configure enabled=true titles=['re4','re5']  -> done
stop the test session                        -> stopped
90 s later: phase playing | Resident Evil 5 (Switch, No Mercy)
```

No gap and no demo: the scheduler took the host straight back. This is the "games overriding me" problem solved by
ordering, and it is now the only order used here.
## Round 51: the enemy lead is class metadata, and one boot that never reached a round

**`module+0xaed3b0` is not a stable address.** Read as a module offset on a live round it holds three words:

```
0x3CA86F13B0:  a7c0f2b0   3c    a7dadfd0
```

None is a guest pointer (the heap band is `0x3CA8…`), and `0x3c` reads like a count. So `0xaed3b0` names a *class* - which
is what the document called it - and the address it was seen at belongs to one boot, not to the module. Chasing it as an
offset wastes a boot; it is not one.

What survives a boot is the **shape** the note describes: about 26 equal-sized objects carrying 1000. The reusable scan is
therefore "find `u16 == 1000` across the mapped window, then look for the stride that repeats" - `ram/search` with
`equals 1000`, then a gap histogram over the candidate addresses. That script is in `system/tools/probes/enemy_stride.py`
and it did not get an answer this round, because the boot never reached a round:

```
MARK reached False
```

The walk reads frames and stops on `unknown` only after `select_stage` has been seen (the driver's own rule). On this boot
that never happened, so it pressed nothing and exited - which is the correct behaviour, and also why the rotation had to be
restored by hand afterwards: the script's restore block sits after the walk, so a failed walk skips it. That is a defect in
the probe, not in gBox: **every probe that pauses the rotation must restore in a `finally`**, whichever way it exits.

## The rule this round reinforced

Three of the last four boots ended somewhere other than a round (a story load, an unclassified screen, a stalled load).
The document's step 5 exists for exactly that: pause, launch, **prove the round is live before measuring anything**, and
restore `enabled=true` first. A probe that measures first and discovers later costs a boot and leaves the host unsupervised.