"""Run each remaining mutating op individually and report which ones throw, so the verifier's crash can be fixed."""
import sys
import traceback

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import gc_mod_matrix as M                                          # noqa: E402

OPS = ("pb", "survival", "walk_through", "always_hit", "equip_any", "autoplay_speed", "stat", "equip", "give", "multi_equip",
       "discard", "legendary", "enemy_drops")

for op in OPS:
    try:
        row = M.run(op, gate=False)
        detail = str(row.get("detail"))
        print(op.ljust(16), row["classification"].ljust(12), detail[:150], flush=True)
    except Exception:                                            # noqa: BLE001
        print(op.ljust(16), "EXCEPTION", flush=True)
        traceback.print_exc(limit=2)
