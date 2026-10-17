# Review a build, remove its files, retain its lessons

The shared Delete dialog offers Report issues before deleting. It retains the chosen all/this-PC/selected-PC
scope, then accepts a note and up to four screenshots or desired-appearance reference images. Images can be
chosen, pasted, or dropped. Capture running build captures only a uniquely matching game/build on this PC and
hides the form until the frame arrives. It never pauses, stops or launches the game. Existing annotated camera
reports remain available for marking boxes/arrows.

Submit report and remove copies first saves the report and its image artifacts. Only then does it call
POST /api/builds/{game_id}/{name}/review-cleanup with report_id and the selected scope. A cleanup failure leaves
the saved report and images intact. Retry queues cleanup without submitting a duplicate report. Invalid images
or a missing saved report cannot trigger deletion.

Cleanup runs through verified quarantine. Running builds wait until the operator closes them. Each selected PC
must preserve its exact copy before removal, and offline PCs wait for reconnection. Spark-only builds are also
supported. ROM archives are temporary: findings, resolution and completed investigation are required before their
purge. PC-only cleanup retains the Spark collection. Reports, images, recipes, slot facts and analysis history
outlive ROM deletion. Recorded findings and resolution update the feedback revision so subsequent builds must
review the learned cause and repair too. This is retention of evidence, not indefinite retention of broken ROM archives.

GET /api/build-feedback?game_id=<id> exposes durable report notes and image artifact links; existing build reports
are indexed at server startup. Character use/live_use/match/cast_swap jobs with feedback must acknowledge its
exact revisions using feedback_ack {request_id: revision}. Missing/stale acknowledgement returns HTTP 409 with
the reports before a job is queued. Already queued builds are checked again before worker claim, so a new report can hold
a stale job without interrupting one already running. The wait reason is recorded on that queued job. Read-only collection/planning, launch/control jobs and unrelated game IDs
remain independent. Agents must inspect images and address defects; acknowledgement is only a review receipt,
not automatic training, a repaired writer, or proof that a later build is visually correct. New build metadata
retains feedback_reviewed. A later report revision requires another review.

The operator preference is whole-cast replacement in one combined build unless a single target or diagnostic is
explicitly requested. cast_swap with slots=all must not silently reduce a writer with only a single-slot path to
a player replacement. Such writers return unsupported_cast with a capability gap. Liberty City Stories currently
replaces Toni outfits; a native full-cast writer for story/ambient/cinematic characters is still required. Existing
single-character ROMs are not relabelled as full-cast builds. Cutscene requirements from character-replacement-scope.md
still apply.

Validation uses fixture caches, actual screenshot uploads, authenticated APIs and managed browser UI tests. No
operator builds are deleted and no live games are controlled by these tests.
