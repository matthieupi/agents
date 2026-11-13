# Boundary-preserving simplification

Three focused skills and one coordinating entrypoint for reaching the smallest
correct solution without losing required behavior or safety boundaries.

## Choose an entrypoint

| Skill | Use it for |
| --- | --- |
| [simplification-flow](simplification-flow/SKILL.md) | A unified pass through the three skills below |
| [minimum-viable-design](minimum-viable-design/SKILL.md) | Defining the smallest sufficient design before adding machinery |
| [reuse-before-build](reuse-before-build/SKILL.md) | Checking existing mechanisms before introducing a new one |
| [simplify-with-invariants](simplify-with-invariants/SKILL.md) | Removing existing complexity while preserving required guarantees |

```text
                   simplification-flow
                            |
                            v
                minimum-viable-design
                            |
                            v
                   reuse-before-build
                            |
                            v
                simplify-with-invariants
```

The children remain independently usable. The unified skill loads their
instructions by reference; it does not maintain another copy of their workflows.
Directory basenames are the skill IDs, including inside this nested collection.

## Usage

- "Use simplification-flow on the email analysis pipeline. Keep current access
  controls and logging guarantees; propose changes only."
- "Use reuse-before-build before adding another activity-history endpoint."
- "Use simplify-with-invariants to remove these wrappers within the approved
  scope."

These skills do not replace project orientation, authorization, implementation
policy, or proportionate verification. They create no automatic subagent team,
plan artifact, approval cycle, or standing evaluation suite. Unchanged behavior
and no new abstraction can be valid outcomes.
