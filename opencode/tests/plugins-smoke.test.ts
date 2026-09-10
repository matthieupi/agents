import { test, expect } from 'bun:test'
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { publishPlugins } from '../scripts/publish-plugins.mjs'
import background from '../.opencode/config/plugins/kdco-background-agents'
import worktree from '../.opencode/config/plugins/kdco-worktree'
import notify from '../.opencode/config/plugins/kdco-notify'

const { DelegationManager } = background.testInternals
const log = { debug: async () => {}, info: async () => {}, warn: async () => {}, error: async () => {} }
const client = { session: { get: async ({ path }) => ({ data: { id: path.id } }) }, app: { log: async () => {} } }

async function fixture(run) {
  const root = await mkdtemp(join(tmpdir(), 'kdco-security-'))
  try {
    const storage = join(root, 'delegations')
    await mkdir(join(storage, 'session-a'), { recursive: true })
    await mkdir(join(storage, 'session-b'))
    const manager = new DelegationManager(client, storage, log)
    await run({ root, storage, manager })
  } finally { await rm(root, { recursive: true, force: true }) }
}

test('valid persisted result remains readable and missing ID reports not found', async () => {
  await fixture(async ({ storage, manager }) => {
    await writeFile(join(storage, 'session-a/bright-blue-cat.md'), 'expected result')
    expect(await manager.readOutput('session-a', ' bright-blue-cat ')).toBe('expected result')
    await expect(manager.readOutput('session-a', 'missing')).rejects.toThrow('not found')
  })
})

test('reject traversal, absolute paths, separators, NUL, invalid and overlong IDs', async () => {
  await fixture(async ({ manager }) => {
    for (const id of ['../session-b/result', '../../private', '/tmp/private', 'a/b', 'a\\b', '.', '', 'a\0b', 'x'.repeat(129)]) {
      await expect(manager.readOutput('session-a', id)).rejects.toThrow('Invalid')
    }
    await expect(manager.readOutput('../session-b', 'result')).rejects.toThrow('Invalid')
  })
})

test('reject symlinked artifacts including links into another session', async () => {
  await fixture(async ({ storage, manager }) => {
    await writeFile(join(storage, 'session-b/result.md'), 'other session')
    await symlink(join(storage, 'session-b/result.md'), join(storage, 'session-a/result.md'))
    await expect(manager.readOutput('session-a', 'result')).rejects.toThrow('Symlinked')
  })
})

test('reject symlinked session directories and storage escapes', async () => {
  await fixture(async ({ root, storage, manager }) => {
    await writeFile(join(root, 'private.md'), 'private')
    await rm(join(storage, 'session-a'), { recursive: true })
    await symlink(root, join(storage, 'session-a'))
    await expect(manager.readOutput('session-a', 'private')).rejects.toThrow('Symlinked')
    await expect(manager.readPersistedArtifact(join(root, 'private.md'))).rejects.toThrow('escaped')
  })
})

test('reject dangling artifact symlinks rather than treating them as absent', async () => {
  await fixture(async ({ root, storage, manager }) => {
    await symlink(join(root, 'absent.md'), join(storage, 'session-a/result.md'))
    await expect(manager.readOutput('session-a', 'result')).rejects.toThrow('Symlinked')
  })
})

test('reject non-regular artifacts', async () => {
  await fixture(async ({ storage, manager }) => {
    await mkdir(join(storage, 'session-a/directory.md'))
    await expect(manager.readOutput('session-a', 'directory')).rejects.toThrow('Regular')
  })
})

test('all factories initialize in disposable HOME without commands, notifications or providers', async () => {
  const root = await mkdtemp(join(tmpdir(), 'kdco-init-'))
  const previousHome = process.env.HOME
  const spawn = Bun.spawn, spawnSync = Bun.spawnSync
  const forbidden = () => { throw new Error('External command forbidden during smoke') }
  try {
    process.env.HOME = root
    Bun.spawn = forbidden as any
    Bun.spawnSync = forbidden as any
    await mkdir(join(root, '.config/opencode'), { recursive: true })
    await writeFile(join(root, '.config/opencode/kdco-notify.json'), JSON.stringify({ terminal: 'smoke' }))
    const config = join(root, '.config/opencode')
    await publishPlugins(fileURLToPath(new URL('../.opencode/config/', import.meta.url)), config)
    for (const pattern of ['{plugin,plugins}/*.{ts,js}', '{plugin,plugins}/**/*.{ts,js}']) {
      const discovered = await Array.fromAsync(new Bun.Glob(pattern).scan({ cwd: config, absolute: true, followSymlinks: true }))
      expect(discovered.length).toBe(3)
      for (const file of discovered) {
        const mod = await import(pathToFileURL(file).href)
        expect(Object.keys(mod)).toEqual(['default'])
        expect(typeof mod.default).toBe('function')
      }
    }
    const ctx = { directory: root, client } as any
    const bg = await background(ctx)
    const wt = await worktree(ctx)
    const nt = await notify(ctx)
    expect(Object.keys(bg.tool!).sort()).toEqual(['delegate', 'delegation_list', 'delegation_read'])
    expect(Object.keys(wt.tool!).sort()).toEqual(['worktree_create', 'worktree_delete'])
    expect(typeof nt.event).toBe('function')
    expect(typeof nt['tool.execute.before']).toBe('function')
    // No event/tool hooks are invoked. SQLite cleanup is local to this process.
  } finally {
    Bun.spawn = spawn; Bun.spawnSync = spawnSync
    if (previousHome === undefined) delete process.env.HOME
    else process.env.HOME = previousHome
    await rm(root, { recursive: true, force: true })
  }
})
