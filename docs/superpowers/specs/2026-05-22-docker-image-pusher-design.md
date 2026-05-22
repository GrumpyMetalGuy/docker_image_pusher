# Docker Image Pusher (`dip`) — Design

**Date:** 2026-05-22
**Status:** Approved (pending implementation plan)

## Purpose

A small, generic command-line utility that, when run from any project folder,
reads a `VERSION.txt` from the current directory, interactively bumps the semantic
version, builds the project's Docker image, and pushes it to a configured registry
under a set of rolling tags (`latest`, full version, minor, major). The target
registry is read from a shared config file in the user's home directory so the
same tool works across every project without per-project configuration.

## Key decisions

- **Language / runtime:** Python, run via `uv`. Single-file script using a PEP 723
  inline dependency block (`pyyaml`). Chosen for clean YAML parsing, good error
  handling, and testability while staying a "short util."
- **Packaging (Approach A):** One file, `pusher.py`, with logic split into small
  importable functions so it can be unit-tested. No full package / `pyproject.toml`.
- **Generic / location-independent:** The tool source lives in this repo and is
  installed once onto `PATH`. It operates on the **current working directory**
  wherever it is invoked — that folder supplies `VERSION.txt` and the `Dockerfile`
  (build context = CWD).
- **Shared config:** Lives at `$XDG_CONFIG_HOME/docker_image_pusher/config.yaml`
  (falling back to `~/.config/docker_image_pusher/config.yaml`), shared by all
  projects.
- **Invocation:** `pusher.py` carries a `#!/usr/bin/env -S uv run --script` shebang,
  is made executable, and is symlinked into `~/.local/bin/dip`. The user then runs
  `dip` from any project folder. `uv` resolves the inline dependencies on demand.
- **Install:** A repo `install.sh` performs the one-time setup (symlink + config
  scaffold) so the steps are reproducible and auditable rather than copy-pasted by
  hand. It is idempotent — safe to re-run after pulling updates.
- **Versioning:** Semantic versioning `MAJOR.MINOR.PATCH`. Bump levels map as:
  `major` → `(M+1).0.0`, `minor` → `M.(N+1).0`, `revision` → `M.N.(P+1)`.
- **Auth:** Assumes the user has already run `docker login`. No credentials are
  stored or handled by the tool.

## Files & layout

```
# Tool repo (this folder)
docker_image_pusher/
├── pusher.py          # #!/usr/bin/env -S uv run --script  (PEP 723 dep: pyyaml)
├── install.sh         # one-time installer (symlink + config scaffold)
├── test_pusher.py     # unit + mocked-docker tests
└── docs/superpowers/specs/2026-05-22-docker-image-pusher-design.md

# Created by install.sh (one-time)
~/.local/bin/dip                              -> symlink to pusher.py (chmod +x)
~/.config/docker_image_pusher/config.yaml     # registry: registry.example.com[/namespace]

# Any project the user runs `dip` in (the current working directory)
./VERSION.txt          # line 1: image name, line 2: semver (e.g. 1.7.3)
./Dockerfile           # build context = CWD
```

### `VERSION.txt` format

```
my-image-name
1.7.3
```

- Line 1: Docker image name (without registry or tag).
- Line 2: current semantic version `MAJOR.MINOR.PATCH`.
- Trailing whitespace / blank lines tolerated.

### `config.yaml` format

```yaml
registry: registry.example.com
# or with a namespace/org:
# registry: registry.example.com/myorg
```

- Single required key: `registry`. Used verbatim as the prefix; image refs are
  formed as `<registry>/<image_name>:<tag>`.

## Installation (`install.sh`)

A one-time, idempotent installer in the repo root. Run once after cloning:

```bash
./install.sh
```

Behavior:

0. **Preflight — require `uv`:** check `command -v uv`. If `uv` is not on `$PATH`,
   abort immediately (before any symlink/config changes) with a clear message and the
   install pointer (`https://docs.astral.sh/uv/` / `curl -LsSf https://astral.sh/uv/install.sh | sh`).
   `uv` is mandatory because the tool runs via the `uv run --script` shebang.
