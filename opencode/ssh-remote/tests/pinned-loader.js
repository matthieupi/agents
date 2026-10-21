import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { Effect } from 'effect';

export const commit = '16747470f976aca3d362ad730bcd3fe82ecc2c9a';
export const excerpts = [
  ['loader-functions-1.18.29.txt', 'index.ts'],
  ['loader-catch-1.18.29.txt', 'index.ts'],
  ['loader-detect-1.18.29.txt', 'shared.ts'],
];
export const excerpt = async name => (await readFile(new URL('./fixtures/' + name, import.meta.url), 'utf8')).trimEnd();

// Execute actual pinned applyPlugin + Effect catch loop, not a rewritten try/catch.
// Node's built-in type erasure only; no tsc/Bun/framework install. External package
// resolution and the instance/server bootstrap are deliberately outside this fixture.
export async function load(factory, input, options) {
  const [functions, loop, detect] = await Promise.all(excerpts.map(([name]) => excerpt(name)));
  const body = stripTypeScriptTypes(functions + '\n' + detect.replace('export function', 'function'));
  const run = new Function('Effect', 'isRecord', 'errorMessage', 'loaded', 'input', `${body}
    return Effect.runPromise(Effect.gen(function* () {
      const hooks = [];
      ${loop}
      return hooks;
    }));`);
  return run(Effect, value => value !== null && typeof value === 'object' && !Array.isArray(value),
    error => error instanceof Error ? error.message : String(error),
    [{ mod: { default: factory }, spec: 'file:///fixture/plugin.js', source: 'file', options }], input);
}
