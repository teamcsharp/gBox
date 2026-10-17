# Shared memory cards

Open a running Dreamcast (RetroArch/Flycast) or GameCube (standalone Dolphin)
session and click the memory-card icon next to the speed control. The manager
shows inserted cards, saved files, free blocks, sync errors and named cards on
Spark. Create another card or select an existing card for a slot.

**Card changes take effect on the next game launch.** These emulators cache
card contents in memory. Replacing their files during play is not a safe card
swap. Save normally, close the game, then launch it again to use the selection.
The manager does not format, delete, or overwrite an existing card.

## A dedicated PSO card

Use **Create PSO card (keep PSO saves)** when the current card is recognized.
For Dreamcast, this copies the native `PSO*` save files onto a new 200-block VMU,
leaving other games on the original VMU. The source card is kept. A card with
the 15-block PSO system save has 185 blocks free, enough for the additional
30-block guild-members file.

For GameCube, the dedicated copy retains the entire native card image and its
serial, including the existing PSO character, system and guild-card saves. This
avoids changing PSO's card identity. It does not remove other saves to make room.
New blank GameCube cards have 251 save blocks. Selecting a blank card starts
without the characters on the previous card.

Cloning uses the last successfully synced cloud revision. Choose **Sync now**
after the game has finished saving if recent changes must be included. If the
worker has not yet loaded this feature, card creation remains available, but
inspection, insertion and syncing wait for an idle worker update.

## Sharing and recovery

Spark stores immutable card images under `gbox-data/memory-cards/blobs` and
metadata, per-game slot selections and leases in its SQLite store. Each launch
leases one revision and downloads a verified local working copy. Emulators
write locally, rather than writing directly to a network share. Another PC
checks out the same card after the previous session has synced and closed.

The worker checks stable card files every 15 seconds and uploads them after a
confirmed emulator exit. A revision comparison prevents an older session from
overwriting newer cloud saves; a single-writer lease prevents simultaneous
sessions from writing the same card. Conflict and network failures keep the
local files and a recovery journal. Pending uploads are retried before a later
launch, preserving the original lease identity. Save states are separate from
memory cards and are not synchronized by this feature.

Only actually configured native card slots are imported. Invalid legacy files
are reported individually and do not prevent a valid card in another slot from
being managed. Existing unmanaged files are backed up as separate cloud cards.
Replay, capture, and agent test sessions retain their isolated save handling.

Managed Dolphin cards require a recognized region in an ISO, GCM or GCZ image.
Other image formats keep the emulator's existing card handling and continue
launching normally; their manager explains that cloud insertion is unavailable.

The vault exposes the latest 32 revisions per card. Blob pruning and arbitrary
save-file editing/deletion are not included. Failed or conflicting local copies
are deliberately retained for recovery.

Validation is recorded in [memory-cards-validation.json](memory-cards-validation.json).
