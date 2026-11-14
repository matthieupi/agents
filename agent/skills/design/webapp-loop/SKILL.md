---
name: webapp-loop
description: >-
  Run a bounded UI improvement loop on a specified component, page or user flow.
---

# Webapp loop


Use fresh Build, Reviewer, Plan-inline and Build subagents each iteration for
quick Playwright captures, criteria 0–10 ratings, proposals, a short inline plan,
implementation and verification. Default to a few base screenshots and up to five
interactions. Builds on @webapp-testing and @simplification-flow. This does not
authorize unrelated redesign or deployment.

## Inputs and authority

- **Target:** component, page or user flow; ask only for information that
  materially blocks work.
- **Iterations:** a positive integer, the maximum number of improvement rounds.
  Baseline capture is not a separate improvement round. Never reset the counter.
- **Optional:** focus areas, viewports, reference design and synthetic test data.
  Preserve the established brand, product intent and project constraints.

Respect existing approval requirements for consequential changes; do not add a
confirmation ceremony at every stage of an already authorized, in-scope round.

## Referenced skills and frozen criteria

Load these to help the different subagent achieve their goals

- [webapp-testing](../../anthropic/webapp-testing/SKILL.md): Playwright, browser
  interaction, screenshots and verification mechanics.
- [frontend-design](../frontend-design/SKILL.md): intentional design
  within the existing brief; do not invent a new brand for a component adjustment.
- [simplification-flow](../../architecture/simplification/simplification-flow/SKILL.md):
  smallest sufficient changes with retained guarantees. The exact ID is
  `simplification-flow`, not `simplify-flow`.
- [Frozen review criteria](references/review-criteria.md): authoritative dimensions,
  0–10 anchors, evidence requirements, critical failures and research sources.

## Fresh-agent pipeline

For **every iteration**, start fresh role sessions in this order.

| Stage | Fresh agent | Required skills and output |
| --- | --- | --- |
| 1. Capture | `build` | `webapp-testing`; quick base screenshot plus up to five interactions, no product edits |
| 2. Critique | `reviewer` | Frozen criteria, `simplification-flow`, relevant design guidance; scores, findings and proposals |
| 3. Select | `plan-inline` | `frontend-design`, `simplification-flow`; worthwhile subset and a quick inline plan |
| 4. Improve | A different `build` session | `frontend-design`, `simplification-flow`, `webapp-testing`; implement selected work, capture and verify |

Loading a skill never expands their read-only role permissions.

## Improve UI round

1. **Capture the actual target.** Take base screenshots and up to five chosen
   interactions; stop as soon as the small evidence set is ready.
2. **Review and propose.** The Reviewer opens the actual images and inspects the
   UI/UX and style/design/layout. Rate applicable dimensions from 0 to 10, with 10
   better.
3. **Propose a list of improvements.**
4. **Assess and select.** Plan-inline checks evidence and relevant source, then
   weighs impact, effort, risk, scope and fit to the brief. Reject
   unnecessary machinery. Return the selected changes, precise source
   targets, short implementation steps and acceptance checks inline, not a plan
   file. Include a Method Signature Surface, or state that no signatures change.
   An empty worthwhile subset is a valid early-convergence result.
5. **Implement and verify.** The implementation Build changes only the selected,
   authorized slice.
   Keep source, generated artifact, served revision and visible result distinct.

Be careful for permanent action on live servers.
