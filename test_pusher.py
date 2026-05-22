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


def test_bootstrap_version_uses_default():
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


def test_confirm_accepts_long_form_yes():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted(["yes"])) is True


def test_confirm_no_default():
    assert confirm(["reg/app:1.0.0"], Path("/proj"), ask=scripted([""])) is False


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
