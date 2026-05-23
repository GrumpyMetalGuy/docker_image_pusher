import subprocess
from pathlib import Path

import pytest

import pusher
from pusher import Version, parse_version


def test_parse_version_valid():
    assert parse_version("1.7.3") == Version(1, 7, 3)


def test_parse_version_str_roundtrip():
    assert str(parse_version("10.0.42")) == "10.0.42"


def test_parse_version_strips_whitespace():
    assert parse_version("  2.3.4  ") == Version(2, 3, 4)


@pytest.mark.parametrize(
    "bad", ["1.2", "1.2.3.4", "1.2.x", "abc", "", "1..3", "-1.0.0"]
)
def test_parse_version_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


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


from pusher import registry_login_host


def test_registry_login_host_private_registry_with_namespace():
    assert registry_login_host("registry.example.com/org") == "registry.example.com"


def test_registry_login_host_host_only():
    assert registry_login_host("registry.example.com") == "registry.example.com"


def test_registry_login_host_localhost_with_port():
    assert registry_login_host("localhost:5000") == "localhost:5000"


def test_registry_login_host_docker_hub_shorthand():
    # A bare first component (no dot/colon) is a Docker Hub namespace, not a host.
    assert registry_login_host("myuser") == "docker.io"


def test_registry_login_host_docker_io():
    assert registry_login_host("docker.io/library") == "docker.io"


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


def test_read_version_skips_comment_lines(tmp_path):
    f = tmp_path / "VERSION.txt"
    f.write_text(
        "# Created and managed by DIP (Docker Image Pusher).\n"
        "# https://github.com/GrumpyMetalGuy/docker_image_pusher\n"
        "my-image\n"
        "1.7.3\n"
    )
    name, version = read_version(f)
    assert name == "my-image"
    assert version == Version(1, 7, 3)


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


