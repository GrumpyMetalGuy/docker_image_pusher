import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent
COREUTILS = ["bash", "mkdir", "ln", "chmod", "pwd", "cat"]


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
