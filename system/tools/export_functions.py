"""CP3: export labelled-ready function rows from the Ghidra project.

Run with the pyghidra venv:
    D:\\gBox\\runtime\\pyghidra-venv\\Scripts\\python.exe system/tools/export_functions.py [--all]

Writes ``D:\\gBox\\pso-ds\\llm\\functions.jsonl``, one row per function:

    {"address": "80103748", "size": 88, "name": "FUN_80103748", "callers": [...], "callees": [...],
     "strings": ["..."], "c": "<decompiled C, 6 KB cap, names stripped>"}

Selection (unless ``--all``): the five neighbourhoods CP3 lists first -
* ``0x8028f508`` and its callers (CP12's model-walk crash);
* code that references ``TObjCityDoor`` names and the door vtables (CP15);
* ``CARD*`` SDK callers (CP9);
* the ``.evt`` interpreter's callers (CP7);
* the scene ``n.rel`` / ``r.rel`` loader (CP8);
plus the functions that reference those strings, their callers and their callees (one hop), so a model sees context
instead of isolated routines.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

OUT = pathlib.Path(r"D:\gBox\pso-ds\llm\functions.jsonl")
SEEDS = ["8028f508"]
PATTERNS = re.compile(r"(TObjCityDoor|CARD|\.evt|n\.rel|r\.rel|map_lobby|map_forest|map_city|HUNTER GUILD|"
                      r"ITEM STORE|CHECK ROOM|JUDGMENT)", re.I)
C_CAP = 6 * 1024


def strip_names(c: str, own_address: str) -> str:
    """The same address-free strip the gold set uses (own symbol -> this_function, callees -> callee_N)."""
    c = re.sub(r"\b(?:thunk_)?FUN_([0-9a-fA-F]{8})\b", lambda m: "sub_" + m.group(1).lower(), c)
    c = re.sub(r"\bsub_" + own_address.lower() + r"\b", "this_function", c)
    seen = {}

    def callee(m):
        key = m.group(0)
        if key not in seen:
            seen[key] = f"callee_{len(seen) + 1}"
        return seen[key]

    c = re.sub(r"\bsub_[0-9a-f]{8}\b", callee, c)
    return re.sub(r"\bentry\b", "this_function", c)


def main() -> int:
    every = "--all" in sys.argv
    os.environ.setdefault("GHIDRA_INSTALL_DIR", r"D:\gBox\runtime\ghidra_12.1.4_PUBLIC")
    os.environ.setdefault("JAVA_HOME", r"D:\gBox\runtime\jdk-21.0.12.1+1")
    import pyghidra

    pyghidra.start()
    from ghidra.app.decompiler import DecompInterface
    from ghidra.program.model.data import StringDataType
    from ghidra.util.task import ConsoleTaskMonitor

    rows = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with pyghidra.open_project(r"D:\gBox\ghidra-pso\PSO", "PSO") as project:
        root = project.getProjectData().getRootFolder()
        pathname = next(f.getPathname() for f in root.getFiles() if f.getName().endswith(".elf"))
        with pyghidra.program_context(project, pathname) as program:
            monitor = ConsoleTaskMonitor()
            dec = DecompInterface()
            dec.openProgram(program)
            fman = program.getFunctionManager()
            refman = program.getReferenceManager()
            listing = program.getListing()

            # function -> referenced strings, via defined string data and references into it
            func_strings: dict[int, list[str]] = {}
            data_iter = listing.getDefinedData(True)
            count = 0
            while data_iter.hasNext():
                d = data_iter.next()
                if not isinstance(d.getDataType(), StringDataType):
                    continue
                try:
                    text = str(d.getValue())
                except Exception:                    # noqa: BLE001
                    continue
                if not text:
                    continue
                count += 1
                for ref in refman.getReferencesTo(d.getAddress()):
                    f = fman.getFunctionContaining(ref.getFromAddress())
                    if f is not None:
                        func_strings.setdefault(f.getEntryPoint().getOffset(), []).append(text[:160])
                if count > 60000:
                    break
            print(f"string data scanned: {count}, functions with strings: {len(func_strings)}", flush=True)

            def wanted(offset: int, strings) -> bool:
                if offset in seeds:
                    return True
                return any(PATTERNS.search(s) for s in (strings or []))

            seeds = {int(a, 16) for a in SEEDS}
            selected = {}
            f = fman.getFunctionAt(program.getAddressFactory().getDefaultAddressSpace().getAddress(0x8028F508))
            if f is not None:
                selected[f.getEntryPoint().getOffset()] = f
            for offset, strings in func_strings.items():
                if wanted(offset, strings):
                    fn = fman.getFunctionAt(program.getAddressFactory().getDefaultAddressSpace().getAddress(offset))
                    if fn is not None:
                        selected[offset] = fn
            print(f"seed functions: {len(selected)}", flush=True)

            # one hop of callers and callees around the seeds
            frontier = dict(selected)
            for fn in list(selected.values()):
                for callee in fn.getCalledFunctions(monitor):
                    frontier.setdefault(callee.getEntryPoint().getOffset(), callee)
                for caller in fn.getCallingFunctions(monitor):
                    frontier.setdefault(caller.getEntryPoint().getOffset(), caller)
            print(f"with one hop: {len(frontier)}", flush=True)

            if every:
                frontier = {fn.getEntryPoint().getOffset(): fn for fn in fman.getFunctions(True)}
                print(f"--all: {len(frontier)} functions", flush=True)

            with OUT.open("w", encoding="utf-8") as fh:
                done = 0
                for offset, fn in sorted(frontier.items()):
                    res = dec.decompileFunction(fn, 90, monitor)
                    c = res.getDecompiledFunction().getC() if res and res.getDecompiledFunction() else ""
                    if not c:
                        continue
                    hexaddr = f"{offset:08x}"
                    row = {"address": hexaddr, "size": fn.getBody().getNumAddresses(), "name": fn.getName(),
                           "callers": sorted(f"{x.getEntryPoint().getOffset():08x}" for x in fn.getCallingFunctions(monitor)),
                           "callees": sorted(f"{x.getEntryPoint().getOffset():08x}" for x in fn.getCalledFunctions(monitor)),
                           "strings": list(dict.fromkeys(func_strings.get(offset, [])))[:12],
                           "c": strip_names(c, hexaddr)[:C_CAP]}
                    fh.write(json.dumps(row) + "\n")
                    done += 1
                    if done % 50 == 0:
                        print(f"  {done}/{len(frontier)} exported", flush=True)
    print(f"wrote {OUT} rows={done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
