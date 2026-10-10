/* One click captures the failing session and starts a tracked recovery. */
const EMULATION_INCIDENTS = new Map();

async function toggleEmulationTroubleshooting(sid) {
  const previous = document.getElementById('emulation-troubleshooting-menu');
  if (previous) { previous.closeMenu(); return; }
  const button = document.getElementById('emulation-troubleshooting');
  const menu = document.createElement('section');
  menu.id = 'emulation-troubleshooting-menu';
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', 'Emulation troubleshooting');
  const rect = button.getBoundingClientRect();
  menu.style.cssText = `position:fixed;z-index:100;left:${Math.max(8, Math.min(rect.left, innerWidth - 368))}px;top:${rect.bottom + 6}px;width:min(360px,calc(100vw - 16px));max-height:65vh;overflow:auto;padding:8px;background:var(--card,#191b23);color:var(--fg,#eee);border:1px solid var(--line,#444);border-radius:10px;box-shadow:0 16px 50px #0009`;
  menu.innerHTML = '<b style="display:block;padding:8px">Troubleshooting</b><p role="status">Loading available repairs...</p>';
  button.setAttribute('aria-expanded', 'true');
  document.body.append(menu);
  const close = () => { menu.remove(); button.setAttribute('aria-expanded', 'false'); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', keyboard); };
  menu.closeMenu = close;
  const outside = e => { if (!menu.contains(e.target) && !button.contains(e.target)) close(); };
  const keyboard = e => { if (e.key === 'Escape') { close(); button.focus(); } };
  document.addEventListener('pointerdown', outside); document.addEventListener('keydown', keyboard);
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sid)}/troubleshooting`);
    if (!menu.isConnected) return;
    menu.innerHTML = '<b style="display:block;padding:8px">Troubleshooting</b>' + data.recipes.map(r =>
      `<button class="act" data-recipe="${esc(r.id)}" style="display:block;width:100%;text-align:left;white-space:normal;padding:10px;margin:3px 0"><b>${esc(r.label)}</b><span class="mut" style="display:block;font-size:12px;margin-top:4px">${esc(r.detail)}</span></button>`).join('') +
      '<button class="act" data-settings style="width:100%;text-align:left;padding:10px">Emulator graphics settings...</button>' +
      '<p class="mut" style="font-size:12px;padding:0 8px">Each repair saves evidence and shows its attempts in an inbox report.</p>';
    menu.querySelectorAll('[data-recipe]').forEach(b => b.onclick = () => { close(); reportEmulationIssue(sid, b.dataset.recipe); });
    menu.querySelector('[data-settings]').onclick = async () => { close(); if (!document.getElementById('gfx')) await show('Sessions', sid, 'play'); document.getElementById('gfx')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
    menu.querySelector('button')?.focus();
  } catch (error) { menu.querySelector('[role=status]').textContent = 'Troubleshooting unavailable: ' + error.message; }
}

function incidentPanel() {
  let panel = document.getElementById('emulation-recovery');
  if (!panel) {
    panel = document.createElement('section');
    panel.id = 'emulation-recovery';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Emulation report and recovery');
    panel.style.cssText = 'position:fixed;z-index:90;right:18px;bottom:28px;width:min(420px,calc(100vw - 36px));max-height:65vh;overflow:auto;padding:16px;background:var(--card,#191b23);color:var(--fg,#eee);border:1px solid var(--line,#444);border-radius:12px;box-shadow:0 16px 50px #0009';
    panel.innerHTML = '<div class="bar"><b>Emulation report &amp; recovery</b><button class="act" aria-label="Minimize recovery output" style="margin-left:auto">&#8722;</button></div><p data-incident-status role="status">Capturing the reported moment...</p><div data-incident-steps></div>';
    panel.querySelector('button').onclick = () => panel.hidden = true;
    document.body.append(panel);
  }
  panel.hidden = false;
  return panel;
}

async function reportEmulationIssue(sid, action = 'auto') {
  const existing = EMULATION_INCIDENTS.get(sid);
  if (existing) { incidentPanel(); return; }
  EMULATION_INCIDENTS.set(sid, { pending: true });
  const button = document.getElementById('emulation-issue');
  if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
  if (window.GBOX_LOCAL?.incidentCapture) {
    const previous = document.getElementById('emulation-recovery');
    if (previous) previous.hidden = true;
    console.log('GBOX:' + JSON.stringify({ ev: 'emulationissue', sid, action }));
    return;
  }
  const panel = incidentPanel();
  panel.querySelector('[data-incident-status]').textContent = 'Saving the screenshot and session diagnostics to the inbox...';
  try {
    const response = await api(`/api/sessions/${encodeURIComponent(sid)}/emulation-issue`, {
      action,
      context: { page: location.href, viewport: { width: innerWidth, height: innerHeight }, tab: cur,
                 game_view: document.querySelector('#session-head')?.innerText || '' }
    });
    emulationIssueAccepted(sid, response);
  } catch (error) { emulationIssueFailed(sid, error.message); }
}

function emulationIssueFailed(sid, error) {
  EMULATION_INCIDENTS.delete(sid);
  incidentPanel().querySelector('[data-incident-status]').textContent = 'Report could not be saved: ' + error;
  const button = document.getElementById('emulation-issue');
  if (button) { button.disabled = false; button.removeAttribute('aria-busy'); }
}

async function emulationIssueAccepted(sid, response) {
  const item = { ...response, pending: false };
  EMULATION_INCIDENTS.set(sid, item);
  // Rebuild the native slot as well as the web stream; lost docking is itself a display fault.
  if (cur === 'Sessions' && playing === sid) await show('Sessions', sid, sessionMode);
  const panel = incidentPanel(), status = panel.querySelector('[data-incident-status]');
  const draw = report => {
    const steps = report.messages.filter(m => m.task_step).slice(-30);
    panel.querySelector('[data-incident-steps]').innerHTML = `<div class="bar"><button class="act" data-open-incident>Open report #${report.number}</button></div>` +
      steps.map(m => `<details style="border-top:1px solid var(--line,#444);padding:9px 0"><summary>${esc(m.task_step.action)} <span class="mut">${esc(m.task_step.status)}</span></summary><p>${esc(m.text)}</p>${(m.attachments || []).map(a => {
        const url = '/api/artifacts/' + encodeURIComponent(a.sha256) + '?' + tq();
        return a.type?.startsWith('image/') ? `<a href="${esc(url)}" target="_blank" rel="noopener"><img alt="${esc(a.name)}" style="width:100%;border-radius:6px" src="${esc(url)}"></a>` :
          `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(a.name)}</a>`;
      }).join('')}</details>`).join('');
    panel.querySelector('[data-open-incident]').onclick = () => {
      if (window.GBOX_LOCAL?.incidentCapture) console.log('GBOX:' + JSON.stringify({ ev: 'emulationreport', requestId: report.id }));
      else { panel.querySelectorAll('details').forEach(d => d.open = true); }
    };
  };
  try {
    for (;;) {
      const [job, report] = await Promise.all([api('/api/jobs/' + item.job.id), api('/api/requests/' + item.request.id)]);
      item.job = job; draw(report);
      status.textContent = `Report #${report.number} saved. ${job.progress?.msg || 'Collecting evidence before recovery...'}`;
      if (!['queued', 'running'].includes(job.state)) {
        const recovered = job.output?.motion;
        status.textContent = job.output?.diagnostics_only ? `Report #${report.number}: diagnostics captured. Hermes investigation queued.` : recovered ? `Report #${report.number}: visible game motion returned. Root-cause investigation continues.` :
          `Report #${report.number}: ${job.error || 'Recovery needs further investigation.'}`;
        if (job.output?.session_id && job.output.session_id !== sid && cur === 'Sessions' && playing === sid)
          await show('Sessions', job.output.session_id);
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
  } catch (error) { status.textContent = `Report #${item.request.number} saved. Output connection interrupted: ${error.message}`; }
  finally {
    EMULATION_INCIDENTS.delete(sid);
    const button = document.getElementById('emulation-issue');
    if (button) { button.disabled = false; button.removeAttribute('aria-busy'); }
  }
}
