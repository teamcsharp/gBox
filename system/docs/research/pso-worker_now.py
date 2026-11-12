"""Report whether the respawned worker registers, with its heartbeat age."""
import time

from pso_pad import call

if __name__ == "__main__":
    for index in range(10):
        rows = call("/api/workers")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        for row in rows:
            age = round(time.time() - (row.get("last_seen") or 0), 1)
            print("  %3ds: %s online=%s last_seen_age=%ss"
                  % (index * 5, row.get("name"), row.get("online"), age))
        if any(row.get("online") for row in rows):
            print("\nWORKER ONLINE")
            break
        time.sleep(5)
    else:
        print("\nstill offline")
