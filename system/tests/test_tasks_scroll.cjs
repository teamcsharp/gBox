// #1289: the Technical task list must not throw the reader back to the top on its 5 s refresh.
// The DOM behaviour runs in a real headless Chromium (driven over CDP); the browser checks are
// skipped when no Chromium is installed, the source checks always run.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const html = fs.readFileSync(path.join(__dirname, '../clients/desktop/index.html'), 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `missing desktop source boundary: ${start}`);
  return html.slice(a, b);
}
const helpers = between('const TK_OWNER', 'async function tasksLocalLoad()');

test('every Technical refresh path keeps the reader place', () => {
  const load = between('async function tasksLoad()', 'async function tkHermesRefresh');
  assert.match(load, /tkRender\(\$\("#tk-body"\), `<div class="mc"><div class="mh"><b>Hermes background runs/);
  assert.match(load, /, \$\("#tk-technical"\)\);\s*\$\("#tk-body"\)\.querySelectorAll\("details\[data-detail-hermes\]\[open\]"\)/);
  assert.doesNotMatch(load, /\$\("#tk-body"\)\.innerHTML\s*=/, 'tasksLoad must not replace the list directly');
  // An open job keeps its loaded details instead of collapsing to "Loading…", which shrank the panel.
  assert.equal((load.match(/TK\.jobDetail\.get\(j\.id\) \|\| "Loading task details…"/g) || []).length, 2);
  assert.match(load, /<details data-tk-key="cmd:/);
  const local = between('async function tasksLocalLoad()', 'async function tasksLoad()');
  assert.match(local, /tkRender\(\$\("#tk-local"\), html, pane\)/);
  const job = between('async function tkJobRefresh(detail)', 'async function tvPoll()');
  assert.match(job, /if \(box\.tkMain !== main\)/);
  assert.match(job, /holder\.tkHtml === filesHtml/);
});

function findChrome() {
  if (process.env.GBOX_CHROME && fs.existsSync(process.env.GBOX_CHROME)) return process.env.GBOX_CHROME;
  const root = path.join(os.homedir(), '.cache/ms-playwright');
  if (!fs.existsSync(root)) return null;
  for (const dir of fs.readdirSync(root).sort().reverse()) {
    for (const rel of ['chrome-linux/headless_shell', 'headless_shell', 'chrome-linux/chrome', 'chrome-linux64/chrome']) {
      const p = path.join(root, dir, rel);
      if (/^chromium/.test(dir) && fs.existsSync(p)) return p;
    }
  }
  return null;
}

async function withPage(fn) {
  const chrome = findChrome();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'gbox-tk-'));
  const proc = spawn(chrome, ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
  try {
    const portFile = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 200 && !fs.existsSync(portFile); i++) await new Promise(r => setTimeout(r, 50));
    const port = fs.readFileSync(portFile, 'utf8').split('\n')[0];
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
    await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
    let seq = 0; const waiting = new Map();
    ws.onmessage = e => { const m = JSON.parse(e.data); waiting.get(m.id)?.(m); waiting.delete(m.id); };
    const send = (method, params) => new Promise(ok => { const id = ++seq; waiting.set(id, ok); ws.send(JSON.stringify({ id, method, params })); });
    const evaluate = async expression => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
      return r.result.result.value;
    };
    await fn(evaluate);
    ws.close();
  } finally {
    proc.kill('SIGKILL');
    fs.rmSync(profile, { recursive: true, force: true });
  }
}

test('a refresh keeps the panel scroll, open logs and expanded rows in a real browser', { skip: !findChrome() && 'no Chromium installed' }, async () => {
  await withPage(async evaluate => {
    const out = await evaluate(`(() => {
      document.body.innerHTML = '<div id="pane" style="height:200px;overflow:auto"><div id="host"></div></div>';
      const TK = { pointerDown: 0, scrolledAt: 0 };
      ${helpers}
      const pane = document.getElementById('pane'), host = document.getElementById('host');
      const lines = n => Array.from({ length: n }, (_, i) => 'trace line ' + i).join('\\n');
      const page = (cpu, n) => '<div style="height:600px">CPU ' + cpu + '%</div>' +
        '<details data-resolution-id="r1270" open><summary>#1270</summary><pre style="height:80px;overflow:auto;margin:0">' + lines(n) + '</pre></details>' +
        '<details data-resolution-id="r1291" open><summary>#1291</summary><pre style="height:80px;overflow:auto;margin:0">' + lines(n) + '</pre></details>' +
        '<table><tr><td><details data-tk-key="cmd:w:42"><summary>retroarch</summary><pre>retroarch.exe -L flycast</pre></details></td></tr></table>' +
        '<div style="height:600px"></div>';
      const out = {};
      out.first = tkRender(host, page(1, 100), pane);
      pane.scrollTop = 500;
      const pre = host.querySelector('pre'); pre.scrollTop = 300;
      host.querySelector('[data-tk-key]').open = true;
      out.same = tkRender(host, page(1, 100), pane);
      out.sameNode = host.querySelector('pre') === pre;
      out.changed = tkRender(host, page(2, 120), pane);
      out.newNode = host.querySelector('pre') !== pre;
      out.paneTop = pane.scrollTop;
      out.preTop = host.querySelectorAll('pre')[0].scrollTop;
      out.untouchedTop = host.querySelectorAll('pre')[1].scrollTop;
      out.cmdOpen = host.querySelector('[data-tk-key]').open;
      const live = host.querySelector('pre'); live.scrollTop = live.scrollHeight;
      tkRender(host, page(3, 200), pane);
      const grown = host.querySelector('pre');
      out.follows = grown.scrollTop > 0 && grown.scrollTop + grown.clientHeight >= grown.scrollHeight - 2;
      const range = document.createRange(); range.selectNodeContents(grown);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      out.selectionDefers = tkRender(host, page(4, 200), pane) === false && host.querySelector('pre') === grown;
      getSelection().removeAllRanges();
      out.afterSelection = tkRender(host, page(4, 200), pane);
      TK.pointerDown = Date.now();
      out.dragDefers = tkRender(host, page(5, 200), pane) === false;
      TK.pointerDown = 0;
      out.afterDrag = tkRender(host, page(5, 200), pane);
      out.finalPaneTop = pane.scrollTop;
      return out;
    })()`);
    assert.equal(out.first, true);
    assert.equal(out.same, false, 'an unchanged refresh must not re-render');
    assert.equal(out.sameNode, true);
    assert.equal(out.changed, true);
    assert.equal(out.newNode, true, 'the changed refresh really replaced the markup');
    assert.equal(out.paneTop, 500, 'the panel stays where the reader scrolled');
    assert.equal(out.preTop, 300, 'an open trace stays where the reader scrolled');
    assert.equal(out.untouchedTop, 0);
    assert.equal(out.cmdOpen, true, 'an expanded command line stays expanded');
    assert.equal(out.follows, true, 'a log read at its end keeps following new lines');
    assert.equal(out.selectionDefers, true, 'a refresh waits while text is selected');
    assert.equal(out.afterSelection, true);
    assert.equal(out.dragDefers, true, 'a refresh waits while the scrollbar is held');
    assert.equal(out.afterDrag, true);
    assert.equal(out.finalPaneTop, 500);
  });
});
