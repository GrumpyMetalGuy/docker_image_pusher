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


def read_version(path: Path) -> tuple[str, Version]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
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
    path.write_text(f"{name}\n{version}\n")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def build_image(ref: str, context: str = ".") -> None:
    _run(["docker", "build", "-t", ref, context])


def tag_image(src: str, dst: str) -> None:
    _run(["docker", "tag", src, dst])


def push_image(ref: str) -> None:
    _run(["docker", "push", ref])


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
            new_version = bump(current, prompt_bump_level(ask=ask))
        else:
            name, new_version = bootstrap_version(ask=ask)

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
        print(f"error: docker command failed (exit {exc.returncode})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
