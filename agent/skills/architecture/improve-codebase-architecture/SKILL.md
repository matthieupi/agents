---
name: improve-codebase-architecture
description: Explore a codebase to find opportunities for architectural improvement, focusing on making the codebase simpler by deepening shallow modules and removing bloat. Use when user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make a codebase more AI-navigable.
---

# Improve Codebase Architecture

Explore a codebase like an Architect would, surface architectural friction, discover opportunities for simplifying flows, mental models, reduce bloat and overengineering. Propose module-deepening refactors that would lead to simpler, less error prone, and

A **deep module** (John Ousterhout, "A Philosophy of Software Design") has a small interface hiding a large implementation. Deep modules are more testable, more AI-navigable, and let you test at the boundary instead of inside.

## Goal
- Improve developper velocity with targeted simplifying refactors.
- **REDUCE CODE ENTROPY** Code entropy, just like in physics, always grows. We aim to fight it. We aim to clean it up.
- Reduce code. Removing > adding.
- Think out of the box.
- Clean code, shallow modules, composable systems.

## Process

### 1. Explore the codebase

Use subagent_type=Explore to navigate the codebase naturally.

- Are there obvious code smell?
- Is there overcomplication/overengineering?
- Are we following the framework design or working against it? Things should be
  made simpler and complexity should be hidden behind simple (deep) modules by
  using the framework, not more bloated.
- Are there refactors that could significantly reduce line count / steps required
  for an operation.
- Where does understanding one concept require bouncing between many small files?
- Where do tightly-coupled modules create integration risk in the seams between them?
- Which parts of the codebase are untested, or hard to test?
- Large files / large functions are a red flag.
- Refactor and simplification opportunities.
- DRY

The friction you encounter IS the signal.

### 2. Present candidates

Present a numbered list of deepening opportunities. For each candidate, show:

- **Cluster**: Which modules/concepts are involved
- **Gains** What simplification, long term system improvements do we gain with this candidate
- **Tradeoffs**
- **Dependency category**: See [REFERENCE.md](REFERENCE.md) for the four categories
- **Test impact**: What existing tests would be replaced by boundary tests
- What can be removed

Do NOT propose interfaces yet. Ask the user: "Which of these would you like to explore?"

### 3. User picks candidates

### 4. Frame the problem space

Always use the Actor Model as the foundational architecture with
[actor-model](../actor-model/SKILL.md).
Consolidate schema knowledge across layers using
[sdd-skill](../sdd-skill/SKILL.md).

Before spawning sub-agents, write a user-facing explanation of the problem space for the chosen candidate:

- The constraints any new interface would need to satisfy
- The dependencies it would need to rely on
- A rough illustrative code sketch to make the constraints concrete (not a proposal, just a way to ground the constraints)

Show this to the user, then immediately proceed to Step 5. The user reads and thinks about the problem while the sub-agents work in parallel.

### 5. Design multiple interfaces

Spawn 3+ sub-agents in parallel using the Agent tool. Each must produce a **radically different** interface for target refactor candidate.

Prompt each sub-agent with a separate technical brief (file paths, coupling details, dependency category, what's being hidden). This brief is independent of the user-facing explanation in Step 4. Give each agent a different design constraint:

- Agent 1: "Minimize the interface: aim for 1-3 entry points max"
- Agent 2: "Maximize flexibility: support many use cases and extension"
- Agent 3: "Optimize for the most common caller: make the default case trivial"
- Agent 4 (if applicable): "Design around the ports & adapters pattern for cross-boundary dependencies"

Each sub-agent outputs:

1. Interface signature (types, methods, params)
2. Usage example showing how callers use it
3. What complexity it hides internally
4. Dependency strategy (how deps are handled; see [REFERENCE.md](REFERENCE.md))
5. Trade-offs

Present designs sequentially, then compare them.

After comparing, give your own recommendation: which design you think is strongest and why. If elements from different designs would combine well, propose an improved hybrid. Be opinionated. We are collaborating with the user, we need to share relevant information to get a shared understanding of the problem/scope/solution.

### 6. User picks an interface (or accepts recommendation)
