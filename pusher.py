#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""dip — build a project's Docker image and push rolling tags to a registry."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

import yaml

VERSION_FILE_HEADER = (
    "# Created and managed by DIP (Docker Image Pusher).\n"
    "# https://github.com/GrumpyMetalGuy/docker_image_pusher\n"
)


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


_LEADING_DIGITS = re.compile(r"^(\d+)")


def coerce_version(raw: str) -> Version | None:
    """Best-effort parse of a version string into MAJOR.MINOR.PATCH, or None.

    Drops a leading 'v' and any pre-release/build suffix, takes the leading
    digits of each dotted component (up to three), and pads short versions.
    """
    s = raw.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    s = s.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for component in s.split("."):
        m = _LEADING_DIGITS.match(component)
        if not m:
            break
        parts.append(int(m.group(1)))
        if len(parts) == 3:
            break
    if not parts:
        return None
    while len(parts) < 3:
        parts.append(0)
    return Version(parts[0], parts[1], parts[2])


def normalize_image_name(raw: str) -> str:
    """Reduce a package name like '@scope/pkg' or 'vendor/pkg' to 'pkg'."""
    return raw.strip().lstrip("@").rsplit("/", 1)[-1]


class VersionCandidate(NamedTuple):
    source: str  # the file the version came from, e.g. "package.json"
    version: Version  # coerced MAJOR.MINOR.PATCH
    raw: str  # the original version string before coercion
    name: str | None  # inferred image name, if the file provided one


def _candidate(source: str, raw_version, raw_name) -> VersionCandidate | None:
    """Build a candidate from raw values, or None if the version won't coerce."""
    if not isinstance(raw_version, str):
        return None
    version = coerce_version(raw_version)
    if version is None:
        return None
    name = (
        normalize_image_name(raw_name)
        if isinstance(raw_name, str) and raw_name
        else None
    )
    return VersionCandidate(source, version, raw_version.strip(), name)


def _detect_json(path: Path, source: str) -> list[VersionCandidate]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    candidate = _candidate(source, data.get("version"), data.get("name"))
    return [candidate] if candidate else []


def detect_package_json(root: Path) -> list[VersionCandidate]:
    return _detect_json(root / "package.json", "package.json")


def detect_composer_json(root: Path) -> list[VersionCandidate]:
    return _detect_json(root / "composer.json", "composer.json")


def _load_toml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return None


def detect_pyproject(root: Path) -> list[VersionCandidate]:
    data = _load_toml(root / "pyproject.toml")
    if data is None:
        return []
    project = data.get("project", {})
    if isinstance(project, dict) and "version" not in (project.get("dynamic") or []):
        candidate = _candidate(
            "pyproject.toml", project.get("version"), project.get("name")
        )
        if candidate:
            return [candidate]
    poetry = (
        data.get("tool", {}).get("poetry", {})
        if isinstance(data.get("tool"), dict)
        else {}
    )
    candidate = _candidate("pyproject.toml", poetry.get("version"), poetry.get("name"))
    return [candidate] if candidate else []


