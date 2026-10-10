"""Operator-controlled Hermes cron job for sustained gBox inbox work."""
from __future__ import annotations

import json
import datetime as dt
import os
from pathlib import Path
import subprocess
import sqlite3
import threading
import time

NAME = "gBox inbox task mode"
_LOCK = threading.RLock()
_PROMPT = Path(__file__).resolve().parent.parent / "hermes" / "gbox" / "TASK_MODE.md"


def _home() -> Path:
    return Path(os.environ.get("GBOX_HERMES_HOME") or Path.home() / ".hermes")


def _cli() -> Path:
    return Path.home() / ".local" / "bin" / "hermes"


def _jobs() -> list[dict]:
    try:
        data = json.loads((_home() / "cron" / "jobs.json").read_text(encoding="utf-8"))
        return data.get("jobs", [])
    except (OSError, ValueError, TypeError):
        return []


def _job() -> dict | None:
    return next((j for j in _jobs() if j.get("name") == NAME), None)


def _config() -> dict:
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
    return config


def _active(job_id: str) -> bool:
    """One-shots are disabled at dispatch, while their execution may still be running."""
    path = _home() / 'cron' / 'executions.db'
    if not path.is_file():
        return False
    try:
        db = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=1)
        try:
            return db.execute("SELECT 1 FROM executions WHERE job_id=? AND status IN "
                              "('claimed','running') LIMIT 1", (job_id,)).fetchone() is not None
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise RuntimeError('Cannot check Hermes executions safely; dispatch was deferred') from exc


def _route_args(job: dict) -> list[str]:
    # A job pin disables Hermes's fallback chain. A configured cron cloud route
    # already overrides the interactive local model without disabling recovery.
    cron = _config().get('cron') or {}
    if cron.get('model') and cron.get('model_provider'):
        return []
    if job.get('model') and job.get('provider'):
        return ['--model', job['model'], '--provider', job['provider']]
    return []


def _once() -> str:
    # Hermes parses "1m" as an interval, even with --repeat 1. Its atomic
    # re-arm command requires a genuine one-shot schedule.
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=1)).isoformat()


def _handoff() -> str:
    from .hermes_capabilities import INSTRUCTIONS
    from .hermes_feedback import brief
    return (' ' + INSTRUCTIONS + ' Prepare or reuse this request\'s isolated Git workspace with prepare_task_workspace before editing. '
            'Never edit the live canonical share. Use the returned workdir and preserve earlier patches. '
            'Use start_job/get_job for remote operations; keep the same pending job ID, check worker health once, '
            'and continue source work if remote calls time out. Do not test on the operator PC. '
            'Use a 45-tool-call work budget with the final 10 calls reserved for focused tests, '
            'publish_task_changes, evidence and a final reply. Publish explicit source files and focused tests '
            'through publish_task_changes to produce a real commit and draft GitHub PR even if deployment '
            'must wait. A pending PR or screenshot alone does not complete the ticket.' + brief())


def _workdir(request_id: str, number: int) -> str:
    from . import hermes_delivery
    if (hermes_delivery.repository() / '.git').exists():
        return hermes_delivery.prepare(request_id, number)['workdir']
    return str(_PROMPT.parents[2])


