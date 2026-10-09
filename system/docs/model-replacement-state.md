# Model replacement and current-game preservation

Replacing a disc model now prepares and verifies the replacement on the target PC while the existing game continues running. Only then does gBox export the current save state, start the replacement disc and import that checkpoint. A failed export cancels the replacement. A failed import stops the replacement and attempts to recover the original game from the retained checkpoint. A dark restored frame never triggers an automatic reset.

Repeated selections for the same game on the same worker share the active replacement job. A conflicting selection receives an actionable response. Modded library launches also use this preservation path when that game is already running. Other games on the same console are no longer closed by a model launch.

Worker downloads are serialized per mod, use resumable ranges and verify file sizes and SHA-256 checksums. The completion marker is published last. State transfer is serialized, selects only the current RetroArch content's state file and loads the slot the emulator actually wrote, including when network commands or hotkeys changed its slot.

## Verified behavior and remaining work

Verified on Windows with WWF SmackDown! 2: the original in-progress match was recovered from its preserved checkpoint; the Sonic/Shadow disc was then launched through the replacement path, its checkpoint restored, and a nonblack game frame captured. A second simultaneous selection joined the same job. Regression checks cover corrupt checkpoints, incorrect slot tracking, unrelated state files, resumed/corrupt downloads, duplicate requests and preparation/export failures.

Save states also contain models already loaded into RAM. The restored SmackDown match still shows the original wrestler; the replacement disc supplies the new model when the game next loads its wrestler assets. Immediate model replacement during an existing match remains unfinished and needs a verified game-specific RAM/VRAM refresh. Loading the replacement disc and restoring a checkpoint must not be reported as proof that the in-memory character model changed. Inbox #767 remains in progress for that part.
