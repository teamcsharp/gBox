# Final hand-off: what this session delivered, and the one thing it could not

Branch `ds-pso-live-platform-20261110`, tip `8ab7c60c` plus this commit. Written at round 254 of 256.

## Delivered and verifiable

| item | evidence | how to re-verify |
|---|---|---|
| **CP1**: local model on the 3090 | 3090 2.4 -> 13.1 GB while deepseek-r1:14b answered | `cp1_local_model.py` |
| **CP2**: gold-set verdict | plausible roles, no exact names, 23.9 s/function -> fallback clause | `cp2_gold.py --run`, `llm/gold34-deepseek-r1-14b-probe.json` |
| **CP3**: labelling pipeline | 46/82 labels, 2.37/min, own resumable file | `label_ds.py`, `llm/labels-deepseek.jsonl` |
| **CP9**: save card | directory at 0x20C0, name +0x08, BE block fields; three files extracted; two cipher hypotheses eliminated | `memcard_parse2.py`, `cipher_probe.py` |
| **CP17 route**: certified walkable | 9 legs, **0 blocked**, 999 units, ends 3.7 units from the warp, 37 s | `cp17_route_check.py` |
| **CP18 capture**: exact accept series | boss HP + every player's HP, verdict on "both alive" | `boss_both.py` |
| **level editor**: end to end | **11/11 self-test**, idempotent | `editor_selftest.py` |

## The editor, in detail

* **rooms** - erode + grow + flood over the collision mesh: 11 rooms on Forest 1 (7 known centres recovered independently), **14 on Forest 2,
  the first room graph that floor has ever had**;
* **doorways** - cells whose neighbour belongs to another room: 61 / 76 edges;
* **placements** - 68-byte set records, 150 / 196 decoded per floor;
* **inspect** - click a room to see its cells, centre and object counts;
* **edit** - place mode appends a validated record to a copy;
* **two gates** - the placement must land inside a walkable room, and the resulting file must satisfy every structural invariant with all
  original records byte-identical (measured: 12 bytes changed for a move, +68 bytes and remainder 0 for an add, 150/150 preserved).

## Not done, and why

| item | blocker |
|---|---|
| **CP17 acceptance** (floor id changes while walking) | needs a running game; route certified but never walked |
| **CP18 acceptance** (boss HP to 0 with both players alive) | needs a running game and a co-op partner |
| **CP19** (Episode I unattended) | needs CP17 + CP18 |
| **all spells**, **Ultimate**, **bot plays the game** | need a running game |
| **boot acceptance of an edited set file** | needs a running game |

**One condition blocks every one of them: a PSO session started from the gBox app.** No session has run for 22 rounds. An agent-launched
session is `agent_owned`, and gBox routes no input to it - which is what made the operator's own controller dead in rounds 228-229. That
boundary cannot be cleared from the agent side, and faking an operator actor to bypass it would be a deliberate circumvention of the guard
that protects the operator's game, so it was not attempted.

## What the next session should do, in order

1. start PSO **from the app** (operator-owned), load the character;
2. `learn_live.py` running for evidence, then `mastery_run.py --all` for CP17 + CP18;
3. `apply_master.py` for HP / Ultimate / five-slot legendary, then `tech_finder.py` -> confirm the technique table at `+0x2E7` -> write it;
4. boot an edited set file to close the last editor risk;
5. `editor_selftest.py` and `mastery_run.py --check` to re-verify everything above still holds.

## The honest summary

The offline half of the PM document moved a long way - CP1 verified, CP2 measured, CP3 running, CP9 advanced, CP8 given a second floor, and a
level editor that goes from map to edit with byte-level proofs. The mastery block (CP17-CP19) is **not achieved**, and its accept tests need a
running game. No amount of further offline work changes that.
