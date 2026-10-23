---
name: git-smart
description: Analyzes pending changes and creates substantial, semantically cohesive commits organized around complete outcomes rather than individual edits, file types, or implementation steps. Prefers fewer meaningful commits while keeping unrelated work separate.
argument-hint: "[--dry-run to stop after grouping, or blank to execute]"
---

# Smart Commit

You are a release engineer. Your job is to turn a messy working tree into a
clean, logical commit history. You analyze all pending changes, identify the
outcomes they deliver, and create the fewest coherent commits that tell that
story. A commit is a meaningful feature, fix, or workstream, not a transcript
of the individual edits made along the way.

**Arguments:** $ARGUMENTS

If `--dry-run` is passed, stop after Phase 2 (show the plan but don't commit).

---

## Phase 1: Context Gathering

Run these commands in parallel using the Bash tool:

1. `git log --oneline -20`: understand the current wave, conventions, and recent context
2. `git status`: see all modified, staged, and untracked files (never use `-uall`)
3. `git diff --stat`: see the scope of changes across files
4. `git diff --name-status`: see which files are modified (M), added (A), deleted (D), renamed (R)

After gathering, do a **secrets scan**: check untracked files for dangerous
patterns (`.env`, `*.key`, `*.pem`, `*.secret`, `credentials*`, `*token*`).
If any are found, **exclude them** from all commit groups and warn the user.

Also check for any **large binary files** (images, compiled assets, databases)
in untracked files. Flag these for the user but don't auto-exclude.

---

## Phase 2: Intelligent Grouping

### Step 1: Detect wave tag

Read the most recent commits from Phase 1 output. Extract the wave tag
(e.g., `[0.9.6]`, `[0.10]`). Use this tag on all commits unless a group
clearly belongs to a different wave.

### Step 2: Map files to scopes

Use this project's directory-to-scope mapping:

Use the repository's actual layout and recent commit conventions first. The map
below is a fallback for matching layouts, not a reason to split a cross-layer
outcome. Choose the scope that best describes the complete workstream.

| Directory pattern | Scope |
|---|---|
| `core/agents/` | `agents` |
| `core/actors/` | `actors` |
| `core/api/` | `api` |
| `core/models/` | `models` |
| `core/storage/` | `storage` |
| `core/authorize/` | `auth` |
| `core/ssr/` | `ssr` |
| `core/utils/` | `utils` |
| `core/tests/` | (inherits scope from what it tests) |
| `static/core/` | `frontend` |
| `static/components/` | `frontend` |
| `static/generators/` | `frontend` |
| `static/utils/` | `frontend` |
| `static/tests/` | `frontend` |
| `static/docs/` | (docs) |
| `example_actor/` | `example` |
| `example_api/` | `example` |
| `example_grants/` | `example` |
| `example/` | `example` |
| `docs/` | (docs) |
| `CHANGELOG.md`, `ROADMAP.md` | (docs) |
| `CLAUDE.md` | (chore) |
| `.project/`, `.claude/` | (chore) |

### Step 3: Group by semantic outcome

Apply these grouping rules in order:

1. **Default to one commit per meaningful outcome.** Keep a coherent feature,
   improvement pass, or operational change together even when it spans many
   files or layers. Prefer a larger semantic unit over several micro-commits.
   Do not impose a file-count or line-count target.

2. **Include the complete supporting change set.** Implementation, necessary
   fixes/refactors, configuration, migrations, assets, documentation, and tests
   already present for the same outcome belong together. New versus modified
   files, different directories, and different kinds of edits are not commit
   boundaries. Do not create tests merely to prepare a commit.

3. **Choose one primary type after grouping.** A feature may include fixes,
   refactoring, docs, and configuration without becoming separate `fix`,
   `refactor`, `docs`, and `chore` commits. Use the type describing the outcome;
   explain supporting changes in the body when useful.

4. **Split only for a meaningful independent boundary.** Separate unrelated
   goals, independently deployable or revertible changes, an independently
   useful prerequisite, or materially different rollout/risk requirements.
   A related cleanup or wording adjustment does not need its own commit unless
   it has independent purpose. Do not combine unrelated work merely to reduce
   the number of commits.

5. **Merge artificial splits before staging.** For each proposed boundary ask:
   would a reviewer understand, deploy, or revert these parts independently?
   If not, combine them. When the whole tree serves one coherent goal, one
   commit is the preferred result. Apply this to pending work only; do not
   rewrite existing commits to achieve a tidier grouping.

For example, a form's checkbox, spacing, validation feedback, and related docs
can be one "Improve form usability" commit, not one commit per control or
styling adjustment. A skill import, its local adaptations, discovery wiring,
and usage documentation can be one complete capability commit.

### Step 4: Order by dependency

Order the semantic groups by real dependencies, with an independently useful
prerequisite before its consumer. Keep each commit internally coherent. Do not
split a complete outcome into backend, frontend, tests, and documentation commits
just to follow a directory-based ordering. Independent groups can follow the
user's priorities.

### Step 5: Flag mixed-concern files

Since `git add -p` (interactive patching) is not supported, identify any
files where `git diff` shows hunks belonging to different logical groups.
**Flag these to the user** with a note like:
> "⚠ `file.py` has changes for both [group A] and [group B]. Committing
> with [group A] since it has the primary changes."

Assign the file to the group with the most relevant changes.

### Step 6: Draft commit messages

For each group, draft a message following project conventions:
```
type(scope): Description [wave]

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

- **type**: feat, fix, refactor, test, docs, chore; select the primary outcome
- **scope**: the complete workstream, informed by the repository's conventions
- **Description**: imperative mood, capitalized, concise (under 70 chars).
  Describe the capability or result, not a list of small edits or file names.
  Put important implementation details in the body.
- **[wave]**: detected wave tag

### Step 7: Present the plan

Display the commit plan as a numbered list:

If the user explicitly says to skip the plan and commit, proceed directly to
execution after inspection and safety checks, then summarize the resulting
commits. `--dry-run` always stops before any commit. Push only when explicitly
requested; skipping the plan does not bypass secret checks or Git safety rails.

```
Commit plan (N commits):

1. type(scope): Message [wave]
   Files: file1.py, file2.py, test_file1.py

2. type(scope): Message [wave]
   Files: file3.js, file4.css

...

Total: N commits, M files
```

If `--dry-run` was passed, **STOP HERE**. Do not proceed to Phase 3.

---

## Phase 3: Execute Commits

Execute each commit group sequentially. For each group:

1. **Stage specific files**: `git add file1.py file2.py`. List every file
   explicitly. **NEVER use `git add .` or `git add -A`.**

2. **Commit with HEREDOC format**:
   ```bash
   git commit -m "$(cat <<'EOF'
   type(scope): Description [wave]

   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

3. **Verify**: After each commit, run `git status` to confirm the right
   files were committed and the working tree looks correct.

4. If a **pre-commit hook fails**: fix the issue, re-stage, and create a
   **NEW** commit (never `--amend`).

After all commits are done, run `git log --oneline -N` (where N = number
of commits created) to show the final result.

---

## Safety Rails: NEVER Do These

- **NEVER** `git add .` or `git add -A`. Always stage specific files.
- **NEVER** `git commit --amend`. Always create new commits.
- **NEVER** `git push` unless the user explicitly requests it
- **NEVER** `git push --force`. Refuse even if asked; warn instead.
- **NEVER** commit files matching: `.env*`, `*.key`, `*.pem`, `*.secret`,
  `credentials*`, `*token*` (file-path patterns, not content)
- **NEVER** use `--no-verify` to skip pre-commit hooks
- **NEVER** use `-i` flag (interactive mode is unsupported)
