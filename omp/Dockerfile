FROM node:22-bookworm

ARG BUN_VERSION=1.4.0
ARG OMP_VERSION=18.0.4
ARG OMP_UID=1000
ARG OMP_GID=1000
# Reviewed release asset, Linux x64 baseline (see README). Deliberately amd64-only.
ARG BUN_SHA256=184fb4595f0d401a217cf7c78c1bc430ba83314dab7a8b94805babbf7fa7097f

LABEL dev.xmist.agents.component="omp"
ENV DEBIAN_FRONTEND=noninteractive \
    BUN_INSTALL=/opt/bun \
    BUN_INSTALL_GLOBAL_DIR=/opt/bun/install/global \
    BUN_INSTALL_BIN=/opt/bun/bin \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    HOME=/root \
    PATH=/opt/bun/bin:/home/omp/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update && apt-get install -y --no-install-recommends \
       ca-certificates tzdata git openssh-client bash ripgrep fzf curl jq \
       python3 python3-pip python3-venv passwd unzip gnupg \
       software-properties-common sshpass \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ && rm /tmp/terraform.zip
RUN python3 -m pip install --break-system-packages ansible ansible-lint jmespath
RUN userdel --remove node \
    && ( ! getent group node >/dev/null || groupdel node ) \
    && test "${OMP_UID}" -gt 0 && test "${OMP_GID}" -gt 0 \
    && groupadd -g "${OMP_GID}" omp \
    && useradd -u "${OMP_UID}" -g omp -s /bin/bash -m -d /home/omp omp \
    && install -d -m 0750 -o omp -g omp /home/omp \
    && install -d -o omp -g omp /workspace /home/omp/.ssh /home/omp/.ansible \
    && install -d -m 0700 -o omp -g omp /home/omp/.omp /home/omp/.omp/agent
RUN curl -fsSL "https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}/bun-linux-x64-baseline.zip" -o /tmp/bun.zip \
    && printf '%s  /tmp/bun.zip\n' "${BUN_SHA256}" | sha256sum -c - \
    && unzip /tmp/bun.zip -d /tmp/bun \
    && install -D /tmp/bun/bun-linux-x64-baseline/bun /opt/bun/bin/bun \
    && rm -rf /tmp/bun /tmp/bun.zip \
    && bun install -g "@oh-my-pi/pi-coding-agent@${OMP_VERSION}" \
    && ln -s /opt/bun/bin/bun /usr/local/bin/bun \
    && ln -s /opt/bun/bin/omp /usr/local/bin/omp \
    && chmod -R a+rX /opt/bun
# General frontend tooling retained; no vanilla Pi, sudo or Docker socket tooling.
RUN npm install -g playwright && playwright install --with-deps chromium \
    && chmod -R a+rX /opt/ms-playwright

USER omp
ENV HOME=/home/omp
WORKDIR /workspace
# Do not inherit node's docker-entrypoint.sh: the harness owns startup exactly.
ENTRYPOINT []
# Version takes the lightweight CLI path, not setup/session initialization.
# Disposable HOME additionally keeps a future upstream regression off bind state.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD d=$(mktemp -d) && HOME="$d" /usr/local/bin/omp --version; rc=$?; rm -rf "$d"; exit "$rc"
CMD ["/usr/local/bin/omp"]