def detect_cargo(root: Path) -> list[VersionCandidate]:
    data = _load_toml(root / "Cargo.toml")
    if data is None:
        return []
    package = data.get("package", {})
    if not isinstance(package, dict):
        return []
    candidate = _candidate("Cargo.toml", package.get("version"), package.get("name"))
    return [candidate] if candidate else []


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag, e.g. '{ns}version' -> 'version'."""
    return tag.rsplit("}", 1)[-1]


def _first_text(root: ET.Element, *local_names: str) -> str | None:
    """Return the text of the first descendant matching any of local_names."""
    for name in local_names:
        for elem in root.iter():
            if _local(elem.tag) == name and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def detect_csproj(root: Path) -> list[VersionCandidate]:
    candidates: list[VersionCandidate] = []
    for path in sorted(root.glob("*.csproj")):
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError):
            continue
        elem = tree.getroot()
        raw_version = _first_text(elem, "Version", "VersionPrefix")
        if raw_version is None:
            continue
        raw_name = _first_text(elem, "PackageId", "AssemblyName") or path.stem
        candidate = _candidate(path.name, raw_version, raw_name)
        if candidate:
            candidates.append(candidate)
    return candidates


def detect_pom(root: Path) -> list[VersionCandidate]:
    path = root / "pom.xml"
    if not path.exists():
        return []
    try:
        project = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    # Only direct children of <project>: skips <parent>/<dependencies> versions.
    raw_version = next(
        (
            c.text.strip()
            for c in project
            if _local(c.tag) == "version" and c.text and c.text.strip()
        ),
        None,
    )
    if raw_version is None:
        return []
    raw_name = next(
        (
            c.text.strip()
            for c in project
            if _local(c.tag) == "artifactId" and c.text and c.text.strip()
        ),
        None,
    )
    candidate = _candidate("pom.xml", raw_version, raw_name)
    return [candidate] if candidate else []


_DETECTORS = (
    detect_package_json,
    detect_pyproject,
    detect_cargo,
    detect_composer_json,
    detect_csproj,
    detect_pom,
)


def detect_version_candidates(root: Path) -> list[VersionCandidate]:
    """Scan the project root for versions in well-known files, in priority order."""
    candidates: list[VersionCandidate] = []
    for detector in _DETECTORS:
        candidates.extend(detector(root))
    return candidates


def bump(version: Version, level: str) -> Version:
    if level == "major":
        return Version(version.major + 1, 0, 0)
    if level == "minor":
        return Version(version.major, version.minor + 1, 0)
    if level == "revision":
        return Version(version.major, version.minor, version.patch + 1)
    raise ValueError(f"Unknown bump level: {level!r}")


def tag_list(version: Version) -> list[str]:
    return [
        str(version),
        f"{version.major}.{version.minor}",
        f"{version.major}",
        "latest",
    ]


def image_refs(registry: str, name: str, tags: list[str]) -> list[str]:
    return [f"{registry}/{name}:{tag}" for tag in tags]


def registry_login_host(registry: str) -> str:
    """The host to `docker login` for a given registry prefix.

    Mirrors docker's reference parsing: the first path component is a registry
    host only if it contains a '.' or ':' (or is 'localhost'); otherwise it is a
    Docker Hub namespace, which authenticates against docker.io.
    """
    first = registry.split("/", 1)[0]
    if "." in first or ":" in first or first == "localhost":
        return first
    return "docker.io"


def read_version(path: Path) -> tuple[str, Version]:
    lines = [
        stripped
        for line in path.read_text().splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    if len(lines) < 2:
        raise ValueError(
            f"{path} must have the image name on line 1 and a semver on line 2"
        )
    return lines[0], parse_version(lines[1])


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


def write_version(path: Path, name: str, version: Version) -> None:
    path.write_text(f"{VERSION_FILE_HEADER}{name}\n{version}\n")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def build_image(ref: str, context: str = ".") -> None:
    _run(["docker", "build", "-t", ref, context])


def tag_image(src: str, dst: str) -> None:
    _run(["docker", "tag", src, dst])


def push_image(ref: str) -> None:
    _run(["docker", "push", ref])


BUMP_LEVELS = ("major", "minor", "revision")


def prompt_bump_level(name: str, current: Version, ask=input) -> str:
    default = "revision"
    print(f"Bumping '{name}' (current version {current})")
    print("Select bump level:")
    for i, level in enumerate(BUMP_LEVELS, start=1):
        marker = "  [default]" if level == default else ""
        print(f"  {i}) {level:<9}{current} -> {bump(current, level)}{marker}")
    choices = {str(i): level for i, level in enumerate(BUMP_LEVELS, start=1)}
    choices.update({level: level for level in BUMP_LEVELS})
    while True:
        answer = ask(f"Choice [{BUMP_LEVELS.index(default) + 1}]: ").strip().lower()
        if not answer:
            return default
        if answer in choices:
            return choices[answer]
        print(f"Invalid choice: {answer!r}. Enter 1, 2, or 3.")


def prompt_version_candidate(
    candidates: list[VersionCandidate], ask=input
) -> VersionCandidate | None:
    """Let the user pick a detected version; None means 'enter manually'."""
    print("Detected a version from your project:")
    width = max(len(c.source) for c in candidates)
    for i, c in enumerate(candidates, start=1):
        annot = f'  (from "{c.raw}")' if c.raw != str(c.version) else ""
        default = "  [default]" if i == 1 else ""
        print(f"  {i}) {c.source:<{width}}  {c.version}{annot}{default}")
    manual = len(candidates) + 1
    print(f"  {manual}) Enter a different version")
    valid: dict[str, VersionCandidate | None] = {
        str(i): c for i, c in enumerate(candidates, start=1)
    }
    valid[str(manual)] = None
    while True:
        answer = ask("Choice [1]: ").strip()
        if not answer:
            return candidates[0]
        if answer in valid:
            return valid[answer]
        print(f"Invalid choice: {answer!r}. Enter a number from 1 to {manual}.")


def _prompt_image_name(default: str | None, ask=input) -> str:
    if default:
        name = ask(f"Image name [{default}]: ").strip()
        return name or default
    name = ""
    while not name:
        name = ask("Image name: ").strip()
        if not name:
            print("Image name cannot be empty.")
    return name


def _prompt_manual_version(ask=input) -> Version:
    while True:
        raw = ask(
            "Starting version — the version this NEW image will be built and pushed as [0.1.0]: "
        ).strip()
        try:
            return parse_version(raw or "0.1.0")
        except ValueError as exc:
            print(exc)


def bootstrap_version(root: Path, ask=input) -> tuple[str, Version]:
    print("No VERSION.txt found in this directory — let's create one.")
    candidates = detect_version_candidates(root)
    name_default = next((c.name for c in candidates if c.name), None)
    name = _prompt_image_name(name_default, ask=ask)
    chosen = prompt_version_candidate(candidates, ask=ask) if candidates else None
    version = chosen.version if chosen else _prompt_manual_version(ask=ask)
    return name, version


def confirm(refs: list[str], context: Path, ask=input) -> bool:
    print(f"\nAbout to build {context} and push:")
    for ref in refs:
        print(f"  {ref}")
    return ask("Proceed? [y/N]: ").strip().lower() in ("y", "yes")


def main(ask=input) -> int:
    cwd = Path.cwd()
    version_file = cwd / "VERSION.txt"
    dockerfile = cwd / "Dockerfile"
    try:
        if not dockerfile.exists():
            raise FileNotFoundError(f"No Dockerfile found in {cwd}")
        registry = load_registry(config_path())

        if version_file.exists():
            name, current = read_version(version_file)
            new_version = bump(current, prompt_bump_level(name, current, ask=ask))
        else:
            name, new_version = bootstrap_version(cwd, ask=ask)

        tags = tag_list(new_version)
        refs = image_refs(registry, name, tags)
        if not confirm(refs, cwd, ask=ask):
            print("Aborted.")
            return 0

        build_image(refs[0], ".")
        for dst in refs[1:]:
            tag_image(refs[0], dst)
        for ref in refs:
            push_image(ref)

        write_version(version_file, name, new_version)
        print(f"Pushed {name} {new_version}  ({', '.join(tags)})")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        action = exc.cmd[1] if len(exc.cmd) > 1 else "command"
        print(
            f"error: 'docker {action}' failed (exit {exc.returncode}); "
            "see the docker output above.",
            file=sys.stderr,
        )
        if action == "push":
            host = registry_login_host(registry)
            print(
                f"hint: if this is an authentication error, run "
                f"'docker login {host}' and try again.",
                file=sys.stderr,
            )
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
