# Inbox organization

The Requests page lists operator prompts at the top level. Automated gap reports, character work, review reminders and imported agent reports are separate records with `automated` and `parent_request_id` fields. Linked work appears in expandable sub-requests under its originating prompt. Pending children keep their parent counted in the inbox badge.

Chat turns carry their request ID through tool jobs and workers. Gap, character-swap and extraction requests inherit that ID. The transcript ledger retains the last operator request when receiving an automated handoff. An agent turn ending records usage; only explicit completion closes a request.

Historical entries are linked using an explicit parent, a quoted original prompt, or a matching conversation/session. Unidentified origins are preserved in a collapsed section with controls to link them to the correct prompt. The system does not invent a parent based only on an unrelated recent request. Request numbers, messages, statuses and artifacts are preserved. `POST /api/requests/{id}/parent` rejects missing parents and cycles.

The game boot menu separately saves the character slug and mod disc. Multiple characters in one roster disc can therefore be selected independently. For SmackDown 2, Sonic uses `sd2_sonic_adventure_2_roster` and replaces The Rock; the menu explains which wrestler to choose in game.

Validation: 75 Python tests passed. A real Edge regression reproduced Sonic selecting Tikal before the fix, then verified independent Sonic/Tikal/Shadow choices, persistence after menu reopen and page reload, save-slot changes, Play's boot image and both Original controls. A browser check of the actual inbox renderer verified parent/child placement, preservation of unidentified automated entries and the pending-child badge. Local evidence: `C:/tmp/gbox-boot-selection-verify.py` and `C:/tmp/gbox-sonic-selection-fixed.png`.
