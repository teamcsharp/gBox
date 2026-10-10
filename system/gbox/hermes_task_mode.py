"""Operator-controlled Hermes cron job for sustained gBox inbox work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

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
    try:
        import yaml
        try:
            config = yaml.safe_load((_home() / 'config.yaml').read_text()) or {}
        except yaml.YAMLError:
            config = {}
    except (ImportError, OSError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    model_config, agent_config = config.get('model') or {}, config.get('agent') or {}
    last_status, last_error = job.get("last_status"), job.get("last_error")
    if job.get("id") and last_status == "ok":
        # Hermes's "ok" only means its process exited; it does not mean an inbox request was solved.
        last_status = "unverified"
        last_error = "Hermes finished, but no completed inbox result has been independently verified."
        output_dir = _home() / "cron" / "output" / job["id"]
        try:
            latest = max(output_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
            response = latest.read_text(encoding="utf-8").split("## Response", 1)[-1]
            if "[CRON_FAILURE]" in response:
                last_status = "failed"
                last_error = next((line.strip()[:300] for line in response.splitlines()
                                   if "[CRON_FAILURE]" in line), "Hermes reported no concrete progress")
        except (OSError, ValueError):
            pass
    return {"enabled": bool(job.get("enabled")), "available": _cli().is_file(),
            "job_id": job.get("id"), "model": job.get("model") or model_config.get('default'),
            "provider": job.get('provider') or model_config.get('provider'),
            "reasoning_effort": job.get('reasoning_effort') or agent_config.get('reasoning_effort'),
            "max_turns": agent_config.get('max_turns'),
            "fallback_providers": [{'provider': item.get('provider'), 'model': item.get('model')}
                                   for item in config.get('fallback_providers') or [] if isinstance(item, dict)],
            "schedule": job.get("schedule_display"),
            "last_run_at": job.get("last_run_at"), "last_status": last_status,
            "last_error": last_error}


def _model() -> tuple[str | None, str]:
    """Follow the operator's Hermes provider/model, including a connected cloud account."""
    return None, "Following Hermes's configured provider and model"


def _run(*args: str) -> None:
    cli = _cli()
    if not cli.is_file():
        raise RuntimeError(f"Hermes CLI is unavailable at {cli}")
    done = subprocess.run([str(cli), "cron", *args], cwd=str(_PROMPT.parents[2]),
                          capture_output=True, text=True, timeout=45, check=False)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout or "Hermes cron command failed").strip()[-1000:])


def _kickoff(job: dict) -> None:
    # `hermes cron run` waits for the entire agent run, so it can time out the
    # checkbox API. Let the gateway launch a one-shot job on its next tick.
    args = ['create', '1m', _PROMPT.read_text(encoding='utf-8'), '--name',
            NAME + ' activation ' + str(time.time_ns()), '--repeat', '1',
            '--workdir', str(_PROMPT.parents[2]), '--deliver', 'local',
            '--failure-deliver', 'local', '--reasoning-effort', 'max']
    if job.get('model') and job.get('provider'):
        args += ['--model', job['model'], '--provider', job['provider']]
    _run(*args)


def set_enabled(enabled: bool) -> dict:
    with _LOCK:
        job = _job()
        # Older gBox jobs were pinned to a local Ollama model when created.
        # Release only those pins so an account upgrade takes effect on the
        # next scheduled run without overriding an intentional cloud pin.
        if enabled and job and job.get("provider") == "custom" and job.get("model") in {
                "gemma4:e4b-it-qat", "gemma4:e4b", "gemma4:12b-it-qat",
                "gemma4:12b", "qwen3:8b"}:
            _run("edit", job["id"], "--unpin")
            job = _job()
        if enabled and not job:
            model, note = _model()
            args = ["create", "every 30m", _PROMPT.read_text(encoding="utf-8"), "--name", NAME,
                    "--workdir", str(_PROMPT.parents[2]),
                    "--deliver", "local", "--failure-deliver", "local", "--reasoning-effort", "max", "--continuity"]
            if model:
                args += ["--model", model, "--provider", "custom"]
            _run(*args)
            result = status()
            if not result["job_id"] or not result["enabled"]:
                raise RuntimeError("Hermes did not register an enabled task-mode job")
            _kickoff(_job() or {})
            return result | {"model_note": note}
        if job and enabled and not job.get("enabled"):
            _run("edit", job["id"], "--clear-skills", "--prompt", _PROMPT.read_text(encoding="utf-8"))
            _run("resume", job["id"])
            _kickoff(_job() or {})
        elif job and not enabled and job.get("enabled"):
            _run("pause", job["id"])
            pending = json.loads((_home() / 'cron/jobs.json').read_text()).get('jobs', [])
            for item in pending:
                if item.get('enabled') and item.get('name', '').startswith(NAME + ' activation '):
                    _run('pause', item['id'])
        result = status()
        if result["enabled"] != enabled:
            raise RuntimeError("Hermes task-mode setting did not take effect")
        return result


def dispatch_request(request_id: str, number: int) -> str:
    """Queue a cloud investigation after the incident's immediate recovery finishes."""
    with _LOCK:
        name = f"gBox emulation investigation #{number}"
        try:
            jobs = json.loads((_home() / "cron/jobs.json").read_text()).get("jobs", [])
        except (OSError, ValueError):
            jobs = []
        existing = next((j for j in jobs if j.get('name') == name), None)
        if existing:
            return existing['id']
        prompt = (f"Investigate and resolve gBox emulation report #{number}, request_id={request_id}. "
                  "Your first substantive action is mcp_gbox_get_request for this request ID. "
                  "If the report is already done, verify its completion reply and finish without reopening it. "
                  "Read the attached emulation-diagnostics Markdown, screenshots, save state and recovery results. Identify the "
                  "permanent root cause of the freeze/black screen and implement and test a concrete fix in gBox. "
                  "Use the available cloud reasoning capacity and gBox MCP tools. Preserve the operator's current "
                  "game; use only an idle worker for reproduction and enforce 2% audio. Record each attempt, "
                  "attach real screenshots and actual token metrics, and mark done only after independent "
                  "verification. A moving frame after relaunch alone does not prove that the supplied moment "
                  "was restored or that the underlying fault was fixed.")
        args = ['create', '1m', prompt, '--name', name, '--repeat', '1',
                '--workdir', str(_PROMPT.parents[2]), '--deliver', 'local', '--failure-deliver', 'local',
                '--reasoning-effort', 'max']
        inbox = _job() or {}
        if inbox.get('model') and inbox.get('provider'):
            args += ['--model', inbox['model'], '--provider', inbox['provider']]
        _run(*args)
        jobs = json.loads((_home() / 'cron/jobs.json').read_text()).get('jobs', [])
        job = next((j for j in jobs if j.get('name') == name), None)
        if not job:
            raise RuntimeError('Hermes did not register the incident investigation')
        return job['id']
