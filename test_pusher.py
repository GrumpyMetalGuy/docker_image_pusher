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
