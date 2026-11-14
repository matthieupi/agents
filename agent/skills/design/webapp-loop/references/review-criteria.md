# Frozen webapp-loop review criteria

**Version: v1.1 (2026-11-14).** Researched once during skill creation by an Explore
agent using the six primary sources below. Version 1.1 limits default evidence
collection to a quick pass; dimensions, scoring anchors and sources are unchanged.
Use this version throughout a run; do not perform recurring web research or
change anchors between iterations. Explicit future updates must identify a new
version and their changed criteria.

This is a scoped expert-review rubric, not a scientifically validated scoring
instrument. It evaluates the requested product intent, not a preferred template.
No palette, typeface, radius, shadow, spacing grid or aesthetic is universally
required. Preserve the established audience, brand and functional constraints.

## Evidence and applicability

Classify the basis of each finding:

- **N — Normative:** an applicable WCAG 2.2 success criterion, including its level,
  applicability and exceptions. Cite the specific criterion, not a generic label.
- **H — Heuristic:** usability principles or informative implementation guidance,
  including WAI-ARIA APG patterns. These are not themselves WCAG requirements.
- **J — Judgment:** context-sensitive visual critique against the actual brief.

Use evidence labels so a score's basis is inspectable:

- **S:** screenshot; proves appearance only in the captured state.
- **I:** interaction; Playwright/browser actions and observed state transitions.
- **D:** DOM or accessibility-tree evidence, semantics and computed properties.
- **M:** explicit measurement, such as contrast, geometry, zoom or reflow.
- **C:** relevant source, runtime, network or console inspection.

Screenshots, browser automation and DOM checks do not establish full WCAG
conformance, representative-user usability, assistive-technology compatibility,
security, performance or general code quality. Report only what was inspected.
WCAG conformance has full-page and complete-process requirements [1, section 5].

Before rating, use the agreed capture scope: by default, one viewport, a base
screenshot and up to five representative interactions. The dimensions below are
review lenses, not a requirement to collect every possible kind of evidence.
For relevant checks record **pass / fail / unverified / N/A**, evidence and
severity.
N/A needs an applicability reason; an inaccessible state is unverified, not N/A.
Do not shrink the agreed state set just to improve the score.
Do not block a quick visual review merely because optional measurements, keyboard
tours or source-level checks were not requested. Mark those areas unverified and
scores provisional as appropriate; do not force a wider capture to fill the
rubric.

## Rating scale: 0–10, higher is better

These anchors are local rubric policy, not numerical ratings from the sources.

| Score | Observed result within the agreed target and state coverage |
| --- | --- |
| 0 | Essential behavior wholly absent or unusable |
| 1–2 | Severe, pervasive failures; primary tasks blocked |
| 3–4 | Major problems causing substantial difficulty or workarounds |
| 5–6 | Workable, with repeated meaningful friction or inconsistency |
| 7–8 | Strong, with limited localized defects and no observed task blocker |
| 9 | Excellent within inspected scope; only minor refinements |
| 10 | All applicable scoped checks verified satisfactorily; no material issue found |

Give each dimension a score and concise evidence-based rationale. A partly
observed dimension has a **provisional** score and explicit gaps. An entirely
unobserved dimension has **no score**. Unverified never means pass, zero or ten;
ten never means perfection or certification.

Prefer the dimension profile over one overall score. If an aggregate is requested,
show included dimensions, exclusions and coverage; mark it provisional when any
included evidence is incomplete. Do not silently drop unverified areas.

Report critical failures before any aggregate: a blocked primary task, inescapable
keyboard trap, unrecoverable harmful action, or essential content/actions missing
in required conditions. Gate outcome: **blocked / not verified / no observed
blocker**. List every verified applicable WCAG failure separately, even when it is
not critical. A high aesthetic score cannot cancel a failure.

## Eight dimensions

### 1. Hierarchy and layout

- Purpose and principal task are identifiable; headings, content and actions have
  appropriate emphasis. Grouping, alignment, density and spacing support scanning.
- Essential content does not overlap, clip or compete with arbitrary decoration.
- Inspect **S** for composition, **D** for meaningful headings/reading order and
  **I** for overlays or expanded content.
