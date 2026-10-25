// Per-title Home workspace. Only recorded events and real collection assets are shown.
(function (root) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
  const list = value => Array.isArray(value) ? value : [];
  const count = value => Math.max(0, Number(value) || 0).toLocaleString();
  const timestamp = value => {
    if (value == null || value === '') return 0;
    const n = Number(value);
    return Number.isFinite(n) ? (n < 1e12 ? n * 1000 : n) : Date.parse(value) || 0;
  };
  const date = value => timestamp(value) ? new Date(timestamp(value)).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Not recorded';
  const safeURL = value => {
    const s = String(value || '').trim();
    if (/[\\\u0000-\u001f\u007f]/.test(s)) return '';
    return /^\/(?!\/)/.test(s) || /^https?:\/\//i.test(s) || /^data:image\/(png|jpe?g|webp|svg\+xml);base64,/i.test(s) ? s : '';
  };
  const urlFor = (value, io) => {
    const safe = safeURL(value);
    return safe ? safeURL((io.url || (u => u))(safe)) : '';
  };
  const label = value => String(value || '').replace(/_/g, ' ');
  function playability(game = {}) {
    if (root.GBoxHome?.playability) return root.GBoxHome.playability(game);
    const status = game.launch?.status || game.playable;
    const pending = game.format === 'ps4_pkg' || game.launch?.kind === 'ps4_package' || ['copy_incomplete', 'installation_required'].includes(status);
    return { allowed: game.playable !== false && !pending, label: pending ? (status === 'copy_incomplete' ? 'Copy incomplete' : 'Needs extracted game') : '' };
  }
  function selectedBuild(data) {
    const raw = data.selected_build, row = typeof raw === 'string' ? { name: raw } : raw;
    const name = row?.mod_name || row?.name;
    if (!name || row.game_id && row.game_id !== data.game?.game_id) return null;
    const recorded = list(data.builds).find(build => build.name === name);
    return { ...row, ...recorded, name, title: recorded?.title || row.title || name };
  }
  function modelOptions(data) {
    return list(data.models).filter(m => m && safeURL(m.model_url) && /^(glb|gltf)$/i.test(String(m.format || '').replace(/^\./, '')));
  }
  function events(data) {
    return list(data.timeline).filter(e => e && timestamp(e.ts)).slice().sort((a, b) => timestamp(b.ts) - timestamp(a.ts));
  }
  function timelineSVG(data) {
    const rows = events(data);
    if (!rows.length) return '';
    const width = 560, height = 92, start = timestamp(rows.at(-1).ts), end = timestamp(rows[0].ts), span = Math.max(end - start, 1);
    const buckets = new Array(Math.min(12, Math.max(1, rows.length))).fill(0);
    rows.forEach(e => buckets[Math.min(buckets.length - 1, Math.floor((timestamp(e.ts) - start) / span * buckets.length))]++);
    const max = Math.max(...buckets), gap = 6, bar = (width - gap * (buckets.length - 1)) / buckets.length;
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(rows.length)} recorded game and mod events over time">${buckets.map((n, i) => `<rect x="${i * (bar + gap)}" y="${height - n / max * 78}" width="${bar}" height="${n / max * 78}" rx="3"><title>${n} recorded event${n === 1 ? '' : 's'}</title></rect>`).join('')}</svg><div class="ghd-chart-dates"><span>${esc(date(start))}</span><span>${esc(date(end))}</span></div>`;
  }
  const originalImage = item => safeURL(item?.original_url) || safeURL(item?.source_url) || safeURL(item?.url);
  function image(src, alt, io, className = '', asset = {}) {
    const u = urlFor(src, io);
    const original = originalImage(asset) || safeURL(src);
    const association = asset.game_id ? ` data-asset-game="${esc(asset.game_id)}" data-asset-url="${esc(safeURL(src))}" data-asset-original-url="${esc(original)}" data-asset-format="image" data-asset-name="${esc(alt)}"` : '';
    return u ? `<img class="${className}" src="${esc(u)}" alt="${esc(alt)}" loading="lazy" decoding="async"${association}>` : '';
  }
  function buildImage(build, game, io) {
    const item = safeURL(build.images?.[0]?.url) ? build.images[0] : build.shots?.[0] || {};
    return image(item.url, build.title || build.name, io, 'ghd-build-image', {...item, game_id:game.game_id});
  }
  const assetCategories = ['characters', 'props', 'textures', 'animations'];
  const activeAssetTask = task => ['queued', 'running'].includes(task?.state);
  const failedAssetTask = task => ['failed', 'invalid', 'rejected', 'cancelled', 'missing'].includes(task?.state);
  function assetsHTML(state, game, io = {}, pending = false, error = '') {
    const tasks = list(state?.tasks), active = tasks.filter(activeAssetTask), failed = tasks.filter(failedAssetTask);
    const source = state?.inventory?.source, archive = /^[a-f0-9]{64}$/.test(source?.archive_sha256 || '') ? source.archive_sha256 : '';
    const coverage = state?.raw_coverage, categories = state?.categories || {};
    const exports = archive ? list(state?.exports).filter(row => row.game_id === game.game_id && row.source?.archive_sha256 === archive && /^[a-f0-9]{64}$/.test(row.bundle_sha256 || '')) : [];
    const native = assetCategories.some(category => categories[category]?.raw_state), available = native || categories.characters?.extractor;
    const complete = native && coverage?.complete;
    const action = active.length ? 'Extraction in progress' : complete ? 'Raw exports complete' : !available && state ? 'Reader unavailable' : failed.length ? 'Retry failed extraction' : state?.inventory ? 'Continue extraction' : 'Collect available assets';
    const writer = typeof state?.writer === 'string' ? state.writer : state?.writer?.name || state?.writer?.writer || '';
    const hint = pending ? 'Loading exact-title asset status…' : active.length ? 'This work waits for the worker’s normal idle and resource checks. No game is launched.' : complete ? 'Raw archive scope is exported. Decoding, replacement and playable builds remain unverified.' : 'Collect starts one bounded extraction step. Continue after it finishes; no work starts automatically.';
    return `<div class="ghd-section-heading"><h3>Original title assets</h3><div class="ghd-actions"><button type="button" data-ghd-action="models">Models &amp; asset browser</button><button type="button" data-ghd-action="asset-status"${pending ? ' disabled' : ''}>Refresh status</button>${native ? `<button type="button" data-ghd-action="asset-inventory"${pending || active.length ? ' disabled' : ''} title="Start a new source inventory after owned files change">Refresh native inventory</button>` : ''}<button type="button" data-ghd-action="asset-collect"${pending || active.length || !state || !available || complete ? ' disabled' : ''}>${pending ? 'Checking assets…' : esc(action)}</button></div></div>
      <div class="ghd-asset-categories">${assetCategories.map(category => {
        const row = categories[category] || {}, collection = row.collection || {};
        return `<div><b>${esc(label(category))}</b><span>${esc(state ? label(row.state || 'pending reader') : 'Status not loaded')}</span>${row.extractor ? `<small>Reader: ${esc(row.extractor)} · registered subset (${count(row.registered)})</small>` : ''}${collection.state && collection.state !== 'not_started' ? `<small>Collection: ${esc(label(collection.state))}</small>` : ''}${row.raw_state ? `<small>Native raw files: ${esc(label(row.raw_state))}</small>` : ''}</div>`;
      }).join('')}</div>
      <p class="ghd-asset-limit">Decoded models and sprites open in the asset browser. Raw native files need decoding and a compatible writer before they can replace game assets. ${!state ? 'Reader and writer status has not loaded.' : writer ? `Registered writer: ${esc(writer)}; each build still needs validation.` : 'No native replacement writer is registered for this title.'}</p>
      ${archive ? `<div class="ghd-asset-source"><b>Native archive raw coverage</b><span>${count(coverage?.exported)} / ${coverage?.expected == null ? '?' : count(coverage.expected)} non-placeholder members exported${coverage?.complete ? ' · raw archive scope covered' : ' · pending'}</span><small>${esc(coverage?.scope || 'Native archive members')}; this is not full-disc or decoded-model coverage.</small><details><summary>Source revision</summary><span>Archive SHA-256 <code>${esc(archive)}</code></span>${source?.xbe_sha256 ? `<span>Executable SHA-256 <code>${esc(source.xbe_sha256)}</code></span>` : ''}</details>${list(coverage?.oversized_members).length ? `<small>${count(coverage.oversized_members.length)} members exceed the portable export budget and remain pending.</small>` : ''}</div>` : `<p class="ghd-asset-limit">${state ? 'No verified native archive inventory recorded for this title.' : 'Checking exact-title inventory status.'}</p>`}
      ${active.length ? `<ul class="ghd-asset-jobs">${active.map(task => `<li><span>${esc(label(task.kind || 'extraction'))} · ${esc(label(task.state))}${task.worker_id ? ` · ${esc(task.worker_id)}` : ''}</span><progress aria-label="${esc(label(task.kind || 'Extraction'))} ${esc(task.state)}"></progress></li>`).join('')}</ul>` : ''}
      ${exports.length ? `<details class="ghd-asset-downloads"><summary>Portable raw bundles (${count(exports.length)})</summary><p>Native bytes and source manifests; these are not insertable models or playable builds.</p><ul>${exports.map((row, index) => {
        const hash = /^[a-f0-9]{64}$/.test(row.bundle_sha256 || '') ? row.bundle_sha256 : '';
        const href = hash ? urlFor('/api/artifacts/' + hash, io) : '';
        return href ? `<li><a href="${esc(href)}" download>Download raw bundle ${index + 1}</a><small>${count(list(row.members).length)} native members${row.worker_id ? ` · exported on ${esc(row.worker_id)}` : ''}</small></li>` : '';
      }).join('')}</ul></details>` : ''}
      <p class="ghd-asset-feedback" role="status" aria-live="polite">${esc(error || state?.blocked_reason || hint)}</p>
      ${failed.length ? `<ul class="ghd-asset-errors">${failed.slice(-3).map(task => `<li>${esc(label(task.kind || 'extraction'))}: ${esc(task.error || label(task.state))}</li>`).join('')}</ul>` : ''}`;
  }
  function render(data, io = {}) {
    const game = data.game || {}, models = list(data.models), builds = list(data.builds), reports = list(data.reports), activity = list(data.activity), media = list(data.media), timeline = events(data);
    const ready = playability(game);
    const models3D = modelOptions(data), jobs = list(data.progress?.active_jobs), devices = list(game.devices);
    const modelTotal = game.models_count ?? models.length, buildTotal = game.mods_count ?? builds.length, reportTotal = game.reports_count ?? reports.length;
    const selected = selectedBuild(data), buildRows = builds.map((build, index) => ({ build, index }));
    if (selected) buildRows.sort((a, b) => Number(b.build.name === selected.name) - Number(a.build.name === selected.name));
    return `<div class="ghd-root">
      <header class="ghd-heading"><div><span class="ghd-eyebrow">${selected ? 'MOD BUILD WORKSPACE' : 'GAME WORKSPACE'}</span><h2>${esc(selected?.title || game.title || 'Game details')}</h2><p>${[selected ? game.title : '', game.system || game.platform, game.year, game.manufacturer].filter(Boolean).map(esc).join(' · ')}</p>${selected ? `<p class="ghd-selected-meta">${esc(date(selected.built))} · ${selected.verified ? 'Verified' : 'Unverified'}${selected.writer ? ` · ${esc(selected.writer)}` : ''}<br><code>${esc(selected.name)}</code></p>` : ''}</div>
        <div class="ghd-actions">${selected ? '<button type="button" class="ghd-primary" data-ghd-action="play-selected">▶ Play selected build</button>' : ''}<button type="button" class="${selected ? '' : 'ghd-primary'}" data-ghd-action="play"${ready.allowed ? '' : ' disabled'}>${esc(ready.label || (selected ? 'Play original game' : 'Play'))}</button><button type="button" data-ghd-action="builds">Mod builds (${count(buildTotal)})</button><button type="button" data-ghd-action="models">Models (${count(modelTotal)})</button></div></header>
      <div class="ghd-metrics"><div><b>${count(game.plays)}</b><span>times played</span></div><div><b>${esc(game.last_played ? date(game.last_played) : 'Not played yet')}</b><span>last played</span></div><div><b>${esc(game.last_device || 'No device recorded')}</b><span>last device</span></div><div><b>${count(modelTotal)} / ${count(buildTotal)}</b><span>models / mod builds</span></div><div><b>${count(reportTotal)}</b><span>reports</span></div></div>
      <section class="ghd-panel ghd-assets-panel" data-ghd-title-assets aria-label="Original title assets">${assetsHTML(null, game, io)}</section>
      <div class="ghd-columns"><section class="ghd-panel ghd-model-panel"><div class="ghd-section-heading"><h3>Models &amp; modding progress</h3><span class="ghd-tag">3D inspection</span></div>
        ${models3D.length ? `<label class="ghd-model-select">Inspect a model<select data-ghd-model>${models3D.map((m, i) => `<option value="${i}">${esc(m.name || m.slug)}${m.source_game_id && m.source_game_id !== game.game_id ? ' · imported' : ' · extracted'}</option>`).join('')}</select></label>` : ''}
        <div class="ghd-stage" data-ghd-stage aria-label="3D model viewer"><p>${models3D.length ? 'Loading the selected collection model…' : 'No viewable 3D model has been extracted for this title yet.'}</p></div><p class="ghd-model-status" data-ghd-model-status role="status" aria-live="polite">${models3D.length ? 'Drag to orbit · scroll to zoom' : 'Extracted sprites and texture images appear in the gallery below.'}</p><div class="ghd-model-meta" data-ghd-model-meta></div>
        <div class="ghd-work-state"><b>${esc(label(data.progress?.status) || (jobs.length ? 'Work in progress' : 'No active work reported'))}</b>${jobs.length ? `<ul>${jobs.map(j => `<li><span>${esc(j.tool || 'Task')} · ${esc(label(j.state))}</span>${j.stage ? `<small>${esc(j.stage)}</small>` : ''}${Number.isFinite(j.progress) && j.progress >= 0 && j.progress <= 100 ? `<progress value="${j.progress}" max="100" aria-label="${esc(j.tool || 'Task')} progress: ${j.progress}%"></progress>` : ''}</li>`).join('')}</ul>` : '<p>No background operation is currently reporting progress for this game.</p>'}</div>
        <div class="ghd-progress-evidence">${timeline.length ? `<div class="ghd-chart">${timelineSVG(data)}<small>Recorded sessions, extractions, builds and reports. These counts describe activity, not completion percentage.</small></div>` : '<p class="ghd-empty">No dated modding activity has been recorded yet.</p>'}</div>
      </section><section class="ghd-panel"><div class="ghd-section-heading"><h3>Mod builds</h3><button type="button" data-ghd-action="builds">View all</button></div>
        <div class="ghd-builds">${builds.length ? buildRows.slice(0, 12).map(({ build: b, index: i }) => `<article class="ghd-build${selected?.name === b.name ? ' ghd-build-selected' : ''}"${selected?.name === b.name ? ' aria-current="true"' : ''}>${buildImage(b, game, io)}<div><h4>${esc(b.title || b.name)}</h4><p>${esc(date(b.built))} · <span class="ghd-tag">${b.verified ? 'Verified' : 'Unverified'}</span>${selected?.name === b.name ? ' <span class="ghd-tag">Selected build</span>' : ''}</p>${b.writer ? `<small>${esc(b.writer)}</small>` : ''}${list(b.changes).length ? `<ul class="ghd-changes">${list(b.changes).slice(0, 4).map(c => `<li>${esc(c.donor_name || c.donor || c.character || c.description || 'Modification')}${c.slot ? ` → ${esc(c.slot)}` : ''}</li>`).join('')}</ul>` : ''}<div class="ghd-actions"><button type="button" data-ghd-build="${i}">▶ Play build</button><button type="button" data-ghd-action="builds">Details &amp; downloads</button></div></div></article>`).join('') : '<p class="ghd-empty">No mod builds have been published for this title yet.</p>'}</div>
      </section></div>
      <section class="ghd-panel"><div class="ghd-section-heading"><h3>Images, screenshots &amp; models</h3><span>${count(media.length)} captured or catalogued assets</span></div><div class="ghd-gallery">${media.slice(0, 30).map((m, i) => {
        const src = urlFor(m.url, io); if (!src) return '';
        return `<figure>${m.kind === 'video' ? `<video src="${esc(src)}" controls muted playsinline preload="none" aria-label="${esc(m.label || 'Gameplay recording')}"></video>` : `<button type="button" class="ghd-image-button" data-ghd-media="${i}" aria-label="Expand ${esc(m.label || 'game image')}">${image(m.url, m.label || game.title, io, '', {...m, game_id:game.game_id})}</button>`}<figcaption>${esc(m.label || m.source || (m.kind === 'video' ? 'Gameplay recording' : 'Game image'))}</figcaption></figure>`;
      }).join('')}${models.slice(0, 16).map((m, i) => image(m.preview_url, m.name || m.slug, io) ? `<figure><button type="button" class="ghd-image-button" data-ghd-model-card="${i}" aria-label="Inspect ${esc(m.name || m.slug)}">${image(m.preview_url, m.name || m.slug, io, '', {game_id:game.game_id, original_url:m.preview_original_url || m.preview_url})}</button><figcaption>${esc(m.name || m.slug)} · model</figcaption></figure>` : '').join('') || '<p class="ghd-empty">No captured media or model thumbnails are available yet.</p>'}</div></section>
      <div class="ghd-columns"><section class="ghd-panel"><div class="ghd-section-heading"><h3>Mod history over time</h3><span>${count(timeline.length)} recorded events</span></div><ol class="ghd-timeline">${timeline.slice(0, 40).map((e, i) => `<li><span class="ghd-event-dot" data-kind="${esc(e.kind)}"></span><div><small>${esc(date(e.ts))} · ${esc(label(e.kind))}${e.state ? ` · ${esc(label(e.state))}` : ''}</small><button type="button" data-ghd-event="${i}">${esc(e.title || e.ref || 'Recorded activity')}</button></div></li>`).join('') || '<p class="ghd-empty">New sessions, reports, extracted models and builds will appear here as they are recorded.</p>'}</ol></section>
      <section class="ghd-panel"><div class="ghd-section-heading"><h3>Recent reports</h3><span>${count(reportTotal)} total</span></div><div class="ghd-reports">${reports.slice(0, 12).map((r, i) => `<button type="button" class="ghd-report" data-ghd-report="${i}"><span>${r.number ? `#${esc(r.number)} · ` : ''}${esc(r.title || 'Game report')}</span><small>${esc(label(r.status) || 'Status not recorded')} · ${esc(date(r.updated || r.created))}</small></button>`).join('') || '<p class="ghd-empty">No reports have been linked to this game.</p>'}</div></section></div>
      <section class="ghd-panel" data-ghd-live="activity"><div class="ghd-section-heading"><h3>Game activity</h3><span>${count(game.plays)} plays across ${count(devices.length)} devices</span></div>${devices.length ? `<div class="ghd-devices">${devices.map(d => `<span><b>${esc(d.name || 'Unknown device')}</b> ${count(d.plays)} plays · ${esc(date(d.last_played))}</span>`).join('')}</div>` : ''}<div class="ghd-activity">${activity.slice(0, 20).map((a, i) => `<div class="ghd-session"><div><b>${esc(a.device || 'Unknown device')}</b><small>${esc(date(a.started))}${a.ended ? ` – ${esc(date(a.ended))}` : ''}</small></div><span>${esc(a.mod || 'Original game')}${a.agent_use ? ' · automated test' : ''}</span><span class="ghd-tag">${esc(label(a.state) || (a.ended ? 'Ended' : 'Recorded'))}</span>${a.session_id ? `<button type="button" data-ghd-session="${i}">View session</button>` : ''}</div>`).join('') || '<p class="ghd-empty">Play sessions will appear here once recorded.</p>'}</div></section><div class="ghd-actions" data-ghd-assets-refresh hidden><span>New models or media are available.</span><button type="button" data-ghd-action="refresh-assets">Refresh assets</button></div><p class="ghd-model-status" data-ghd-live-status aria-live="polite"></p><p class="ghd-action-status" data-ghd-action-status role="status" aria-live="polite"></p>
    </div>`;
  }
  const CSS = `.ghd-root{--ghd-line:color-mix(in srgb,currentColor 15%,transparent);color:inherit;font:14px system-ui;display:grid;gap:20px;padding:22px 0}.ghd-root h2,.ghd-root h3,.ghd-root h4,.ghd-root p{margin:0}.ghd-root h2{font-size:25px;line-height:1.25}.ghd-root h3{font-size:17px}.ghd-root h4{font-size:14px}.ghd-heading,.ghd-section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.ghd-heading p,.ghd-root small,.ghd-empty,.ghd-model-status,.ghd-section-heading>span,.ghd-chart-dates{color:#aeb9cf}.ghd-heading p{margin-top:6px}.ghd-eyebrow{display:block;color:#9aaef1;font-size:10px;font-weight:700;letter-spacing:2px;margin-bottom:7px}.ghd-root button,.ghd-root select,.ghd-root a{font:inherit;color:inherit}.ghd-root button,.ghd-root select{border:1px solid #47566c;background:#263147;border-radius:6px;padding:7px 10px;cursor:pointer}.ghd-root button:hover{background:#344565;border-color:#8ba9e5}.ghd-root button:focus-visible,.ghd-root select:focus-visible{outline:2px solid #acc8ff;outline-offset:3px}.ghd-root .ghd-primary{background:#7d92ed;border-color:#9caeff;color:#fff}.ghd-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ghd-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:1px;background:var(--ghd-line);border:1px solid var(--ghd-line);border-radius:9px;overflow:hidden}.ghd-metrics>div{background:#1b2230;padding:16px;display:flex;flex-direction:column;gap:6px}.ghd-metrics b{font-size:15px;overflow-wrap:anywhere}.ghd-metrics span{color:#aeb9cf;font-size:12px}.ghd-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;align-items:start}.ghd-panel{background:#19212ee6;border:1px solid var(--ghd-line);border-radius:10px;padding:18px;min-width:0}.ghd-section-heading{margin-bottom:15px}.ghd-section-heading button{font-size:12px}.ghd-tag{display:inline-block;font-size:11px;background:#2b3950;color:#c3d0e9;padding:3px 6px;border-radius:5px;white-space:nowrap}.ghd-model-select{display:flex;align-items:center;gap:10px;font-size:12px;color:#aeb9cf;margin-bottom:10px}.ghd-model-select select{min-width:0;flex:1}.ghd-stage{height:310px;display:grid;place-items:center;background:#111925;border:1px solid #344359;border-radius:7px;overflow:hidden}.ghd-stage>p{padding:24px;text-align:center;max-width:360px;color:#aeb9cf;line-height:1.6}.ghd-model-status{font-size:12px;padding-top:10px;min-height:18px}.ghd-model-meta{font-size:12px;color:#cad6ed;line-height:1.7;margin-top:5px}.ghd-work-state{margin-top:18px;padding-top:15px;border-top:1px solid var(--ghd-line)}.ghd-work-state p{margin-top:6px;color:#aeb9cf;font-size:12px;line-height:1.6}.ghd-work-state ul{margin:10px 0 0;padding-left:18px}.ghd-work-state li{margin-top:10px}.ghd-work-state small{display:block;margin-top:4px;white-space:pre-wrap}.ghd-work-state progress{display:block;width:100%;height:7px;margin-top:8px;accent-color:#8ba9f4}.ghd-chart{margin-top:20px}.ghd-chart svg{display:block;width:100%;height:80px;fill:#6d91db}.ghd-chart-dates{display:flex;justify-content:space-between;font-size:10px;margin-top:6px;gap:12px}.ghd-chart>small{display:block;margin-top:8px;font-size:10px;line-height:1.5}.ghd-empty{font-size:13px;line-height:1.7;padding:8px 0}.ghd-builds{max-height:620px;overflow:auto;scrollbar-gutter:stable}.ghd-build{display:flex;gap:13px;padding:14px 0;border-top:1px solid var(--ghd-line)}.ghd-build:first-child{padding-top:0;border-top:0}.ghd-build>div{flex:1;min-width:0}.ghd-build-image{width:108px;height:98px;object-fit:cover;border-radius:6px;background:#111925}.ghd-build p{font-size:11px;color:#aeb9cf;margin:5px 0}.ghd-build .ghd-actions{margin-top:10px}.ghd-build button{font-size:11px;padding:5px 8px}.ghd-changes{font-size:12px;color:#c9d3e4;padding-left:16px;margin:8px 0;overflow-wrap:anywhere}.ghd-changes li{margin-top:3px}.ghd-gallery{display:flex;gap:13px;overflow-x:auto;padding-bottom:8px;scrollbar-gutter:stable}.ghd-gallery figure{flex:0 0 192px;width:192px;margin:0}.ghd-gallery img,.ghd-gallery video{display:block;width:192px;height:134px;object-fit:contain;background:#101723;border-radius:6px}.ghd-root .ghd-image-button{display:block;border:0;padding:0;background:transparent;overflow:hidden;border-radius:6px}.ghd-gallery figcaption{font-size:11px;color:#b8c7df;padding:8px 0;overflow-wrap:anywhere}.ghd-timeline{list-style:none;margin:0;padding:0;max-height:480px;overflow:auto}.ghd-timeline li{display:flex;gap:12px;padding-bottom:18px}.ghd-event-dot{background:#7499e5;width:8px;height:8px;border-radius:50%;flex:none;margin-top:5px}.ghd-event-dot[data-kind=build]{background:#79c3a1}.ghd-event-dot[data-kind=report]{background:#e0b975}.ghd-timeline small{font-size:10px;display:block;margin-bottom:5px}.ghd-root .ghd-timeline button{background:none;border:0;text-align:left;padding:0;font-size:13px}.ghd-report{display:block;width:100%;text-align:left;margin-bottom:9px}.ghd-report span,.ghd-report small{display:block}.ghd-report small{font-size:11px;margin-top:5px}.ghd-devices{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:15px}.ghd-devices span{font-size:11px;border:1px solid var(--ghd-line);padding:7px;border-radius:5px;color:#b9c6df}.ghd-devices b{margin-right:7px;color:#e0e8f8}.ghd-session{display:grid;grid-template-columns:minmax(190px,1fr) minmax(140px,1fr) auto auto;align-items:center;gap:14px;border-top:1px solid var(--ghd-line);padding:11px 0;font-size:12px}.ghd-session small{display:block;font-size:10px;margin-top:5px}.ghd-session button{font-size:11px}.ghd-action-status{color:#e0b975}.ghd-lightbox{background:#111925;color:#e2e9f8;max-width:90vw;max-height:92vh;border:1px solid #566b91;border-radius:10px;padding:14px}.ghd-lightbox::backdrop{background:#000b}.ghd-lightbox img{max-width:85vw;max-height:75vh;object-fit:contain;display:block}.ghd-lightbox button{display:block;margin-top:10px;background:#283a59;color:inherit;border:1px solid #6680ad;border-radius:5px;padding:7px 15px}@media(max-width:1000px){.ghd-columns{grid-template-columns:1fr}.ghd-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.ghd-heading{align-items:flex-start;flex-direction:column}}@media(max-width:600px){.ghd-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.ghd-panel{padding:13px}.ghd-session{grid-template-columns:1fr auto}.ghd-stage{height:260px}.ghd-build-image{width:74px;height:80px}.ghd-section-heading{gap:8px}.ghd-section-heading h3{font-size:15px}}@media(prefers-reduced-motion:reduce){.ghd-root *{scroll-behavior:auto!important}}`;
  const ASSETS_CSS = `.ghd-assets-panel .ghd-section-heading{flex-wrap:wrap}.ghd-asset-categories{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.ghd-asset-categories>div{display:flex;flex-direction:column;gap:5px;background:#111925;border:1px solid var(--ghd-line);border-radius:6px;padding:11px;overflow-wrap:anywhere}.ghd-asset-categories b{text-transform:capitalize}.ghd-asset-categories span,.ghd-asset-source>span{font-size:12px;color:#d3def2}.ghd-asset-categories small,.ghd-asset-source small,.ghd-asset-downloads small{display:block;font-size:11px;line-height:1.5}.ghd-assets-panel .ghd-asset-limit,.ghd-asset-downloads p{font-size:12px;line-height:1.6;color:#aeb9cf;margin-top:12px}.ghd-asset-source{display:grid;gap:6px;margin-top:13px}.ghd-asset-source details{font-size:11px;color:#aeb9cf}.ghd-asset-source details span{display:block;margin-top:6px}.ghd-asset-source code{overflow-wrap:anywhere;color:#c4d0e7}.ghd-asset-downloads{margin-top:14px;font-size:12px}.ghd-asset-downloads summary{cursor:pointer;font-weight:600}.ghd-asset-downloads li{padding:4px 0}.ghd-assets-panel a{color:#b4c9ff}.ghd-asset-jobs{padding-left:18px;font-size:12px}.ghd-asset-jobs progress{width:100%;height:6px;accent-color:#8ba9f4}.ghd-asset-jobs li{margin-top:8px}.ghd-assets-panel .ghd-asset-feedback{margin-top:12px;font-size:12px;line-height:1.6;color:#c4d0e7;overflow-wrap:anywhere}.ghd-asset-errors{font-size:12px;color:#e6ba91;overflow-wrap:anywhere;padding-left:18px}.ghd-assets-panel button:disabled{opacity:.6;cursor:default}@media(max-width:750px){.ghd-asset-categories{grid-template-columns:repeat(2,minmax(0,1fr))}.ghd-assets-panel .ghd-actions{gap:6px}}`;
  function geometryStats(viewer) {
    let vertices = 0, triangles = 0, meshes = 0;
    viewer.gltf?.scene?.traverse(o => {
      if (!o.isMesh) return;
      meshes++; vertices += o.geometry?.attributes?.position?.count || 0;
      triangles += (o.geometry?.index?.count || o.geometry?.attributes?.position?.count || 0) / 3;
    });
    return { meshes, vertices, triangles: Math.floor(triangles) };
  }
  function mount(host, data, io = {}) {
    const doc = host.ownerDocument || root.document;
    if (!doc.getElementById('gbox-home-detail-style')) {
      const style = doc.createElement('style'); style.id = 'gbox-home-detail-style'; style.textContent = '.ghd-root [hidden]{display:none!important}.ghd-root header.ghd-heading{position:static;inset:auto;z-index:auto;background:transparent;padding:0;border:0}.ghd-root .ghd-build-selected{background:#243451;border-left:3px solid #92b4ff;padding:12px;border-radius:7px}.ghd-root .ghd-selected-meta{font-size:12px;line-height:1.7}.ghd-root h2,.ghd-root .ghd-selected-meta{overflow-wrap:anywhere}' + CSS + ASSETS_CSS; doc.head.appendChild(style);
    }
    host.innerHTML = render(data, io);
    const game = data.game || {}, gid = game.game_id, pinnedSelection = selectedBuild(data), eligible = modelOptions(data), q = s => host.querySelector(s);
    let disposed = false, generation = 0, viewer = null, pendingStage = null, lightbox = null, pollTimer = null, refreshing = false, latest = data;
    let assetState = null, assetError = '', assetBusy = false, assetTimer = null, assetVersion = 0;
    const assetsKey = value => JSON.stringify([list(value.models).map(m => [m.slug, m.model_url, m.preview_url]), list(value.media).map(m => [m.kind, m.url])]);
    const initialAssets = assetsKey(data);
    const paintAssets = () => { if (!disposed) q('[data-ghd-title-assets]').innerHTML = assetsHTML(assetState, game, io, assetBusy, assetError); };
    function scheduleAssets() {
      root.clearTimeout(assetTimer); assetTimer = null;
      if (disposed || !list(assetState?.tasks).some(activeAssetTask)) return;
      assetTimer = root.setTimeout(() => {
        if (doc.hidden || io.visible && !io.visible()) { scheduleAssets(); return; }
        loadAssets();
      }, 5000);
    }
    async function loadAssets(body) {
      if (disposed || assetBusy) return;
      const version = ++assetVersion;
      assetBusy = true; assetError = ''; paintAssets();
      try {
        if (!io.api) throw new Error('Asset status is unavailable in this client.');
        const state = await io.api('/api/title-assets/' + encodeURIComponent(gid) + (body ? '/collect' : ''), body);
        if (disposed || version !== assetVersion) return;
        if (!state || state.game_id !== gid || !state.categories) throw new Error('Received asset status for a different title.');
        assetState = state;
      } catch (error) { if (!disposed && version === assetVersion) assetError = 'Asset status: ' + String(error.message || error).slice(0, 1200); }
      finally {
        if (!disposed && version === assetVersion) { assetBusy = false; paintAssets(); scheduleAssets(); }
      }
    }
    function stopModel() {
      generation++; viewer?.dispose?.(); viewer = null;
      pendingStage?.remove(); pendingStage = null;
      if (!disposed) q('[data-ghd-stage]').replaceChildren();
    }
    async function showModel(index) {
      if (disposed || !eligible[index]) return;
      stopModel(); const current = generation, model = eligible[index], outer = q('[data-ghd-stage]'), status = q('[data-ghd-model-status]');
      status.textContent = 'Loading ' + (model.name || model.slug) + '…';
      q('[data-ghd-model-meta]').textContent = '';
      // A detached staging node prevents late downloads from overwriting another model.
      const stage = doc.createElement('div'); stage.style.cssText = 'width:100%;height:100%;min-height:0;display:grid;place-items:center'; outer.appendChild(stage); pendingStage = stage;
      try {
        const mod = await (io.loadViewer ? io.loadViewer() : import('./character-model.js'));
        if (disposed || current !== generation) return;
        const loaded = await mod.createCharacterViewer(stage, urlFor(model.model_url, io), {
          autoRotate: !(root.matchMedia?.('(prefers-reduced-motion: reduce)').matches),
          model: model.file || model.model,
          fileUrl: rel => urlFor(`/api/characters/${encodeURIComponent(model.slug)}/file/${String(rel).split('/').map(encodeURIComponent).join('/')}`, io)
        });
        if (disposed || current !== generation) { loaded.dispose?.(); return; }
        viewer = loaded;
        const stats = geometryStats(loaded);
        q('[data-ghd-model-meta]').textContent = `${model.name || model.slug} · ${count(stats.meshes)} meshes · ${count(stats.vertices)} vertices · ${count(stats.triangles)} triangles`;
        status.textContent = 'Real collection model · drag to orbit · scroll to zoom';
      } catch (error) {
        if (disposed || current !== generation) return;
        stage.replaceChildren();
        const preview = urlFor(model.preview_url, io);
        if (preview) { stage.innerHTML = image(model.preview_url, model.name || model.slug, io, '', {game_id:gid, original_url:model.preview_original_url || model.preview_url}); stage.firstChild.style.cssText = 'max-width:100%;max-height:100%;object-fit:contain'; }
        else { const p = doc.createElement('p'); p.textContent = 'This model could not be displayed.'; stage.appendChild(p); }
        status.textContent = '3D preview unavailable: ' + String(error.message || error);
      }
    }
    function openImage(item) {
      const src = urlFor(originalImage(item), io); if (!src || disposed) return;
      lightbox?.remove();
      const dialog = doc.createElement('dialog'), img = doc.createElement('img'), close = doc.createElement('button');
      dialog.className = 'ghd-lightbox'; img.src = src; img.alt = item.label || game.title || 'Game image';
      if (gid) img.dataset.assetGame = gid;
      img.dataset.assetUrl = originalImage(item);
      img.dataset.assetOriginalUrl = originalImage(item); img.dataset.assetFormat = 'image'; img.dataset.assetName = img.alt;
      close.textContent = 'Close'; close.type = 'button';
      const done = () => { dialog.close?.(); dialog.remove(); if (lightbox === dialog) lightbox = null; };
      close.onclick = done; dialog.addEventListener('cancel', e => { e.preventDefault(); done(); });
      dialog.append(img, close); doc.body.appendChild(dialog); lightbox = dialog; dialog.showModal(); close.focus();
    }
    async function action(event) {
      const button = event.target.closest('button'); if (!button || !host.contains(button) || disposed) return;
      const status = q('[data-ghd-action-status]'); status.textContent = '';
      const launches = button.dataset.ghdAction === 'play' || button.dataset.ghdAction === 'play-selected' || button.dataset.ghdBuild !== undefined;
      if (button.dataset.ghdAction === 'play' && !playability(game).allowed) return;
      if (launches) { if (button.disabled) return; button.disabled = true; }
      const invoke = (name, ...args) => {
        if (typeof io[name] !== 'function') throw new Error(`${name === 'report' ? 'Report details' : name === 'session' ? 'Session details' : 'This action'} are unavailable in this client.`);
        return io[name](...args);
      };
      const buildOptions = build => ({ mod: build.name, ...(build.launch_node ? { node: build.launch_node } : {}) });
      try {
        if (['asset-status', 'asset-collect', 'asset-inventory'].includes(button.dataset.ghdAction)) {
          if (button.disabled || assetBusy) return;
          await loadAssets(button.dataset.ghdAction === 'asset-status' ? undefined : {
            categories: assetCategories.slice(),
            ...(button.dataset.ghdAction === 'asset-inventory' ? { refresh_inventory: true } : {}),
            ...(list(assetState?.tasks).some(failedAssetTask) ? { retry_failed: true } : {})
          });
        } else if (button.dataset.ghdAction === 'play') await invoke('launch', gid, ...(pinnedSelection ? [{ mod: '', slot: '' }] : []));
        else if (button.dataset.ghdAction === 'play-selected' && pinnedSelection) await invoke('launch', gid, buildOptions(selectedBuild(data) || pinnedSelection));
        else if (button.dataset.ghdAction === 'refresh-assets') await invoke('refreshDetail', latest);
        else if (button.dataset.ghdAction === 'models') await invoke('models', gid, game.title);
        else if (button.dataset.ghdAction === 'builds') await invoke('builds', gid);
        else if (button.dataset.ghdBuild !== undefined) await invoke('launch', gid, buildOptions(list(data.builds)[+button.dataset.ghdBuild]));
        else if (button.dataset.ghdReport !== undefined) await invoke('report', list(data.reports)[+button.dataset.ghdReport]?.id);
        else if (button.dataset.ghdSession !== undefined) await invoke('session', list(data.activity)[+button.dataset.ghdSession]?.session_id);
        else if (button.dataset.ghdMedia !== undefined) openImage(list(data.media)[+button.dataset.ghdMedia]);
        else if (button.dataset.ghdModelCard !== undefined) {
          const model = list(data.models)[+button.dataset.ghdModelCard], index = eligible.indexOf(model);
          if (index >= 0) { q('[data-ghd-model]').value = String(index); await showModel(index); if (!disposed) q('[data-ghd-stage]').scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }); }
          else await invoke('models', gid, game.title);
        } else if (button.dataset.ghdEvent !== undefined) {
          const row = events(data)[+button.dataset.ghdEvent];
          if (row.kind === 'report') await invoke('report', row.ref);
          else if (row.kind === 'session') await invoke('session', row.ref);
          else if (row.kind === 'model') await invoke('models', gid, game.title);
          else await invoke('builds', gid);
        }
      } catch (error) { if (!disposed) status.textContent = String(error.message || error); }
      finally { if (launches && !disposed) button.disabled = false; }
    }
    const change = event => { if (event.target.matches('[data-ghd-model]')) showModel(+event.target.value); };
    const context = event => { if (!io.context || event.target.closest('button,select,video,a,canvas')) return; io.context(event, game); };
    const mediaError = event => {
      if (disposed || event.target.tagName !== 'IMG') return;
      const img = event.target, fallback = doc.createElement('span'); fallback.className = img.className;
      fallback.textContent = 'Image unavailable'; fallback.setAttribute('role', 'img'); fallback.setAttribute('aria-label', img.alt || 'Image unavailable');
      fallback.style.cssText = 'display:grid;place-items:center;min-height:90px;color:#aeb9cf;font-size:12px'; img.replaceWith(fallback);
    };
    async function refresh() {
      if (disposed || refreshing || !io.api || doc.hidden || !host.isConnected || io.visible && !io.visible()) return;
      refreshing = true;
      try {
        const fresh = await io.api('/api/home/games/' + encodeURIComponent(gid));
        if (disposed) return;
        if (fresh?.game?.game_id !== gid) throw new Error('Received details for a different game');
        latest = { ...fresh, selected_build: pinnedSelection };
        // Keep the selected model and playing media intact. New catalogue assets are
        // offered explicitly; the dynamic sections and their indexed actions move together.
        const next = { ...fresh, selected_build: pinnedSelection, models: data.models, media: data.media }, fragment = doc.createElement('div');
        fragment.innerHTML = render(next, io);
        const selectors = ['.ghd-heading', '.ghd-metrics', '.ghd-work-state', '.ghd-progress-evidence', '.ghd-builds', '.ghd-timeline', '.ghd-reports', '[data-ghd-live=activity]'];
        for (const selector of selectors) {
          const current = q(selector), replacement = fragment.querySelector(selector);
          if (!current || !replacement || current.innerHTML === replacement.innerHTML) continue;
          const scrollTop = current.scrollTop;
          current.replaceWith(replacement); replacement.scrollTop = scrollTop;
        }
        data = next;
        q('[data-ghd-assets-refresh]').hidden = initialAssets === assetsKey(fresh) || !io.refreshDetail;
        q('[data-ghd-live-status]').textContent = 'Activity updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      } catch (error) { if (!disposed) q('[data-ghd-live-status]').textContent = 'Live activity could not refresh. Retrying shortly.'; }
      finally { refreshing = false; }
    }
    const schedule = () => {
      if (disposed || !io.api) return;
      pollTimer = root.setTimeout(async () => { await refresh(); schedule(); }, 15000);
    };
    host.addEventListener('click', action); host.addEventListener('change', change); host.addEventListener('contextmenu', context); host.addEventListener('error', mediaError, true);
    schedule();
    const donors = new Set(list(pinnedSelection?.changes).map(change => change.donor || change.character).filter(value => typeof value === 'string'));
    const matchingModel = eligible.findIndex(model => donors.has(model.slug)), initialModel = Math.max(0, matchingModel);
    if (eligible.length) q('[data-ghd-model]').value = String(initialModel);
    const assetsReady = io.api ? loadAssets() : Promise.resolve();
    return {
      ready: Promise.all([eligible.length ? showModel(initialModel) : Promise.resolve(), assetsReady]),
      refresh,
      dispose() {
        if (disposed) return;
        root.clearTimeout(pollTimer); pollTimer = null; root.clearTimeout(assetTimer); assetTimer = null; assetVersion++;
        disposed = true; stopModel(); lightbox?.close?.(); lightbox?.remove(); lightbox = null;
        for (const video of host.querySelectorAll('video')) { video.pause(); video.removeAttribute('src'); video.load(); }
        host.removeEventListener('click', action); host.removeEventListener('change', change); host.removeEventListener('contextmenu', context); host.removeEventListener('error', mediaError, true); host.replaceChildren();
      }
    };
  }
  const api = { mount, render, modelOptions, events, timelineSVG, geometryStats, safeURL, selectedBuild, assetsHTML };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxHomeDetail = api;
})(typeof window !== 'undefined' ? window : globalThis);
