# Thin composition of the reviewed, digest-pinned production image.
ARG PAPERCLIP_IMAGE
FROM ${PAPERCLIP_IMAGE}

# Numeric identity is supplied from the existing account's NSS facts, not a
# host HOME mount or upstream root-time UID remapping.
ARG USER_UID
ARG USER_GID
USER root
COPY configure.mjs /opt/paperclip/configure.mjs
RUN node --check /opt/paperclip/configure.mjs
ENV PAPERCLIP_CONFIG=/run/paperclip/config.json
USER ${USER_UID}:${USER_GID}

# Configuration preload only; no install, company/agent seeding or supervisor.
# Retain upstream's production loader/application entrypoint; skip root-time chown.
ENTRYPOINT ["/usr/bin/tini", "--", "node"]
CMD ["--import", "/opt/paperclip/configure.mjs", "--import", "./server/node_modules/tsx/dist/loader.mjs", "server/dist/index.js"]
