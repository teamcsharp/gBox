# Why gBox ignored the controller: two relays were cancelling each other

## The measurement that settled it

A live probe of the pad showed the operator's stick **working perfectly**:

```
axes (-1.0, ...)        <- stick LEFT
axes (0.0, -1.0, ...)   <- stick UP
axes (1.0, ...)         <- stick RIGHT
buttons []              <- (pressing A/B at other moments)
```

So SDL was reading the hardware correctly. And the injection path was proven twice over: a single press moved the character **30 units**, and the relay's exact **batch** shape - releases then a press in one job - moved it **73.5 units**.

**What was left was the relays themselves, and there were two.** Each reads the same pad and posts its own view of it. With two, one relay's `up:False` release cancels the other's `up:True` press in the same instant, so **the net input is nothing** - the game sees a stream of presses and releases and never a held direction. From the operator's side the controller simply does nothing, with no error anywhere.

**Killed to one relay, and the stick moves the character:**

```
positions: (211,394) -> (214,392) -> (216,410) -> (223,447)
MOVEMENT: 58 units

relayed 5 event(s): ['up', 'down', 'left', 'right', 'down']
```

**The `down` at the end of that event list is the operator's stick.**

## Why the singleton did not prevent it

The launcher problem again: **`python.exe` in the hermes venv spawns the real interpreter as a child, and both run the script.** The singleton blocks a *second genuine* instance, but the parent and child are one launch, so one of them exits on the lock and the other runs - which is correct. What produced the extra relay was **starting one while an older one was still alive**: the older one held the lock, so the new launch's child exited, and the old relay kept injecting from a stale session. That is a lifecycle problem, not a locking one, and the fix is the same rule that has applied all session: **kill before starting, and verify exactly one is running afterwards.**

## Verified now

* **one effective relay** (shim parent launching, child running, the lock blocking any second);
* **it rebinds to the live session every second**, so a bot relaunch no longer strands it on a dead session id - which was the *other* half of "the controller stopped working";
* **the pad is read** (axes at ±1.0 when the stick moves);
* **the injection reaches the game** (58 units of travel, and 73.5 in the batch test).

## The rule for operating this

**Kill every relay, start exactly one, then confirm the count is one.** The same for the bot. Two of anything in this system does not add - it **cancels**, because each copy asserts its own view of a shared input device.
