# OpenCode - Containerized AI Coding Assistant
# Base: Node.js LTS on Debian for better package compatibility
FROM node:22-bookworm

LABEL maintainer="sys-ops"
LABEL description="OpenCode Containerized AI Coding Assistant"
LABEL version="1.0.0"

# Avoid prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Runtime dependencies for coding workflows
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    git \
    openssh-client \
    bash \
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
RUN npm install -g opencode-ai@latest \
    && npm cache clean --force

# Health check - verify CLI exists and responds
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD opencode --version || exit 1

# Switch to opencode user
USER opencode
WORKDIR /workspace

# Default: show help (override with entrypoint in compose)
CMD ["opencode"]
