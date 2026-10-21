# Method Signature Surface

📍 Native integration is in the pinned PiWeb source represented by `pi-web.patch`.
`getRpcSession(sessionId)` and `wrapper.inner.sessionManager.getBranch()` are
existing APIs, not new interfaces. All HTTP handler parameter signatures and
`AgentSessionWrapper.send(command: Record<string, unknown>): Promise<unknown>`
are unchanged. The existing session-state response adds `projectMode: "local" | "remote"`.

## SDK structural declarations (actual 0.85.1 types)

```ts
// lib/pi-types.ts — ExtensionRunnerLike
+ emitUserBash?(event: UserBashEvent): Promise<UserBashEventResult | undefined>;
+ onError?(handler: (error: ExtensionError) => void): () => void;

// AgentSessionLike; BashResult derived from SDK recordBashResult parameter type
+ recordBashResult(command: string, result: BashResult,
    options?: { excludeFromContext?: boolean }): void;
```

## Session adapter and browser context

```ts
// lib/session-project-mode.ts
+ sessionProjectMode(sessionId: string): Promise<"local" | "remote">;
+ rejectRemoteProjectRequest(request: Request): Promise<Response | undefined>;

// lib/project-request.ts
+ projectRequestUrl(path: string, sessionId: string | null): string;

// components/ProjectMode.tsx
+ ProjectModeProvider(props: { sessionId: string | null; children: ReactNode }): ReactNode;
+ useProjectMode(): { sessionId: string | null; local: boolean; url(path: string): string };
+ LocalOnly(props: { children: ReactNode }): ReactNode;
// Provider effect-local callback
+ refresh(): Promise<void>;
```

## Existing request helpers

```ts
// components/FileExplorer.tsx
- fetchEntries(dirPath: string): Promise<FileNode[]>;
+ fetchEntries(dirPath: string, sessionId: string | null): Promise<FileNode[]>;
- fetchGitStatus(cwd: string): Promise<GitStatusResponse>;
+ fetchGitStatus(cwd: string, sessionId: string | null): Promise<GitStatusResponse>;
- uploadFiles(targetDirectory: string, files: File[], strategy: UploadConflictStrategy,
    onProgress: (progress: number) => void): Promise<{ status: number; data: UploadResponse }>;
+ uploadFiles(targetDirectory: string, files: File[], strategy: UploadConflictStrategy,
    onProgress: (progress: number) => void, sessionId: string | null): Promise<{ status: number; data: UploadResponse }>;

// lib/terminal-client.ts — returned writer interface unchanged
- createTerminalWriter(id: string, onError: (error: Error) => void);
+ createTerminalWriter(id: string, onError: (error: Error) => void, sessionId: string | null = null);
```

## Canonical copied helper — no source/interface changes in this lane

```ts
remoteProjectMode(entries: readonly unknown[]): 'local' | 'remote';
requireLocalProjectExecution(ctx: any, operation: string): void;
```

## Build/test utilities

```python
# fetch.py
+ extract(data, dest)
# apply.py
+ apply(source: Path)
# build.py
+ run(*args)
# provenance.py
+ record(source: Path)
```

```js
// test.mjs (Node test callbacks omitted; no application exports)
+ async function setup(t, handler)
// test-package.mjs
+ function session(data)
+ install(archive)
+ request(path, options = {})
```
