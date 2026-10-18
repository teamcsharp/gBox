# Historical Cxbx diagnostics

`cxbx_diagnostics` is a read-only Windows worker tool. Inputs are an exact
`launch_job_id`, its expected `game_id`, and optional exact `stop_job_id`.
There are no arbitrary path, PID, script, launch, or settings inputs.

The wrapper retrieves the accepted launch job and receipt from the control
plane. It requires successful completed acceptance, matching input/output
hashes, timestamps, game, Cxbx adapter, session, and worker identity. A stopped
session can be inspected. If the worker was refreshed, the existing canonical
server worker alias must resolve to the executing Windows worker; matching a
name supplied by the caller is insufficient. An optional stop receipt must prove
that this exact session ended. No broad job or process scan is performed.

The collector reads nine fixed files: four Cxbx binaries, the exact extracted
`default.xbe`, `.gbox-installed.json`, selected `settings.ini` values, and the two
gBox launch logs. Binaries have a 128 MiB limit per file, small text files a
128 KiB limit, and large logs return two 32 KiB samples without a false full-file
hash. Linked/reparse paths, unexpected handle targets, changes during reading,
and oversized files are rejected. Missing or unavailable evidence is explicit.
No saves, controller mappings, network settings, or history values are read into
the report. Current hashes and timestamps do not prove the files were identical
at launch. Installation metadata is not treated as independent binary proof.

The historical launch format does not record process creation times. The tool
therefore reports process/window evidence unavailable instead of trusting a
possibly recycled PID. It does not enumerate processes or attach to one. A
render window or nonblack frame is not gameplay acceptance, and this tool does
not repair the black screen or declare the original request complete.

The JSON artifact retains the accepted source receipt and collection worker
identity. `agent_use` remains true for agent dispatch. This exact read-only tool
is exempt from the worker's volume-lowering path and active audio-quieting set;
other agent jobs retain existing behavior.

## Activation boundary

Workers import tools into a long-lived process; each job uses a thread, not a
fresh Python child. A source deployment or renderer reload does not activate
this tool. The desktop reconnect action refuses a still-running worker, and the
app relaunch action can stop its worker and native children and update the
server. Do not use those actions as an unreviewed diagnostic shortcut. Activate
through separately authorized idle worker maintenance and verify that the same
node advertises `cxbx_diagnostics` before submitting it. No automatic reload,
restart, game launch, or historical retry is added here.
