# Shared harness HOME

All selected VM harnesses use the single configured `agents` execution account,
its discovered NSS UID/GID, and its exact NSS HOME. CLI and web containers mount
that HOME at the same path and receive consistent HOME and XDG paths. This is one
VM-root-equivalent Docker trust boundary, not per-harness isolation.

The current launcher validates the configured policy, identity, physical paths,
and required mounts before launching. Current controls are serialized by their
file/source locks and published atomically. Finite activation can install a missing
selected immutable image and reconcile the declared default; it does not replace an
installed image, promote a shared runtime, copy state, or migrate a deployment.

Persistent identity is retained only as a root-owned record beneath the configured
internal root. Existing HOME, provider, workspace, and user state stay in place.
Paseo persistence is limited to currently declared daemon state beneath its own
configured internal root; it has no state-copy or daemon-migration path. Mount
layout is configuration-owned: [plan 106](../../../.project/features/106-agent-storage-mount-schema.md)
is an optional proposal, not a default.

If a current reconciliation fails, correct the reported condition and rerun the
same selected standard command. Do not remove locks, protected controls, identity
records, or user state to force a retry. Final provider and application acceptance
is manual and remains outside bounded coordinator verification.
