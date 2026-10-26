# AGENTS.md

Guidance for AI agents working on this repository.

## Project overview

oc2 is a launcher for running opencode (CLI v2) in an isolated rootless podman
container. Each project gets its own state directory, project auto-detection
by cwd, and extra mounts. The main entry point is the single-file Python
script `./oc` (stdlib only, python >= 3.11). The container image is built via
`make build` (see `Dockerfile` and `fetch.sh`).

## Useful commands

```sh
make sync     # uv sync: create .venv from uv.lock (dev deps: pre-commit, pytest, ruff)
make test     # run tests (pytest; podman is not required)
make lint     # ruff check over oc and tests/
make checks   # pre-commit over all files + tests (same as CI)
make help     # everything else (build, run, shell, clean, ...)
```

### Commit Messages

- Use Conventional Commits with a scope in parentheses: `feat(scope):`, `fix(scope):`, `refactor(scope):`, `chore(scope):`, etc.
- **Do NOT add `Co-Authored-By`, `Generated-with`, or any similar AI/tool trailer lines unless the user explicitly asks for them.** Keep commit messages clean and authored by the user. The AI assistant (`opencode`) must never append such trailers.
- **NEVER run `git commit` (or `git add` + `git commit`) without the user's explicit approval for that specific change — including fix commits made while troubleshooting.** Editing files is allowed; committing is not. When in doubt, ask first.
- Never amend, rebase, or force-push without explicit request.

## Conventions

- Documentation (README, TODO, AGENTS) is written in English.
- Runtime is stdlib-only; dev tools are managed with uv via `pyproject.toml`.
- There are no strict gate checks here — hooks and CI exist, but running them
  locally is optional. Use judgement.
- `--project`/profile semantics are described in README (Workspaces section);
  env overrides (`OC_DRY_RUN`, `OC_PROFILES`, ...) are listed in the `./oc`
  docstring (`./oc --help`).

## Tests

Tests live in `tests/test_oc.py` (unittest-style, run with pytest). They use
`OC_DRY_RUN` and an isolated fake `$HOME`, so real podman is not needed.
