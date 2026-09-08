# No default artifact selections. Both bases must be reviewed prepared images.
# NODE_IMAGE: exact Node patch tag + sha256 digest, runtime-only tools (Node/npm,
# bash, coreutils, util-linux flock, git, CA certificates), no compiler/toolchain or privileged tools.
# BUILDER_IMAGE: exact tag + sha256 digest, same Node patch/ABI/OS/architecture,
# plus the reviewed native build tools. Their OS package pins/snapshot and SBOM
# must be reviewed externally. No mutable apt installation is performed here.
# Build context: services/agents/t3code. This file intentionally cannot build yet:
# runtime/package.json has no approved t3 dependency and its real lock is absent.
ARG NODE_IMAGE
ARG BUILDER_IMAGE
FROM ${BUILDER_IMAGE} AS builder
ARG NODE_IMAGE
ARG BUILDER_IMAGE
ARG NODE_VERSION
ARG T3_VERSION
ARG T3_INTEGRITY
ARG PACKAGE_LOCK_SHA256
ARG PREPARED_BASES_REVIEWED
ARG INSTALL_HOOKS_REVIEWED
USER root
RUN mkdir -p /opt/t3/runtime /tmp/t3-build-home && \
    chown 10001:10001 /opt/t3/runtime /tmp/t3-build-home && \
    chmod 0700 /tmp/t3-build-home
WORKDIR /opt/t3/runtime
COPY --chown=10001:10001 runtime/ ./
USER 10001:10001
# Check all gates before fetching packages or executing dependency hooks.
# Review flags are attestations by the build owner, not automated provenance
# verification. Review release provenance, native/optional artifacts and ALL
# secondary hook downloads (independently pinned/integrity-verified) first.
RUN node --input-type=module <<'NODE'
import fs from 'node:fs';
import crypto from 'node:crypto';
const env = process.env;
const fail = (message) => { throw new Error(`T3 build gate: ${message}`); };
if (env.PREPARED_BASES_REVIEWED !== 'yes' || env.INSTALL_HOOKS_REVIEWED !== 'yes') {
  fail('prepared OS bases and dependency hooks require explicit review');
}
if (!/^\d+\.\d+\.\d+$/.test(env.NODE_VERSION ?? '') || process.versions.node !== env.NODE_VERSION) {
  fail('exact NODE_VERSION must match the builder');
}
for (const key of ['NODE_IMAGE', 'BUILDER_IMAGE']) {
  const image = env[key] ?? '';
  if (!/^[^\s@]+:[A-Za-z0-9_][A-Za-z0-9_.-]*@sha256:[a-f0-9]{64}$/.test(image) ||
      /:(latest|nightly)(?:[-.@]|$)/i.test(image)) fail(`${key} requires an exact tag and digest`);
}
const runtimeTag = env.NODE_IMAGE.split('@')[0].split(':').at(-1);
if (runtimeTag !== env.NODE_VERSION && !runtimeTag.startsWith(`${env.NODE_VERSION}-`)) {
  fail('NODE_IMAGE tag must start with the exact NODE_VERSION');
}
if (!/^\d+\.\d+\.\d+$/.test(env.T3_VERSION ?? '') ||
    !/^sha512-[A-Za-z0-9+/]{86}==$/.test(env.T3_INTEGRITY ?? '')) {
  fail('approved exact T3_VERSION and SHA-512 T3_INTEGRITY required');
}
if (!fs.existsSync('package-lock.json')) fail('reviewed package-lock.json is missing; never synthesize one during build');
const bytes = fs.readFileSync('package-lock.json');
if (!/^[a-f0-9]{64}$/.test(env.PACKAGE_LOCK_SHA256 ?? '') ||
    crypto.createHash('sha256').update(bytes).digest('hex') !== env.PACKAGE_LOCK_SHA256) {
  fail('reviewed lock SHA-256 mismatch');
}
const manifest = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const lock = JSON.parse(bytes);
const exactDependency = (deps) => deps && Object.keys(deps).length === 1 && deps.t3 === env.T3_VERSION;
if (!exactDependency(manifest.dependencies) || manifest.scripts || manifest.devDependencies ||
    manifest.optionalDependencies || manifest.overrides || manifest.workspaces) fail('manifest must contain only the approved t3 dependency');
