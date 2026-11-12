"""Break the memory-card lease deadlock that is stopping every launch.

`memory_cards.lease` refuses a card when:

```python
active = (session or {}).get('state') == 'running' or (job or {}).get('state') in ('queued', 'running')
if (active or time.time() - old['updated'] < 90) and not demo:
    raise HTTPException(409, 'This card is already inserted in another session...')
```

So a lease is kept alive by **either** a running session **or a queued/running job**. A launch that sat in the queue therefore holds its own card lease, and because
that job is `queued`, **every subsequent launch is refused with the same 409** - a deadlock that looks exactly like "PSO won't launch".

The sequence in the job list shows it happening: an 08:41 launch succeeded, then 09:14 failed for the card, 09:19 was cancelled, and 09:21 is queued again.

This cancels the queued launch and releases each card's lease using the owner it already names, then reports the cards so the release is visible rather than assumed.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, payload=None, method="GET", timeout=40):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:220].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:140]}


if __name__ == "__main__":
    print("=== cancel queued launches ===")
    queued = call("/api/jobs?state=queued,running")
    queued = queued if isinstance(queued, list) else (queued.get("items") or [])
    for job in queued:
        answer = call(f"/api/jobs/{job['id']}/cancel", {}, "POST")
        print(f"  cancel {job['id']} ({job.get('tool')}): {json.dumps(answer)[:120]}")

    print("\n=== memory cards and their leases ===")
    cards = call("/api/memory-cards")
    cards = cards if isinstance(cards, list) else (cards.get("items") or [])
    print("cards:", len(cards))
    released = 0
    for card in cards:
        lease = card.get("lease") or None
        cid = card.get("id") or card.get("card_id")
        print(f"  {cid} | platform {card.get('platform')} | lease: "
              f"{json.dumps(lease)[:120] if lease else 'none'}")
        if not lease:
            continue
        owner = lease.get("session_id") or lease.get("owner")
        worker = lease.get("worker_id")
        if not owner:
            print("    lease has no owner - cannot release through the API")
            continue
        answer = call(f"/api/memory-cards/{cid}/release", {"owner": owner, "worker_id": worker}, "POST")
        ok = isinstance(answer, dict) and "err" not in answer
        print(f"    release as {owner}: {'ok' if ok else json.dumps(answer)[:140]}")
        if ok:
            released += 1

    print(f"\nreleased {released} lease(s)")
    cards = call("/api/memory-cards")
    cards = cards if isinstance(cards, list) else (cards.get("items") or [])
    free = [card.get("id") or card.get("card_id") for card in cards if not card.get("lease")]
    print(f"cards now free: {len(free)} of {len(cards)} -> {free}")
