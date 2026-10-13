"""`ghidra_bridge` worker tool: the operator's Ghidra as JSON functions for the LLM (gbox/ghidra_bridge.py).

ops
  status                       is the bridge running here, which program is open, can it run (unavailable reason)
  start / open                 start the bridge inside the operator's Ghidra and open a program: binary_path (imported
                               into a gBox-owned project; the file itself is only read) or an existing Ghidra project
                               (project_dir + project_name + program_name). processor = Ghidra language id.
  stop / close                 close the program (stop also ends the bridge process)
  info | functions | decompile | xrefs_to | xrefs_from | containing | strings
                               queries; live when a program is open, else from export_dir (an upstream
                               `ghidra-bridge export` directory or one written by op=export)
  run_script                   run any GhidraScript (gBox's adapters/ghidra scripts by name, or a path) on the open program
  export                       write the upstream export layout to export_dir (ReAgent / ghidra-bridge CLI can read it)
Every result is JSON; the full result is also kept as the ghidra_bridge.json artifact.
"""
import json
from pathlib import Path

from pydantic import BaseModel, Field

from . import ghidra_bridge as gb
from .models import Permission as P
from .registry import ToolUnavailable, tool

QUERY_OPS = {"info", "functions", "decompile", "xrefs_to", "xrefs_from", "containing", "strings"}
OPS = QUERY_OPS | {"status", "start", "open", "stop", "close", "run_script", "export"}


class GhidraBridgeIn(BaseModel):
    op: str = Field("status", description="|".join(sorted(OPS)))
    binary_path: str | None = None
    project_dir: str | None = None
    project_name: str | None = None
    program_name: str | None = None
    processor: str | None = None
    analyze: bool = True
    target: str | None = None          # decompile / xrefs: 0x address or function name
    address: str | None = None         # containing
    query: str = ""                    # functions: name substring
    pattern: str = ""                  # strings: regex
    limit: int = Field(100, ge=1, le=5000)
    offset: int = Field(0, ge=0)
    script: str | None = None          # run_script: file name in adapters/ghidra or a path
    args: list[str] = []
    export_dir: str | None = None
    export_limit: int = Field(0, ge=0)   # export: first N functions only (0 = all)


class GhidraBridgeOut(BaseModel):
    op: str
    source: str                        # live | export | none
    worker_id: str
    result: dict


