# Docker Image Pusher (`dip`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `dip`, a generic CLI that reads/creates a project's `VERSION.txt`, interactively bumps the semver, builds the Docker image, and pushes rolling tags (`X.Y.Z`, `X.Y`, `X`, `latest`) to a home-dir-configured registry.

**Architecture:** A single self-contained Python script (`pusher.py`) run via `uv` (PEP 723 inline deps). Logic is split into small pure functions (parse/bump/tag/config/write) plus thin `subprocess` wrappers around the `docker` CLI and interactive prompt helpers, all orchestrated by `main()`. A separate idempotent `install.sh` symlinks the script onto `PATH` as `dip` and scaffolds the shared config.

**Tech Stack:** Python 3.11+, `uv` (script runner + ephemeral test envs), `pyyaml` (config parsing), `pytest` (tests), Bash (installer), Docker CLI (build/push).

**Spec:** `docs/superpowers/specs/2026-05-22-docker-image-pusher-design.md`

---

## Conventions used throughout this plan

- **Repo root** is `/home/peter/Development/tools/docker_image_pusher`. All paths below are relative to it. `pusher.py` and the test files live in the repo root (flat layout — Approach A).
- **Test command** (run from repo root): every test step uses
  `uv run --with pyyaml --with pytest pytest`
  uv builds an ephemeral env containing `pyyaml` + `pytest`; pytest prepends the repo root to `sys.path`, so `import pusher` resolves to `./pusher.py`. No `pyproject.toml` is created.
- **Why `import pusher` works:** the PEP 723 `# /// script` block and the shebang are plain comments to a normal Python import; they only matter when `uv run pusher.py` executes the script directly. The module guards execution behind `if __name__ == "__main__":`, so importing it never runs `main()`.
- **Version representation:** a `typing.NamedTuple` `Version(major, minor, patch)` with a `__str__` of `"M.N.P"`.
- **Run log:** the executing session should maintain `RUNS.md` per the repo convention (create/append a run entry, fill Summary before the final commit). This is session bookkeeping, not a code task, so it is not listed as a task below.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `pusher.py` | The entire tool: pure helpers, docker wrappers, prompts, `main()`. Single file, ~180 lines. |
| `test_pusher.py` | Unit tests for pure helpers + integration tests for `main()` (docker mocked, prompts scripted). |
| `install.sh` | One-time idempotent installer: uv/docker preflight, symlink to `~/.local/bin/dip`, config scaffold. |
| `test_install.py` | Tests that run `install.sh` in a sandboxed `$HOME`/`$XDG_CONFIG_HOME` with a controlled `$PATH`. |
| `README.md` | Brief usage + install instructions. |

---

## Task 1: Scaffold `pusher.py` with `Version` and `parse_version`

**Files:**
- Create: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Create `test_pusher.py`:

```python
import pytest

import pusher
from pusher import Version, parse_version


def test_parse_version_valid():
    assert parse_version("1.7.3") == Version(1, 7, 3)


def test_parse_version_str_roundtrip():
    assert str(parse_version("10.0.42")) == "10.0.42"


def test_parse_version_strips_whitespace():
    assert parse_version("  2.3.4  ") == Version(2, 3, 4)


@pytest.mark.parametrize("bad", ["1.2", "1.2.3.4", "1.2.x", "abc", "", "1..3", "-1.0.0"])
def test_parse_version_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_version(bad)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -v`
Expected: collection/import error or FAIL — `pusher` module / `parse_version` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `pusher.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""dip — build a project's Docker image and push rolling tags to a registry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import yaml


class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(s: str) -> Version:
    parts = s.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Version must be MAJOR.MINOR.PATCH, got: {s!r}")
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError:
        raise ValueError(f"Version components must be integers, got: {s!r}")
    if min(major, minor, patch) < 0:
        raise ValueError(f"Version components must be non-negative, got: {s!r}")
    return Version(major, minor, patch)


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -v`
Expected: PASS (4 tests / parametrized cases all green).

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add pusher.py skeleton with Version + parse_version"
```

---

## Task 2: `bump`

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import bump


def test_bump_major():
    assert bump(Version(1, 7, 3), "major") == Version(2, 0, 0)


def test_bump_minor():
    assert bump(Version(1, 7, 3), "minor") == Version(1, 8, 0)


def test_bump_revision():
    assert bump(Version(1, 7, 3), "revision") == Version(1, 7, 4)


def test_bump_unknown_level():
    with pytest.raises(ValueError):
        bump(Version(1, 0, 0), "patch")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k bump -v`
