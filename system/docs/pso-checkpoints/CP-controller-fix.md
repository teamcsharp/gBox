# Your controller: why it never reached the game, and the fix

## The diagnosis, measured

**Your controller is present and readable - just not through the API gBox was listening on.**

| check | result |
|---|---|
| Windows devices | **Xbox 360 controller** (`HID\VID_045E&PID_028E`, Status **OK**) and a **DualSense** (`VID_054C&PID_0CE6`) |
| XInput slots | **slot 0 = gBox's virtual pad; slots 1, 2, 3 all ABSENT** |
| SDL (pygame) | **exactly one joystick: "Xbox 360 Controller", 6 axes, 11 buttons** |
| Dolphin's binding | `Device = XInput/0/Gamepad` |

So the two halves never met:

* **Dolphin asks XInput for slot 0** - and **my virtual pad is sitting there**, answering for the bot.
* **Your pad enumerates as HID**, so `XInputGetState` never returns it on any slot.
* `padstate.watch_xinput` (the existing mirror) therefore found **no operator pad** and logged *"no operator pad to mirror (virtual pad on slot 0) - the bot drives alone"*, then **returned**.

**That is the whole reason your controller did nothing: the game reads a pad I own, and the mirror that was supposed to relay you only knew how to ask XInput.**

## The fix: a second mirror that speaks SDL

`padstate.watch_sdl` is new. It reads the controller through pygame - the API that *can* see it - and feeds the same chain the XInput mirror uses:

* the same key names (including the A/B swap `_XI` already uses: physical A is `b`, physical B is `a`);
* the same `pad_lease` call, which is what makes a playing bot **let go of the pad**;
* the same `RELAY` flag, which is set automatically for any session that has a virtual pad.

**And the delivery route is the one that provably works.** The relay originally posted to `/api/sessions/{sid}/input` - the queue whose `_pump` I measured earlier as reporting `steps` while the character stood still, whereas `vpad.apply` moved it **211 units through a gate**. Since the mirror runs inside the worker, which holds the live adapter, it now calls **`vpad.apply` directly** and only falls back to the queue if the adapter is missing.

Verified live:

```
padstate: mirroring the operator's SDL pad 'Xbox 360 Controller' (6 axes, 11 buttons)
watch_sdl ran clean: True
```

and it is started beside the XInput mirror whenever a session starts:

```python
threading.Thread(target=padstate.watch_xinput, args=(...), daemon=True).start()
threading.Thread(target=padstate.watch_sdl,    args=(...), daemon=True).start()
```

## What you should now experience

Press anything on the Xbox pad while the bot is playing:

1. `pad_lease` marks you as playing, so **`pad_takeover` makes the bot let go**;
2. your presses go straight to the virtual pad, so **the game acts on them**;
3. when you stop, the bot takes the pad back after its idle time.

## Honest caveat

I verified that the pad is **seen**, that the mirror **runs**, and that the relay is wired to the **proven** delivery path. I have **not** been able to press your controller myself, so the last step - your press visibly moving the character - is the one thing I cannot confirm without you. If it still does not respond, the remaining suspect is Dolphin's binding picking a different device, and the fix is one line of `GCPadNew.ini`.
