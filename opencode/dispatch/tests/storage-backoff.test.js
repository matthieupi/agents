import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import { storageFixture } from './storage-fixture.js';

test('failed pre-poll persistence does not retry writes every second', async t => {
  const f = await storageFixture(t); await f.task();
  let attempts = 0;
  f.runtime.open = async (...args) => {
    attempts++; const fd = await fs.open(...args);
    return { writeFile: async () => { throw Object.assign(Error('disk full'), { code: 'ENOSPC' }); }, sync: () => fd.sync(), close: () => fd.close() };
  };
  f.advance(5000); await f.dispatch.poll(); assert.equal(attempts, 1);
  for (let i = 0; i < 4; i++) { f.advance(1000); await f.dispatch.poll(); }
  assert.equal(attempts, 1);
  f.advance(1000); await f.dispatch.poll(); assert.equal(attempts, 2);
  for (let i = 0; i < 9; i++) { f.advance(1000); await f.dispatch.poll(); }
  assert.equal(attempts, 2);
  assert.equal(f.calls.filter(c => !c.body).length, 0);
});

test('directory-scan failure backs off even when the filesystem recovers on the next one-second tick', async t => {
  const f = await storageFixture(t); await f.task(); f.advance(5000);
  await fs.chmod(f.options.stateDirectory, 0o755);
  await assert.rejects(f.dispatch.poll());
  await fs.chmod(f.options.stateDirectory, 0o700);
  const before = f.calls.length;
  f.advance(1000); await f.dispatch.poll(); assert.equal(f.calls.length, before);
  f.advance(4000); await f.dispatch.poll(); assert.equal(f.calls.length, before + 1);
});
