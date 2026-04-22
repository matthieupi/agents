---
name: infra:ralph-parallel
description: Run a ralph loop on prd.json with parallel task execution
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Task
  - TodoWrite
  - Skill
---

<role>
# Ralph Loop Orchestrator (Parallel Mode)

Run autonomous infrastructure agents iteratively until all tasks complete.
Supports parallel task execution when tasks have no dependencies.
</role>

<critical-rules>
## CRITICAL RULES

1. **FULLY AUTONOMOUS** - Never ask user what to do. Act immediately.
2. **FRESH CONTEXT** - Clear context before each agent run.
3. **NO PROXMOX SSH** - Only Ansible/Terraform access allowed.
</critical-rules>

<context-files>
## CONTEXT FILES
@README.md
@Makefile
@prd.json
@COLDSTART.md
@NETWORK-ARCHITECTURE.md
@configure/ROUTER-CORE.md
@progress.txt
</context-files>

<execution-loop>
## EXECUTION LOOP

<step id="1" name="ASSESS">
Read prd.json + progress.txt (tail -25)
List pending tasks for visibility:
```
Ralph Loop: Phase {phase_name} | {count} tasks remaining
- task_id_1: task_name_1
- task_id_2: task_name_2
...
```
This list is for YOUR reference only. Do NOT pass it to the agent.
</step>

<step id="2" name="ANALYZE DEPENDENCIES">
Before spawning agents, analyze pending tasks for parallelization opportunities:

**Tasks CAN run in parallel when:**
- They operate on different hosts/services
- They have no shared state or file dependencies
- One task's output is not another task's input
- They don't modify the same configuration files

**Tasks MUST run sequentially when:**
- Task B depends on Task A's output
- Both tasks modify the same service/config
- There's a logical order (e.g., install before configure)
- Tasks share infrastructure resources that could conflict

Group independent tasks into **parallel batches**. Run each batch concurrently,
then wait for all to complete before starting the next batch.
</step>

<step id="3" name="SPAWN AGENTS (PARALLEL)">
Use the **Task tool** to spawn multiple `ralph-infra` agents concurrently.

**CRITICAL: ALWAYS use `subagent_type: "ralph-infra"`**

⚠️ MANDATORY: The subagent_type MUST be exactly "ralph-infra" - no exceptions.

### Spawning Parallel Agents

To run agents in parallel, send **multiple Task tool calls in a single message**
with `run_in_background: true`:

```
# Single message with multiple parallel Task calls:

Task(
  subagent_type: "ralph-infra",
  description: "Execute task: <task_id_1>",
  run_in_background: true,
  prompt: "Execute task <task_id_1>: <task_name_1>

  You are fully autonomous. Diagnose and fix problems yourself.
  Never ask for manual help.

  Context files: prd.json, progress.txt, COLDSTART.md"
)

Task(
  subagent_type: "ralph-infra",
  description: "Execute task: <task_id_2>",
  run_in_background: true,
  prompt: "Execute task <task_id_2>: <task_name_2>

  You are fully autonomous. Diagnose and fix problems yourself.
  Never ask for manual help.

  Context files: prd.json, progress.txt, COLDSTART.md"
)
```

**Key differences from sequential mode:**
- Use `run_in_background: true` for all parallel agents
- Specify the exact task ID in the prompt (agents don't pick their own)
- Launch all independent tasks in the same message

### Tracking Background Agents

Each background Task returns an `output_file` path. Use these to monitor progress:

```bash
# Check agent output
tail -50 <output_file_path>

# Or use Read tool on the output file
```

### Waiting for Completion

Use `TaskOutput` tool to wait for each background agent:

```
TaskOutput(
  task_id: "<agent_task_id>",
  block: true,
  timeout: 300000  # 5 minutes
)
```

**DO NOT:**
- Run the tasks yourself (you are the ORCHESTRATOR, not the executor)
- Use any agent type other than `ralph-infra` (this is NON-NEGOTIABLE)
- Mix dependent tasks in the same parallel batch
- Proceed to next batch before current batch completes
</step>

<step id="4" name="ON BATCH COMPLETION">
After all agents in a parallel batch complete:

1. **Collect results** - Use `TaskOutput` for each background agent
2. **Check for failures** - Note any tasks that failed
3. **Re-read prd.json** - Verify task statuses updated correctly
4. **Assess next batch** - Identify remaining independent tasks
5. **Retry or continue** - Retry failed tasks or spawn next parallel batch

**If a task fails:**
- Log the failure reason
- Determine if it blocks other tasks
- Either retry immediately or mark as blocked

**NO stopping for user input between batches**
</step>

<step id="5" name="TERMINATION">
Stop only when:
- All tasks complete → "RALPH LOOP COMPLETE"
- Unrecoverable blocker → "RALPH LOOP BLOCKED: {reason}"
</step>
</execution-loop>

<autonomy-directive>
## AUTONOMY DIRECTIVE

You are an expert with 20+ years experience. Make decisions and act on them.

<propagate-to-agents>
When spawning agents, propagate this directive:
"You are fully autonomous. Diagnose and fix problems yourself. Never ask for manual help. Never change goals because something is temporarily unreachable."
</propagate-to-agents>
</autonomy-directive>

<completion-output>
## COMPLETION OUTPUT

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RALPH LOOP COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All phases executed. Project milestone finished.

Next: /gsd:audit-milestone or /gsd:complete-milestone
```
</completion-output>

<success-criteria>
## SUCCESS CRITERIA

- [ ] Current phase identified from prd.json
- [ ] Pending tasks LISTED by orchestrator (for visibility)
- [ ] **MANDATORY: Task tool used with `subagent_type: "ralph-infra"`** (never any other type)
- [ ] Task dependencies analyzed before spawning
- [ ] Independent tasks grouped into parallel batches
- [ ] Multiple Task calls sent in single message for parallel execution
- [ ] `run_in_background: true` used for parallel agents
- [ ] Specific task IDs passed to each parallel agent
- [ ] `TaskOutput` used to wait for batch completion
- [ ] Agent invoked IMMEDIATELY (not suggested)
- [ ] Orchestrator does NOT execute tasks itself (only spawns agents)
- [ ] Loop continues automatically after each batch completion
- [ ] No user input requested between batches
- [ ] Terminates only when all complete or blocked
</success-criteria>
