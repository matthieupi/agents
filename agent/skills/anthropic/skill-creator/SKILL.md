---
name: skill-creator
description: Create, revise, and evaluate reusable OpenCode skills when the user asks for skill authoring, skill benchmarks, or description-trigger tuning. Use for an existing SKILL.md or a workflow the user explicitly wants turned into a skill, not ordinary implementation or document editing.
---

# Skill Creator for OpenCode V2

Create and revise skills with proportionate review. Use one-off validation during
setup; run evaluations only when relevant to setup or explicitly requested.
Adapted from Anthropic's skill-creator; retain `LICENSE.txt`. See
`OPENCODE_PORT.md` for source-change notices, runtime contracts, and limitations.

## Choose the right starting point

- New skill: capture intent, draft, and perform relevant one-time setup checks.
- Existing skill: inspect the affected instructions and resources, edit, and
  review the result directly. Do not automatically create tests or run benchmarks.
- User wants discussion only: do not force benchmarks or paid calls.
- Description tuning: finish the skill first, then offer the separate trigger
  optimization workflow below. Get approval for model-call cost and concurrency.

Explain technical terms according to the user's familiarity. Show reviewable
changes rather than silently rewriting or installing an existing skill.

Skills do not need a standing maintenance test suite. The evaluation tools below
remain available for initial setup and explicit benchmarking requests; they are
not a mandatory phase for routine edits. Keep one-off checks/results in a scratch
workspace rather than adding permanent test files or fixtures to the repository
unless the user asks for them.

## Capture intent and research

1. What should the skill enable the agent to do?
2. When should it load, and what adjacent requests should **not** load it?
3. What output format, inputs, dependencies, and edge cases matter?
4. What would demonstrate success? Suggest measurable assertions for deterministic
   tasks and human review for subjective outputs.

If the conversation already contains a workflow, extract the tools, order,
corrections, and input/output formats before asking the user to repeat them.
Confirm the intended scope before writing test prompts. Research available tools,
MCP integrations, and similar skills as needed. For OpenCode mechanics, load the
`opencode` skill and use only the official V2 documentation.

## Write the skill

Installable layout:

```text
.opencode/skills/my-skill/
  SKILL.md
  scripts/       # deterministic helpers
  references/    # documentation read on demand
  assets/        # templates and output resources
```

The directory basename determines the ID: `teams/release/SKILL.md` has ID
`release`. `name` is a display label, not the ID. Prefer unique lowercase
kebab-case IDs, 1-64 characters. Global installation uses
`~/.config/opencode/skills/<id>/` (or `$XDG_CONFIG_HOME/opencode/skills/<id>/`).
Never change an existing directory ID accidentally or overwrite an installed
skill without approval. Work on a writable copy if necessary.

```yaml
---
name: Release Review
description: Review release readiness and migration notes when the user asks for a release review.
---
```

The model sees permitted IDs, display names, and descriptions. It loads the body
through the native `skill` tool with `{"id":"release"}`. Supporting resources
are not automatically read; paths in the body resolve relative to the skill's
base directory. `metadata.opencode/autoinvoke: false` hides a skill from automatic
discovery but does not unregister it. `compatibility` and `license` are portable
metadata; they do not configure tools or permissions.

### Writing principles

- Put what the skill does and when to use it in the description. Cover relevant
  intent clearly, without claiming every related keyword or hijacking other work.
- Prefer concrete steps and explain why they matter. Avoid needless MUSTs,
  overfitted examples, hidden side effects, and instructions to bypass permissions.
- Keep the body under roughly 500 lines. Move domain-specific detail into clearly
  linked references, with a table of contents for long files.
- Use examples for output conventions. Bundle repeated scripts instead of making
  each evaluator recreate them. Read only the references relevant to the task.
- Do not create misleading skills, unauthorized access workflows, or covert data
  transfers. Make actions and approval boundaries clear to the user.

## Optional setup validation or requested output evaluation

When output evaluation is warranted and approved, draft 2-3 realistic prompts and
ask the user to review them. Save `evals/evals.json` in the evaluation workspace
with the structure in `references/schemas.md`:

