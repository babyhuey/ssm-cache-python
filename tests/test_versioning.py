"""Tests for SSMParameter versioning — uses placebo-recorded responses.

These tests do not extend TestBase because they use a pre-recorded placebo
session rather than a live moto mock; all boto3 calls are replayed from disk.

The parameter names used in each test must match the names baked into the
placebo JSON files (recorded against the original test method names).
"""

import os
import unittest
from unittest.mock import patch

import boto3
import placebo

from ssm_cache.exceptions import InvalidParameterError, InvalidVersionError
from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SSMParameter
from ssm_cache.refreshable import Refreshable

PLACEBO_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "placebo/versioning"))

# Map each test to the param name recorded in its placebo files.
# These names are fixed by the original recording session and must not change.
_PLACEBO_PARAM = {
    "test_update_increments_version": "test_update_versions",
    "test_pinned_version_not_overwritten_on_refresh": "test_select_versions",
    "test_nonexistent_version_raises": "test_versions_unexisting",
    "test_group_version_tracking": "test_versions_group",
    "test_group_pinned_version": "test_versions_group_select",
}

_FAKE_AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
}


class TestSSMVersioning(unittest.TestCase):
    """SSMParameter version selection, pinning, and group behaviour."""

    PARAM_VALUE = "abc123"
    PARAM_VALUE_V2 = "789xyz"

    def setUp(self):
        self._env_patcher = patch.dict(os.environ, _FAKE_AWS_ENV)
        self._env_patcher.start()

    def tearDown(self):
        for cls in (SSMParameter, SSMParameterGroup, Refreshable):
            if "_ssm_client" in cls.__dict__:  # pylint: disable=protected-access
                delattr(cls, "_ssm_client")
        Refreshable._ssm_client = None  # pylint: disable=protected-access
        self._env_patcher.stop()

    def _placebo_param(self, test_name):
        """Return the SSM param name recorded for this test."""
        return _PLACEBO_PARAM[test_name]

    def _setup_placebo(self, test_name):
        """Attach a placebo session and set it as the shared SSM client."""
        session = boto3.Session()
        pill = placebo.attach(
            session,
            data_path=os.path.join(PLACEBO_BASE, test_name),
        )
        pill.playback()
        # Set on Refreshable so SSMParameterGroup picks it up via MRO.
        Refreshable.set_ssm_client(session.client("ssm"))
        return session.client("ssm")

    def _put(self, client, name, value=None):
        client.put_parameter(
            Name=name,
            Value=value or self.PARAM_VALUE,
            Type="String",
            Overwrite=True,
        )

    def _delete(self, client, name):
        client.delete_parameter(Name=name)

    # ------------------------------------------------------------------

    def test_update_increments_version(self):
        test = "test_update_increments_version"
        name = self._placebo_param(test)
        client = self._setup_placebo(test)
        self._put(client, name)

        param = SSMParameter(name)
        self.assertEqual(param.version, 1)
        self.assertEqual(param.value, self.PARAM_VALUE)

        self._put(client, name, self.PARAM_VALUE_V2)
        param.refresh()

        self.assertEqual(param.version, 2)
        self.assertEqual(param.value, self.PARAM_VALUE_V2)
        self._delete(client, name)

    def test_pinned_version_not_overwritten_on_refresh(self):
        test = "test_pinned_version_not_overwritten_on_refresh"
        name = self._placebo_param(test)
        client = self._setup_placebo(test)
        self._put(client, name)

        param = SSMParameter(f"{name}:1")
        self.assertEqual(param.value, self.PARAM_VALUE)
        self.assertEqual(param.version, 1)

        self._put(client, name, self.PARAM_VALUE_V2)
        param.refresh()

        # pinned to :1 — must not change
        self.assertEqual(param.value, self.PARAM_VALUE)
        self.assertEqual(param.version, 1)
        self._delete(client, name)

    def test_nonexistent_version_raises(self):
        test = "test_nonexistent_version_raises"
        name = self._placebo_param(test)
        client = self._setup_placebo(test)
        self._put(client, name)

        with self.assertRaises(InvalidParameterError):
            _ = SSMParameter(f"{name}:10").value
        self._delete(client, name)

    def test_invalid_version_format_raises(self):
        """No placebo needed — validation is pure Python."""
        for bad in (":hello", ":0", ":-1", ":"):
            with self.assertRaises(InvalidVersionError):
                SSMParameter(f"my_param{bad}")

    def test_group_version_tracking(self):
        test = "test_group_version_tracking"
        name = self._placebo_param(test)
        client = self._setup_placebo(test)
        self._put(client, name)

        group = SSMParameterGroup()
        param = group.parameter(name)
        self.assertEqual(param.version, 1)
        self.assertEqual(param.value, self.PARAM_VALUE)

        self._put(client, name, self.PARAM_VALUE_V2)
        group.refresh()

        self.assertEqual(param.version, 2)
        self.assertEqual(param.value, self.PARAM_VALUE_V2)
        self._delete(client, name)

    def test_group_pinned_version(self):
        test = "test_group_pinned_version"
        name = self._placebo_param(test)
        client = self._setup_placebo(test)
        self._put(client, name)
        self._put(client, name, self.PARAM_VALUE_V2)

        group = SSMParameterGroup()
        param = group.parameter(f"{name}:1")
        self.assertEqual(param.version, 1)
        self.assertEqual(param.value, self.PARAM_VALUE)
        self._delete(client, name)
