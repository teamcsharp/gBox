"""Equip the right weapon class for the room: the gun for fliers, the sword for the ground.

The operator stated both rules and both are now implementable, because `equip` can find the inventory:

* *"for these bug enemies, I would equip a gun or pistol or launcher and blast them because they are flying pissants"*
  - and it is not advice, it is a necessity: `TObjEneBm3Fly` took **zero damage from twelve melee swings at 6.2
  units** because it is airborne and the melee arc does not reach it;
* *"weapon equipped changing every 2-5 minutes"* - a strict timer.

`choose_weapon()` combines them without fighting:

1. **A flier or a nest is present and in the room** -> the ranged weapon must be active. This outranks the timer,
   because the alternative is not "a suboptimal weapon" but **an enemy that cannot be damaged at all**.
2. **Otherwise the timer decides** - every `SWAP_SECONDS` the equipped weapon rotates to the next in the rotation,
   so variety happens on schedule and combat is not interrupted mid-fight.

`ensure_equipped()` performs the swap through `pso_inventory equip`, which the inventory fix made reachable, and
verifies by reading the inventory back. Failures are logged and non-fatal: a weapon swap must never stop the loop.
"""
import time

GUN_CODE = "004400"          # RED HANDGUN, given last at arming so it is the default equipped weapon
MELEE_CODES = ("009d00", "003200")   # DARK FLOW, J-SWORD
ROTATION = (GUN_CODE,) + MELEE_CODES
SWAP_SECONDS = 150.0         # the operator's 2-5 minute window, taken at 2.5
FAIL_BACKOFF_S = 90.0        # after a failed swap, wait this long instead of retrying every iteration

LAST_SWAP = {"at": 0.0, "index": 0, "code": GUN_CODE, "failed_at": 0.0}


def is_flier(entity) -> bool:
    """True for the airborne classes: flies and their nests."""
    name = str(entity.get("class") or "")
    return "Fly" in name or "Nest" in name


def fliers_present(entities) -> bool:
    return any(is_flier(e) and float(e.get("hp") or 0) > 0 for e in (entities or []))


def choose_weapon(entities, now=None) -> str | None:
    """Weapon code that should be equipped now, or None if the current one is fine."""
    now = time.time() if now is None else now
    # A swap that just failed is deferred rather than hammered: the log was filling with the same error every
    # fifteen seconds and each retry cost a worker round-trip.
    if now - float(LAST_SWAP.get("failed_at") or 0.0) < FAIL_BACKOFF_S:
        return None
    if fliers_present(entities):
        # A flier outranks the timer: melee literally cannot damage it.
        return GUN_CODE if LAST_SWAP.get("code") != GUN_CODE else None
    if now - float(LAST_SWAP.get("at") or 0.0) >= SWAP_SECONDS:
        index = (int(LAST_SWAP.get("index") or 0) + 1) % len(ROTATION)
        return ROTATION[index]
    return None


def ensure_equipped(pad, entities, log=None) -> bool:
    """Swap the equipped weapon if the room or the timer calls for it. Never raises."""
    wanted = choose_weapon(entities)
    if not wanted:
        return False
    try:
        from pso_pad import call
        job = call("/api/jobs", {"tool": "pso_inventory", "require_worker": pad.worker,
                                 "input": {"session_id": pad.sid, "op": "equip", "code": wanted}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return False
        for _ in range(20):
            time.sleep(1.0)
            row = call("/api/jobs/" + job_id)
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                ok = row.get("state") == "succeeded"
                if ok:
                    LAST_SWAP["code"] = wanted
                    LAST_SWAP["at"] = time.time()
                    LAST_SWAP["failed_at"] = 0.0
                    LAST_SWAP["index"] = ROTATION.index(wanted) if wanted in ROTATION else 0
                else:
                    LAST_SWAP["failed_at"] = time.time()
                if log:
                    log(f"  weapon: {'equipped ' + wanted if ok else 'equip failed ' + wanted}"
                        f"{'' if ok else ' - ' + str(row.get('error'))[:60]}")
                return ok
    except Exception as error:                                  # noqa: BLE001 - a swap must never stop the loop
        if log:
            log(f"  weapon: equip error {type(error).__name__}")
    return False
