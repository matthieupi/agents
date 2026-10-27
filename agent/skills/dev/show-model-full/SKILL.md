---
name: show-model-full
description: Show a model's full structure after tracing its parents, mixins and relevant relationships. Use for show-model full or @show-model-full; display compact stacked UML compartments, never side-by-side fields and methods.
---

# Show Model Full

Given a model/class name or source path, review its dependencies and show its
structure directly in chat. This is read-only: find, read, trace, display. Do not
edit files, run application code, generate helper scripts or turn it into an audit.

## Review

1. Locate the requested definition in the current project. Ask which one only
   when multiple matches remain ambiguous in context.
2. Read the definition and follow parent classes, relevant mixins and field
   injection declarations far enough to establish contributed fields and methods.
   Follow project guidance; do not crawl unrelated framework code.
3. Trace directly relevant references and embedded types so ownership and data
   flow can be shown. Verify cardinality and constraints; do not invent them.
4. Prefer source declarations. Consult an existing generated schema only when
   needed to resolve injection, identifying that evidence. Report missing parent
   source or uncertain injection briefly rather than inventing members.

## Diagram

- Use compact, vertically stacked model boxes with solid box-drawing borders
  (`┌─┐`, `│`, `├─┤`, `└─┘`) in a text code block.
- Each box has the model name, then fields, then method signatures, separated by
  horizontal rules. **Never use two columns for fields and methods.**
- Keep the requested model central. Connect relevant related models with arrows
  and concise relationship labels/cardinalities. Include only the related fields
  needed to explain that relationship, not every member of every dependency.
- Show the source path and a short inheritance chain above the diagram. Include
  inherited fields in the target box, labeling their declaring/injecting origin.
  Label inherited method groups by origin as well; omit empty groups.
- Show types, defaults and method parameters/returns where declared. Wrap long
  signatures within the box; omit bodies. Use the target language's notation.
- Show overridden members once at their effective owner. Distinguish runtime
  state, computed properties and class metadata from model data; annotations
  alone do not prove persistence.
- Keep framework plumbing subordinate to the model. Summarize routine inherited
  infrastructure unless explicitly asked for an exhaustive member inventory.
- Finish with only essential type aliases, constraints or uncertainty notes.

Example layout (illustrative, not a framework contract):

```text
Task - app/models/task.py
BaseRecord -> Task (+ TimestampMixin)

┌─────────────────────────────────────┐
│               Project               │
├─────────────────────────────────────┤
│ id: int                             │
└──────────────────┬──────────────────┘
                   1
                   │ owns
                  0..*
┌──────────────────┴──────────────────┐
│                Task                 │
├─────────────────────────────────────┤
│ id: int = 0            [BaseRecord] │
│ created_at: datetime   [Timestamp]  │
│ title: str = ''                     │
│ status: str = 'open'                │
│ project: Ref[Project]               │
├─────────────────────────────────────┤
│ [Task]                              │
│ complete(user: dict) -> dict        │
│ [BaseRecord]                        │
│ save() -> None                      │
└─────────────────────────────────────┘
```
