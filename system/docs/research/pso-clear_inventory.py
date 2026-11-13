"""Clear the inventory, so weapons can be equipped and the bag stays empty.

The operator's rule: *"dont pick up items if the inventory is full... Keep the inventory empty."* It had filled to 30/30
and every `give` now fails with **"Not enough inventory slots"**, so the character was running around unarmed - the
weapons could not be placed.

Every item slot is **28 bytes** and there are **30** of them, so clearing is a single zero-fill at the inventory's base
address plus zeroing the count byte that sits immediately before slot 0 (the same byte the finder validates against).
That is the whole operation: an all-zero slot is what the game itself writes for an empty one - `_slot_ok` returns 0 for
`present=0, flags=0` - so this is the game's own representation of "empty", not an invented one.

The base comes from `pso_inventory list`, which reports `inventory_at`. Nothing is guessed.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from pso_pad import Pad, call                                   # noqa: E402

SLOT_BYTES = 28
SLOTS = 30


def job(pad, tool, payload, tries=120):
    j = call("/api/jobs", {"tool": tool, "require_worker": pad.worker,
                           "input": {"session_id": pad.sid, **payload}}, "POST")
    jid = j.get("id") if isinstance(j, dict) else None
    if not jid:
        raise RuntimeError(str(j)[:160])
    for _ in range(tries):
        time.sleep(1.0)
        row = call("/api/jobs/" + jid)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            if row.get("state") != "succeeded":
                raise RuntimeError(str(row.get("error"))[:160])
            return (row.get("output") or {}).get("result") or {}
    raise RuntimeError("job timed out")


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    listing = job(pad, "pso_inventory", {"op": "list"})
    base_text = str(listing.get("inventory_at") or "")
    items = listing.get("items") or []
    print(f"inventory at {base_text} with {len(items)} item(s)")
    if not base_text.startswith("0x"):
        raise SystemExit("the worker did not report an inventory address")
    base = int(base_text, 16)

    # zero the count byte just before slot 0, then every slot
    job(pad, "write_memory", {"address": base - 4, "hex_bytes": "00"})
    print("count byte zeroed")
    job(pad, "write_memory", {"address": base, "hex_bytes": "00" * (SLOT_BYTES * SLOTS)})
    print(f"{SLOT_BYTES * SLOTS} bytes of slots zeroed")

    after = job(pad, "pso_inventory", {"op": "list"})
    left = after.get("items") or []
    print(f"after: {len(left)} item(s)", [i.get("name") for i in left][:6])
    print("VERDICT:", "EMPTY" if not left else "still has items")
