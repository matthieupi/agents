import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDispatch } from '../core.js';

test('peer descriptions cannot be empty or whitespace only', () => {
  for (const description of ['', '   ']) {
    assert.throws(() => createDispatch({ enabled: true, stateDirectory: '/private/state', peers: [{ alias: 'worker', description, url: 'https://worker.invalid', username: 'opencode', passwordFile: '/private/password' }] }));
  }
});

test('peer descriptions are trimmed before advertising them', () => {
  const dispatch = createDispatch({ enabled: true, stateDirectory: '/private/state', peers: [{ alias: 'worker', description: '  Worker  ', url: 'https://worker.invalid', username: 'opencode', passwordFile: '/private/password' }] });
  assert.equal(dispatch.catalog[0].description, 'Worker');
});
