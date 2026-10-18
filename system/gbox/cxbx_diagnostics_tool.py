"""Typed, read-only diagnostic dispatch tied to an accepted historical launch."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .registry import HOST_OS, Ctx, tool
from .store import canon, sha256

ARTIFACT = "cxbx-diagnostics.json"
MAX_API_BYTES = 1 << 20
ID = r"^[0-9a-f]{16}$"


class DiagnosticsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    launch_job_id: str = Field(pattern=ID)
    game_id: str = Field(pattern=ID)
    stop_job_id: str | None = Field(default=None, pattern=ID)


class DiagnosticsOut(BaseModel):
    result: dict
    report_sha256: str


def _get(ctx, path):
    if not ctx.server:
        raise ValueError("A control-plane connection is required for launch identity")
    deadline = ctx.execution_deadline_monotonic
    remaining = deadline - time.monotonic() if deadline is not None else 10.0
    if remaining <= 0:
        raise TimeoutError("Diagnostic execution deadline expired")
    data = bytearray()
    with httpx.stream("GET", ctx.server.rstrip("/") + path, headers=ctx.headers,
                      timeout=min(10.0, remaining), follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes(chunk_size=65536):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Diagnostic execution deadline expired")
            if len(data) + len(chunk) > MAX_API_BYTES:
                raise ValueError("Diagnostic identity response exceeds the bounded limit")
            data.extend(chunk)
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Diagnostic identity response is not an object")
    return value


def _accepted(ctx, job_id, tool_name):
    job = _get(ctx, "/api/jobs/" + job_id)
    rid = job.get("receipt_id")
    if (job.get("id") != job_id or job.get("tool") != tool_name
            or job.get("state") != "succeeded" or job.get("error")
            or job.get("result_acceptance") != "complete"
            or not isinstance(rid, str) or not re.fullmatch(ID, rid)):
        raise ValueError("An exactly accepted successful job is required")
    receipt = _get(ctx, "/api/receipts/" + rid)
    if (receipt.get("id") != rid or receipt.get("job_id") != job_id
            or receipt.get("tool") != tool_name or receipt.get("worker_id") != job.get("worker_id")
            or receipt.get("validation_ok") is not True or receipt.get("validation_problems") != []
            or receipt.get("input_sha256") != sha256(canon(job.get("input")))
            or receipt.get("output_sha256") != sha256(canon(job.get("output")))
            or receipt.get("started") != job.get("started") or receipt.get("finished") != job.get("finished")):
        raise ValueError("Job identity or bytes differ from the accepted receipt")
    started, finished = job.get("started"), job.get("finished")
    if (any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (started, finished))
            or finished < started):
        raise ValueError("Job receipt has no valid time boundary")
    return job, receipt


def trusted_launch(inp: DiagnosticsIn, ctx: Ctx):
    job, receipt = _accepted(ctx, inp.launch_job_id, "launch_game")
    game = (job.get("input") or {}).get("game") or {}
    output = job.get("output") or {}
    detail = output.get("detail") or {}
    worker = job.get("worker_id")
    if (not isinstance(worker, str) or not re.fullmatch(ID, worker)
            or not isinstance(game, dict) or game.get("game_id") != inp.game_id
            or game.get("platform") != "xbox" or output.get("adapter") != "cxbx"
            or output.get("session_id") != f"{worker}-{inp.launch_job_id}"
            or not isinstance(detail, dict) or not isinstance(detail.get("rom"), str)):
        raise ValueError("The exact Xbox game and Cxbx launch identity are required")
    # Worker ids change on refresh. Resolve only the server's existing recorded
    # alias chain, never a caller-supplied machine name or inferred model route.
    alias = None
    if worker != ctx.worker:
        status = _get(ctx, "/api/background/workers/" + worker + "/status")
        current = status.get("worker") or {}
        if (status.get("online") is not True or current.get("id") != ctx.worker
                or current.get("os") != "windows" or not detail.get("worker_name")
                or current.get("name") != detail["worker_name"]):
            raise ValueError("This worker is not the launch owner or its canonical successor")
        alias = {"source": "control-plane worker alias", "from": worker, "to": ctx.worker,
                 "name": current["name"]}
    launch = {"game_id": inp.game_id, "job_id": inp.launch_job_id,
              "session_id": output["session_id"], "worker_id": worker,
              "started": job["started"], "finished": job["finished"], "detail": detail,
              "receipt_id": receipt["id"], "input_sha256": receipt["input_sha256"],
              "output_sha256": receipt["output_sha256"],
              "collection_worker_id": ctx.worker, "worker_alias": alias}
    if inp.stop_job_id:
        stopped, stop_receipt = _accepted(ctx, inp.stop_job_id, "session_op")
        stop_in, stop_out = stopped.get("input") or {}, stopped.get("output") or {}
        if (stopped.get("worker_id") != worker or stop_in.get("op") != "stop_game"
                or stop_in.get("session_id") != launch["session_id"]
                or stop_out.get("session_id") != launch["session_id"] or stop_out.get("ended") is not True
                or stopped["started"] < job["finished"]):
            raise ValueError("Stop receipt does not establish this exact session ended")
        launch["ended"] = {"job_id": inp.stop_job_id, "receipt_id": stop_receipt["id"],
                           "at": stopped["finished"], "output_sha256": stop_receipt["output_sha256"]}
    return launch


@tool("cxbx_diagnostics", "1.0", DiagnosticsIn, DiagnosticsOut, platforms=["windows"],
      capabilities=["runtime", "diagnostics"], artifacts=[ARTIFACT], timeout_s=120,
      validation="accepted exact launch receipt, fixed bounded file snapshots")
def cxbx_diagnostics(inp: DiagnosticsIn, ctx: Ctx):
    """Read fixed Cxbx installation and launch evidence for an accepted Xbox launch.

    Supports ended sessions. Does not launch, attach, install, configure, or read saves.
    Source on disk must already be loaded by the worker; this is not a hot reload.
    """
    if HOST_OS != "windows":
        raise ValueError("Cxbx diagnostics must execute on the owning Windows worker")
    launch = trusted_launch(inp, ctx)
    from .cxbx_diagnostics import collect
    result = collect(ctx.config, xbe=Path(launch["detail"]["rom"]), launch=launch)
    result["accepted_launch"] = {key: value for key, value in launch.items() if key != "detail"}
    report = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ctx.artifact(ARTIFACT, report, "application/json", game_id=inp.game_id,
                 launch_job_id=inp.launch_job_id, launch_worker=launch["worker_id"],
                 collected_by=ctx.worker, read_only=True)
    return {"result": result, "report_sha256": sha256(report)}
