---
name: simplification-flow
description: >-
  Coordinate an end-to-end simplification pass by loading minimum-viable-design,
  reuse-before-build and simplify-with-invariants in order. Use when the user
  requests the unified simplification flow or wants an overbuilt approach reduced
  to the smallest guarantee-preserving solution. For just one of those concerns,
  use the focused skill instead. This entrypoint composes, not copies, their work.
---

# Simplification flow

Coordinate the three linked skills. Their files are the authoritative procedures;
this entrypoint owns only sequencing, handoff and the final combined result.

## Scope

Use the current task and its existing authorization. A request for analysis or a
design does not become permission to implement by entering the final stage.
Project safety, approval, tool permissions and verification ownership still apply.

## Load and compose

Load each skill when its stage is reached, using the active harness's native
skill loader and the exact ID below. In OpenCode, the input is
`{"id":"minimum-viable-design"}`, and likewise for the other IDs.

If an ID is unregistered or no loader exists, read the linked `SKILL.md` only if
file access is permitted. Never bypass a permission denial. If neither method is
available, report the missing dependency rather than reconstructing its procedure.

| Order | Skill to load | Handoff |
| --- | --- | --- |
| 1 | [minimum-viable-design](../minimum-viable-design/SKILL.md) | Carry its target shape and constraints into stage 2 |
| 2 | [reuse-before-build](../reuse-before-build/SKILL.md) | Carry its supported mechanism and differences into stage 3 |
| 3 | [simplify-with-invariants](../simplify-with-invariants/SKILL.md) | Return its planned or authorized completed delta |

Run the loaded procedure, not a locally maintained summary of it. Keep a single
task context across stages, including user exclusions, retained guarantees,
current evidence and unresolved questions. Do not create a separate plan or
approval cycle per stage. If a stage's result is already current, reuse it rather
than repeating the investigation; a no-change result is legitimate.

When later evidence invalidates an earlier conclusion, update only the affected
result and downstream work. Do not keep executing a rejected design or restart
the whole flow without cause. A missing required invariant blocks progression;
an irrelevant concern or absent hypothetical extension does not.

## Finish

Return one combined result using the children’s outputs. Include the chosen
minimal path, retained boundaries, planned/completed change and evidence gaps.
Do not concatenate three reports or claim checks or activation that did not run.
For a small task, a few bullets are enough.

Stop at the authorized outcome or a concrete blocker. This coordinator adds no
mandatory agents, tests, runtime helpers, persistent state or automatic deployment.
