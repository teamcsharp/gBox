"""CP2: export the gold set's decompiled C from the Ghidra project, with the names stripped.

Run with the pyghidra venv:
    D:\gBox\runtime\pyghidra-venv\Scripts\python.exe system/tools/export_decompiles.py

Writes ``D:\gBox\pso-ds\llm\decompiles.json``: for every address in ``GOLD`` (the code map proven in
``docs/research/pso-gc-executable.md`` section 3, plus the named routines in ``gbox/pso_ram.py``):

    {address: {"bytes": n, "ghidra_name": "FUN_...", "c": "<decompiled C with every FUN_xxxxxxxx renamed sub_XXXXXXXX>"}}

The names are stripped because CP2 asks a model to *infer* them; a model that can read ``FUN_80103748`` in the prompt is
being tested on recall of the address, not on the code.
"""
import json
import os
import pathlib
import re
import sys

ADDRESSES = [
    # the code map, docs/research/pso-gc-executable.md section 3 (address -> what it is)
    "8000c040", "8000f998", "8001e5c8", "800791bc", "8007a448", "80102ac0", "80103748", "801057a8", "8010b198",
    "8010b46c", "8010c740", "8010ccb0", "80154764", "80154788", "80192ccc", "80192d70", "80192dc4", "801b7998",
    "801b8310", "801b8e68", "801b9d50", "801b9f40", "801bab1c", "801bb330", "801d4f14", "801d5764", "802077cc",
    "80207e88", "80228540", "80229220",
    # named routines in gbox/pso_ram.py that the map does not repeat
    "801b8e68",
]


def main() -> int:
    out_path = pathlib.Path(r"D:\gBox\pso-ds\llm\decompiles.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("GHIDRA_INSTALL_DIR", r"D:\gBox\runtime\ghidra_12.1.4_PUBLIC")
    os.environ.setdefault("JAVA_HOME", r"D:\gBox\runtime\jdk-21.0.12.1+1")
    import pyghidra

    pyghidra.start()
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor

    addresses = sorted(set(a.lower() for a in ADDRESSES))
    out = {}
    with pyghidra.open_project(r"D:\gBox\ghidra-pso\PSO", "PSO") as project:
        root = project.getProjectData().getRootFolder()
        pathname = next(f.getPathname() for f in root.getFiles() if f.getName().endswith(".elf"))
        with pyghidra.program_context(project, pathname) as program:
            dec = DecompInterface()
            dec.openProgram(program)
            monitor = ConsoleTaskMonitor()
            space = program.getAddressFactory().getDefaultAddressSpace()
            for hexaddr in addresses:
                func = program.getFunctionManager().getFunctionAt(space.getAddress(int(hexaddr, 16)))
                if func is None:
                    print(f"{hexaddr}: no function", file=sys.stderr)
                    continue
                res = dec.decompileFunction(func, 90, monitor)
                c = res.getDecompiledFunction().getC() if res and res.getDecompiledFunction() else ""
                if not c:
                    print(f"{hexaddr}: decompile failed", file=sys.stderr)
                    continue
                out[hexaddr] = {"bytes": func.getBody().getNumAddresses(), "ghidra_name": func.getName(),
                                "c": strip_names(c, hexaddr)}
                print(f"{hexaddr} {func.getName()} {out[hexaddr]['bytes']}B -> {len(out[hexaddr]['c'])} chars",
                      flush=True)
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} decompiles to {out_path}")
    return 0


def strip_names(c: str, own_address: str) -> str:
    """Remove every address-carried identity from the C.

    The function's own symbol becomes ``this_function`` and every callee becomes ``callee_1``, ``callee_2``... in order
    of appearance - not ``sub_<address>``, which would hand the model the address (and with it, for a famous binary,
    the answer from memory). ``entry`` is renamed too, because Ghidra names the DOL entry point.
    """
    c = re.sub(r"\b(?:thunk_)?FUN_([0-9a-fA-F]{8})\b", lambda m: "sub_" + m.group(1).lower(), c)
    c = re.sub(r"\bsub_" + own_address.lower() + r"\b", "this_function", c)
    seen = {}

    def callee(m):
        key = m.group(0)
        if key not in seen:
            seen[key] = f"callee_{len(seen) + 1}"
        return seen[key]

    c = re.sub(r"\bsub_[0-9a-f]{8}\b", callee, c)
    c = re.sub(r"\bentry\b", "this_function", c)
    return c


if __name__ == "__main__":
    sys.exit(main())
