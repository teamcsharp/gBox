// A recovery supervisor may preserve settings in a new profile when Windows
// retains an exited Electron process's lock. Normal startup follows that saved
// selection too. Selection is explicit: a lock failure never creates a second app.
const fs = require('node:fs');
const path = require('node:path');

function resolve(appData, standalone) {
  if (standalone) return path.join(standalone, '.tools', 'desktop-profile');
  const fallback = path.join(appData, 'gbox-desktop');
  try {
    const selected = JSON.parse(fs.readFileSync(path.join(appData, 'gbox-desktop-profile.json'), 'utf8'));
    if (selected.v !== 1 || !/^gbox-desktop-recovery-[a-f0-9]{16}$/.test(selected.directory)) return fallback;
    const candidate = path.join(appData, selected.directory);
    if (!fs.lstatSync(candidate).isDirectory() || fs.lstatSync(candidate).isSymbolicLink()) return fallback;
    if (path.dirname(fs.realpathSync(candidate)).toLowerCase() !== fs.realpathSync(appData).toLowerCase()) return fallback;
    return candidate;
  } catch { return fallback; }
}

module.exports = { resolve };
