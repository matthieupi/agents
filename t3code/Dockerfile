# BuildKit is required for network-disabled native rebuild/validation steps.
# Values come exclusively from runtime/pins.json via ./t3code build.
ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS base
ARG DEBIAN_SNAPSHOT
USER root
# The dated Debian archives pin the entire apt dependency closure. Retain apt's
# signature/hash verification; only historical Release expiry is disabled.
# HTTP bootstraps CA roots using Debian's image-bundled signing keyring.
RUN test -n "$DEBIAN_SNAPSHOT" && \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://snapshot.debian.org/archive/debian/%s/ bookworm main\ndeb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://snapshot.debian.org/archive/debian-security/%s/ bookworm-security main\n' \
      "$DEBIAN_SNAPSHOT" "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git util-linux libatomic1 && \
    rm -rf /var/lib/apt/lists/*

FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /opt/t3/runtime /opt/t3/build /tmp/t3-build-home && \
    chown 10001:10001 /opt/t3/runtime /tmp/t3-build-home && chmod 0700 /tmp/t3-build-home
COPY --chown=0:0 scripts/verify_build.py /opt/t3/build/
COPY --chown=10001:10001 runtime/ /opt/t3/runtime/
WORKDIR /opt/t3/runtime
USER 10001:10001
RUN python3 -B /opt/t3/build/verify_build.py /opt/t3/runtime
# Clean, credential-free npm configuration; npm ci verifies every locked SRI.
RUN umask 077 && : > /tmp/t3-build-home/global.npmrc && \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/t3-build-home \
    npm_config_userconfig=/dev/null npm_config_globalconfig=/tmp/t3-build-home/global.npmrc \
    npm_config_cache=/tmp/t3-build-home/cache npm_config_engine_strict=true \
    timeout 900 npm ci --ignore-scripts --include=optional --no-audit --no-fund --registry=https://registry.npmjs.org/ && \
    python3 -B /opt/t3/build/verify_build.py /opt/t3/runtime --installed
# Reviewed hooks execute, not blanket-disabled. Fallback node-gyp uses headers
# already integrity-covered by the Node image, never secondary network downloads.
RUN --network=none umask 077 && \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/t3-build-home \
    npm_config_userconfig=/dev/null npm_config_globalconfig=/tmp/t3-build-home/global.npmrc \
    npm_config_cache=/tmp/t3-build-home/cache npm_config_engine_strict=true \
    npm_config_nodedir=/usr/local \
    timeout 900 npm rebuild --offline --no-audit --no-fund

FROM base AS runtime
COPY --from=builder --chown=0:0 /opt/t3/runtime /opt/t3/runtime
COPY --chown=0:0 init.sh /opt/t3/init.sh
COPY --chown=0:0 scripts/entrypoint.sh scripts/start.sh scripts/provider.sh scripts/healthcheck.mjs scripts/smoke-native.mjs /opt/t3/scripts/
RUN chmod -R a+rX /opt/t3 && chmod -R a-w /opt/t3 && \
    mkdir -p /home/t3code /opt/agent /workspace && \
    chown 10001:10001 /home/t3code && chmod 0700 /home/t3code
ENV HOME=/home/t3code
ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /workspace
USER 10001:10001
# Test against the FINAL libraries, non-root ownership and immutable runtime,
# without network. A native/CLI failure must prevent successful image capture.
RUN --network=none timeout 90 node /opt/t3/scripts/smoke-native.mjs
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD ["node", "/opt/t3/scripts/healthcheck.mjs"]
ENTRYPOINT ["/bin/bash", "/opt/t3/init.sh"]
# Clear the upstream Node image CMD; init is the only server entrypoint.
CMD []
