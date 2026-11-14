---
name: actor-model
description: >-
  Use the Actor Model as the foundational architecture for planning, building,
  and reviewing software systems. Apply actor principles throughout the design
  and map them to the project's implementation, including N3TX ActorModel/TX/Matrix.
---

# Actor Model

The Actor Model is a mathematical model of concurrent computation introduced in 1973 that treats "actors" as the universal primitives of concurrent digital computation.

## Core Principles

• Independent Units (Actors): Each actor is an autonomous entity that encapsulates its own private state, behavior, and a message queue (mailbox).

• Asynchronous Message Passing: Actors do not share memory or call stacks. Instead, they communicate exclusively by sending asynchronous messages to each other's addresses (PIDs/references).

• Sequential Message Processing: An individual actor processes incoming messages one at a time from its mailbox in sequential order, eliminating the need for traditional lock-based synchronization and race conditions.

## What an Actor Can Do

When an actor receives a message, it can perform a combination of three basic actions:
1. Send finite messages to other actors it knows.
2. Create (spawn) new actors to delegate sub-tasks.
3. Designate its next behavior or modify its own internal private state for the next message it processes.

## Fault Tolerance & Supervision

• "Let it Crash": Instead of trying to defensively catch every unexpected error inside a single thread, actors are designed to fail fast and crash when encountering an invalid state.

• Hierarchical Supervision: Parent actors supervise child actors. If a child actor crashes, the parent supervisor intercepts the failure signal and can restart, stop, or escalate the fault according to a recovery strategy.

## Apply as the foundation

Always plan, build, and review through the Actor Model, not only messaging code.
Keep domain state, invariants, and behavior with their actor; compose systems
through explicit addressed operations rather than shared mutable state or a
parallel service/command architecture. Reuse the project's actor primitives.

The introduction combines actor principles with common mailbox and supervision
conventions. Sequential handling protects actor-local state, not cross-actor
workflows or shared storage. Supervision requires runtime support; restarting
cannot undo completed effects. Handle expected domain errors explicitly and
preserve diagnostics, cleanup, and uncertain outcomes when unexpected work fails.

## N3TX implementation

- First use [n3tx-init](../../dev/n3tx-init/SKILL.md) to locate the consumed version;
  read its `docs/ACTORS.md` and `packages/n3tx-actors/docs/actor-model.md`.
- Use the project's actor base or native `ActorModel` for domain models and
  `Actor` for non-model actors; reuse `TX` and `Matrix` for message dispatch.
- Keep fields, validation, access rules, and exposed methods authoritative;
  actor registration, storage registration, and HTTP routing are separate choices.
- Reuse native CRUD for ordinary edits and `@expose_route` for domain operations;
  keep their contract schema-driven with [sdd-skill](../sdd-skill/SKILL.md).
- Verify caller propagation and authorization on each enabled entrypoint;
  raw internal TX does not inherit HTTP guards or list-policy filtering.
- Do not infer serialized handlers, supervision, transactions, or durable delivery
  from actor names; verify required guarantees and surface implementation gaps.
