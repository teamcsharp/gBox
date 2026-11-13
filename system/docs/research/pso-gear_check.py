"""Find the strongest weapons and see what the character is actually carrying.

The operator's requirement is explicit: *"the bot must have the best weapons and fight properly"*, and it is the gate on Ultimate, because PSO only offers Ultimate at level 80 while
BQF is level 5 with 68 HP.

The app already carries the machinery:

* `pso_item_search` - the item catalog read from the game disc, names -> item codes, all weapons;
* `pso_inventory` - op=list and op=equip with an item code;
* `pso_drops` - op=scale to raise what enemies drop.

This asks the catalog for the top weapons and lists the character's inventory, so the next step (equipping) is based on real codes rather than guesses.
"""
import json
import time

from pso_pad import Pad, call


def run(pad: Pad, tool: str, payload: dict, wait: float = 40.0) -> dict:
    job = call("/api/jobs", {"tool": tool, "require_worker": pad.worker,
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


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    print("\n=== current inventory ===")
    answer = run(pad, "pso_inventory", {"op": "list"}, wait=45)
    print(json.dumps(answer)[:1200])

    print("\n=== strongest weapons in the disc catalog ===")
    for query in ("sword", "saber", "partisan", "rifle", "mechgun"):
        answer = run(pad, "pso_item_search", {"op": "search", "query": query, "limit": 6}, wait=45)
        text = json.dumps(answer)
        print(f"  {query}: {text[:220]}")
        if answer.get("state") == "succeeded":
            break
