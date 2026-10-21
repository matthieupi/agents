"""Exact-version source patch. No dependency installation or deployment.

Usage: python3 apply-upstream.py /isolated/package-directory [--check]
Every replacement is unique and the entire before/after source is SHA256 pinned.
The adjacent managed-projects.ts must be copied alongside the resulting index.ts.
"""
import difflib
import hashlib
import pathlib
import sys

BEFORE = '051f7addcdd00f690fab61cc8fb70b22c85114223b892be9df2480ddcdd42a87'
AFTER = 'c59152d32ca0746d5ac562e64e61f511e0dc39297cb3a573459168b0bfa81105'
HELPER = '55be75cd1690e31889dfcdae97b2f49d4679eec37fc7eb3c68e7eb63fc115d38'


def patched(source):
    if hashlib.sha256(source.encode()).hexdigest() != BEFORE:
        raise ValueError('Not published pi-ssh-remote 0.1.12; refusing to patch')

    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError(f'Patch context mismatch: {old[:100]}')
        source = source.replace(old, new)

    replace('const { Client, utils: ssh2Utils } = ssh2;',
            'import { loadProjectCatalog, ManagedProjects } from "./managed-projects.js";\n\nconst { Client, utils: ssh2Utils } = ssh2;')
    replace('''async function withSftp<T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>): Promise<T> {
  const sftp = await getSftp(client);
  try { return await operation(sftp); }''', '''async function withSftp<T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>, guard?: () => void): Promise<T> {
  const sftp = await getSftp(client);
  try { guard?.(); return await operation(sftp); }''')
    # All four factory SFTP dispatch sites share the same post-acquisition gate.
    for dispatch in ['sftp.readFile(mapPath(path)', 'sftp.stat(mapPath(path)', 'sftp.stat(path', 'sftp.writeFile(mapPath(path)']:
        lines = source.splitlines(True)
        index = next(i for i, line in enumerate(lines) if dispatch in line)
        replace(lines[index - 1] + lines[index], (lines[index - 1] + lines[index]).replace('withSftp(client,', 'projectSftp(client,'))
    replace('  migrateLegacyServerMemories();\n\n  const localCwd = process.cwd();', '''  const catalogPath = process.env.PI_PROJECT_CATALOG;
  const managed = catalogPath !== undefined ? new ManagedProjects(catalogPath) : undefined;
  if (!managed) migrateLegacyServerMemories();

  let localCwd = "/"; // Initialized from the SDK context, never process.cwd().''')
    replace('  let lastCommand = credentialCache.resume?.command ?? activeSshCommand() ?? "";',
            '  let lastCommand = managed ? "" : credentialCache.resume?.command ?? activeSshCommand() ?? "";')
    replace('  const configuredCwd = (command: string): string =>', '''  let managedBusy = false;
  let managedGeneration = 0;
  const managedEntry = "pi-ssh-remote-project";
  const bindContext = (ctx: any): void => { localCwd = ctx.cwd; currentCtx = ctx; };
  const closeManaged = (): void => {
    managedGeneration++;
    const previous = remote;
    remote = null;
    routeRemoteTools = false;
    previous?.client.end();
  };
  const saveManaged = (): void => {
    pi.appendEntry(managedEntry, { version: 1, projectRef: managed!.projectRef ?? null,
      local: !managed!.remoteIntent, workspace: remote?.cwd });
  };
  const managedExclusive = async <T>(work: () => Promise<T>): Promise<T> => {
    if (managedBusy) throw new Error("Managed project operation in progress; retry explicitly when idle");
    managedBusy = true;
    try { return await work(); } finally { managedBusy = false; }
  };
  const requireManaged = (): RemoteState => {
    managed!.current();
    if (!remote || !routeRemoteTools) throw new Error("Managed remote is not ready; explicitly reconnect or select a project");
    return remote;
  };
  const projectSftp = <T>(client: SshClient, operation: (sftp: SFTPWrapper) => Promise<T>): Promise<T> => {
    if (!managed) return withSftp(client, operation);
    const generation = managedGeneration;
    return withSftp(client, operation, () => {
      // No await between this gate and SFTP dispatch. current() checks the selected
      // catalog snapshot; generation/client checks prevent using a stale channel.
      if (generation !== managedGeneration || requireManaged().client !== client) {
        throw new Error("Managed connection changed during SFTP acquisition");
      }
    });
  };
  const connectProject = async (ref: string, ctx: any): Promise<RemoteState> => {
    closeManaged();
    let entry;
    try { entry = managed!.select(ref); } finally { saveManaged(); }
    const generation = managedGeneration;
    // Quote fields for the existing parser, not a local shell. Identity is exclusive.
    const parsed = parseSshCommand(`ssh -i ${quote(entry.identity_file)} -p ${entry.port} ${quote(`${entry.user}@${entry.address}`)}`);
    const keyData = readPrivateKey(parsed);
    const key = parsePrivateKey(keyData);
    if (key instanceof Error) throw new Error("Managed identity must be a usable dedicated, unencrypted private key");
    const next = await establish(parsed, { privateKey: keyData }, entry.cwd);
    try {
      managed!.current();
      if (generation !== managedGeneration) throw new Error("Managed selection changed during connection");
      remote = next;
      routeRemoteTools = true;
      status(ctx);
      saveManaged();
      return next;
    } catch (error) { if (remote === next) closeManaged(); else next.client.end(); throw error; }
  };
  const managedControl = async (params: any, ctx: any) => {
    bindContext(ctx);
    return managedExclusive(async () => {
      let text: string;
      if (params.action === "connect" || params.action === "reconnect") {
        const ref = params.projectRef ?? managed!.projectRef;
        closeManaged();
        managed!.begin(); // An accepted idle attempt is remote intent, even with bad input.
        saveManaged();
        status(ctx);
        if (params.command !== undefined || params.cwd !== undefined || params.forwards !== undefined) {
          throw new Error("Managed connect accepts only projectRef, not SSH commands/cwd/forwards");
        }
        if (typeof ref !== "string") throw new Error("Managed connect requires an exact projectRef");
        const state = await connectProject(ref, ctx);
        text = `Connected project ${managed!.projectRef}: ${state.cwd}`;
      } else if (params.action === "status") {
        if (managed!.remoteIntent) requireManaged();
        text = managed!.remoteIntent ? `Remote project ${managed!.projectRef}: ${remote!.cwd}` : "Local mode";
      } else if (params.action === "exec") {
        const state = requireManaged();
        if (params.cwd !== undefined) throw new Error("Managed cwd overrides are disabled; use cd within your remote command");
        if (!params.remoteCommand) throw new Error("remoteCommand is required for exec");
        const limits = configuredOutputLimits();
        const result = await withReconnect((client) => execRemoteLimited(client,
          `cd -- ${quote(state.cwd)} && ${params.remoteCommand}`,
          parseRemoteTimeout(params.timeout ?? DEFAULT_REMOTE_TIMEOUT_SECONDS), limits.execMaxLines, limits.execMaxBytes));
        text = result.text;
      } else {
        throw new Error("Managed mode permits connect/reconnect/status/exec only; only the USER /remote off or Local choice may enable local tools");
      }
      return { content: [{ type: "text" as const, text }], details: {} };
    });
  };
  const runTool = async (ctx: any, remoteWork: () => Promise<any>, localWork: () => Promise<any>) => {
    bindContext(ctx);
    if (!managed) return remoteWork(); // Caller retains upstream routing rules.
    if (!managed.remoteIntent) return localWork();
    return managedExclusive(async () => { requireManaged(); return remoteWork(); });
  };

  const configuredCwd = (command: string): string =>''')
    replace('    if (!remote) ctx.ui.setStatus("ssh-remote", undefined);', '''    if (managed) {
      ctx.ui.setStatus("ssh-remote", managed.remoteIntent
        ? `project ${managed.projectRef ?? "unselected"}: ${remote ? "remote" : "NOT READY"}` : "Local");
      return;
    }
    if (!remote) ctx.ui.setStatus("ssh-remote", undefined);''')
    replace('      void reconnectRemote().catch((error) => {', '''      if (managed) { closeManaged(); status(currentCtx); return; }
      void reconnectRemote().catch((error) => {''')
    replace('    const fingerprint = loadKnownHosts()[key];',
            '    const fingerprint = managed ? managed.current().host_key_sha256.toLowerCase() : loadKnownHosts()[key];')
    replace('''    const client = await connect(parsed, authentication, fingerprint);
    try {''', '''    const client = await connect(parsed, authentication, fingerprint);
    try {
      if (managed) managed.current(); // Policy may change during the SSH handshake.''')
    replace('      const state = { ...parsed, client, cwd: resolved };', '''      if (managed && resolved !== managed.current().cwd) throw new Error("Managed cwd is not the catalog canonical physical directory");
      const state = { ...parsed, client, cwd: resolved };''')
    replace('    if (reconnectPromise) return reconnectPromise;', '''    if (managed) throw new Error("Managed reconnect requires explicit project selection");
    if (reconnectPromise) return reconnectPromise;''')
    replace('    if (!remote) throw new Error("SSH remote is not connected");\n    try { return await operation(remote.client); }', '''    if (managed) {
      const state = requireManaged(); // Re-read policy before EVERY SSH/SFTP operation.
      // Never replay an operation with an unknown result, including mutations.
      return operation(state.client);
    }
    if (!remote) throw new Error("SSH remote is not connected");
    try { return await operation(remote.client); }''')
    replace('    if (!remote) throw new Error("SSH remote is not connected");\n    const target = requested.trim()', '''    if (managed) throw new Error("Managed workspace is fixed; use cd inside a remote bash command");
    if (!remote) throw new Error("SSH remote is not connected");
    const target = requested.trim()''')
    replace('    let parsed: ParsedSsh;\n    try { parsed = parseSshCommand(command); }', '''    if (managed) throw new Error("Use an authorized projectRef, not a saved SSH endpoint");
    let parsed: ParsedSsh;
    try { parsed = parseSshCommand(command); }''')
    replace('    if (remote) return remote;\n    if (credentialCache.resume)', '''    if (managed) return requireManaged();
    if (remote) return remote;
    if (credentialCache.resume)''')
    replace('    if (!remote || typeof path !== "string") return false;',
            '    if (managed || !remote || typeof path !== "string") return false;')
    replace('''        signal?.addEventListener("abort", abort, { once: true });
        stream.on("data", onData);''', '''        signal?.addEventListener("abort", abort, { once: true });
        if (managed) stream.once("error", (error: Error) => {
          clearTimeout(timer);
          signal?.removeEventListener("abort", abort);
          reject(error); // Unknown remote result: no replay, no local retry.
        });
        stream.on("data", onData);''')
    replace('''    execute: (id, params, signal, update) => remote && routeRemoteTools && !targetsLocalServerMemory(params.path)
      ? executeRemoteRead(id, params, signal, update)
      : localRead.execute(id, params, signal, update),''', '''    execute: (id, params, signal, update, ctx) => runTool(ctx, () => remote && routeRemoteTools && !targetsLocalServerMemory(params.path)
      ? executeRemoteRead(id, params, signal, update)
      : createReadTool(ctx.cwd).execute(id, params, signal, update),
      () => createReadTool(ctx.cwd).execute(id, params, signal, update)),''')
    for kind in ['Write', 'Edit']:
        replace(f'''  pi.registerTool({{ ...local{kind}, execute: (id, params, signal, update) => remote && routeRemoteTools && !targetsLocalServerMemory(params.path) ? create{kind}Tool(localCwd, {{ operations: remote{kind}Ops() }}).execute(id, params, signal, update) : local{kind}.execute(id, params, signal, update) }});''',
                f'''  pi.registerTool({{ ...local{kind}, execute: (id, params, signal, update, ctx) => runTool(ctx,
    () => remote && routeRemoteTools && !targetsLocalServerMemory(params.path) ? create{kind}Tool(localCwd, {{ operations: remote{kind}Ops() }}).execute(id, params, signal, update) : create{kind}Tool(ctx.cwd).execute(id, params, signal, update),
    () => create{kind}Tool(ctx.cwd).execute(id, params, signal, update)) }});''')
    replace('''    execute: async (id, params, signal, update) => {
      if (!remote || !routeRemoteTools) return localBash.execute(id, params, signal, update);''', '''    execute: (id, params, signal, update, ctx) => runTool(ctx, async () => {
      if (!remote || !routeRemoteTools) return createBashTool(ctx.cwd).execute(id, params, signal, update);''')
    replace('''      return limitRemoteToolResult(result, "exec");
    },''', '''      return limitRemoteToolResult(result, "exec");
    }, () => createBashTool(ctx.cwd).execute(id, params, signal, update)),''')
    replace('      action: StringEnum(["connect",', '''      projectRef: Type.Optional(Type.String({ description: "Managed mode: exact authorized catalog reference for connect/reconnect; SSH command is forbidden. Only connect/reconnect/status/exec are available." })),
      action: StringEnum(["connect",''')
    replace('    async execute(_id, params, _signal, _update, ctx) {', '''    async execute(_id, params, _signal, _update, ctx) {
      bindContext(ctx);
      if (managed) return managedControl(params, ctx);''')
    replace('      const action = input.toLowerCase();', '''      const action = input.toLowerCase();
      bindContext(ctx);
      if (managed) {
        try {
          if (action === "off" || action === "local") {
            await managedExclusive(async () => { closeManaged(); managed.local(); saveManaged(); status(ctx); });
          } else if (!input) {
            let entries: ReturnType<typeof loadProjectCatalog> = [];
            try { entries = loadProjectCatalog(managed.path); }
            catch (error) { ctx.ui.notify(`Project catalog unavailable: ${(error as Error).message}`, "error"); }
            const choices = entries.map((entry) => `${entry.label} [${entry.ref}]`);
            const choice = await ctx.ui.select("Authorized remote project", ["Local (explicit)", ...choices]);
            if (choice === undefined) return; // Cancel preserves pending/remote intent.
            if (choice === "Local (explicit)") {
              await managedExclusive(async () => { closeManaged(); managed.local(); saveManaged(); status(ctx); });
            } else {
              const index = choices.indexOf(choice);
              if (index < 0) throw new Error("Unknown project selection");
              await managedControl({ action: "connect", projectRef: entries[index]!.ref }, ctx);
            }
          } else if (input.startsWith("project ")) {
            await managedControl({ action: "connect", projectRef: input.slice(8) }, ctx);
          } else if (["status", "reload", "reconnect"].includes(action)) {
            const result = await managedControl({ action: action === "status" ? "status" : "reconnect" }, ctx);
            ctx.ui.notify(result.content[0]!.text, "info");
          } else if (input.startsWith("exec ")) {
            const result = await managedControl({ action: "exec", remoteCommand: input.slice(5) }, ctx);
            ctx.ui.notify(result.content[0]!.text, "info");
          } else throw new Error("Managed commands: /remote | project REF | status | reconnect | exec COMMAND | off");
        } catch (error) { ctx.ui.notify((error as Error).message, "error"); status(ctx); }
        return;
      }''')
    replace('    currentCtx = ctx;\n    sessionReady = true;', '''    bindContext(ctx);
    if (managed) {
      closeManaged();
      // A fresh session never inherits global resume or another factory's target.
      const record = [...ctx.sessionManager.getBranch()].reverse().find((entry: any) =>
        entry.type === "custom" && [managedEntry, SESSION_STATE_ENTRY_TYPE].includes(entry.customType)) as any;
      const saved = record?.customType === managedEntry ? record.data : undefined;
      if (record) managed.begin(); // A malformed remote record is not a fresh Local session.
      else managed.local(); // New context without metadata: ordinary Local Pi, no inheritance.
      try {
        if (saved?.version === 1 && saved.local === true && saved.projectRef === null) managed.local();
        else if (saved?.version === 1 && saved.local === false && typeof saved.projectRef === "string") {
          await managedExclusive(() => connectProject(saved.projectRef, ctx));
        } else if (record) throw new Error("Invalid managed session metadata; select a project");
      } catch (error) { ctx.ui.notify(`Managed restore failed: ${(error as Error).message}`, "error"); }
      status(ctx);
      return;
    }
    sessionReady = true;''')
    replace('    sessionReady = false;\n    const previous = remote;', '''    if (managed) { closeManaged(); return; }
    sessionReady = false;
    const previous = remote;''')
    replace('  pi.on("user_bash", async (event, ctx) => {', '''  pi.on("tool_call", (event) => {
    if (!managed?.remoteIntent) return;
    if (!["read", "write", "edit", "bash", "remote"].includes(event.toolName)) {
      return { block: true, reason: "Unsupported tool in managed remote mode (including child launchers); use remote read/write/edit/bash" };
    }
  });
  pi.on("user_bash", async (event, ctx) => {
    bindContext(ctx);
    if (managed) {
      if (!managed.remoteIntent) return undefined;
      try {
        requireManaged();
        const generation = managedGeneration;
        return { operations: { exec: (command, _cwd, options) => managedExclusive(async () => {
          if (generation !== managedGeneration) throw new Error("Managed selection changed before bash execution");
          requireManaged();
          return remoteBashOps().exec(command, localCwd, options);
        }) } };
      } catch (error) {
        return { result: { output: (error as Error).message, exitCode: 1, cancelled: false, truncated: false } };
      }
    }''')
    replace('    if (!remote || !routeRemoteTools) return undefined;\n    const content = serverMemoryContext(remote);',
            '    if (managed || !remote || !routeRemoteTools) return undefined;\n    const content = serverMemoryContext(remote);')
    replace('    systemPrompt: remoteSystemPrompt(event.systemPrompt, localCwd, remote),', '''    systemPrompt: managed
      ? `${event.systemPrompt}\\nManaged project ${managed.projectRef}: ${remote.cwd}. Only read/write/edit/bash are remotely covered. No local memory exception, forwarding or model disconnect. Browser panels, direct SDK bash and slash/child launchers require separate integration; do not assume coverage.`
      : remoteSystemPrompt(event.systemPrompt, localCwd, remote),''')
    replace('    description: "Connect, reconnect, annotate endpoints,',
            '    description: managed ? "Managed projects: connect/reconnect using exact projectRef, status, or exec using remoteCommand. User /remote selects authorized projects; only user Local/off enables local tools. No forwarding, memory exception or cwd overrides." : "Connect, reconnect, annotate endpoints,')
    replace('    promptSnippet: "Control the configured remote SSH connection,',
            '    promptSnippet: managed ? "Use an authorized projectRef; managed remote errors never imply local routing" : "Control the configured remote SSH connection,')
    replace('''    promptGuidelines: [
      "Use remote when''', '''    promptGuidelines: managed ? ["Use exact projectRef for connect/reconnect and remoteCommand for exec. Only the user can enable local mode; unsupported tools and child launchers are blocked."] : [
      "Use remote when''')
    if hashlib.sha256(source.encode()).hexdigest() != AFTER:
        raise ValueError(f'Unexpected patched source digest: {hashlib.sha256(source.encode()).hexdigest()}')
    return source


if __name__ == '__main__':
    target = pathlib.Path(sys.argv[1]) / 'index.ts'
    before = target.read_bytes().decode('utf8')
    after = patched(before)
    helper = pathlib.Path(__file__).with_name('managed-projects.ts').read_bytes()
    if hashlib.sha256(helper).hexdigest() != HELPER:
        raise ValueError('Unexpected managed helper digest')
    destination = target.parent / 'managed-projects.ts'
    if target.is_symlink() or destination.is_symlink() or (destination.exists() and destination.read_bytes() != helper):
        raise ValueError('Refusing symlink target or unrelated existing helper')
    print(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='a/index.ts', tofile='b/index.ts')))
    print('Post SHA256:', hashlib.sha256(after.encode()).hexdigest())
    if '--check' not in sys.argv:
        target.write_bytes(after.encode('utf8'))
        destination.write_bytes(helper)
