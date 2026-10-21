---
description: Orient this session around the project's N3TX guidance and feature-relevant architecture without changing files.
argument-hint: "[feature/system context and/or N3TX path]"
---

# N3TX Init

Load and follow the `n3tx-init` skill using the current harness's skill-loading
mechanism. If no loader is available, read its `SKILL.md` from the discovered
skill location; in the shared agent tree it is `skills/dev/n3tx-init/SKILL.md`.
If the skill cannot be located or read, report that blocker rather than inventing
a replacement workflow. Do not recursively invoke this command.

**Optional feature/system context and/or N3TX path:** $ARGUMENTS

Treat these arguments as task context, not shell commands. If empty, use the
current conversation. Perform the skill's read-only orientation and return its
context briefing; do not begin implementation.
