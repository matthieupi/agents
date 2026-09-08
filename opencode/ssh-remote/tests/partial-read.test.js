import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import plugin from '../index.js';
import { fixture } from './fixture.js';

test('a line-clipped read invalidates a cached write-result hash before write or delete', async t => {
  const f = await fixture(t);
  const h = await plugin(f.input, f.options);
  const call = (op, args) => h.tool[op].execute(args, f.ctx());
  // Writing a new file establishes a full-result hash in this session.
  await call('write', { filePath: 'cached', content: 'line\n'.repeat(1100) });
  const read = await call('read', { filePath: 'cached' });
  assert.equal(read.metadata.truncated, true);
  await assert.rejects(call('write', { filePath: 'cached', content: 'lost content' }), /conflict|read required/);
  await assert.rejects(call('apply_patch', { patchText: '*** Begin Patch\n*** Delete File: cached\n*** End Patch' }), /conflict|read required/);
});

test('partial reads invalidate prior full hashes; write/edit/delete require a new full read', async t => {
  const f = await fixture(t);
  const h = await plugin(f.input, f.options);
  const call = (op, args) => h.tool[op].execute(args, f.ctx());
  const content = 'first\nsecond\nthird\n';
  for (const range of [{ limit: 1 }, { offset: 2 }, { offset: 2, limit: 1 }, { offset: 100 }]) {
    await writeFile(path.join(f.target.cwd, 'small'), content);
    const full = await call('read', { filePath: 'small' });
    assert.equal(full.metadata.truncated, false);
    assert.equal(full.output, content);
    const partial = await call('read', { filePath: 'small', ...range });
    assert.equal(partial.metadata.truncated, true);
    await assert.rejects(call('write', { filePath: 'small', content: 'lost' }), /conflict|read required/);
    await assert.rejects(call('edit', { filePath: 'small', oldString: 'first', newString: 'lost' }), /conflict|read required/);
    const deletion = { patchText: '*** Begin Patch\n*** Delete File: small\n*** End Patch' };
    await assert.rejects(call('apply_patch', deletion), /conflict|read required/);
    assert.equal((await call('read', { filePath: 'small', offset: 1, limit: 3 })).metadata.truncated, false);
    await call('write', { filePath: 'small', content });
    await call('apply_patch', deletion);
  }
});
