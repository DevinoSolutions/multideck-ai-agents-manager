from multideck.titles import generate_titles, get_leaf_name


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
