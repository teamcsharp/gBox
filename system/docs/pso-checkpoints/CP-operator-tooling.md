# Live operator tooling for PSO on the i9

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

Three operator-owned features built on the paths proven on this machine (2026-11-10 evening). All of them are small, single-purpose
scripts under `docs/research/`; each logs to `D:\\gBox\\pso-ds\\`.

## 1. Turbo chord - `pso-turbo-chord.py`

The operator's request: *"If I hold down R one and I press forward on the D pad, increase the speed of the emulation by one point
five X and if I press back on the D pad, reduce the speed of the emulation until it's back to normal."*

* watches the physical pad (the `pad_bind` alive slot, so the phantom at slot 0 can never trigger it) at 60 Hz;
* **R1 is XInput's right bumper (`0x0200`)**, because Dolphin's `GCPad1` binds `Buttons/Z = Shoulder R`; the analog right trigger is
  accepted too (the first version watched only the trigger and never fired - the bug is documented here so it is not repeated);
* R1 + D-pad **up** -> `session_op fast_forward {"on": true}`; R1 + D-pad **down** -> `{"on": false}`; the chord starts at normal speed;
* every transition is appended to `turbo.log` with the plane's answer.

**Caveat recorded for the operator:** Dolphin's fast-forward is a *binary* turbo whose rate is Dolphin's own FF setting, not a
per-press 1.5x. If exactly 1.5x is wanted, the session must run with Dolphin's speed limit at 150 % instead.

## 2. Route recording - `pso-route-local.py`

Samples the player's world position at 4 Hz while the operator plays, using **`127.0.0.1:18765`'s RPC**, which returns raw hex in
~20 ms:

```
POST http://127.0.0.1:18765/api/sessions/<sid>/rpc
{"op": "read_memory", "args": {"address": 2152786448, "length": 16}}   -> "80da62a0..."
```

(the job route returns only a sha256; the main API's `/rpc` answers 504). Reads the player slot table `0x8050EA10` -> actor pointer,
then x/y/z at actor + 0x38/0x3C/0x40 and the floor id. `pso-route.py convert` (already in the tree) simplifies the walk with
Douglas-Peucker and emits an autoplay mission of `navigate {to: [x, z]}` steps - the bot walking the route the operator walked.

## 3. Random high-level weapon + mag every five minutes - `pso-cycle-build.py`

Zips **`pso_loadout op=plan`** (disc-resolved codes: `atp` for weapons, explicit mag names for mags) with the proven
`pso_controls/floor_spawn` RPC:

```
{"at": "21:15:06", "codes": ["000f02","024000"], "state": "ok", "spawned": 2, "verified": true, "ids": [15728642,15728643], "ms": 797.0}
{"at": "21:20:03", "codes": ["008903","023c00"], "state": "ok", "spawned": 2, "verified": true, "ids": [15728644,15728645], "ms": 31.0}
```

12 weapon + 12 mag codes rotate without repeats; the control layer requires a **fresh** `now < expires <= now + 15` window per call,
which is why the plane's own `pso_loadout op=drop` (expiry computed before its multi-second plan) expires under load.

## 4. Learning the operator's play - `pso-record-operator.py` (already run)

30 Hz pad timeline -> `imitate.learn`: **1,549 input changes -> 173 bursts**, menu keys `start, x, a`, written to
`D:\\gBox\\pso-ds\\learned-missions\\pso-learned-20261110-210547.json`.

## Correction: the cycler equips into the inventory, it does not drop on the floor

The operator's correction: *"when it comes to replacing the weapon, I wanted you to replace the weapon that's in my inventory that I
currently have equipped. not place them on the ground."*

The right operation is `pso_controls op=equip`, which in `pso_live.py` is a **give-and-equip in one verified step**:

```python
if inp.op == 'equip':
    gear = Extras(ad, player_index=inp.player_index, pin_player=True); gear.check()
    code = inp.code.strip().lower()
    if code not in by_code or not code.startswith(('00', '02', '0101', '0102')):
        raise ValueError('Select one equippable item from this disc catalog')
    made = gear.give(code)                      # into the inventory
    item_id = made['ids'][0]
    verified = gear.equip_id(item_id)           # replaces what is equipped
```

verified live on the operator's character:

```
equip 000f02 (weapon) -> {"verified": true, "item_id": 15728648, "message": "Equipment applied to player 1", "elapsed_ms": 359}
equip 024000 (mag)    -> {"verified": true, "item_id": 15728649, "message": "Equipment applied to player 1", "elapsed_ms": 343}
```

and the cycler now logs one entry per five-minute cycle with both items verified:

```
{"at": "21:28:23", "codes": ["009b00", "023a00"], "state": "ok",
 "items": [{"state": "ok", "verified": true, "item_id": 15728650, "ms": 328},
           {"state": "ok", "verified": true, "item_id": 15728651, "ms": 407}]}
```

Mag codes (`02*`) are accepted by the same op, so one path replaces both the equipped weapon and the equipped mag. The earlier
`floor_spawn` approach (and the `pso_loadout op=drop` route built on it) put items on the ground; both are superseded for this
feature.
