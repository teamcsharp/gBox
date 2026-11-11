import json
import urllib.request


def place(payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request("http://127.0.0.1:8801/api/place", data=body, method="POST",
                                     headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=90) as reply:
            return json.loads(reply.read())
    except Exception as exc:                                        # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:140]}"}


print("--- place inside a room (record 3 cloned at -300,400 on floor 1) ---")
print(json.dumps(place({"floor": 1, "record": 3, "x": -300, "y": 0, "z": 400}), indent=1)[:500])
print()
print("--- place in the void (should be refused) ---")
print(json.dumps(place({"floor": 1, "record": 3, "x": 1082, "y": 0, "z": 1030}), indent=1)[:300])
