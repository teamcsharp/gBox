The desktop shell and standalone web shell share the background 3D task popup. Embedded pages leave popup ownership to the desktop. Desktop updates reuse its existing jobs poll; standalone jobs and asset-change polls permit one request at a time and retry after failures.

The popup follows a **running task with a relevant visual asset**. It stays hidden until the reported sprite/image has decoded or a model with geometry has loaded. A queued job, tool name, progress wording or console output alone cannot open it. Missing assets, empty models and renderer failures produce no popup and no substitute shape. The current task's snapshot is preferred; a source donor is labelled as a source preview. Models rotate for inspection without simulated decimation, retargeting or calibration effects.

Changing jobs or models invalidates older downloads. Late results cannot replace the newest model or reopen a closed popup. Replaced models, textures, materials and temporary stage graphics are disposed. The dialog role lets the existing native-emulator cutout handling recognize the non-modal popup.

The popup disappears when processing ends, the task loses its visual, or the control plane can no longer confirm the work. Hiding it keeps that task hidden while it runs; it does not cancel the worker. Ordinary task status and console output remain available in the dashboard/job details and game-operation text overlay.

## This PC's automation activity

The desktop and idle operations screen use activity mode. Its popup additionally requires running work to belong to this worker and have a loaded relevant image/model. RE, compilation, cleanup and service work without such assets stays in the dashboard rather than opening a visual window. Queued and unassigned entries remain in the eligible-work list. The desktop resolves its worker from the shared cached worker inventory. The idle iframe owns its own scoped popup; the parent suspends its duplicate without creating another polling loop.

The operation selector switches between concurrent local jobs. Expand gives a larger inspection window. The scrollable console shows up to the latest 50 reported progress lines and follows the tail only while already at the bottom. **Pause output** freezes console and measurement text for reading without pausing execution. Controls inside the idle popup remain usable; Escape or clicking the idle-page background still returns to gBox.

The window shows the worker/job/request IDs, current step, last worker-update age, measured fitting data (scale, heights, role/vertex/triangle counts, encoding sizes), and a stage flow that leaves goal verification pending. Backend snapshots contain only whitelisted presentation inputs, up to 50 bounded log lines and 12 model rows including the current model; larger rosters explicitly show how many rows are displayed. Arbitrary tool inputs, prompts and outputs are omitted.

Both popup modes display the current model's actual writer snapshot, or its source donor while waiting for a fitted snapshot. A preceding character's snapshot is never substituted. New assets remain hidden until loaded; failed assets are suppressed until a different visual is reported. Model rendering is limited to 20 frames per second and skips hidden documents. Nonvisual tasks and unavailable renderers do not allocate a fallback animation.

Writer snapshots are preview artifacts and may use the existing reduced geometry budget; the viewer labels them as task model snapshots. Reported native triangle/vertex measurements and full build artifacts remain distinct from the preview's display geometry.

The ReAgent reverse loop now reports bounded excerpts of actual Ghidra source and reconstructed candidate code, evidence requests, model-call/round counts and checker/structural verdicts. Progress publication is asynchronous and retains the latest code excerpt across coalesced updates. It does not stream model reasoning or claim a checker PASS is verified native gameplay. Other tools continue to show the progress they actually publish; this is not a capture of every subprocess console or a frame-by-frame mesh edit recorder.

## Fixing a bad deformation: the R buttons

While a writer fits models (a cast build, `characters op=cast_swap`, or a single `op=use`), each fitting row names its donor (collection slug), the target game id and the slot (`gbox/fit_events.py`: `plan` rows and `model` events carry `donor`, `game`, `slot`). Two "R" buttons open the Retarget editor (`clients/web/viz/retarget-editor.js`) on that model, in the web shell and in the desktop app:

- the round **R** at the bottom-right corner of the 3D view: the model the view shows (the current row's snapshot, else the newest one);
- the small **R** at the end of each row's stage chips (S R P W D E W): that row's model.

A row without a named donor (an older writer) has no R. The editor opens in its **Goals** view: the donor (left) and the target slot's own skeleton (right) side by side, both laid out in a T-pose front view, with a translucent numbered circle on every joint (head, neck, chest, pelvis, shoulders, elbows, wrists, hips, knees, ankles). The same number and colour on both sides is the same body role, so the correspondence is visible at a glance; the side list repeats it (donor bone → target joint).

- **Drag a donor circle** to where that joint really is on the donor mesh (an elbow guessed too high: drag it down). The move is stored in the profile as `joints: {role: [dx, dy, dz]}` (fractions of the donor height, at most a quarter per axis). Builds move the donor rig joint before fitting and re-derive which limb segment owns the vertices the moved elbow / wrist / knee / ankle swept across, so the bend, the segmentation and the weights follow it (`gbox/retarget_profile.py: move_joints`, called by `sm64_swap.retarget`, `doa2_weighted_retarget.retarget` and `re4gc_enemies.retarget`).
- **Click a circle** to pick which donor bone it is from a list of every bone (the same role assignment as "What is what").
- The target side shows the donor fitted onto the target skeleton and updates live as circles move. The target skeleton is the one the slot's last build actually loaded (the shared retargets' `retarget` stage carries the fit's goals; the server keeps the newest per game and slot, `GET /api/retarget/goals`), else the slot's stock model in the collection, else a standard humanoid.
- **Save for this slot** writes the profile. **Save and rebuild this slot** saves, then queues the same `characters` call for that slot only (the job's own call, else the game's recorded special-builds cast recipe holding this donor in this slot: `slots=<slot>`, `assignments=[{slot, character}]`, `launch=false`, `rebuild=true`) through `POST /api/games/{id}/special_builds/rebuild`. The popup follows that job, so its fitting shows in the same window.

Writers that do not use the shared retargets with the profile (GTA III / Vice City / Stories, RE6, 007 AUF, MGS VR, Crazy Taxi's per-part fit, the sprite writers) do not honour joint moves yet.
