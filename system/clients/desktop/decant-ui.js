// File menu (title bar ▾ + the app menu's File > Decant…, Ctrl+Shift+D) and the Decant dialog: package this gBox as a zip someone
// without gBox unzips on their own Windows PC to get a standalone gBox (gbox/decant.py). The manifest — what goes in, what is
// left out and why — is shown before anything is saved; nothing from anyone's games ever goes in (docs/model_swaps.md).
(() => {
  if (!window.gbox || !gbox.decantPlan) return;
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const css = document.createElement("style");
  css.textContent = `
  #tb-file { -webkit-app-region:no-drag; background:none; border:1px solid transparent; color:var(--fg); font:12px system-ui; border-radius:6px;
             padding:3px 8px; cursor:pointer; margin-left:-4px; } #tb-file:hover, #tb-file.on { background:#ffffff14; border-color:var(--line); }
  #filemenu { display:none; position:fixed; z-index:72; top:34px; min-width:230px; padding:5px; background:var(--bg); border:1px solid var(--line);
              border-radius:8px; box-shadow:0 10px 30px #0009; font-size:13px; -webkit-app-region:no-drag; } #filemenu.on { display:block; }
  #filemenu button { display:flex; width:100%; justify-content:space-between; gap:20px; background:none; border:0; color:var(--fg); font:inherit;
                     padding:7px 10px; border-radius:5px; cursor:pointer; text-align:left; } #filemenu button:hover { background:var(--card); }
  #filemenu kbd { color:var(--mut); font:11px system-ui; } #filemenu small { display:block; color:var(--mut); font-size:11px; }
  #decant { position:fixed; inset:0; z-index:90; display:none; background:#0009; backdrop-filter:blur(3px); align-items:center; justify-content:center; }
  #decant.on { display:flex; }
  #decant .dlg { width:min(1040px,94vw); max-height:90vh; display:flex; flex-direction:column; background:var(--bg); border:1px solid var(--line);
                 border-radius:12px; box-shadow:0 20px 60px #000c; overflow:hidden; }
  #decant header { padding:16px 20px 12px; border-bottom:1px solid var(--line); display:flex; gap:14px; align-items:flex-start; }
  #decant header img { height:38px; } #decant h2 { margin:0; font-size:18px; } #decant header p { margin:3px 0 0; color:var(--mut); font-size:13px; }
  #decant .body { padding:16px 20px; overflow:auto; display:grid; gap:14px; }
  #decant .cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; } @media (max-width:760px) { #decant .cols { grid-template-columns:1fr; } }
  #decant .box { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
  #decant .box h3 { margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--mut); }
  #decant ul { margin:0; padding:0; list-style:none; display:grid; gap:7px; font-size:13px; }
  #decant li { display:grid; grid-template-columns:18px 1fr; gap:6px; } #decant li b { font-weight:600; } #decant li span { color:var(--mut); }
  #decant .in li::before { content:"✓"; color:var(--ok); } #decant .out li::before { content:"✕"; color:var(--bad); }
  #decant details { font-size:13px; } #decant summary { cursor:pointer; color:var(--fg); } #decant details .scroll { max-height:220px; overflow:auto; margin-top:8px; }
  #decant table { border-collapse:collapse; width:100%; font-size:12px; } #decant td, #decant th { text-align:left; padding:3px 6px; border-bottom:1px solid var(--line); vertical-align:top; }
  #decant th { color:var(--mut); font-weight:500; }
  #decant .stats { display:flex; flex-wrap:wrap; gap:8px; } #decant .stat { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:6px 10px; font-size:12px; color:var(--mut); }
  #decant .stat b { display:block; font-size:18px; color:var(--fg); font-weight:600; }
  #decant footer { padding:12px 20px; border-top:1px solid var(--line); display:flex; align-items:center; gap:10px; }
  #decant footer .note { flex:1; font-size:12px; color:var(--mut); }
  #decant .log { font:12px/1.4 ui-monospace,Consolas,monospace; background:#0b0b0d; color:#d6d6de; border:1px solid var(--line); border-radius:8px;
                 padding:8px 10px; max-height:160px; overflow:auto; white-space:pre-wrap; }
  #decant .err { color:var(--bad); } #decant .okc { color:var(--ok); }
  #decant .spin { display:inline-block; width:14px; height:14px; border:2px solid var(--line); border-top-color:var(--acc); border-radius:50%; animation:dspin .8s linear infinite; vertical-align:-2px; margin-right:8px; }
  @keyframes dspin { to { transform:rotate(360deg); } }`;
  document.head.appendChild(css);

  // ---- File menu
  const tb = $("#titlebar");
  let btn = $("#tb-file");
  if (!btn && tb) { btn = document.createElement("button"); btn.id = "tb-file"; btn.textContent = "File ▾"; tb.querySelector(".ttl")?.after(btn); }
  if (!btn) return;
  btn.title = "File";
  document.body.insertAdjacentHTML("beforeend", `<div id="filemenu" role="menu">
    <button id="fm-decant" role="menuitem"><span>Decant…<small>a standalone gBox zip for someone else's PC</small></span><kbd>Ctrl+Shift+D</kbd></button></div>
    <div id="decant" role="dialog" aria-modal="true" aria-labelledby="dc-title"><div class="dlg">
      <header><img src="../../assets/brand/gbox-logo.svg" alt=""><div><h2 id="dc-title">Decant</h2>
        <p>A zip someone without gBox unzips on their own Windows PC to get a standalone gBox: control plane, worker and local LLM on one machine,
           their own ROM folders, the toolkits, and your mods rebuilt from recipes on <i>their</i> copies of the games.</p></div></header>
      <div class="body" id="dc-body"></div>
      <footer><span class="note" id="dc-note">Assets extracted from games are for local use only: the zip holds code and recipes, never game data.</span>
        <button class="act" id="dc-cancel">Close</button><button class="act pri" id="dc-save" disabled>Save zip…</button></footer>
    </div></div>`);
  const menu = $("#filemenu");
  btn.onclick = e => { e.stopPropagation(); const b = btn.getBoundingClientRect(); menu.style.left = b.left + "px"; menu.classList.toggle("on"); btn.classList.toggle("on", menu.classList.contains("on")); };
  document.addEventListener("mousedown", e => { if (!e.target.closest("#filemenu, #tb-file")) { menu.classList.remove("on"); btn.classList.remove("on"); } });
  $("#fm-decant").onclick = () => { menu.classList.remove("on"); btn.classList.remove("on"); open(); };
  gbox.onMenu?.(item => { if (item === "decant") open(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#decant").classList.contains("on") && !busy) close(); });

  // ---- Decant dialog
  let busy = false, plan = null;
  const body = $("#dc-body"), save = $("#dc-save");
  const logBox = () => body.querySelector(".log") || (body.insertAdjacentHTML("beforeend", `<div class="log" id="dc-log"></div>`), body.querySelector(".log"));
  gbox.onDecant?.(line => { if (!busy) return; const l = logBox(); l.textContent += line + "\n"; l.scrollTop = l.scrollHeight; });
  function close() { $("#decant").classList.remove("on"); if (busy) gbox.decantCancel(); busy = false; }
  $("#dc-cancel").onclick = close;
  $("#decant").addEventListener("mousedown", e => { if (e.target.id === "decant" && !busy) close(); });

  async function open() {
    $("#decant").classList.add("on");
    save.disabled = true; save.textContent = "Save zip…"; save.onclick = doSave;
    body.innerHTML = `<div><span class="spin"></span>Reading the collection: mod cards, characters, built mods, the games they need, the code tree…</div>`;
    busy = true;
    plan = await gbox.decantPlan();
    busy = false;
    render(plan);
  }

  function render(m) {
    if (!m || m.error && !m.included) { body.innerHTML = `<div class="err">${esc(m?.error || "decant failed")}</div>`; return; }
    const r = m.recipes || {}, byGame = {};
    for (const c of r.cards || []) (byGame[c.game_title || c.game_id] ||= []).push(c.title);
    body.innerHTML = `
      <div class="stats">
        <div class="stat"><b>${m.files_included}</b>files of code (${(m.bytes_included / 1e6).toFixed(1)} MB)</div>
        <div class="stat"><b>${(r.cards || []).length}</b>mod cards</div>
        <div class="stat"><b>${(r.characters || []).length}</b>character recipes</div>
        <div class="stat"><b>${(r.built_mods || []).length}</b>built-mod recipes</div>
        <div class="stat"><b>${(r.bone_maps || []).length}</b>bone maps</div>
        <div class="stat"><b>${m.scrub?.replacements ?? 0}</b>scrubbed paths / hosts / IPs</div>
      </div>
      ${m.error ? `<div class="box err">${esc(m.error)}</div>` : ""}
      <div class="cols">
        <div class="box"><h3>In the zip</h3><ul class="in">${m.included.map(i => `<li><div><b>${esc(i.what)}</b><br><span>${esc(i.detail)}</span></div></li>`).join("")}</ul></div>
        <div class="box"><h3>Left out, and why</h3><ul class="out">${m.left_out.map(i => `<li><div><b>${esc(i.what)}</b><br><span>${esc(i.why)}</span></div></li>`).join("")}</ul></div>
      </div>
      <div class="box"><h3>Recipes</h3>
        <details><summary>${(r.cards || []).length} mod cards for ${Object.keys(byGame).length} games</summary><div class="scroll"><table>
          <tr><th>Game</th><th>Mods</th></tr>${Object.entries(byGame).map(([g, t]) => `<tr><td>${esc(g)}</td><td>${t.map(esc).join(" · ")}</td></tr>`).join("")}</table></div></details>
        <details><summary>${(r.characters || []).length} characters (re-extracted from the recipient's own copy of the source game)</summary><div class="scroll"><table>
          <tr><th>Character</th><th>From</th><th>Swaps into</th></tr>${(r.characters || []).map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.source)}</td><td>${esc((c.targets || []).join(", ") || "–")}</td></tr>`).join("")}</table></div></details>
        <details><summary>${(r.built_mods || []).length} built disc/ROM mods (rebuilt, never shipped)</summary><div class="scroll"><table>
          <tr><th>Mod</th><th>Game</th><th>Rebuilt by</th></tr>${(r.built_mods || []).map(b => `<tr><td>${esc(b.name)}</td><td>${esc(b.game)}</td><td>${esc(b.rebuild)}</td></tr>`).join("")}</table></div></details>
      </div>
      <div class="box"><h3>Privacy check</h3>
        <div class="${m.scrub?.verified ? "okc" : "err"}">${m.scrub?.verified ? "✓" : "✕"} ${m.scrub?.replacements ?? 0} replacements of your paths, host names and IPs in ${(m.scrub?.files || []).length} files; ${m.scrub?.verified ? "none remain" : "some remain (see above)"}. The API token is never written.</div>
        <details><summary>Files in your tree that are not packaged (${(m.excluded_files || []).length})</summary><div class="scroll"><table>
          ${(m.excluded_files || []).map(e => `<tr><td><code>${esc(e.path)}</code></td><td>${esc(e.why)}</td></tr>`).join("")}</table></div></details>
        <details><summary>Scrubbed files</summary><div class="scroll"><table>
          ${(m.scrub?.files || []).map(f => `<tr><td><code>${esc(f.file)}</code></td><td>${f.replacements}</td></tr>`).join("")}</table></div></details>
      </div>`;
    save.disabled = !!m.error;
  }

  async function doSave() {
    save.disabled = true; busy = true;
    const l = logBox(); l.textContent = "Packing…\n";
    const r = await gbox.decantSave();
    busy = false;
    if (!r) { save.disabled = false; l.textContent += "Cancelled.\n"; return; }
    if (r.error && !r.zip) { save.disabled = false; l.insertAdjacentHTML("beforeend", `<span class="err">${esc(r.error)}</span>\n`); return; }
    render(r);
    body.insertAdjacentHTML("afterbegin", `<div class="box okc">✓ Saved <b>${esc(r.zip)}</b> (${(r.zip_bytes / 1e6).toFixed(1)} MB). The manifest is inside (MANIFEST.md).
      Send it to whoever should have it; they unzip it and run <b>Install gBox.cmd</b>.</div>`);
    save.disabled = false; save.textContent = "Show in folder"; save.onclick = () => gbox.decantShow(r.zip);
  }
})();
