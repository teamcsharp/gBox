'use strict';
const { renderSVG } = require('../clients/web/viz/tactical-map.js');
const LIMIT = 5 * 1024 * 1024;
const chunks = [];
let size = 0;
process.stdin.on('data', chunk => {
  size += chunk.length;
  if (size > LIMIT) { process.stderr.write('Tactical input exceeds limit\n'); process.exit(1); }
  chunks.push(chunk);
});
process.stdin.on('end', () => {
  try {
    const svg = renderSVG(JSON.parse(Buffer.concat(chunks).toString('utf8')));
    if (Buffer.byteLength(svg, 'utf8') > 4 * 1024 * 1024) throw Error('Tactical output exceeds limit');
    process.stdout.write(svg);
  } catch (error) { process.stderr.write(String(error.message).slice(0, 300) + '\n'); process.exitCode = 1; }
});
