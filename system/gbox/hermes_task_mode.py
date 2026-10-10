"""Operator-controlled Hermes cron job for sustained gBox inbox work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading

import httpx
import psutil


NAME = "gBox inbox task mode"
_LOCK = threading.RLock()
_PROMPT = Path(__file__).resolve().parent.parent / "hermes" / "gbox" / "TASK_MODE.md"


def _home() -> Path:
    return Path(os.environ.get("GBOX_HERMES_HOME") or Path.home() / ".hermes")


def _cli() -> Path:
    return Path.home() / ".local" / "bin" / "hermes"


def _job() -> dict | None:
    try:
        data = json.loads((_home() / "cron" / "jobs.json").read_text(encoding="utf-8"))
        return next((j for j in data.get("jobs", []) if j.get("name") == NAME), None)
    except (OSError, ValueError, TypeError):
        return None


def status() -> dict:
    job = _job() or {}
    return {"enabled": bool(job.get("enabled")), "available": _cli().is_file(),
            "job_id": job.get("id"), "model": job.get("model"), "schedule": job.get("schedule_display"),
            "last_run_at": job.get("last_run_at"), "last_status": job.get("last_status"),
            "last_error": job.get("last_error")}


def _model() -> tuple[str | None, str]:
    """Prefer the strongest locally verified inbox tool caller that fits available RAM."""
    try:
        models = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5).json().get("models", [])
        names = {m.get("name") for m in models}
        available = psutil.virtual_memory().available
        for name, minimum in (("qwen3.8:38b", 50), ("qwen3.6:35b", 40), ("gemma4:31b", 32),
                              ("qwen3.8:27b-mtp-q4_K_M", 30), ("gemma4:12b", 15)):
            if name in names and available >= minimum * 1024**3:
                return name, f"{name} selected ({available // 1024**3} GiB available)"
        return None, "No verified installed model fits current memory; using Hermes's configured model"
    except (httpx.HTTPError, ValueError, TypeError):
        return None, "Ollama model inventory unavailable; using Hermes's configured model"


def _run(*args: str) -> None:
    cli = _cli()
    if not cli.is_file():
        raise RuntimeError(f"Hermes CLI is unavailable at {cli}")
    done = subprocess.run([str(cli), "cron", *args], cwd=str(_PROMPT.parents[2]),
                          capture_output=True, text=True, timeout=45, check=False)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout or "Hermes cron command failed").strip()[-1000:])


def set_enabled(enabled: bool) -> dict:
    with _LOCK:
        job = _job()
        if enabled and not job:
            model, note = _model()
            args = ["create", "every 10m", _PROMPT.read_text(encoding="utf-8"), "--name", NAME,
                    "--workdir", str(_PROMPT.parents[2]),
                    "--deliver", "local", "--failure-deliver", "local", "--reasoning-effort", "high"]
            if model:
                args += ["--model", model, "--provider", "custom"]
            _run(*args)
            result = status()
            if not result["job_id"] or not result["enabled"]:
                raise RuntimeError("Hermes did not register an enabled task-mode job")
            _run("run", result["job_id"])
            return result | {"model_note": note}
        if job and enabled and not job.get("enabled"):
            _run("edit", job["id"], "--clear-skills", "--prompt", _PROMPT.read_text(encoding="utf-8"))
            _run("resume", job["id"])
            _run("run", job["id"])
        elif job and not enabled and job.get("enabled"):
            _run("pause", job["id"])
        result = status()
        if result["enabled"] != enabled:
            raise RuntimeError("Hermes task-mode setting did not take effect")
        return result
