import sys

import pytest

from multideck.titles import MD_TITLE_PREFIX, generate_titles, get_leaf_name


class TestGetLeafName:
    def test_unix_path(self):
        assert get_leaf_name("/home/user/code/api") == "api"

    def test_windows_path(self):
        assert get_leaf_name("C:\\Users\\user\\code\\api") == "api"

    def test_forward_slashes(self):
        assert get_leaf_name("internal/api") == "api"

    def test_trailing_slash(self):
        assert get_leaf_name("/home/user/api/") == "api"

    def test_simple_name(self):
        assert get_leaf_name("api") == "api"


class TestGenerateTitles:
    def test_no_windows_uses_title(self):
        titles = generate_titles(title="my-api", path="internal/api", windows=None)
        assert titles == ["my-api"]

    def test_no_windows_no_title_uses_leaf(self):
        titles = generate_titles(title=None, path="internal/api", windows=None)
        assert titles == ["api"]

    def test_windows_int_auto_titles(self):
        titles = generate_titles(title=None, path="internal/api", windows=3)
        assert titles == ["api", "api-2", "api-3"]

    def test_windows_int_with_title(self):
        titles = generate_titles(title="my-api", path="internal/api", windows=3)
        assert titles == ["my-api", "my-api-2", "my-api-3"]

    def test_windows_1_same_as_none(self):
        titles = generate_titles(title=None, path="internal/api", windows=1)
        assert titles == ["api"]

    def test_windows_string_array(self):
        titles = generate_titles(title=None, path="internal/api", windows=["feat", "bugs", "review"])
        assert titles == ["feat", "bugs", "review"]

    def test_windows_string_array_ignores_title(self):
        titles = generate_titles(title="ignored", path="internal/api", windows=["a", "b"])
        assert titles == ["a", "b"]


class TestMdTitlePrefixContract:
    """Producer (cli/attach.py) and consumer (hotkey.py) must agree on the
    md: title prefix, or Alt+V session recognition silently breaks for newly
    created sessions. Pinned here so a change to either side fails loudly.
    """

    def test_prefix_value(self):
        assert MD_TITLE_PREFIX == "md:"

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="hotkey is Windows-only (ImportError off-Windows)",
    )
    def test_hotkey_imports_same_object(self):
        from multideck import hotkey
        assert hotkey.MD_TITLE_PREFIX is MD_TITLE_PREFIX

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="hotkey is Windows-only (ImportError off-Windows)",
    )
    def test_producers_agree_with_consumer(self):
        from multideck.hotkey import MD_TITLE_PREFIX as consumer_prefix
        name = "my-project"
        assert f"md:{name}" == f"{consumer_prefix}{name}"
