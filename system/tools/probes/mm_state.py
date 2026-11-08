"""Print the lilspark MercMode host row from a saved /api/mercmode response.

Between rounds this is the one thing that must be left correct: the operator wants the rotation playing. The probe reads a file rather
than a URL so it can be run against a capture taken at any moment.
"""
import json
import sys


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mm.json"
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {path}: {exc}")
        return 1
    hosts = data.get("hosts") or []
    if not hosts:
        print("no hosts in the response")
        return 1
    for host in hosts:
        if host.get("name") != "lilspark":
            continue
        run = host.get("current_run") or {}
        print("enabled:", host.get("enabled"))
        print("phase:", run.get("phase"), "| title:", run.get("title"), "| rounds:", run.get("mercmode_rounds"))
        print("session:", str(run.get("session_id"))[:40])
        note = host.get("scheduler_note") or ""
        if note:
            print("scheduler:", str(note)[:100])
        return 0
    print("lilspark is not in the host list")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
