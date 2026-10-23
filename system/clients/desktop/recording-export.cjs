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
    let handle;
    for (let attempt = 0; attempt < 5; attempt++) {
      const parsed = path.parse(basename);
      final = path.join(directory, attempt ? `${parsed.name}-${crypto.randomUUID()}${parsed.ext}` : basename);
      // CopyFile propagates the hidden attribute of our dot-prefixed staging
      // file on Windows/SMB. Create the visible destination independently.
      try { handle = await fsp.open(final, 'wx'); created = true; break; }
      catch (e) { if (e.code !== 'EEXIST') throw e; }
    }
    if (!created) throw Error('Could not reserve a unique export filename');
    try {
      for await (const chunk of fs.createReadStream(stage)) {
        let offset = 0;
        while (offset < chunk.length) {
          const { bytesWritten } = await handle.write(chunk, offset, chunk.length - offset);
          if (!bytesWritten) throw Error('The export destination stopped accepting data');
          offset += bytesWritten;
        }
      }
      await handle.sync();
    } finally { await handle.close(); }
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

// Replay artifacts already fit their requested size. Download once, verify the
// content-addressed bytes, and publish through the same per-instance export policy.
async function saveReplay({ clip, directory, exportDir, fetchArtifact }) {
  if (!/^[a-f0-9]{64}$/.test(clip?.sha256 || '') || !Number.isSafeInteger(clip.bytes) || clip.bytes <= 0 || clip.bytes > 256 * 1048576)
    throw Error('Invalid or oversized replay clip');
  const folder = preferences({ exportDir }).exportDir || directory;
  const name = String(clip.name || `replay-${clip.sha256.slice(0, 12)}.mp4`);
  if (name.length > 180 || !/\.mp4$/i.test(name) || /[<>:"/\\|?*\x00-\x1f]/.test(name) || name.startsWith('.'))
    throw Error('Invalid replay filename');
  await fsp.mkdir(directory, { recursive: true });
  const local = path.join(directory, `.gbox-replay-${crypto.randomUUID()}.mp4`);
  let verified = false;
  try {
    const response = await fetchArtifact(clip.sha256);
    if (!response.ok || !response.body) throw Error(`Replay download failed (${response.status})`);
    const hash = crypto.createHash('sha256'); let bytes = 0;
    // Open before starting the pipeline. A rejected input can otherwise race
    // createWriteStream's asynchronous open: cleanup sees no file, then the
    // pending open creates an invalid replay after cleanup has returned.
    const handle = await fsp.open(local, 'wx');
    try {
      await require('node:stream/promises').pipeline(require('node:stream').Readable.from(response.body), async function* (chunks) {
        for await (const chunk of chunks) {
          bytes += chunk.length;
          if (bytes > clip.bytes) throw Error('Replay download exceeded its expected size');
          hash.update(chunk); yield chunk;
        }
      }, handle.createWriteStream());
    } finally { await handle.close(); }
    if (bytes !== clip.bytes || hash.digest('hex') !== clip.sha256) throw Error('Replay download did not verify');
    verified = true;
    let file;
    try { file = await publish(local, folder, name); }
    catch (e) { throw Error(`Export failed: ${e.message}. Clip retained locally at ${local}; the Spark artifact is also retained`); }
    verified = false;
    return { file, bytes, sha256: clip.sha256, exported: !!exportDir };
  } finally {
    if (!verified) await fsp.unlink(local).catch(() => {});
  }
}
module.exports = { DEFAULTS, preferences, fingerprint, ownedOriginal, publish, finish, saveReplay };
