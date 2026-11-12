"""Fix the launch: use the app's own launch route, not `launch_game` with a partial entry.

The operator's screen showed a real 422:

```
Input invalid: 4 validation errors for LaunchIn
  game_platform / game_source_paths / game_format / game_profile_id  all "Field required"
```

`LaunchIn.game` is a **`CatalogEntry`**, and the entry the add-game panel sends comes from `/api/catalog` - the **list** - which does not carry every required field.
The panel only fetched the full entry when `!game.launch`, so an entry that happened to have a `launch` key was sent as-is and rejected.

The app never sends `launch_game` with a hand-built entry: the Play button calls

```
POST /api/games/{gid}/launch?node=auto
```

and the server builds the full `LaunchIn` from the stored catalogue entry. That route cannot be given a malformed entry, so all three of my call sites now use it:

1. the add-game panel's `start()`;
2. the recent strip's tile click;
3. the host's `launch` in `index.html`.

An empty JSON body is sent because the picker's `io.api(path, body)` does not forward an HTTP method - with no body it would go out as a GET.
"""
import pathlib

changes = 0
picker = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\pip-stream-picker.js")
text = picker.read_text(encoding="utf-8")

# 1. the panel's start(): resolve nothing, just call the app route
old_start = """        // A session-derived tile carries only id and title; /api/catalog/<id> gives the entry launch_game needs.
        if (!game.launch && io.api) {
          try { const full = await io.api('/api/catalog/' + encodeURIComponent(String(game.game_id))); if (full && (full.game_id || full.id)) game = full; }
          catch { /* fall back to what we have */ }
        }"""
new_start = """        // The app's own launch route builds the full LaunchIn from the stored catalogue entry; sending a
        // hand-built entry to launch_game was rejected with "game_platform / game_source_paths / game_format /
        // game_profile_id Field required" because the list entry does not carry them.
        const appLaunch = async target => {
          const id = String((target && (target.game_id || target.id)) || '');
          if (!id) throw new Error('no game id');
          const answer = await call('/api/games/' + encodeURIComponent(id) + '/launch?node=auto', {});
          return answer;
        };"""
if old_start in text:
    text = text.replace(old_start, new_start, 1)
    changes += 1
    print("panel: start() now resolves via the app launch route")

# 2. start()'s launch call
old_body = """        try {
          const body = { tool: 'launch_game', input: { game } };
          if (typeof io.launch === 'function') { await io.launch(game); }
          else if (io.api) {
            const answer = await io.api('/api/jobs', body);
            if (answer && answer.ok === false) throw new Error(answer.error || 'refused');
          } else throw new Error('no way to launch from here');
        } catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }"""
new_body = """        try {
          await appLaunch(game);
        } catch (error) { if (valid()) message('Could not start it: ' + String(error?.message || error)); }"""
if old_body in text:
    text = text.replace(old_body, new_body, 1)
    changes += 1
    print("panel: launch call switched to appLaunch")

# 3. the recent strip's click
old_strip = """          const go = typeof io.launch === 'function'
            ? io.launch(game)
            : io.api('/api/jobs', { tool: 'launch_game', input: { game } });
          Promise.resolve(go).catch(error => message('Could not start it: ' + String(error?.message || error)));"""
new_strip = """          const id = String(game.game_id || game.id || '');
          const go = call('/api/games/' + encodeURIComponent(id) + '/launch?node=auto', {});
          Promise.resolve(go).catch(error => message('Could not start it: ' + String(error?.message || error)));"""
if old_strip in text:
    text = text.replace(old_strip, new_strip, 1)
    changes += 1
    print("strip: launch call switched to the app route")

picker.write_text(text, encoding="utf-8")

import subprocess
result = subprocess.run(["node", "--check", str(picker)], capture_output=True, text=True, timeout=120)
print("picker node check:", "OK" if result.returncode == 0 else (result.stderr or "")[:300])

# 4. the host's launch
page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
page_text = page.read_text(encoding="utf-8")
old_host = """    launch: async game => {
      try { globalThis.gboxRememberGame?.(game); } catch {}
      const worker = (S.workerName || '').trim();
      const body = { tool: 'launch_game', input: { game } };
      const answer = await gbox.api('/api/jobs', body);
      if (!answer.ok) throw new Error(answer.error || 'the launch was refused');
      return answer.data;
    },"""
new_host = """    launch: async game => {
      try { globalThis.gboxRememberGame?.(game); } catch {}
      // The app's own route: it builds the full LaunchIn from the stored entry, so a partial list entry
      // can never be rejected for missing game_platform / game_source_paths / game_format / game_profile_id.
      const id = String((game && (game.game_id || game.id)) || '');
      if (!id) throw new Error('no game id to launch');
      const answer = await gbox.api('/api/games/' + encodeURIComponent(id) + '/launch?node=auto', {});
      if (!answer.ok) throw new Error(answer.error || 'the launch was refused');
      return answer.data;
    },"""
if old_host in page_text:
    page_text = page_text.replace(old_host, new_host, 1)
    page.write_text(page_text, encoding="utf-8")
    changes += 1
    print("host: launch switched to the app route")
else:
    print("host anchor not found")

print("changes:", changes)
source = picker.read_text(encoding="utf-8")
print("panel uses the app route:", "/api/games/' + encodeURIComponent(id) + '/launch?node=auto" in source)
print("no launch_game left in the picker:", "launch_game" not in source)