if (lock.lockfileVersion !== 3 || !exactDependency(lock.packages?.['']?.dependencies)) fail('npm v3 lock root mismatch');
const t3 = lock.packages['node_modules/t3'];
if (!t3 || t3.version !== env.T3_VERSION || t3.integrity !== env.T3_INTEGRITY ||
    t3.resolved !== `https://registry.npmjs.org/t3/-/t3-${env.T3_VERSION}.tgz` ||
    t3.bin?.t3 !== 'dist/bin.mjs') fail('locked t3 identity, bin or integrity mismatch');
for (const [path, pkg] of Object.entries(lock.packages)) {
  if (path === '') continue;
  if (!path.startsWith('node_modules/') || path.split('/').includes('..') || pkg.link ||
      !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(pkg.version ?? '') ||
      !/^https:\/\/registry\.npmjs\.org\/[^?#\s]+\.tgz$/.test(pkg.resolved ?? '') ||
      !/^sha512-[A-Za-z0-9+/]{86}==$/.test(pkg.integrity ?? '')) fail('all locked packages need exact registry artifacts and SHA-512 integrity');
}
NODE
# Clean environment/config; no inherited npm credentials. npm ci verifies locked
# tarball integrity before extraction. Hooks run only after the review gate,
# unprivileged and bounded; never at container initialization.
RUN umask 077 && : > /tmp/t3-build-home/empty-global.npmrc && \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/t3-build-home \
    npm_config_userconfig=/dev/null npm_config_globalconfig=/tmp/t3-build-home/empty-global.npmrc \
    npm_config_cache=/tmp/t3-build-home/cache npm_config_engine_strict=true \
    timeout 900 npm ci --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/ && \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/t3-build-home \
    npm_config_userconfig=/dev/null npm_config_globalconfig=/tmp/t3-build-home/empty-global.npmrc \
    npm_config_cache=/tmp/t3-build-home/cache npm_config_engine_strict=true \
    timeout 900 npm rebuild --no-audit --no-fund --registry=https://registry.npmjs.org/
RUN node --input-type=module <<'NODE'
import fs from 'node:fs';
const pkg = JSON.parse(fs.readFileSync('node_modules/t3/package.json', 'utf8'));
if (pkg.name !== 't3' || pkg.version !== process.env.T3_VERSION || pkg.bin?.t3 !== 'dist/bin.mjs' ||
    fs.realpathSync('node_modules/.bin/t3') !== '/opt/t3/runtime/node_modules/t3/dist/bin.mjs') {
  throw new Error('Installed T3 identity/bin mismatch');
}
fs.accessSync('node_modules/.bin/t3', fs.constants.X_OK);
NODE

FROM ${NODE_IMAGE} AS runtime
ARG NODE_VERSION
USER root
RUN test "$(node -p process.versions.node)" = "$NODE_VERSION"
COPY --from=builder --chown=0:0 /opt/t3/runtime /opt/t3/runtime
COPY --chown=0:0 init.sh /opt/t3/init.sh
COPY --chown=0:0 scripts/entrypoint.sh scripts/start.sh scripts/provider.sh scripts/healthcheck.mjs /opt/t3/scripts/
RUN chmod -R a+rX /opt/t3 && chmod -R a-w /opt/t3 && \
    mkdir -p /home/t3code /opt/agent /workspace && \
    chown 10001:10001 /home/t3code && chmod 0700 /home/t3code
ENV HOME=/home/t3code
ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /workspace
# Safe image default; Compose overrides with matching numeric UID/GID and env.
# Port and provider deliberately have no defaults: the wrapper must supply them.
USER 10001:10001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["node", "/opt/t3/scripts/healthcheck.mjs"]
ENTRYPOINT ["/bin/bash", "/opt/t3/init.sh"]