def status() -> dict:
    from .hermes_capabilities import audit
    from . import hermes_delivery
    job, config = _job() or {}, _config()
    model_config, agent_config, cron = (config.get(k) or {} for k in ('model', 'agent', 'cron'))
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
            "job_id": job.get("id"), "model": job.get("model") or cron.get('model') or model_config.get('default'),
            "provider": job.get('provider') or cron.get('model_provider') or model_config.get('provider'),
            "reasoning_effort": job.get('reasoning_effort') or agent_config.get('reasoning_effort'),
            "max_turns": agent_config.get('max_turns'),
            "fallback_providers": [{'provider': item.get('provider'), 'model': item.get('model')}
                                   for item in config.get('fallback_providers') or [] if isinstance(item, dict)],
            "fallback_enabled": not any(job.get(k) for k in ('model', 'provider', 'base_url')),
            "max_parallel_jobs": cron.get('max_parallel_jobs'),
            "image_input_mode": agent_config.get('image_input_mode', 'auto'),
            "git_workspace_ready": (hermes_delivery.repository() / '.git').exists(),
            "capabilities": audit(config),
            "operator_worker": ((config.get('mcp_servers') or {}).get('gbox') or {}).get('env', {}).get('GBOX_OPERATOR_WORKER'),
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
    if job.get('id') and _active(job['id']):
        return
    if any((j.get('enabled') or _active(j['id'])) for j in _jobs()
           if j.get('name', '').startswith(NAME + ' activation ')):
        return
    args = ['create', _once(), _PROMPT.read_text(encoding='utf-8') + _handoff(), '--name',
            NAME + ' activation ' + str(time.time_ns()), '--repeat', '1',
            '--workdir', str(_PROMPT.parents[2]), '--deliver', 'local',
            '--failure-deliver', 'local', '--reasoning-effort', 'high']
    args += _route_args(job)
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
                    "--deliver", "local", "--failure-deliver", "local", "--reasoning-effort", "high", "--continuity"]
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
        jobs = _jobs()
        existing = next((j for j in reversed(jobs) if j.get('name') == name
                         or j.get('name', '').startswith(name + ' retry ')), None)
        previous = None
        if existing:
            if (existing.get('enabled', True) or _active(existing['id'])
                    or existing.get('last_status') != 'error'):
                return existing['id']
            if (existing.get('schedule') or {}).get('kind') == 'once':
                # Hermes locks and resets the genuine one-shot occurrence itself.
                args = ['edit', existing['id'], '--continuity', '--prompt',
                        f'Resume report #{number}, request_id={request_id}. Read get_request, the previous replies and saved patch. '
                        'Change the failed step using get_dispatch_feedback, validate the existing fix and finish its handoff. '
                        'Keep the ticket in progress until its acceptance criteria are verified.' + _handoff(),
                        '--workdir', _workdir(request_id, number),
                        '--reasoning-effort', 'high']
                if not _route_args(_job() or {}):
                    args += ['--unpin']
                _run(*args)
                _run('resume', existing['id'], '--run-now')
                return existing['id']
            # Hermes cannot re-arm an exhausted legacy interval, or convert its
            # terminal schedule through edit. Keep that history and create one
            # identifiable replacement occurrence for the same report.
            previous = existing['id']
            name += ' retry ' + previous
        prompt = (f"Investigate and resolve gBox emulation report #{number}, request_id={request_id}. "
                  "Your first substantive action is mcp_gbox_get_request for this request ID. "
                  "If the report is already done, verify its completion reply and finish without reopening it. "
                  "Read the attached emulation-diagnostics Markdown, screenshots, save state and recovery results. Identify the "
                  "permanent root cause of the freeze/black screen and implement and test a concrete fix in gBox. "
                  "Use the available cloud reasoning capacity and gBox MCP tools. Preserve the operator's current "
                  "game; use only an idle worker for reproduction and enforce 2% audio. Record each attempt, "
                  "attach real screenshots and actual token metrics with the actual provider/model/system, "
                  "record solved_by implementation credit separately from its reviewer, and mark done only after independent "
                  "verification. Before editing, inspect list_tasks and the report's latest replies to avoid "
                  "duplicating an active investigation. Work on this report only, checkpoint each material "
                  "attempt in its replies, and reserve the last turns for validation and an honest final result. "
                  "Edit the isolated task workspace with terminal, read_file and patch; "
                  "Use execute_code for bounded Python orchestration when useful. Read at most 120 nearby source lines per call. "
                  "Use /home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/python with PYTHONPATH set to your task's system directory for focused tests. Once those pass, "
                  "do not repeat unrelated baseline/headless test failures without a relevant new change. "
                  "A moving frame after relaunch alone does not prove that the supplied moment "
                  "was restored or that the underlying fault was fixed.")
        if previous:
            prompt += (f" This resumes failed Hermes job {previous}. Read the report's previous replies "
                       "and existing source before changing anything; preserve already-applied fixes. "
                       "The old failed run remains available in Tasks for its evidence and token accounting.")
        prompt += _handoff()
        args = ['create', _once(), prompt, '--name', name, '--repeat', '1',
                '--workdir', _workdir(request_id, number), '--deliver', 'local', '--failure-deliver', 'local',
                '--reasoning-effort', 'high']
        inbox = _job() or {}
        args += _route_args(inbox)
        _run(*args)
        jobs = json.loads((_home() / 'cron/jobs.json').read_text()).get('jobs', [])
        job = next((j for j in jobs if j.get('name') == name), None)
        if not job:
            raise RuntimeError('Hermes did not register the incident investigation')
        return job['id']
