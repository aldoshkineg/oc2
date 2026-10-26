# Build the opencode CLI v2 image from the official npm tarball.
# fetch.sh downloads the binary into /tmp/oc-build; the build context is
# /tmp/oc-build:
#   make build            (latest version)
#   make build VER=2.1.5  (a specific version)

FROM debian:bookworm-slim

# pin the mise version: make build MISE_VERSION=v2026.10.18; empty → fresh release
ARG MISE_VERSION=

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates curl jq ripgrep \
 && rm -rf /var/lib/apt/lists/*

# mise: installs runtimes on demand (python etc.). Data lives in /opt/mise:
# the host mount of /data cannot wipe it there. The shims on PATH work both
# in the TUI and in one-shot commands.
RUN curl -fsSL https://mise.run \
      | MISE_INSTALL_PATH=/usr/local/bin/mise MISE_VERSION=$MISE_VERSION sh
ENV MISE_DATA_DIR=/opt/mise/data \
    MISE_CONFIG_DIR=/opt/mise/cfg \
    MISE_CACHE_DIR=/opt/mise/cache \
    MISE_STATE_DIR=/opt/mise/state

COPY opencode /usr/local/bin/opencode
RUN chmod +x /usr/local/bin/opencode && opencode --version

# All the opencode state lives under /data — a directory mounted from the
# host into the container (see README, "Layout inside the state profile").
ENV XDG_CONFIG_HOME=/data/cfg \
    XDG_DATA_HOME=/data/data \
    XDG_STATE_HOME=/data/state \
    XDG_CACHE_HOME=/data/cache

ENV PATH="/usr/local/bin:/opt/mise/data/shims:${PATH}"

WORKDIR /workspace
ENTRYPOINT ["opencode"]
