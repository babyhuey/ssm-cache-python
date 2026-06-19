"""Tests for ssm_cache/groups.py — SSMParameterGroup, including hierarchy."""

from datetime import timedelta

from freezegun import freeze_time

from ssm_cache.exceptions import InvalidParameterError, InvalidPathError
from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SSMParameter
from ssm_cache.utils import utcnow

from . import TestBase

# pylint: disable=protected-access

# ---------------------------------------------------------------------------
# Basic group behaviour
# ---------------------------------------------------------------------------


class TestSSMParameterGroup(TestBase):
    """SSMParameterGroup creation, multi-param fetch, and expiry."""

    def setUp(self):
        super().setUp()
        self._create_params(["my_param", "my_param_1", "my_param_2", "my_param_3"])
        self._create_params(["my_params_list"], parameter_type="StringList")

    def test_creation_defaults(self):
        group = SSMParameterGroup()
        param = group.parameter("my_param")
        self.assertIsNotNone(param)
        self.assertEqual(len(group), 1)

    def test_creation_requires_path_arg(self):
        with self.assertRaises(TypeError):
            SSMParameterGroup().parameter()  # pylint: disable=no-value-for-parameter

    def test_duplicate_name_deduped(self):
        group = SSMParameterGroup()
        _ = group.parameter("my_param_1")
        __ = group.parameter("my_param_1")
        self.assertEqual(1, len(group))

    def test_multi_param_fetch(self):
        group = SSMParameterGroup()
        p1 = group.parameter("my_param_1")
        p2 = group.parameter("my_param_2")
        p3 = group.parameter("my_param_3")
        for p in (p1, p2, p3):
            self.assertEqual(p.value, self.PARAM_VALUE)

    def test_string_list_in_group(self):
        group = SSMParameterGroup()
        group.parameter("my_param_1")
        lst = group.parameter("my_params_list")
        values = lst.value
        self.assertIsInstance(values, list)
        self.assertEqual(len(values), self.PARAM_LIST_COUNT)

    def test_invalid_parameter_in_group_raises(self):
        group = SSMParameterGroup()
        _ = group.parameter("my_param_1")
        __ = group.parameter("does_not_exist")
        with self.assertRaises(InvalidParameterError):
            group.refresh()

    def test_explicit_group_refresh(self):
        group = SSMParameterGroup()
        p1 = group.parameter("my_param_1")
        p2 = group.parameter("my_param_2")

        new_value = "new_value"
        self._create_params(["my_param_1", "my_param_2"], new_value)
        group.refresh()

        self.assertEqual(p1.value, new_value)
        self.assertEqual(p2.value, new_value)

    def test_refresh_via_param_refreshes_group(self):
        group = SSMParameterGroup()
        p1 = group.parameter("my_param_1")
        p2 = group.parameter("my_param_2")

        new_value = "new_value"
        self._create_params(["my_param_1", "my_param_2"], new_value)
        p1.refresh()  # should pull in p2 as well

        self.assertEqual(p1.value, new_value)
        self.assertEqual(p2.value, new_value)

    def test_expiry_propagates_to_params(self):
        group = SSMParameterGroup(max_age=300)
        p1 = group.parameter("my_param_1")
        p2 = group.parameter("my_param_2")
        p3 = group.parameter("my_param_3")

        group.refresh()
        group._last_refresh_time = utcnow() - timedelta(seconds=301)

        self.assertTrue(group._should_refresh())
        self.assertTrue(p1._should_refresh())
        self.assertTrue(p2._should_refresh())
        self.assertTrue(p3._should_refresh())

    def test_with_expiration(self):
        group = SSMParameterGroup(max_age=300)
        p = group.parameter("my_param")
        self.assertEqual(p.value, self.PARAM_VALUE)


# ---------------------------------------------------------------------------
# Hierarchical parameters
# ---------------------------------------------------------------------------


