# T3 artifact evidence — 2026-09-08

## ✅ Recorded and verified

The executable build-pin source is [`runtime/pins.json`](runtime/pins.json), not
environment exports. The lock is genuine npm v3 output from `npm 10.9.8` on Node
22.23.2 (supported by T3's `^22.16 || ^23.11 || >=24.10` engine). Lock resolution
used clean config, `--package-lock-only --ignore-scripts --no-audit --no-fund` and
the public registry. **No native install hook ran on the host.**

| Artifact | Actual evidence |
|---|---|
| `t3@0.0.40` | [Exact npm metadata](https://registry.npmjs.org/t3/0.0.40), package identity/bin/engines checked |
| Tarball | [Downloaded bytes](https://registry.npmjs.org/t3/-/t3-0.0.40.tgz) matched locked SHA-512 SRI |
| Registry signatures | Both ECDSA signatures verified against [npm registry keys](https://registry.npmjs.org/-/npm/v1/keys), over `t3@0.0.40:<integrity>` |
| SLSA provenance | [Published bundle](https://registry.npmjs.org/-/npm/v1/attestations/t3@0.0.40) cryptographically verified with npm-bundled Sigstore, expected GitHub Actions issuer and exact release-workflow certificate identity; tarball subject matched |
| Source | Provenance identifies [`ea2983afbbcd5ad6ee2e7db80c2a9270ff4964a9`](https://github.com/pingdotgg/t3code/tree/ea2983afbbcd5ad6ee2e7db80c2a9270ff4964a9), [release workflow run](https://github.com/pingdotgg/t3code/actions/runs/34171449177/attempts/1). The earlier plan's research commit is NOT release provenance. |
| Transitives | All 178 lock tarballs downloaded/read in memory and SHA-512 verified; all package install/preinstall/postinstall scripts inventoried |
| Node image | Live Docker registry index bytes hashed to recorded digest; amd64/arm64 manifests identified, amd64 config inspected (`NODE_VERSION=24.20.0`, upstream Node entrypoint, no declared volumes). This is registry evidence, not a Node image signature/SBOM audit. |
| OS | Dated Debian and Debian-security bookworm Release/index endpoints fetched successfully. Image builds use apt's Debian keyring/signature and package-hash checks; no host apt operation occurred. |

Exact content identities:

```text
T3 SRI:
sha512-lvyH1fexahy7lVXNNWP9FUE/IRlYFKEt5DksoscftVY0VBDQ3LBVrKbyYd5iiHWXr1Qun3Fcbf+kXsIP+75wjg==

package-lock.json SHA-256:
12a95eb87b99475c0564e9277eebdcf99ec55efb1e2f41048d68a4e01832fdbc

node:24.20.0-bookworm-slim index:
sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e
linux/amd64:
sha256:6642ef280aebc09c4541bee0b15c9f89f0f3f3c247ddee79ae1d37eddfdcbbaa
linux/arm64:
sha256:e9b5516b06baeaea9a8e65a7aec6a85fbb960a30b52b66968f2c8092b3e2a3eb
```

Node source annotation:
<https://github.com/nodejs/docker-node/tree/c4eb0858f5c522521768d5b6dc1d9f1631d4854d/24/bookworm-slim>

OS snapshot endpoints:
- <https://snapshot.debian.org/archive/debian/20260908T000000Z/dists/bookworm/Release>
- <https://snapshot.debian.org/archive/debian-security/20260908T000000Z/dists/bookworm-security/Release>

These are a fixed resolution universe, not a claim of bit-reproducible compiled
output. The build returns a unique content-addressed local image; no tag overwrite.
Snapshots intentionally freeze security updates until a reviewed pin refresh.

## 🔎 Native hooks and secondary downloads

| Locked package | Reviewed behavior / build handling |
|---|---|
| `node-pty@1.1.0` | `scripts/prebuild.js` checks included architecture directory, otherwise node-gyp rebuild. Linux postinstall only cleans build output; Windows conpty copy branch does not run. No prebuild fetch in these scripts. |
| `msgpackr-extract@3.0.4` | `node-gyp-build-optional-packages@5.2.2` tests the included/optional native binary; falls back to node-gyp compilation. Platform npm tarballs are locked/SRI-covered. |
| node-gyp fallback | Potential Node-header downloader; eliminated from the allowed build path by `npm_config_nodedir=/usr/local` and BuildKit `--network=none`. Local headers are covered by the pinned Node image. Missing headers fail rather than fetch. |
| `@ff-labs/fff-node@0.9.4` | No install hook. `dist/src/binary.js` resolves locked `@ff-labs/fff-bin-*` npm libraries or local dev output, not network downloads. Production smoke requires actual library loading and file search. |
| `ffi-rs@1.3.7` | Platform-specific npm optional binaries are in the lock; no install hook found. Exercised transitively by the required FFF smoke. |

Additional static inspection of the GNU/Linux amd64/arm64 binaries found FFF
GLIBC symbol versions through 2.30 and ffi-rs through 2.14/2.17 respectively,
below bookworm's 2.36 baseline. This narrows one compatibility risk; it does not
replace loading/executing the binaries in the actual image. The pinned upstream
Node Dockerfile retains `/usr/local/include/node` headers (apart from irrelevant
OpenSSL architecture headers), supporting the offline node-gyp configuration.

No blanket script omission is used in the finished image. Installation/rebuild
are unprivileged and bounded to 900 seconds each. Final-stage smoke is bounded to
90 seconds, runs without network, loads native msgpackr, spawns/reads a PTY, performs
FFF scanning/search, exercises Node SQLite, and checks exact T3 version/CLI help.
This validates against the runtime libraries rather than accidentally relying on
the builder's toolchain packages. **These Docker steps have not executed here.**

The upstream dependency tree includes Anthropic SDK and SDK platform artifacts;
these are not silently removed from T3's upstream dependency contract. Provider
`none` remains, no extra provider is selected/configured/authenticated, and no
provider acceptance task is run. Runtime telemetry/updates/provider-triggered
downloads are a separate, still-open egress audit—not covered by the hook review.
Transitive provenance/SBOM/vulnerability review is not claimed by SRI checks.

## 🧪 Reproduction and future updates

Read-only artifact audits (network required; no extraction/hooks):

```sh
node scripts/audit-artifacts.mjs
python3 -B scripts/audit-hooks.py --source
python3 -B scripts/verify_build.py runtime
```

The first uses the Sigstore verifier bundled in the installed npm (located with
`npm root -g`); it fails if unavailable, never downloads a verifier with npx.
The second reads tarballs in memory and reports lifecycle source for review.

For an intentional release update, change the exact dependency, regenerate the
lock with clean config and `--package-lock-only --ignore-scripts`, rerun both audits,
then update the pins' digest/evidence/hook inventory together. Verify new base
tag/index/platform manifests and OS snapshot. Never hand-edit a lock hash/SRI to
invent metadata, remove validation, or mark Docker checks successful without runs.
Build with `./t3code build`; compatibility failures must be investigated in that
canonical Dockerfile/build flow. Existing workspace images still require explicit
`recreate --ack-stop` and compatible stopped-state backups to change.

Local constraint encountered: `/tmp/opencode` is root-owned/unwritable to UID 1000.
No permission repair was attempted. Lock generation used a clean ignored
component-local `.build-research/` npm config/cache instead; that path is excluded
from the Docker build context. The first npm attempt also rejected using `/dev/null`
for both global and user config, so a distinct empty global config was used.

Remaining manual prerequisite: an already authorized local Docker/BuildKit/Compose
setup. Docker CLI and shellcheck were absent; no installation, remote daemon,
deployment, actual native execution, provider login or paid task was performed.
