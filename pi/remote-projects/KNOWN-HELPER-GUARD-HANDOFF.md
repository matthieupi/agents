# #4.1 known local helper guards — source-only handoff

✅ Implemented 2026-09-08. No live/home writes, installer changes, publication,
package installs, commits, or gitlink updates. This is **not live activation**.

## Scope and behavior

The canonical dependency-free source is
`pi/.pi/agent/extension-library/remote-project-mode.ts` (paths here are relative
to the agents repository). Browser build ownership must **copy this file
verbatim** into Pi Web's build inputs and import `remoteProjectMode`; do not
reimplement its parser. No browser build or installed UI was validated here.

### Method Signature Surface

```ts
+ export function remoteProjectMode(entries: readonly unknown[]): 'local'|'remote';
+ export function requireLocalProjectExecution(ctx: any, operation: string): void;
```

No existing production callable/interface signatures changed. Focused test helpers:

```js
+ function load(file, mocks = {}, globals = {});
+ async function harness(relative, branch = [], closeAutomatically = true);
+ async function blocked(h, action);
```

```text
current parent SessionManager.getBranch()
  -> last custom pi-ssh-remote-project OR pi-ssh-remote-state
  -> no relevant entry / valid explicit Local : existing local launcher
  -> remote / legacy / malformed entry       : visible static error, no child
  -> missing or unreadable branch            : visible static error, no child
```

Valid explicit Local is exactly version 1, `local === true`, `projectRef === null`,
matching the current managed extension restore decision. Remote authorization is
not attempted by this helper. Catalog failures or missing project refs cannot
enable Local. No cache, event bus, global mode, backend migration, or SSH startup
hook change. Operation labels at call sites are static, not task/ref/branch data.

Both subagent-widget copies guard `/sub`, `/subcont`, create/continue tools and the
shared spawn boundary. Checks precede state mutation and the fire-and-forget
boundary throws synchronously. Team dispatch, chain steps, and Pi expert launches
also guard their actual spawn boundary; each chain step rechecks after the
previous asynchronous child completes. No launch path here awaits a UI prompt;
team/chain selectors only change metadata, never spawn.

`cross-agent.ts` remains unchanged: it scans definitions and sends prompt text,
not local child processes. Team/chain/expert selectors, lists and grids remain
usable. Existing explicit subagent removal/clear and lifecycle behavior is
unchanged. **Switching mode or rejecting a new helper does not kill existing user
jobs: they remain where originally started.** Existing removal commands can still
terminate jobs when explicitly requested. This is a known-helper boundary, not
containment for arbitrary extensions or already-running processes.

## Before hashes — compare-before-patch migration input

These files were clean against agents HEAD
`5abf083b548f53181d32b2625f5e33c45a059d43` before this pass; hashes were rechecked
immediately before editing. SHA-256 of the **original bytes**:

| File under `pi/.pi/agent/` | Before SHA-256 |
|---|---|
| `extensions/subagent-widget.ts` | `1d09019104938726b87990d04ffca9aa9247e9cdeee3b61444a40b3700d6ab87` |
| `extension-library/pi-vs-claude-code/subagent-widget.ts` | `1d09019104938726b87990d04ffca9aa9247e9cdeee3b61444a40b3700d6ab87` |
| `extension-library/pi-vs-claude-code/agent-team.ts` | `7301cc9b25d0e01538c96ac313b0c570b673bf4348654c6497e5e19d6ea58830` |
| `extension-library/pi-vs-claude-code/agent-chain.ts` | `48002207ff4ba60150e7af8aed74a87dd5b883dfd7b4811afcac5b9b4d75a913` |
| `extension-library/pi-vs-claude-code/pi-pi.ts` | `1378a5a53f757f585739627e1ba74fd1672529320f8500bd2032055d34305b04` |
| `extensions/cross-agent.ts` (inspected, unchanged) | `1e430978446eb13dbd28cf726ba4a8dbcaf85f9edb9da0c32cb8a8e28ce74a3f` |

New canonical helper has no before hash. Its source SHA-256 at handoff is
`01f211cd703a3150fbd723fcaad0df965e0e1922d05c8e9df6026bea616324da`.

## ⚠️ Installed-home / enablement gate — owned by reprovision team

Native initialization is copy-once: updating this repository does **not** update
existing home helpers. Do not enable managed Remote with old unguarded loaded
helpers. A source diff or successful repository test is not installed evidence.

Required safe migration/activation sequence (not performed here):

1. As the owning account, inventory actual extension load paths, including home,
   manual library presets and any additional/custom copies. Keep managed Remote
   disabled until all known local launchers are guarded or explicitly excluded
   from the extension load set. Failure to import the helper must not cause an
   older unguarded copy to be loaded instead.
2. For a regular, non-symlink installed file whose bytes match the relevant
   **before** hash, back it up and apply the reviewed guard-only change. Recheck
   bytes immediately before replacement to avoid overwriting concurrent edits.
   Already matching reviewed after-bytes need no rewrite. Missing files can be
   installed only under the existing approved ownership/path controls.
3. On any other bytes, ownership mismatch, or redirected path, **stop**. Preserve
   customizations; require an owner-reviewed merge or explicitly exclude that
   extension. Do not replace custom helpers wholesale or treat mismatch as safe.
4. Install the canonical helper alongside the complete relative directory layout.
   The default subagent imports `../extension-library/remote-project-mode.ts`;
   library helpers import `../remote-project-mode.ts`. Check both tracked copies
   and all actually loaded installed copies. Browser copying is a separate build
   input action, not an alternative to native helper migration.
5. Verify installed-byte hashes against the reviewed source and test a newly
   loaded parent session: Remote `/sub` creates zero children with visible error;
   explicit Local allows it. Test continue and loaded team/chain/expert tools too.
   Coordinate any session reload/service restart with existing job owners; this
   handoff does not authorize terminating their jobs.
6. Only then enable managed project selection on the concerned machine. Follow
   the team's existing single-machine-first validation/reprovision sequence.

## 🧪 Verification

From `services/agents`, using the already-present scratch compiler/dependencies
read-only (no installer or fixture regeneration):

```sh
node --test pi/remote-projects/test-known-helper-guards.mjs
node --test pi/remote-projects/test-managed.mjs
git diff --check
```

- **11 focused tests passed**: actual helper and extension sources, synthetic
  session branches, fake spawn/filesystem/timers, direct commands and tools,
  local arguments/environment/session continuation, remote/legacy/malformed
  zero-child behavior, unreadable contexts, static error secrecy, independent
  parents, safe administrative commands, async chain recheck and preservation
  of an existing running local job.
- Parser consistency test executes the actual restore statements from the
  current `apply-upstream.py` without editing it. Comparison uses SDK-shaped
  entries; arbitrary unrelated null/primitive entries are tested separately in
  the pure helper (the restore patch assumes SDK-shaped entries).
- **20 existing managed-extension tests passed**, using the existing pinned
  pi-ssh-remote 0.1.12 fixture and Pi SDK test dependencies.
- `git diff --check` passed. The parent gitlink remains
  `5abf083b548f53181d32b2625f5e33c45a059d43`.
- No real children, SSH endpoints, browser, native home migration, live VM,
  installer or publication verification was performed in this pass.