def test_load_registry_empty_string_value(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text('registry: ""\n')
    with pytest.raises(ValueError):
        load_registry(f)


def test_load_registry_whitespace_only_value(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text('registry: "   "\n')
    with pytest.raises(ValueError):
        load_registry(f)


from pusher import VERSION_FILE_HEADER, write_version


def test_write_version_roundtrips(tmp_path):
    f = tmp_path / "VERSION.txt"
    write_version(f, "my-image", Version(2, 0, 0))
    assert f.read_text() == f"{VERSION_FILE_HEADER}my-image\n2.0.0\n"
    # round-trips back through read_version
    name, version = read_version(f)
    assert name == "my-image"
    assert version == Version(2, 0, 0)


def test_write_version_includes_repo_reference(tmp_path):
    f = tmp_path / "VERSION.txt"
    write_version(f, "my-image", Version(1, 0, 0))
    text = f.read_text()
    assert text.startswith("#")
    assert "github.com/GrumpyMetalGuy/docker_image_pusher" in text


def test_write_version_creates_missing_file(tmp_path):
    f = tmp_path / "VERSION.txt"
    assert not f.exists()
    write_version(f, "fresh", Version(0, 1, 0))
    assert f.exists()
    assert f.read_text() == f"{VERSION_FILE_HEADER}fresh\n0.1.0\n"


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


from pusher import VersionCandidate, bootstrap_version, confirm, prompt_new_version


def scripted(answers):
    """Return an `ask`-compatible callable that yields the given answers in order."""
    it = iter(answers)

    def ask(_prompt):
        return next(it)

    return ask


def test_prompt_new_version_accepts_words():
    assert prompt_new_version(
        "app", Version(1, 2, 3), [], ask=scripted(["minor"])
    ) == Version(1, 3, 0)


def test_prompt_new_version_is_case_insensitive():
    assert prompt_new_version(
        "app", Version(1, 2, 3), [], ask=scripted(["REVISION"])
    ) == Version(1, 2, 4)


def test_prompt_new_version_accepts_numbers():
    def pick(n):
        return prompt_new_version("app", Version(1, 2, 3), [], ask=scripted([n]))

    assert pick("1") == Version(2, 0, 0)
    assert pick("2") == Version(1, 3, 0)
    assert pick("3") == Version(1, 2, 4)


def test_prompt_new_version_empty_uses_revision_default():
    assert prompt_new_version(
        "app", Version(1, 2, 3), [], ask=scripted([""])
    ) == Version(1, 2, 4)


def test_prompt_new_version_reprompts_on_invalid():
    assert prompt_new_version(
        "app", Version(1, 2, 3), [], ask=scripted(["patch", "9", "major"])
    ) == Version(2, 0, 0)


def test_prompt_new_version_shows_image_name_header(capsys):
    prompt_new_version("my-image", Version(1, 2, 3), [], ask=scripted([""]))
    out = capsys.readouterr().out
    assert "my-image" in out
    assert "1.2.3" in out


def test_prompt_new_version_external_candidate_returns_its_version():
    cands = [VersionCandidate("package.json", Version(1, 5, 0), "1.5.0", "app")]
    # options 1-3 are bump levels, 4 is the detected candidate
    assert prompt_new_version(
        "app", Version(1, 2, 3), cands, ask=scripted(["4"])
    ) == Version(1, 5, 0)


def test_prompt_new_version_multiple_candidates():
    cands = [
        VersionCandidate("package.json", Version(1, 5, 0), "1.5.0", "app"),
        VersionCandidate("Cargo.toml", Version(2, 0, 0), "2.0.0", "app"),
    ]
    assert prompt_new_version(
        "app", Version(1, 2, 3), cands, ask=scripted(["5"])
    ) == Version(2, 0, 0)


def test_prompt_new_version_annotates_same_as_current(capsys):
    cands = [VersionCandidate("Cargo.toml", Version(1, 2, 3), "1.2.3", "app")]
    prompt_new_version("app", Version(1, 2, 3), cands, ask=scripted([""]))
    assert "same as current" in capsys.readouterr().out


def test_prompt_new_version_annotates_older_than_current(capsys):
    cands = [VersionCandidate("Cargo.toml", Version(1, 0, 0), "1.0.0", "app")]
    prompt_new_version("app", Version(1, 2, 3), cands, ask=scripted([""]))
    assert "older than current" in capsys.readouterr().out


def test_prompt_new_version_newer_candidate_has_no_relation_annotation(capsys):
    cands = [VersionCandidate("Cargo.toml", Version(9, 0, 0), "9.0.0", "app")]
    prompt_new_version("app", Version(1, 2, 3), cands, ask=scripted([""]))
    out = capsys.readouterr().out
    assert "same as current" not in out
    assert "older than current" not in out


def test_prompt_new_version_shows_coerced_raw(capsys):
    cands = [VersionCandidate("composer.json", Version(1, 2, 0), "1.2", "app")]
    prompt_new_version("app", Version(1, 2, 3), cands, ask=scripted([""]))
    assert 'from "1.2"' in capsys.readouterr().out


def test_bootstrap_version_uses_default(tmp_path):
    name, version = bootstrap_version(tmp_path, ask=scripted(["my-image", ""]))
    assert name == "my-image"
    assert version == Version(0, 1, 0)


def test_bootstrap_version_custom_value(tmp_path):
    name, version = bootstrap_version(tmp_path, ask=scripted(["my-image", "2.3.4"]))
    assert version == Version(2, 3, 4)


def test_bootstrap_version_reprompts_empty_name_and_bad_version(tmp_path):
    name, version = bootstrap_version(
        tmp_path, ask=scripted(["", "app", "x.y.z", "1.0.0"])
    )
    assert name == "app"
    assert version == Version(1, 0, 0)


def test_bootstrap_version_uses_detected_candidate(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name": "@acme/widget", "version": "1.2.3"}'
    )
    # name prompt accepts default (empty), version picker accepts default (empty)
    name, version = bootstrap_version(tmp_path, ask=scripted(["", ""]))
    assert name == "widget"
    assert version == Version(1, 2, 3)


def test_bootstrap_version_detected_name_can_be_overridden(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "widget", "version": "1.2.3"}')
    name, version = bootstrap_version(tmp_path, ask=scripted(["custom", ""]))
    assert name == "custom"
    assert version == Version(1, 2, 3)


def test_bootstrap_version_manual_version_via_picker(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "widget", "version": "1.2.3"}')
    # name default, picker option 2 = "enter a different version", then type it
    name, version = bootstrap_version(tmp_path, ask=scripted(["", "2", "5.6.7"]))
    assert name == "widget"
    assert version == Version(5, 6, 7)


def test_confirm_yes():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted(["y"])) is True


def test_confirm_accepts_long_form_yes():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted(["yes"])) is True


