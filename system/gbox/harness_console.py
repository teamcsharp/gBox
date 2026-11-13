"""The game-hooked console: emulator log, MercMode state and freeze reports on one PiP feed.

The PiP already shows what the game draws. This module supplies the other half: the emulator's own console, the
session's applied build and validation state, and a place for the browser to file a freeze report with the exact frame
witness. It is deliberately read-mostly: reports are written to `<data>/harness/`, never into a game, a build or a
session record.

The browser half is clients/web/viz/pip-harness-console.js; it polls `/api/sessions/{sid}/harness/console` alongside the
job console and can POST `/harness/freeze` when the frame stops changing.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, HTTPException


class HarnessConsole:
    """Per-session console lines and freeze reports, process-local and bounded."""

    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.lock = threading.RLock()
        self.lines: deque[dict] = deque(maxlen=4000)
        self.seq = 0
        self.offsets: dict[tuple[str, str], int] = {}
        self.partial: dict[tuple[str, str], bytes] = {}
        self.last: dict[str, dict] = {}
        self.ghidra = {"checked": False, "status": "not checked", "reason": ""}
        self.root = Path(getattr(config, "data_dir", Path("."))) / "harness"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    # -- lines -----------------------------------------------------------------------------------------------------
    def add(self, source: str, text: str, session: str = "") -> None:
        text = str(text or "").rstrip()
        if not text:
            return
        with self.lock:
            self.seq += 1
            self.lines.append({"seq": self.seq, "at": time.time(), "source": source, "session": session,
                               "text": text})

    def _session(self, sid: str) -> dict:
        row = self.store.get("session", sid) or {}
        return row

    def _emulator(self, sid: str, session: dict) -> None:
        detail = session.get("detail") or {}
        path = str(detail.get("log") or detail.get("eden_log") or "")
        if not path:
            return
        file = Path(path)
        try:
            size = file.stat().st_size
        except OSError:
            return
        key = (sid, path)
        start = self.offsets.get(key, max(0, size - 64 * 1024))
        if size < start:                       # rotated or truncated: start from the new tail
            start = max(0, size - 64 * 1024)
        if size == start:
            return
        try:
            with file.open("rb") as handle:
                handle.seek(start)
                chunk = handle.read(min(size - start, 512 * 1024))
        except OSError:
            return
        self.offsets[key] = start + len(chunk)
        pending = self.partial.get(key, b"") + chunk
        parts = pending.split(b"\n")
        self.partial[key] = parts.pop() if parts else b""
        for raw in parts[-600:]:
            line = raw.decode("utf-8", "replace").rstrip("\r")
            if line:
                self.add("game", line, sid)

    def _state(self, sid: str, session: dict) -> None:
        detail = session.get("detail") or {}
        view = {
            "validation": session.get("validation") or detail.get("validation") or "",
            "build": ((detail.get("overlay") or {}).get("build") or session.get("mod") or ""),
            "mod": session.get("mod") or "",
            "autoplay_job": detail.get("autoplay_job") or "",
        }
        old = self.last.get(sid) or {}
        for key, value in view.items():
            if value and value != old.get(key):
                self.add("runtime", f"{key}: {value}", sid)
        autoplay = str(view.get("autoplay_job") or "")
        if autoplay:
            job = self.store.get("job", autoplay) or {}
            state = str(job.get("state") or "")
            if state and state != old.get("autoplay_state"):
                text = f"autoplay job {autoplay}: {state}"
                if job.get("error"):
                    text += f" · {job['error']}"
                self.add("autoplay", text, sid)
                view["autoplay_state"] = state
        self.last[sid] = view

    def _ghidra_once(self) -> None:
        if self.ghidra["checked"]:
            return
        self.ghidra["checked"] = True

        def check():
            try:
                from . import ghidra_bridge
                reason = ghidra_bridge.unavailable(self.config)
                self.ghidra.update(status="available" if not reason else "unavailable", reason=reason or "")
                self.add("ghidra", "available: PyGhidra and the operator's Ghidra are ready" if not reason
                         else f"unavailable: {reason}")
            except Exception as exc:                       # noqa: BLE001 - a status line never breaks the console
                self.ghidra.update(status="error", reason=f"{type(exc).__name__}: {exc}")
                self.add("ghidra", f"status error: {self.ghidra['reason']}")

        threading.Thread(target=check, name="harness-ghidra-status", daemon=True).start()

    def collect(self, sid: str) -> dict:
        session = self._session(sid)
        if not session:
            raise HTTPException(404, "no such session")
        with self.lock:
            self._state(sid, session)
            self._emulator(sid, session)
        self._ghidra_once()
        return session

    def tail(self, sid: str, after: int = 0, limit: int = 500) -> dict:
        session = self.collect(sid)
        after = max(0, int(after or 0))
        with self.lock:
            rows = [line for line in self.lines if line["seq"] > after and (not line["session"] or line["session"] == sid)]
            rows = rows[-max(1, min(limit, 2000)):]
            seq = self.seq
        return {"seq": seq, "lines": rows, "session": _session_view(session), "ghidra": dict(self.ghidra),
                "freeze": self.freeze_state(sid)}

    # -- reports ---------------------------------------------------------------------------------------------------
    def freeze_state(self, sid: str) -> dict:
        reports = sorted(self.root.glob(f"freeze-{sid}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if self.root.is_dir() else []
        return {"count": len(reports), "latest": reports[0].name if reports else ""}

    def write_freeze(self, sid: str, body: dict) -> dict:
        session = self._session(sid)
        if not session:
            raise HTTPException(404, "no such session")
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        path = self.root / f"freeze-{sid}-{stamp}.json"
        payload = {
            "session_id": sid,
            "at": time.time(),
            "at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "session": _session_view(session),
            "witness": body or {},
            "console": [line for line in list(self.lines) if not line["session"] or line["session"] == sid][-200:],
        }
        try:
            path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        except OSError as exc:
            raise HTTPException(500, f"could not write the freeze report: {exc}") from None
        self.add("freeze", f"report written: {path.name} ({len(payload['console'])} console lines)", sid)
        return {"ok": True, "report": str(path), "witness": body or {}, "console_lines": len(payload["console"])}

    def probe(self, sid: str) -> dict:
        session = self.collect(sid)
        detail = session.get("detail") or {}
        path = str(detail.get("log") or detail.get("eden_log") or "")
        tail = ""
        if path:
            try:
                tail = Path(path).read_text(errors="replace")[-12000:]
            except OSError:
                tail = ""
        self.add("probe", "diagnostic snapshot requested", sid)
        return {"session_id": sid, "at": time.time(), "session": _session_view(session),
                "emulator_log_path": path, "emulator_log_tail": tail, "ghidra": dict(self.ghidra),
                "freeze": self.freeze_state(sid)}


def _session_view(session: dict) -> dict:
    detail = session.get("detail") or {}
    return {
        "session_id": session.get("session_id"), "game_id": session.get("game_id"), "title": session.get("title"),
        "state": session.get("state"), "mod": session.get("mod"), "adapter": session.get("adapter"),
        "validation": session.get("validation") or detail.get("validation"),
        "overlay": {k: (detail.get("overlay") or {}).get(k) for k in ("build", "selection", "files", "pending")},
        "autoplay_job": detail.get("autoplay_job"), "log": detail.get("log") or detail.get("eden_log"),
    }


def _title_elf(config, session: dict) -> Path | None:
    """The analyzed Switch main for this session, from the known extracted/ELF locations."""
    from . import re_switch as editions
    ids = {editions.RE4_GAME_ID: "re4", editions.RE5_GAME_ID: "re5", editions.RE6_GAME_ID: "re6"}
    title = ids.get(session.get("game_id"))
    detail = session.get("detail") or {}
    serial = str(session.get("title_id") or detail.get("title_id") or "").upper()
    by_serial = next((name for name, row in editions.EDITIONS.items() if row["title_id"] == serial), None)
    if title and by_serial and title != by_serial:
        return None
    title = title or by_serial
    if title is None:
        return None
    root = Path(getattr(config, "data_dir", Path(".")))
    cache = Path(getattr(config, "cache", None) or getattr(config, "cache_dir", None) or root / "cache")
    tid = editions.EDITIONS[title]["title_id"]
    candidates = [cache / "exefs" / tid / "main.elf"]
    home = Path.home() / "gBox_alt"
    candidates += {
        "re4": [root / "analysis/switch/re4/re4_switch_main.elf", home / "gbox-cache/exefs" / tid / "main.elf"],
        "re5": [root / "analysis/switch/re5/re5_switch_main_EBFFDB22.elf",
                home / "scratch/agent/switch/re5/ghidra/re5main.elf"],
        "re6": [root / "analysis/switch/re6/re6_switch_main.elf",
                home / "scratch/agent/re6sw/nso/re6sw_main_061D2A06.elf"],
    }[title]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def install(app, store, config, auth, submit_job=None):
    service = HarnessConsole(store, config)

    @app.get("/api/sessions/{sid}/harness/console", dependencies=[Depends(auth)])
    def harness_console(sid: str, after: int = 0, limit: int = 500):
        """The game-hooked console: emulator log + MercMode/session transitions, tailed by sequence."""
        return service.tail(sid, after, limit)

    @app.post("/api/sessions/{sid}/harness/probe", dependencies=[Depends(auth)])
    def harness_probe(sid: str):
        """A diagnostic snapshot: session, overlay, emulator log tail and Ghidra readiness."""
        return service.probe(sid)

    @app.post("/api/sessions/{sid}/harness/freeze", dependencies=[Depends(auth)])
    def harness_freeze(sid: str, body: dict | None = None):
        """Persist a freeze witness (frame hash, unchanged seconds, screen, timer, console tail)."""
        return service.write_freeze(sid, body or {})

    @app.get("/api/sessions/{sid}/harness/freeze", dependencies=[Depends(auth)])
    def harness_freeze_list(sid: str):
        root = service.root
        rows = sorted(root.glob(f"freeze-{sid}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if root.is_dir() else []
        return {"reports": [{"name": p.name, "at": p.stat().st_mtime, "bytes": p.stat().st_size} for p in rows[:50]]}

    @app.get("/api/harness/ghidra", dependencies=[Depends(auth)])
    def harness_ghidra():
        """Whether the Ghidra Bridge can be hooked on this worker and why not when it cannot."""
        try:
            from . import ghidra_bridge
            reason = ghidra_bridge.unavailable(config)
            return {"status": "available" if not reason else "unavailable", "reason": reason or "",
                    "home": str(ghidra_bridge.ghidra_install_dir(config) or ""),
                    "python": ghidra_bridge.python_for(config)}
        except Exception as exc:                           # noqa: BLE001
            return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    @app.post("/api/sessions/{sid}/harness/ghidra", dependencies=[Depends(auth)])
    def harness_ghidra_attach(sid: str, body: dict | None = None):
        """Hook the title's analyzed main into the Ghidra Bridge: open / status / decompile / xrefs.

        The job runs on the session's worker, so the PiP console follows the same job console it already streams. This
        is the manual troubleshooter hook: the operator opens it when a freeze needs a loader/part-table answer.
        """
        if not store.get("session", sid):
            raise HTTPException(404, "no such session")
        if submit_job is None:
            raise HTTPException(503, "this control plane has no job submitter for Ghidra")
        body = body or {}
        op = str(body.get("op") or "status").strip().lower()
        if op == "status":
            return harness_ghidra()
        if op not in {"open", "info", "decompile", "xrefs_to", "xrefs_from", "functions", "containing", "strings"}:
            raise HTTPException(422, "unsupported harness analysis operation")
        elf = _title_elf(config, store.get("session", sid) or {})
        if elf is None:
            raise HTTPException(409, "no analyzed main ELF is present for this title; build/convert one first")
        inp = {"op": op, "binary_path": str(elf), "processor": body.get("processor") or "AARCH64:LE:64:v8A"}
        if op != "open":
            import hashlib
            with elf.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            inp.update(expected_binary_path=str(elf), expected_sha256=digest)
        if body.get("target"):
            inp["target"] = body["target"]
        worker = str(store.get("session", sid).get("worker_id") or sid.split("-")[0])
        try:
            job = submit_job("ghidra_bridge", inp, worker)
        except Exception as exc:                           # noqa: BLE001
            raise HTTPException(503, f"Ghidra Bridge job was not submitted: {exc}") from None
        service.add("ghidra", f"{op} requested on {elf.name} (job {job.get('id', '?')})", sid)
        return {"status": "submitted", "op": op, "binary_path": str(elf), "worker": worker, "job": job}

    return service