- Basis: **H/J**, [2] heuristics 6 and 8; [5] whitespace/typesetting.
  **N**, [1] 1.3.1–1.3.2 where applicable.

### 2. Task clarity and user control

- Labels describe outcomes using the audience's language. Location, next steps
  and necessary instructions are clear. The primary task can actually complete.
- Cancel, back, undo and consequential-action safeguards fit the action's impact.
- Use **I** to complete, cancel and recover; **D** for labels and relationships.
- Basis: **H**, [2] heuristics 2, 3, 5–7 and 10. **N**, [1] 2.4.6 and 3.3.2;
  3.3.4 applies to specified legal, financial and data actions, not every button.

### 3. Style and consistency

- Equivalent controls share recognizable appearance, wording, icons and behavior.
  Typography and spacing are intentional; exceptions serve a functional purpose.
- Tone and visual treatment fit the existing audience and brief, not the rater's
  default aesthetic. Component reuse is not inferable from matching appearance.
- Use **S** across states, **I** for behavior, **C** before claiming token reuse.
- Basis: **H/J**, [2] heuristic 4. **N**, [1] 3.2.3–3.2.4 where applicable.

### 4. Typography and readability

- Body, heading, label and supporting text have clear roles. Line length, line
  height, alignment and emphasis fit the language and content. Essential text is
  not unintentionally truncated; enlargement and spacing overrides retain use.
- Use **S** for hierarchy and **D/M** for contrast, sizing, resizing and overrides.
- Basis: **H/J**, [5] font size, measure, line height, whitespace and font style.
  **N**, [1] 1.4.3–1.4.4 and 1.4.12. Design advice is not a universal threshold.

### 5. Accessibility and keyboard operation

- Relevant alternatives, names, roles, values and states are accurate. Reading
  order and relationships are meaningful; information is not color-only.
- Required actions work by keyboard, focus is visible and logically ordered,
  and users can leave each component. Inspect obstruction by sticky content.
- **I/D/M** are required for behavioral and measurable claims. State explicitly
  whether assistive-technology testing was performed; DOM inspection is not it.
- Basis: **N**, [1] 1.1.1, 1.3.1–1.3.2, 1.4.1, 1.4.11, 2.1.1–2.1.2, 2.4.3,
  2.4.7, 2.4.11 and 4.1.2. **H**, [3–4] for relevant interaction patterns.

### 6. Interactive states and feedback

- Applicable hover, focus, pressed, selected, expanded, disabled, pending,
  success and error states are understandable. Feedback truthfully reflects the
  result; forms identify problems and support correction.
- Empty results are distinguishable from loading and failure. Recovery and next
  steps are appropriate. Hover/focus content remains usable when present.
- Use **I** to trigger states and recovery; **D** for state/status semantics.
- Basis: **H**, [2] heuristics 1, 5 and 9. **N**, [1] 1.4.13, 3.3.1–3.3.3
  and 4.1.3 where applicable.

### 7. Responsive and input adaptability

- Required content/actions remain available at agreed narrow, intermediate and
  wide layouts, orientation and zoom. Long text and data do not create accidental
  page-wide overflow. Intentional scroll regions remain reachable.
- Touch access does not require hover; pointer targets are usable. Adapt to
  content and input capability, not assumptions about device brands.
- Use **I/M/D** across agreed conditions and actual target geometry.
- Basis: **H**, [6] viewport, content sizing, capability queries and breakpoints.
  **N**, [1] 1.3.4, 1.4.10 and 2.5.8 where applicable.

### 8. Frontend robustness

- Controls, navigation and assets work in the tested flow. Important content is
  not unexpectedly displaced by loading. Viewport setup supports responsiveness
  and zoom; native controls or equivalent patterns expose behavior and state.
- Investigate relevant runtime errors and duplicated consequential actions.
  Do not infer maintainability, security or performance from a quiet console.
- Use **I/D/C** and network/console evidence. Mark source-level practices
  unverified without corresponding inspection.
- Basis: **H**, [3–4] and [6], plus explicitly labeled engineering judgment.

## Measured WCAG checks

