# OpenCode - Containerized AI Coding Assistant
# Base: Node.js LTS on Debian for better package compatibility
FROM node:22-bookworm

LABEL maintainer="sys-ops"
LABEL description="OpenCode Containerized AI Coding Assistant"
LABEL version="1.0.0"
LABEL dev.xmist.opencode.lifecycle="v2-serve-1"

# Avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies for coding workflows
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    git \
    openssh-client \
    bash \
    util-linux \
    ripgrep \
    fzf \
    curl \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    unzip \
    gnupg \
    software-properties-common \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

# Install Terraform
RUN curl -fsSL https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && chmod +x /usr/local/bin/terraform

# Install Ansible system-wide
RUN python3 -m pip install --break-system-packages \
    ansible \
    ansible-lint \
    jmespath

# Non-root user setup with sudo access
RUN deluser --remove-home node 2>/dev/null || true \
    && groupadd -g 1000 opencode \
    && useradd -u 1000 -g opencode -s /bin/bash -m opencode \
    && echo "opencode ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/opencode \
    && chmod 0440 /etc/sudoers.d/opencode

# Workspace mount point
RUN mkdir -p /workspace \
    && chown opencode:opencode /workspace

# Config and data directories
RUN mkdir -p /home/opencode/.config/opencode \
    && mkdir -p /home/opencode/.local/share/opencode \
    && mkdir -p /home/opencode/.cache/opencode \
    && mkdir -p /home/opencode/.ssh \
    && mkdir -p /home/opencode/.ansible \
    && chown -R opencode:opencode /home/opencode

# Install OpenCode globally
RUN npm install -g @opencode/cli@latest \
    && npm cache clean --force

# Canonical native config and title assets; bind mounts use these same paths.
COPY init.sh scripts/docker-* /opt/harness/
RUN chmod 0755 /opt/harness && chmod 0644 /opt/harness/*
COPY scripts/publish-plugins.mjs /opt/opencode/publish-plugins.mjs
COPY .opencode/config/opencode.json .opencode/config/cli.json /opt/opencode-defaults/
COPY .opencode/config/plugins/first-prompt-title.js /opt/opencode-defaults/plugins/
COPY .opencode/config/plugins/background-subagents.js /opt/opencode-defaults/plugins/
COPY .opencode/config/tui-plugins/session-title.mjs /opt/opencode-defaults/tui-plugins/
COPY .opencode/config/tui-plugins/session-title/tui.js /opt/opencode-defaults/tui-plugins/session-title/

# Preinstall Playwright for frontend workflows
RUN npm install -g playwright \
    && playwright install --with-deps chromium

# Readiness checks the authenticated V2 API, not merely the installed binary.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python3 /opt/harness/docker-health.py

# Switch to opencode user
USER opencode
WORKDIR /workspace

ENV OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_EXPERIMENTAL_WORKSPACES=1
ENV OPENCODE_DOCKER_PORT=4096 OPENCODE_CONFIG_DIR=/home/opencode/.config/opencode
CMD ["bash", "/opt/harness/docker-server.sh"]
