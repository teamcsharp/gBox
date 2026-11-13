"""pso_pad - drive PSO's menus and gameplay from the control plane, and see the result.

The app's own autoplay does it this way, which is why this is the shape that works:

```python
def keys(self, keys, down):
    self.api.post(f"/api/sessions/{self.sid}/input", json={"events": [{"key": k, "down": down} for k in keys]})

def hold(self, keys, secs):
    self.keys(keys, True); time.sleep(secs); self.keys(keys, False)

def press(self, key, n=1, gap=0.35):
    for _ in range(n):
        self.hold([key], 0.12); time.sleep(gap)
```

`/input` did nothing for the whole session because no virtual pad existed; now `GBOX_DOLPHIN_VPAD=on` and slot 0 is a real pad, so the operator-facing route works and is
far quicker than one job per event.

Frames come from `GET /api/sessions/{sid}/mjpeg` (the viewer stream, one multipart part = one JPEG), so every action can be checked on screen.
"""
from __future__ import annotations

import pathlib
import json
import time
import urllib.request
from pathlib import Path

TOKEN_PATH = Path(r"C:\_tools\gBox\system\gbox-data\api_token")
BASE = "http://127.0.0.1:18765"
SHOTS = Path(r"D:\gBox\pso-ds\shots")

PLAYER = 0x8050EA10
FLOOR = 0x805D5FC0


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path: str, payload=None, method: str = "GET", timeout: float = 60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:200].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__}


def session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise RuntimeError("no live session")
    return live[0]["session_id"]


OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
OPERATOR_FRESH_S = 15.0


def operator_active() -> bool:
    """True when the operator's controller relay has touched the pad in the last 15 seconds."""
    try:
        if not OPERATOR_FLAG.exists():
            return False
        return (time.time() - OPERATOR_FLAG.stat().st_mtime) < OPERATOR_FRESH_S
    except OSError:
        return False


def yield_to_operator(max_wait: float = 3.0) -> None:
    """Wait while the operator is playing, so two writers never interleave inside one held press."""
    deadline = time.time() + max_wait
    while operator_active() and time.time() < deadline:
        time.sleep(0.05)


