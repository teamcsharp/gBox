"""Preview or retire one overdue read-only tasks/list request using fresh evidence.

This is a timeout outcome, not proof that a thread stopped. No process action,
job cancellation, resubmission, success receipt or gameplay change is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sqlite3
import stat
import time
import tomllib
from urllib.parse import urlsplit

MIN_AGE = 300
MAX_AGE = 30
MAX_NAMESPACES = 128
MAX_TEMP_BYTES = 16 * 1024 * 1024
MAX_TEMP_FILES = 32


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _fresh(value, now):
    return _time(value) and -5 <= now - value <= MAX_AGE


def _option(args, option):
    return args[args.index(option) + 1] if args.count(option) == 1 and args.index(option) + 1 < len(args) else None


def _leaf(processes, config, server, name):
    if not isinstance(processes, list) or not 1 <= len(processes) <= 4:
        raise ValueError("Expected a bounded worker process chain")
    for p in processes:
        if (not isinstance(p,dict) or type(p.get("pid")) is not int or p["pid"] <= 0
                or type(p.get("ppid")) is not int or p["ppid"] < 0 or p["pid"] == p["ppid"]
                or not _time(p.get("created")) or not isinstance(p.get("exe"),str) or not p["exe"]
                or p.get("name") != name or p.get("server") != server or p.get("config") != str(config)):
            raise ValueError("Invalid worker process identity")
    by_id = {p["pid"]:p for p in processes}
    if len(by_id) != len(processes):
        raise ValueError("Repeated worker PID")
    parents = {p["ppid"] for p in processes}
    leaves = [p for p in processes if p["pid"] not in parents]
    if len(leaves) != 1:
        raise ValueError("Expected one actual worker process")
    current, visited = leaves[0], set()
    while current["pid"] not in visited:
        visited.add(current["pid"])
        if current["ppid"] not in by_id:
            break
        parent = by_id[current["ppid"]]
        if parent["created"] > current["created"]:
            raise ValueError("Worker launcher is newer than its child")
        current = parent
    if visited != set(by_id):
        raise ValueError("Worker process records do not form one launcher chain")
    return leaves[0]


def _configured_runtime(config):
    """Read the same base/host-overlay runtime settings as Config.load, no secrets."""
    data, fingerprints = {}, {}
    for path in (config, config.with_name("gbox.local-" + platform.node().lower() + ".toml")):
        if not path.exists():
            continue
        with path.open("rb") as stream:
            raw = stream.read(1024*1024+1)
        if len(raw)>1024*1024:
            raise ValueError("Configuration exceeds supported size")
        fingerprints[str(path)] = hashlib.sha256(raw).hexdigest()
        for key,value in tomllib.loads(raw.decode("utf-8")).items():
            data[key] = data.get(key,{}) | value if isinstance(value,dict) and isinstance(data.get(key),dict) else value
    host = platform.system().lower()
    custom = (data.get("runtime_dirs") or {}).get(host)
    if custom:
        runtime = Path(os.path.expandvars(custom))
    else:
        directory = Path(data.get("data_dir","gbox-data"))
        if not directory.is_absolute(): directory = config.parent/directory
        runtime = directory/("runtime-"+host+"-"+platform.machine().lower())
    return runtime.resolve(strict=True), fingerprints


def _processes(config, server, name):
    """Read only Python process identities; never invoke the tasks/kill tool."""
    import psutil
    found = []
    for proc in psutil.process_iter(["pid", "name"]):
        if not (proc.info.get("name") or "").lower().startswith("python"):
            continue
        try:
            args = proc.cmdline()
            if _option(args, "-m") != "gbox" or "worker" not in args:
                continue
            if (_option(args, "--name") or platform.node()) != name:
                continue
            if (_option(args, "--server") or "").rstrip("/") != server or not _option(args, "--config"):
                raise ValueError("Another same-name worker has different server/configuration")
            if Path(_option(args, "--config")).resolve() != config:
                raise ValueError("Another same-name worker has different configuration")
            found.append({"pid": proc.pid, "ppid": proc.ppid(), "created": proc.create_time(),
                          "exe": proc.exe(), "name": name, "server": server, "config": str(config)})
        except psutil.NoSuchProcess as exc:
            raise ValueError("Python process inventory changed; collect fresh evidence") from exc
        except psutil.AccessDenied as exc:
            raise ValueError("Cannot inspect a Python process; worker uniqueness is unverified") from exc
    # Windows venv launchers are ancestors with the same explicit identity.
    return sorted(found, key=lambda p: p["pid"]), _leaf(found,config,server,name)



def _redirected(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _old_temporary(path, namespace, job_id, now):
    """Describe an unrelated abandoned atomic-write file without changing it."""
    if not re.fullmatch(r"[0-9a-f]{64}\.json\.[0-9a-f]{32}\.tmp", path.name):
        raise ValueError("Unknown outbox file needs review")
    path_before = path.stat()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_TEMP_BYTES:
            raise ValueError("Temporary outbox evidence exceeds supported size/type")
        raw = stream.read(MAX_TEMP_BYTES + 1)
        after = os.fstat(stream.fileno())
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    # Windows Python 3.12 can report different creation/ctime values through
    # fstat and stat. Compare each API to itself, then bind inode/size/mtime.
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    path_after = path.stat()
    if (signature(before) != signature(after) or signature(path_before) != signature(path_after)
            or identity(after) != identity(path_after) or len(raw) != after.st_size):
        raise ValueError("Temporary outbox evidence changed during observation")
    record = json.loads(raw)
    if not isinstance(record, dict):
        raise ValueError("Temporary result must be an object")
    result = record.get("result")
    result_id = result.get("job_id") if isinstance(result, dict) else None
    if (type(record.get("version")) is not int or record["version"] != 1
            or not isinstance(result_id, str) or not re.fullmatch(r"[0-9a-f]{16}", result_id)
            or result_id == job_id or path.name.split(".")[0] != hashlib.sha256(result_id.encode()).hexdigest()
            or record.get("status") not in ("pending", "acknowledged", "rejected")
            or not isinstance(record.get("server"), str) or not isinstance(record.get("name"), str)
            or namespace != hashlib.sha256((record["server"] + "\0" + record["name"]).encode()).hexdigest()[:24]
            or record.get("result_sha256") != _digest(result)
            or not _time(record.get("created")) or now - record["created"] < MIN_AGE
            or not _time(after.st_mtime) or now - after.st_mtime < MIN_AGE):
        raise ValueError("Unsettled or unidentified temporary outbox evidence needs review")
    return {"path": str(path), "namespace": namespace, "job_id": result_id,
            "file_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "mtime": after.st_mtime, "record_created": record["created"],
            "status": record["status"], "result_sha256": record["result_sha256"]}


def observe_worker(runtime, config, server, name, worker_id, job_id, *, expected_pid):
    """Collect fresh local process/outbox evidence without importing worker tools."""
    if platform.node().casefold() != name.casefold():
        raise ValueError("Observation must run on the named worker host")
    if any(not re.fullmatch(r"[0-9a-f]{16}", v) for v in (worker_id, job_id)):
        raise ValueError("Expected exact worker/job IDs")
    server = server.rstrip("/")
    parsed = urlsplit(server)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Expected a credential-free control-plane URL")
    config, runtime = Path(config).resolve(strict=True), Path(runtime).resolve(strict=True)
    configured, fingerprints = _configured_runtime(config)
    if configured != runtime:
        raise ValueError("Observed runtime differs from worker configuration")
    processes, worker = _processes(config, server, name)
    if type(expected_pid) is not int or worker["pid"] != expected_pid:
        raise ValueError("Actual worker PID differs from the expected process")
    root = runtime / "worker-results"
    if not root.is_dir() or _redirected(root):
        raise ValueError("Expected an existing local result-outbox root")
    children = sorted(root.iterdir())
    if not 1 <= len(children) <= MAX_NAMESPACES:
        raise ValueError("Unexpected result namespace inventory")
    target = hashlib.sha256(job_id.encode()).hexdigest() + ".json"
    namespaces, pending, target_paths, old_temporary = [], [], [], []
    observed = time.time()
    for namespace in children:
        if _redirected(namespace) or not namespace.is_dir() or not re.fullmatch(r"[0-9a-f]{24}", namespace.name):
            raise ValueError("Unrecognized result namespace entry")
        namespaces.append(namespace.name)
        for entry in sorted(namespace.iterdir()):
            if _redirected(entry):
                raise ValueError("Redirected outbox entry needs review")
            if entry.is_file():
                if entry.name.startswith(target.removesuffix(".json") + "."):
                    target_paths.append(str(entry))
                if entry.suffix == ".json":
                    pending.append(str(entry))
                elif entry.name.startswith(target.removesuffix(".json") + "."):
                    pending.append(str(entry))
                else:
                    if len(old_temporary) >= MAX_TEMP_FILES:
                        raise ValueError("Too many abandoned temporary result files")
                    old_temporary.append(_old_temporary(entry, namespace.name, job_id, observed))
            elif entry.name not in ("acknowledged", "rejected", "refused-evidence") or not entry.is_dir():
                raise ValueError("Unexpected outbox directory needs review")
        for label in ("acknowledged", "rejected", "refused-evidence"):
            directory = namespace / label
            if directory.exists():
                if _redirected(directory) or not directory.is_dir():
                    raise ValueError("Redirected result directory needs review")
                for entry in sorted(directory.iterdir()):
                    if _redirected(entry) or not entry.is_file():
                        raise ValueError("Unexpected nested result evidence needs review")
                    if entry.name.startswith(target.removesuffix(".json") + "."):
                        target_paths.append(str(entry))
                    if label == "rejected":
                        pending.append(str(entry))
    expected_namespace = hashlib.sha256((server + "\0" + name).encode()).hexdigest()[:24]
    if expected_namespace not in namespaces:
        raise ValueError("Current worker result namespace is missing")
    # Recheck the same process after reading all outbox locations.
    import psutil
    if psutil.Process(expected_pid).create_time() != worker["created"]:
        raise ValueError("Worker process identity changed during observation")
    return {"version": 1, "job_id": job_id, "worker_id": worker_id, "worker_name": name,
            "host": platform.node(), "server": server, "runtime": str(runtime), "config": str(config),
            "observed_at": time.time(), "worker_process": worker, "process_chain": processes,
            "configuration_sha256": fingerprints,
            "namespaces": namespaces, "current_namespace": expected_namespace,
            "target_filename": target, "target_paths": target_paths, "pending_paths": pending,
            "old_temporary_evidence": old_temporary}


def retire_inventory(db, job_id, *, expected_job_sha256, expected_worker, evidence,
                     apply=False, now=None, actor="operator-maintenance"):
    """CAS one exact overdue tasks/list job to failed, with an atomic audit record."""
    from .store import append_audit
    now = time.time() if now is None else now
    if not _time(now) or db.in_transaction:
        raise ValueError("Recovery requires a valid clock and its own transaction")
    db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
    try:
        row = db.execute("SELECT body FROM docs WHERE kind='job' AND id=?", (job_id,)).fetchone()
        original = row[0] if row else None
        job = json.loads(original) if original else None
        if not original or hashlib.sha256(original.encode()).hexdigest() != expected_job_sha256:
            raise ValueError("Exact expected job snapshot no longer matches")
        if (job.get("id") != job_id or job.get("tool") != "tasks" or job.get("input") != {"op": "list", "pid": None}
                or job.get("state") != "running" or job.get("worker_id") != expected_worker
                or job.get("require_worker") != expected_worker or job.get("cancel")
                or any(job.get(k) is not None for k in ("finished", "output", "error", "receipt_id", "result_sha256", "result_acceptance", "result_state"))
                or not _time(job.get("started")) or now - job["started"] < MIN_AGE):
            raise ValueError("Expected an overdue claimed read-only tasks/list job without a result")
        if db.execute("SELECT 1 FROM docs WHERE kind IN ('receipt','late_result') AND json_extract(body,'$.job_id')=? LIMIT 1", (job_id,)).fetchone():
            raise ValueError("Durable result evidence already exists")
        audits = db.execute("SELECT action,data FROM audit WHERE subject=? ORDER BY seq", (job_id,)).fetchall()
        if ([a[0] for a in audits] != ["job.submit", "job.claim"]
                or json.loads(audits[0][1]).get("input") != job["input"]
                or json.loads(audits[0][1]).get("tool") != "tasks"
                or json.loads(audits[1][1]).get("worker") != expected_worker):
            raise ValueError("Submission/claim audit history is not the exact uncompleted inventory request")
        row = db.execute("SELECT body FROM docs WHERE kind='worker' AND id=?", (expected_worker,)).fetchone()
        worker = json.loads(row[0]) if row else {}
        if (worker.get("id") != expected_worker or not _fresh(worker.get("last_seen"), now)
                or any(type(worker.get(k)) is not int or worker[k] != 0 for k in ("active_jobs", "pending_results"))
                or "tasks" not in (worker.get("tools") or [])
                or not {"independent_heartbeat", "durable_result_delivery"}.issubset(worker.get("features") or [])):
            raise ValueError("Worker needs fresh idle and durable-result heartbeat evidence")
        others = db.execute("SELECT id,body FROM docs WHERE kind='worker' AND lower(json_extract(body,'$.name'))=lower(?)",(worker.get("name"),)).fetchall()
        if any(wid != expected_worker and _fresh(json.loads(body).get("last_seen"),now) for wid,body in others):
            raise ValueError("Another fresh worker identity uses the same host name")
        if (not isinstance(evidence, dict) or type(evidence.get("version")) is not int or evidence["version"] != 1 or evidence.get("job_id") != job_id
                or evidence.get("worker_id") != expected_worker or evidence.get("worker_name") != worker.get("name")
                or evidence.get("host", "").casefold() != worker.get("name", "").casefold()
                or not _fresh(evidence.get("observed_at"), now)
                or evidence.get("target_paths") != [] or evidence.get("pending_paths") != []
                or evidence.get("target_filename") != hashlib.sha256(job_id.encode()).hexdigest() + ".json"):
            raise ValueError("Fresh matching local evidence must show no pending or target result")
        namespaces = evidence.get("namespaces")
        server, name = evidence.get("server"), worker["name"]
        if (not isinstance(server, str) or not isinstance(namespaces, list) or not 1 <= len(namespaces) <= MAX_NAMESPACES
                or any(not isinstance(n,str) or not re.fullmatch(r"[0-9a-f]{24}",n) for n in namespaces) or len(set(namespaces)) != len(namespaces)
                or evidence.get("current_namespace") != hashlib.sha256((server + "\0" + name).encode()).hexdigest()[:24]
                or evidence["current_namespace"] not in namespaces):
            raise ValueError("Incomplete local result namespace evidence")
        temporary = evidence.get("old_temporary_evidence")
        if not isinstance(temporary, list) or len(temporary) > MAX_TEMP_FILES:
            raise ValueError("Incomplete temporary outbox evidence")
        for item in temporary:
            if (not isinstance(item, dict) or not isinstance(item.get("job_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{16}", item["job_id"]) or item["job_id"] == job_id
                    or item.get("namespace") not in namespaces or not isinstance(item.get("path"), str)
                    or not re.fullmatch(hashlib.sha256(item["job_id"].encode()).hexdigest() + r"\.json\.[0-9a-f]{32}\.tmp", re.split(r"[/\\]", item["path"])[-1])
                    or type(item.get("bytes")) is not int or not 0 < item["bytes"] <= MAX_TEMP_BYTES
                    or item.get("status") not in ("pending", "acknowledged", "rejected")
                    or any(not isinstance(item.get(k), str) or not re.fullmatch(r"[0-9a-f]{64}", item[k]) for k in ("file_sha256", "result_sha256"))
                    or any(not _time(item.get(k)) or item[k] >= job["started"] for k in ("mtime", "record_created"))):
                raise ValueError("Temporary result evidence must identify another job before this claim")
        proc, chain = evidence.get("worker_process") or {}, evidence.get("process_chain")
        if (proc != _leaf(chain,evidence.get("config"),server,name) or proc["created"] > job["started"]
                or any(p["created"] > evidence["observed_at"] for p in chain)
                or not isinstance(evidence.get("configuration_sha256"),dict)
                or evidence.get("config") not in evidence["configuration_sha256"]
                or any(not isinstance(v,str) or not re.fullmatch(r"[0-9a-f]{64}",v) for v in evidence["configuration_sha256"].values())):
            raise ValueError("Expected worker process/configuration identity is not established")
        reason = "Read-only process inventory exceeded its delivery timeout without a result. No process was stopped; a later result will be retained only as evidence."
        after = job | {"state": "failed", "finished": now, "error": reason,
                       "inventory_timeout": {"evidence_sha256": _digest(evidence), "observed_at": evidence["observed_at"]}}
        proof = {"before": job, "after": after, "worker": {k:worker.get(k) for k in ("id","name","last_seen","active_jobs","pending_results")},
                 "local_evidence": evidence, "read_only_inventory_timeout": True, "process_action": None,
                 "reason": reason, "observed_at": now}
        result = {"applied": False, "audit_seq": None, **proof}
        if apply:
            changed = db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? AND body=?", (json.dumps(after),job_id,original)).rowcount
            if changed != 1:
                raise ValueError("Inventory job changed during retirement")
            result["audit_seq"] = append_audit(db,actor,"job.failed",job_id,proof,ts=now)
            db.commit(); result["applied"] = True
        else:
            db.rollback()
        return result
    except BaseException:
        db.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    observe = commands.add_parser("observe", help="Read local worker processes/outboxes only")
    for flag in ("runtime", "config", "server", "name", "worker-id", "job-id"):
        observe.add_argument("--" + flag, required=True)
    observe.add_argument("--expected-pid", type=int, required=True)
    recover = commands.add_parser("retire", help="Preview exact retirement; --apply is explicit")
    recover.add_argument("--database", type=Path, required=True)
    recover.add_argument("--job-id", required=True)
    recover.add_argument("--expected-worker", required=True)
    recover.add_argument("--expected-job-sha256", required=True)
    recover.add_argument("--evidence", type=Path, required=True)
    recover.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "observe":
        result = observe_worker(args.runtime,args.config,args.server,args.name,args.worker_id,args.job_id,expected_pid=args.expected_pid)
    else:
        with args.evidence.open("rb") as stream:
            raw = stream.read(1024*1024+1)
        if len(raw)>1024*1024:
            raise ValueError("Local evidence exceeds the supported size")
        evidence=json.loads(raw)
        db=sqlite3.connect(args.database.resolve().as_uri()+("?mode=rw" if args.apply else "?mode=ro"),uri=True,timeout=5)
        try:
            if not args.apply: db.execute("PRAGMA query_only=ON")
            result=retire_inventory(db,args.job_id,expected_job_sha256=args.expected_job_sha256,expected_worker=args.expected_worker,evidence=evidence,apply=args.apply)
        finally: db.close()
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__ == "__main__":
    main()
