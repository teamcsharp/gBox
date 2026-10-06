"""gbox CLI: init | serve [--worker] | worker | submit | schemas"""
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
    j = sub.add_parser("submit", help="submit a job and wait for its receipt")
    j.add_argument("tool")
    j.add_argument("input", nargs="?", default="{}")
    j.add_argument("--server", default=None)
    sub.add_parser("schemas", help="export JSON Schemas to schemas/")
    su = sub.add_parser("setup", help="install/verify this node's dependencies (apt, mounts, cores, BIOS, ghidra, blender)")
    su.add_argument("--no-ghidra", action="store_true")
    a = ap.parse_args()

    if a.cmd == "init":
        p = Path(a.config)
        if p.exists():
            raise SystemExit(f"{p} already exists")
        p.write_text(cfgmod.TEMPLATE)
        print(f"wrote {p}; API token will be created at <data_dir>/api_token on first serve")
        return

    cfg = cfgmod.load(a.config)
    if a.cmd == "serve":
        import uvicorn
        from .server import create_app
        app = create_app(cfg)
        if a.worker:
            from . import worker
            url = f"http://127.0.0.1:{cfg.api_port}"
            threading.Thread(target=lambda: (time.sleep(1.5), worker.run(url, cfg.token(), cfg)), daemon=True).start()
        print(f"G-Box on http://{cfg.api_host}:{cfg.api_port}  token file: {cfg.data_dir / 'api_token'}")
        uvicorn.run(app, host=cfg.api_host, port=cfg.api_port, log_level="warning")
    elif a.cmd == "worker":
        from . import worker
        worker.run(a.server, cfg.token(), cfg, a.name)
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
        print(f"G-Box setup on {provision.HOST_OS}/{provision.ARCH}")
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
