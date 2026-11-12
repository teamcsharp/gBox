"""Fix the mod row: make the icons fit, and make every click report what happened.

Two complaints, and both are real:

1. **Cramped.** The buttons had no sizing rules, so twenty-one of them were squeezed into whatever space was left and their glyphs overlapped. They now
   have a fixed 22x22 box, 14x14 icons, a small gap, and the row scrolls horizontally instead of crushing everything.

2. **Clicks do nothing.** A per-button `onclick` set inside a builder that runs once is fragile: if any statement in the handler throws before the RPC -
   a missing helper, a stale element - the click is silently dead with no message. This replaces it with **event delegation** on the container (one
   listener that survives rebuilds) and wraps the work in a try/catch that surfaces the error in a toast, so a failure is visible instead of silent.

   It also removes a real ordering hazard: `gboxPsoRpc` and `askFor` are defined after the point where the buttons are built, so a click that happened
   before that code ran would have found them missing. The delegated handler resolves them at click time, not at build time.
"""
import pathlib

page = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\index.html")
text = page.read_text(encoding="utf-8")

# --- 1. layout rules for the row -------------------------------------------------
css_anchor = "#compact-controls [data-compact-coach] { flex:1 1 180px; min-width:0; -webkit-app-region:no-drag; }"
css_add = (
    css_anchor + "\n"
    "  /* the per-game mod icons: a fixed box each, a gap between them, and the row scrolls rather than crushing itself */\n"
    "  #compact-controls [data-game-mods] { display:flex; align-items:center; gap:3px; flex:0 0 auto; max-width:42vw; overflow-x:auto; overflow-y:hidden; -webkit-app-region:no-drag; }\n"
    "  #compact-controls [data-game-mods][hidden] { display:none !important; }\n"
    "  #compact-controls [data-game-mods] button { flex:0 0 auto; width:22px; height:22px; padding:0; display:inline-flex; align-items:center; justify-content:center; background:transparent; border:1px solid transparent; border-radius:4px; color:var(--fg); -webkit-app-region:no-drag; }\n"
    "  #compact-controls [data-game-mods] button:hover { background:#2a2f39; border-color:#3d4450; }\n"
    "  #compact-controls [data-game-mods] button[data-on=\"1\"] { border-color:var(--acc); color:var(--acc); }\n"
    "  #compact-controls [data-game-mods] svg { width:14px; height:14px; display:block; }"
)
if css_anchor in text and "data-game-mods] button" not in text:
    text = text.replace(css_anchor, css_add, 1)
    print("cramped: sizing and spacing added to the mod row")

# --- 2. replace the builder's click wiring with delegation ----------------------
start = text.find("      const modSvg = icon =>")
end = text.find("      window.gboxBuildMods = buildMods;")
if start < 0 or end < 0:
    raise SystemExit("mod builder block not found")

builder = r'''      const modSvg = icon => `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="${icon}" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
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
          host.append(button);
        }
        return mods;
      };
      // One delegated listener: it survives every rebuild, and it reports failures instead of swallowing them.
      if (!controls.dataset.modsWired) {
        controls.dataset.modsWired = '1';
        controls.addEventListener('click', async event => {
          const button = event.target.closest?.('[data-game-mods] button[data-game-mod]');
          if (!button) return;
          event.preventDefault();
          event.stopPropagation();
          try {
            const mods = window.gboxGameMods?.modsFor(compactTitle) || [];
            const mod = mods.find(entry => entry.id === button.dataset.gameMod);
            if (!mod) { toast('That button is not in the current game\u2019s list.'); return; }
            if (mod.open) { root.open(mod.open, 'gbox-mod-' + mod.id, 'width=960,height=760'); return; }
            let fields = null;
            if (mod.ask) {
              if (typeof window.gboxAsk !== 'function') { toast('The dialog is not loaded yet - reload once.'); return; }
              fields = await window.gboxAsk(mod.ask);
              if (!fields) return;
            }
            if (mod.build && fields) fields = mod.build(fields);
            if (mod.toggle) {
              button.dataset.on = button.dataset.on === '1' ? '0' : '1';
              fields = button.dataset.on === '1' ? mod.toggle.on : mod.toggle.off;
            }
            if (typeof window.gboxPsoRpc !== 'function') { toast('The RPC helper is not loaded yet - reload once.'); return; }
            const out = await window.gboxPsoRpc(mod.op, fields || {});
            toast(out ? `${mod.id}: sent` : `${mod.id}: no answer`);
          } catch (error) {
            toast(`mod failed: ${(error && error.message) || error}`);
          }
        });
      }
'''
text = text[:start] + builder + text[end:]
page.write_text(text, encoding="utf-8")
print("clicks: delegated, with errors surfaced instead of swallowed")
