# The working input path on the i9: focus gBox + win_send_keys (the adapter's no-vpad keyboard path)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

## What finally worked

After hours of failures (virtual pad on a phantom slot, relay events queued into nothing, SendKeys lost to focus changes), the path
that actually drives PSO on this machine is the adapter's **own keyboard branch**:

```python
# DolphinWinAdapter.send_input
if self.vpad is not None:
    return self.vpad.apply(events)          # the phantom: acknowledged, dropped by the emulator
keymap = {...}
return win_send_keys(self.proc.pid, rows)   # the path that works here
```

`win_send_keys` needs the game's **top-level window in front** (`_win_input_in_front`), and the docked game's top-level is the **gBox
app window**, so the sequence is:

1. find the visible window titled `gBox`, `SetForegroundWindow`;
2. `win_send_keys(dolphin_pid, [{key,down},{key,up}])` — retry a few times, because the harness window can steal focus;
3. the posted keys reach Dolphin's keyboard bindings on `GCPad1` (`Start = RETURN`, `A = X`, `D-pad = T/G/F/H`, `Main Stick = UP/DOWN`).

Measured: one START press moved the attract screen to the **main menu** (screenshot `232528-gbox-docked.png`), then
`ddown` highlighted **OFFLINE GAME**, `a` opened **SELECT GAME MODE**, and five `a` presses created/selected the character and landed in
**Pioneer 2** (`232934-gbox-docked.png`, "BQF, the Hunter" at Principal Tyrell), player slot `0x80da62a0`.

## What that unlocked, all verified live

| action | result |
|---|---|
| **crit always** | `{"crit_always": true, "verified": true, "code_cache_flushed": true, "message": "Every local-player melee hit is now a critical."}` - RAM site `0x8001468c` reads `4bff0974` (PATCH) |
| **max MAG** | `mag_set` with `item_id` (the op needs the MAG's own id; a bare `properties` call answers "Refresh your equipped MAG first") and a spread summing to <= 200: `{"level": 200, "form": 6, "stage": 3, "pow": 150, "dex": 30, "mind": 10, "iq": 200, "synchro": 120}` |
| **random weapon + mag every 5 min** | cycle 23:28:52: both `verified`, mag rolled to `level 148` with `def 35, pow 37, dex 32, mind 44, iq 191, synchro 116` |
| **through the teleporter** | `pso_controls floor_warp {"target": "1"}` -> `{"warped": true, "from": 0, "floor": 1, "name": "Forest1"}`; player slot intact, floor reads 1 |
| **fighting in the forest** | the key driver advances, attacks and re-centres; `233112-gbox-docked.png` shows BQF in Forest 1 with a Rappy in view and the weapon swinging |

## The one remaining product gap

`autoplay`/missions still press through **gBox's virtual pad**, which this machine cannot enumerate (phantom slot 0), so the bot's own
input path is dead here while the *keyboard* path works. The fix is small and belongs in the adapter: when `self.vpad is not None` but
the pad is not actually reporting (as `pad_bind.alive()` can already tell), fall back to `win_send_keys` instead of pressing a phantom.
That is the difference between "the automation drives the game" (today, via the key path) and "gBox's own bot drives the game".
