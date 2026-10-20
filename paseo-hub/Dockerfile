# Only image-local NSS identity changes; no provider installation or host state.
ARG PASEO_BASE
FROM ${PASEO_BASE}
ARG AGENT_UID
ARG AGENT_GID
USER root
RUN set -eu; test "$AGENT_UID" -gt 0; test "$AGENT_GID" -gt 0; \
    account="$(getent passwd 1000 | cut -d: -f1)"; \
    group="$(getent group 1000 | cut -d: -f1)"; \
    groupmod -n agent -g "$AGENT_GID" "$group"; \
    usermod -l agent -u "$AGENT_UID" -g "$AGENT_GID" -d /home/agent "$account"; \
    install -d -m 0700 -o agent -g agent /home/agent
ENV HOME=/home/agent USER=agent LOGNAME=agent PASEO_HOME=/home/agent/.paseo
USER agent
