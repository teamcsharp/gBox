# F3 was stopping the bot, not starting it

## What the measurement shows

The autobot works. Driven from F3's own endpoint it walked the character across the room:

```
pos before: (21.3, -3.4, -661.8)
  1: (19.7, -2.1, -654.4)
  3: (15.4, 0.0, -642.5)
  6: (3.6, 0.0, -646.2)
  8: (-51.5, -10.0, -795.5)
 10: (-131.8, 0.0, -753.4)

largest movement: 258.46 units
VERDICT: the autobot is driving the character
```

**258 units across a Cave 1 room.** The bot can play. So "it just stands there" was never about combat or pathing.

## The cause

F3 is wired to `op: 'toggle'` in both places that can fire it:

* `index.html` → `f3Autobot()` → `autobot(api, sid, {op: 'toggle', source: 'F3'})`
* `pip-media.js` → `toggleAutobot()` → `op: 'toggle'`

The server resolves `toggle` as **"if running then stop, else start"**:

```python
want = ('stop' if running else 'start') if body.op == 'toggle' else body.op
```

So **every press while the bot was playing stopped it.** The screen showed a character standing still, and the menu item is labelled *"Take control (autoplay)
F3"* — a take-over, not a toggle. Pressing it twice was start-then-stop, which looks exactly like a bot that never plays.

## The fix

Both call sites send **`op: 'start'`**. The server answers `already_running` when it is already in charge, so a second press is harmless and **never hands
control back**. F3 now always means "the bot drives now". Stopping stays on the menu and the API.

The shown-session lookup before the call is also shortened (2.5 s → 1.2 s) so the request goes out on the first frame the game is known.

```
index F3 sends start: True      index F3 toggle gone: True
media F3 sends start: True      media F3 toggle gone: True
```

## What the operator has to do

**Press F3 once.** It starts the autobot and leaves it in charge.

An agent cannot start it - the server refuses with `409 That game is the operator's session; automated tasks can't start or stop its autobot` - which is
correct and is why this has to be the operator's press.

## Two fixes behind this one

* **`pad_route.py` was missing from the live install**, so the virtual-pad probe always failed and every press fell back to `win_send_keys`, which takes the
  window focus and blinded the RPC for **25 s**. Deployed and proven (buttons 0 → 4096, `input_path: vpad`).
* **F3 was a toggle**, so the operator's own presses were cancelling the bot.
