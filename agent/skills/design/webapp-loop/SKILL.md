---
name: webapp-loop
description: >-
  Run a bounded UI improvement loop on a specified component, page or user flow.
  Use fresh Build, Reviewer, Plan-inline and Build subagents each iteration for
  interactive Playwright screenshots, frozen-criteria 0–10 ratings, proposals,
  a short inline plan, implementation and verification. Builds on webapp-testing
  and simplification-flow. Not a screenshot-only audit, recurring web-research
  task or authorization for unrelated redesign or deployment.
---

# Webapp loop

Coordinate evidence-driven improvements to one target. Reference the existing
skills for browser work, design and simplification; do not duplicate their
procedures or build a new browser runner.

## Inputs and authority

- **Target:** component, page or user flow, with enough route, selector or source
  context to identify it. Infer the running app and relevant state from the
  project when possible; ask only for information that materially blocks work.
- **Iterations:** a positive integer, the maximum number of improvement rounds.
  Baseline capture is not a separate improvement round. Never reset the counter.
- **Optional:** focus areas, viewports, reference design and synthetic test data.
  Preserve the established brand, product intent and project constraints.

Do not start a loop while authoring this skill. When invoked without its required
inputs, ask for them together. A proposal-only request does not authorize edits.
No automatic commits, host publication, deployments or service restarts.
Respect existing approval requirements for consequential changes; do not add a
confirmation ceremony at every stage of an already authorized, in-scope round.

## Referenced skills and frozen criteria

Load these by exact ID when needed; the linked files are the fallback only when
native loading is unavailable and file access is permitted. Never bypass a denial.

- [webapp-testing](../../anthropic/webapp-testing/SKILL.md): Playwright, browser
  interaction, screenshots and verification mechanics.
- [frontend-design](../../anthropic/frontend-design/SKILL.md): intentional design
  within the existing brief; do not invent a new brand for a component adjustment.
- [simplification-flow](../../architecture/simplification/simplification-flow/SKILL.md):
  smallest sufficient changes with retained guarantees. The exact ID is
  `simplification-flow`, not `simplify-flow`.
- [Frozen review criteria](references/review-criteria.md): authoritative dimensions,
  0–10 anchors, evidence requirements, critical failures and research sources.

Read the frozen criteria at run start and include their version in handoffs.
Do not research a new rubric on each run, silently reweight dimensions or alter
the anchors to make an iteration appear better. Any explicit rubric revision is
separate work, not part of the improvement loop.

## Fresh-agent pipeline

For **every iteration**, start fresh role sessions in this order. Do not reuse a
session from another iteration or impersonate a role with a different agent.
Use native `subagent` calls with `agent: "build"`, `"reviewer"` and
`"plan-inline"`; omit `sessionID` on each new role's first call. Use background
execution and completion notifications, not polling. Stages are sequential
because each consumes the previous result; do not launch them speculatively.

| Stage | Fresh agent | Required skills and output |
| --- | --- | --- |
| 1. Capture | `build` | `webapp-testing`; current interactive-state evidence, no product edits |
| 2. Critique | `reviewer` | Frozen criteria, `simplification-flow`, relevant design guidance; scores, findings and proposals |
| 3. Select | `plan-inline` | `frontend-design`, `simplification-flow`; worthwhile subset and a quick inline plan |
| 4. Improve | A different `build` session | `frontend-design`, `simplification-flow`, `webapp-testing`; implement selected work, capture and verify |

Keep project-required specialist ownership and native depth/permission limits.
Build owns its stage but must delegate actual validation when project policy
requires it. If a required role or capability is unavailable, report the blocker;
do not silently substitute a worker, skip evidence or invent a successful check.
Reviewer and Plan-inline use `simplification-flow` in analysis-only mode; loading
a skill never expands their read-only role permissions.

### Handoff packet

Fresh context must not mean lost context. Pass each agent the same bounded brief:

