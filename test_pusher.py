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
