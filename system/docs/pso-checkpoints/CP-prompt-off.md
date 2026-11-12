# The relaunch prompt is off, and what else the log showed

## What I changed

**`relaunch-prompt.js` is no longer loaded.** It was the newest change and the only one that runs on page load, so it is out until the cause is understood. The file
stays on disk, unchanged, so it can come back once we know it is safe.

Kept:

* the `pip-relaunch-prompt` clause in the compact allow-list - inert without the script;
* the host's `gboxRememberGame` call - a try/catch one-liner that does nothing when the global is absent.

## What the log says about the unresponsiveness

Your relaunch is recorded, and one line stands out:

```
12:33:49  app started
12:33:51  relaunch prompt ready
12:34:19  [embed] Game-window helper stopped answering (no answer to attach); a new one starts with the next command
12:34:21  padtakeover sid=null
```

**`Game-window helper stopped answering`** is the app's own diagnostic for the component that finds and attaches the game window. With **no session running at
all** (`live: 0`), there is nothing for it to attach to - and the app can sit waiting on that path, which matches "a little unresponsive".

So there are two candidate causes and I am not going to guess between them:

1. **the new script** - now removed;
2. **the game-window helper** failing to attach with no game running - unrelated to my script, and visible in the app's own log.

## What to do

**Restart gBox once more.** Two outcomes:

* **the menu works** - the script was the cause, and it stays out;
* **the menu still does not** - then it is the game-window helper or the `user-select` rule, and I will revert that rule next, since it is the other change that
  touches every element on the page.

## What I will not claim

I have not reproduced the failure, and I cannot click in the app myself. What I have is the log line above and the knowledge that two of my changes are new on
this page load. **The script is out; the next restart tells us which half we are in.**
