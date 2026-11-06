# Where a Switch build file actually lives

Trying to relaunch the Sonic-slots build exposed an operational gap that cost a round.

Scanning every build folder under both `gBox/system/gbox-data/cache/mods/<game_id>/` and
`gBox_alt/gbox-cache/mods/<game_id>/` finds **no uEm10.arc in any of them** - even in builds that demonstrably ran with that
arc (cast-inverted swaps uEm10 today, and the Sonic-slots run reached character select with the slots archive installed).

So the file the emulator reads is not in the build folder the tool reports. `new_build` returns `succeeded` and a build gets
its marker, but the folder `switch_mods.build_dir(...)` then points at holds no marker and no romfs, and the copies made with
`shutil.copyfile` went somewhere nothing reads. The LayeredFS mechanism is `link_build`, which links the build into the
emulator's own load folder (`load/<title_id>/<build>`).

**Rule: populate a build through `switch_mods`, never by copying files into a build directory.** `op: "write"` or
`op: "apply_live"` with `changes` both register the build and record the edit (which is what makes `revert` work), and they
are what the MercMode panel itself uses. A hand copy leaves the manifest, the link and the launch registry disagreeing - which
looks exactly like "the game ignored my mod".