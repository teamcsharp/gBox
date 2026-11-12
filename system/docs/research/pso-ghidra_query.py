"""Read the analysed PSO program back out of the Ghidra project.

`analyzeHeadless` finished: *"Analysis succeeded for file /D:/gBox/pso-ds/pso_v3.elf … Save succeeded for /pso_v3.elf (pso:/pso_v3.elf)"* in 149 s, so the project at
`D:\\gBox\\pso-ds\\ghidra_proj` now holds PSO's code as functions, references and stack frames.

This opens it with the same PyGhidra the bridge uses and reports what is actually in there - program name, language, function count, and the entry points and largest
functions by name - so the analysis is demonstrated as usable rather than assumed.
"""
import os

PROJECT = r"D:\gBox\pso-ds\ghidra_proj"
NAME = "pso"
PROGRAM = "/pso_v3.elf"


def main() -> int:
    os.environ.setdefault("GHIDRA_INSTALL_DIR", r"D:\gBox\runtime\ghidra_12.1.4_PUBLIC")
    import pyghidra
    pyghidra.start()

    from ghidra.base.project import GhidraProject
    from ghidra.program.model.listing import FunctionManager

    project = GhidraProject.openProject(PROJECT, NAME, False)
    try:
        program = project.openProgram("/", "pso_v3.elf", False)
        listing = program.getListing()
        functions = program.getFunctionManager()
        count = functions.getFunctionCount()
        print("program:", program.getName())
        print("language:", program.getLanguageID(), "| image base:", program.getImageBase())
        print("functions:", count)
        print("memory blocks:", program.getMemory().getNumAddressRanges())

        biggest = []
        iterator = functions.getFunctions(True)
        while iterator.hasNext():
            function = iterator.next()
            body = function.getBody()
            biggest.append((body.getNumAddresses(), function.getName(), str(function.getEntryPoint())))
        biggest.sort(reverse=True)
        print("\nlargest functions:")
        for size, name, entry in biggest[:12]:
            print(f"  {size:6d} bytes  {name:40s} @ {entry}")

        print("\nentry points:")
        for symbol in program.getSymbolTable().getExternalEntryPointIterator():
            print("  ", symbol)
            break

        print("\nfirst strings in defined data:")
        shown = 0
        for data in listing.getDefinedData(True):
            value = data.getValue()
            if isinstance(value, str) and len(value) >= 6:
                print("  ", value[:70])
                shown += 1
                if shown >= 10:
                    break
    finally:
        project.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
