# Ghidra service

Status: **written, not run.** Ghidra isn't installed on the build host.

`analyze_binary {binary_path, processor?}` runs `analyzeHeadless` with `adapters/ghidra/ExportAnalysis.java` and produces `analysis.json` (program info, functions, defined strings) as an artifact. For Dreamcast use `processor = "SuperH4:LE:32:default"`. It requires `ghidra_home` and JDK 21.

Not yet built: decompile_function, xrefs, structure/label creation, static↔runtime correlation, patch proposals. Findings should enter the knowledge graph as `hypothesis` edges and be promoted only with runtime evidence artifacts (enforced by `/api/knowledge`).