- Target, user goal, current round/limit, authorized scope and explicit exclusions.
- Actual checkout, allowed source paths, applicable project rules and skill paths.
- App URL, observed served revision, viewports, routes, states and synthetic-data
  setup. Pass safe credential references, never secret values or real-user data.
- Frozen rubric version, prior verified scores/findings, source-to-runtime gaps,
  and real screenshot/log paths. A fresh Reviewer receives the images and facts,
  not a directive to agree with earlier judgments.
- Selected proposals and inline plan when those exist; label assumptions and
  checks not yet performed. Do not forward an entire conversation transcript.

## Run each round

1. **Capture the actual target.** The capture Build uses Playwright to navigate,
   open menus/dialogs, click safe controls, type in synthetic forms and exercise
   relevant keyboard/focus and responsive states. Capture screenshots during
   interaction, not only the resting view. Include the real parent composition
   where nested layout matters. No product-source changes in this stage.
2. **Review and propose.** The Reviewer opens the actual images and inspects the
   interaction/DOM evidence. Rate applicable dimensions from 0 to 10, with 10
   better, using the frozen anchors. Every finding identifies its state, evidence
   and user impact. Propose a small ranked batch; distinguish defects, heuristic
   concerns and subjective style preferences. Do not claim UX or accessibility
   was verified solely from a screenshot.
3. **Assess and select.** Plan-inline checks evidence and relevant source, then
   weighs impact, effort, risk, scope and fit to the brief. Reject speculative
   polish and unnecessary machinery. Return the selected changes, precise source
   targets, short implementation steps and acceptance checks inline, not a plan
   file. Include a Method Signature Surface, or state that no signatures change.
   An empty worthwhile subset is a valid early-convergence result.
4. **Implement and verify.** The implementation Build changes only the selected,
   authorized slice. Reproduce the same viewports, synthetic data and interaction
   states with Playwright, take new screenshots and exercise the affected actions.
   Check relevant focus, errors, responsive behavior and console/runtime failures.
   Keep source, generated artifact, served revision and visible result distinct;
   an isolated build is not proof the running app changed. Load existing skills
   rather than copying their helpers or creating permanent tests by default.
5. **Close the comparison.** Return the after-evidence to this round's Reviewer
   for post-change ratings and regression assessment. Continuing that same
   Reviewer within the round is allowed; never carry its session into another
   round. Use the same anchors and state coverage. Report observed improvement,
   neutrality or regression honestly; implementation alone does not prove better
   scores. This comparison is not another improvement round.

Browser actions must use permitted synthetic/disposable identities and data.
Opening a destructive confirmation is not permission to commit it. Do not send
messages, make purchases, delete real records or bypass access controls to test
a control. Keep other collaborators' edits and shared defaults outside the slice.

## Budget, failures and stopping

Each attempted improvement batch consumes one round, including a failed batch.
Do not add uncounted redesign/retry cycles. Minor in-scope repairs follow existing
policy; substantial verification gaps or unsafe regressions stop the loop and
require a decision. Never reset a checkout or discard unrelated work to roll back.

Repeat with fresh role sessions until the requested limit, no worthwhile changes,
a user stop/steering instruction, or a concrete blocker. Report the actual number
of attempted and verified rounds and the reason for stopping. Never manufacture
changes merely to exhaust the budget or mark a blocked round as passed.

## Evidence and final report

Use the project's permitted artifact location; otherwise use
`.project/reviews/webapp-loop/<target-slug>-<run-id>/`. Keep before/after images,
state labels, browser evidence and a concise round summary. Plan-inline remains
read-only; the coordinator or Build owns permitted artifact writes.

Return:

- Target, attempted/verified rounds, stop reason and changed source paths.
- Baseline/final per-dimension scores with evidence and unverified areas.
- Before/after screenshots for corresponding interaction states and viewports.
- Selected improvements, observed behavior changes, regressions and remaining
  worthwhile work. A higher average never cancels a critical failure.

Do not claim this skill certifies WCAG compliance, real-user usability or overall
code quality. The evidence supports only the inspected target, states and scope.
