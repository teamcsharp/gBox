# One owner of the pad, enforced at process level

## The last piece: the bot was still pressing

The relay and the bot both write to the same virtual pad. The bot's cooperation was checked **once per loop iteration**, and an iteration contains a `hold(pad, "up", 0.7)` - **0.7 seconds of
pressing**. So whenever the operator pressed during that window, **both were injecting at once** and the same cancellation that made two relays useless applied: **one side's release wipes the other's
press.** From the operator's side: the controller "ignored them", *intermittently* - which is exactly what was reported.

**Iteration-level cooperation cannot fix that. Process-level suspension can.**

```
relay watching 'Xbox One Controller'
  suspended the bot (1 process(es)) - operator has the pad
  relayed 1 event(s): ['a']
  operator idle - bot resumed
  operator idle - bot may resume
```

`NtSuspendProcess` freezes the bot where it stands - **no further input from it, nothing to cancel** - and `NtResumeProcess` lets it carry on **without a relaunch, a boot, or a lost session**.

## And the reason the first attempt at this did nothing

`_bot_pids()` used **`wmic`**, which is **absent on current Windows**:

```
wmic MISSING - that is why _bot_pids() returned nothing
```

so it found no bot, suspended nothing, and logged nothing - a silent no-op. Replaced with PowerShell's CIM query, which is present everywhere:

```
bot pids found: [39832]
```

## The complete picture of "the controller does not work"

**Four separate faults**, each of which alone was enough to break it, and each found by measuring rather than guessing:

1. **The controller is HID, not XInput** - SDL sees it, `XInputGetState` never did, and Dolphin's GCPad is bound to `XInput/0`. Needed a whole relay, not a setting.
2. **The relay resolved its session once** and kept posting to a dead id after every relaunch - silent, no errors.
3. **Two relays ran at once** and cancelled each other's presses.
4. **The bot kept pressing while the operator did** - an iteration is 0.7 s of held input, so cooperation at iteration boundaries was never enough.

Fixed by: an SDL relay that **rebinds to the live session every second**, a **single-instance lock**, and **process suspension while the operator plays**.

## The invariant now

**Exactly one writer to the virtual pad at any moment** - the operator while they are touching it, the bot the rest of the time. The relay proves it on every burst and gives the pad back on idle.
