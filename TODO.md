# TODO — improvements to the `oc` launcher

Context: we are reworking `oc` (bash → python3, stdlib only) and adding extra
container mounts. All decisions are agreed:

- language: **python3** (stdlib, no pip dependencies), script — `./oc`
- mechanism: **profiles + universal flag** (`--with <profile>`,
  `--mount SRC[:DST[:OPTS]]`)
- in-container paths: **mirror the XDG structure** into /data
  (state→/data/state, share→/data/data, config→/data/cfg, cache→/data/cache;
  anything else → /mnt/...)

## Done

- [x] `oc` rewritten in python3 (chosen as a single shebang file, `./oc` kept)
  - own flags only before the first opencode argument: `--with NAME[,...]`,
    `--mount SRC[:DST[:OPTS]]`, `--list-mounts`, `--` (after it the whole tail
    goes to opencode)
  - **daynews** profile:
    1. `~/.local/state/daynews/` as a whole → `/data/state/daynews`
       (daynews.db, golden.db and wal/shm go with the directory)
    2. `~/.local/share/newsboat/cache.db` (+ `-wal`, `-shm` if present) →
       `/data/data/newsboat/cache.db*` — wal/shm marked optional (not always
       present); cache.db in WAL mode requires rw, hence rw
    3. `~/.config/newsboat/urls` → `/data/cfg/newsboat/urls`
  - `--mount` parses `SRC[:DST[:OPTS]]`; without DST → the mirror path
  - missing profile files → warning (not an error); `--mount` with a
    non-existent SRC → error
  - dst collision check between two mounts
  - bash-version semantics preserved: OC_IMAGE / OC_DATA / OC_WORKSPACE,
    `-it` only with a TTY, proxy variable pass-through, `mkdir -p` for /data
  - added: `--list-mounts` (show the final mounts and exit),
    `OC_DRY_RUN=1` (print the podman command without running it)
  - image selection: `podman images` with numeric tag sorting ("2.10" > "2.9")
- [x] Small bug: `pick_image` called `podman images` without a repository
      filter — a foreign tag (e.g. `alpine:3.22`) glued onto `localhost/opencode`
      → `localhost/opencode:3.22`, with podman eager to pull it from the
      `localhost` registry (connection refused). A repo filter is added (as in
      the Makefile); the test fixes both the filter in the command and the
      latest-tag choice. Test count now 33.
- [x] Verified in a sandbox (python 3.12 installed via mise; podman not
      available — all runs via `OC_DRY_RUN=1` + a fake `OC_IMAGE`):
  - `python3 -m py_compile oc` — clean
  - `--list-mounts --with daynews`: mirror paths are correct
    (state→/data/state, share→/data/data, config→/data/cfg)
  - `-v` in a dry run go in the right order (data, workspace, profile)
  - wal is mounted when present; shm without a file is silently skipped
  - `--mount` without DST (mirror) / with DST + `:ro` — ok; with a
    non-existent SRC — error
  - a foreign flag after the first opencode argument goes to opencode as is
  - `--` disables parsing of our flags
  - unknown profile → usage error, exit 2
  - tag sorting: 2.10.0 > 2.9.1 > 2.2 > 2.1.5
  - env for tests:
    `PATH="/data/data/mise/installs/python/3.12/bin:/root/.local/bin:$PATH"`
    (mise in the sandbox: binary /root/.local/bin/mise, config /data/cfg/mise,
    tools /data/data/mise)

## Left

- [x] mise in the image (a thin layer: apt set unchanged + bare mise;
      python is NOT preinstalled — installed on demand)
- [ ] Verify on the host (only what the sandbox cannot):
  - a real `./oc` run (TUI) and `./oc run ...` with real podman
  - `./oc --with daynews run ...` with live wal/shm from a running newsboat
  - a behavioral check of the sqlite pre-ingest: does cache.db open from the
    container (single-file bind SQLite works, but the database must not be
    touched from the container and the host at the same time)
- [x] Docs updated: README (the "Extra mounts" section, the XDG-mirror table,
      examples, "in the image: opencode + mise + python"), Makefile
      (build passes MISE_VERSION, help updated), TODO
- [x] Profiles moved out of the script into `profiles.toml` (tomllib, format:
      `[profile-name]` with the `mount` and `optional` keys). Lookup: next to
      `./oc`, then `~/.config/oc/profiles.toml`; nowhere → a clear error (exit 2).
      Verified: the toml profile produces an identical podman command draft; the
      old hardcode removed from `oc`.
- [x] `optional` removed from the config (by decision): wal/shm just go into
      `mount`; the missing paths of a section are aggregated into one warning.
      The `profiles.toml` format: a section = workspace (`state`, `mounts` —
      including other people's sections with cycle protection, `mount` — own
      paths). Verified: `--with dn` with `state="or2"` gives /data from
      profiles/or2 + the daynews mounts; `--state` overrides the state; the flat
      root migration into profiles/oc works (list-mounts — without migration).
- [x] ruff in the repo (`ruff.toml`: E,W,F,I,UP; py311) + `make lint` — oc and
      tests are clean
- [x] tests in `tests/test_oc.py` — 28 of them (unittest, podman not needed:
      e2e via OC_DRY_RUN + an isolated HOME; `make test`). The tests uncovered and
      fixed 3 bugs: OC_PROFILES priority over the local toml, a false
      auto-detection when cwd is the parent of the project directory, a lost
      "project X (cwd)" print. die() now raises a plain SystemExit with a string —
      exit code 1.
- [x] Flat-root migration is strictly one-time: a `~/.local/share/oc2/.migrated`
      marker is placed after the move; with a non-empty `profiles/<state>` the
      flat directories stay untouched with a warning (nothing is wiped).
      Earlier the move could fire twice: freshly re-appeared `cfg/data` in the
      root were treated as "old state" and taken to the new state.
      The migration message now shows what exactly was moved
      (`{cfg,data}` and not just the root). Test count 35.
- [x] Best-practices revision + `--help` (called from /home/hash without
      mounts — this is the norm: cwd is not a project; `--project-list` now has
      a hint). Covered: `--help`/`-h` prints the docstring (after `--` it goes to
      opencode); dry-run quotes the arguments via shlex.join; the dead USAGE_EXIT
      removed; `--project` is validated before auto-detection; docstring updates
      (`load_profiles`, flags, env). Tests: 31 (+help/hint/quoting).
- [ ] (optional) `make shell` should also pass the day-profiles — currently
      shell mounts only /data and /workspace directly via podman
- [ ] (optional) a "pre-ingest" mode: a separate profile/flag so that the
      newsboat cache.db is mounted only when a pre-ingest is needed, and not
      always with daynews
- [ ] (optional) add the day-profile to the `make help` examples