def _clip(result: dict, limit=60000) -> dict:
    """Keep polling responses bounded; the artifact has everything."""
    text = json.dumps(result, default=str)
    if len(text) <= limit:
        return result
    out = dict(result)
    if isinstance(out.get("decompiled"), str):
        out["decompiled"] = out["decompiled"][:limit // 2] + "\n/* gBox: truncated; full text in ghidra_bridge.json */"
    for k in ("functions", "xrefs", "strings", "callers", "callees", "data_refs"):
        if isinstance(out.get(k), list) and len(json.dumps(out, default=str)) > limit:
            out[k] = out[k][:50]
            out["_truncated"] = True
    return out


def default_project_dir(config) -> str:
    return str((config.data_dir / "analysis" / "ghidra_bridge").resolve())


def run(inp: GhidraBridgeIn, config, worker="local", progress=None, sess=None) -> dict:
    s = sess or gb.session(config)
    op = {"start": "open", "close": "close"}.get(inp.op, inp.op)
    if inp.op not in OPS:
        raise ValueError(f"unknown op {inp.op!r}; ops: {sorted(OPS)}")
    if inp.op == "status":
        return {"op": "status", "source": "live" if s.opened else "none", "worker_id": worker,
                "result": {"running": s.running(), "open": s.opened, "unavailable": gb.unavailable(config) if sess is None else None,
                           "ghidra": str(gb.ghidra_install_dir(config) or "")}}
    if inp.op == "stop":
        return {"op": "stop", "source": "none", "worker_id": worker, "result": {"stopped": s.stop()}}
    if op == "open":
        if not inp.binary_path and not (inp.project_dir and inp.project_name and inp.program_name):
            if inp.op == "start":
                s.start()
                return {"op": "start", "source": "none", "worker_id": worker, "result": {"running": s.running()}}
            raise ValueError("open needs binary_path, or project_dir + project_name + program_name of an existing project")
        if inp.binary_path and not Path(inp.binary_path).is_file():
            raise FileNotFoundError(f"binary_path not found on this worker: {inp.binary_path}")
        args = {"binary_path": inp.binary_path, "project_dir": inp.project_dir or default_project_dir(config),
                "project_name": inp.project_name, "program_name": inp.program_name, "processor": inp.processor,
                "analyze": inp.analyze}
        res = s.request("open", args, timeout=3500, progress=progress)
        return {"op": inp.op, "source": "live", "worker_id": worker, "result": res}
    if op == "close":
        res = s.request("close") if s.running() else {"closed": False, "note": "bridge not running"}
        return {"op": "close", "source": "none", "worker_id": worker, "result": res}
    if op == "run_script":
        if not inp.script:
            raise ValueError("run_script needs script")
        res = s.request("run_script", {"script": inp.script, "args": inp.args, "script_dirs": gb.SCRIPT_DIRS},
                        timeout=3500, progress=progress)
        return {"op": op, "source": "live", "worker_id": worker, "result": res}
    if op == "export":
        if not inp.export_dir:
            raise ValueError("export needs export_dir")
        res = s.request("export", {"export_dir": inp.export_dir, "limit": inp.export_limit},
                        timeout=3500, progress=progress)
        return {"op": op, "source": "live", "worker_id": worker, "result": res}
    # queries
    args = {"info": {}, "functions": {"query": inp.query, "limit": inp.limit, "offset": inp.offset},
            "decompile": {"target": inp.target}, "xrefs_to": {"target": inp.target, "limit": inp.limit},
            "xrefs_from": {"target": inp.target}, "containing": {"address": inp.address or inp.target},
            "strings": {"pattern": inp.pattern or inp.query, "limit": inp.limit}}[op]
    if op in ("decompile", "xrefs_to", "xrefs_from") and not inp.target:
        raise ValueError(f"{op} needs target (0x address or function name)")
    if op == "containing" and not args["address"]:
        raise ValueError("containing needs address")
    if s.opened and s.running():
        return {"op": op, "source": "live", "worker_id": worker, "result": s.request(op, args, timeout=900, progress=progress)}
    if inp.export_dir:
        return {"op": op, "source": "export", "worker_id": worker,
                "result": getattr(gb.ExportBackend(inp.export_dir), op)(**args)}
    raise ToolUnavailable("No program is open in this worker's Ghidra Bridge and no export_dir was given: "
                          "run ghidra_bridge op=open (binary_path or an existing project) first, on the same worker.")


@tool("ghidra_bridge", "1.0", GhidraBridgeIn, GhidraBridgeOut, capabilities=["analysis", "ghidra", "reverse-engineering"],
      platforms=["windows", "linux", "darwin"], permissions=[P.READ, P.EXECUTE], timeout_s=3600,
      side_effects=["keeps a Ghidra process with the open program on this worker until op=stop",
                    "op=open/run_script save analysis into the Ghidra project; game files are only read"],
      artifacts=["ghidra_bridge.json"], validation="output schema + preserved full result artifact")
def ghidra_bridge(inp: GhidraBridgeIn, ctx):
    """The operator's Ghidra as functions: start/stop the bridge, open a binary or existing project, decompile by address
    or name, callers/callees (xrefs), function search, strings with references, containing function, run any Ghidra
    script, export. Keep later calls on the returned worker_id (the program stays open there)."""
    out = run(inp, ctx.config, ctx.worker, progress=lambda: ctx.progress(1, f"Ghidra Bridge {inp.op} still running"))
    ctx.artifact("ghidra_bridge.json", json.dumps(out, default=str).encode(), "application/json", op=inp.op,
                 upstream="https://github.com/Dryxio/ghidra-bridge")
    return out | {"result": _clip(out["result"])}
