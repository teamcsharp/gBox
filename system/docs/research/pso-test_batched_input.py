"""Verify the batched input builds the right job payloads, without a game.

Rounds 24-25 changed how input is delivered, and the change is exactly the kind that fails silently: a `tap` that sends the wrong event order, a `move` that
drops a key, or a cap that never releases would all look like "the bot stopped moving". This checks the payloads directly by replacing the plane call with a
recorder:

  * `tap(k)` -> one job holding `[{k, down}, {k, up}]`, in that order;
  * `move(a, b)` -> one job holding `a` down/up then `b` down/up;
  * `send` -> exactly one job per call, with the rows it was given;
  * the in-flight counter returns to zero after a success and after a failure;
  * `MAX_IN_FLIGHT` is a small number, because its job is to stop a queue forming.

A wrong order (up before down) would produce a press the emulator never sees; a leaked counter would stall the bot at the cap forever. Both are checked.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (" - " + detail if detail else ""))
    if not condition:
        failures.append(label)


class Recorder:
    """Stands in for the plane: records submitted payloads and answers a fixed job state."""

    def __init__(self, final_state="succeeded"):
        self.payloads = []
        self.final_state = final_state

    def __call__(self, path, method="GET", body=None, timeout=None):     # noqa: ANN001
        if path == "/api/jobs" and method == "POST":
            self.payloads.append(body)
            return {"id": f"job-{len(self.payloads)}", "state": "queued"}
        if path.startswith("/api/jobs/job-"):
            return {"state": self.final_state}
        return {}


class FakeSession:
    def __init__(self, recorder):
        self.recorder = recorder

    def _call(self, path, method="GET", body=None, timeout=None):        # noqa: ANN001
        return self.recorder(path, method, body, timeout)

    def session_id(self):
        return "abc123def456-00aa"


def install(final_state="succeeded"):
    recorder = Recorder(final_state)
    import session as real_session
    rec = FakeSession(recorder)
    real_session.session_id = rec.session_id
    real_session._call = rec._call
    return recorder


def events_of(payload):
    return payload["input"]["args"]["events"]


if __name__ == "__main__":
    print("cap:", G.MAX_IN_FLIGHT)
    check("the cap is small enough to prevent a queue", 1 <= G.MAX_IN_FLIGHT <= 8, str(G.MAX_IN_FLIGHT))

    recorder = install()
    G.tap("up")
    payloads = recorder.payloads
    check("tap submits exactly one job", len(payloads) == 1, str(len(payloads)))
    if payloads:
        rows = events_of(payloads[0])
        check("tap sends two events", len(rows) == 2, str(len(rows)))
        check("tap presses before releasing",
              len(rows) == 2 and rows[0].get("down") is True and rows[1].get("down") is False,
              str(rows))
        check("tap names the key", all(row.get("key") == "up" for row in rows), str(rows[0]))

    recorder = install()
    G.move("up", "up", "a")
    rows = events_of(recorder.payloads[0]) if recorder.payloads else []
    check("move submits one job for three taps", len(recorder.payloads) == 1, str(len(recorder.payloads)))
    check("move sends six events", len(rows) == 6, str(len(rows)))
    check("move keeps the tap order (each key down+up in sequence)",
          [row.get("key") for row in rows] == ["up", "up", "up", "up", "a", "a"],
          str([row.get("key") for row in rows]))
    check("move alternates down and up",
          [row.get("down") for row in rows] == [True, False, True, False, True, False],
          str([row.get("down") for row in rows]))

    recorder = install()
    before = G._IN_FLIGHT["jobs"]
    G.tap("a")
    check("the in-flight counter is released after success", G._IN_FLIGHT["jobs"] == before,
          f"{before} -> {G._IN_FLIGHT['jobs']}")

    recorder = install(final_state="failed")
    before = G._IN_FLIGHT["jobs"]
    ok = G.tap("a")
    check("a failed job reports False", ok is False, str(ok))
    check("the in-flight counter is released after failure", G._IN_FLIGHT["jobs"] == before,
          f"{before} -> {G._IN_FLIGHT['jobs']}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("all batched-input checks passed")
