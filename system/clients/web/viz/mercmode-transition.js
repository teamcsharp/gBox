/* The picture-in-picture window between MercMode titles: one of the random gBox visualizations with a loading
   bar while the next title boots in the background (operator 2026-10-24). Polls /api/mercmode; the host that owns
   the displayed session says which phase its run is in (GBoxMercMode.transition). No input, no launch. */
(function (root, factory) { const api = factory(); if (typeof module === 'object' && module.exports) module.exports = api; else root.GBoxMercModeTransition = api; })(globalThis, function () {
  'use strict';
  const CSS = `#compact-transition{display:none;position:fixed;inset:0;z-index:105;background:#000;color:#fff;font:13px system-ui;overflow:hidden}
    #compact-transition.on{display:block}#compact-transition canvas{position:absolute;inset:0;width:100%;height:100%}
    #compact-transition .mmt-text{position:absolute;left:0;right:0;bottom:46px;text-align:center;text-shadow:0 1px 4px #000}
    #compact-transition .mmt-text b{display:block;font-size:17px;margin-bottom:3px}#compact-transition .mmt-text span{opacity:.75;font-size:11px}
    #compact-transition .mmt-bar{position:absolute;left:12%;right:12%;bottom:26px;height:6px;border-radius:3px;background:#ffffff26;overflow:hidden}
    #compact-transition .mmt-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#5aa0ff,#9bffd6);transition:width .6s linear}`;
  // A status read that hangs never freezes the overlay (operator 2026-10-26, the PiP on "Loading Resident Evil 5..." while
  // RE5 had played for 16 minutes: "mercmode is just sitting here frozen"): each read gives up after READ_TIMEOUT_S, and
  // the overlay never stays up longer than SHOW_MAX_S without a read that says a title is really booting
  const READ_TIMEOUT_S = 8, SHOW_MAX_S = 240;
  function create({ mercmode, api, current, worker = () => null, render, follow = null, now = () => Date.now() / 1000,
                    timeout = ms => new Promise((_, reject) => setTimeout(() => reject(Error('MercMode status timed out')), ms)) }) {
    let stopped = false, polling = false, following = false, shownSince = null;
    const state = { show: false, title: '', progress: 0, phase: '', text: '', sub: '' };
    async function poll() {
      if (stopped || polling) return;
      const sid = current();
      polling = true;
      try {
        const data = await Promise.race([api('/api/mercmode', undefined, 'GET'), timeout(READ_TIMEOUT_S * 1000)]);
        if (stopped) return;
        const next = mercmode.transition(mercmode.hostFor(data, sid, worker()), sid, now());
        Object.assign(state, { show: false, progress: 0, follow: null, only_if_ended: false }, next);
        if (!state.show) shownSince = null;
        else if (shownSince === null) shownSince = now();
        else if (now() - shownSince > SHOW_MAX_S) state.show = false;      // not a boot any more: never a frozen screen
        if (next.follow && follow && !following) {          // the run plays elsewhere: the PiP goes to it (one at a time;
          following = true;                                 // a black first frame is retried on the next poll)
          Promise.resolve().then(() => follow(next.follow, Boolean(next.only_if_ended))).catch(() => {}).finally(() => { following = false; });
        }
      } catch { state.show = false; shownSince = null; }
      finally { polling = false; }
      render({ ...state });
    }
    return { poll, state: () => ({ ...state }), stop: () => { stopped = true; } };
  }
  function mount(host, options) {
    host.id = 'compact-transition';
    host.innerHTML = '<canvas aria-hidden="true"></canvas><div class="mmt-text"><b data-mmt-title></b><span data-mmt-sub></span></div><div class="mmt-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><i></i></div>';
    let shown = false;
    const ctl = create({ ...options, render: state => {
      if (state.show !== shown) { shown = state.show; host.classList.toggle('on', shown); if (shown) options.visual?.start?.(host.querySelector('canvas')); else options.visual?.stop?.(); }
      host.querySelector('[data-mmt-title]').textContent = state.text || '';
      host.querySelector('[data-mmt-sub]').textContent = state.sub || '';
      const bar = host.querySelector('.mmt-bar'); bar.setAttribute('aria-valuenow', String(state.progress || 0));
      bar.querySelector('i').style.width = (state.progress || 0) + '%';
    } });
    const timer = setInterval(() => ctl.poll(), 2000); ctl.poll();
    return { ...ctl, stop: () => { clearInterval(timer); ctl.stop(); options.visual?.stop?.(); host.classList.remove('on'); } };
  }
  return { CSS, create, mount };
});
