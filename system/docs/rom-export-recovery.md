# ROM export recovery

Plan before exporting. A failed export is not repaired by repeating an unchanged recipe.
Use `rom_export(op="plan", game_id=..., mod_id=...)` or `POST /api/romexport/plan`.
The response lists the exact selection, available saved/built mods, blocking issues,
installed optional programs, and the next engineering step. A game ID alone does not
identify a modification. Ask which build/change is intended; do not silently export
the unmodified game as a successful ROM hack.

The bell tray's **Review export** action checks the failed selection and lets the
operator choose a saved or built modification. Export remains disabled until that
selection passes planning. The agent follows the same plan-before-export sequence.
The worker still verifies source bytes during the build; a ready plan is not proof
that an image was built or booted.

## Fresh-process local recovery

From `system/`, with the configured Python environment:

```text
python -m gbox.romexport_recovery --config gbox.toml --job JOB_ID
python -m gbox.romexport_recovery --config gbox.toml --job JOB_ID --mod MOD_NAME
python -m gbox.romexport_recovery --config gbox.toml --job JOB_ID --mod-id SAVED_MOD_ID --execute
```

The first two commands only review. `--execute` uses the current process's writer,
so local engineering can proceed while a busy long-running worker awaits refresh.
For an unchanged original use `--original --execute`; never infer this from an empty selection.
Credentials come from the local configuration, never from command-line tokens.
The failed historical job remains intact. Record the replacement export manifest
and verification alongside its original job ID; do not relabel a failure as success.

## Repair paths

| Failure | Required repair |
| --- | --- |
| No mods given | Choose the intended saved/build mod or explicit file changes. If original media was intended, choose **Original game file (unchanged)**, or use `--original --execute`. |
| Saved mod missing | Select a current saved mod; retain the old job's recipe for diagnosis. |
| Build missing locally | Check the exact game/build ID and collection manifest. Fetch/stage the named build, then verify its files. Do not select an unrelated build automatically. |
| Wrong game/revision | Fingerprint the owned source and target build. Never bypass expected-byte or revision checks. |
| Live memory modification | Trace its executable/asset loader with analyze_binary/ghidra_script or native decompilation tools. Implement a bounded static writer, or explain why the runtime operation requires a persistent hook. |
| File exceeds disc extent | Measure sector alignment and free extents. Preserve the original compression parse where possible; otherwise prove a relocation plan and update the format's references/checksums. Never truncate or overwrite the next file. |
| Missing optional encoder | BPS/IPS are built in; IPS is limited to 16 MiB. Use chdman/7z/Dolphin tooling only when that container requires it. A PATH entry alone does not prove the needed format operation works. |
| Worker unavailable | Preserve the recipe and use a source-capable local worker or the fresh-process command. Do not retry against a retired worker ID or interrupt an operator game. |

For a missing reader or writer, follow `gbox.native_engineering.plan()` and
`docs/native_decomp.md`: source fingerprint, proved layout, bounded reader, no-op
round trip, intended modification, rebuilt-file readback, patch application equality,
then runtime/gameplay proof. Hermes and Spark2 should retain artifacts and advance
these stages rather than marking a preview or an attempted export complete.

## Verified PSO US v2 critical-hit export

`pso_rom_export` supports only the hash-identified Dreamcast US v2 retail files and
the saved `pso_mods/crit_always` modification. It decodes `DP_ADDRESS.JPN` using
`KATSUO.SEA` and `IWASHI.SEA`, verifies the full executable hash and the original
instruction, changes `0x8C047BC0` from `1a89` to `0900`, and preserves the retail
PRS references to fit the allocated sectors. It writes a new GDI set, reads the
rebuilt native files back, and round-trips both BPS patches. Other regions,
mod combinations, and other PSO live operations are not claimed supported.

The file-format reference is [newserv DCSerialNumbers.cc](https://github.com/fuzziqersoftware/newserv/blob/ce2273a8e48c5c6fec9e21d85c490028498d8682/src/DCSerialNumbers.cc).
The owned decoded source SHA-256 is
`c3f17d16215da4fe568b1ebcfbea556b9fe909b71059f3985cd19b37b92f5884`.
Output manifests distinguish codec/disc/patch verification from gameplay verification.
Download the GDI descriptor and every referenced track together. The per-file BPS
patches apply to the named files extracted from the same owned source revision.