Expected: FAIL — `bump` is not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `parse_version`:

```python
def bump(version: Version, level: str) -> Version:
    if level == "major":
        return Version(version.major + 1, 0, 0)
    if level == "minor":
        return Version(version.major, version.minor + 1, 0)
    if level == "revision":
        return Version(version.major, version.minor, version.patch + 1)
    raise ValueError(f"Unknown bump level: {level!r}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k bump -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add semver bump"
```

---

## Task 3: `tag_list` and `image_refs`

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import image_refs, tag_list


def test_tag_list_order_and_values():
    assert tag_list(Version(1, 7, 3)) == ["1.7.3", "1.7", "1", "latest"]


def test_tag_list_zero_version():
    assert tag_list(Version(0, 1, 0)) == ["0.1.0", "0.1", "0", "latest"]


def test_image_refs_prefixes_registry_and_name():
    refs = image_refs("registry.example.com/org", "app", ["1.7.3", "latest"])
    assert refs == [
        "registry.example.com/org/app:1.7.3",
        "registry.example.com/org/app:latest",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "tag_list or image_refs" -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `bump`:

```python
def tag_list(version: Version) -> list[str]:
    return [str(version), f"{version.major}.{version.minor}", f"{version.major}", "latest"]


def image_refs(registry: str, name: str, tags: list[str]) -> list[str]:
    return [f"{registry}/{name}:{tag}" for tag in tags]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "tag_list or image_refs" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add tag_list and image_refs"
```

---

## Task 4: `read_version`

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import read_version


def test_read_version_valid(tmp_path):
    f = tmp_path / "VERSION.txt"
    f.write_text("my-image\n1.7.3\n")
    name, version = read_version(f)
    assert name == "my-image"
    assert version == Version(1, 7, 3)


def test_read_version_tolerates_blank_lines_and_whitespace(tmp_path):
    f = tmp_path / "VERSION.txt"
    f.write_text("\n  my-image  \n\n 1.7.3 \n\n")
    name, version = read_version(f)
    assert name == "my-image"
    assert version == Version(1, 7, 3)


def test_read_version_missing_second_line(tmp_path):
    f = tmp_path / "VERSION.txt"
    f.write_text("my-image\n")
    with pytest.raises(ValueError):
        read_version(f)


def test_read_version_non_semver(tmp_path):
    f = tmp_path / "VERSION.txt"
    f.write_text("my-image\nnot-a-version\n")
    with pytest.raises(ValueError):
        read_version(f)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k read_version -v`
Expected: FAIL — `read_version` not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `image_refs`:

```python
def read_version(path: Path) -> tuple[str, Version]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(
            f"{path} must have the image name on line 1 and a semver on line 2"
        )
    return lines[0], parse_version(lines[1])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k read_version -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add read_version"
```

---

## Task 5: `config_path` and `load_registry`

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import config_path, load_registry


def test_config_path_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "docker_image_pusher" / "config.yaml"


def test_config_path_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_path() == tmp_path / ".config" / "docker_image_pusher" / "config.yaml"


def test_load_registry_reads_key(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("registry: registry.example.com/org\n")
    assert load_registry(f) == "registry.example.com/org"


def test_load_registry_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "nope.yaml")


def test_load_registry_missing_key(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("something_else: 1\n")
    with pytest.raises(ValueError):
        load_registry(f)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "config_path or load_registry" -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `read_version`:

```python
def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "docker_image_pusher" / "config.yaml"


def load_registry(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Run ./install.sh or create it with a 'registry:' key."
        )
    data = yaml.safe_load(path.read_text()) or {}
    registry = data.get("registry")
    if not isinstance(registry, str) or not registry.strip():
        raise ValueError(f"{path} must contain a non-empty 'registry:' value")
    return registry.strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "config_path or load_registry" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add config_path and load_registry"
```

---

## Task 6: `write_version`

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import write_version


def test_write_version_roundtrips(tmp_path):
    f = tmp_path / "VERSION.txt"
    write_version(f, "my-image", Version(2, 0, 0))
    assert f.read_text() == "my-image\n2.0.0\n"
    # round-trips back through read_version
    name, version = read_version(f)
    assert name == "my-image"
    assert version == Version(2, 0, 0)


def test_write_version_creates_missing_file(tmp_path):
    f = tmp_path / "VERSION.txt"
    assert not f.exists()
    write_version(f, "fresh", Version(0, 1, 0))
    assert f.exists()
    assert f.read_text() == "fresh\n0.1.0\n"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k write_version -v`
Expected: FAIL — `write_version` not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `load_registry`:

```python
def write_version(path: Path, name: str, version: Version) -> None:
    path.write_text(f"{name}\n{version}\n")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k write_version -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add write_version"
```

---

## Task 7: Docker wrappers (`_run`, `build_image`, `tag_image`, `push_image`)

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
import pusher as pusher_mod
from pusher import build_image, push_image, tag_image


def test_docker_wrappers_build_correct_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))

    build_image("reg/app:1.0.0", ".")
    tag_image("reg/app:1.0.0", "reg/app:latest")
    push_image("reg/app:1.0.0")

    assert calls == [
        ["docker", "build", "-t", "reg/app:1.0.0", "."],
        ["docker", "tag", "reg/app:1.0.0", "reg/app:latest"],
        ["docker", "push", "reg/app:1.0.0"],
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k docker_wrappers -v`
Expected: FAIL — wrappers / `_run` not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after `write_version`:

```python
def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def build_image(ref: str, context: str = ".") -> None:
    _run(["docker", "build", "-t", ref, context])


def tag_image(src: str, dst: str) -> None:
    _run(["docker", "tag", src, dst])


def push_image(ref: str) -> None:
    _run(["docker", "push", ref])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k docker_wrappers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add docker subprocess wrappers"
```

---

## Task 8: Interactive prompts (`prompt_bump_level`, `bootstrap_version`, `confirm`)

These take an injected `ask` callable (default `input`) so tests can script answers without monkeypatching builtins.

**Files:**
- Modify: `pusher.py`
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
from pusher import bootstrap_version, confirm, prompt_bump_level


def scripted(answers):
    """Return an `ask`-compatible callable that yields the given answers in order."""
    it = iter(answers)

    def ask(_prompt):
        return next(it)

    return ask


def test_prompt_bump_level_accepts_valid():
    assert prompt_bump_level(ask=scripted(["minor"])) == "minor"


def test_prompt_bump_level_is_case_insensitive():
    assert prompt_bump_level(ask=scripted(["REVISION"])) == "revision"


def test_prompt_bump_level_reprompts_on_invalid():
    assert prompt_bump_level(ask=scripted(["patch", "", "major"])) == "major"


def test_bootstrap_version_uses_default(capsys):
    name, version = bootstrap_version(ask=scripted(["my-image", ""]))
    assert name == "my-image"
    assert version == Version(0, 1, 0)


def test_bootstrap_version_custom_value():
    name, version = bootstrap_version(ask=scripted(["my-image", "2.3.4"]))
    assert version == Version(2, 3, 4)


def test_bootstrap_version_reprompts_empty_name_and_bad_version():
    name, version = bootstrap_version(ask=scripted(["", "app", "x.y.z", "1.0.0"]))
    assert name == "app"
    assert version == Version(1, 0, 0)


def test_confirm_yes():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted(["y"])) is True


def test_confirm_no_default():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted([""])) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "prompt_bump_level or bootstrap_version or confirm" -v`
Expected: FAIL — prompt helpers not defined.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, add after the docker wrappers:

```python
def prompt_bump_level(ask=input) -> str:
    while True:
        answer = ask("Bump level (major / minor / revision): ").strip().lower()
        if answer in ("major", "minor", "revision"):
            return answer
        print(f"Invalid choice: {answer!r}. Enter 'major', 'minor', or 'revision'.")


def bootstrap_version(ask=input) -> tuple[str, Version]:
    print("No VERSION.txt found in this directory — let's create one.")
    name = ""
    while not name:
        name = ask("Image name: ").strip()
        if not name:
            print("Image name cannot be empty.")
    while True:
        raw = ask(
            "Starting version — the version this NEW image will be built and pushed as [0.1.0]: "
        ).strip()
        try:
            return name, parse_version(raw or "0.1.0")
        except ValueError as exc:
            print(exc)


def confirm(refs: list[str], context: Path, ask=input) -> bool:
    print(f"\nAbout to build {context} and push:")
    for ref in refs:
        print(f"  {ref}")
    return ask("Proceed? [y/N]: ").strip().lower() in ("y", "yes")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "prompt_bump_level or bootstrap_version or confirm" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: add interactive bump/bootstrap/confirm prompts"
```

---

## Task 9: `main()` — normal run (existing VERSION.txt)

`main()` uses `Path.cwd()`, so integration tests `monkeypatch.chdir(tmp_path)` and patch `pusher._run` plus `builtins.input`.

**Files:**
- Modify: `pusher.py` (replace the `main` stub)
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
def _make_input(answers):
    it = iter(answers)
    return lambda _prompt: next(it)


def _setup_config(monkeypatch, tmp_path, registry="reg.example.com/org"):
    cfg_home = tmp_path / "xdg"
    cfg = cfg_home / "docker_image_pusher" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(f"registry: {registry}\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))


def test_main_normal_run_builds_tags_pushes_and_writes_back(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.7.2\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))
    # bump level = revision, then confirm = y
    monkeypatch.setattr("builtins.input", _make_input(["revision", "y"]))

    assert pusher_mod.main() == 0

    base = "reg.example.com/org/app"
    assert calls == [
        ["docker", "build", "-t", f"{base}:1.7.3", "."],
        ["docker", "tag", f"{base}:1.7.3", f"{base}:1.7"],
        ["docker", "tag", f"{base}:1.7.3", f"{base}:1"],
        ["docker", "tag", f"{base}:1.7.3", f"{base}:latest"],
        ["docker", "push", f"{base}:1.7.3"],
        ["docker", "push", f"{base}:1.7"],
        ["docker", "push", f"{base}:1"],
        ["docker", "push", f"{base}:latest"],
    ]
    assert (proj / "VERSION.txt").read_text() == "app\n1.7.3\n"


def test_main_missing_dockerfile_errors_before_docker(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("builtins.input", _make_input([]))

    assert pusher_mod.main() == 1
    assert calls == []


def test_main_missing_config_errors_before_docker(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("builtins.input", _make_input([]))

    assert pusher_mod.main() == 1
    assert calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "main_normal_run or missing_dockerfile or missing_config" -v`
Expected: FAIL — `main` raises `NotImplementedError`.

- [ ] **Step 3: Write the minimal implementation**

In `pusher.py`, replace the `main` stub with:

```python
def main() -> int:
    cwd = Path.cwd()
    version_file = cwd / "VERSION.txt"
    dockerfile = cwd / "Dockerfile"
    try:
        if not dockerfile.exists():
            raise FileNotFoundError(f"No Dockerfile found in {cwd}")
        registry = load_registry(config_path())

        if version_file.exists():
            name, current = read_version(version_file)
            new_version = bump(current, prompt_bump_level())
        else:
            name, new_version = bootstrap_version()

        refs = image_refs(registry, name, tag_list(new_version))
        if not confirm(refs, cwd):
            print("Aborted.")
            return 0

        build_image(refs[0], ".")
        for dst in refs[1:]:
            tag_image(refs[0], dst)
        for ref in refs:
            push_image(ref)

        write_version(version_file, name, new_version)
        print(f"Pushed {name} {new_version}  ({', '.join(tag_list(new_version))})")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: docker command failed (exit {exc.returncode})", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "main_normal_run or missing_dockerfile or missing_config" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pusher.py test_pusher.py
git commit -m "feat: implement main orchestration for normal run"
```

---

## Task 10: `main()` — bootstrap run (missing VERSION.txt)

**Files:**
- Modify: none (behavior already in `main`)
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
def test_main_bootstrap_creates_file_after_push(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    # NOTE: no VERSION.txt
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))
    # bootstrap: image name = "newapp", version = "" (=> default 0.1.0), confirm = y
    monkeypatch.setattr("builtins.input", _make_input(["newapp", "", "y"]))

    assert pusher_mod.main() == 0

    base = "reg.example.com/org/newapp"
    # entered version used as-is (no bump) -> 0.1.0 tags
    assert calls[0] == ["docker", "build", "-t", f"{base}:0.1.0", "."]
    assert ["docker", "push", f"{base}:0.1.0"] in calls
    assert ["docker", "push", f"{base}:latest"] in calls
    assert (proj / "VERSION.txt").read_text() == "newapp\n0.1.0\n"
```

- [ ] **Step 2: Run the test to verify it fails (or passes immediately)**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k bootstrap_creates_file -v`
Expected: PASS — `main` already routes to `bootstrap_version` when `VERSION.txt` is absent. (If it fails, fix `main`'s branch before continuing.)

- [ ] **Step 3: No new implementation needed**

This task verifies the bootstrap branch end-to-end. If Step 2 passed, proceed.

- [ ] **Step 4: Re-run the full suite**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add test_pusher.py
git commit -m "test: cover bootstrap run that creates VERSION.txt after push"
```

---

## Task 11: `main()` — abort and docker-failure cases

**Files:**
- Modify: none (behavior already in `main`)
- Test: `test_pusher.py`

- [ ] **Step 1: Write the failing test**

Append to `test_pusher.py`:

```python
def test_main_decline_confirmation_does_nothing(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))
    # bump level = minor, then decline confirm
    monkeypatch.setattr("builtins.input", _make_input(["minor", "n"]))

    assert pusher_mod.main() == 0
    assert calls == []  # nothing built or pushed
    assert (proj / "VERSION.txt").read_text() == "app\n1.0.0\n"  # unchanged


def test_main_push_failure_leaves_version_unchanged(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    def fake_run(cmd):
        if cmd[:2] == ["docker", "push"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pusher_mod, "_run", fake_run)
    monkeypatch.setattr("builtins.input", _make_input(["revision", "y"]))

    assert pusher_mod.main() == 1
    assert (proj / "VERSION.txt").read_text() == "app\n1.0.0\n"  # NOT bumped


def test_main_bootstrap_push_failure_creates_no_file(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    def fake_run(cmd):
        if cmd[:2] == ["docker", "push"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pusher_mod, "_run", fake_run)
    monkeypatch.setattr("builtins.input", _make_input(["newapp", "0.1.0", "y"]))

    assert pusher_mod.main() == 1
    assert not (proj / "VERSION.txt").exists()  # no half-written file
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -k "decline_confirmation or push_failure" -v`
Expected: PASS — these behaviors follow from `main`'s ordering (write-back only after pushes). If any fail, fix `main` before continuing.

- [ ] **Step 3: No new implementation needed**

- [ ] **Step 4: Run the full suite**

Run: `uv run --with pyyaml --with pytest pytest test_pusher.py -v`
Expected: PASS (entire `pusher.py` suite green).

- [ ] **Step 5: Commit**

```bash
git add test_pusher.py
git commit -m "test: cover abort and docker-failure paths"
```

---

## Task 12: `install.sh`

A POSIX-bash installer that uses only `mkdir`, `ln`, `chmod` as external commands (path resolution via bash builtins), so tests can sandbox it with a controlled `$PATH`.

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write the installer**

Create `install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# --- Preflight: dependency checks -------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' is required but not found on PATH." >&2
    echo "       Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "       Docs: https://docs.astral.sh/uv/" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "warning: 'docker' not found on PATH. dip needs the docker CLI at run time;" >&2
    echo "         install Docker before using dip (continuing with install)." >&2
fi

# --- Resolve paths (bash builtins only) -------------------------------------
script_dir="$(cd "${0%/*}" 2>/dev/null && pwd)"
pusher="${script_dir}/pusher.py"
if [ ! -f "${pusher}" ]; then
    echo "error: pusher.py not found next to install.sh (${pusher})." >&2
    exit 1
fi

bin_dir="${HOME}/.local/bin"
link="${bin_dir}/dip"
config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/docker_image_pusher"
config="${config_dir}/config.yaml"

# --- Make the script executable + symlink it as `dip` -----------------------
chmod +x "${pusher}"
mkdir -p "${bin_dir}"
if [ -e "${link}" ] && [ ! -L "${link}" ]; then
    echo "error: ${link} exists and is not a symlink; refusing to overwrite." >&2
    exit 1
fi
ln -sfn "${pusher}" "${link}"
echo "linked ${link} -> ${pusher}"

# --- Scaffold config (never overwrite an existing one) ----------------------
mkdir -p "${config_dir}"
if [ -f "${config}" ]; then
    echo "config already exists, leaving it untouched: ${config}"
else
    {
        echo "# Docker registry to push images to."
        echo "# Include a namespace/org if needed, e.g. registry.example.com/myorg"
        echo "registry: registry.example.com"
    } > "${config}"
    echo "wrote starter config: ${config}"
fi

# --- PATH hint --------------------------------------------------------------
case ":${PATH}:" in
    *":${bin_dir}:"*) ;;
    *) echo "note: ${bin_dir} is not on your PATH. Add it, e.g.:"
       echo "      echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;;
esac

echo
echo "Done. Edit ${config} to set your registry, make sure you're 'docker login'-ed,"
echo "then run 'dip' from any project folder containing a Dockerfile."
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x install.sh`

- [ ] **Step 3: Smoke-test the syntax**

Run: `bash -n install.sh`
Expected: no output, exit 0 (valid syntax).

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "feat: add idempotent install.sh with uv/docker preflight"
```

---

## Task 13: Installer tests

Runs `install.sh` under `bash` with a fully controlled `$PATH` (a temp `bin` holding stub `uv`/`docker` plus symlinks to the real `mkdir`/`ln`/`chmod`), and sandboxed `$HOME`/`$XDG_CONFIG_HOME`. Because `install.sh` only does `command -v` on `uv`/`docker` (it never executes them), stubs are sufficient to drive the preflight branches.

**Files:**
- Create: `test_install.py`

- [ ] **Step 1: Write the failing test**

Create `test_install.py`:

```python
import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent
COREUTILS = ["mkdir", "ln", "chmod", "pwd", "cat"]


def _make_stub(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _bin_with(tools, *, uv=True, docker=True):
    """Create a temp bin dir with symlinked coreutils and optional uv/docker stubs."""
    bindir = tools / "bin"
    bindir.mkdir()
    for name in COREUTILS:
        real = shutil.which(name)
        assert real, f"{name} not found on test host PATH"
        (bindir / name).symlink_to(real)
    if uv:
        _make_stub(bindir / "uv")
    if docker:
        _make_stub(bindir / "docker")
    return bindir


def _run_install(tmp_path, *, uv=True, docker=True):
    home = tmp_path / "home"
    xdg = home / ".config"
    home.mkdir()
    bindir = _bin_with(tmp_path, uv=uv, docker=docker)
    # Copy installer + pusher.py into an isolated repo dir
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(REPO / "install.sh", repo / "install.sh")
    shutil.copy(REPO / "pusher.py", repo / "pusher.py")
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg),
        "PATH": str(bindir),
    }
    proc = subprocess.run(
        ["bash", str(repo / "install.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, home, xdg, repo


def test_install_creates_symlink_and_config(tmp_path):
    proc, home, xdg, repo = _run_install(tmp_path)
    assert proc.returncode == 0, proc.stderr
    link = home / ".local" / "bin" / "dip"
    assert link.is_symlink()
    assert os.readlink(link) == str(repo / "pusher.py")
    config = xdg / "docker_image_pusher" / "config.yaml"
    assert config.exists()
    assert "registry:" in config.read_text()


def test_install_is_idempotent(tmp_path):
    _run_install(tmp_path)
    proc, home, xdg, repo = _run_install(tmp_path)  # second run, same sandbox dirs? -> use fresh
    # NOTE: _run_install uses fresh subdirs each call via tmp_path children that already exist;
    # to truly re-run against the same HOME, call the inner steps twice:
    assert proc.returncode == 0, proc.stderr


def test_install_preserves_existing_config(tmp_path):
    # First install, then overwrite config, then re-run installer against same HOME.
    home = tmp_path / "home"
    xdg = home / ".config"
    home.mkdir()
    bindir = _bin_with(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(REPO / "install.sh", repo / "install.sh")
    shutil.copy(REPO / "pusher.py", repo / "pusher.py")
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(xdg), "PATH": str(bindir)}

    first = subprocess.run(["bash", str(repo / "install.sh")], capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr

    config = xdg / "docker_image_pusher" / "config.yaml"
    config.write_text("registry: my.private.registry/team\n")

    second = subprocess.run(["bash", str(repo / "install.sh")], capture_output=True, text=True, env=env)
    assert second.returncode == 0, second.stderr
    assert config.read_text() == "registry: my.private.registry/team\n"  # untouched


def test_install_aborts_without_uv(tmp_path):
    proc, home, xdg, repo = _run_install(tmp_path, uv=False)
    assert proc.returncode != 0
    assert "uv" in proc.stderr
    assert not (home / ".local" / "bin" / "dip").exists()  # no changes made
    assert not (xdg / "docker_image_pusher" / "config.yaml").exists()


def test_install_warns_without_docker(tmp_path):
    proc, home, xdg, repo = _run_install(tmp_path, docker=False)
    assert proc.returncode == 0, proc.stderr
    assert "docker" in proc.stderr.lower()
    assert (home / ".local" / "bin" / "dip").is_symlink()  # install still completed
```

> Note for the implementer: the `test_install_is_idempotent` body above is a placeholder shape — replace it with the explicit two-run-against-same-HOME pattern shown in `test_install_preserves_existing_config` (create `home`/`xdg`/`repo` once, run `install.sh` twice with the same `env`, assert the second run exits 0 and the symlink still points at `repo/pusher.py`). Do not rely on `_run_install` twice, since it builds fresh dirs each call.

- [ ] **Step 2: Run the tests to verify they fail or error**

Run: `uv run --with pytest pytest test_install.py -v`
Expected: Initially FAIL on `test_install_is_idempotent` (placeholder) — rewrite that test per the note so it runs `install.sh` twice against one sandboxed HOME.

- [ ] **Step 3: Fix the idempotency test**

Rewrite `test_install_is_idempotent` to:

```python
def test_install_is_idempotent(tmp_path):
    home = tmp_path / "home"
    xdg = home / ".config"
    home.mkdir()
    bindir = _bin_with(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(REPO / "install.sh", repo / "install.sh")
    shutil.copy(REPO / "pusher.py", repo / "pusher.py")
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(xdg), "PATH": str(bindir)}

    first = subprocess.run(["bash", str(repo / "install.sh")], capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(["bash", str(repo / "install.sh")], capture_output=True, text=True, env=env)
    assert second.returncode == 0, second.stderr

    link = home / ".local" / "bin" / "dip"
    assert link.is_symlink()
    assert os.readlink(link) == str(repo / "pusher.py")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest pytest test_install.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add test_install.py
git commit -m "test: sandboxed install.sh coverage (symlink, config, preflight)"
```

---

## Task 14: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

Create `README.md`:

```markdown
# dip — Docker Image Pusher

A small CLI that builds the Docker image in the current directory and pushes it to
your registry under rolling semver tags (`X.Y.Z`, `X.Y`, `X`, `latest`).

## Install

```bash
./install.sh
```

This requires [`uv`](https://docs.astral.sh/uv/). It symlinks `pusher.py` to
`~/.local/bin/dip` and creates `~/.config/docker_image_pusher/config.yaml`. Edit that
file to set your registry:

```yaml
registry: registry.example.com/myorg
```

Make sure `~/.local/bin` is on your `PATH` and that you are `docker login`-ed.

## Usage

From any project folder containing a `Dockerfile`:

```bash
dip
```

- If `VERSION.txt` exists (line 1 = image name, line 2 = `MAJOR.MINOR.PATCH`), you are
  prompted for a bump level (major / minor / revision).
- If `VERSION.txt` is missing, you are prompted for an image name and starting version
  (default `0.1.0`); that version is built and pushed as-is and the file is created.

`dip` then shows the tags it will push, asks for confirmation, builds, pushes
`X.Y.Z` / `X.Y` / `X` / `latest`, and (on success) writes the new version back to
`VERSION.txt`.

## Development

```bash
uv run --with pyyaml --with pytest pytest        # pusher unit/integration tests
uv run --with pytest pytest test_install.py      # installer tests
```
```

- [ ] **Step 2: Verify it renders**

Run: `uv run --with pyyaml --with pytest pytest` and `uv run --with pytest pytest test_install.py`
Expected: full suite PASS (sanity check the repo is green before finishing).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with install + usage"
```

---

## Final verification

- [ ] **Run the entire suite**

Run: `uv run --with pyyaml --with pytest pytest -v`
Expected: every test in `test_pusher.py` and `test_install.py` passes.

- [ ] **Manual smoke test (optional, needs Docker + a reachable registry)**

```bash
cd /tmp && mkdir dip-smoke && cd dip-smoke
printf 'FROM alpine:3\n' > Dockerfile
# first run bootstraps VERSION.txt; point config at a registry you can push to
dip
```
Expected: prompts for image name + version, shows the four refs, builds, pushes, writes `VERSION.txt`.

---

## Self-Review (completed by plan author)

- **Spec coverage:** language/uv (Tasks 1–11), Approach-A single file (all), generic CWD operation (Task 9 `Path.cwd()`), home-dir XDG config (Task 5), shebang/symlink invocation + install.sh (Tasks 12–13), semver bump levels (Task 2), four rolling tags (Task 3), assume-logged-in (no auth code — out of scope honored), write-back only after push (Tasks 9/11), confirmation step (Task 8/9), bootstrap on missing VERSION.txt with default 0.1.0 and no-bump first run (Tasks 8/10), uv-required + docker-warn preflight (Tasks 12/13), error handling (Task 9), unit + integration tests + installer tests (throughout). README added (Task 14). All spec sections map to tasks.
- **Placeholder scan:** the only intentional placeholder is the `test_install_is_idempotent` stub in Task 13, explicitly flagged and given its corrected form in the same task (Step 3).
- **Type consistency:** `Version` NamedTuple, `parse_version`/`bump`/`tag_list`/`image_refs`/`read_version`/`load_registry`/`config_path`/`write_version`/`_run`/`build_image`/`tag_image`/`push_image`/`prompt_bump_level`/`bootstrap_version`/`confirm`/`main` signatures are consistent across the tasks that define and call them. Tag ordering (`[X.Y.Z, X.Y, X, latest]`) is consistent between Task 3 and the `main` integration assertions in Tasks 9–11.
```
