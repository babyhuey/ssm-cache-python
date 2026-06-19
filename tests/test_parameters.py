"""Tests for ssm_cache/parameters.py — SSMParameter."""

from datetime import timedelta

from ssm_cache.exceptions import InvalidParameterError
from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SSMParameter
from ssm_cache.utils import utcnow

from . import TestBase


# pylint: disable=protected-access
class TestSSMParameter(TestBase):
    """SSMParameter creation, value fetching, expiration, and refresh."""

    def setUp(self):
        super().setUp()
        self._create_params(["my_param", "my_param_1", "my_param_2", "my_param_3"])
        self._create_params(["my_params_list"], parameter_type="StringList")

    def test_creation_defaults(self):
        param = SSMParameter("my_param")
        self.assertTrue(param._with_decryption)
        self.assertIsNone(param._max_age)
        self.assertIsNone(param._last_refresh_time)

    def test_creation_requires_name(self):
        with self.assertRaises(TypeError):
            SSMParameter()  # pylint: disable=no-value-for-parameter
        with self.assertRaises(ValueError):
            SSMParameter(None)

    def test_value(self):
        self.assertEqual(SSMParameter("my_param").value, self.PARAM_VALUE)

    def test_value_without_decryption(self):
        param = SSMParameter("my_param", with_decryption=False)
        self.assertEqual(param.value, self.PARAM_VALUE)

    def test_value_with_max_age(self):
        param = SSMParameter("my_param", max_age=300)
        self.assertEqual(param.value, self.PARAM_VALUE)

    def test_invalid_parameter_raises(self):
        with self.assertRaises(InvalidParameterError):
            _ = SSMParameter("does_not_exist").value

    def test_string_list_auto_converted(self):
        values = SSMParameter("my_params_list").value
        self.assertIsInstance(values, list)
        self.assertEqual(len(values), self.PARAM_LIST_COUNT)
        for v in values:
            self.assertEqual(v, self.PARAM_VALUE)

    def test_explicit_refresh(self):
        param = SSMParameter("my_param")
        _ = param.value  # populate cache

        new_value = "new_value"
        self._create_params(["my_param"], new_value)
        param.refresh()
        self.assertEqual(param.value, new_value)

    def test_expiration_triggers_refetch(self):
        group = SSMParameterGroup(max_age=300)
        param_1 = group.parameter("my_param_1")
        param_2 = group.parameter("my_param_2")
        param_3 = group.parameter("my_param_3")

        # individual params carry no max_age — it lives on the group
        for p in (param_1, param_2, param_3):
            self.assertIsNone(p._max_age)

        group.refresh()

        # simulate expiry
        group._last_refresh_time = utcnow() - timedelta(seconds=301)
        self.assertTrue(group._should_refresh())
        self.assertTrue(param_1._should_refresh())

    def test_lambda_handler_pattern(self):
        cache = SSMParameter("my_param")

        def lambda_handler(event, context):
            return f"secret={cache.value}"

        self.assertEqual(lambda_handler(None, None), f"secret={self.PARAM_VALUE}")

    def test_retry_on_error(self):
        param = SSMParameter("my_param")

        class BadCreds(Exception):
            pass

        def do_work():
            if param.value == self.PARAM_VALUE:
                raise BadCreds()

        try:
            do_work()
        except BadCreds:
            self._create_params(["my_param"], "new_value")
            param.refresh()
            do_work()  # should not raise; new value is "new_value" ≠ PARAM_VALUE
