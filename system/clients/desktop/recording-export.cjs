'use strict';
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const fsp = fs.promises;

const DEFAULTS = Object.freeze({ targetMB: 20, speed: 'balanced', keep: true, capture: 'gameplay', exportDir: '' });
function preferences(value = {}) {
  if (!value || typeof value !== 'object') value = {};
  const p = { ...DEFAULTS };
  if (Number.isFinite(value.targetMB) && value.targetMB >= 0 && value.targetMB <= 100) p.targetMB = value.targetMB;
  if (['fast', 'balanced', 'best'].includes(value.speed)) p.speed = value.speed;
  if (typeof value.keep === 'boolean') p.keep = value.keep;
  if (['gameplay', 'app'].includes(value.capture)) p.capture = value.capture;
  if (typeof value.exportDir === 'string') p.exportDir = value.exportDir.trim();
  if (p.exportDir && (!path.isAbsolute(p.exportDir) || /[\x00-\x1f]/.test(p.exportDir))) throw Error('Choose an absolute export folder or a network share');
  return p;
}
const fingerprint = async file => {
  const s = await fsp.stat(file, { bigint: true });
  return [s.dev, s.ino, s.size, s.mtimeNs].join(':');
};
async function digest(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function ownedOriginal(file, directory) {
  const resolved = await fsp.realpath(file), root = await fsp.realpath(directory);
  if (path.dirname(resolved) !== root || !/\.(mp4|webm)$/i.test(resolved) || (await fsp.lstat(file)).isSymbolicLink())
    throw Error('Only a local gBox recording can be processed');
  return resolved;
}

// Exclusive publication never replaces a same-named recording from another instance.
async function publish(source, directory, basename) {
  await fsp.mkdir(directory, { recursive: true });
  const stamp = await fingerprint(source), hash = await digest(source);
  const stage = path.join(directory, `.gbox-export-${crypto.randomUUID()}.partial`);
  let final, created = false;
  try {
    await fsp.copyFile(source, stage, fs.constants.COPYFILE_EXCL);
    if (await fingerprint(source) !== stamp || await digest(stage) !== hash) throw Error('Recording changed or the export copy did not verify');
    for (let attempt = 0; attempt < 5; attempt++) {
      const parsed = path.parse(basename);
      final = path.join(directory, attempt ? `${parsed.name}-${crypto.randomUUID()}${parsed.ext}` : basename);
      try { await fsp.copyFile(stage, final, fs.constants.COPYFILE_EXCL); created = true; break; }
      catch (e) { if (e.code !== 'EEXIST') throw e; }
    }
    if (!created) throw Error('Could not reserve a unique export filename');
    const handle = await fsp.open(final, 'r+');
    try { await handle.sync(); } finally { await handle.close(); }
    if (await digest(final) !== hash) throw Error('The published export did not verify');
    return final;
  } catch (e) {
    if (created) await fsp.unlink(final).catch(() => {});
    throw e;
  } finally { await fsp.unlink(stage).catch(() => {}); }
}

async function finish({ original, candidate, exportDir, keep, originalStamp }) {
  let file = candidate, exported = false;
  if (exportDir) {
    const folder = path.resolve(exportDir);
    if (path.resolve(path.dirname(candidate)) !== folder) {
      try { file = await publish(candidate, folder, path.basename(candidate)); exported = true; }
      catch (e) { throw Error(`Export failed: ${e.message}. Original retained at ${original}; local video retained at ${candidate}`); }
    } else exported = true;
  }
  let originalDeleted = false, warning = '';
  if (!keep && file !== original) {
    if (await fingerprint(original) === originalStamp) {
      try { await fsp.unlink(original); originalDeleted = true; }
      catch (e) { warning = `Export saved; original could not be deleted: ${e.message}`; }
    } else warning = 'Export saved; original changed during processing and was kept';
  }
  if (exported && candidate !== original && file !== candidate) {
    try { await fsp.unlink(candidate); }
    catch (e) { warning = [warning, `Local compressed copy kept: ${e.message}`].filter(Boolean).join('. '); }
  }
  return { file, exported, originalFile: original, originalDeleted, warning };
}
module.exports = { DEFAULTS, preferences, fingerprint, ownedOriginal, publish, finish };