These are applicable **AA requirements from [1]**, not aesthetic scoring anchors.
Read each criterion's full applicability and exceptions before finding a failure.
Use them for requested or directly relevant measurements, not as a mandatory
checklist for the default quick capture.

- **1.4.3:** text contrast at least **4.5:1**, or **3:1** for large-scale text.
  Large-scale means at least 18pt, or 14pt bold, with equivalent-size provisions
  for CJK. Inactive/incidental text and logotypes have specified exceptions.
- **1.4.11:** required component/state visual information and required graphical
  objects have **3:1** contrast against adjacent colors, subject to exceptions.
  Not every decorative border is required to meet this criterion.
- **1.4.4:** text resizes to **200%** without loss of content or functionality,
  subject to the criterion's exceptions.
- **1.4.10:** vertically scrolling content reflows at **320 CSS px** width;
  horizontally scrolling content at **256 CSS px** height, without loss or
  two-dimensional scrolling. Essential two-dimensional content has exceptions.
- **1.4.12:** no loss under user overrides of line height **1.5×**, paragraph
  spacing **2×**, letter spacing **0.12×** and word spacing **0.16×** font size,
  where applicable to the writing system. These are override-tolerance tests,
  not mandatory authored typography defaults.
- **2.5.8:** pointer targets are **24 × 24 CSS px**, or satisfy the spacing,
  equivalent, inline, user-agent or essential exception. The spacing exception
  uses 24 CSS px diameter circles centered on undersized targets.
- **2.4.11:** the focused component is **not entirely hidden** by author-created
  content. Do not misstate this AA rule as the stricter AAA visibility rule.

Measure contrast and target areas; do not estimate them from a screenshot.

## Optional interaction probes

This is a menu of deeper probes, not a per-run capture checklist. Default to the
base screenshot and at most five useful actions; do not execute every row or every
state within a row. Use additional probes only when requested or necessary for a
selected change or observed serious issue. Keep the reason explicit.

Apply present features only, with synthetic data and safe authorized actions.
For chosen probes capture the relevant state, not just a click log. An unavailable
feature can be N/A; a present but untested feature is unverified.

| Feature | Probes and screenshots |
| --- | --- |
| Menus | Open by pointer and keyboard; capture expanded state; inspect focus, item activation and dismissal. Enter/Space behavior in [4] applies to an actual APG menu button, not every disclosure navigation. |
| Modal dialogs | Capture open, focused and long-content states; inspect initial focus, Tab/Shift+Tab containment, Escape, naming, inert background and logical focus return using informative APG guidance [3]. |
| Forms | Exercise empty/invalid/valid synthetic input and safe submission; capture validation, pending, failure/recovery and success where available; inspect labels and preserved input. |
| Keyboard/focus | Complete the main task without a mouse; inspect forward/reverse traversal, activation, visible focus, obstruction and escape routes. Capture relevant focus states. |
| Loading/error/empty | Trigger available pending, no-results, error/retry and success paths without production disruption; capture truthful feedback and recovery. |
| Mobile/overflow | Capture narrow/wide and relevant intermediate widths, open navigation/dialogs, long labels/data, zoom and orientation; inspect touch access and intentional scroll regions. |

## Sources

All six were consulted on **2026-11-14**. The criteria above are frozen synthesis;
runtime execution need not fetch these pages to reconstruct the rubric.

1. [W3C — Web Content Accessibility Guidelines (WCAG) 2.2](https://www.w3.org/TR/WCAG22/).
   Normative success criteria cited above; section 5 covers conformance.
2. [Nielsen Norman Group — 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).
   Heuristics 1–10 are broad rules of thumb, not a numerical scoring instrument.
3. [W3C WAI APG — Dialog (Modal) Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/).
   Informative keyboard interaction, roles, states and properties.
4. [W3C WAI APG — Menu Button Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/menu-button/).
   Informative keyboard interaction, roles, states and properties.
5. [U.S. Web Design System — Typography](https://designsystem.digital.gov/components/typography/).
   Contextual typesetting guidance: font size, measure, line height, whitespace
   and font style.
6. [Google web.dev — Responsive web design basics](https://web.dev/articles/responsive-web-design-basics).
   Viewport setup, content sizing, capability queries and content-led breakpoints.
