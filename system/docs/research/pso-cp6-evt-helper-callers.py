"""CP6.1: who calls the "EVT NO : %d" debug helpers - the event system's own update path.

The helpers print an object's event number, so their caller walks actors with events and is therefore part of the event system.
That caller (and its caller) is the nearest thing to the interpreter reachable offline.
"""
import os
import sys

os.environ.setdefault("GHIDRA_INSTALL_DIR", r"D:\gBox\runtime\ghidra_12.1.4_PUBLIC")
os.environ.setdefault("JAVA_HOME", r"D:\gBox\runtime\jdk-21.0.12.1+1")
import pyghidra  # noqa: E402

HELPERS = [0x8015BB8C, 0x80188814, 0x8018CBF0]


def main():
    pyghidra.start()
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor

    with pyghidra.open_project(r"D:\gBox\ghidra-pso\PSO", "PSO") as project:
        root = project.getProjectData().getRootFolder()
        pathname = next(f.getPathname() for f in root.getFiles() if f.getName().endswith(".elf"))
        with pyghidra.program_context(project, pathname) as program:
            space = program.getAddressFactory().getDefaultAddressSpace()
            fman = program.getFunctionManager()
            dec = DecompInterface()
            dec.openProgram(program)
            monitor = ConsoleTaskMonitor()
            seen = set()
            for helper in HELPERS:
                fn = fman.getFunctionAt(space.getAddress(helper))
                if fn is None:
                    print(f"{helper:#x}: no function")
                    continue
                callers = [c for c in fn.getCallingFunctions(monitor)]
                print(f"{helper:#x} {fn.getName()} ({fn.getBody().getNumAddresses()}B): "
                      f"{len(callers)} caller(s) {[c.getEntryPoint().toString() for c in callers]}")
                for caller in callers:
                    key = caller.getEntryPoint().getOffset()
                    if key in seen:
                        continue
                    seen.add(key)
                    result = dec.decompileFunction(caller, 90, monitor)
                    code = result.getDecompiledFunction().getC() if result and result.getDecompiledFunction() else ""
                    print(f"\n===== caller {caller.getEntryPoint()} {caller.getName()} "
                          f"({caller.getBody().getNumAddresses()}B)")
                    lines = code.splitlines()
                    print("\n".join(lines[:40]))
                    print("-- callees:", ", ".join(f"{c.getEntryPoint()}" for c in caller.getCalledFunctions(monitor)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