class TestSSMParameterGroupHierarchy(TestBase):
    """SSMParameterGroup.parameters() — path-prefix fetching and caching."""

    ROOT = "/Root"
    PATH_SIMPLE = "/Level1/Level2"
    PATH = f"{ROOT}{PATH_SIMPLE}"
    PATH_LIST_SIMPLE = "/LevelA/LevelB"
    PATH_LIST = f"{ROOT}{PATH_LIST_SIMPLE}"
    GROUP_SIZE = 20

    def setUp(self):
        super().setUp()
        self._create_params([f"{self.PATH}/my_param_{i}" for i in range(self.GROUP_SIZE)])
        self._create_params(
            [f"{self.PATH_LIST}/my_param_list_{i}" for i in range(self.GROUP_SIZE)],
            parameter_type="StringList",
        )

    def test_fetch_by_prefix(self):
        group = SSMParameterGroup()
        params = group.parameters(self.PATH)
        self.assertEqual(len(group), self.GROUP_SIZE)
        for p in params:
            self.assertEqual(p.value, self.PARAM_VALUE)
            self.assertIn(self.PATH, p.name)

    def test_cache_without_max_age_never_refreshes(self):
        group = SSMParameterGroup()
        group.parameters(self.PATH)
        self.assertFalse(group._should_refresh())

    def test_cache_with_max_age_not_expired(self):
        group = SSMParameterGroup(max_age=10)
        group.parameters(self.PATH)
        self.assertFalse(group._should_refresh())

    def test_cache_with_max_age_expired(self):
        group = SSMParameterGroup(max_age=10)
        group.parameters(self.PATH)
        with freeze_time(lambda: utcnow() + timedelta(seconds=10)):
            self.assertTrue(group._should_refresh())

    def test_cache_tracks_oldest_fetch(self):
        """Second parameters() call inside freeze_time anchors the expiry."""
        group = SSMParameterGroup(max_age=10)
        group.parameters(self.PATH)
        self.assertFalse(group._should_refresh())
        with freeze_time(lambda: utcnow() + timedelta(seconds=10)):
            group.parameters(self.PATH_LIST)
            self.assertTrue(group._should_refresh())

    def test_string_list_params(self):
        group = SSMParameterGroup()
        params = group.parameters(self.PATH_LIST)
        self.assertEqual(len(group), self.GROUP_SIZE)
        for p in params:
            self.assertIsInstance(p.value, list)
            for v in p.value:
                self.assertEqual(v, self.PARAM_VALUE)

    def test_root_prefix_fetches_all(self):
        group = SSMParameterGroup()
        params = group.parameters(self.ROOT)
        self.assertEqual(len(params), self.GROUP_SIZE * 2)

    def test_multiple_prefix_calls(self):
        group = SSMParameterGroup()
        p1 = group.parameters(self.PATH)
        p2 = group.parameters(self.PATH_LIST)
        self.assertEqual(len(p1), self.GROUP_SIZE)
        self.assertEqual(len(p2), self.GROUP_SIZE)
        self.assertEqual(len(group), self.GROUP_SIZE * 2)

    def test_overlapping_prefixes_deduped(self):
        group = SSMParameterGroup()
        group.parameters(self.PATH)
        all_params = group.parameters(self.ROOT)
        self.assertEqual(len(all_params), self.GROUP_SIZE * 2)
        self.assertEqual(len(group), self.GROUP_SIZE * 2)

    def test_base_path_prefix(self):
        group = SSMParameterGroup(base_path=self.ROOT)
        p1 = group.parameters(self.PATH_SIMPLE)
        p2 = group.parameters(self.PATH_LIST_SIMPLE)
        self.assertEqual(len(p1), self.GROUP_SIZE)
        self.assertEqual(len(p2), self.GROUP_SIZE)
        self.assertEqual(len(group), self.GROUP_SIZE * 2)
        for p in p1:
            self.assertTrue(p.name.startswith(self.PATH))
        for p in p2:
            self.assertTrue(p.name.startswith(self.PATH_LIST))

    def test_base_path_single_param(self):
        group = SSMParameterGroup(base_path=self.ROOT)
        param = group.parameter(f"{self.PATH_SIMPLE}/my_param_1")
        self.assertEqual(len(group), 1)
        self.assertTrue(param.name.startswith(self.PATH))
        self.assertEqual(param.value, self.PARAM_VALUE)

    def test_base_path_mixed(self):
        group = SSMParameterGroup(base_path=self.ROOT)
        param = group.parameter(f"{self.PATH_SIMPLE}/my_param_1")
        p1 = group.parameters(self.PATH_SIMPLE)
        p2 = group.parameters(self.PATH_LIST_SIMPLE)
        self.assertIsInstance(param, SSMParameter)
        self.assertEqual(len(p1), self.GROUP_SIZE)
        self.assertEqual(len(p2), self.GROUP_SIZE)
        self.assertEqual(len(group), self.GROUP_SIZE * 2)

    def test_base_path_complex(self):
        names = [
            "/PC/Foo/Bar",
            "/PC/Foo/Baz/1",
            "/PC/Foo/Baz/2",
            "/PC/Foo/Taz/1",
            "/PC/Foo/Taz/2",
        ]
        self._create_params(names)
        group = SSMParameterGroup(base_path="/PC/Foo")
        bar = group.parameter("/Bar")
        baz = group.parameters("/Baz")
        taz = group.parameters("/Taz")
        self.assertIsInstance(bar, SSMParameter)
        self.assertEqual(len(baz), 2)
        self.assertEqual(len(taz), 2)
        self.assertEqual(len(group), 5)

    def test_recursive_default(self):
        names = [
            "/PR/Foo/Baz/1",
            "/PR/Foo/Baz/2",
            "/PR/Foo/Baz/Taz/1",
            "/PR/Foo/Baz/Taz/2",
        ]
        self._create_params(names)
        group = SSMParameterGroup(base_path="/PR/Foo")
        self.assertEqual(len(group.parameters("/Baz")), 4)

    def test_non_recursive(self):
        names = [
            "/PNR/Foo/Baz/1",
            "/PNR/Foo/Baz/2",
            "/PNR/Foo/Baz/Taz/1",
            "/PNR/Foo/Baz/Taz/2",
        ]
        self._create_params(names)
        group = SSMParameterGroup(base_path="/PNR/Foo")
        baz = group.parameters("/Baz", recursive=False)
        taz = group.parameters("/Baz/Taz")
        self.assertEqual(len(baz), 2)
        self.assertEqual(len(taz), 2)
        self.assertEqual(len(group), 4)

    def test_invalid_base_path_raises(self):
        with self.assertRaises(InvalidPathError):
            SSMParameterGroup(base_path="no_leading_slash")

    def test_invalid_param_path_raises_when_base_set(self):
        group = SSMParameterGroup(base_path=self.ROOT)
        with self.assertRaises(InvalidPathError):
            group.parameter("no_leading_slash")
        with self.assertRaises(InvalidPathError):
            group.parameters("no_leading_slash")
