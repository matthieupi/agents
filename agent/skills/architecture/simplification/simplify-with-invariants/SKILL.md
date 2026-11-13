---
name: simplify-with-invariants
description: >-
  Remove existing complexity after a user requests simplification, rejects an
  overbuilt approach, or approves replacing wrappers and parallel mechanisms.
  Preserve required behavior, authorization, data, trust and lifecycle guarantees
  while deleting unnecessary concepts. Not permission for destructive cleanup,
  weaker security or a broader migration than the user requested.
---

# Simplify with invariants

Own the question: **what can disappear without losing a required guarantee?**
Use this for a focused subtraction plan or authorized implementation. A design
request remains analysis-only; the skill does not grant permission to edit,
deploy, discard data or change unrelated work.

## Workflow

1. **Rebase on the current instruction.** Identify the accepted outcome and any
   rejected approach. After a correction, stop extending the superseded design.
   Reuse existing task context and completed evidence; do not restart unrelated
   work or create a persistent correction registry. Resolve only ambiguities
   that affect correctness, scope or consequential actions.
2. **State what must survive.** Trace affected consumers and the actual owners
   of required behavior. Preserve relevant authorization, disclosure, trust and
   logging boundaries, data identity, public contracts and lifecycle behavior.
   Distinguish these from speculative hardening or compatibility machinery.
   "Simpler" is not permission to remove a guarantee or invent a new one.
3. **Choose subtraction, not another layer.** Identify what stays, moves and
   disappears. Move policy to its existing owner when that removes coupling.
   Prefer replacing an unnecessary mechanism to wrapping it. Keep staged
   coexistence only where explicitly required; do not invent a clean cutover or
   delete user state to obtain a smaller diff.
4. **Apply only the authorized delta.** If implementation is requested and
   permitted, migrate affected consumers and remove obsolete paths within the
   approved boundary. Distinguish instance/component changes from shared
   defaults. Preserve unrelated edits and the project's documentation standards.
   For a proposal-only request, describe this delta without editing files.
5. **Check the preserved contract.** For actual edits, use existing focused
   checks and representative consumers of the changed boundary. Check the real
   nested component or runtime state when that is where behavior lives. Add or
   update permanent tests only for a concrete uncovered invariant or an explicit
   request, following the project's verification ownership policy. In analysis
   mode, name the needed evidence without claiming it was executed.

## Output and stopping condition

Report the planned or completed subtraction, guarantees retained, and evidence
with its limits. Separate source changes, verification and live activation; do
not equate one with another. If a retained mechanism is still necessary, name the
specific requirement rather than hiding it behind "best practice".

Stop when the requested outcome and preserved contracts are demonstrated, or a
specific unknown/blocker needs a decision. Do not drift into adjacent cleanup,
rewrite all guards, manufacture migrations or run a full suite by default.
Do not add an approval round for an unchanged, already authorized scope; follow
existing policy for genuinely new scope, risk or consequential actions.

## Neighbors

- [minimum-viable-design](../minimum-viable-design/SKILL.md) defines the target
  shape if it is not already clear.
- [reuse-before-build](../reuse-before-build/SKILL.md) verifies a replacement's
  native capabilities and contract differences.
- Existing bugfix and browser-verification workflows own incident reproduction
  and their warranted checks; this skill does not impose universal TDD.
