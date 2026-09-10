import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import { storageFixture } from './storage-fixture.js';

for (const stage of ['writeFile', 'sync', 'close']) {
  test(`temporary result file is removed after ${stage} failure without replacing committed JSON`, async t => {
    const f = await storageFixture(t), task = await f.task(); f.complete();
    // Establish a committed inbox before injecting a failure in a subsequent result write.
    await f.run('result', { handle: task.handle });
    await f.run('reply', { handle: task.handle, prompt: 'Next' }); f.complete('Second private result');
    const previous = await fs.readFile(f.boxFile, 'utf8');
    let failures = 0;
    f.runtime.open = async (...args) => {
      const fd = await fs.open(...args);
      return {
        writeFile: async text => { await fd.writeFile(text); if (stage === 'writeFile') { failures++; throw Object.assign(Error('disk failure'), { code: 'EIO' }); } },
        sync: async () => { if (stage === 'sync') { failures++; throw Object.assign(Error('disk failure'), { code: 'EIO' }); } await fd.sync(); },
        close: async () => { await fd.close(); if (stage === 'close') { failures++; throw Object.assign(Error('disk failure'), { code: 'EIO' }); } },
      };
    };
    for (let i = 0; i < 3; i++) {
      const result = await f.run('result', { handle: task.handle });
      assert.equal(result.state, 'completed'); assert.equal(result.text, 'Second private result');
      assert.ok(result.cacheWarning);
    }
    assert.ok(failures >= 3);
    assert.equal(await fs.readFile(f.boxFile, 'utf8'), previous);
    assert.deepEqual((await fs.readdir(f.options.stateDirectory)).filter(n => n.startsWith('.')), []);
  });
}
