"""Tests for SecretsManagerParameter in ssm_cache/parameters.py."""

from ssm_cache.exceptions import InvalidParameterError
from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SecretsManagerParameter

from . import TestBase


class TestSecretsManagerParameter(TestBase):
    """SecretsManagerParameter creation, prefix handling, and group support."""

    def setUp(self):
        super().setUp()
        self._create_secrets(
            [
                "my_secret",
                "my_secret_1",
                "my_secret_2",
                "my_secret_3",
            ]
        )

    def test_creation_defaults(self):
        param = SecretsManagerParameter("my_secret")
        self.assertTrue(param._with_decryption)  # pylint: disable=protected-access
        self.assertIsNone(param._max_age)  # pylint: disable=protected-access
        self.assertIsNone(param._last_refresh_time)  # pylint: disable=protected-access
        self.assertTrue(param._name.startswith(SecretsManagerParameter.PREFIX))  # pylint: disable=protected-access

    def test_creation_requires_name(self):
        with self.assertRaises(TypeError):
            SecretsManagerParameter()  # pylint: disable=no-value-for-parameter
        with self.assertRaises(ValueError):
            SecretsManagerParameter(None)

    def test_slash_prefix_rejected(self):
        """Names starting with '/' are ambiguous — raise instead of silently mangling."""
        with self.assertRaises(InvalidParameterError):
            SecretsManagerParameter("/my_secret")

    def test_invalid_secret_raises(self):
        with self.assertRaises(InvalidParameterError):
            _ = SecretsManagerParameter("does_not_exist").value

    def test_invalid_secret_in_group_raises(self):
        group = SSMParameterGroup()
        group.secret("my_secret_1")
        group.secret("does_not_exist")
        with self.assertRaises(InvalidParameterError):
            group.refresh()

    def test_duplicate_secret_in_group_deduped(self):
        group = SSMParameterGroup()
        group.secret("my_secret_1")
        group.secret("my_secret_1")
        self.assertEqual(1, len(group))

    def test_group_secret_helper(self):
        group = SSMParameterGroup()
        with self.assertRaises(TypeError):
            group.secret()  # pylint: disable=no-value-for-parameter
        with self.assertRaises(InvalidParameterError):
            group.secret("/my_secret")
