# Automatic session observers

`python -m gbox.session_observers --config gbox.toml` runs beside the control API.
Every running operator session receives two persistent roles, including sessions
already running when the observer starts. Agent-owned test sessions are excluded;
labeling one as `owner: you` opts it in. No favorite is required.

The model role schedules the existing native roster collector once per game.
Missing readers, failures and partial collection create one durable inbox repair
per game. Hermes receives the exact game/session and instructions to develop
readers with REA/Ghidra against owned files. A screenshot is never reported as a
native model, and unsupported titles remain visibly incomplete.

The gameplay role samples fresh session frames approximately every 30 seconds,
using the configured local vision model. At most two observations run concurrently;
other sessions remain attached and receive fair turns. Each observation records
visible actors, HUD values, changes, uncertain mechanics hypotheses, a timestamp
and a stored screenshot. Identical images skip inference. All observations persist
in `session_observation`; the session keeps its latest 40 for display. Capture/model
errors back off, and repeated errors create an actionable repair request.

Only `get_frame` and native `characters collect` jobs are dispatched by this
service. It cannot issue controls, pause, relaunch, write memory or use the GPU
capture path that pauses games. Native files can be extracted while the operator
plays. Unsupported live capture needs a repair; observation does not make every
game's format or native replacement immediately supported.

The Sessions workbench shows **Session agents**, extraction status, repair IDs,
observations and evidence. Its Pause/Resume control governs future observation and
collection scheduling; an already-running native extraction may finish. Closing
the game ends observation, and late vision responses are discarded. API:
`GET/POST /api/sessions/{session_id}/observers`; POST accepts `{"enabled": false}`.
Hermes can read the same state through `get_session_observers`.

On Spark, run this as a user service with the same working directory/config and
Python environment as the API. The process holds a singleton lock and recovers
existing collection/capture jobs after restart. It can start without interrupting
the API or games. API/UI additions become available after the backend refreshes.
