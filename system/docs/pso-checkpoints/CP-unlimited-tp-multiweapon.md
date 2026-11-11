# Unlimited TP and stacked multi-weapon equip, live and verified

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Session `e731ee594dde4a89-cae9dad929a34d17`, character BQF Lv 2, Forest 1

## Unlimited TP - done

Offsets (documented in `pso_re_seeds.py:751`, measured live):
```
TObjPlayer.tp      actor + 0x32E (u16)
TObjPlayer.tp_max  actor + 0x2BA (u16)
      hp +0x32C, hp_max +0x2B8
```

Writes go through the **job** API, not the session RPC (`write_memory` on the session channel is read-only; its error says "edits go
through the write_memory job"). The job input field is **`hex_bytes`**, not `data`:

```python
job("write_memory", {"session_id": sid, "address": actor + 0x2BA, "hex_bytes": "03e7"})   # tp_max = 999
job("write_memory", {"session_id": sid, "address": actor + 0x32E, "hex_bytes": "03e7"})   # tp = 999
job("freeze_memory", {"session_id": sid, "address": actor + 0x32E, "hex_bytes": "03e7",
                      "enabled": True, "interval_ms": 50})                                # keep it full
```

Verified: `write tp_max -> succeeded {'verified': True, 'rollback_hex': '0023', 'written': 2}`, read-back **tp = 999, tp_max = 999**,
still 999/999 six seconds later, and the HUD in the capture reads **TP 999/999**.

`freeze_memory` is the useful primitive here: it repins the value every 50 ms, so the bar never drains - "unlimited" without a host-side
loop.

## Multiple weapons equipped at the same time - done

`pso_controls op=multi_equip target=<slot-as-STRING> on=true` runs an item's own on-equip path **without** unequipping the item already
in that slot, so equipment accumulates instead of replacing. `target` must be a **string** (`0`, not `0`) - an int is rejected by
validation.

```
slot 0  000100 SABER        -> "Weapon effects stacked." verified True
slot 4  000100 SABER        -> "Weapon effects stacked." verified True
slot 5  007201 BLADE        -> already equipped, verified True
equipped items now: 5  ->  2x Saber + BLADE + Frame + MASTER SYSTEM
```

So the character has **three weapons equipped simultaneously** and the mechanism is unlimited in the sense that every extra compatible
item adds another stacked equip (`equipped` flags accumulate; PSO still draws one active weapon - the tool states this explicitly).

## Still to do from this request set

- **all techniques**: the learned-technique table is not located yet. Scanning the actor struct and its pointers for a 20-entry level
  array only produced noise; the next attempt should follow the character's name (UTF-16 "BQF") into the player-data block and inspect
  the surrounding bytes;
- **rapid-fire techniques**: needs the cast/action cooldown field in the actor (the technique action state) so it can be zeroed or
  frozen, and a way to fire a technique without the menu (the technique quick-slot path).
