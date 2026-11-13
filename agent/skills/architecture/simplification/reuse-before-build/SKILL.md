---
name: reuse-before-build
description: >-
  Check existing framework, project or maintained library capabilities before
  adding a helper layer, wrapper, endpoint, registry, parser or custom protocol
  mechanism. Use when a proposal duplicates native behavior or the user asks why
  existing primitives are not used. Compare real contracts, including security
  and lifecycle differences; do not assume native reuse is always equivalent.
---

# Reuse before build

Own the question: **does this need a new mechanism at all?**
This is a focused capability comparison, not a framework rewrite or installation
request. A justified small custom implementation is a valid outcome.

## Inputs and boundaries

Use the requested behavior, relevant constraints and current project orientation.
Do not rediscover the whole framework if its location and extension points are
already known. Inspect the actual installed version rather than relying on a
familiar API name or an outdated plan.

## Workflow

1. **Name the capability.** Identify the caller, required input/output and the
   problem the proposed new mechanism would solve. Distinguish retrieval from
   presentation, policy from transport, and framework limitations from optional
   application wrappers.
2. **Trace existing support.** Read relevant documentation and the implementation
   or representative consumers of the closest existing primitive. Prefer project
   and framework facilities already in use. If a hand-written parser or protocol
   stack is growing, consider a maintained dependency without installing one or
   changing the dependency policy merely for this investigation.
3. **Compare actual contracts.** Check the differences that matter here: access
   and payload disclosure, errors, persistence, identity, lifecycle, state and
   compatibility. A native LIST returning full records may not replace a filtered
   projection safely. Record unknowns rather than declaring equivalence by name.
4. **Choose the least additional mechanism.** Prefer direct reuse, then a small
   adapter for a demonstrated mismatch, then custom behavior with a specific
   justification. Do not rename an existing function through a new wrapper or
   retain parallel paths without a current requirement. Reuse is not a mandate
   to weaken access controls or fix the framework during a local task.

## Output and stopping condition

Provide one decision: **reuse**, **small adapter**, or **custom justified**.
Include the relevant source/API evidence, material contract differences, and any
missing evidence that prevents a decision. Keep it proportional to the task.

Stop when that comparison settles the choice or exposes one concrete blocker.
Do not expand into an exhaustive library survey, rewrite neighboring modules,
create a new abstraction for "flexibility", or add tests merely to document the
comparison. Follow the project's normal authorization before any actual change.

## Neighbors

- `n3tx-init` owns orientation when this is an N3TX project.
- [minimum-viable-design](../minimum-viable-design/SKILL.md) owns the smallest
  requested behavior and excludes hypothetical requirements.
- [simplify-with-invariants](../simplify-with-invariants/SKILL.md) owns removing
  redundant mechanisms after their real consumers and guarantees are understood.
