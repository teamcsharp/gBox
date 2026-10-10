(function (root) {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const services = {
    codex: ['Codex', 'C', '#80cdb0'], nous: ['Nous', 'N', '#bd95e7'], zai: ['Z AI', 'Z', '#80b8ff'],
    deepseek: ['DeepSeek', 'DS', '#5d8cff'], 'ollama-cloud': ['Ollama Cloud', 'O', '#d5d5df'],
    openrouter: ['OpenRouter', 'OR', '#bb9dff'], google: ['Google', 'G', '#6dcda2'],
    openai: ['OpenAI', 'AI', '#80cdb0'], local: ['Local model', 'L', '#b7b889'], unknown: ['Unrecorded', '?', '#999']
  };
  function canonical(service) {
    const name = String(service || '').toLowerCase().trim();
    return ({ 'z-ai': 'zai', 'z ai': 'zai', 'nous portal': 'nous', 'ollama_cloud': 'ollama-cloud',
      'ollama cloud': 'ollama-cloud', 'ollama': 'local', 'llamacpp': 'local', 'custom': 'local',
      'openai-api': 'openai', 'gemini': 'google' })[name] || name || 'unknown';
  }
  function attribution(request) {
    const explicit = request.solved_by;
    if (explicit?.service && explicit.verification) return { ...explicit, service: canonical(explicit.service), recorded: true };
    // Older usage records identify a model that participated, not necessarily
    // the model that produced the accepted implementation. Never award it a win.
    const metrics = request.metrics || {};
    return { service: canonical(metrics.provider), model: metrics.model || '', system: metrics.system || '', recorded: false };
  }
  function badge(request) {
    if (request.status !== 'done') return '';
    const solver = attribution(request), [name, glyph, color] = services[solver.service] || [solver.service, 'AI', '#aaa'];
    const title = solver.recorded
      ? `Solved by ${name}${solver.model ? ' · ' + solver.model : ''}${solver.system ? ' · ' + solver.system : ''}${solver.verified_by ? '\nVerified by ' + solver.verified_by : ''}\n${solver.verification}`
      : `Solver was not recorded.${solver.model ? '\nRecorded usage model: ' + solver.model + ' (not completion credit).' : ''}`;
    return `<button class="act solver-badge" data-solver-benchmark="${esc(solver.recorded ? solver.service : 'unknown')}" title="${esc(title)}" aria-label="${esc(title)}" style="display:inline-flex;align-items:center;gap:4px;padding:2px 5px;font-size:11px"><svg viewBox="0 0 28 28" width="23" height="23" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="${solver.recorded ? color : '#777'}"/><text x="14" y="18" text-anchor="middle" font-size="${glyph.length > 1 ? 9 : 13}" font-weight="700" fill="#15151b">${solver.recorded ? glyph : '?'}</text></svg>${esc(solver.recorded ? name : 'Unrecorded')}</button>`;
  }
  function benchmark(requests) {
    const groups = new Map(); let unrecorded = 0;
    for (const request of requests) {
      if (request.status !== 'done' || request.automated && !request.context?.auto_report) continue;
      const solver = attribution(request);
      if (!solver.recorded) { unrecorded++; continue; }
      const key = JSON.stringify([solver.service, solver.model, solver.system]);
      const group = groups.get(key) || { ...solver, count: 0, seconds: 0, timed: 0, tokens: 0, metered: 0 };
      const metrics = request.metrics || {}, usage = (metrics.usage_by_solver || []).find(item =>
        canonical(item.provider) === solver.service && item.model === solver.model && item.system === solver.system);
      group.count++;
      // Queue time is not execution time. Only measured agent duration counts.
      if (usage?.timed && Number.isFinite(usage.agent_seconds)) { group.seconds += usage.agent_seconds; group.timed++; }
      if (usage && !usage.token_count_unavailable && Number.isFinite(usage.tokens_in) && Number.isFinite(usage.tokens_out) && usage.tokens_in + usage.tokens_out > 0) {
        group.tokens += usage.tokens_in + usage.tokens_out; group.metered++;
      }
      groups.set(key, group);
    }
    return { groups: [...groups.values()].sort((a, b) => b.count - a.count || a.service.localeCompare(b.service)), unrecorded };
  }
  function show(requests, selected) {
    document.querySelector('#solver-benchmarks')?.remove();
    const data = benchmark(requests), dialog = document.createElement('dialog');
    dialog.id = 'solver-benchmarks'; dialog.style.cssText = 'width:min(950px,90vw);max-height:85vh;overflow:auto;background:var(--card,#202027);color:var(--fg,#fff);border:1px solid var(--line,#444);border-radius:10px;padding:20px';
    dialog.innerHTML = `<div style="display:flex;align-items:center;gap:12px"><h2 style="margin:0;flex:1">Verified inbox results by solver</h2><button class="act" data-close>Close</button></div><p class="mut">Completion credit identifies the implementation service and model. Reviewers are recorded separately. Reopened issues do not count as solved.</p><div style="overflow:auto"><table style="width:100%;text-align:left"><thead><tr><th>Service</th><th>Model / system</th><th>Verified completions</th><th>Measured agent time</th><th>Recorded tokens</th></tr></thead><tbody>${data.groups.map(group => `<tr style="${selected === group.service ? 'background:#8190ff22' : ''}"><td>${esc(services[group.service]?.[0] || group.service)}</td><td>${esc(group.model || 'Not recorded')}<br><small>${esc(group.system)}</small></td><td>${group.count}</td><td>${group.timed ? Math.round(group.seconds / group.timed) + 's average (' + group.timed + ' measured)' : 'Not recorded'}</td><td>${group.metered ? group.tokens.toLocaleString() + ' (' + group.metered + ' measured)' : 'Not recorded'}</td></tr>`).join('') || '<tr><td colspan="5">No verified solver attribution has been recorded yet.</td></tr>'}</tbody></table></div><p class="mut">${data.unrecorded} older completed tickets have no verified solver attribution. They are excluded. Ticket totals and mixed task difficulty alone do not establish which model performs best.</p>`;
    document.body.append(dialog); dialog.showModal();
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => dialog.remove());
  }
  const api = { canonical, attribution, badge, benchmark, show };
  root.GBoxRequestSolvers = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
