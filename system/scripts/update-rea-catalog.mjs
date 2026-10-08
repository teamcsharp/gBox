// Regenerate the complete pinned catalog from an installed upstream npm artifact.
// node scripts/update-rea-catalog.mjs <runtime>/rea/node_modules/rea-agents
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { gzipSync } from 'node:zlib';
const root = path.resolve(process.argv[2]);
const require = createRequire(path.join(root, 'package.json'));
const { z } = await import(pathToFileURL(require.resolve('zod')));
const { TOOL_CONTRACTS } = await import(pathToFileURL(path.join(root, 'dist/contracts/toolContracts.js')));
const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'))).version;
if (version !== '6.0.0') throw new Error('Update the gBox runtime pin and tests before changing the catalog version.');
const tools = TOOL_CONTRACTS.map(t => ({
  name: t.name, title: t.title, description: t.description,
  inputSchema: { ...z.toJSONSchema(t.inputSchema, { io: 'input', unrepresentable: 'any' }), type: 'object' },
  outputSchema: z.toJSONSchema(t.outputSchema, { unrepresentable: 'any' }),
  effects: t.effects, annotations: t.annotations, kind: t.kind, examples: t.examples,
}));
fs.writeFileSync(new URL('../gbox/rea_catalog.json.gz', import.meta.url), gzipSync(JSON.stringify({ version, tools })));
fs.copyFileSync(path.join(root, 'LICENSE'), new URL('../gbox/REA-LICENSE', import.meta.url));
fs.copyFileSync(path.join(root, 'LICENSE'), new URL('../docs/REA-LICENSE', import.meta.url));
console.log(`REA ${version}: ${tools.length} tools exported`);
