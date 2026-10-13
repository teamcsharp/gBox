"""gbox CLI: init | serve [--worker] | worker | submit | schemas | mcp"""
import argparse
import json
import os
import threading
import time
from pathlib import Path

from . import config as cfgmod


def main():
    ap = argparse.ArgumentParser(prog="gbox")
    ap.add_argument("--config", default=os.environ.get("GBOX_CONFIG", "gbox.toml"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="write a first-run gbox.toml")
    s = sub.add_parser("serve", help="run the control plane")
    s.add_argument("--worker", action="store_true", help="also run a local worker (Windows standalone mode)")
    w = sub.add_parser("worker", help="run an execution worker against a control plane")
    w.add_argument("--server", required=True)
    w.add_argument("--name")
    w.add_argument("--reconcile-results", action="store_true",
                   help="explicitly retry up to four exact retained results; activation still requires verified delivery")
    j = sub.add_parser("submit", help="submit a job and wait for its receipt")
    j.add_argument("tool")
    j.add_argument("input", nargs="?", default="{}")
    j.add_argument("--server", default=None)
    sub.add_parser("schemas", help="export JSON Schemas to schemas/")
    sub.add_parser("rea-install", help="install the pinned REA runtime on this worker without changing agent configs")
    sub.add_parser("ghidra-bridge-install", help="make the Ghidra Bridge PyGhidra venv from this Ghidra's own wheels (offline)")
    su = sub.add_parser("setup", help="install/verify this node's dependencies (apt, mounts, cores, BIOS, ghidra, blender)")
    su.add_argument("--no-ghidra", action="store_true")
    wz = sub.add_parser("wizard", help="setup / deploy / troubleshoot wizard in the browser (what gBox.sh opens)")
    wz.add_argument("--port", type=int, default=8770)
    wz.add_argument("--no-browser", action="store_true")
    m = sub.add_parser("mcp", help="MCP server (stdio) so Claude / other agents can drive gBox; --http for streamable HTTP")
    m.add_argument("--server", default=None, help="control plane URL (default: public_url from the config)")
    m.add_argument("--http", type=int, nargs="?", const=0, default=None, metavar="PORT",
                   help="serve streamable HTTP at /mcp instead of stdio (default port: api_port + 1)")
    a = ap.parse_args()

    if a.cmd == "wizard":
        from . import wizard
        wizard.serve(Path(a.config), a.port, not a.no_browser)
        return

    if a.cmd == "init":
        p = Path(a.config)
        if p.exists():
            raise SystemExit(f"{p} already exists")
        p.write_text(cfgmod.TEMPLATE)
        print(f"wrote {p}; API token will be created at <data_dir>/api_token on first serve")
        return

    cfg = cfgmod.load(a.config)
    if a.cmd == "ghidra-bridge-install":
        from .ghidra_bridge import install as gb_install
        print(json.dumps(gb_install(cfg), indent=2))
        return
    if a.cmd == "rea-install":
        from .rea import install
        print(json.dumps(install(cfg), indent=2))
        return
    if a.cmd == "mcp":
        from . import mcp_server
        if not os.environ.get("GBOX_TOKEN") and not (cfg.data_dir / "api_token").exists():   # never mint a new token here
            raise SystemExit(f"no token: set GBOX_TOKEN or use the deployment's gbox.toml ({cfg.data_dir / 'api_token'} missing)")
        server = a.server or cfg.public_url or f"http://127.0.0.1:{cfg.api_port}"
        if a.http is None:
            mcp_server.serve_stdio(server, cfg.token())
        else:
            mcp_server.serve_http(server, cfg.token(), cfg.api_host, a.http or cfg.api_port + 1)
        return
    if a.cmd in ("serve", "worker"):                     # a venv older than a dependency gets it now, before tools import
        from . import deps
        deps.ensure_declared()
    if a.cmd == "serve":
        import uvicorn
        from .server import create_app
        app = create_app(cfg)
        if a.worker:
            from . import worker
            url = f"http://127.0.0.1:{cfg.api_port}"
            threading.Thread(target=lambda: (time.sleep(1.5), worker.run(url, cfg.token(), cfg)), daemon=True).start()
        print(f"gBox on http://{cfg.api_host}:{cfg.api_port}  token file: {cfg.data_dir / 'api_token'}")
        uvicorn.run(app, host=cfg.api_host, port=cfg.api_port, log_level="warning")
    elif a.cmd == "worker":
        from . import worker
        worker.run(a.server, cfg.token(), cfg, a.name, reconcile_results=a.reconcile_results)
    elif a.cmd == "submit":
        import httpx
        server = a.server or f"http://127.0.0.1:{cfg.api_port}"
        h = {"authorization": f"Bearer {cfg.token()}"}
        job = httpx.post(f"{server}/api/jobs", json={"tool": a.tool, "input": json.loads(a.input)}, headers=h).json()
        while job.get("state") in ("queued", "running"):
            time.sleep(0.5)
            job = httpx.get(f"{server}/api/jobs/{job['id']}", headers=h).json()
        if job.get("receipt_id"):
            job["receipt"] = httpx.get(f"{server}/api/receipts/{job['receipt_id']}", headers=h).json()
        print(json.dumps(job, indent=2))
    elif a.cmd == "setup":
        from . import provision
        print(f"gBox setup on {provision.HOST_OS}/{provision.ARCH}")
        r = provision.setup(cfg, with_ghidra=not a.no_ghidra)
        bad = [x["step"] for x in r if x["status"] in ("failed", "missing")]
        print("all steps ok" if not bad else f"FAILED: {bad}")
        raise SystemExit(1 if bad else 0)
    elif a.cmd == "schemas":
        from . import models, uap
        from .registry import REGISTRY
        from . import tools  # noqa: F401
        out = Path(__file__).resolve().parent.parent / "schemas"
        out.mkdir(exist_ok=True)
        for m in (models.ToolInfo, models.Job, models.Receipt, models.WorkerInfo, models.CatalogEntry,
                  models.KnowledgeEdge, models.RunRecord, uap.Manifest):
            (out / f"{m.__name__}.schema.json").write_text(json.dumps(m.model_json_schema(), indent=1))
        (out / "tools.json").write_text(json.dumps([t.info().model_dump(mode="json") for t in REGISTRY.values()], indent=1))
        print(f"wrote schemas to {out}")


if __name__ == "__main__":
    main()
