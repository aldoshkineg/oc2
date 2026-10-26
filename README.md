# oc2 — opencode CLI v2 in an isolated container

[![pre-commit](https://github.com/aldoshkineg/oc2/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/aldoshkineg/oc2/actions/workflows/pre-commit.yml)
[![test](https://github.com/aldoshkineg/oc2/actions/workflows/test.yml/badge.svg)](https://github.com/aldoshkineg/oc2/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://github.com/aldoshkineg/oc2)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Utility for isolating opencode (CLI v2) runs in a rootless podman container,
with per-project settings. The binary comes from the official npm channel
(`@opencode/cli-linux-x64`); by default `make build` takes the latest version,
or pin it explicitly (`make build VER=2.1.5`). Built with podman (rootless,
no root); plain docker works as well.

## Layout

```
oc2/
├── oc              launcher: ./oc [--project P] [--state N] [--mount SRC[:DST]] [args] — python3
├── profiles.toml.example   projects: state profile + paths for auto-detection + mounts (template; the config itself lives next to ./oc or in ~/.config/oc/profiles.toml)
├── pyproject.toml  uv project: dev dependencies (uv sync / uv run)
├── Makefile        all actions: make help (incl. make test / make lint)
├── Dockerfile      image build (opencode + bare mise)
├── fetch.sh        binary download (goes to /tmp/oc-build)
├── ruff.toml       lint config: make lint
├── .pre-commit-config.yaml  hooks: make checks (same as CI)
├── .github/workflows        CI: pre-commit + tests (via uv)
├── AGENTS.md       guidance for AI agents
├── tests/test_oc.py  35 tests: unit + e2e (podman is not required)
├── LICENSE         MIT
└── TODO.md         mount-improvement progress
```

Everything here is plain text files — committed to git as is. The binary and
build temp files live in `/tmp/oc-build`; opencode state lives in
`~/.local/share/oc2/profiles/<state>` (default `oc`). The launcher is a Python
script (stdlib, python >= 3.11 on the host). Python dependencies of your
projects — a venv inside `/workspace` (mounted from the host, survives
`--rm`).

## Running

```sh
./oc                                            # TUI (state = oc)
./oc run -m opencode/glm-5.3-flash-free "hi"    # one-shot command
./oc auth login                                 # login (browser on host)
./oc --state or2                                # TUI with profiles/or2 state
make shell                                      # bash inside the container
make stop                                       # stop all opencode containers
```

The directory `./oc` was launched from is mounted as `/workspace`; state is
`~/.local/share/oc2/profiles/<state>` → `/data` (default `oc`; another state
profile: `--state name`, or `OC_DATA=/path ./oc` for an arbitrary directory).
The old flat `~/.local/share/oc2/{cfg,data,…}` is migrated once, at first run,
into `profiles/<state>` (for daynews — `profiles/oc2`: profile has
`state = "oc2"`) and never again: after the move a `.migrated` marker is placed
in the root — even if the old directories reappear on disk nothing moves
(in a non-empty `profiles/<state>` flat dirs stay untouched with a warning).

## Workspaces and extra mounts

A workspace = state profile + a set of mounts, described by one section in
`profiles.toml` (oc's only config): looked up next to `./oc` first, then in
`~/.config/oc/profiles.toml` — the personal one, never committed. The repo
kept a sanitized template — `profiles.toml.example`. Own flags go
**before the opencode arguments** (after the first foreign token everything
is passed to opencode):

```sh
./oc --project dn run -m ... "hi"        # project dn from profiles.toml manually
./oc                                     # from a project directory → auto-detect
./oc --project-list                      # projects + effect for cwd
./oc --help                              # usage: flags, env, section format
./oc --mount ~/.config/newsboat/urls ... # mount without config
./oc --mount SRC:DST:ro ...              # explicit DST/options (ro)
OC_DRY_RUN=1 ./oc ...                    # print the podman command, don't run
                                         # (no state, no dirs; <auto> image)
```

Auto-detection: `oc` compares cwd with `paths` of `profiles.toml` sections
(cwd itself or a subdirectory); with several matches the deepest one wins,
with a printed warning.

`profiles.toml` (section = project; `state` — state profile, `paths` — where
the project lives for auto-detection, `mount` — paths, `mounts` — include
paths of other sections, `persistent` — keep the container between runs):

```toml
[daynews]
state = "oc2"                    # state → ~/.local/share/oc2/profiles/oc2
persistent = true                # named container, survives restarts
paths = [                        # ./oc from this dir (or deeper)
  "~/src/daynews",              # activates the project automatically
]
mount = [                        # missing on disk → warning, not an error
  "~/.local/state/daynews",
  "~/.local/share/newsboat/cache.db",
  "~/.local/share/newsboat/cache.db-wal",
  "~/.local/share/newsboat/cache.db-shm",
  "~/.config/newsboat/urls",
]
```

One config — next to `./oc` or `~/.config/oc/profiles.toml`. For tests it can
be overridden: `OC_PROFILES=/path`.

Host paths are mirrored into the XDG layout of the container:

| Host               | Container       |
| ------------------ | --------------- |
| `~/.local/state/x` | `/data/state/x` |
| `~/.local/share/x` | `/data/data/x`  |
| `~/.config/x`      | `/data/cfg/x`   |
| `~/.cache/x`       | `/data/cache/x` |
| outside `$HOME`    | `/mnt/...`      |

Extra mounts are rw: SQLite WAL databases don't work without write access to
`-wal`. Read-only is enforced only where there are no databases:
`--mount SRC:DST:ro`.

Don't open the same SQLite database from the container and the host at the
same time.

## Persistent projects

A project with `persistent = true` gets a named container
`oc2-<state>-<project>` (entrypoint sleeps, opencode is entered via
`podman exec`). Repeated exits do not destroy the container: binaries, pip/apt
packages and tool settings installed in a session survive restarts (the
`/data` state survives anyway — login, sessions, DB).

Everything about the container is baked at creation: the image, the profile
mounts, `/data`, and `/workspace` = `paths[0]` of the project (the cwd at
launch does not matter). Any difference between the profile and the container
is detected — a mount added, a mount revoked, a changed `paths[0]` — and
refused with a hint to recreate the container keeping the state
(`--drop-container`). A mount path missing at creation is skipped with a
warning and is baked nowhere: create such paths before the first run.

```sh
./oc                                             # enters the container (or
                                                 # creates it on first run)
./oc --project daynews                           # same, resolved manually
./oc --drop-container                            # remove the container(s)
                                                 # oc2-<state>-*, keep the
                                                 # state (login, sessions)
./oc --drop                                      # remove containers + the
                                                 # state profile altogether
```

Both drop flags resolve the target the same way (cwd project, `--project`,
`--state`) and refuse to run without one. `OC_DRY_RUN=1` prints the whole
chain (`create → start → exec` or the removal commands) without running them:
no state directory, no migration, and the image is only looked up when
possible (otherwise `<auto>` is printed).

## Layout inside the state profile (~/.local/share/oc2/profiles/<state>/)

| Path (inside the state profile)  | Contents                        |
| -------------------------------- | ------------------------------- |
| `cfg/opencode/`                  | config, `service.json`          |
| `data/opencode/opencode.db`      | DB: sessions, login credentials |
| `data/opencode/log/opencode.log` | logs (look here on errors)      |
| `cache/`                         | cache — safe to wipe anytime    |
| `state/`                         | service state                   |

## Development (uv)

Dev tooling is managed with [uv](https://docs.astral.sh/uv/): `pyproject.toml`
declares the dev group (pre-commit, pytest, ruff), `uv.lock` pins versions,
`.venv` is created in the project directory.

```sh
make sync            # uv sync: create/update .venv from uv.lock
make test            # uv run pytest (podman is not needed)
make lint            # uv run ruff check oc tests/
make checks          # pre-commit over all files + tests (same as CI)
make hooks           # pre-commit install — hooks on every git commit
```

## Building the image

```sh
make build                    # latest: download binary + build + tag
make build VER=2.1.5          # a specific version
make build VER=2.1.5 MISE_VERSION=v2026.10.18   # + pin mise
```

The image contains: `opencode` (npm binary) and a bare `mise` (`/usr/local/bin`,
data in `/opt/mise`, shims on PATH). Python and other runtimes are installed
on demand inside the container (`mise use -g python@3.12`); updates live in the
container layer; for one-off Python deps that must survive `--rm` — a venv in
`/workspace` (mounted from the host).

The image is tagged with the opencode version (`localhost/opencode:2.1.4`);
building a new version removes old images. `./oc` always runs the latest
built tag.

## Maintenance

```sh
make clean         # reset ~/.local/share/oc2 → a clean run (login again: make auth)
make distclean     # everything: stop containers, wipe state, /tmp/oc-build and all opencode images
```
