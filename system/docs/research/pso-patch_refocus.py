"""Give the keyboard back to the game after a toolbar click or a dialog.

The symptom: after using the mod buttons, the game ignores input - the character does not move, and presses do nothing. The app window is focused, the
PiP is active, and the session is live, so the OS-level focus is not the problem.

The problem is **DOM focus**. Clicking a toolbar button (or typing in the dialog) moves the page's focus to that element, and from then on the key
events are delivered to the button rather than to the game surface. `#gpu-game` only receives keys while it holds focus, and the app already has the
helper for that: `window.GBoxGPUVideo.focus()`.

So a `refocusGame()` helper is called at the end of every mod click and when a dialog closes, returning the keyboard to the game automatically. That is
what makes "click a mod, then keep playing" work instead of appearing to freeze the character.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

if "window.gboxRefocusGame" not in text:
    anchor = "// A real dialog for asking values."
    if text.count(anchor) != 1:
        raise SystemExit("dialog anchor not found")
    helper = r'''// Clicking a toolbar button (or typing in a dialog) moves DOM focus off the game surface, and from then on the key events go to the button instead of
// the game - which looks exactly like the game ignoring input. This hands the keyboard back to the surface after any UI interaction.
window.gboxRefocusGame = () => {
  try {
    const surface = document.querySelector('#gpu-game');
    if (surface && surface.style.display === 'block' && window.GBoxGPUVideo?.focus) window.GBoxGPUVideo.focus();
    else document.querySelector('#playhost')?.focus?.();
  } catch (error) { /* focus is best effort */ }
};

'''
    text = text.replace(anchor, helper + anchor, 1)
    print("refocus helper added")

# the dialog hands focus back when it finishes
old_finish = "  const finish = (value) => { box.remove(); window.gboxPipCover?.(false); document.removeEventListener('keydown', onKey, true); resolve(value); };"
new_finish = "  const finish = (value) => { box.remove(); window.gboxPipCover?.(false); document.removeEventListener('keydown', onKey, true); window.gboxRefocusGame?.(); resolve(value); };"
if text.count(old_finish) == 1:
    text = text.replace(old_finish, new_finish, 1)
    print("dialog returns focus")

# and so does every mod click, after the RPC
old_tail = """            const out = await window.gboxPsoRpc(mod.op, fields || {});
            toast(out ? `${mod.id}: sent` : `${mod.id}: no answer`);
          } catch (error) {
            toast(`mod failed: ${(error && error.message) || error}`);
          }"""
new_tail = """            const out = await window.gboxPsoRpc(mod.op, fields || {});
            toast(out ? `${mod.id}: sent` : `${mod.id}: no answer`);
          } catch (error) {
            toast(`mod failed: ${(error && error.message) || error}`);
          } finally {
            window.gboxRefocusGame?.();
          }"""
if text.count(old_tail) == 1:
    text = text.replace(old_tail, new_tail, 1)
    print("mod clicks return focus")

path.write_text(text, encoding="utf-8")
print("done")
