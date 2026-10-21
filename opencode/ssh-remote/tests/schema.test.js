import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';

const example = async name => JSON.parse(await readFile(new URL('../examples/' + name, import.meta.url), 'utf8'));

test('explicit profiles use tuple options, safe fake catalog and no implicit activation', async () => {
  const remote = await example('remote.config.json');
  const disabled = await example('disabled.config.json');
  const catalog = await example('catalog.fake.json');
  for (const config of [remote, disabled]) {
    assert.equal(config.$schema, 'https://opencode.ai/config.json');
    assert.equal(config.plugin[0].length, 2);
    assert.match(config.plugin[0][0], /^file:\/\/\//);
    assert.equal(typeof config.plugin[0][1], 'object');
  }
  assert.equal(remote.plugin[0][1].project, catalog.projects[0].ref);
  assert.equal(disabled.plugin[0][1].enabled, false);
  assert.match(catalog.projects[0].address, /\.invalid$/);
  assert.match(catalog.projects[0].host_key_sha256, /^[0-9a-f]{64}$/);
});

test('examples validate against the live official JSON schema', {
  skip: process.env.VERIFY_PUBLIC_SCHEMA !== '1' && 'Opt-in public schema fetch; npm run test:schema',
}, async () => {
  const response = await fetch('https://opencode.ai/config.json');
  assert.equal(response.ok, true);
  const schema = await response.json();
  const examples = await Promise.all(['remote.config.json', 'disabled.config.json'].map(example));
  // Existing controller jsonschema, not an installed package/global dependency.
  const result = spawnSync('python3', ['-c', 'import json,sys,jsonschema\nx=json.load(sys.stdin)\nfor example in x["examples"]: jsonschema.Draft202012Validator(x["schema"]).validate(example)'], {
    input: JSON.stringify({ schema, examples }), encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr || String(result.error || ''));
});
