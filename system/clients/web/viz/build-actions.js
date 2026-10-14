// Build actions shared by the Mods cards, the Builds rows and the game menu's Special builds (#1656):
//   * "What this changes": the server's summary of a build (gbox/build_summary.py: recorded facts, else the files
//     compared with the game's base copy, else inferred from the name and the writer's docs), the "No changes from the
//     original game found" / "Changes not recorded" badges and "Where to look in game".
//   * 🗑 Delete: a confirm dialog (name, size, where it lives; delete everywhere = the Spark collection + every PC's
//     copy, or only this PC) -> POST /api/builds/{game}/{name}/delete {scope, node} (= DELETE ...?scope=&node=).
//     onlyHere (the download icon's "Delete from this PC", viz/build-local.js, #1639): only this PC's copy is offered.
//   * ⚑ Report: quick reasons + free text -> POST /api/builds/{game}/{name}/report {reason, note}; the server files it
//     through the issue flow with the build's facts and pictures and routes it to the investigation queue.
// Plain functions + open(kind, build, env) that renders a modal into env.document (node tests use a fake one).
(function (root) {
  "use strict";
  const ESC = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const REASONS = [["no_change", "Doesn't show the expected change"], ["broken", "Character looks broken or garbled"],
                   ["detail_loss", "Character lost too much detail"], ["crash", "Game crashes or freezes"], ["other", "Other"]];
  const fmtSize = n => n == null ? "size not known yet" : !n ? "0 B" : n >= 2 ** 30 ? (n / 2 ** 30).toFixed(2) + " GB"
    : n >= 2 ** 20 ? (n / 2 ** 20).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B";
  const nameOf = b => b.mod_title || b.label || b.name;
  const path = b => `/api/builds/${encodeURIComponent(b.game_id)}/${encodeURIComponent(b.name)}`;
  // Workbench cards identify a collection build; a session may run a pinned
  // local copy of it. Keep both identities and never link another mod's session.
  function sessionBuild(card, gameId, session) {
    const launch = (card.calls || []).find(c => c.tool === "@launch")?.input;
    if (!launch?.mod) return null;
    const gid = launch.game_id || card.game_id || gameId, name = launch.mod;
    const actual = session?.mod || session?.detail?.mod || "";
    const linked = session?.game_id === gid && (actual === name || actual.split("~")[0] === name || session?.detail?.collection_mod === name);
    return { game_id: gid, name, label: card.title || name,
      game_title: session?.game_id === gid ? session.title || session.game_title || gid : gid,
      ...(linked ? { session_id: session.session_id, runtime_mod: actual, node: session.detail?.worker_name || "" } : {}) };
  }

  // ---------------------------------------------------------------- What this changes
  function whatHTML(w, { compact = false, cls = "ba-what" } = {}) {
    if (!w) return "";
    const lines = (w.lines || []).slice(0, compact ? 1 : 3);
    const badge = w.badge ? `<span class="ba-badge ba-${w.status === "no_changes" ? "none" : "unknown"}">${ESC(w.badge)}</span>` : "";
    const tag = w.inferred ? ' <span class="ba-tag" title="Nothing was recorded for this build: read from its name and its writer\'s docs">inferred</span>' : "";
    const where = w.where ? `<div class="ba-where"><b>Where to look in game:</b> ${ESC(w.where)}${w.where_inferred ? ' <span class="ba-tag">inferred</span>' : ""}</div>` : "";
    if (compact) return `<div class="${cls} ba-compact" title="${ESC([...(w.lines || []), w.where ? "Where to look: " + w.where : ""].filter(Boolean).join("\n"))}">`
      + `${badge}${lines.map(l => `<span class="ba-line">${ESC(l)}</span>`).join("")}${tag}</div>`;
    return `<div class="${cls} ba-${ESC(w.status || "unknown")}"><div class="ba-h">What this changes${tag}</div>${badge}`
      + (lines.length ? `<ul class="ba-lines">${lines.map(l => `<li>${ESC(l)}</li>`).join("")}</ul>` : "") + where + "</div>";
  }
  const reportedHTML = (r, cls = "ba-rep") => r && r.number ? `<span class="${cls}" title="A report was filed on this build: request #${ESC(r.number)}">Reported #${ESC(r.number)}</span>` : "";

  // ---------------------------------------------------------------- the dialogs
  function attachedCopies(b) {
    return [...new Map((b.where || []).filter(w => w.where === "pc" && w.node).map(w => [w.node, w])).values()];
  }
  function whereList(b) { return (b.where || []).map(w => w.label).filter(Boolean); }
  function deleteDialogHTML(b, { here = "", onlyHere = false } = {}) {
    const where = whereList(b), onHere = here && (b.where || []).some(w => w.node === here), pcs = attachedCopies(b);
    return `<div class="ba-box" role="dialog" aria-modal="true" aria-label="Delete build"><h3>🗑 Delete “${ESC(nameOf(b))}”${onlyHere ? " from this PC" : ""}?</h3>
      <table class="ba-facts"><tr><th>Name</th><td>${ESC(nameOf(b))}</td></tr><tr><th>Folder</th><td><code>${ESC(b.name)}</code></td></tr>
        <tr><th>Game</th><td>${ESC(b.game_title || b.title || b.game_id)}</td></tr><tr><th>Size</th><td>${ESC(fmtSize(b.own_size || b.size))}${b.own_size && b.size > b.own_size ? ` (${ESC(fmtSize(b.size))} with files shared with the base game)` : ""}</td></tr>
        <tr><th>Lives on</th><td>${where.length ? where.map(ESC).join("<br>") : "the Spark collection"}</td></tr></table>
      ${onlyHere ? "" : `<label class="ba-opt"><input type="radio" name="ba-scope" value="all" checked> Delete everywhere (Spark collection + every PC's copy)</label>`}
      <label class="ba-opt${onHere ? "" : " ba-dis"}"><input type="radio" name="ba-scope" value="node"${onHere ? (onlyHere ? " checked" : "") : " disabled"}> Only this PC${here ? ` (${ESC(here)})` : ""}${onHere ? "" : " (no copy here)"}</label>
      ${onlyHere ? "" : `<label class="ba-opt${pcs.length ? "" : " ba-dis"}"><input type="radio" name="ba-scope" value="pcs"${pcs.length ? "" : " disabled"}> Attached computers (keep Spark collection)</label>
      <fieldset class="ba-pcs" data-ba-pcs disabled><legend>Choose copies to delete</legend>${pcs.length ? pcs.map(w => `<label class="ba-opt"><input type="checkbox" data-ba-pc value="${ESC(w.node)}"> ${ESC(w.node)}${w.online === false ? " (offline; cannot delete now)" : ""}</label>`).join("") : '<span class="ba-note">No attached computer reports a copy.</span>'}</fieldset>`}
      ${onlyHere ? `<p class="ba-note">Only this PC's copy is removed: the Spark collection and other PCs keep theirs, and ⬇ downloads it again.</p>` : ""}
      <p class="ba-note">The base game and other builds are never touched. A build a running game uses can't be deleted: stop the game first. Deleting can't be undone (the marker is kept in the recently deleted list).</p>
      <div class="ba-btns"><button class="act" type="button" data-ba="review">Report issues before deleting…</button><button class="act ba-danger" type="button" data-ba="go">🗑 Delete</button><button class="act" type="button" data-ba="cancel">Cancel</button><span class="ba-status" data-ba-status></span></div></div>`;
  }
  function reportDialogHTML(b, env = {}) {
    const w = b.what;
    return `<div class="ba-box" role="dialog" aria-modal="true" aria-label="Report a build"><h3>⚑ Report a problem with “${ESC(nameOf(b))}”</h3>
      <p class="ba-note">${ESC(b.game_title || b.title || b.game_id)} · <code>${ESC(b.name)}</code>${b.writer ? ` · ${ESC(b.writer)}` : ""}</p>
      ${whatHTML(w, { compact: true })}
      ${b.session_id ? `<p class="ba-note">Linked to the game session${b.node ? ` on ${ESC(b.node)}` : ""}. Build being played: <code>${ESC(b.runtime_mod || b.name)}</code>.</p>` : ""}
      <div class="ba-reasons">${REASONS.map(([k, l], i) => `<label class="ba-opt"><input type="radio" name="ba-reason" value="${k}"${i === 0 ? " checked" : ""}> ${ESC(l)}</label>`).join("")}</div>
      <label class="ba-opt" for="ba-report-note">Note for the ticket</label>
      <textarea id="ba-report-note" class="ba-text" data-ba-note rows="4" maxlength="4000" placeholder="Describe what needs attention. For example: Decimation removed too much detail from Leon. Please re-evaluate the model and preserve his facial and clothing detail." data-nomic></textarea>
      <label class="ba-opt">Screenshots and reference images (up to 4)<input data-ba-files type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
      <p class="ba-note">Choose, paste or drop images. Label desired-appearance images as references. Your notes and pictures remain after the ROM files are removed.</p>
      <button class="act" type="button" data-ba="capture">Capture running build</button><div class="ba-images" data-ba-images></div>
      ${env.reviewCleanup ? `<p class="ba-note ba-retire">After the report is saved, remove ${ESC(env.reviewCleanup.scope === "all" ? "all copies" : env.reviewCleanup.scope === "node" ? env.reviewCleanup.node : (env.reviewCleanup.nodes || []).join(", "))}. Copies in use wait until you stop playing. Exact build evidence is preserved for analysis; ROM archives are purged after findings and resolution are recorded. ${env.reviewCleanup.scope === "all" ? "" : "Spark collection stays."}</p>` : ""}
      <p class="ba-note">Sent with the build's game, writer, slots and donors, what it changes, its recipe, its last launch, its newest in-game frame and its fit previews. It goes to the investigation queue.</p>
      <div class="ba-btns"><button class="act pri" type="button" data-ba="go">${env.reviewCleanup ? "Submit report and remove copies" : "Submit ticket"}</button><button class="act" type="button" data-ba="cancel">Cancel</button><span class="ba-status" data-ba-status></span></div></div>`;
  }
  const deleteCall = (b, scope, here, nodes = []) => ({ path: path(b) + "/delete",
    body: scope === "pcs" ? { scope, nodes: [...new Set(nodes)] } : { scope, node: scope === "node" ? here : "" } });
  function brokenDialogHTML(b, env = {}) {
    return `<div class="ba-box" role="dialog" aria-modal="true" aria-label="Mark build broken"><h3>Mark ${ESC(nameOf(b))} broken</h3>
      <p>Queue this build for investigation and remove its copy from ${ESC(env.here || "this PC")} after a verified copy is preserved on Spark.</p>
      <p>After the findings and resolution are recorded and the ticket is completed, the broken files are deleted from Spark too. The ticket and repair history remain.</p>
      <label for="ba-broken-note">What is broken?</label><textarea id="ba-broken-note" class="ba-text" data-ba-note rows="4" maxlength="4000" placeholder="For example: The character is completely distorted, although the game no longer crashes." data-nomic></textarea>
      <div class="ba-btns"><button class="act ba-danger" type="button" data-ba="go">Mark broken &amp; remove local copy</button><button class="act" type="button" data-ba="cancel">Cancel</button><span class="ba-status" data-ba-status></span></div></div>`;
  }
  const reportCall = (b, reason, note) => ({ path: path(b) + "/report", body: { reason, note: String(note || "").trim(),
    ...(b.session_id ? { session_id: b.session_id } : {}) } });
  function deleteResultText(b, r) {
    if (r.scope === "review") return `Report #${r.number} saved; copy removal queued after evidence preservation. Running games are left in place.`;
    if (r.scope === "review_report_only") return `Report #${r.number} saved; cleanup was not queued and copies are kept.`;
    const n = nameOf(b), jobs = (r.jobs || []).map(j => j.node), skipped = (r.skipped || []).map(s => `${s.node}: ${s.reason}`);
    return `${r.scope === "pcs" ? `Requested deletion of ${n} from ${(r.nodes || []).join(", ")} (Spark collection kept)` : `Deleted ${n}${r.scope === "node" ? ` from ${r.node}` : ""}`}` + ((r.spark?.removed || []).length ? " (Spark collection removed)" : "")
      + (jobs.length ? `; deleting the copy on ${jobs.join(", ")}` : "") + (skipped.length ? `; not deleted: ${skipped.join("; ")}` : "");
  }

  const CSS = `.ba-modal{position:fixed;inset:0;z-index:2147483000;background:#0009;display:flex;align-items:center;justify-content:center}
    .ba-box{background:var(--bg,#16161a);color:var(--fg,#e8e8ee);border:1px solid var(--line,#444);border-radius:10px;box-shadow:0 16px 48px #000c;padding:16px 18px;width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;font-size:13px}
    .ba-box h3{margin:0 0 10px;font-size:15px;overflow-wrap:anywhere}.ba-facts{border-collapse:collapse;margin:0 0 10px;width:100%}.ba-facts th{text-align:left;color:#9aa;font-weight:500;padding:2px 10px 2px 0;vertical-align:top;white-space:nowrap}.ba-facts td{padding:2px 0;overflow-wrap:anywhere}
    .ba-opt{display:flex;gap:6px;align-items:center;margin:4px 0}.ba-dis{opacity:.55}.ba-note{color:#9aa;font-size:12px;margin:8px 0}.ba-text{width:100%;box-sizing:border-box;font:inherit;margin-top:6px}
    .ba-pcs{margin:6px 0 8px 20px;border:1px solid #444;border-radius:6px;padding:6px 10px}.ba-pcs:disabled{opacity:.5}.ba-pcs legend{font-size:12px;color:#9aa}
    .ba-images{display:flex;gap:8px;flex-wrap:wrap}.ba-images figure{margin:8px 0;max-width:150px}.ba-images img{max-width:145px;max-height:100px}.ba-images select{max-width:145px}.ba-retire{border-left:2px solid #cc9b56;padding-left:8px}
    .ba-btns{display:flex;gap:8px;align-items:center;margin-top:10px}.ba-danger{background:#7a2b2b;color:#fff;border-color:#7a2b2b}.ba-status{font-size:12px;color:#9aa}`;
  const WHAT_CSS = `.ba-what{border-left:3px solid var(--acc,#7c96ff);background:#ffffff08;padding:4px 8px;border-radius:0 6px 6px 0;font-size:12.5px}
    .ba-what .ba-h{font-weight:600;font-size:12px;margin-bottom:2px}.ba-lines{margin:2px 0;padding-left:16px}.ba-where{font-size:12px;margin-top:2px}
    .ba-what.ba-no_changes{border-left-color:#c0503a}.ba-what.ba-unknown{border-left-color:#777}.ba-what.ba-inferred{border-left-color:#c9a43a}
    .ba-badge{display:inline-block;font-size:11.5px;font-weight:600;border-radius:6px;padding:1px 7px;margin:2px 0}.ba-none{background:#7a2b2b;color:#fff}.ba-unknown{background:#444;color:#ddd}
    .ba-tag{font-size:10.5px;border:1px solid #c9a43a;color:#e3c46a;border-radius:8px;padding:0 5px;font-weight:500}
    .ba-compact{border-left-width:2px;padding:2px 6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}.ba-compact .ba-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1}
    .ba-rep{font-size:11px;padding:1px 6px;border-radius:9px;background:#5a3f8a;color:#fff;white-space:nowrap}`;

  // open("delete" | "report", build, env = {document, api(path, body, method), here, toast?}) -> the server's answer
  // (delete: {..., scope}; report: {number, id, title}) or null when cancelled
  function open(kind, b, env = {}) {
    const doc = env.document || root.document;
    const wrap = doc.createElement("div");
    wrap.className = "ba-modal";
    wrap.innerHTML = `<style>${CSS}${WHAT_CSS}</style>` + (kind === "broken" ? brokenDialogHTML(b, env) : kind === "delete" ? deleteDialogHTML(b, env) : reportDialogHTML(b, env));
    doc.body.appendChild(wrap);
    if (kind === "delete" && !env.onlyHere) wrap.addEventListener("change", () => {
      const pcs = wrap.querySelector('[data-ba-pcs]');
      if (pcs) pcs.disabled = wrap.querySelector('input[name="ba-scope"]:checked')?.value !== "pcs";
    });
    if (kind !== "delete") wrap.querySelector("[data-ba-note]")?.focus?.();
    const status = text => { const s = wrap.querySelector("[data-ba-status]"); if (s) s.textContent = text; };
    return new Promise(resolve => {
      let busy = false, reading = false, closed = false, savedReport = null, images = [];
      const showImages = () => {
        const box = wrap.querySelector('[data-ba-images]');
        if (box) box.innerHTML = images.map((image,i) => `<figure><img alt="Attached image ${i+1}" src="data:image/png;base64,${image.b64}"><figcaption>${ESC(image.name)}</figcaption><select data-ba-role="${i}" aria-label="Image ${i+1} purpose"><option value="screenshot"${image.role === "screenshot" ? " selected" : ""}>Issue screenshot</option><option value="reference"${image.role === "reference" ? " selected" : ""}>Desired appearance</option></select><button type="button" data-ba="remove-image" data-image="${i}">Remove</button></figure>`).join('');
      };
      const readFiles = async files => {
        if (busy || reading || savedReport) return;
        reading = true;
        const go = wrap.querySelector('[data-ba="go"]'); if (go) go.disabled = true;
        try {
          for (const file of files) {
            if (images.length >= 4) throw Error('Attach up to four images.');
            if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 4*1024*1024) throw Error('Use PNG, JPEG or WebP images up to 4 MB.');
            const url = root.URL.createObjectURL(file), image = new root.Image();
            try {
              image.src = url; await image.decode();
              const canvas = doc.createElement('canvas'), ratio = Math.min(1,1600/Math.max(image.width,image.height));
              canvas.width = Math.max(1,Math.round(image.width*ratio)); canvas.height = Math.max(1,Math.round(image.height*ratio));
              canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
              const b64 = canvas.toDataURL('image/png').split(',')[1];
              if (b64.length > Math.ceil(4*1024*1024/3)*4) throw Error('Converted image is too large; use a smaller picture.');
              images.push({name:file.name || 'screenshot.png',role:'screenshot',b64});
            } finally { root.URL.revokeObjectURL(url); }
          }
          showImages(); status('Images attached.');
        } catch (err) { showImages(); status(err.message); }
        finally { reading = false; if (go) go.disabled = false; }
      };
      wrap.querySelector('[data-ba-files]')?.addEventListener?.('change', e => readFiles([...e.target.files]));
      wrap.addEventListener('paste', e => { if (e.clipboardData?.files?.length) { e.preventDefault(); readFiles([...e.clipboardData.files]); } });
      wrap.addEventListener('dragover', e => e.preventDefault());
      wrap.addEventListener('drop', e => { e.preventDefault(); readFiles([...(e.dataTransfer?.files || [])]); });
      wrap.addEventListener('change', e => { if (e.target?.dataset?.baRole !== undefined && !savedReport) images[+e.target.dataset.baRole].role=e.target.value; });
      const done = v => { closed = true; try { wrap.remove(); } catch {} resolve(v); };
      wrap.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation?.(); if (!busy) done(savedReport ? {...savedReport,scope:"review_report_only"} : null); } });
      wrap.addEventListener("click", async e => {
        const a = e.target?.closest?.("[data-ba]")?.dataset?.ba;
        if ((a === "cancel" || e.target === wrap) && !busy && !reading) return done(savedReport ? {...savedReport,scope:"review_report_only"} : null);
        if (a === "remove-image" && !busy && !reading && !savedReport) { images.splice(+e.target.dataset.image,1); showImages(); return; }
        if (a === "review" && !busy) {
          const scope = env.onlyHere ? "node" : wrap.querySelector('input[name="ba-scope"]:checked')?.value || "all";
          const nodes = scope === "pcs" ? [...wrap.querySelectorAll('[data-ba-pc]:checked')].map(el => el.value) : [];
          if (scope === "pcs" && !nodes.length) { status('Choose at least one attached computer.'); return; }
          busy=true; wrap.remove();
          return done(await open("report",b,{...env,reviewCleanup:deleteCall(b,scope,env.here || "",nodes).body}));
        }
        if (a === "capture" && !busy && !reading && !savedReport) {
          busy=true;
          const escapeCapture = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(null); } };
          doc.addEventListener?.('keydown',escapeCapture,true);
          try {
            if (images.length >= 4) throw Error('Remove an image before capturing another.');
            const sessions = await env.api('/api/sessions?include_ended=false');
            const matches = sessions.filter(s => s.state === 'running' && s.game_id === b.game_id &&
              ((s.mod || s.detail?.mod || '').split('~')[0] === b.name || s.detail?.collection_mod === b.name) &&
              (!env.here || s.detail?.worker_name === env.here));
            if (matches.length !== 1) throw Error('Open this build on this PC, or upload a screenshot from your test.');
            wrap.style.setProperty('visibility','hidden','important');
            await new Promise(yes => root.requestAnimationFrame(() => root.requestAnimationFrame(yes)));
            const frame = await env.api(`/api/sessions/${encodeURIComponent(matches[0].session_id)}/report-frame`,{},'POST');
            if (closed) return;
            images.push({name:'captured-game.png',role:'screenshot',b64:frame.image_b64}); showImages(); status('Game screenshot attached.');
          } catch (err) { status(err.message); }
          finally { doc.removeEventListener?.('keydown',escapeCapture,true); if (!closed) wrap.style.removeProperty('visibility'); busy=false; }
          return;
        }
        if (a !== "go" || busy || reading) return;
        const btn = wrap.querySelector('[data-ba="go"]');
        busy = true; if (btn) btn.disabled = true;
        try {
          let r;
          if (kind === "broken") {
            if (!env.here) throw new Error("Choose this PC before marking a build broken");
            status("Preserving evidence and queuing investigation...");
            r = await env.api(path(b) + "/broken", { node: env.here, note: String(wrap.querySelector("[data-ba-note]")?.value || "").trim() }, "POST");
          } else if (kind === "delete") {
            const scope = env.onlyHere ? "node" : wrap.querySelector('input[name="ba-scope"]:checked')?.value || "all";
            status("Deleting…");
            const nodes = scope === "pcs" ? [...wrap.querySelectorAll('[data-ba-pc]:checked')].map(el => el.value) : [];
            if (scope === "pcs" && !nodes.length) throw new Error("Choose at least one attached computer.");
            const c = deleteCall(b, scope, env.here || "", nodes);
            r = { ...(await env.api(c.path, c.body, "POST")), scope };
          } else {
            const reason = wrap.querySelector('input[name="ba-reason"]:checked')?.value || "other";
            const c = reportCall(b, reason, wrap.querySelector("[data-ba-note]")?.value);
            status("Filing the report…");
            if (env.reviewCleanup && !c.body.note) throw Error('Describe what is wrong before removing the build.');
            if (images.length) c.body.images = images;
            r = savedReport || await env.api(c.path, c.body, "POST");
            if (env.reviewCleanup) {
              savedReport=r;
              for (const el of wrap.querySelectorAll('[data-ba-note],[data-ba-files],[data-ba-role],[data-ba="capture"],[data-ba="remove-image"]')) el.disabled=true;
              status(`Report #${r.number} saved. Queueing evidence preservation and removal…`);
              const cleanup=await env.api(path(b)+"/review-cleanup",{...env.reviewCleanup,report_id:r.id},"POST");
              r={...cleanup,id:r.id,number:r.number,scope:"review"};
            }
          }
          done(r);
        } catch (err) {
          busy = false; if (btn) btn.disabled = false;
          status((savedReport ? `Report #${savedReport.number} is saved. Retry to queue cleanup: ` : "⚠ ") + String(err?.message || err).slice(0, 300));
        }
      });
    });
  }

  const api = { whatHTML, reportedHTML, deleteDialogHTML, reportDialogHTML, deleteCall, reportCall, deleteResultText, open, fmtSize,
                sessionBuild, brokenDialogHTML, REASONS, CSS, WHAT_CSS };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GBoxBuildActions = api;
})(typeof window !== "undefined" ? window : globalThis);
