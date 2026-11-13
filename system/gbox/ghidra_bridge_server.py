"""gBox Ghidra Bridge server: one program held open inside the operator's Ghidra (PyGhidra), queried over stdio.

Started by gbox/ghidra_bridge.py as `<python with pyghidra> -I ghidra_bridge_server.py`, with GHIDRA_INSTALL_DIR and
JAVA_HOME in its environment. Protocol: one JSON object per line.
  request  {"id": 1, "op": "decompile", "args": {"target": "0x401000"}}
  response {"id": 1, "result": {...}}   or   {"id": 1, "error": "TypeError: ..."}
Ghidra's own logging goes to stderr so stdout carries only protocol lines.

The ops mirror Dryxio/ghidra-bridge's query surface (MIT; https://github.com/Dryxio/ghidra-bridge): decompile by
address or name, callers/callees, string search with references, containing-function lookup, function search, plus
`export`, which writes the same JSON export layout that project's CLI and ReAgent read (_index.json, one
<address>.json per function, _strings.json). This file is gBox's own implementation, not a copy of that code.

Standalone on purpose: it imports only the standard library and pyghidra, so it runs in Ghidra's PyGhidra venv.
"""
import json
import hashlib
import os
import re
import sys
import threading
import time
import traceback
import uuid
import warnings


