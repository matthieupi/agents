# Paseo Hub — ordinary VM service

`docker-compose.j2`, `env.j2` and `config.json.j2` are consumed by the standard
Docker service role. `Dockerfile` changes only the configured upstream image's NSS
identity to the shared `agent` account; it installs no providers. Canonical Hub
selection is currently `ghcr.io/getpaseo/paseo:latest`, not an enforced digest pin.
The environment template also rebases inherited provider-directory and XDG
variables onto this product-local HOME so the upstream entrypoint does not try
to create directories beneath the deliberately inaccessible `/home/paseo`.
These are empty local directories, not mounted provider credentials; providers
remain disabled.

See [the VM service contract](../VM-SERVICES.md) for exact metadata and finite
build inputs. Hub receives product-local state only, never provider HOME,
workspace, workstation SSH or Docker socket. S prepares a dynamically allocated
internal bridge; Compose references it by `paseo_hub_network_name` with **no
published host port** or static address. Its observed `paseo_hub_network_gateway`
is the sole trusted proxy `/32`. After Compose, S inspects the container endpoint
for ordinary host-nginx upstream routing, waiting for health and a nonempty
network address before rendering nginx. No Hub CPU limit is invented when absent.

All upstream providers are explicitly disabled, **including `omp`**. Removing the
OMP product must not remove this upstream security setting. Native bcrypt auth,
exact hostnames and HTTPS Origins remain in protected `config.json`; relay, MCP,
service proxy, terminal hooks and voice features stay disabled.

The deployment owns credential resolution, owner-only config/state preparation
and ordinary ingress/catalog wiring. On 2026-09-23, DevAI Hub build/start, healthy
private endpoint, host nginx routing and TLS frontend availability passed live
validation. Native authentication/provider workflows remain separate acceptance;
frontend HTTP200 alone does not certify them.
