"""CP4/CP5: drive a live PSO session on the i9's own plane - launch, read RAM, press the pad, save/jump a state.

The pieces all exist (`gbox.pso_boot_walk` walks the menus, `pso_ram` knows the addresses, `jumpstate` boots a state);
this is the driver that binds them to the plane over HTTP:

    python system/tools/pso_boot.py launch                 # stock game, no jump
    python system/tools/pso_boot.py walk                   # the MULTI MODE boot script, RAM-checked
    python system/tools/pso_boot.py state                  # what the walk asserts on
    python system/tools/pso_boot.py save-state             # Dolphin slot 1, printed path
    python system/tools/pso_boot.py install-jumpstates     # copy it to jumpstates/<gid>-<build>.state
    python system/tools/pso_boot.py launch-jump --mod pso_guilddoor_moved

Every call carries `x-gbox-actor: agent`; the token is read from `system/gbox-data/api_token` and never printed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
BASE = "http://127.0.0.1:8765"
GAME_ID = "436e0bb84d5337d1"
JUMPSTATES = pathlib.Path(r"D:\gBox\runtime\jumpstates")


class Plane:
    def __init__(self, base: str = BASE):
        self.base = base.rstrip("/")
        self.token = TOKEN.read_text(encoding="utf-8").strip()

    def call(self, method: str, path: str, body: dict | None = None, *, timeout: float = 120.0):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "authorization": f"Bearer {self.token}", "x-gbox-actor": "agent", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path}: HTTP {error.code} {error.read()[:300]!r}") from None
        return json.loads(raw) if raw else {}

    # -- reads -----------------------------------------------------------------------------------------------------
    def sessions(self) -> list[dict]:
        data = self.call("GET", "/api/sessions?include_ended=false")
        return data if isinstance(data, list) else data.get("sessions") or []

    def running(self) -> dict | None:
        rows = self.sessions()
        return rows[0] if rows else None

    def catalog(self, gid: str = GAME_ID) -> dict:
        return self.call("GET", f"/api/catalog/{gid}")

    def rpc(self, sid: str, op: str, args: dict | None = None) -> dict:
        return self.call("POST", f"/api/sessions/{sid}/rpc", {"op": op, "args": args or {}})

    def read_memory(self, sid: str, address: int, length: int) -> bytes:
        out = self.rpc(sid, "read_memory", {"address": address, "length": length})
        if isinstance(out, dict):
            out = out.get("data") or out.get("bytes") or out.get("result") or b""
        if isinstance(out, str):
            out = bytes.fromhex(out)
        return bytes(out)

    def press(self, sid: str, keys, *, frames: int = 2) -> dict:
        events = [{"key": k, "frames": frames} for k in (keys if isinstance(keys, (list, tuple)) else [keys])]
        return self.call("POST", f"/api/sessions/{sid}/input", {"events": events})

    # -- jobs ------------------------------------------------------------------------------------------------------
    def job(self, tool: str, inp: dict) -> str:
        out = self.call("POST", "/api/jobs", {"tool": tool, "input": inp})
        return out.get("id") or out.get("job_id")

    def wait(self, jid: str, *, timeout: float = 180.0, every: float = 1.5) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.call("GET", f"/api/jobs/{jid}")
            if st.get("state") in ("succeeded", "failed", "cancelled"):
                return st
            time.sleep(every)
        return {"state": "timeout", "id": jid}

    def launch(self, *, mod: str = "", jump: bool = False, timeout: float = 240.0) -> tuple[str, dict]:
        game = self.catalog()
        inp = {"game": game, "pso_coop": False, "debug": True, "mod": mod, "mod_title": "",
               "jump": bool(jump), "boot_timeout_s": None}
        jid = self.job("launch_game", inp)
        st = self.wait(jid, timeout=timeout)
        sid = (st.get("output") or {}).get("session_id") or (st.get("output") or {}).get("session") or ""
        return sid, st


class Reader:
    """`pso_boot_walk`'s reader: the handful of reads `pso_ram` needs, over the plane's read_memory."""

    def __init__(self, plane: Plane, sid: str, *, chunk: int = 16):
        self.plane, self.sid, self.chunk = plane, sid, chunk

    def bytes(self, address: int, length: int) -> bytes:
        return self.plane.read_memory(self.sid, address, length)

    def read(self, address: int, length: int) -> bytes:
        # pso_ram's reader protocol is reader.read(addr, n); pso_boot_walk.state() goes through it.
        return self.bytes(address, length)

    def u8(self, address: int) -> int:
        data = self.bytes(address, 1)
        return data[0] if data else 0

    def u16(self, address: int) -> int:
        data = self.bytes(address, 2)
        return int.from_bytes(data, "big") if len(data) == 2 else 0

    def u32(self, address: int) -> int:
        data = self.bytes(address, 4)
        return int.from_bytes(data, "big") if len(data) == 4 else 0

    def f32(self, address: int) -> float:
        import struct
        data = self.bytes(address, 4)
        return struct.unpack(">f", data)[0] if len(data) == 4 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["launch", "walk", "state", "save-state", "install-jumpstates",
                                        "launch-jump", "stop"])
    ap.add_argument("--mod", default="")
    ap.add_argument("--build", default="stock")
    ap.add_argument("--settle", type=float, default=1.6)
    args = ap.parse_args()
    plane = Plane()
    sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
    from gbox import pso_boot_walk, pso_ram

    if args.command == "launch":
        sid, st = plane.launch(mod=args.mod)
        print(json.dumps({"session_id": sid, "job_state": st.get("state"), "mod": args.mod}, indent=1))
        return 0 if sid else 1
    if args.command == "launch-jump":
        sid, st = plane.launch(mod=args.mod, jump=True)
        print(json.dumps({"session_id": sid, "job_state": st.get("state"), "jump": True}, indent=1))
        return 0 if sid else 1
    if args.command == "stop":
        sess = plane.running()
        if not sess:
            print("no running session")
            return 0
        jid = plane.job("session_op", {"session_id": sess["session_id"], "op": "stop_game"})
        print(json.dumps(plane.wait(jid), indent=1))
        return 0
    sess = plane.running()
    if not sess:
        raise SystemExit("no running session")
    sid = sess["session_id"]
    reader = Reader(plane, sid)
    if args.command == "state":
        print(json.dumps(pso_boot_walk.state(reader), indent=1))
        return 0
    if args.command == "walk":
        result = pso_boot_walk.walk(lambda: pso_boot_walk.state(reader), lambda keys: plane.press(sid, keys),
                                    settle=args.settle, log=print)
        print(json.dumps({"ok": result["ok"], "arrived": result["arrived"], "why": result["why"]}, indent=1))
        return 0 if result["arrived"] else 1
    if args.command == "save-state":
        jid = plane.job("session_op", {"session_id": sid, "op": "save_state", "args": {"slot": 1}})
        print(json.dumps(plane.wait(jid, timeout=180), indent=1))
        return 0
    if args.command == "install-jumpstates":
        JUMPSTATES.mkdir(parents=True, exist_ok=True)
        src = pathlib.Path(sys.argv[-1])
        dst = JUMPSTATES / f"{GAME_ID}-{args.build}.state"
        dst.write_bytes(src.read_bytes())
        import hashlib
        print(json.dumps({"wrote": str(dst), "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
                          "bytes": dst.stat().st_size}, indent=1))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
