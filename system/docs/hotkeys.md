# gBox hotkeys

Every key and mouse gesture gBox reacts to, and where it works. **None of them apply outside gBox**: while another
application (Blender, a browser, an editor) is the window in front, gBox registers no global key, swallows no click or
key, and reacts to nothing that application receives. This is the default and only behaviour (Settings shows a note).

## In the gBox window

Handled by the app itself (`before-input-event` in `clients/desktop/main.js`, page `keydown` listeners), so they exist
only while a gBox window has the keyboard.

| Key | Action |
| --- | --- |
| F2 | Save state (current slot) |
| Shift+F2 / Ctrl+F2 | Save slot + / - |
| F3 | Autoplay on/off (also `A` when no text box has focus) |
| F4 | Load state |
| F5 | Full recovery, step by step in the reconnect dialog: update this PC's gBox (a fast-forward of a clean `main` checkout, then one reload), reconnect to the Spark, show MercMode's current game in the PiP with a fresh stream (a new encoder when no frame arrives within 3 s) and its autobot driving, and put the main window on the same game. The operator's own game on this PC stays on screen. See `clients/desktop/reconnect-flow.js`. |
| F11 / Alt+Enter | Full screen on/off |
| Esc | Leave full screen |
| Ctrl+I | Game eyedropper |
| hold ~ (key under Esc) | Push-to-talk to gBox |

## While a native game is docked in gBox and has the keyboard

The docked emulator window owns the keyboard focus, so the keys above never reach gBox's pages. gBox holds them as
Electron global shortcuts (F2, Shift+F2, Ctrl+F2, F3, F4, F5, Ctrl+I, Alt+Enter, F11) **only while a game is docked AND
gBox (or the game docked in it) is the foreground window** (`clients/desktop/hotkey-scope.js`). The foreground comes from
`winembed.py` (an `EVENT_SYSTEM_FOREGROUND` hook plus a 100 ms recheck); the window's blur / minimize / hide release
them at once and quitting unregisters everything. The moment another application comes to the front they are released,
so Blender's F2 rename, F3 search, Ctrl+I invert selection and F11 work normally.

`winembed.py` low-level hooks, all scoped to gBox:

| Input | Action | Scope |
| --- | --- | --- |
| hold ~ | Push-to-talk | Swallowed only while a game is docked and gBox / the docked game is in front; elsewhere it passes through untouched (a release in another app still ends a talk started in gBox) |
| Right-click on the docked game | Game context menu | Only when the window actually under the cursor (`WindowFromPoint` -> `GA_ROOTOWNER`) is gBox / the docked game |
| Ctrl+click on the docked game | Eyedropper at that spot | Window under the cursor is gBox's, **and** gBox is in front |
| Alt+drag over the game or gBox | Pick whip ("swap this with that") | Window under the cursor is gBox's, **and** gBox is in front |
| Left/middle click on the game | Closes gBox's open menus (not swallowed) | Window under the cursor is gBox's |
| Drop of a sidebar card on the game | Card menu (not swallowed) | Window under the cursor is gBox's |

A screen rectangle alone never counts: a click in Blender over the screen area where the gBox window sits behind it goes
to Blender.

## Emulator hotkeys held by the Windows worker (`gbox/tools.py`)

Registered with `RegisterHotKey` only while the emulator is in front, checked every 30 ms, and released the moment
anything else is (`_scoped_hotkey`). A press that lands in the gap right after a switch is replayed to the window now in
front.

| Key | Action | Held while |
| --- | --- | --- |
| Keypad minus | Rewind 5 s (RetroArch with rewind on) | RetroArch's window, or the gBox window it is docked in / gBox.exe, is in front. Blender's numpad zoom-out is never taken |
| F4 | Load the newest save state (RPCS3 relaunch) | RPCS3's own window is in front (docked in gBox, gBox's F4 above does it) |

## Blender

The gBox Blender add-on adds **Ctrl+Shift+V** (paste the gBox model) to Blender's own 3D View keymap
(`clients/blender/gbox_addon.py`). It lives inside Blender and works only there.

## Keys gBox sends (not hotkeys)

Agent input to games is synthesized only while the game (or gBox docking it) is the foreground window, and a batch stops
the moment another application comes to the front, so keys never land in another app: `adapters.win_send_keys`,
Xenia's physical-keyboard path (`gbox/xenia.py`) and the yuzu pad bridge (`gbox/yuzu_input.py`, only while yuzu has
focus). NinjaRipper's rip hotkey (F10 by default, `gbox/ninja_ripper.py`) is pressed once per explicit rip request, after
trying to bring the game to the front (NinjaRipper reads the global key state, so that focus is best effort).
