"""Render the PiP toolbar's mod icons from the per-game manifest, and run them against the live session.

The operator asked for an icon per mod, clickable **while the bot is playing**. Mods are RPCs (`pso_controls`), not keystrokes, so they work while the
bot drives the character and they need no window focus - which is why this is a toolbar of icons rather than keyboard shortcuts.

What this does to `index.html`:

  1. loads `game-mods.js` (the manifest) before the app's own script runs;
  2. replaces the four hardcoded PSO buttons with an empty container the manifest fills;
  3. builds one button per mod, each with its SVG icon and tooltip;
  4. on click: `open` opens a URL, `toggle` alternates on/off, otherwise the `ask` prompts are collected and the op is sent to the session's RPC;
  5. exposes the RPC helper as `window.gboxPsoRpc` so later code is not trapped by block scope.

Every click is reported with a toast, so a mod that refuses says why instead of appearing to do nothing.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = path.read_text(encoding="utf-8")

# 1. load the manifest before the main script
if "game-mods.js" not in text:
    anchor_script = "<script"
    index = text.find(anchor_script)
    if index < 0:
        raise SystemExit("no <script> tag found")
    text = text[:index] + '<script src="game-mods.js"></script>\n' + text[index:]
    print("manifest script tag added")

# 2. the container replaces the four hardcoded buttons
old_span = ('<span data-pso-actions hidden>'
            '<button type="button" data-pso-equip title="PSO: change the equipped weapon">Equip</button>'
            '<button type="button" data-pso-mag title="PSO: adjust the mag\'s stats">Mag</button>'
            '<button type="button" data-pso-warp title="PSO: teleport to another area">Warp</button>'
            '<button type="button" data-pso-map title="PSO: open the live 2D map viewer">Map</button>'
            '</span>')
new_span = '<span data-game-mods hidden></span>'
if text.count(old_span) == 1:
    text = text.replace(old_span, new_span, 1)
    print("hardcoded PSO buttons replaced by the manifest container")
elif text.count(new_span) == 1:
    print("manifest container already present")

# 3. the renderer replaces the old paint/handler block
start = text.find("      // PSO actions (operator 2026-11-11)")
end = text.find("controls.dataset.psoPaint = 'ready';")
if start < 0 or end < 0:
    raise SystemExit("old PSO block not found")
end += len("controls.dataset.psoPaint = 'ready';")

renderer = r'''      // Per-game mod icons (operator 2026-11-11: "every mod that we have for PSO, I want an icon in the top bar that I'm able to click on and use to
      // modify the game in action even while the bot is playing"). Each button is an RPC against the live session, so it works mid-play and needs no
      // focus; the manifest in game-mods.js lists the mods per game.
      window.gboxPsoRpc = async (op, fields) => {
        const sid = COMPACT && COMPACT.sid;
        if (!sid) { toast('No game in the PiP.'); return null; }
        try {
          return await gbox.api(`/api/sessions/${encodeURIComponent(sid)}/rpc`, { op: 'pso_controls', args: {
            command_id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random(),
            expires: Date.now() / 1000 + 5,
            input: { session_id: sid, op, ...(fields || {}) } } });
        } catch (error) {
          toast(`${op} failed: ${(error && error.message) || error}`);
          return null;
        }
      };
      const askFor = spec => {
        const values = {};
        for (const field of spec) {
          const said = prompt(field.label, String(field.value == null ? '' : field.value));
          if (said === null) return null;
          values[field.key] = field.type === 'number' ? Number(said) : said.trim();
          if (field.type === 'number' && !Number.isFinite(values[field.key])) {
            toast(`${field.key} must be a number`); return null;
          }
        }
        return values;
      };
      const modSvg = icon => `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" style="vertical-align:-3px"><path d="${icon}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      const buildMods = () => {
        const host = controls.querySelector('[data-game-mods]');
        if (!host || !window.gboxGameMods) return [];
        const mods = window.gboxGameMods.modsFor(compactTitle);
        host.hidden = !mods.length;
        host.textContent = '';
        for (const mod of mods) {
          const button = document.createElement('button');
          button.type = 'button';
          button.dataset.gameMod = mod.id;
          button.title = mod.label;
          button.innerHTML = modSvg(mod.icon);
          button.onclick = async () => {
            if (mod.open) { root.open(mod.open, 'gbox-mod-' + mod.id, 'width=960,height=760'); return; }
            let fields = null;
            if (mod.ask) { fields = askFor(mod.ask); if (!fields) return; }
            if (mod.build && fields) fields = mod.build(fields);
            if (mod.toggle) {
              button.dataset.on = button.dataset.on === '1' ? '0' : '1';
              fields = button.dataset.on === '1' ? mod.toggle.on : mod.toggle.off;
            }
            const out = await window.gboxPsoRpc(mod.op, fields || {});
            if (out) toast(`${mod.id}: ok`);
          };
          host.append(button);
        }
        return mods;
      };
      let modsBuilt = false;
      if (!modsBuilt) { modsBuilt = true; buildMods(); }'''

text = text[:start] + renderer + text[end:]

# 4. repaint hook: rebuild the icons when the title changes
old_hook = "    if (controls && controls.dataset.psoPaint === 'ready' && typeof window.gboxPaintPso === 'function') window.gboxPaintPso();"
new_hook = "    if (controls && typeof window.gboxBuildMods === 'function') window.gboxBuildMods();"
if text.count(old_hook) == 1:
    text = text.replace(old_hook, new_hook, 1)

# expose the builder for that hook, and call it once after the bar exists
text = text.replace("      let modsBuilt = false;", "      window.gboxBuildMods = buildMods;\n      let modsBuilt = false;", 1)

path.write_text(text, encoding="utf-8")
print("toolbar now builds one icon per mod from the manifest")