def test_confirm_no_default():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted([""])) is False


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
    assert pusher_mod.main(ask=scripted(["revision", "y"])) == 0

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
    assert (proj / "VERSION.txt").read_text() == f"{VERSION_FILE_HEADER}app\n1.7.3\n"


def test_main_missing_dockerfile_errors_before_docker(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))

    assert pusher_mod.main(ask=scripted([])) == 1
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

    assert pusher_mod.main(ask=scripted([])) == 1
    assert calls == []


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
    assert pusher_mod.main(ask=scripted(["newapp", "", "y"])) == 0

    base = "reg.example.com/org/newapp"
    # entered version used as-is (no bump) -> 0.1.0 tags
    assert calls[0] == ["docker", "build", "-t", f"{base}:0.1.0", "."]
    assert ["docker", "push", f"{base}:0.1.0"] in calls
    assert ["docker", "push", f"{base}:latest"] in calls
    assert (proj / "VERSION.txt").read_text() == f"{VERSION_FILE_HEADER}newapp\n0.1.0\n"


def test_main_bump_picks_external_version(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.2.3\n")
    (proj / "package.json").write_text('{"name": "app", "version": "1.5.0"}')
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))

    # menu: 1-3 are bump levels, 4 = package.json (1.5.0); then confirm
    assert pusher_mod.main(ask=scripted(["4", "y"])) == 0

    base = "reg.example.com/org/app"
    assert calls[0] == ["docker", "build", "-t", f"{base}:1.5.0", "."]
    assert (proj / "VERSION.txt").read_text() == f"{VERSION_FILE_HEADER}app\n1.5.0\n"


def test_main_bootstrap_uses_detected_version(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "package.json").write_text('{"name": "acme", "version": "1.2.3"}')
    # NOTE: no VERSION.txt
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))

    # name default (empty), detected-version default (empty), confirm = y
    assert pusher_mod.main(ask=scripted(["", "", "y"])) == 0

    base = "reg.example.com/org/acme"
    assert calls[0] == ["docker", "build", "-t", f"{base}:1.2.3", "."]
    assert (proj / "VERSION.txt").read_text() == f"{VERSION_FILE_HEADER}acme\n1.2.3\n"


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
    assert pusher_mod.main(ask=scripted(["minor", "n"])) == 0
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

    assert pusher_mod.main(ask=scripted(["revision", "y"])) == 1
    assert (proj / "VERSION.txt").read_text() == "app\n1.0.0\n"  # NOT bumped


def test_main_push_failure_prints_login_hint(monkeypatch, tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path, registry="registry.example.com/org")

    def fake_run(cmd):
        if cmd[:2] == ["docker", "push"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pusher_mod, "_run", fake_run)

    assert pusher_mod.main(ask=scripted(["revision", "y"])) == 1
    err = capsys.readouterr().err
    assert "push" in err  # names the failing step
    assert "docker login registry.example.com" in err  # actionable hint with host


