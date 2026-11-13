---
name: minimum-viable-design
description: >-
  Find the smallest sufficient design when a user requests a minimal prototype,
  rejects an overbuilt proposal, supplies a direct implementation sketch, or a
  design adds infrastructure for hypothetical future needs. Separate current
  requirements from deferred work without weakening required guarantees. Not a
  general feature-execution or broad architecture-audit workflow.
---

# Minimum viable design

Own the question: **what is the smallest design that meets this request?**
This is a design workflow, not authorization to implement or change the scope.

## Inputs and boundaries

Use the current request, relevant project guidance and already established
context. Ask only when a missing answer materially changes scope or correctness.
Use project orientation when needed; do not repeat an already adequate discovery
pass or start a general audit.

Keep requested public APIs, examples and pseudocode as the starting contract.
Separate requirements the user stated from assumptions you inferred. An existing
security or data boundary remains binding even if the user asks for fewer layers.

## Workflow

1. **Establish the immediate outcome.** Identify the real caller and a
   representative successful use. State what is out of scope and what "finished"
   means for this request. Use existing acceptance criteria rather than inventing
   a product specification.
2. **Separate needs from possibilities.** Distinguish required-now behavior,
   guarantees that must remain, and hypothetical extensions. Future composition
   is not permission to build registries, providers, leases or adapters now.
   Preserve an extension seam only when a concrete constraint earns it.
3. **Draw the direct path first.** Start with the user's sketch or the shortest
   caller-to-result flow. For each added class, helper, route, stage or policy,
   identify the current requirement it satisfies. Remove additions justified
   only by "we might need it" or move policy to its actual owner.
4. **Challenge only the necessary deviations.** Explain where the direct path
   would fail a required contract. Prefer the smallest repair over a generalized
   framework. Mark unverified assumptions; do not present a provisional design
   as proven compatible with the installed framework.

## Output and stopping condition

Return a compact design delta, normally a few bullets:

- Immediate outcome and smallest caller-to-result flow.
- Required boundaries that stay, and their owners.
- Concepts proposed for removal or deferral, including user-requested concepts
  that must not be misclassified as speculative.
- Any concrete unresolved constraint or assumption requiring investigation.

For a tiny request, keep this reasoning internal rather than producing ceremony.
Stop once the minimal shape is clear or a specific blocking constraint is named.
Do not require multiple alternative designs, an exact concept count, saved plans,
new tests, subagents or another approval round merely to complete this skill.
Existing approval and safety policies still apply.

## Neighbors

- [reuse-before-build](../reuse-before-build/SKILL.md) checks whether the
  installed framework or a maintained dependency already provides the mechanism.
- [simplify-with-invariants](../simplify-with-invariants/SKILL.md) owns safe
  subtraction from existing code, not this design step.
- Use `distill` for an explicitly requested deeper subsystem dialogue, not by
  default for every minimal design.
