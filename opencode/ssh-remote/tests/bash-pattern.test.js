import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import plugin from '../index.js';
import { fixture } from './fixture.js';

test('Bash permission identity cannot collide between colon cwd and command prefix', async t => {
  const f = await fixture(t);
  const colonCwd = f.target.cwd + ':part';
  await mkdir(colonCwd);
  const getPattern = async (target, command) => {
    await f.save([target]);
    const h = await plugin(f.input, f.options);
    let pattern;
    await assert.rejects(h.tool.bash.execute({ command }, f.ctx('s', async request => {
      pattern = request.patterns[0];
      throw new Error('fixture permission stop');
    })), /fixture permission stop/);
    return pattern;
  };
  const a = await getPattern({ ...f.target, cwd: colonCwd }, 'command');
  const b = await getPattern(f.target, 'part:command');
  assert.notEqual(a, b, 'different cwd/command pairs must not have the same permission pattern');
  assert.equal(a, `${f.target.ref}:${encodeURIComponent(colonCwd)}:command`);
  assert.equal(f.connections(), 0);
});

test('Bash encodes canonical workdir only; command suffix stays opaque and file patterns stay unchanged', async t => {
  const f = await fixture(t);
  const h = await plugin(f.input, f.options);
  const command = 'printf "a:b:%3A"';
  let request;
  const ctx = f.ctx('s', async value => { request = value; throw Error('permission stop'); });
  await assert.rejects(h.tool.bash.execute({ workdir: './child:dir/../child:dir', command }, ctx), /permission stop/);
  assert.equal(request.patterns[0], `${f.target.ref}:${encodeURIComponent(f.target.cwd + '/child:dir')}:${command}`);
  assert.deepEqual(request.always, []);
  assert.equal(request.metadata.args.command, command);
  await assert.rejects(h.tool.read.execute({ filePath: 'file:with:colons' }, ctx), /permission stop/);
  assert.equal(request.patterns[0], `${f.target.ref}:${f.target.cwd}/file:with:colons`);
  for (const ref of ['fake/project', 'fake:project', 'Fake.project', 'fake.project.extra', 'fake.*']) {
    const locked = await plugin(f.input, { ...f.options, project: ref });
    await assert.rejects(locked['tool.definition']({ toolID: 'bash' }, {}), /lockdown/);
  }
  assert.equal(f.connections(), 0);
});