```json
{
  "skill_name": "my-skill",
  "evals": [{
    "id": 1,
    "prompt": "A realistic task with concrete inputs",
    "expected_output": "The desired artifact and qualities",
    "files": [],
    "expectations": []
  }]
}
```

Put results in a sibling `<id>-workspace/iteration-N/`. Use an `eval-` directory
prefix so the aggregation script finds them:

```text
iteration-1/eval-1-table-extraction/
  eval_metadata.json
  with_skill/run-1/{outputs/,transcript.md,grading.json,timing.json}
  without_skill/run-1/{outputs/,transcript.md,grading.json,timing.json}
```

`eval_metadata.json` records `eval_id`, `eval_name`, `prompt`, and `assertions`.
The eval set uses `expectations`; copy these into metadata's `assertions` field.

### 1. Launch independent runs and baselines

Use the native `subagent` tool with an available agent, a concise description,
and a self-contained prompt; set `background: true`. Include the task, exact
skill path/ID, inputs, output directory, and required artifacts. Each writer owns
a separate run directory. Observe the active agent's permission and depth limits.
Do not invent tool names or assume a fixed set of agent IDs.

With-skill prompt shape:

```text
Execute the following task using the skill at <path>.
If it is registered, load skill with {"id":"<id>"}; otherwise read this exact
SKILL.md and resolve its references relative to that directory.
Task: <prompt>
Inputs: <files>
Save artifacts to: <run>/outputs/
Save an execution transcript to: <run>/transcript.md
Do not change the skill or another run's files. Respect all tool permissions.
```

- New skill baseline: same task without the skill. A shared parent environment
  can still advertise installed skills; instruct the agent not to load the target
  and inspect the transcript. If it loads it, the baseline is contaminated and
  must be rerun in a separate workspace where that skill is denied.
- Existing skill baseline: snapshot the old directory before editing and give the
  baseline its exact snapshot path, saving to `old_skill/run-1/`. Do not rely on
  the live registered ID, which would load the new version.
- Start independent pairs concurrently when capacity permits. Do not wait for an
  entire batch before grading a completed run. Never poll or sleep awaiting native
  background agents: completion notifications resume the conversation. Continue
  independent work, or report what is running and end the response.
- If subagents are unavailable, run sequentially and label this a weaker,
  context-contaminated sanity check. Do not claim blind or independent baselines.

### 2. Draft assertions while runs execute

Use objectively verifiable expectations with descriptive text. Prefer executable
checks to eyeballing files. Explain what each assertion checks to the user. Do
not force quantitative grading onto subjective criteria better reviewed by humans.

### 3. Record honest timing and usage

Capture start/end times with a clock. If measured, save duration and its source in
`timing.json`. A parent-observed duration may include scheduling/notification
latency; label it accordingly. Native completion notifications are **not** assumed
to contain tokens or duration. Record token totals only from actual runtime usage
data with a documented definition; otherwise use `null`. Characters are not tokens.

```json
{"total_duration_seconds": 23.3, "total_tokens": null, "timing_source": "parent wall clock"}
```

### 4. Grade, aggregate, and review

1. Read `agents/grader.md`. Grade each finished run, inline or via a native
   background agent. Write `grading.json` alongside `outputs/`; expectations use
   exactly `text`, `passed`, and `evidence`.
2. From this skill-creator directory run:
   `python3 -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <id>`.
   It produces `benchmark.json` and `benchmark.md`; missing usage stays unknown.
3. Read the benchmark-analysis section in `agents/analyzer.md` for non-discriminating
   assertions, flaky cases, and time/usage trade-offs. Do not infer unknown metrics.
4. Generate the bundled viewer before revising the skill. In headless environments:

```sh
python3 <skill-creator-path>/eval-viewer/generate_review.py <workspace>/iteration-N \
  --skill-name <id> --benchmark <workspace>/iteration-N/benchmark.json \
  --static <workspace>/iteration-N/review.html
```

For iteration 2+, add `--previous-workspace <workspace>/iteration-<N-1>`.
Without `--static`, the script serves on loopback and opens a browser. Run it with
the shell tool's background facility if available; stop only that server when done.
Static review works without a server; spreadsheet rendering needs its external
SheetJS dependency, but downloads remain available offline.

