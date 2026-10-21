# syntax=docker/dockerfile:1
# Context is services/agents, NOT this directory. Never use a floating base.
ARG PASEO_BASE
FROM ${PASEO_BASE}
ARG PASEO_BASE
ARG PASEO_VERSION
ARG PASEO_RUNTIME_UID
ARG PASEO_RUNTIME_GID
USER root
RUN node -e 'if(!/^ghcr\.io\/getpaseo\/paseo:\d+\.\d+\.\d+@sha256:[a-f0-9]{64}$/.test(process.argv[1]))process.exit(1)' "$PASEO_BASE"
RUN apt-get update && apt-get install -y --no-install-recommends python3 util-linux ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/bin/node /usr/bin/node \
    && ln -s /usr/local/bin/npm /usr/bin/npm
COPY opencode/scripts/entrypoint.sh /opt/opencode/native-contract.sh
COPY paseo-deamon/verify-paseo.mjs /opt/paseo-component/verify-paseo.mjs
RUN node /opt/paseo-component/verify-paseo.mjs "$PASEO_VERSION"
RUN install -d -o 1000 -g 1000 /opt/opencode/build-home /opt/opencode/component
USER 1000:1000
# Same scoped @opencode/cli@latest installer as the native lifecycle; no home publication.
RUN /bin/bash -c 'set -euo pipefail; source /opt/opencode/native-contract.sh; export OPENCODE_USER=paseo OPENCODE_UID=1000 OPENCODE_HOME=/opt/opencode/build-home OPENCODE_ROOT=/opt/opencode/component OPENCODE_PREFIX=/opt/opencode/component/.runtime; install_runtime; verify_runtime "$OPENCODE_PREFIX" "$OPENCODE_HOME"; isolated_runtime "$OPENCODE_PREFIX" "$OPENCODE_HOME" --version > /opt/opencode/component/version.txt'
USER root
RUN set -eu; \
    case "$PASEO_RUNTIME_UID" in ''|*[!0-9]*|0) exit 1;; esac; \
    case "$PASEO_RUNTIME_GID" in ''|*[!0-9]*|0) exit 1;; esac; \
    test "$PASEO_RUNTIME_UID" -le 2147483647; \
    test "$PASEO_RUNTIME_GID" -le 2147483647; \
    runtime_user="$(getent passwd 1000 | cut -d: -f1)"; \
    runtime_group="$(getent group 1000 | cut -d: -f1)"; \
    test -n "$runtime_user"; \
    test -n "$runtime_group"; \
    test "$(id -g "$runtime_user")" = 1000; \
    target_uid_user="$(getent passwd "$PASEO_RUNTIME_UID" | cut -d: -f1)"; \
    target_gid_group="$(getent group "$PASEO_RUNTIME_GID" | cut -d: -f1)"; \
    test -z "$target_uid_user" || test "$target_uid_user" = "$runtime_user"; \
    test -z "$target_gid_group" || test "$target_gid_group" = "$runtime_group"; \
    if [ "$runtime_user" != paseo ]; then ! getent passwd paseo >/dev/null; usermod --login paseo "$runtime_user"; fi; \
    if [ "$runtime_group" != paseo ]; then ! getent group paseo >/dev/null; groupmod --new-name paseo "$runtime_group"; fi; \
    groupmod --gid "$PASEO_RUNTIME_GID" paseo; \
    usermod --uid "$PASEO_RUNTIME_UID" --gid "$PASEO_RUNTIME_GID" --home /home/paseo paseo; \
    test "$(id -u paseo)" = "$PASEO_RUNTIME_UID"; \
    test "$(id -g paseo)" = "$PASEO_RUNTIME_GID"; \
    install -d -o "$PASEO_RUNTIME_UID" -g "$PASEO_RUNTIME_GID" /home/paseo/.config/opencode /state/paseo /state/provider /workspace; \
    chown -R "$PASEO_RUNTIME_UID:$PASEO_RUNTIME_GID" /opt/opencode/build-home /opt/opencode/component /home/paseo /state; \
    chmod -R a+rX,a-w /opt/opencode/component
ENV HOME=/home/paseo \
    PASEO_HOME=/state/paseo \
    XDG_CONFIG_HOME=/home/paseo/.config \
    XDG_DATA_HOME=/state/provider/data \
    XDG_CACHE_HOME=/state/provider/cache \
    XDG_STATE_HOME=/state/provider/state \
    OPENCODE_CONFIG_DIR=/home/paseo/.config/opencode \
    OPENCODE_CONFIG=/home/paseo/.config/opencode/opencode.json \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    PATH=/opt/opencode/component/.runtime/bin:/usr/local/bin:/usr/bin:/bin
RUN node -e 'const fs=require("node:fs"),root="/opt/opencode/component/",p=require(root+".runtime/node_modules/@opencode/cli/package.json"),r=require(root+".runtime/.native-install.json"); if(p.name!=="@opencode/cli"||!/^\d+\.\d+\.\d+$/.test(p.version)||Number(p.version.split(".")[0])!==2||(Number(p.version.split(".")[1])===0&&Number(p.version.split(".")[2])<10)||r.package!==p.name||r.requested!=="latest"||r.version!==p.version||fs.readFileSync(root+"version.txt","utf8").trim()!=="opencode v"+p.version)process.exit(1); fs.writeFileSync("/opt/opencode-version.txt",p.version+"\n"); fs.copyFileSync(root+".runtime/.native-install.json","/opt/opencode-install.json")' \
    && printf '%s\n' "$PASEO_VERSION" > /opt/paseo-version.txt
COPY paseo-deamon/entry.py /opt/paseo-component/entry.py
USER ${PASEO_RUNTIME_UID}:${PASEO_RUNTIME_GID}
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-I", "/opt/paseo-component/entry.py"]
CMD []
