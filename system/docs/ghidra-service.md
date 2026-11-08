# Ghidra service

Status: **available on lilspark** (2026-11-08). The operator's Ghidra is
`/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC`; the PyGhidra venv is
`gbox-data/runtime-linux-aarch64/pyghidra-venv` (PyGhidra 3.1.0). `GET /api/harness/ghidra` reports
`status: available`.

`ghidra_bridge` is the live interface: `op=open` imports/analyzes a binary, then `info`, `functions`, `decompile`,
`xrefs_to`, `xrefs_from`, `containing`, `strings`, `run_script` and `export` query the held program. The program stays
open in a worker-owned process, so a troubleshooter must do the open and the follow-up queries on the same worker.

## RE5 Switch main

The NSO is already dumped at
`~/gBox_alt/scratch/agent/switch/re5/main-EBFFDB223149A725A93CD9B60979F6AA.nso`. It was converted with
`~/gBox_alt/scratch/agent/re6sw/tools/nso2elf.py` to
`~/gBox_alt/scratch/agent/switch/re5/ghidra/re5main.elf` (30,360,176 bytes, four `PT_LOAD`s). The canonical gBox
analysis copy is `gBox-data/analysis/switch/re5/re5_switch_main_EBFFDB22.elf`.

Address rule: **Ghidra address = module offset + 0x100000** (the ELF image base). For example module `0x1cccec` is
Ghidra `0x2cccec`.

## Measured open (2026-11-08)

`ghidra_bridge op=open` on `re5main.elf` completed: `AARCH64:LE:64:v8A`, image base `0x00100000`, **20,835
functions**, MD5 `003b064c2f13456b1a7a2c658e541133`. The open took about 40 minutes and kept the program in the bridge
process; a restart of gBox closes it (the Ghidra project is saved).

Useful anchors for the model-loader work:

| string | address | code reference |
|---|---|---|
| `mVertexNum` | `0x0188df9f` | `FUN_011537b0` (property registration) |
| `mPrimitiveNum` | `0x0189c95a` | data `0x010ff300` |
| `mIndexNum` | `0x0188dfaa` | data `0x010ff438` |
| `mMaterialNum` | `0x01899c42` | data `0x010ff4a0` |
| `pawn\em\em10\model\em1000` | `0x01cfbd28` | data table `0x00803874` |
| `pawn\em\em10\model\em1000_low` | `0x01bf9138` | data only |

The model paths live in a data table (17 pointer entries for `em1000`), not behind an ADRP+ADD in code; the next step is
to find the table's consumer and the function that turns a `Mesh`/`Primitive` record into a GPU buffer.

## Troubleshooter hook

The PiP console's **G** button POSTs `/api/sessions/{sid}/harness/ghidra {op:"open"}`. The server resolves the title's
analyzed main and submits `ghidra_bridge` on the session's worker; the console follows the job's `ghidra` lines. A second
call can carry `op:"decompile", target:"0x..."` once the program is open.

## What this is not

This is static analysis of the title main plus the live RAM/console console. It is not a ptrace/gdb hook inside Eden and
does not by itself patch code. The Ghidra open of RE5's 30 MB main takes several minutes; the bridge keeps it open after
that.
