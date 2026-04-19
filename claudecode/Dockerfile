# Claude Code - Containerized AI Coding Assistant
# Base: Node.js LTS on Ubuntu for better package compatibility
FROM node:22-bookworm

LABEL maintainer="sys-ops"
LABEL description="Claude Code Containerized AI Coding Assistant"
LABEL version="1.1.0"

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

# Install Ansible system-wide (simpler than pipx for multi-user)
RUN python3 -m pip install --break-system-packages \
    ansible \
    ansible-lint \
    jmespath

# Non-root user setup with sudo access
RUN deluser --remove-home node 2>/dev/null || true \
    && groupadd -g 1000 claude \
    && useradd -u 1000 -g claude -s /bin/bash -m claude \
    && echo "claude ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/claude \
    && chmod 0440 /etc/sudoers.d/claude

# Workspace mount point
RUN mkdir -p /workspace \
    && chown claude:claude /workspace

# Config directories
RUN mkdir -p /home/claude/.config/claude-code \
    && mkdir -p /home/claude/.claude \
    && mkdir -p /home/claude/.ssh \
    && mkdir -p /home/claude/.ansible \
    && chown -R claude:claude /home/claude


RUN echo "Updating claudecode installation..."
# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# Install Playwright MCP server globally (avoids npx download on every session)
RUN npm install -g @playwright/mcp

# Install Playwright system deps as root (needs apt-get)
RUN npx playwright install-deps chromium

# Health check - verify CLI exists and responds
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD claude --version || exit 1

# Switch to claude user
USER claude
WORKDIR /workspace
RUN npx get-shit-done-cc --global

# Install Playwright browser binary as claude user (goes to ~/.cache/ms-playwright/)
RUN npx playwright install chromium

# Default: show help (override with entrypoint in compose)
CMD ["claude"]
