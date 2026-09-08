// Image build gate, also runnable with --entrypoint node in a disposable image.
// No credentials, provider startup or network required. Never run hooks on host.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const runtime = '/opt/t3/runtime';
const require = createRequire(`${runtime}/package.json`);
const pins = require('./pins.json');
assert.equal(process.versions.node, pins.node_version);
assert.notEqual(process.getuid(), 0);
const manifest = require('t3/package.json');
assert.equal(manifest.version, pins.t3_version);
assert.equal(manifest.name, 't3');
assert.equal(manifest.bin.t3.replace(/^\.\//, ''), 'dist/bin.mjs');
const bin = `${runtime}/node_modules/.bin/t3`;
assert.equal(fs.realpathSync(bin), `${runtime}/node_modules/t3/dist/bin.mjs`);
fs.accessSync(bin, fs.constants.X_OK);
assert.throws(() => fs.accessSync(bin, fs.constants.W_OK));
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 't3-native-'));
try {
  const env = { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: scratch, XDG_CACHE_HOME: scratch };
  const cli = (...args) => execFileSync(bin, args, { env, encoding: 'utf8', timeout: 20000, stdio: ['ignore', 'pipe', 'pipe'] });
  assert.match(cli('--version'), new RegExp(`\\b${pins.t3_version.replaceAll('.', '\\.')}\\b`));
  const help = cli('serve', '--help');
  for (const option of ['--host', '--port', '--base-dir']) assert.ok(help.includes(option), option);
  assert.match(cli('auth', '--help'), /pairing/);
  const db = new DatabaseSync(path.join(scratch, 'state.sqlite'));
  assert.equal(db.prepare('SELECT 42 AS value').get().value, 42);
  db.close();
  const extract = require('msgpackr-extract');
  assert.equal(typeof extract.extractStrings, 'function');
  const { pack, unpack } = require('msgpackr');
  assert.deepEqual(unpack(pack({ text: 'native smoke' })), { text: 'native smoke' });
  const pty = require('node-pty');
  await new Promise((resolve, reject) => {
    const term = pty.spawn('/bin/sh', ['-c', 'printf t3-pty-ok'], { cwd: scratch, env });
    let output = '';
    const timer = setTimeout(() => { term.kill(); reject(new Error('PTY timeout')); }, 10000);
    term.onData((data) => { output += data; });
    term.onExit(({ exitCode }) => {
      clearTimeout(timer);
      try { assert.equal(exitCode, 0); assert.match(output, /t3-pty-ok/); resolve(); } catch (error) { reject(error); }
    });
  });
  // This package exports only the import condition, so require.resolve(package)
  // is deliberately not used for this ESM-only API.
  const { FileFinder, closeLibrary } = await import(pathToFileURL(`${runtime}/node_modules/@ff-labs/fff-node/dist/src/index.js`));
  fs.writeFileSync(path.join(scratch, 't3-native-marker.txt'), 'native-search-marker');
  FileFinder.ensureLoaded();
  const result = FileFinder.create({ basePath: scratch, frecencyDbPath: path.join(scratch, 'frecency'),
    historyDbPath: path.join(scratch, 'history'), logFilePath: path.join(scratch, 'fff.log'), disableWatch: true });
  assert.ok(result.ok, 'FFF create failed');
  try {
    const scan = await result.value.waitForScan(10000);
    assert.ok(scan.ok && scan.value, 'FFF scan failed');
    const search = result.value.fileSearch('t3-native-marker');
    assert.ok(search.ok && search.value.items.some((item) => item.relativePath === 't3-native-marker.txt'), 'FFF search failed');
  } finally { result.value.destroy(); closeLibrary(); }
} finally {
  fs.rmSync(scratch, { recursive: true, force: true });
}
console.log('Exact Node/T3 CLI, SQLite, native msgpackr, PTY and FFF search passed (no provider).');
