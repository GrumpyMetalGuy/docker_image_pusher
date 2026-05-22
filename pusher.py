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


def main() -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