def test_main_build_failure_has_no_login_hint(monkeypatch, tmp_path, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    def fake_run(cmd):
        if cmd[:2] == ["docker", "build"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pusher_mod, "_run", fake_run)

    assert pusher_mod.main(ask=scripted(["revision", "y"])) == 1
    err = capsys.readouterr().err
    assert "build" in err  # names the failing step
    assert "docker login" not in err  # auth hint is push-only


def test_main_aborts_cleanly_on_interrupt(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    calls = []
    monkeypatch.setattr(pusher_mod, "_run", lambda cmd: calls.append(cmd))

    def interrupt(_prompt):
        raise EOFError

    assert pusher_mod.main(ask=interrupt) == 130
    assert calls == []  # nothing built or pushed
    assert (proj / "VERSION.txt").read_text() == "app\n1.0.0\n"  # unchanged


def test_main_build_failure_leaves_version_unchanged(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "Dockerfile").write_text("FROM scratch\n")
    (proj / "VERSION.txt").write_text("app\n1.0.0\n")
    monkeypatch.chdir(proj)
    _setup_config(monkeypatch, tmp_path)

    def fake_run(cmd):
        if cmd[:2] == ["docker", "build"]:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(pusher_mod, "_run", fake_run)

    assert pusher_mod.main(ask=scripted(["revision", "y"])) == 1
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

    assert pusher_mod.main(ask=scripted(["newapp", "0.1.0", "y"])) == 1
    assert not (proj / "VERSION.txt").exists()  # no half-written file


from pusher import coerce_version, normalize_image_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.2.3", Version(1, 2, 3)),
        ("1.2", Version(1, 2, 0)),
        ("1", Version(1, 0, 0)),
        ("  1.2.3  ", Version(1, 2, 3)),
        ("v1.4.0", Version(1, 4, 0)),
        ("1.2.3-beta", Version(1, 2, 3)),
        ("1.2.3-beta.1", Version(1, 2, 3)),
        ("1.0.0-SNAPSHOT", Version(1, 0, 0)),
        ("1.2.3+build5", Version(1, 2, 3)),
        ("2.0.0.4", Version(2, 0, 0)),
        ("1.2.3a1", Version(1, 2, 3)),
        ("1.2.3.dev0", Version(1, 2, 3)),
    ],
)
def test_coerce_version_coerces(raw, expected):
    assert coerce_version(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "latest", "abc", "v", "-1.0.0"])
def test_coerce_version_returns_none_for_unparseable(raw):
    assert coerce_version(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my-app", "my-app"),
        ("  my-app  ", "my-app"),
        ("@scope/pkg", "pkg"),
        ("vendor/pkg", "pkg"),
        ("vendor/sub/pkg", "pkg"),
    ],
)
def test_normalize_image_name(raw, expected):
    assert normalize_image_name(raw) == expected


from pusher import (
    detect_cargo,
    detect_composer_json,
    detect_csproj,
    detect_package_json,
    detect_pom,
    detect_pyproject,
)


def test_detect_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"name": "@acme/widget", "version": "1.2.3"}'
    )
    [c] = detect_package_json(tmp_path)
    assert c.source == "package.json"
    assert c.version == Version(1, 2, 3)
    assert c.raw == "1.2.3"
    assert c.name == "widget"


def test_detect_package_json_absent(tmp_path):
    assert detect_package_json(tmp_path) == []


def test_detect_package_json_malformed_is_skipped(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    assert detect_package_json(tmp_path) == []


def test_detect_package_json_no_version(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "widget"}')
    assert detect_package_json(tmp_path) == []


def test_detect_composer_json(tmp_path):
    (tmp_path / "composer.json").write_text('{"name": "vendor/pkg", "version": "2.0"}')
    [c] = detect_composer_json(tmp_path)
    assert c.source == "composer.json"
    assert c.version == Version(2, 0, 0)
    assert c.name == "pkg"


def test_detect_pyproject_pep621(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "my-tool"\nversion = "3.4.5"\n'
    )
    [c] = detect_pyproject(tmp_path)
    assert c.source == "pyproject.toml"
    assert c.version == Version(3, 4, 5)
    assert c.name == "my-tool"


def test_detect_pyproject_poetry(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "poet"\nversion = "1.0.0"\n'
    )
    [c] = detect_pyproject(tmp_path)
    assert c.version == Version(1, 0, 0)
    assert c.name == "poet"


def test_detect_pyproject_dynamic_version_skipped(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndynamic = ["version"]\n'
    )
    assert detect_pyproject(tmp_path) == []


def test_detect_pyproject_malformed_is_skipped(tmp_path):
    (tmp_path / "pyproject.toml").write_text("this is = = not toml")
    assert detect_pyproject(tmp_path) == []


def test_detect_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "crate-thing"\nversion = "0.9.1"\n'
    )
    [c] = detect_cargo(tmp_path)
    assert c.version == Version(0, 9, 1)
    assert c.name == "crate-thing"


