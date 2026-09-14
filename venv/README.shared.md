# Protected shared runtime

The shared runtime is an optional, root-promoted replacement path for already
enrolled schema-2 VM harnesses. It is not a bootstrap mechanism and does not infer
machine identity, accounts, capabilities, image compatibility, or state layout.

## Authority

Activation remains the finite protected interface:

```text
sudo -n <paths.command> activate <pi|omp|opencode|t3> sha256:<64 lowercase hex>
```

The caller must be the sole shared `execution_account` referenced by the selected
harness. Policy `accounts` contains only that identity. Ambient `USER`, `SUDO_USER`, Docker
context, checkout content, and provider files do not expand authority.

Protected controls are imported only from sealed absolute paths with exact SHA-256
digests. The extension binds one canonical target, checkout revision, immutable
image receipts, staging limits, explicit privilege grants, and reviewed state
transitions. Editable checkout content is never imported by the root launcher.

## Replacement transaction

```text
activation.lock
  -> validate current policy, seal, account, receipt, and transition
  -> inspect and quiesce the exact old instance
  -> stage candidate with bounded resources and isolated state
  -> verify CLI/web behavior as applicable
  -> persist shared-replacement.json
  -> switch the exact container and gateway route
  -> atomically publish policy.json
  -> finalize and archive recovery evidence
```

The policy publication is the image commit point. Recovery admits only the exact
signed previous/candidate pair and exact derived container names. Unknown images,
mutable tags, unreviewed state transitions, foreign containers, drifted controls,
or ambiguous journals fail closed.

## Capability and identity contract

- Pi: CLI and web
- OpenCode: CLI and web
- OMP: CLI only
- T3: web only

Each runtime contract includes the shared execution account, UID, GID, NSS HOME, XDG
paths, immutable image, receipt digest, resource limits, source mode, and privilege
grants. `USER` and `LOGNAME` are set from that account. Systemd `%i` selects the
harness while `User=`/`Group=` remain the shared execution identity; builds and
activation requests use that same account.

## State and rollback

The shared runtime does not import, rewrite, copy, or delete historical HOME or
provider state. Existing state remains an explicit operator responsibility. A
reviewed image compatibility assertion does not prove application-data rollback;
stateful cutovers require separate backup/restore evidence.

Rollback restores only transaction-owned policy, gateway, unit, and container
state. Locks and journals are retained whenever exact recovery cannot be proved.
No credential values are written to policy, receipts, logs, or diagnostics.
