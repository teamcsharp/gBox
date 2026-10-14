const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const {spawn}=require('node:child_process');
function findChrome() {
  if (process.env.GBOX_CHROME && fs.existsSync(process.env.GBOX_CHROME)) return process.env.GBOX_CHROME;
  if (process.platform === 'win32') {
    for (const p of [path.join(process.env['PROGRAMFILES(X86)'] || '', 'Microsoft/Edge/Application/msedge.exe'),
      path.join(process.env.PROGRAMFILES || '', 'Google/Chrome/Application/chrome.exe')]) {
      if (fs.existsSync(p)) return p;
    }
  }
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
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore', windowsHide: true });
  const exited = new Promise(resolve => proc.once('exit', resolve));
  let ws;
  try {
    // Same startup as test_chat_conversation_composer.cjs: wait for each condition (up to 30 s), and
    // evaluate only after our own about:blank load so the command-line navigation cannot replace the
    // document mid-script.
    const until = async (what, probe) => {
      for (const end = Date.now() + 30000; ;) {
        const value = await probe().catch(() => null);
        if (value) return value;
        if (Date.now() > end || proc.exitCode !== null) throw new Error(`headless browser: no ${what}`);
        await new Promise(r => setTimeout(r, 50));
      }
    };
    const portFile = path.join(profile, 'DevToolsActivePort');
    const port = await until('DevToolsActivePort', async () => {
      const line = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
      return /^\d+$/.test(line) && line;
    });
    const page = await until('page target', async () =>
      (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page' && t.webSocketDebuggerUrl));
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((ok, no) => { ws.onopen = ok; ws.onerror = no; });
    let seq = 0; const waiting = new Map(), events = [];
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.id === undefined) { events.push(m.method); return; }
      waiting.get(m.id)?.(m); waiting.delete(m.id);
    };
    const send = (method, params) => new Promise(ok => { const id = ++seq; waiting.set(id, ok); ws.send(JSON.stringify({ id, method, params })); });
    await send('Page.enable', {});
    events.length = 0;
    await send('Page.navigate', { url: 'about:blank' });
    await until('page load', async () => events.includes('Page.loadEventFired'));
    const evaluate = async expression => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.error) throw new Error('Runtime.evaluate: ' + JSON.stringify(r.error));
      if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
      return r.result.result.value;
    };
    await fn(evaluate, send);
  } finally {
    // Close only the browser created for this temporary profile, including its child processes.
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ id: 1000000, method: 'Browser.close' }));
    const delay = ms => new Promise(resolve => { const timer = setTimeout(resolve, ms); timer.unref(); });
    await Promise.race([exited, delay(3000)]);
    if (proc.exitCode === null && proc.signalCode === null) {
      proc.kill('SIGKILL'); await Promise.race([exited, delay(3000)]);
    }
    ws?.close();
    // Windows can retain a profile file handle briefly after the parent browser exits.
    for (let i = 0; i < 300; i++) {
      try { if (path.dirname(path.resolve(profile)) !== path.resolve(os.tmpdir()) || !path.basename(profile).startsWith('gbox-tk-')) throw new Error('Unexpected browser profile path');
        fs.rmSync(profile, { recursive: true, force: true }); break; }
      catch (error) {
        if (i === 299 || !['EPERM', 'EBUSY', 'ENOTEMPTY'].includes(error.code)) throw error;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
  }
}


module.exports={withPage,findChrome};
