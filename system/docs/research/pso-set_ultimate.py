"""Persist the operator's PSO entry (Episode 1, Ultimate) where the app actually reads it, and look at the level gate.

The screenshot shows **Ep 1 / Ultimate** selected in the sidebar, but `pso-launch-config.json` - the file `pso_launch_config` defines (line 21) and `pso_coop` reads - **does not
exist**, and the game's difficulty global `0x805D5550` reads **0 = Normal**. So the selection was never reaching the game.

The shape is taken from the module's own `normalize()` return (lines 48-50), so the fields match what a reader expects rather than being invented.

**The gate that matters**: PSO GameCube only offers **Ultimate at level 80** (Hard 20, Very Hard 40, Ultimate 80). The character BQF is **level 5**. Writing the difficulty
global is attempted, but the honest expectation is that the game will not honour it while the character is that low - which is exactly why the operator says the bot "must have
the best weapons and fight properly": the route to Ultimate is power, and the app has machinery for that (`psoitems`, `pso_loadouts`, `pso_control`).
"""
import json
import pathlib
import time

CONFIG = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\pso-launch-config.json")
DIFFICULTY_ADDR = 0x805D5550

if __name__ == "__main__":
    from pso_pad import Pad, call

    entry = {
        "episode": 1,
        "episode_label": "Episode 1",
        "difficulty": "ultimate",
        "difficulty_index": 3,
        "difficulty_label": "Ultimate",
        "requested_difficulty_input": "Ultimate",
        "legendary": False,
        "saved": time.time(),
        "by": "operator-sidebar (persisted by the harness)",
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(entry, indent=1), encoding="utf-8")
    print("wrote", CONFIG, "->", json.dumps(entry)[:200])

    pad = Pad()
    print("\nsession:", pad.sid)

    def read(address, length):
        raw = call("/api/sessions/%s/rpc" % pad.sid,
                   {"op": "read_memory", "args": {"address": address, "length": length}}, "POST")
        try:
            return bytes.fromhex(raw)
        except Exception:                                          # noqa: BLE001
            return b""

    before = read(DIFFICULTY_ADDR, 4)
    print("difficulty before:", int.from_bytes(before, "big") if len(before) == 4 else None)

    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": DIFFICULTY_ADDR,
                                       "hex_bytes": "00000003"}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(1)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("write:", row.get("state"), str(row.get("error"))[:100])
            break

    time.sleep(2)
    after = read(DIFFICULTY_ADDR, 4)
    print("difficulty after:", int.from_bytes(after, "big") if len(after) == 4 else None,
          "  (3 = ultimate)")
    print("\nnote: the game sets this global itself when a game starts, so a value written while a floor is")
    print("already in play is likely to be overwritten on the next entry - and PSO gates Ultimate at level 80.")
