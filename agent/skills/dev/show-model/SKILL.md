---
name: show-model
description: Show a compact ASCII UML view of a named model or class, with fields grouped by declaring parent on the left and method signatures on the right. Use when asked for @show-model <model> or a quick model structure diagram.
---

# Show Model

Given a model/class name or source path, show its structure directly in chat.
This is a read-only utility: find, read, trace parents, display. Do not edit
files, run application code, generate helper scripts, or turn this into an audit.

1. Locate the requested definition in the current project. If several definitions
   match and context does not identify the target, ask which one.
2. Read the definition and follow parent classes and relevant mixins, including
   field-injection declarations, just far enough to identify contributed fields
   and methods. Follow applicable project guidance; do not crawl unrelated code.
3. Show one ASCII box: fields on the left, method signatures on the right. Group
   fields into labeled sections by their declaring class or injecting parent,
   including a section for the requested class's own fields. Label inherited
   method groups by origin too. List only actual contributions, not empty groups.
4. Add the source path and a short inheritance chain above the box. Show types,
   defaults, and method parameters/returns where declared; omit method bodies.
   Wrap signatures as needed. Keep the output compact and readable in a terminal.

Example layout (illustrative, not a framework contract):

```text
Task - app/models/task.py
BaseRecord -> Task (+ TimestampMixin)

+----------------------------------+--------------------------------------+
| Fields                           | Methods                              |
+----------------------------------+--------------------------------------+
| [BaseRecord]                     | [BaseRecord]                         |
| id: int = 0                      | save() -> None                       |
|                                  |                                      |
| [TimestampMixin: injected]       | [Task]                               |
| created_at: datetime             | complete(user: dict) -> dict         |
|                                  |                                      |
| [Task]                           |                                      |
| title: str = ''                  |                                      |
| status: str = 'open'             |                                      |
+----------------------------------+--------------------------------------+
```

Use the target language's native signatures. Identify overridden members once,
at their effective owner, noting the overridden parent if useful. Distinguish
instance fields from class/static metadata and computed properties; do not
present constants or framework configuration as persisted fields. Do not infer
persistence merely from an annotation.

Report missing parent source or uncertain dynamic injection briefly below the
diagram instead of inventing members. Prefer source declarations; consult an
existing generated schema only when needed to resolve injection, identifying
that evidence. Stop after the diagram and any essential caveat or source note.
