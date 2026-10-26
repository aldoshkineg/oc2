# opencode CLI v2 in a container (podman)
# State: ~/.local/share/oc2 (override: DATA=/path make clean)
# Build: make build (latest version) or make build VER=2.1.5
# The binary is downloaded to /tmp/oc-build, the image is tagged with the
# version, old images are removed.
# Development: uv (make sync; then test/lint/checks via uv).

IMAGE_REPO := localhost/opencode
DATA       ?= $(HOME)/.local/share/oc2
DATA       := $(abspath $(DATA))
BUILD_DIR  := /tmp/oc-build

.DEFAULT_GOAL := help
.PHONY: help sync build run cmd shell auth stop test lint checks clean distclean

help:
	@echo "opencode in a container. Image: $(IMAGE_REPO):<version>  State: $(DATA)"
	@echo ""
	@echo "Development (uv):"
	@echo "  make sync                       uv sync (create .venv from uv.lock)"
	@echo "  make test                       tests (pytest, podman not needed)"
	@echo "  make lint                       ruff check over oc and tests"
	@echo "  make checks                     what pre-commit/CI runs: hooks + tests"
	@echo ""
	@echo "Container:"
	@echo "  make build                      download the latest version and build the image"
	@echo "  make build VER=2.1.5            build a specific version"
	@echo "  make build VER=... MISE_VERSION=v2026.10.18   pin mise"
	@echo "  make run                        TUI (the current directory is mounted as /workspace)"
	@echo "  make cmd CMD='...args...'       run one opencode command and exit"
	@echo "  make shell                      bash inside the container"
	@echo "  make auth                       OpenCode Console login (browser on the host)"
	@echo "  make stop                       stop all running opencode containers"
	@echo "  make clean                      full state reset: delete $(DATA)"
	@echo "  make distclean                  delete EVERYTHING: state + $(BUILD_DIR) + all opencode images"

sync:
	uv sync

build:
	@set -e; \
	if [ -n "$(VER)" ]; then V="$(VER)"; \
	else V=$$(curl -fsSL https://opencode.ai/update/api/latest/cli/npm | jq -r .version); fi; \
	[ -n "$$V" ] || { echo "could not determine the version"; exit 1; }; \
	echo ">> version: $$V"; \
	./fetch.sh "$$V"; \
	podman build --build-arg MISE_VERSION="$(MISE_VERSION)" -f Dockerfile -t $(IMAGE_REPO):$$V $(BUILD_DIR); \
	old=$$(podman images --format '{{.Tag}}' $(IMAGE_REPO) 2>/dev/null | grep -vx -e '<none>' -e "$$V" || true); \
	for t in $$old; do \
	  echo ">> removing the old image $(IMAGE_REPO):$$t"; \
	  podman rmi "$(IMAGE_REPO):$$t" >/dev/null 2>&1 || true; \
	done; \
	echo ">> done: $(IMAGE_REPO):$$V"

run:
	./oc

test:
	uv run pytest

lint:
	uv run ruff check oc tests/

checks:
	uv run pre-commit run --all-files && uv run pytest

cmd:
	@test -n "$(CMD)" || { echo "give a command: make cmd CMD='run -m opencode/glm-5.3-flash-free \"hi\"'"; exit 1; }
	./oc $(CMD)

shell:
	podman run -it --rm -v "$(DATA):/data" -v "$$PWD:/workspace" --entrypoint /bin/bash \
	  $(IMAGE_REPO):$$(podman images --format '{{.Tag}}' $(IMAGE_REPO) | grep -vx '<none>' | sort -V | tail -1)

auth:
	./oc auth login

stop:
	@ids=""; \
	for c in $$(podman ps -q 2>/dev/null); do \
	  case "$$(podman inspect -f '{{.Config.Image}}' $$c 2>/dev/null)" in \
	    *opencode*) ids="$$ids $$c" ;; \
	  esac; \
	done; \
	if [ -n "$$ids" ]; then \
	  echo ">> stopping opencode containers:$$ids"; \
	  podman stop -t 10 $$ids; \
	else \
	  echo ">> no running opencode containers"; \
	fi

clean:
	@echo ">> resetting container state: $(DATA)"
	@if command -v podman >/dev/null 2>&1 && [ -n "$$(podman ps -q 2>/dev/null)" ]; then \
	  for c in $$(podman ps -q); do \
	    if podman inspect -f '{{range .Mounts}}{{.Source}} {{end}}' $$c 2>/dev/null | grep -qF "$(DATA)"; then \
	      echo "!!! container $$c keeps $(DATA) mounted — first run: make stop"; \
	      exit 1; \
	    fi; \
	  done; \
	fi
	@if [ -z "$(DATA)" ] || [ "$(DATA)" = "/" ] || [ "$(DATA)" = "$(HOME)" ]; then \
	  echo "refusing: suspicious DATA='$(DATA)'"; exit 1; \
	fi
	@if [ -d "$(DATA)" ]; then \
	  rm -rf "$(DATA)"; \
	  echo ">> removed: $(DATA) (login, DB, cache, logs)"; \
	  echo ">> the next run is a clean container; restore the login via make auth"; \
	else \
	  echo ">> $(DATA) is already gone — clean"; \
	fi

distclean: stop clean
	@rm -rf $(BUILD_DIR)
	@echo ">> removing images $(IMAGE_REPO):*"
	@images=$$(podman images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^$(IMAGE_REPO):' || true); \
	if [ -n "$$images" ]; then \
	  for i in $$images; do \
	    podman rmi -f "$$i" >/dev/null 2>&1 || true; \
	  done; \
	else \
	  echo ">> no images found"; \
	fi
	@echo ">> wiped everything: state, $(BUILD_DIR), images"
