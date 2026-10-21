---
name: n3tx-init
description: Orient a session in an N3TX project by locating its N3TX dependency, reading AGENTS.md and README.md, and tracing feature-relevant documentation and code to understand the intended architecture. Use at the beginning of N3TX project work or when asked to run n3tx-init.
---

# N3TX Session Orientation

Understand the **N3TX-intended way** to build the current feature or system before
proposing changes. Discover architecture from the project's actual N3TX version,
not from memory or generic framework assumptions.

This is a **read-only orientation workflow**, not project initialization or
implementation. Do not edit files, generate saved plans, install dependencies,
clone repositories, initialize submodules, or run application code or tests.
Use available read/search tools and read-only metadata inspection. Respect the
active harness's permissions and governing instructions throughout.

## 1. 📍 Locate the project's N3TX

1. Establish the consuming project root from the current workspace and project
   guidance. Do not assume the shell's current subdirectory is the project root.
2. Check an explicitly supplied N3TX path first; otherwise start with
   `<project>/lib/n3tx`. If working inside N3TX itself, consider that checkout.
3. If needed, inspect project guidance, dependency manifests, lockfiles, workspace
   configuration, import paths, and submodule references to locate N3TX. Keep
   searches scoped to the project and referenced locations, not the entire machine.
4. Confirm the candidate is N3TX and determine how the project actually consumes
   it. Follow symlinks where permitted. Record the resolved path and version or
   revision when available through read-only metadata.
5. If several copies exist, use dependency wiring to identify the relevant one.
   If the supplied path differs from the consumed dependency, surface the mismatch.
   Ask for clarification when the target remains ambiguous rather than selecting
   an arbitrary checkout.

If N3TX is missing or inaccessible, report what was checked and ask for its
location or access. Do not fetch it, silently substitute a different version,
or claim that orientation is complete.

## 2. 📖 Read the foundational guidance

- Read the consuming project's applicable guidance, then N3TX's root `AGENTS.md`
  and `README.md`. Explicitly report either file if missing or inaccessible.
- Follow their architecture, documentation-index, and getting-started references
  to establish N3TX's core concepts, ownership boundaries, and supported patterns.
  Discover the actual documentation layout rather than assuming a `docs/` tree.
- Read applicable nested `AGENTS.md` files before investigating their modules.
  Treat scoped guidance within its scope and honor higher-priority instructions.
- Prefer documentation shipped with the consumed version. If linked material is
  unavailable or describes another version, mark that limitation explicitly.

Read the foundational files, not merely search snippets. For extensive linked
documentation, use its index to select relevant sections rather than loading
everything indiscriminately.

## 3. 🗺️ Trace the feature or system

Use the current conversation and any invocation arguments to identify the goal.
If none is supplied, finish baseline orientation, summarize it, and ask which
feature or system to investigate. Do not invent a feature to justify exploration.

For a known goal, trace the smallest coherent path:

```text
Feature goal -> N3TX guidance -> supported interfaces and extension points
                                      |
                                      v
Project integration <- implementation + relevant examples and tests
```

- Read feature-relevant N3TX docs before the associated code.
- Trace public interfaces into enough implementation to understand the relevant
  lifecycle, data flow, configuration, and ownership boundaries.
- Inspect the closest examples and tests for intended usage and edge cases.
  Reading tests is evidence of encoded expectations, not proof they pass.
- Inspect the consuming project's call sites, configuration, and neighboring
  implementations to understand where the feature belongs.
- Identify existing primitives to reuse, supported extension seams, and patterns
  to avoid. Prefer N3TX's supported composition over parallel infrastructure or
  internal-API workarounds; do not force a fit if the required capability is absent.
- Distinguish **documented intent**, **observed implementation**, and **inference**.
  Flag contradictions, deprecated examples, or project deviations with evidence;
  do not silently resolve them or start fixing them.

Stop when you can explain the relevant architectural rules, the appropriate
integration points, and the remaining uncertainties. This is focused orientation,
not a whole-framework audit.

## 4. ✅ Return an N3TX context briefing

Keep the response concise and cite concrete file paths, symbols, or sections:

| Topic | Report |
| --- | --- |
| Location | Project root, resolved N3TX path, dependency wiring, version if known |
| Sources read | Foundational guidance and relevant docs, code, examples, tests |
| Intended architecture | Relevant responsibilities, lifecycle, invariants, boundaries |
| Feature fit | Existing primitives, extension points, and project integration sites |
| Recommended direction | The simplest approach consistent with the evidence |
| Gaps | Missing sources, contradictions, assumptions, and decisions needed |

For baseline-only orientation, mark feature fit and direction as pending the
feature scope. Never list unread files as reviewed. State that no files changed
and no runtime behavior was verified. Do not invent signatures or APIs; include
existing signatures only when verified and useful to explain the integration.

End after the briefing. This invocation does not authorize implementation. Carry
the verified context into subsequent work, and revisit relevant sources when the
feature scope or N3TX version changes.
