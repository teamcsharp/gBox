# Round 227: the write channel is back, and the master setup is staged and ready

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Session `0d2e88799e11476b-e425afc683e145f1` (pid 2236) - **relaunched under the current worker**

## The unlock: memory writes work again

The operator saved and exited, which allowed a clean relaunch through the plane. The new session belongs to the worker that is running now,
so the job channel finally owns it. Proven with a **no-op write** (writing the current value back, so the game could not change):

```
session: 0d2e88799e11476b-e425afc683e145f1
write job: succeeded
result: {"rollback_hex": "00000000", "verified": true, "via": "process memory", "written": 4}
after: 00000000
unchanged: True
```

That single line unblocks everything that was stuck all session: HP writes and freezing, the technique table ("all spells"), and arbitrary
player-struct edits. It also confirms the rollback receipt mechanism, so a bad write can be reverted.

## Every tool now survives a stale desktop service

The desktop service answered `504` for this session while the worker mirror answered correctly. Rather than exporting an environment
variable per script, `session.py` now retries the worker port on a gateway timeout and remembers the winner:

```
start api: http://127.0.0.1:18765
read player table: 00000000        <- fell back automatically
api now: http://127.0.0.1:8765
```

## `apply_master.py` - the operator's setup as verified stages

```
python apply_master.py status        report actor, hp/tp, technique bytes, capabilities
python apply_master.py hp            write + freeze HP at max
python apply_master.py legendary     give 5 copies of a legendary weapon and multi-equip all five slots
python apply_master.py ultimate      enable the Ultimate difficulty selection
python apply_master.py techs --offset 0x2E7 [--apply]    write the technique array (dry run by default)
```

Each stage prints the plane's answer **and** a re-read of memory, so no claim rests on the request alone. `status` currently reports
`no player loaded (table holds 0x0)` because the game is at the title screen.

## Where the boot stands

The title menu resists automation at the standalone window size: fixed row coordinates belong to the docked 1030x579 layout, and the
dynamic band detector finds the entries but mis-labels the highlight because the title art shares their brightness. The operator asked for
the game **docked in gBox**, which is the right way anyway - launching from the app starts the emulator through the embedder, so the window
docks and the same session is used. That click is theirs; everything after it is automated.

## Files

* `probe_write.py` - the no-op write proof
* `patch_session_fallback.py` / `session.py` - automatic worker-port fallback
* `apply_master.py` - staged HP / 5x legendary / Ultimate / techniques
* `boot_auto.py` - dynamic-row title navigation (works for the docked layout, not the standalone one yet)
