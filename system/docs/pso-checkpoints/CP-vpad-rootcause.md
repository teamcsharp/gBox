# Why the bot stands still: one missing file disabled the focus-free input path

## The chain, measured end to end

**1. A press via the app's own endpoint is instant, and then everything goes blind.**

```
input w down                0.02s  {"queued":1}
input w up                  0.14s  {"queued":1}
read_memory again          10.03s  HTTP 504  Session did not acknowledge
pso_controls status        10.21s  HTTP 504  Session did not acknowledge
```

Polling afterwards: **the RPC was unavailable for 25.19 s after a single 0.15 s press.** A bot in that shape cannot play - it acts, then cannot see the
result, which is precisely "just standing there".

**2. The input path that does this is the keyboard, not the pad.**

`adapters.py` `DolphinWinAdapter.send_input` has the correct design already:

```python
if self.vpad is not None and self._vpad_works():
    return self.vpad.apply(events)          # focus-independent, instant
...
return win_send_keys(self.proc.pid, rows)   # takes the window focus
```

and `win_send_keys` calls `give_focus()` then waits **up to 10 s** for the focus check. That is the focus stealing, and the blindness.

**3. `_vpad_works()` could never return True.**

```python
from . import pad_route, xinput          # ModuleNotFoundError: No module named 'gbox.pad_route'
except Exception:
    self.vpad_report = {"input_path": "keyboard", ...}
```

**`gbox/pad_route.py` existed in `main-repo/system/gbox/` and was missing from the live install** at `C:\_tools\gBox\system\gbox\`. So the probe raised every
time, the adapter silently chose the keyboard, and every press cost 25 seconds.

## The fix

**Deployed `pad_route.py` to the live tree** (3621 bytes, unchanged from the repo), then ran the exact probe the adapter runs against a real virtual pad:

```
before: {'buttons': 0, 'lx': 0, ...}
press:  {'sent': 1, 'via': 'dolphin virtual pad (XInput slot 1)', 'held': ['a']}
after:  {'buttons': 4096, 'lx': 0, ...}
press_registered: True
report: {'input_path': 'vpad', 'vpad_slot': 1, 'vpad_probe': True,
         'reason': 'the virtual pad reports its presses'}
```

**The probe passes.** An audit of both trees confirms it was the **only** module missing - 0 in the repo that the live install lacks, so no second instance of this
bug is waiting.

## What changes on the next launch

| | before | after |
|---|---|---|
| input path | `win_send_keys` | `vpad.apply` (XInput slot 1) |
| focus | **taken from the operator** | untouched |
| focus wait | up to 10 s per press | none |
| RPC blindness after a press | **25 s** | none |
| a press takes | 10-25 s | milliseconds |

The running session keeps the keyboard INI it launched with; **the fix lands on the next launch**.

## Also established this round

**Talk to the control plane directly.** The app proxy on 8765 cuts worker ops off at 10 s with a 504, while `127.0.0.1:18765` answers the same reads in
**0.03-0.08 s**. `pso_controls` needs `expires` inside `now < expires <= now + 15` - a 5 s window returns `422 PSO command expired`, a 12 s window works:

```
pso_controls status -> {"stats":{"atp":71,"dfp":25,"mst":732,"ata":70,"evp":67,"lck":10,"hp":68}, "equip_any":true}
```

That is the signed-command path for every mod - fast, and usable while the bot plays.

**Player struct facts confirmed live:** pointer in `0x8050EA10`, position at `+0x38`, and this character's HP reads **68 at `+0x2B8`** (the `+0x32C` offset
used by the older tooling does not hold for this session), TP 736. The `state` RPC returns `globals.disc_id = "GPOE8P"` and an entity with `ptr 80DA62A0`.
