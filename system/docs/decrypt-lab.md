# The decryption lab

One reusable pipeline for every title, and a live window that shows it working plus what autoplay sees.

The problem it replaces: each title's reverse engineering lived in its own scripts and notes, so every new
title re-derived the same things (module base, signature, segment layout, field offsets, evidence) and nobody
outside the shell could watch it happen. The lab makes the *process* a first-class object.

```
adapter ──► stages ──► fields (confirmed / candidate / rejected) ──► verification ──► driver
              │           │
              │           └─ evidence: how it was found and what would falsify it
              └─ identify · extract · disassemble · fields · verify · driver
```

## What is reused, not reinvented

* **`gbox.mercs.titles.*`** already declare a title's identity and anchors (`TITLE_ID`, `BUILD_ID`,
  `SIG_OFF`, `SIGNATURE`, `S_*`, `DRIVER`). The lab introspects those modules, so a title never restates them.
* **`nso2elf.py` / `nsodis.py` / `addrrefs.py` / `funcof.py`** (in `~/gBox_alt/scratch/agent/re6sw/tools`)
  are the extraction and disassembly stage: dump → ELF → Ghidra.
* **`ghidra_bridge`** supplies decompilation and xrefs; the lab's stage view links a title to the ELF it
  should load.
* **`tactical_map`** already carries the Mercenaries frames the bot publishes. The lab reads that store for
  the "what autoplay sees" panel — no new publisher, no duplicated telemetry.

## The live instruments

**RAM hex scanner.** `POST /api/decrypt-lab/scan {title, offset, length, mode}`.
In `module` mode the scanner finds the title's module base **from that title's own signature** (the same
64 bytes the driver uses), then reads `base + offset` from the emulator's `/proc/<pid>/mem` server-side.
NCE on this box means guest address == host address, so an absolute address works too (`mode: "absolute"`).
Every 4-byte cell is classified — `zero`, `int`, `float`, `pointer?`, `ascii`, `raw` — which is the triage the
page colours.

**Bot perception.** `GET /api/decrypt-lab/state` embeds the newest tactical frame per session: stage, round,
player, units, aim, frame keys, and whether it is live (< 3 s old). This is the same data the Mercenaries map
and the reviewer consume, so the page shows exactly what the bot is using — not a re-render of it.

## Adding a title

1. Append an adapter to `ADAPTERS` in `gbox/decrypt_lab.py`:

```python
{
  "id": "mytitle_switch",
  "module": "gbox.mercs.titles.mytitle_switch",   # where TITLE_ID/BUILD_ID/SIGNATURE live
  "nso_glob": "main-*.nso",
  "elf": "mytitlemain.elf",
  "notes": "one line on what this port is",
  "fields": [
      ("health", 0x3C2, "u16 @ unit+0x3c2", "confirmed",
       "FUN_00xxxxxx writes it; verified live against a damage read"),
  ],
}
```

2. Dump the NSO (`dump_nso`), wrap it with `nso2elf.py`, and open it in Ghidra — the `extract` and
   `disassemble` stages light up from the file checks, no code change.
3. Record fields **with evidence and status**. `rejected` entries are kept on purpose: knowing what a field
   is not is part of the map, and it stops the next session repeating a dead hypothesis.

## Extraction and replacement

The **Extraction** panel is the asset half of the lab. Two routes back it:

| route | purpose |
|---|---|
| `GET /api/decrypt-lab/assets?title=&kind=&q=` | the title's RomFS inventory (cached JSON), filtered by kind and path; `inventory: null` with a `note` when the title has no inventory yet |
| `POST /api/decrypt-lab/stage` | write a replacement file into a **LayeredFS overlay** for a RomFS path |

### The RomFS decode is solved — through hactool

`gbox/switch_assets.py` originally carried its own NCA → IVFC → RomFS reader. That reader works for plaintext
sections but **not** for this title's game NCA: the 19.9 GB section is neither plaintext nor AES-CTR with the
ticket key at any plausible base, and `nsz` cannot list it either (it lists the ExeFS and the control NCA's
RomFS, then stops).

What works is **hactool** (`~/gBox_alt/hactool/hactool`, built from source; `bktr.c` + `lz4.c` handle the
block-compressed sections). Two details matter:

* pass the ticket's key explicitly — `--titlekey=<hex>`; hactool reads no ticket in NCA mode and otherwise
  fails with *"Unable to match rights id to titlekey"*;
* feed it an **NCA file**, not the NSP: `switch_assets._game_nca_path()` extracts the game NCA once (cached
  under `~/gBox_alt/switch/work`).

```bash
hactool -k prod.keys --titlekey=<title key hex> -t nca --listromfs game-<size>.nca      # inventory
hactool -k prod.keys --titlekey=<title key hex> -t nca --romfsdir=<dir> game-<size>.nca # full tree
```

Measured on Resident Evil 5 (Switch): **17,483 files** in 0.3 s — 14,592 audio (`.adpcm`/`.opus`), 2,509
archives, 286 models, 68 textures. `GBOX_HACTOOL` overrides the binary path; `GBOX_SWITCH_WORK` and
`GBOX_SWITCH_ROMFS` override the work and extracted-tree directories.

Staging is the real Switch mechanism, not a copy trick: the overlay is gBox's mod collection
(`<cache>/mods/<title>/<build>/romfs/<path>`), which the emulator layers over the game's own RomFS when the
title boots (see `switch_mods.py`). The route rejects absolute paths, `..` segments, oversized payloads and
invalid base64, and the window's allowlist checks the same shape before the request leaves the renderer.

## The window

`File → Decryption lab` (`Ctrl+Shift+L`). Three panels:

* **3D memory map** (vendored `three.js`): the title's state as a lattice — confirmed fields, candidates,
  rejects, then the kinds from the last scan. Drag to orbit, wheel to zoom, click a block to scan that page.
* **Tables**: the stage matrix per title, the field catalog with status badges (select a row for its
  evidence), and the event feed.
* **RAM bytes**: address, four classified cells per row, and the ASCII gutter.

The window is hardened like the Mercenaries viewer: `contextIsolation`, `sandbox`, no node integration, a
`partition` of its own, navigation locked to the page file, and an **allowlist** in `decrypt-lab.cjs` for the
three lab routes it may relay. The renderer never receives the API credential; the main process attaches it.

## API

| route | purpose |
|---|---|
| `GET /api/decrypt-lab/state` | titles with stages + fields, recent events, scans, bot frames, emulator present |
| `GET /api/decrypt-lab/events?after=N` | event feed after a sequence number |
| `POST /api/decrypt-lab/scan` | read and classify guest memory (module or absolute) |
| `GET /api/decrypt-lab/scan/{id}` | one stored scan (kept in a 40-entry ring) |
| `POST /api/decrypt-lab/field` | promote/reject a field with a note (logged as an event) |

All routes require the server's normal auth dependency; the window relays them through the main process.