1. Resolve the absolute path to `pusher.py` (so the symlink survives regardless of
   the caller's CWD).
2. `chmod +x pusher.py`.
3. Ensure `~/.local/bin` exists; create the symlink `~/.local/bin/dip -> <abs>/pusher.py`.
   If the symlink already exists, refresh it to the current path (idempotent). If a
   non-symlink file named `dip` is in the way, abort with a clear message rather than
   clobbering it.
4. Ensure `~/.config/docker_image_pusher/` exists (honoring `$XDG_CONFIG_HOME`).
5. If `config.yaml` does not already exist there, scaffold a starter:
   ```yaml
   # Docker registry to push images to.
   # Include a namespace/org if needed, e.g. registry.example.com/myorg
   registry: registry.example.com
   ```
   An existing `config.yaml` is never overwritten.
6. Check whether `~/.local/bin` is on `$PATH`; if not, print a warning with the line
   to add to the user's shell rc.
7. Print a short "done" summary: the symlink target, the config path, and a reminder
   to edit `registry` and to be `docker login`'d.

The installer does **not** require root and touches only the user's home directory.

## Tagging scheme

For a resolved new version `1.7.3`, the tool pushes **four** tags:

| Tag      | Ref                              | Purpose                              |
|----------|----------------------------------|--------------------------------------|
| `1.7.3`  | `registry/image:1.7.3`           | Exact pin                            |
| `1.7`    | `registry/image:1.7`             | Rolling: latest patch within `1.7`   |
| `1`      | `registry/image:1`               | Rolling: latest minor/patch within `1` |
| `latest` | `registry/image:latest`          | Newest overall                       |

This follows the official-image convention so downstream consumers can pin to `1`
or `1.7` and automatically pick up bugfix releases.

## Execution flow

Run `dip` from a project folder:

1. **Read `./VERSION.txt`** → `image_name` (line 1), `version` (line 2). Validate it
   parses as semver `MAJOR.MINOR.PATCH`.
2. **Read config** at `$XDG_CONFIG_HOME/docker_image_pusher/config.yaml`
   (fallback `~/.config/...`) → require `registry` key.
3. **Prompt for bump level**: `major` / `minor` / `revision`. Compute the new version.
4. **Compute tags** for the new version → four full refs (see Tagging scheme).
5. **Confirmation**: print the four refs and the build context (CWD), prompt `y/n`.
   Abort with no docker calls if declined.
6. **Build**: `docker build -t <registry/image:NEW> .`, then `docker tag` the built
   image to the other three refs.
7. **Push**: `docker push` each of the four refs in turn.
8. **Write-back**: only after **all** pushes succeed, write the new version back to
   `./VERSION.txt` (preserving the image-name line). A failure anywhere before this
   leaves `VERSION.txt` unchanged so the run can be retried cleanly.

## Components (functions in `pusher.py`)

Pure / testable:

- `read_version(path) -> (name: str, version: Version)` — parse and validate.
- `bump(version: Version, level: str) -> Version` — pure semver bump.
- `tag_list(version: Version) -> list[str]` — e.g. `["1.7.3", "1.7", "1", "latest"]`.
- `load_registry(path) -> str` — read YAML, require `registry`.
- `image_refs(registry, name, tags) -> list[str]` — build full refs.
- `write_version(path, name, version)` — write-back, preserving format.
- `config_path() -> Path` — resolve XDG / `~/.config` location.

Side-effecting (thin `subprocess` wrappers around the `docker` CLI):

- `build_image(ref, context=".")`
- `tag_image(src_ref, dst_ref)`
- `push_image(ref)`

Orchestration:

- `main()` — wires the flow, prompts, confirmation, ordering, exit codes.

## Error handling

- Missing `./VERSION.txt`, missing `./Dockerfile`, missing config file, missing
  `registry` key, or a non-semver version string → clear human-readable message,
  exit non-zero, **no docker commands run**.
- Any `docker build` / `tag` / `push` failure → surface docker's stderr, exit
  non-zero, **`VERSION.txt` left unchanged**.
- Push authentication failures surface docker's own error (the tool assumes an
  existing `docker login`).
- User declines the confirmation prompt → exit zero (or a distinct "aborted" code),
  nothing built or pushed.

## Testing

Per project testing standards, both unit and integration coverage from the start.

- **Unit (pure logic, no docker):**
  - `bump` for each level, including rollovers (`1.7.9` + revision, `1.9.0` + minor).
  - `tag_list` produces exactly the four expected tags in order.
  - `read_version` for valid input, missing file, malformed lines, non-semver.
  - `load_registry` for present key, missing key, missing file.
  - `write_version` round-trips and preserves the image-name line.
- **Integration (docker mocked):**
  - Assert `build_image` / `tag_image` / `push_image` are invoked with the correct
    argument lists and in the correct order (build → tag×3 → push×4).
  - Assert write-back happens **only** after all four pushes succeed (simulate a
    push failure → `VERSION.txt` unchanged, non-zero exit).
  - Confirmation declined → no docker invocations.
  - Keep CI-runnable: mock the `subprocess`/`docker` boundary, no real registry.
- **Installer:** verify `install.sh` by running it in a temp `$HOME`/`$XDG_CONFIG_HOME`
  sandbox — asserts the symlink is created/refreshed, the config is scaffolded only
  when absent, an existing config is preserved, and a second run is a no-op (idempotent).
  Also assert the `uv` preflight aborts cleanly (non-zero, no changes made) when `uv`
  is absent from `$PATH`.

## Out of scope (YAGNI)

- Storing or managing registry credentials / `docker login`.
- Multi-architecture / buildx, build args, alternate Dockerfile paths.
- Auto-detecting or generating a Dockerfile.
- Pre-release / build-metadata semver suffixes.
- A `pyproject.toml` / installable package (may be added later if needed).