class Bridge:
    """Query operations over one open Ghidra program. Every result is plain JSON data."""

    def __init__(self):
        self.flat = self.program = self.project = self._ctx = None
        self._decomp = None
        self._request_lock = threading.RLock()

    def dispatch(self, op, args=None):
        """Check a pinned target and execute its operation in one serialized request."""
        if op not in OPS:
            raise ValueError(f"unknown op {op!r}; ops: {sorted(OPS)}")
        if args is not None and not isinstance(args, dict):
            raise ValueError("operation args must be an object")
        params = dict(args or {})
        # An older running bridge accepts arbitrary **kwargs on queries. A new
        # protocol op makes that server reject a guarded script before running
        # it, instead of silently ignoring the expected target parameters.
        wrapped = op == "guarded"
        if wrapped:
            op = params.pop("operation", None)
            if op not in GUARDED_OPS:
                raise ValueError("guarded requests require a query, script or export operation")
        guarded = "expected_binary_path" in params or "expected_sha256" in params
        with self._request_lock:
            if guarded or wrapped:
                if op not in GUARDED_OPS:
                    raise ValueError("target guards apply to queries, scripts and exports, not lifecycle operations")
                self._check_target(params.pop("expected_binary_path", None), params.pop("expected_sha256", None))
            return getattr(self, op)(**params)

    def _check_target(self, expected_binary_path, expected_sha256):
        expected_path = canonical_binary_path(expected_binary_path)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be a complete SHA-256 digest")
        program = self._need()
        actual_path = program.getExecutablePath()
        if actual_path is None or canonical_binary_path(str(actual_path)) != expected_path:
            raise RuntimeError("Ghidra target changed: the open executable path differs from the pinned analysis input")
        getter = getattr(program, "getExecutableSHA256", None)
        actual_sha = getter() if callable(getter) else None
        if actual_sha is None or str(actual_sha).lower() != expected_sha256.lower():
            raise RuntimeError("Ghidra target changed: the loaded executable SHA-256 differs or is unavailable")

    # --- lifecycle ---------------------------------------------------------------------------------------------------
    def open(self, binary_path=None, project_dir=None, project_name=None, program_name=None, processor=None,
             analyze=True, **_):
        import pyghidra
        if self._ctx is not None:
            self.close()
        if not pyghidra.started():
            pyghidra.start(verbose=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            # an existing operator project is a plain (non-nested) Ghidra project directory
            nested = binary_path is not None and not program_name
            self._ctx = pyghidra.open_program(binary_path, project_location=project_dir, project_name=project_name,
                                              analyze=bool(analyze), language=processor, program_name=program_name,
                                              nested_project_location=nested)
            self.flat = self._ctx.__enter__()
        self.program = self.flat.getCurrentProgram()
        return self.info()

    def close(self, **_):
        ctx, self._ctx = self._ctx, None
        if self._decomp is not None:
            self._decomp.dispose()
            self._decomp = None
        if ctx is not None:
            ctx.__exit__(None, None, None)
        self.flat = self.program = None
        return {"closed": True}

    def _need(self):
        if self.program is None:
            raise RuntimeError("no program open: call op=open first")
        return self.program

    # --- helpers -----------------------------------------------------------------------------------------------------
    def _addr(self, text):
        p = self._need()
        a = p.getAddressFactory().getAddress(str(text))
        if a is None:
            raise ValueError(f"not an address in this program: {text!r}")
        return a

    def _function(self, target):
        """target: 0x-hex address (entry or any address inside) or an exact/unique function name."""
        p = self._need()
        fm = p.getFunctionManager()
        t = str(target).strip()
        if re.fullmatch(r"(0x)?[0-9a-fA-F]+", t) and (t.lower().startswith("0x") or not t.isalpha()):
            a = self._addr(t)
            f = fm.getFunctionAt(a) or fm.getFunctionContaining(a)
            if f is None:
                raise LookupError(f"no function at or containing {t}")
            return f
        hits = [f for f in fm.getFunctions(True) if f.getName() == t or f.getName(True) == t]
        if not hits:
            raise LookupError(f"no function named {t!r}")
        return hits[0]

    @staticmethod
    def _fn_entry(f):
        return {"address": "0x" + str(f.getEntryPoint()), "name": f.getName(True)}

    def _callers(self, f):
        p = self._need()
        fm, rm, out = p.getFunctionManager(), p.getReferenceManager(), []
        for ref in rm.getReferencesTo(f.getEntryPoint()):
            c = fm.getFunctionContaining(ref.getFromAddress())
            out.append({"from": "0x" + str(ref.getFromAddress()), "type": str(ref.getReferenceType()),
                        **({"function": c.getName(True), "function_address": "0x" + str(c.getEntryPoint())} if c else {})})
        return out

    def _callees(self, f):
        p = self._need()
        fm, rm, seen, out = p.getFunctionManager(), p.getReferenceManager(), set(), []
        for a in rm.getReferenceSourceIterator(f.getBody(), True):
            for ref in rm.getReferencesFrom(a):
                if not ref.getReferenceType().isCall():
                    continue
                c = fm.getFunctionAt(ref.getToAddress())
                key = str(ref.getToAddress())
                if key in seen:
                    continue
                seen.add(key)
                out.append({"address": "0x" + key, "name": c.getName(True) if c else None, "from": "0x" + str(a)})
        return out

    def _decompiler(self):
        if self._decomp is None:
            from ghidra.app.decompiler import DecompInterface
            self._decomp = DecompInterface()
            self._decomp.openProgram(self._need())
        return self._decomp

    # --- ops ---------------------------------------------------------------------------------------------------------
    def info(self, **_):
        p = self._need()
        getter = getattr(p, "getExecutableSHA256", None)
        return {"name": p.getName(), "language": str(p.getLanguageID()), "compiler": str(p.getCompilerSpec().getCompilerSpecID()),
                "image_base": "0x" + str(p.getImageBase()), "functions": p.getFunctionManager().getFunctionCount(),
                "executable_path": p.getExecutablePath(), "executable_md5": p.getExecutableMD5(),
                "executable_sha256": getter() if callable(getter) else None}

    def functions(self, query="", limit=100, offset=0, **_):
        fm, q, rows = self._need().getFunctionManager(), (query or "").lower(), []
        for f in fm.getFunctions(True):
            if q and q not in f.getName(True).lower():
                continue
            rows.append(self._fn_entry(f) | {"size": int(f.getBody().getNumAddresses())})
        return {"total": len(rows), "functions": rows[int(offset):int(offset) + int(limit)]}

    def decompile(self, target, timeout=60, **_):
        from ghidra.util.task import ConsoleTaskMonitor
        f = self._function(target)
        res = self._decompiler().decompileFunction(f, int(timeout), ConsoleTaskMonitor())
        ok = res is not None and res.decompileCompleted()
        return self._fn_entry(f) | {
            "signature": str(f.getSignature()), "calling_convention": str(f.getCallingConventionName()),
            "decompiled": res.getDecompiledFunction().getC() if ok else None,
            "error": None if ok else (res.getErrorMessage() if res is not None else "decompiler returned nothing"),
            "timed_out": bool(res is not None and res.isTimedOut()),
            "callers": self._callers(f), "callees": self._callees(f)}

    def xrefs_to(self, target, limit=200, **_):
        p = self._need()
        try:
            f = self._function(target)
            a = f.getEntryPoint()
        except LookupError:
            a = self._addr(target)
        fm, rows = p.getFunctionManager(), []
        for ref in p.getReferenceManager().getReferencesTo(a):
            c = fm.getFunctionContaining(ref.getFromAddress())
            rows.append({"from": "0x" + str(ref.getFromAddress()), "type": str(ref.getReferenceType()),
                         "function": c.getName(True) if c else None,
                         "function_address": "0x" + str(c.getEntryPoint()) if c else None})
            if len(rows) >= int(limit):
                break
        return {"target": "0x" + str(a), "xrefs": rows}

    def xrefs_from(self, target, limit=500, **_):
        f = self._function(target)
        p, data = self._need(), []
        rm = p.getReferenceManager()
        for a in rm.getReferenceSourceIterator(f.getBody(), True):
            for ref in rm.getReferencesFrom(a):
                if ref.getReferenceType().isData():
                    data.append({"from": "0x" + str(a), "to": "0x" + str(ref.getToAddress()), "type": str(ref.getReferenceType())})
        return self._fn_entry(f) | {"callees": self._callees(f), "data_refs": data[:limit] if limit else data,
                                    "data_refs_total": len(data), "truncated": bool(limit and len(data) > limit)}

    def containing(self, address, **_):
        f = self._need().getFunctionManager().getFunctionContaining(self._addr(address))
        return {"address": str(address), "function": self._fn_entry(f) if f else None}

    def strings(self, pattern="", limit=100, **_):
        p = self._need()
        fm, rm, rx, rows = p.getFunctionManager(), p.getReferenceManager(), re.compile(pattern or ".", re.I), []
        for d in p.getListing().getDefinedData(True):
            tn = d.getDataType().getName().lower()
            if "string" not in tn and "char[" not in tn and "unicode" not in tn:
                continue
            try:
                value = str(d.getValue())
            except Exception:  # noqa: BLE001 - undecodable data is skipped like upstream does
                continue
            if not rx.search(value):
                continue
            refs = []
            for ref in rm.getReferencesTo(d.getAddress()):
                c = fm.getFunctionContaining(ref.getFromAddress())
                refs.append({"from": "0x" + str(ref.getFromAddress()), "function": c.getName(True) if c else None,
                             "function_address": "0x" + str(c.getEntryPoint()) if c else None})
            rows.append({"address": "0x" + str(d.getAddress()), "value": value, "type": d.getDataType().getName(), "references": refs})
            if len(rows) >= int(limit):
                break
        return {"strings": rows}

    def run_script(self, script, args=(), script_dirs=(), **_):
        """Run any GhidraScript (Java/Python) against the open program; returns its stdout/stderr."""
        import pyghidra
        path = script
        if not os.path.isfile(path):
            path = next((os.path.join(d, script) for d in script_dirs if os.path.isfile(os.path.join(d, script))), None)
            if path is None:
                raise FileNotFoundError(f"script {script!r} not found in {list(script_dirs)}")
        run = getattr(pyghidra, "ghidra_script", None)
        if run is None:
            raise RuntimeError("this PyGhidra has no ghidra_script(); use Ghidra 11.3+ PyGhidra or the ghidra_script job")
        # Java scripts compile only from a registered source bundle (headless gets these from -scriptPath)
        from generic.jar import ResourceFile
        from ghidra.app.script import GhidraScriptUtil
        from java.io import File
        host = GhidraScriptUtil.getBundleHost()
        folder = ResourceFile(File(os.path.dirname(os.path.abspath(path))))
        if host.getExistingGhidraBundle(folder) is None:
            host.add(folder, True, False)
        out, err = run(path, None, self._need(), [str(a) for a in args], echo_stdout=False, echo_stderr=False)
        return {"script": os.path.basename(path), "stdout": str(out)[-20000:], "stderr": str(err)[-5000:]}

    def export(self, export_dir, limit=0, budget_s=120, function_timeout_s=30, retry_failed=False,
               retry_below_attempts=None, **_):
        """Resume a bounded batch. The manifest inventories every function; errors never count as decompiled source.

        `limit` is the attempts in this batch (0 uses 100), not a truncated program inventory. Each function and
        outcome is saved atomically, so process loss costs at most the running function. Legacy exports without
        an identity manifest are not silently adopted. The upstream function/index formats remain readable.
        """
        from pathlib import Path
        if not 5 <= float(budget_s) <= 3000 or not 1 <= int(function_timeout_s) <= 300:
            raise ValueError("export budget must be 5..3000 seconds and function timeout 1..300 seconds")
        maximum = int(limit) or 100
        if not 1 <= maximum <= 10000:
            raise ValueError("export batch limit must be 0..10000")
        started = time.monotonic()
        deadline = started + float(budget_s)
        directory = Path(export_dir)
        info = self.info()
        digest = str(info.get("executable_sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("export requires the loaded program's executable SHA-256")
        source = Path(str(info.get("executable_path") or ""))
        if not source.is_file() or _file_sha256(source) != digest:
            raise ValueError("loaded program and executable on disk do not match")
        functions = {str(f.getEntryPoint()): f for f in self._need().getFunctionManager().getFunctions(True)}
        if not functions:
            raise ValueError("no functions discovered: analyze the program before exporting")
        inventory = [{"address": a, "name": f.getName(True), "size": int(f.getBody().getNumAddresses())}
                     for a, f in functions.items()]
        inventory_hash = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
        directory.mkdir(parents=True, exist_ok=True)
        manifest_file = directory / "_manifest.json"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("version") != 1 or manifest.get("program") != info \
                    or manifest.get("inventory_sha256") != inventory_hash:
                raise ValueError("export program/inventory changed: use a new export directory")
        else:
            if any(directory.glob("*.json")):
                raise ValueError("existing export has no matching manifest: use a new export directory")
            manifest = {"version": 1, "program": info, "inventory": inventory,
                        "inventory_sha256": inventory_hash, "outcomes": {}, "strings_state": "pending"}
        outcomes = manifest["outcomes"]
        if any(a not in functions for a in outcomes):
            raise ValueError("export manifest contains functions outside this inventory")
        if any(row.get("state") not in {"pending", "running", "success", "error", "timeout"}
               for row in outcomes.values()):
            raise ValueError("export manifest contains an unknown outcome state")

        def save():
            manifest["updated_at"] = time.time()
            _atomic_json(manifest_file, manifest)

        # Recover interrupted calls and detect missing/corrupted cached source before reporting success.
        for addr, row in list(outcomes.items()):
            if row.get("state") == "running":
                row.update(state="pending", error="previous export interrupted")
            if row.get("state") == "success":
                path = directory / (addr.replace(":", "_") + ".json")
                if not path.is_file() or _file_sha256(path) != row.get("sha256"):
                    row.update(state="pending", error="cached function missing or corrupt")
        # A reader must not mistake a previous batch's summary for current completion during recovery/retry.
        manifest["summary"] = {"complete": False, "all_success": False, "batch_running": True}
        save()
        pending = [a for a in functions if outcomes.get(a, {}).get("state", "pending") == "pending"]
        retries = [a for a in functions if outcomes.get(a, {}).get("state") in ("error", "timeout")
                   and (retry_below_attempts is None or outcomes[a].get('attempts', 0) < int(retry_below_attempts))] if retry_failed else []
        attempted = 0
        for addr in pending + retries:
            remaining = deadline - time.monotonic() - 3
            if attempted >= maximum or remaining < 1:
                break
            f = functions[addr]
            attempt = outcomes.get(addr, {}).get("attempts", 0) + 1
            outcomes[addr] = {"state": "running", "attempts": attempt}
            save()
            attempted += 1
            try:
                d = self.decompile("0x" + addr, timeout=min(int(function_timeout_s), int(remaining)))
                if d.get("timed_out"):
                    raise TimeoutError(d.get("error") or "native decompiler timed out")
                if d.get("error") or not d.get("decompiled"):
                    raise RuntimeError(d.get("error") or "native decompiler returned no source")
                callers = [{"addr": c["function_address"][2:], "name": c["function"], "ref_type": c["type"]}
                           for c in d["callers"] if c.get("function_address")]
                callees = [{"addr": c["address"][2:], "name": c["name"]} for c in d["callees"]]
                refs = self.xrefs_from("0x" + addr, limit=0)
                rec = {"address": addr, "name": f.getName(), "signature": d["signature"],
                       "calling_convention": d["calling_convention"], "return_type": str(f.getReturnType()),
                       "parameter_count": f.getParameterCount(), "is_thunk": f.isThunk(),
                       "decompiled": d["decompiled"], "callers": callers, "callees": callees,
                       "data_refs": refs["data_refs"], "data_refs_truncated": refs["truncated"]}
                record_hash = _atomic_json(directory / (addr.replace(":", "_") + ".json"), rec)
                entry = {"name": f.getName(), "address": addr, "num_callers": len(callers), "num_callees": len(callees)}
                outcomes[addr] = {"state": "success", "attempts": attempt, "sha256": record_hash, "index": entry}
            except Exception as exc:
                outcomes[addr] = {"state": "timeout" if isinstance(exc, TimeoutError) else "error",
                                  "attempts": attempt, "error": f"{type(exc).__name__}: {exc}"[:2000]}
            save()
        index = {a: row["index"] for a, row in outcomes.items() if row["state"] == "success"}
        _atomic_json(directory / "_index.json", index)
        counts = {state: sum(outcomes.get(a, {}).get("state", "pending") == state for a in functions)
                  for state in ("pending", "running", "success", "error", "timeout")}
        # Strings are a separate resumable pass; scanning them never delays checkpointing function work.
        if not counts["pending"] and not counts["running"] and time.monotonic() < deadline - 3:
            self._export_strings(directory, manifest, deadline - 2)
        complete = not counts["pending"] and not counts["running"] and manifest["strings_state"] == "complete"
        summary = {"discovered": len(functions), **counts, "complete": complete,
                   "all_success": complete and not counts["error"] and not counts["timeout"],
                   "attempted_this_batch": attempted, "strings_state": manifest["strings_state"],
                   "elapsed_s": round(time.monotonic() - started, 3)}
        manifest["summary"] = summary
        save()
        return {"export_dir": str(directory), "functions": counts["success"],
                "strings": manifest.get("string_count", 0), **summary}

    def _export_strings(self, directory, manifest, deadline):
        path = directory / "_strings.json"
        if manifest.get("strings_state") == "complete" and path.is_file() \
                and _file_sha256(path) == manifest.get("strings_sha256"):
            return
        good = path.is_file() and _file_sha256(path) == manifest.get("strings_sha256")
        rows = json.loads(path.read_text(encoding="utf-8")) if good else {}
        after = manifest.get("strings_cursor") if good else None
        p = self._need()
        fm, rm = p.getFunctionManager(), p.getReferenceManager()
        listing = p.getListing()
        iterator = listing.getDefinedData(self._addr(after), True) if after else listing.getDefinedData(True)
        done = True
        cursor = after
        for data in iterator:
            addr = str(data.getAddress())
            if addr == after:
                continue
            if time.monotonic() >= deadline:
                done = False
                break
            cursor = addr
            typename = data.getDataType().getName()
            if not any(s in typename.lower() for s in ("string", "char[", "unicode")):
                continue
            value = str(data.getValue())
            refs = []
            for ref in rm.getReferencesTo(data.getAddress()):
                f = fm.getFunctionContaining(ref.getFromAddress())
                refs.append({"func_addr": str(f.getEntryPoint()) if f else "", "func_name": f.getName(True) if f else None,
                             "ref_addr": str(ref.getFromAddress())})
            rows[addr] = {"address": addr, "value": value, "length": len(value), "type": typename, "references": refs}
        sha = _atomic_json(path, rows)
        manifest.update(strings_state="complete" if done else "pending", strings_cursor=cursor,
                        strings_sha256=sha, string_count=len(rows))


OPS = {"open", "close", "info", "functions", "decompile", "xrefs_to", "xrefs_from", "containing", "strings", "run_script",
       "export", "guarded"}
GUARDED_OPS = OPS - {"open", "close", "guarded"}


def _file_sha256(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _atomic_json(path, data):
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return hashlib.sha256(payload).hexdigest()


def canonical_binary_path(value):
    """Bounded lexical identity only: never probe an arbitrary path or follow links."""
    if not isinstance(value, str) or not value or len(value) > 4096 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("expected_binary_path must be a bounded absolute file path without control characters")
    # Ghidra's executable-path metadata has no guaranteed naming convention;
    # Java sometimes stores a Windows drive path with a leading slash.
    if os.name == "nt" and re.match(r"^/[A-Za-z]:[/\\]", value):
        value = value[1:]
    if not os.path.isabs(value) or (os.name == "nt" and not os.path.splitdrive(value)[0]):
        raise ValueError("expected_binary_path must be an absolute file path on this worker")
    return os.path.normcase(os.path.normpath(value))


def serve(bridge, stdin, stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid, op = req.get("id"), req.get("op")
            reply = {"id": rid, "result": bridge.dispatch(op, req.get("args"))}
        except Exception as exc:  # noqa: BLE001 - every failure is reported to the caller, the server keeps running
            traceback.print_exc(file=sys.stderr)
            reply = {"id": rid, "error": f"{type(exc).__name__}: {exc}"}
        stdout.write(json.dumps(reply, default=str) + "\n")
        stdout.flush()


def main():
    proto = sys.stdout
    sys.stdout = sys.stderr           # Ghidra / JPype chatter must never reach the protocol stream
    bridge = Bridge()
    try:
        serve(bridge, sys.stdin, proto)
    finally:
        try:
            bridge.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
