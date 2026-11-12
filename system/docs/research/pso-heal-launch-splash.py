"""Make the launch splash self-heal when the game is running but the poll missed the finish.

The evidence says the launch itself is healthy: job `79276d0fa07c45cc` created 08:41:57, started 08:41:58, **finished 08:42:16 - 18.4 s** - at **100%** with the message
*"Running natively in its own window"*, and its `output.session_id` was present. The emulator is up and sitting at PSO's title screen.

Yet the browser showed the splash at ~25% more than twenty minutes later. That is a **stale client**, not a stuck launch: the poll loop in `web/index.html` only
leaves the splash when it observes `j.state === "succeeded"`, and if that observation is missed - a throttled tab in a remote desktop, a dropped request, a page whose
timers were suspended - nothing else ever clears it. The game runs behind an overlay that never lifts, which reads exactly as "PSO freezes while loading".

**The fix**: while the launch job is not terminal, also ask whether a session for this game is already running. If one is, the launch has succeeded by definition -
hide the splash and show it. That makes the screen agree with the game instead of depending on one message arriving.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\web\index.html")
text = path.read_text(encoding="utf-8")

anchor = """    if (j.state === "queued" && waitNote) loader.progress(1, waitNote);
    else if (j.progress) loader.progress(j.progress.pct, j.progress.msg);
    else if (j.state === "running") loader.progress(3, "Worker picked up the launch");"""

addition = """    if (j.state === "queued" && waitNote) loader.progress(1, waitNote);
    else if (j.progress) loader.progress(j.progress.pct, j.progress.msg);
    else if (j.state === "running") loader.progress(3, "Worker picked up the launch");
    // Self-heal: if the game is already running, the launch succeeded - even when this poll missed the finish.
    // Without this the splash can outlive a healthy launch (a throttled tab in a remote desktop never sees
    // "succeeded"), and the game plays behind an overlay that never lifts, which reads as "it freezes while loading".
    if (!["succeeded", "failed", "cancelled", "rejected"].includes(j.state) && i % 5 === 4) {
      const live = await api("/api/sessions", undefined, "GET", 10000).catch(() => null);
      if (LOADING !== launch) return;
      const mine = Array.isArray(live) && live.find(s => s.state === "running" &&
        ((g.title && s.title === g.title) || s.game_id === id || s.session_id === job.id));
      if (mine) {
        LOADING = null;
        loader.progress(100, "Running - opening the game");
        setTimeout(() => { if (LAST_LAUNCH === launch && !LOADING) loader.hide(); }, 300);
        return show("Sessions", mine.session_id);
      }
    }"""

if "Self-heal: if the game is already running" in text:
    print("watchdog already present")
else:
    count = text.count(anchor)
    print("anchor count:", count)
    if count != 1:
        raise SystemExit("launch loop anchor not unique")
    text = text.replace(anchor, addition, 1)
    path.write_text(text, encoding="utf-8")
    print("launch splash now self-heals from a running session")

source = path.read_text(encoding="utf-8")
print("present:", "Self-heal: if the game is already running" in source)
print("still hides on success:", "loader.hide()" in source)
