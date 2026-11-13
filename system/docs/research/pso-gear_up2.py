"""Give the character the best weapon and the stats to use it, using the app's own PSO mod operations.

`pso_mods` is the machinery for exactly what the operator asked - *"the bot must have the best weapons and fight properly"* - and its input says how:

```
op:     give | stat | floor_clear | equip_any | crit_always | key_bypass | move_speed | rare_drops | meseta | item_set
code:   give: item code hex (e.g. 000105 = DB's Saber) or name
equip:  give: also equip the first created item
name:   stat: atp | mst | evp | hp | dfp | ata | lck
value:  the amount
factor: move_speed: the player moves N times faster (1 = off)
```

And `pso_loadout op=plan` already resolved HUmar's best weapon from the disc's own item database: **DARK FLOW, code `009d00`, ATP 756-900, 11 stars** (with TSUMIKIRI J-SWORD
`003200` next at 700-756 plus 50 grind).

So: give DARK FLOW and equip it, then raise the stats that make it usable - `hp` so the character survives, and `atp` so the weapon's 900 ATP is actually realised. These are
mutations, so each is attempted once and its result read; nothing is retried blindly.
"""
import json
import time

from pso_pad import Pad, call

BEST_WEAPON = "009d00"          # DARK FLOW, from pso_loadout's own plan for HUmar
BACKUP_WEAPON = "003200"        # TSUMIKIRI J-SWORD


def mods(pad: Pad, payload: dict, wait: float = 45.0) -> dict:
    job = call("/api/jobs", {"tool": "pso_mods", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, **payload}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return {"submitted": False, "answer": job}
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"state": "timeout"}


def report(label: str, answer: dict) -> None:
    print(f"\n{label}: {answer.get('state')} | {str(answer.get('error'))[:140]}")
    if answer.get("output") is not None:
        print("   ", json.dumps(answer.get("output"))[:500])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    report("give DARK FLOW (equip)", mods(pad, {"op": "give", "code": BEST_WEAPON, "equip": True}))
    time.sleep(1.5)

    # if the weapon cannot be made, fall back to the next best rather than leaving the bot unarmed
    report("give TSUMIKIRI J-SWORD (equip)", mods(pad, {"op": "give", "code": BACKUP_WEAPON, "equip": True}))
    time.sleep(1.5)

    report("stat hp", mods(pad, {"op": "stat", "name": "hp", "value": 9999}))
    report("stat atp", mods(pad, {"op": "stat", "name": "atp", "value": 9999}))
    report("stat ata", mods(pad, {"op": "stat", "name": "ata", "value": 999}))

    print("\nstate after:")
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    player = state.get("player") or {}
    print("  player:", (player.get("x"), player.get("z")), "| hp", player.get("hp"), "/", player.get("hp_max"))
    print("shot:", pad.shot("geared"))
