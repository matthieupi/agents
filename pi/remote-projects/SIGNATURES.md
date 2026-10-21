# Method Signature Surface

📍 All production changes apply to published `pi-ssh-remote@0.1.12/index.ts`
plus the adjacent helper. `+` means added, `-` removed/replaced. Existing callable
bodies changed without signature changes are listed separately. No transport API
was extracted or replaced. Full behavioral contract and installation gates are in
`README.md`.

## Catalog helper — added

```ts
+ interface ProjectEntry
+ const text: (value: unknown) => value is string
+ const canonicalPath: (value: string) => boolean
+ function loadProjectCatalog(path: string): ProjectEntry[]

+ class ManagedProjects
  + constructor(path: string)
  + begin(ref?: string): void
  + select(ref: string): ProjectEntry
  + current(): ProjectEntry
  + local(): void
```

## Upstream factory — new private callables

```ts
+ const bindContext: (ctx: any) => void
+ const closeManaged: () => void
+ const saveManaged: () => void
+ const managedExclusive: <T>(work: () => Promise<T>) => Promise<T>
+ const requireManaged: () => RemoteState
+ const projectSftp: <T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>) => Promise<T>
+ const connectProject: (ref: string, ctx: any) => Promise<RemoteState>
+ const managedControl: (params: any, ctx: any) => Promise<{
    content: { type: "text"; text: string }[]; details: {};
  }>
+ const runTool: (ctx: any, remoteWork: () => Promise<any>, localWork: () => Promise<any>) => Promise<any>
```

## Tool override callback signatures — context added

The types below describe the SDK callback positions; source inference uses the
existing upstream tool schemas. No input parameter schema was copied/replaced.

```ts
read/write/edit/bash
  - execute(id, params, signal, update): Promise<AgentToolResult>
  + execute(id, params, signal, update, ctx): Promise<AgentToolResult>

remote parameters (additive field)
  + projectRef?: string
```

## SFTP acquisition boundary — optional synchronous dispatch guard

```ts
- async function withSftp<T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>): Promise<T>
+ async function withSftp<T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>, guard?: () => void): Promise<T>
```

## New hook

```ts
+ tool_call(event: ToolCallEvent): { block: true; reason: string } | undefined
```

## Existing signatures unchanged; bodies updated

```ts
export default function sshRemoteExtension(pi: ExtensionAPI)
const status: (ctx: any) => void
const attachClient: (state: RemoteState) => void
const establish: (parsed: ParsedSsh, authentication: SshAuthentication, cwd: string) => Promise<RemoteState>
function reconnectRemote(): Promise<RemoteState>
const withReconnect: <T>(operation: (client: SshClient) => Promise<T>) => Promise<T>
const changeRemoteCwd: (requested: string, ctx: any) => Promise<string>
const connectInteractive: (command: string, ctx: any, cwd?: string) => Promise<RemoteState | null>
const ensureConnected: (ctx: any) => Promise<RemoteState>
const targetsLocalServerMemory: (path: unknown) => boolean
const remoteBashOps: () => BashOperations
const remoteReadOps: () => ReadOperations
const remoteWriteOps: () => WriteOperations
const executeRemoteRead: (id: string, params: any, signal: AbortSignal | undefined, update: any) => Promise<any>

remote.execute(_id, params, _signal, _update, ctx): Promise<AgentToolResult>
remote.handler(args: string, ctx: ExtensionCommandContext): Promise<void>
session_start(event: SessionStartEvent, ctx: ExtensionContext): Promise<void>
session_shutdown(event: SessionShutdownEvent): Promise<void>
user_bash(event: UserBashEvent, ctx: ExtensionContext): Promise<UserBashEventResult | undefined>
before_agent_start(event: BeforeAgentStartEvent): BeforeAgentStartEventResult | undefined
context(event: ContextEvent): ContextEventResult | undefined
```

## Source patch / fixture / verification tooling — added

```python
# apply-upstream.py
+ def patched(source)
  + def replace(old, new)

# fixture.py
+ def prepare_scratch()
+ def fetch_fixture()

# verify.py
+ def verify()
  + def diagnostics(file)
```

## Test helpers and fakes — added

```js
+ project(suffix = "a", extra = {})
+ harness(managed = true)
  + load(file)
  + session(branch = [], cwd = "/same/local/control")
  + catalog(entries)

+ class Client extends EventEmitter
  + connect(options)
  + end()
  + exec(command, callback)
  + sftp(callback)

+ async blocked(session, state)

// SDK registration/session stub callbacks
+ registerTool(tool)
+ registerCommand(name, command)
+ on(name, callback)
+ appendEntry(customType, data)
+ choose(value)
+ start(reason = "startup")
+ shutdown(reason = "reload")
+ call(name, params = {})
+ command(input = "")
+ bash()

// Fake filesystem/key/SFTP boundary callbacks
+ readFileSync(file, encoding)
+ statSync(file)
+ mkdirSync(...args)
+ writeFileSync(...args)
+ parseKey(data)
+ stat(file, done)
+ readFile(file, done)
+ writeFile(file, contents, done)
```

## Verification tooling follow-up

```js
// test-paths.mjs: validated, allowlisted scratch path export; no callables.
+ const fixture: string

// test-sdk-smoke.mjs
+ denyNetwork(): never
+ async makeSession()
```

`prepare_scratch()` validates the known scratch directory/marker and output file
ownership/aliases. `fetch_fixture()` and `verify()` retain their signatures;
verification now includes path rejection, dependency pins and the real SDK smoke.

The P1 revision adds `ManagedProjects.begin()` and `projectSftp()`, and updates
`withSftp()` as listed above. `select()`, `managedControl()`, lifecycle/selector
callbacks and test `Client.sftp()` keep their signatures with corrected behavior.
Fresh intent is Local; explicit remote attempts/malformed remote records are
blocked until valid selection or an explicit user Local choice.
