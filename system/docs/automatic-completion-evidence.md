# Automatic completion evidence for game files

The chat completion guard treats `rom_export` with `op=export` (including its
default) and `file_mod` with `op=build` as required operations. These create files;
they remain separate from the live-game mutation classifier and never acquire
game bookmarks or send controls because of this guard.

Previously, a failed ROM export or a successful preflight returning
`ready: false, status: needs_selection` could finish the chat request as `done`.
The turn now remains `in_progress` until that attempted operation has a completed
tool result with the producer's expected deliverable fields. A generic succeeded
job, a plan, a README, or a later successful read is insufficient.

ROM exports require their export directory and an image/folder or cheat files.
An explicit game ID must match any returned ID and the export directory. Existing
original-file exports, saved-mod selection, cheat-only exports and shortened chat
receipts remain supported. The short receipt retains game identity, export mode
and failure/status flags; an explicitly returned original/modified mode must
match the request. A cheat-file receipt proves only that tool's supported export,
not that a request for a modified game image was fulfilled.
File builds require the requested mod name, its
directory and nonempty changed-file paths. Explicit failure, pending, unsupported,
partial or not-ready results cannot be hidden by those fields. Direct tools and
the typed `run_tool` wrapper use the same guard.

An exact successful retry clears a failed attempt. Another game's export or an
operation with different arguments does not automatically clear it; independent
verification may still resolve the inbox request. Plan/list calls and ordinary
informational answers retain their existing completion behavior.

This guard validates tool-result contracts, not the on-disk bytes or every natural
language acceptance criterion. It does not prove that a cast swap works in game,
that unlocks are complete, or that code is deployed. Explicit inbox status changes
continue to require the caller's verification, except for existing specialized
server guards. No inbox history is rewritten by this change.

Validation: `tests/test_agent_required_completion.py`,
`tests/test_agent_contracts.py`, `tests/test_live_request_agent.py`,
`tests/test_auto_resolution_turn.py`, `tests/test_romexport_recovery.py`.
