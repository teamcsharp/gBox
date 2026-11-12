# Round 26: the batched input is verified - 12 checks

## Why this test matters

Rounds 24-25 changed how input is delivered, and that change is exactly the kind that fails **silently**: a `tap` sending the wrong event order, a `move`
dropping a key, or a cap that never releases would all present as "the bot stopped moving" - which is the symptom that cost several rounds already.

So the payloads are checked directly against a recorder that stands in for the plane, with no game involved.

## The 12 checks

```
PASS the cap is small enough to prevent a queue - 4
PASS tap submits exactly one job - 1
PASS tap sends two events - 2
PASS tap presses before releasing - [{'key': 'up', 'down': True}, {'key': 'up', 'down': False}]
PASS tap names the key
PASS move submits one job for three taps - 1
PASS move sends six events - 6
PASS move keeps the tap order (each key down+up in sequence) - ['up', 'up', 'up', 'up', 'a', 'a']
PASS move alternates down and up - [True, False, True, False, True, False]
PASS the in-flight counter is released after success - 0 -> 0
PASS a failed job reports False - False
PASS the in-flight counter is released after failure - 0 -> 0
```

The last three are the ones that would have bitten hardest:

* **the counter is released after success and after failure** - a leak there would stall the bot at the cap forever, and it would look exactly like a hung
  worker;
* **a failed job reports False** - so a rejected press is visible to the caller instead of being treated as delivered.

And one check **failed at first, and the code was right**: my expected order for `move("up", "up", "a")` was an interleaving that would have pressed `a`
before releasing `up`. The implementation emits each key's down+up in sequence, which is correct, and the expectation was corrected rather than the code.

## Total verification now

| layer | checks |
|---|---|
| perception (entity table, names, position, HP, door state) | 11 |
| movement (calibration-driven direction, approach) | 10 |
| decision (switch/enemy/exit/room priority) | 12 |
| **batched input (payloads, cap, counter)** | **12** |
| **total** | **45** |

All runnable without an emulator, all re-runnable after any change.

## State

| item | state |
|---|---|
| batched input | **verified**, 12 checks |
| job guard | running |
| worker | **still hung** on round 23's executing jobs |
| game | same session from 20:17, unresponsive to input |
| needed | **restart gBox** |
