FROM node:22-bookworm

ARG BUN_VERSION=1.4.0
ARG OMP_VERSION=18.0.4

LABEL maintainer="sys-ops"
LABEL description="Pi containerized coding agent"
LABEL version="1.0.0"

ENV DEBIAN_FRONTEND=noninteractive \
    BUN_INSTALL=/opt/bun \
    PATH=/opt/bun/bin:/home/pi/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

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
    passwd \
    sudo \
    unzip \
    gnupg \
    software-properties-common \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && chmod +x /usr/local/bin/terraform

RUN python3 -m pip install --break-system-packages \
    ansible \
    ansible-lint \
    jmespath

RUN deluser --remove-home node 2>/dev/null || true \
    && groupadd -g 1000 pi \
    && useradd -u 1000 -g pi -s /bin/bash -m pi \
    && echo "pi ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/pi \
    && chmod 0440 /etc/sudoers.d/pi

RUN mkdir -p /workspace \
    && chown pi:pi /workspace

RUN mkdir -p /home/pi/.pi/agent \
    && mkdir -p /home/pi/.ssh \
    && mkdir -p /home/pi/.ansible \
    && chown -R pi:pi /home/pi

RUN npm install -g @mariozechner/pi-coding-agent \
    && npm cache clean --force

RUN curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}" \
    && bun install -g "@oh-my-pi/pi-coding-agent@${OMP_VERSION}" \
    && ln -s /opt/bun/bin/bun /usr/local/bin/bun \
    && ln -s /opt/bun/bin/omp /usr/local/bin/omp \
    && bun --version \
    && omp --version

# Preinstall Playwright for frontend workflows
RUN npm install -g playwright \
    && playwright install --with-deps chromium

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pi --version && omp --version || exit 1

USER pi
WORKDIR /workspace

CMD ["pi"]
