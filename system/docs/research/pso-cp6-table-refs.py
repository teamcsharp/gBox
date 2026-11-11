"""CP6.1 route 3: who references the debug helpers' table, and what loops over it.

The helpers at 0x8015bb8c / 0x80188814 / 0x8018cbf0 have no callers but sit in .data tables (0x804b023c, 0x804b6660,
0x804b72dc). Whoever references those table addresses is the code that dispatches a per-area or per-type debug draw - and its
caller is the update loop that knows about actors with events, which is where events get evaluated.
"""
import os
import sys

os.environ.setdefault("GHIDRA_INSTALL_DIR", r"D:\gBox\runtime\ghidra_12.1.4_PUBLIC")
os.environ.setdefault("JAVA_HOME", r"D:\gBox\runtime\jdk-21.0.12.1+1")
import pyghidra  # noqa: E402

TABLES = [0x804B023C, 0x804B6660, 0x804B72DC]


def main():
    pyghidra.start()
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor

    with pyghidra.open_project(r"D:\gBox\ghidra-pso\PSO", "PSO") as project:
        root = project.getProjectData().getRootFolder()
        pathname = next(f.getPathname() for f in root.getFiles() if f.getName().endswith(".elf"))
        with pyghidra.program_context(project, pathname) as program:
            space = program.getAddressFactory().getDefaultAddressSpace()
            refman = program.getReferenceManager()
            fman = program.getFunctionManager()
            dec = DecompInterface()
            dec.openProgram(program)
            monitor = ConsoleTaskMonitor()
            seen = set()
            for table in TABLES:
                refs = list(refman.getReferencesTo(space.getAddress(table)))
                print(f"{table:#x}: {len(refs)} reference(s)")
                for ref in refs:
                    fn = fman.getFunctionContaining(ref.getFromAddress())
                    print(f"   from {ref.getFromAddress()} {ref.getReferenceType()} in "
                          f"{fn.getEntryPoint() if fn else None} {fn.getName() if fn else ''}")
                    if fn and fn.getEntryPoint().getOffset() not in seen:
                        seen.add(fn.getEntryPoint().getOffset())
            for offset in sorted(seen):
                fn = fman.getFunctionAt(space.getAddress(offset))
                result = dec.decompileFunction(fn, 90, monitor)
                code = result.getDecompiledFunction().getC() if result and result.getDecompiledFunction() else ""
                print(f"\n===== {fn.getEntryPoint()} {fn.getName()} ({fn.getBody().getNumAddresses()}B)")
                print("\n".join(code.splitlines()[:45]))
                print("-- callees:", ", ".join(f"{c.getEntryPoint()}" for c in fn.getCalledFunctions(monitor))[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
