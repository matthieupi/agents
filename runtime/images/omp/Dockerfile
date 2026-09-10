ARG NODE_IMAGE
FROM ${NODE_IMAGE}
LABEL io.agents-runtime.harness="omp" io.agents-runtime.contract="1"
COPY apt.sources /tmp/apt.sources
# Bootstrap CA roots with the image-bundled Debian signing keyring, retaining
# the selected snapshots and signature/hash checks. Then restore HTTPS verbatim.
RUN test "$(dpkg --print-architecture)" = amd64 && \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* && \
    sed 's|^URIs: https://snapshot\.debian\.org/|URIs: http://snapshot.debian.org/|' /tmp/apt.sources > /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    cp /tmp/apt.sources /etc/apt/sources.list.d/debian.sources && rm -f /tmp/apt.sources && \
    rm -rf /var/lib/apt/lists/* && apt-get update && \
    apt-get install -y --no-install-recommends python3 libnss-wrapper make g++ git openssh-client ripgrep && rm -rf /var/lib/apt/lists/*
RUN install -d -o node -g node /opt/agents-runtime/packages
COPY --chown=node:node package.json package-lock.json /opt/agents-runtime/packages/
USER node
RUN cd /opt/agents-runtime/packages && npm ci --ignore-scripts --include=optional --no-audit --no-fund
RUN --network=none cd /opt/agents-runtime/packages && npm_config_nodedir=/usr/local npm rebuild --offline
USER root
COPY entry.py harnesses.json /opt/agents-runtime/
RUN dpkg-query -W > /opt/agents-runtime/os-packages.tsv && chmod -R a+rX,a-w /opt/agents-runtime
ENV PATH=/opt/agents-runtime/packages/node_modules/.bin:/usr/local/bin:/usr/bin:/bin
USER node
ENTRYPOINT ["/usr/bin/python3", "-I", "/opt/agents-runtime/entry.py", "omp"]