class Pad:
    """The pad of one session: press keys, read the screen, read the player."""

    def __init__(self, sid: str = "") -> None:
        self.sid = sid or session()
        self.worker = self.sid.split("-")[0]
        SHOTS.mkdir(parents=True, exist_ok=True)

    # ---- input ---------------------------------------------------------------------------------------------------
    def keys(self, keys: list[str], down: bool) -> dict:
        return call("/api/sessions/%s/input" % self.sid,
                    {"events": [{"key": key, "down": down} for key in keys]}, "POST", timeout=25)

    def send(self, events: list[dict]) -> str:
        """Push events through the adapter (`session_op` `send_input`), which is the path that reaches the game.

        `/api/sessions/{sid}/input` did **not** move the screen while this did: START opened the main menu with it. The reliable shape is **one job carrying the
        down and the up together** - the presses that failed were split across two jobs, where the hold depended on job latency and a missed release left the pad held.
        """
        job = call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "op": "send_input",
                                           "args": {"events": events}}}, "POST", timeout=30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return "rejected: " + json.dumps(job)[:120]
        # A job can take longer than a few seconds when the worker is busy, and a short window reports a false "timeout"
        # for a press that actually landed - which then makes the caller re-press and walk the menus past their target.
        for _ in range(90):
            time.sleep(0.5)
            row = call("/api/jobs/" + job_id)
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                return str(row.get("state")) + ("" if row.get("state") == "succeeded"
                                                else ": " + str(row.get("error"))[:80])
        return "timeout"

    def hold(self, keys: list[str], secs: float) -> None:
        self.keys(keys, True)
        time.sleep(secs)
        self.keys(keys, False)

    def press(self, key: str, n: int = 1, gap: float = 0.45, hold: float = 0.0) -> None:
        """One job per press, carrying down and up together."""
        for _ in range(n):
            self.send([{"key": key, "down": True}, {"key": key, "down": False}])
            time.sleep(gap)

    def seq(self, keys: list[str], gap: float = 0.45, hold: float = 0.0) -> None:
        """Press several keys in order, e.g. seq(["down", "a"])."""
        for key in keys:
            self.press(key, gap=gap, hold=hold)

    # ---- verified input: the screen is the oracle ---------------------------------------------------------------
    def digest(self) -> str:
        import hashlib
        return hashlib.sha256(self.frame()).hexdigest()

    def tap_until_changed(self, keys: list[str], tries: int = 5, settle: float = 1.1,
                          wait: float = 0.8) -> tuple:
        """Press keys until the screen changes, retrying with each key in turn.

        Presses are not reliable one-shot: the same A press activated a highlighted option once and did nothing the next time, because each press is a single job whose
        events the emulator may consume within one frame. So the screen decides - press, wait, look, and try again (or with the next key) if nothing moved.

        Returns (changed, key_used, tries).
        """
        before = self.digest()
        for attempt in range(1, tries + 1):
            key = keys[(attempt - 1) % len(keys)]
            self.press(key, gap=wait, hold=0.0)
            time.sleep(settle)
            if self.digest() != before:
                return True, key, attempt
        return False, "", tries

    def confirm(self, tries: int = 6) -> bool:
        """Activate the highlighted option: **A only**.

        START is deliberately not used as a fallback here: in PSO, A confirms and START *toggles the pause menu*, so retrying with START closes the very menu the
        press was meant to advance and drops the bot back to the title. Measured: a DOWN+A chain into OFFLINE GAME ended on "PRESS START" because of exactly that.
        """
        return self.tap_until_changed(["a"], tries=tries)[0]

    def move(self, direction: str, tries: int = 4, settle: float = 0.9) -> bool:
        """Move the cursor: press the direction until the screen changes."""
        return self.tap_until_changed([direction], tries=tries, settle=settle)[0]

    # ---- observation ---------------------------------------------------------------------------------------------
    def frame(self) -> bytes:
        request = urllib.request.Request(
            BASE + "/api/sessions/%s/mjpeg?fps=2" % self.sid,
            headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent"})
        response = urllib.request.urlopen(request, timeout=25)
        buffer = b""
        try:
            for _ in range(90):
                chunk = response.read(32768)
                if not chunk:
                    break
                buffer += chunk
                start = buffer.find(b"\xff\xd8")
                if start >= 0:
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end > start:
                        return buffer[start:end + 2]
        finally:
            response.close()
        return b""

    def shot(self, name: str) -> str:
        body = self.frame()
        path = SHOTS / (name if name.endswith(".jpg") else name + ".jpg")
        path.write_bytes(body)
        return str(path)

    def read(self, address: int, length: int) -> bytes:
        raw = call("/api/sessions/%s/rpc" % self.sid,
                   {"op": "read_memory", "args": {"address": address, "length": length}}, "POST")
        try:
            return bytes.fromhex(raw)
        except Exception:                                          # noqa: BLE001
            return b""

    def player_pointer(self) -> int | None:
        body = self.read(PLAYER, 4)
        pointer = int.from_bytes(body, "big") if len(body) == 4 else 0
        return pointer if 0x80000000 <= pointer < 0x81800000 else None

    def floor(self) -> int | None:
        body = self.read(FLOOR, 4)
        return int.from_bytes(body, "big") if len(body) == 4 else None

    def status(self) -> dict:
        return {"floor": self.floor(), "player": self.player_pointer()}


if __name__ == "__main__":
    import hashlib

    pad = Pad()
    print("session:", pad.sid)
    print("status:", pad.status())

    before = pad.shot("probe_before")
    digest = hashlib.sha256(Path(before).read_bytes()).hexdigest()[:12]
    print("before:", before, digest)

    pad.press("down")
    time.sleep(0.6)
    after = pad.shot("probe_after")
    digest_after = hashlib.sha256(Path(after).read_bytes()).hexdigest()[:12]
    print("after :", after, digest_after)
    print("changed:", digest != digest_after)
