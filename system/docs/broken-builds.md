# Broken build lifecycle

The warning icon at the top left of a Mods card marks a build broken, accepts an operator note, and reuses its existing build report when available. The card shows static and investigation status. Operator launch and download routes refuse the flagged build; agents can still investigate it on an idle test machine.

Broken files are temporary evidence, not a permanent archive:

1. Preserve the collection copy and any local variants under `cache/.broken-builds/<digest>/files` on Spark. Verify the complete file list, sizes, and SHA256 hashes.
2. Queue `file_mod` with `op=quarantine_build` on the selected PC. The worker uploads missing evidence, checks Spark's sealed manifest, checks that its local files did not change, and checks running sessions before removing local copies. Running builds defer cleanup. Retention skips flagged builds.
3. Investigate the exact archived bytes and use the findings to repair and verify the build or writer. The report includes archive IDs and the evidence location.
4. POST `/api/builds/{game_id}/{name}/broken/analysis` with nonempty `findings` and `resolution` (include repair and validation evidence), then complete the linked request. Neither step alone deletes the evidence.
5. The cleanup loop deletes the archived payloads, including abandoned partial uploads, and unchanged broken collection copies. A repaired replacement with different bytes is kept. Ticket history, findings, manifests, and deletion receipts remain.

The selected PC needs the updated worker for preservation jobs. An older worker fails the unknown operation without deleting the build. After updating, POST the same `/broken` action to retry a blocked cleanup. A preservation or upload failure leaves the PC's files intact. No emulator is stopped by this workflow.

Validation: isolated Python tests cover checksum failures, local-only uploads, successful worker preservation/removal, offline preservation, active sessions, completed-ticket gating, repaired replacements, retention protection, and existing-ticket reuse. Node tests and the headless browser fixture cover note submission, card status, disabled Play, reduced motion, and ticket navigation. Screenshots in `evidence/broken-builds` use sample data; they are not live gameplay evidence.
