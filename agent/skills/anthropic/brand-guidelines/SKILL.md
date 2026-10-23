---
name: brand-guidelines
description: Apply Neuralys branding to interfaces, documents, presentations, diagrams, and other visual outputs. Use when the user requests Neuralys styling, brand colors, semantic status colors, corporate typography, or a brand-consistency review. Use emerald for primary/success, amber for secondary/warning, cyan for information, and coral for errors. Preserve an explicitly requested client brand instead of replacing it.
license: Complete terms in LICENSE.txt
---

# Neuralys Brand Styling

Locally adapted from Anthropic's brand-guidelines skill for Neuralys and OpenCode.
The license retains its original attribution; the visual identity below is Neuralys's,
not Anthropic's.

## Workflow

1. Identify the output, audience, light/dark mode, and whether Neuralys or a client
   brand applies. Preserve a client's explicitly requested identity.
2. Read the target project's existing design guide and semantic tokens before
   introducing new styles. Reuse those definitions rather than duplicating CSS.
3. Apply the palette by **meaning**, not by cycling accent colors decoratively.
4. Preserve the project's typography and component conventions. Use the defaults
   below only when no application-specific decision exists.
5. Render or preview the output where tooling permits. Check contrast, hierarchy,
   status labels, fonts, and mobile/print readability; report what was not checked.
6. Return the actual output paths and a concise explanation of any adaptations.
   OpenCode does not require a proprietary artifact or file-presentation tool.

## Colors

### Semantic accents

| Role | Color | Use |
|---|---|---|
| Primary / success | Emerald `#008f62` | Main action, brand identity, confirmed positive state |
| Primary light | Emerald `#40ab89` | Accent foreground on dark surfaces, lighter emphasis |
| Primary dark | Emerald `#006b49` | Darker emphasis or foreground on light surfaces |
| Secondary / warning | Amber `#f59e0b` | Secondary brand emphasis, caution, pending decision |
| Information / focus | Cyan `#38bdf8` | Informational signals and visible focus indicators |
| Error / destructive | Coral `#ffb4ab` | Error messages and destructive-state emphasis on dark surfaces |

Primary and success share a color family, as do secondary and warning; they are
not interchangeable meanings. An emerald primary button does not assert that an
operation succeeded. An amber highlight is not automatically an alert. Always
label actual status and use icons or text so meaning never depends on color alone.
Do not make every secondary control amber: routine Back, Cancel, or Refresh actions
should normally be quiet neutral controls.

### Dark surfaces and neutral text

| Role | Color |
|---|---|
| Background | `#141313` |
| Surface | `#191c1e` |
| Raised surface | `#2b2a2a` |
| Border | `#444748` |
| Primary text | `#e5e2e1` |
| Muted text | `#c4c7c7` |

For light documents and print, use white or the project's existing light surface
with charcoal text. Do not simply invert every token. Pale coral, cyan, and amber
are not suitable small text on white; use the project's accessible foreground
variants, a dark label on an accent fill, or a labeled neutral treatment.

### Contrast and implementation

- Target WCAG AA: at least **4.5:1** for normal text, **3:1** for large text and
  meaningful UI boundaries/focus indicators against adjacent colors.
- Base emerald is a brand color, not a guarantee of readable text on every
  surface. Prefer the lighter emerald for small dark-mode accent text and verify
  the actual foreground/background pair, including opacity and hover states.
- Treat the neutral border as decorative unless its contrast is sufficient for
  the control boundary. Never remove a visible keyboard focus indicator.
- Use existing semantic CSS variables or design-system tokens. For slides and
  documents, pass the same hex values through the library's native color API;
  for example `RGBColor.from_string("008F62")` in python-pptx. Do not introduce
  python-pptx merely to style an unrelated output format.

## Typography and composition

- Preserve the application's existing system sans-serif and monospace stacks;
  do not install or fetch fonts without permission. For standalone documents,
  use an available sans-serif (such as Arial) for headings/body and a monospace
  face for code or actual technical data.
- Older Neuralys design references specify Geist and JetBrains Mono. Use those
  only when the target already supplies them or the user requests that treatment;
  do not impose Anthropic's Poppins/Lora pairing.
- Establish clear title, section, body, and caption hierarchy. Keep long prose
  comfortably readable; uppercase mono labels belong to short technical metadata,
  not every paragraph.
- Prefer restrained charcoal surfaces, deliberate alignment, and emerald-led
  emphasis. Use a 4px spacing rhythm when designing new UI. Respect existing
  component geometry instead of forcing website-specific clipped shapes onto
  every application, document, or slide.
- Use one dominant accent per composition. Charts may use multiple colors when
  needed, with labels, patterns, or markers to preserve accessibility.
- Reuse approved logos unchanged. The Neuralys logo has its own charcoal/amber
  treatment; emerald primary UI styling is **not** permission to recolor it.

## Voice

Write clearly, practically, and without hype. Start with the reader's problem or
decision, distinguish facts from recommendations, and avoid unsupported promises
or claims of compliance. Branding is not evidence for a business claim.

## Source alignment

These local defaults derive from the Neuralys repository's
`shared/src/brand-tokens.css`, its existing `web/design-source/**/DESIGN.md`
references, and `docs/00-meta/writing-style-guide.md`. The shared color tokens
and the requested emerald-primary/amber-secondary semantics take precedence over
older template palettes that call metallic gray “primary.” The approved logo
reference is `web/design-source/logo_/LOGO.md`.

These are source references, not runtime dependencies: the skill works without a
sibling checkout. When editing a Neuralys project, read its current authoritative
tokens and documentation; if they differ from this summary, flag the discrepancy
instead of silently rewriting the application's design system.

## Reviewing changes

Review palette semantics, light-mode contrast, typography fallback, client-brand
boundaries, and logo use directly when updating this guidance. Do not create a
standing test suite or evaluation fixtures for routine skill edits. At initial
setup, a one-off rendered example can help verify readability; merely finding the
expected hex strings does not establish visual quality.
