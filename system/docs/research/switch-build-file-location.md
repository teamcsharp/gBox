# Where a Switch build file actually lives

Two roots exist and I had been inspecting the wrong one:

```
~/gBox_alt/gbox-cache/mods/<game_id>/<build>/     <- switch_mods WRITES here (the tool says so in its own output)
~/gBox/system/gbox-data/cache/mods/<game_id>/<build>/   <- where I kept looking, and where my hand copies went
```

That is why scanning the second root found no `uEm10.arc` in any build while `cast-inverted` demonstrably swaps it every
round, and why hand copies were invisible to the emulator.

**Rule: populate a build through `switch_mods` (`op: write` / `op: apply_live` with `changes`), never by copying files into a
build directory**, and when checking what a build holds, use the `dir` the tool reports rather than a path you assumed.

Verified this round: `op: write` with `{"from": "<path on the worker>"}` installed an 82 MB `uEm10.arc` as edit
`e1793992938982-001`, the launch then reported `succeeded`, and the session came up with `mod: "ssv1322"` - so a build
installed this way is registered and loaded. (The `{"from": path}` source also avoids base64-ing an 82 MB payload through
JSON.) What is still unshown for that build is a frame with an enemy in it: the capture window returned no frames over 8 KB,
and the round had already been replaced by the rotation when it was checked.