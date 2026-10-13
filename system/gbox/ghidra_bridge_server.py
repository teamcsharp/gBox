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
import os
import re
import sys
import traceback
import warnings


class Bridge:
    """Query operations over one open Ghidra program. Every result is plain JSON data."""

    def __init__(self):
        self.flat = self.program = self.project = self._ctx = None
        self._decomp = None

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
        return {"name": p.getName(), "language": str(p.getLanguageID()), "compiler": str(p.getCompilerSpec().getCompilerSpecID()),
                "image_base": "0x" + str(p.getImageBase()), "functions": p.getFunctionManager().getFunctionCount(),
                "executable_path": p.getExecutablePath(), "executable_md5": p.getExecutableMD5()}

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

    def xrefs_from(self, target, **_):
        f = self._function(target)
        p, data = self._need(), []
        rm = p.getReferenceManager()
        for a in rm.getReferenceSourceIterator(f.getBody(), True):
            for ref in rm.getReferencesFrom(a):
                if ref.getReferenceType().isData():
                    data.append({"from": "0x" + str(a), "to": "0x" + str(ref.getToAddress()), "type": str(ref.getReferenceType())})
        return self._fn_entry(f) | {"callees": self._callees(f), "data_refs": data[:500]}

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

    def export(self, export_dir, limit=0, **_):
        """Write Dryxio/ghidra-bridge's export layout so its CLI and ReAgent can read this program offline."""
        os.makedirs(export_dir, exist_ok=True)
        fm, index, n = self._need().getFunctionManager(), {}, 0
        for f in fm.getFunctions(True):
            d = self.decompile("0x" + str(f.getEntryPoint()))
            addr = str(f.getEntryPoint())
            callers = [{"addr": c["function_address"][2:], "name": c["function"], "ref_type": c["type"]}
                       for c in d["callers"] if c.get("function_address")]
            callees = [{"addr": c["address"][2:], "name": c["name"]} for c in d["callees"]]
            rec = {"address": addr, "name": f.getName(), "signature": d["signature"],
                   "calling_convention": d["calling_convention"], "return_type": str(f.getReturnType()),
                   "parameter_count": f.getParameterCount(), "is_thunk": f.isThunk(),
                   "decompiled": d["decompiled"] or f"// Decompilation failed: {d['error']}",
                   "callers": callers, "callees": callees, "data_refs": []}
            with open(os.path.join(export_dir, addr.replace(":", "_") + ".json"), "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=1)
            index[addr] = {"name": f.getName(), "address": addr, "num_callers": len(callers), "num_callees": len(callees)}
            n += 1
            if limit and n >= int(limit):
                break
        with open(os.path.join(export_dir, "_index.json"), "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=1)
        strings = {s["address"][2:]: {"address": s["address"][2:], "value": s["value"], "length": len(s["value"]),
                                      "type": s["type"], "references": [{"func_addr": (r["function_address"] or "")[2:],
                                                                         "func_name": r["function"], "ref_addr": r["from"][2:]}
                                                                        for r in s["references"]]}
                   for s in self.strings(limit=10 ** 9)["strings"]}
        with open(os.path.join(export_dir, "_strings.json"), "w", encoding="utf-8") as fh:
            json.dump(strings, fh, indent=1)
        return {"export_dir": export_dir, "functions": n, "strings": len(strings)}


OPS = {"open", "close", "info", "functions", "decompile", "xrefs_to", "xrefs_from", "containing", "strings", "run_script",
       "export"}


def serve(bridge, stdin, stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid, op = req.get("id"), req.get("op")
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}; ops: {sorted(OPS)}")
            reply = {"id": rid, "result": getattr(bridge, op)(**(req.get("args") or {}))}
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
