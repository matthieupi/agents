---
name: gsd:ralph
description: Run ralph autonomous loop on gsd project
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Task
  - TodoWrite
  - Skill
---

<objective>
Run a ralph loop to complete this project phase by phase. Each agent works autonomously, and when it finishes, its context is cleared and a fresh session starts for the next phase.

The ralph loop automates the progression through phases without requiring user validation at each step.

**CRITICAL: This is a FULLY AUTONOMOUS loop. Do NOT stop to ask the user what to do. IMMEDIATELY invoke the next skill when you determine what action is needed.**
**CRITICAL** Agent context should be /clear BEFORE EVERY RUN (each time it 
is called. Agents **must** always start in a fresh session with empty context.
**IMPORTANT**: Always use OPUS 4.5 When executing gsd-executor
</objective>

<execution_context>
@.planning/STATE.md
@.planning/ROADMAP.md
</execution_context>

<autonomy_prompt>
Never check with the user for validation. You are sufficiently competent (high pay grade) to make decisions and act on them. You are an expert in your field and have over 20 years of experience doing this. You know what you are doing.

When spawning agents, include (propagate) your autonomy directive:

"Never check with the user for validation. You are sufficiently competent (high pay grade) to make decisions and act on them. You are an expert in your field and have over 20 years of experience doing this. You know what you are doing."

When an agent finishes, check if there is another phase in line. If it does,
go ahead and re-run the appropriate command (usually provided in the last
executor's output)

DO NOT start ralph-sm or ralph-lg. We use GSD's workflow for this ralph loop.

When starting ANY agent, also add the subagent additional prompt (next 
section) in their initial prompt.
</autonomy_prompt>

<subagents_additionnal_prompt>
When doing infrastructure level development:
- When working on only one machine, manually restart only this machine, 
  instead of the whole stack, to validate your fixes are running, and only 
  once this seems right, then you can run the regular deployment.
- Same thing with playbooks, no need to restart the whole thing everytime at 
  first. This is our standard pipeline. We always run only on concerned 
  machines at first, and when it all works we do a dry-run to reprovision 
  everything:
    1. First make sure the current playbook you are working on runs properly.
       (on the machine you are working on, if there is no need to run it on 
       the entire inventory) 
    2. Then you can run and debug subsequent playbooks. (Still only on the 
       machine you need to properly validate) 
    3. Then you can run and debug the full playbook on the concerned machine.
    4. Then you can run and debug the full playbooks on all machines
    5. Finally we do a full dry-run, we reprovision everything in <dev> and 
       run the full playbook for final integration validation. (Go back to 
       relevant step if something breaks) 
</subagents_additional_prompt>

<process>
**Step 1: Load current position**

Read STATE.md and ROADMAP.md to determine:
- Current phase number (e.g., 02)
- Total phases remaining
- Current phase status (planned, in-progress, complete)

Report briefly:
```
Ralph Loop: Phase {phase_number} | {count} remaining
```

---

**Step 2: Determine and EXECUTE next action**

Based on current phase status, **IMMEDIATELY invoke the Skill tool**:

| Status | Action |
|--------|--------|
| No PLAN.md exists | `Skill(skill="gsd:plan-phase", args="{phase}")` |
| PLAN.md exists, no SUMMARY.md | `Skill(skill="gsd:execute-phase", args="{phase}")` |
| SUMMARY.md exists for all plans | Phase complete, advance to next phase and repeat |

**DO NOT** output instructions for the user. **DO** invoke the Skill tool immediately.

---

**Step 3: After skill completes, continue the loop**

When a skill returns (planning or execution complete):
1. Check if there's more work in current phase (more plans to execute)
2. If phase complete, advance to next phase
3. **Immediately invoke the next skill** - do not stop

Continue until all phases are complete or a blocker is encountered.

---

**Step 4: Loop termination**

Only stop when:
- All phases complete → Output: "RALPH LOOP COMPLETE - All phases executed"
- Blocker encountered → Output: "RALPH LOOP BLOCKED - {reason}"

If all phases complete:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 RALPH LOOP COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All phases executed. Project milestone finished.

Next: /gsd:audit-milestone or /gsd:complete-milestone
```

</process>

<success_criteria>
- [ ] Current phase identified from STATE.md
- [ ] Skill tool invoked IMMEDIATELY (not suggested)
- [ ] Loop continues automatically after each skill completes
- [ ] No user input requested between phases
- [ ] Loop terminates only when all phases complete or blocked
</success_criteria>
