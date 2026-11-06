Thanks. Items 1, 2 (the commit), 3 and 5 look right. Two corrections.

A. Emulator config: no decision is needed, because the config is effectively auto.
gbox.toml says "eden", but config.load() lays gbox.local-lilspark.toml on top of it. That file is gitignored, which is why the repository doesn't show it, and it says "auto".

I ran the deployed code on the Spark:
  effective switch_linux_emulator = auto, citron available = True
  RE4 -> citron, RE5 -> eden, RE6 -> eden

This matches the record: RE4 launched on Citron at 00:03 today (job f3233eb954974641). So RE4 is not forced onto Eden, and it can be played on lilspark. Your f11594fb matters more than you thought: under auto, that list is what keeps RE5 and RE6 on Eden. The VK_ERROR_UNKNOWN note predates Citron d3df71e55, which renders RE4 on the GB10. The function is switch_linux_kind, not pick_switch_emulator.

To do:
1. Correct mercmode-switch-only.md (lines 38 and 53) so it no longer says the config forces Eden.
2. Set the committed gbox.toml to "auto" with an accurate comment. Nothing changes on lilspark, and RE4 stops depending on an untracked file. If that file were lost, RE4 would fall back to Eden and fail.

B. cast-inverted: clean on disk, not in its record.
Confirmed clean: uWp06.arc is gone from romfs in the live overlay and in the cache copy. uPl00ChrisNormal.arc is the skin-chris-as-jill file (hash 5ff83bf1fced), not your 2x test.

Not clean: .gbox-mod.json still lists uWp06.arc in files and file_changes, and its last history entry, e1793975941987-012 "mine pole gated", is still applied with no revert. Two uWp06.arc backups also remain under .gbox-backup.

To do:
1. Reconcile this through switch_mods, not by hand. Removing the file by hand is what split the record from the disk.
2. Confirm with op=audit that the manifest and disk agree.
3. Don't restart the running round for this. If it needs a reboot to apply, ask the operator first.

Next:
- Check that the ported Bot turns with lleft/lright, not the d-pad, which is item select.
- RE4 doc steps 2 and 3 need the Spark, so wait for the operator's OK before pausing the rotation.
