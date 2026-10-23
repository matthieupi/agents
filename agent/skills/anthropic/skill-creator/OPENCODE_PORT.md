# OpenCode V2 adaptation notice

This directory is a modified version of Anthropic's skill-creator. The original
license remains in `LICENSE.txt`. Local changes (2026-10-23) replace the execution
adapter, update workflow/reference/UI instructions, align metadata validation with
path-derived IDs, and preserve unknown benchmark usage as unknown. The packaging
utility is retained as optional ZIP transport, not an OpenCode installer.

## Verified contract

Official documentation consulted:
- https://opencode.ai/v2/docs/cli
- https://opencode.ai/v2/docs/config
- https://opencode.ai/v2/docs/skills
- https://opencode.ai/v2/docs/permissions

The installed `opencode v2.1.2` CLI's `run --help` confirms `--standalone`,
`--format json`, `--agent`, `--file`, and `--model provider/model#variant`.
The runner never uses `--auto` or a permission bypass.

The JSON event implementation was inspected in the JavaScript embedded in
`/opt/opencode/component/.runtime/node_modules/@opencode/cli-linux-x64/bin/opencode`.
The CLI writes newline-delimited objects with `type`, `timestamp`, `sessionID`:

```json
{"type":"tool_use","part":{"tool":"skill","state":{"status":"completed","input":{"id":"example"}}}}
{"type":"text","part":{"text":"response"}}
{"type":"step_finish","part":{"reason":"stop"}}
{"type":"error","error":{"message":"provider failure"}}
```

The `tool_use` event is emitted for completed **and failed** tools. Failed tools
have `state.status: "error"`. The renderer maps `session.step.ended` into
`step_finish` with `part.reason = event.data.finish`, and step/execution failures
into `error`. The CLI reads piped stdin as prompt text. Setup checks modeled this contract,
not Anthropic partial-stream messages. A normal final `stop` plus exit code zero
is required; empty/truncated/error streams are invalid even after a skill load.

## Isolation and credentials

Every run gets a unique temporary home, config, cache, state, temp directory, and
workspace. It uses `OPENCODE_CONFIG_PROJECT_DISABLE=true` (verified in installed
V2 source), an explicit skills source, and a private standalone server. It does
not write to the caller's project, installed skills, or configuration. The target
keeps its real directory ID; random workspace paths, not random IDs, isolate
parallel workers. All tools are denied except `skill` for that exact ID; the
description improver denies every tool. No plugins/MCP/user instructions are
imported. A nonempty system configuration causes a refusal rather than silently
overriding managed settings.

OpenCode V2 stores credentials in its data database. The runner retains the
normal `XDG_DATA_HOME` (and an explicit `OPENCODE_DB` override, if set) so
authenticated providers work without copying secrets.
Consequently normal session/log records are persisted by OpenCode; **this is not
an ephemeral credential database or an OS security sandbox**. Environment provider
keys also work. Do not run untrusted CLI/provider code. Custom provider packages
and their network behavior remain trusted host code.

Global/project provider definitions are intentionally not imported with their
plugins, skills, or permissions. For a custom endpoint/model, point
`SKILL_CREATOR_PROVIDER_CONFIG` at a separate JSON document containing only
`providers` and optionally `model`, using V2 shapes and `{env:...}` references.
Use an explicit `--model` in CLI invocations. No credentials should be embedded
in files, logs, or the repository. Authentication and model-selection failures
abort evaluation and must be fixed before retrying.

## Batch cancellation

Each evaluation batch owns a shared `threading.Event`. A worker failure signals
it before that worker can start another trial. The main thread also catches
`BaseException`, including Ctrl+C during job submission or result collection,
signals cancellation, cancels queued futures, and waits for active cleanup.
An interrupt is propagated as an interrupt; ordinary failures report no valid
score. Neither path returns partial observations as successful non-triggers.

Cancellation and subprocess creation share a short launch lock. No new CLI is
launched after cancellation is signalled; workers already dequeued check the same
event before launch. Active workers check cancellation between `communicate`
waits of at most 100ms, using a monotonic overall timeout. The complete prompt is
supplied on stdin through a private unnamed temporary file in the workspace;
retrying `communicate` only drains stdout/stderr, preserving their buffers. This
avoids CPython's incomplete-stdin retry problem and never resends the prompt. On cancellation
or timeout the worker kills its CLI process group, drains the pipes, and reaps
the direct CLI. Descendants in that group are killed; orphan reaping belongs to
the OS. Already-submitted provider requests may still incur charges: stopping a
local process does not undo a remote request or guarantee provider-side abort.

The skill body in trigger trials is a neutral stop instruction. This isolates
description discovery rather than running potentially destructive user requests.
Only the tested skill is advertised: these scores do not estimate competition
with the user's full skill catalog or execution quality. Baseline/full-task tests
need independent sessions and transcript checks as described in SKILL.md.

## Checks and portability

The automated evaluation runner supports **Linux only** and rejects other
platforms. macOS managed preferences and Windows process-tree/configuration
isolation are not implemented or reviewed. Use a Linux environment instead of
assuming those systems have equivalent isolation or cleanup. Static viewer and
packaging helpers are separate from this restriction.

Use Python 3.10+ and PyYAML (`python3 -m pip install PyYAML` in your environment).
Run scripts as modules from this directory, e.g. `python3 -m scripts.run_eval --help`.

Setup verification used mock event streams and local fake subprocesses only, plus
CLI help/source inspection. No paid model evaluations were run. The setup test
files were removed at the user's request; no standing maintenance suite is kept.
Real provider authentication, model-specific trigger quality, and browser visual
behavior still require an approved manual smoke test.