Tell the user where the HTML is and how to view Outputs and Benchmark tabs.
"Submit All Reviews" saves feedback on the server or downloads `feedback.json` in
static mode. Ask the user for the actual downloaded file and place it in the
iteration directory; do not assume access to their local Downloads folder.
Wait for review, then read feedback. Empty feedback counts as acceptance only for
reviews the user actually submitted, not missing or unreviewed runs.

### 5. Improve and repeat

Generalize from failures rather than patching individual prompts. Read transcripts
as well as outputs: remove wasted steps, clarify intent, and bundle repeated work.
Rerun both configurations into a new iteration directory, show previous outputs
and feedback, and repeat until the user is satisfied or progress stalls. Report
limitations honestly. For optional blind A/B comparison, read `agents/comparator.md`
and the post-hoc portion of `agents/analyzer.md`; give comparators anonymous A/B
outputs and reveal skill versions only to the subsequent analyzer.

## Optimize description discovery

This is separate from full task execution. It measures whether a fresh OpenCode
session successfully loads the target through the native `skill` tool. It does not
count text mentions, file reads, failed tool calls, or partial argument streams.

1. Draft around 20 realistic queries, balanced between relevant requests and
   difficult near misses. Include varied language, detailed context, and adjacent
   tasks that should not load the skill. Do not assume any model always/never loads
   skills for simple tasks. Save `[{"query":"...","should_trigger":true}, ...]`.
2. Review with the user using `assets/eval_review.html`. Escape name/description
   for HTML and escape `<` as `\u003c` in JSON before replacing its placeholders.
   Write a local HTML file, share its path, and ask for the exported `eval_set.json`.
3. Confirm model, cost, and concurrency. Linux, Python 3.10+, PyYAML, OpenCode V2, and
   authenticated provider access are required. Use `provider/model#variant` from
   the session or model discovery; never guess an ID. Read `OPENCODE_PORT.md` for
   custom provider configuration and the isolated runner's limitations.
4. From this skill-creator directory, run using the shell tool's background mode:

```sh
python3 -m scripts.run_loop --eval-set <eval-set.json> --skill-path <skill-directory> \
  --model <provider/model#variant> --max-iterations 5 --num-workers 3 \
  --timeout 120 --results-dir <workspace>/description --no-open --verbose
```

Do independent work while it runs and consume its completion notification; do not
periodically poll or tail solely to wait. The loop uses stratified train/test
splitting, repeated trials, and held-out score selection, never feeding held-out
queries to the improvement model. Tiny sets retain training examples and may have
no holdout; report that limitation. A selection set is not an unbiased final test.

Each trial gets a disposable workspace/config with only the target skill permitted
and no side-effect tools. A neutral skill body stops task execution after loading.
The runner does not modify the live skill folder. Runtime/auth/process/timeout or
malformed-stream failures abort the batch, not count as successful non-triggers.
Interrupts and batch failures cancel queued trials and stop active CLI process
groups before returning. Already-submitted remote requests may still be charged.
The result measures this restricted environment, not competition with your complete
production skill catalog. Full task tests above remain necessary.

5. Show the original/proposed descriptions and scores. Apply `best_description`
   only with the user's approval. The script returns suggestions; it never edits
   SKILL.md automatically. Keep descriptions focused on relevant intent.

## Validate and deliver

Run `python3 -m scripts.quick_validate <skill-directory>`. Its portable authoring
checks are stricter than runtime discovery; OpenCode does not impose a 1024-character
description limit. The description optimizer uses that size as its own budget.

Deliver the complete directory and explain the project/global installation path.
After approval, copy it into the chosen skills folder without discarding existing
files. Verify the path-derived ID and native `skill {"id":"..."}` loading when
an interactive session is available.

`python3 -m scripts.package_skill <skill-directory> <output-directory>` remains
available for optional ZIP transport (`.skill`). It is **not** an OpenCode installer;
the user must review/extract it and install the directory. Preserve real licenses
and include source-change notices when adapting third-party bundles.
