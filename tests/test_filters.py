"""Tests for ssm_cache/filters.py — SSMFilter and subclasses."""

import os

import boto3
import placebo

from ssm_cache.filters import (
    SSMFilter,
    SSMFilterKeyId,
    SSMFilterName,
    SSMFilterPath,
    SSMFilterType,
)
from ssm_cache.groups import SSMParameterGroup

from . import TestBase

PLACEBO_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "placebo/filters"))


class TestSSMFilterInterface(TestBase):
    """Unit tests for SSMFilter and typed subclasses."""

    def test_basic_to_dict(self):
        f = SSMFilter(key=SSMFilter.KEY_NAME)
        d = f.to_dict()
        self.assertEqual(d["Key"], SSMFilter.KEY_NAME)
        self.assertEqual(d["Option"], SSMFilter.OPTION_EQUALS)
        self.assertNotIn("Values", d)

    def test_value_appears_in_dict(self):
        f = SSMFilter(key=SSMFilter.KEY_NAME)
        f.value("TestValue")
        d = f.to_dict()
        self.assertIn("Values", d)
        self.assertEqual(d["Values"], ["TestValue"])

    def test_invalid_key_raises(self):
        with self.assertRaises(ValueError):
            SSMFilter(key="invalid_key")

    def test_max_50_values(self):
        f = SSMFilter(key=SSMFilter.KEY_NAME)
        for i in range(50):
            f.value(i)
        with self.assertRaises(ValueError):
            f.value("51st")

    def test_option_beginswith(self):
        f = SSMFilter(key=SSMFilter.KEY_NAME, option=SSMFilter.OPTION_BEGINSWITH)
        self.assertEqual(f.to_dict()["Option"], SSMFilter.OPTION_BEGINSWITH)

    def test_path_option_recursive(self):
        f = SSMFilter(key=SSMFilter.KEY_PATH, option=SSMFilter.OPTION_RECURSIVE)
        self.assertEqual(f.to_dict()["Option"], SSMFilter.OPTION_RECURSIVE)

    def test_path_with_non_path_option_raises(self):
        with self.assertRaises(ValueError):
            SSMFilter(key=SSMFilter.KEY_PATH, option=SSMFilter.OPTION_EQUALS)
        with self.assertRaises(ValueError):
            SSMFilter(key=SSMFilter.KEY_PATH, option=SSMFilter.OPTION_BEGINSWITH)

    def test_non_path_key_with_path_option_raises(self):
        with self.assertRaises(ValueError):
            SSMFilter(key=SSMFilter.KEY_NAME, option=SSMFilter.OPTION_RECURSIVE)
        with self.assertRaises(ValueError):
            SSMFilter(key=SSMFilter.KEY_NAME, option=SSMFilter.OPTION_ONELEVEL)

    def test_filter_name_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            SSMFilterName()

    def test_filter_type_valid_values(self):
        f = SSMFilterType()
        self.assertEqual(f.to_dict()["Key"], SSMFilter.KEY_TYPE)
        with self.assertRaises(ValueError):
            f.value("invalid_type")
        f.value(SSMFilterType.TYPE_SECURESTRING)
        self.assertEqual(f.to_dict()["Values"], [SSMFilterType.TYPE_SECURESTRING])

    def test_filter_keyid(self):
        f = SSMFilterKeyId()
        self.assertEqual(f.to_dict()["Key"], SSMFilter.KEY_KEYID)
        self.assertEqual(f.to_dict()["Option"], SSMFilter.OPTION_EQUALS)

    def test_filter_path_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            SSMFilterPath()

    def test_chainability(self):
        f = SSMFilterKeyId()
        f.value("V1").value("V2").value("V3")
        self.assertEqual(len(f.to_dict()["Values"]), 3)
        f.values(["V4", "V5"]).values(["V6", "V7"]).values(["V8", "V9", "V10"])
        self.assertEqual(len(f.to_dict()["Values"]), 10)


class TestSSMFilterIntegration(TestBase):
    """Integration tests using placebo-recorded SSM responses.

    All assertions live in a single test method because the placebo session
    replays responses sequentially — each call consumes the next file.
    Splitting into separate test methods would reset the counter to file 1
    for each, breaking the expected response order.
    """

    def setUp(self):
        super().setUp()
        from ssm_cache.refreshable import Refreshable

        session = boto3.Session()
        pill = placebo.attach(session, data_path=PLACEBO_PATH)
        pill.playback()
        Refreshable.set_ssm_client(session.client("ssm"))

    def test_integration(self):
        """Run all filter variants in the order responses were recorded."""
        # 1. manual filter dict — StringList
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[{"Key": "Type", "Option": "Equals", "Values": ["StringList"]}],
        )
        self.assertEqual(len(params), 1)

        # 2. SSMFilterType — StringList
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[SSMFilterType().value("StringList")],
        )
        self.assertEqual(len(params), 1)

        # 3. SSMFilterType — SecureString
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[SSMFilterType().value("SecureString")],
        )
        self.assertEqual(len(params), 1)

        # 4. SSMFilterType — String
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[SSMFilterType().value("String")],
        )
        self.assertEqual(len(params), 3)

        # 5. SSMFilterKeyId — exact match
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[SSMFilterKeyId().value("alias/aws/ssm")],
        )
        self.assertEqual(len(params), 1)

        # 6. SSMFilterKeyId — begins-with
        group = SSMParameterGroup()
        params = group.parameters(
            path="/filters-test",
            filters=[SSMFilterKeyId("BeginsWith").value("alias/")],
        )
        self.assertEqual(len(params), 1)
