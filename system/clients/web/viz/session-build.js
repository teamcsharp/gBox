/* Session header: the build a session runs, named and renamed in place (the web shell's Sessions view; the desktop app
   shows this shell in its Play webview).
   - a session of a build (session.collection_mod, else session.mod; a staged "<mod>~<build>" copy is still that build,
     GET /api/sessions names it mod_build) shows "<game> · <build>": the operator's display name (mod_title), else the
     folder name
   - click the build name (or ✎, or the game title) and it turns into a text field: Enter saves through the same
     PATCH /api/builds/{game}/{folder} as the Mods cards, Builds and Special builds (#1656), Esc cancels, an empty name
     restores the original. The folder and its marker never change.
   - after a rename it offers "★ Favorite this build" (PUT /api/builds/{game}/{folder}/favorite): a working build is the
     one to keep (favorites list first and are never evicted)
   - the stock game (no build): the title says "Stock game, no build to rename" and nothing renames it
   - the field carries data-nomic: the shell's dictation wrapper moves a text field into its wrapper, which blurs it,
     and the blur would close the field at once (as on the Mods cards, #1656)
   opts.onRenamed / opts.onFavorite tell the shell, which refreshes the tray (notifications), and the desktop app (launch
   bar, Mods page). sync(row) takes a newer session row (the tray's poll) so a rename made elsewhere shows here too.
   Node tests: tests/test_session_build.cjs. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(root);
  else root.GBoxSessionBuild = factory(root);
})(typeof window === "undefined" ? globalThis : window, function (root) {
  "use strict";
  const SEP = "~";                                         // gbox.built_mods.STAGED_SEP: <mod>~<build>
  const RENAME_TIP = "Rename this build";
  const STOCK_TIP = "Stock game, no build to rename";
  const FAV_TIP = "Keep this build: favorites list first on the Mods page, in Builds and Special builds, and are never evicted";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const CSS = `#session-head .sb-game[data-sb]{cursor:text;border-radius:3px}#session-head .sb-game[data-sb]:hover{background:#ffffff14}
    #session-head .sb-build{display:inline-flex;gap:4px;align-items:center;min-width:0;max-width:100%}
    #session-head .sb-sep{opacity:.6}#session-head .sb-name{cursor:text;border-radius:3px;padding:0 2px;max-width:34ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #session-head .sb-name:hover{background:#ffffff14}#session-head .sb-name:focus-visible{outline:1px solid var(--acc,#6cf)}
    #session-head .sb-ico{background:none;border:0;color:inherit;opacity:.65;cursor:pointer;padding:0 2px;font:inherit;line-height:1}
    #session-head .sb-ico:hover{opacity:1}#session-head .sb-star{color:var(--warn,#f5c542)}
    #session-head .sb-input{font:inherit;font-weight:600;min-width:12ch;max-width:40ch}
    #session-head .sb-note{font-size:12px;opacity:.8}#session-head .sb-fav{padding:2px 8px;font-size:12px;color:var(--warn,#f5c542)}`;

  // the build a session runs, or null for the stock game
  function buildOf(s) {
    if (!s || !s.game_id) return null;
    const name = String(s.mod_build || s.collection_mod || s.mod || "").split(SEP)[0].trim();
    if (!name) return null;
    const display = String(s.mod_title || "").trim();
    return { game_id: String(s.game_id), name, key: `${s.game_id}/${name}`, display_name: display,
             label: display || name, favorite: s.mod_favorite === true };
  }
  const buildPath = b => `/api/builds/${encodeURIComponent(b.game_id)}/${encodeURIComponent(b.name)}`;

  // the build part of the header: "· name ✎" (★ when a favorite), or the rename field; then a note / the ★ offer
  function buildHTML(b, st = {}) {
    if (!b) return "";
    const sep = `<span class="sb-sep" aria-hidden="true">·</span>`;
    if (st.editing) {
      const size = Math.min(46, Math.max(12, b.label.length + 2));
      return sep + `<input class="sb-input" data-sb-input type="text" value="${ESC(b.label)}" size="${size}" maxlength="120"`
        + ` aria-label="Build name" placeholder="${ESC(b.name)}" title="Enter saves · Esc cancels · empty restores the original name (${ESC(b.name)})"`
        + ` spellcheck="false" autocomplete="off" data-nomic>`;
    }
    const tip = b.display_name ? `${RENAME_TIP}: ${b.label} (folder ${b.name})` : `${RENAME_TIP} (folder ${b.name}, no name of its own yet)`;
    return sep + `<b class="sb-name" data-sb="rename" role="button" tabindex="0" title="${ESC(tip)}">${ESC(b.label)}</b>`
      + `<button class="sb-ico" type="button" data-sb="rename" title="${RENAME_TIP}" aria-label="${RENAME_TIP}">✎</button>`
      + (b.favorite ? `<span class="sb-star" title="A favorite build: listed first and kept">★</span>` : "")
      + (st.note ? `<span class="sb-note" role="status"${st.noteTip ? ` title="${ESC(st.noteTip)}"` : ""}>${ESC(st.note)}</span>` : "")
      + (st.offer && !b.favorite ? `<button class="act sb-fav" type="button" data-sb="favorite" title="${ESC(FAV_TIP)}">★ Favorite this build</button>` : "");
  }

  // the header's title: the game, then the build it runs. The stock game's title renames nothing (a tooltip says so).
  function titleHTML(s) {
    const game = ESC((s && s.title) || "Game session"), b = buildOf(s);
    if (!b) return `<b class="sb-game" id="session-title" data-stock="1" title="${STOCK_TIP}">${game}</b>`;
    return `<b class="sb-game" id="session-title" data-sb="rename" title="${RENAME_TIP}: ${ESC(b.label)}">${game}</b>`
      + `<span class="sb-build" id="session-build" data-key="${ESC(b.key)}">${buildHTML(b)}</span>`;
  }

  // head: the header element (#session-head); opts: { session, api(path, body, method), onRenamed(info), onFavorite(info),
  // document }. The stock game mounts too, and never renames.
  function mount(head, opts = {}) {
    const doc = opts.document || root.document;
    const b = buildOf(opts.session);
    const st = { build: b, editing: false, busy: false, note: "", offer: false, quietUntil: 0 };
    const now = opts.now || (() => Date.now());
    const QUIET_MS = 8000;                                   // a poll that left before our save must not undo it on screen
    if (doc && doc.head && !doc.getElementById?.("sb-css")) {
      const style = doc.createElement("style"); style.id = "sb-css"; style.textContent = CSS; doc.head.appendChild(style);
    }
    const host = () => head && head.querySelector && head.querySelector("#session-build");
    const field = () => { const h = host(); return h && h.querySelector && h.querySelector("[data-sb-input]"); };
    function draw() {
      const h = host(); if (!h || !st.build) return;
      h.innerHTML = buildHTML(st.build, st);
      const game = head.querySelector && head.querySelector("#session-title");
      if (game && game.setAttribute) game.setAttribute("title", `${RENAME_TIP}: ${st.build.label}`);
      if (st.editing) { const f = field(); try { f && f.focus && f.focus(); f && f.select && f.select(); } catch {} }
    }
    function start() {
      if (!st.build || st.busy) return false;
      st.editing = true; st.offer = false; st.note = ""; st.noteTip = ""; draw();
      return true;
    }
    function cancel() {
      if (!st.editing) return false;
      st.editing = false; draw();
      return true;
    }
    async function save(value) {
      const bd = st.build; if (!bd || st.busy) return null;
      st.editing = false;
      const v = String(value ?? "").trim();
      if (v === bd.display_name || (!bd.display_name && v === bd.name)) { draw(); return null; }   // nothing changed
      st.busy = true; st.note = "Saving…"; st.noteTip = ""; draw();
      try {
        const r = await opts.api(buildPath(bd), { display_name: v }, "PATCH");
        bd.display_name = String((r && r.display_name) || "").trim();
        bd.label = bd.display_name || bd.name;
        st.note = bd.display_name ? "✓ Renamed" : "✓ Original name restored";
        st.noteTip = `Shown on the Mods page, in Builds, Special builds, the launch bar and notifications; the folder stays ${bd.name}`;
        st.offer = !!bd.display_name && !bd.favorite; st.quietUntil = now() + QUIET_MS;
        const info = { game_id: bd.game_id, name: bd.name, key: bd.key, display_name: bd.display_name, label: bd.label };
        try { opts.onRenamed && opts.onRenamed(info); } catch {}
        return info;
      } catch (e) {
        st.note = "⚠ rename failed"; st.noteTip = String((e && e.message) || e).slice(0, 300);
        return null;
      } finally { st.busy = false; draw(); }
    }
    async function favorite() {
      const bd = st.build; if (!bd || st.busy || bd.favorite) return null;
      st.busy = true;
      try {
        const r = await opts.api(buildPath(bd) + "/favorite", { favorite: true }, "PUT");
        bd.favorite = !r || r.favorite !== false;
        st.offer = false; st.note = bd.favorite ? "✓ Favorite" : ""; st.quietUntil = now() + QUIET_MS;
        st.noteTip = bd.favorite ? "Listed first on the Mods page, in Builds and Special builds, and never evicted" : "";
        try { opts.onFavorite && opts.onFavorite({ game_id: bd.game_id, name: bd.name, key: bd.key, favorite: bd.favorite }); } catch {}
        return bd.favorite;
      } catch (e) {
        st.note = "⚠ favorite failed"; st.noteTip = String((e && e.message) || e).slice(0, 300);
        return null;
      } finally { st.busy = false; draw(); }
    }
    // a newer row of this session (the tray's poll): a rename or ★ made elsewhere (Mods, Builds, the desktop app)
    function sync(row) {
      const nb = buildOf(row);
      if (!nb || !st.build || nb.key !== st.build.key || st.editing || st.busy || now() < st.quietUntil) return false;
      if (nb.label === st.build.label && nb.favorite === st.build.favorite) return false;
      if (nb.favorite) st.offer = false;
      Object.assign(st.build, { display_name: nb.display_name, label: nb.label, favorite: nb.favorite });
      draw();
      return true;
    }

    const at = (e, sel) => e && e.target && e.target.closest && e.target.closest(sel);
    function onClick(e) {
      if (at(e, "[data-sb-input]")) return;                  // clicks inside the field stay in it
      const act = at(e, "[data-sb]");
      if (!act || !head.contains || !head.contains(act)) return;
      const what = act.getAttribute ? act.getAttribute("data-sb") : act.dataset && act.dataset.sb;
      if (what === "rename") { e.preventDefault && e.preventDefault(); start(); }
      else if (what === "favorite") { e.preventDefault && e.preventDefault(); favorite(); }
    }
    function onKey(e) {
      const f = at(e, "[data-sb-input]");
      if (f) {
        e.stopPropagation && e.stopPropagation();            // typing a name never reaches the game or the shell's shortcuts
        if (e.key === "Enter") { e.preventDefault && e.preventDefault(); save(f.value); }
        else if (e.key === "Escape") { e.preventDefault && e.preventDefault(); cancel(); }
        return;
      }
      if ((e.key === "Enter" || e.key === "F2" || e.key === " ") && at(e, ".sb-name[data-sb]")) { e.preventDefault && e.preventDefault(); start(); }
    }
    function onInput(e) {
      const f = at(e, "[data-sb-input]");
      if (f && "size" in f) f.size = Math.min(46, Math.max(12, String(f.value || "").length + 2));
    }
    function onFocusOut(e) {                                 // leaving the field keeps what was typed (as the Mods cards do)
      const f = at(e, "[data-sb-input]");
      if (f && st.editing) save(f.value);
    }
    const on = [["click", onClick], ["keydown", onKey], ["input", onInput], ["focusout", onFocusOut]];
    if (b && head && head.addEventListener) for (const [ev, fn] of on) head.addEventListener(ev, fn);
    function dispose() { if (head && head.removeEventListener) for (const [ev, fn] of on) head.removeEventListener(ev, fn); }
    return { st, sid: opts.session && opts.session.session_id, start, cancel, save, favorite, sync, draw, onClick, onKey, onInput, onFocusOut, dispose };
  }

  return { buildOf, buildHTML, titleHTML, mount, RENAME_TIP, STOCK_TIP, CSS };
});
