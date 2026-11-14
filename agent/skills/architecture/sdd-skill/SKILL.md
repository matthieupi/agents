---
name: sdd-skill
description: >-
  Plan, build, and review using Schema Driven Design: executable model contracts
  own data, validation, behavior, permissions, and downstream API/UI/tool schemas.
  Use for model or contract work and preventing duplicated definitions across
  layers; SDD here is schema-driven, not spec-driven development.
---

# Schema Driven Design

Schema-Driven Development (SDD) is a software engineering approach where a single, machine-readable schema serves as the foundational blueprint and Single Source of Truth (SSOT) for an entire application. Instead of manually writing boilerplate code across different layers of a system, developers define data models and API contracts upfront. Automated tools then use that schema to generate code, documentation, validation logic, and even user interfaces.

How It Works

The SDD workflow flips traditional development by putting data structure before business logic.
• Contract Definition. Teams collaborate to write an unambiguous schema using formats like OpenAPI, GraphQL SDL, JSON Schema, or Protobuf before writing application code.
• Code Generation. Build tools and compilers read the schema to automatically produce server stubs, client SDKs, database migrations, and strongly typed data models (such as TypeScript interfaces or Kotlin classes).
• Boundary Validation. Applications use the schema at runtime to automatically reject malformed incoming requests and verify that outgoing responses match the contract.
• Automated Documentation & Testing. Tools like Swagger UI parse the schema to create live, interactive API docs and mock servers, while test suites generate contract tests directly from the rules.

Common Applications

SDD is applied across several layers of modern software architecture.
• API-First Design. Backend and frontend teams agree on an API schema early, allowing both teams to build and test against mock data in parallel without waiting for endpoints to be finished.
• Schema-Driven UI. Frontend frameworks read JSON or GraphQL schemas to dynamically render forms, tables, and admin dashboards on the fly without hardcoding individual screens.
• AI & Agent Guardrails. Clear, strongly typed schemas give AI agents explicit context about data types, constraints, and relationships, preventing hallucinations and ensuring safe tool execution

The model is the application contract, not a passive data-transfer object.
Declare knowledge once and let APIs, storage, forms, clients, and tools consume
the same executable definition through the framework's supported mechanisms.
Use the [Actor Model](../actor-model/SKILL.md) as the architectural foundation.

## Plan and build schema-first

1. **Find the owner.** Identify the canonical model and the consumers affected by
   the request before proposing routes, UI fields, tools, or helper services.
2. **Change the declaration.** Keep typed fields, defaults, constraints,
   relationships, domain methods, access policy, and presentation hints together
   at their existing owners; use CRUD for edits, methods for domain operations.
3. **Derive, do not mirror.** Reuse native generation and runtime discovery;
   do not hand-copy field lists, method arguments, validation, or permissions
   into a second client schema, endpoint, registry, or command definition.
4. **Extend narrowly.** Add only missing behavior at existing extension points;
   custom presentation consumes the schema rather than replacing its contract.
5. **Check the flow.** Verify declaration -> schema -> enabled consumer/transport
   -> validation, authorization, and stored result as relevant to the change.
   Schema visibility and client validation are not server-side enforcement.

## N3TX mapping

Use [n3tx-init](../../dev/n3tx-init/SKILL.md) for the consumed version, then read
its `docs/MODELS.md` and relevant `BACKEND.md` / `FRONTEND.md` references.
Models declare fields, validators, `__access__`, `@expose_route`, and UI hints;
N3TX derives native CRUD, schemas, forms, and actor-tool contracts from them.
Import capability packages before model declarations and register storables.
Use runtime schemas, NTT, native forms/widgets, and named schema extensions;
do not build parallel API, permission, or browser-state frameworks.
Review stored-data compatibility explicitly; schema-first is not migration
approval, atomicity, or proof that every transport enforces the same policy.