def test_detect_csproj_with_version_and_packageid(tmp_path):
    (tmp_path / "App.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <PropertyGroup>\n"
        "    <Version>2.1.0</Version>\n"
        "    <PackageId>MyApp</PackageId>\n"
        "  </PropertyGroup>\n"
        "</Project>\n"
    )
    [c] = detect_csproj(tmp_path)
    assert c.source == "App.csproj"
    assert c.version == Version(2, 1, 0)
    assert c.name == "MyApp"


def test_detect_csproj_name_falls_back_to_filename(tmp_path):
    (tmp_path / "Service.csproj").write_text(
        "<Project><PropertyGroup><Version>1.0.0</Version></PropertyGroup></Project>"
    )
    [c] = detect_csproj(tmp_path)
    assert c.name == "Service"


def test_detect_csproj_multiple_files_sorted(tmp_path):
    (tmp_path / "B.csproj").write_text(
        "<Project><PropertyGroup><Version>2.0.0</Version></PropertyGroup></Project>"
    )
    (tmp_path / "A.csproj").write_text(
        "<Project><PropertyGroup><Version>1.0.0</Version></PropertyGroup></Project>"
    )
    sources = [c.source for c in detect_csproj(tmp_path)]
    assert sources == ["A.csproj", "B.csproj"]


def test_detect_pom_with_namespace(tmp_path):
    (tmp_path / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <artifactId>my-service</artifactId>\n"
        "  <version>4.5.6</version>\n"
        "  <dependencies>\n"
        "    <dependency><artifactId>dep</artifactId><version>9.9.9</version></dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    [c] = detect_pom(tmp_path)
    assert c.source == "pom.xml"
    assert c.version == Version(4, 5, 6)  # project version, not the dependency's
    assert c.name == "my-service"


def test_detect_pom_inherited_version_skipped(tmp_path):
    (tmp_path / "pom.xml").write_text(
        "<project>\n"
        "  <parent><version>1.0.0</version></parent>\n"
        "  <artifactId>child</artifactId>\n"
        "</project>\n"
    )
    assert detect_pom(tmp_path) == []  # no project-level version of its own


from pusher import detect_version_candidates


def test_detect_version_candidates_empty_dir(tmp_path):
    assert detect_version_candidates(tmp_path) == []


def test_detect_version_candidates_orders_by_priority(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "c"\nversion = "3.0.0"\n')
    (tmp_path / "package.json").write_text('{"name": "n", "version": "1.0.0"}')
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "2.0.0"\n'
    )
    (tmp_path / "pom.xml").write_text(
        "<project><artifactId>m</artifactId><version>4.0.0</version></project>"
    )
    sources = [c.source for c in detect_version_candidates(tmp_path)]
    assert sources == ["package.json", "pyproject.toml", "Cargo.toml", "pom.xml"]


from pusher import prompt_version_candidate

_CANDS = [
    VersionCandidate("package.json", Version(1, 2, 3), "1.2.3", "widget"),
    VersionCandidate("pyproject.toml", Version(1, 2, 0), "1.2", "widget"),
]


def test_prompt_version_candidate_picks_by_number():
    assert prompt_version_candidate(_CANDS, ask=scripted(["2"])) is _CANDS[1]


def test_prompt_version_candidate_empty_uses_first_default():
    assert prompt_version_candidate(_CANDS, ask=scripted([""])) is _CANDS[0]


def test_prompt_version_candidate_manual_option_returns_none():
    # the option after the candidates ("enter a different version")
    assert prompt_version_candidate(_CANDS, ask=scripted(["3"])) is None


def test_prompt_version_candidate_reprompts_on_invalid():
    assert prompt_version_candidate(_CANDS, ask=scripted(["x", "9", "1"])) is _CANDS[0]


def test_prompt_version_candidate_shows_source_and_coerced_raw(capsys):
    prompt_version_candidate(_CANDS, ask=scripted([""]))
    out = capsys.readouterr().out
    assert "package.json" in out
    assert "pyproject.toml" in out
    assert "1.2" in out  # the coerced raw value is surfaced
