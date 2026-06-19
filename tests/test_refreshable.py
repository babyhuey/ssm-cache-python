"""Tests for ssm_cache/refreshable.py — Refreshable base class,
refresh_on_error decorator, and set_ssm_client override."""

from datetime import timedelta
from unittest.mock import Mock

from freezegun import freeze_time

from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SSMParameter
from ssm_cache.refreshable import Refreshable
from ssm_cache.utils import utcnow

from . import TestBase

# ---------------------------------------------------------------------------
# Refreshable base class
# ---------------------------------------------------------------------------


class TestRefreshable(TestBase):
    """Unit tests for the Refreshable abstract base class."""

    def test_should_refresh_without_max_age(self):
        ref = Refreshable(None)
        self.assertFalse(ref._should_refresh())  # pylint: disable=protected-access

    def test_should_refresh_with_max_age_and_no_data(self):
        ref = Refreshable(max_age=10)
        self.assertTrue(ref._should_refresh())  # pylint: disable=protected-access

    def test_should_refresh_recently_fetched(self):
        ref = Refreshable(max_age=10)
        ref._last_refresh_time = utcnow()  # pylint: disable=protected-access
        self.assertFalse(ref._should_refresh())  # pylint: disable=protected-access

    def test_should_refresh_after_max_age_elapsed(self):
        ref = Refreshable(max_age=10)
        ref._last_refresh_time = utcnow()  # pylint: disable=protected-access
        with freeze_time(lambda: utcnow() + timedelta(seconds=10)):
            self.assertTrue(ref._should_refresh())  # pylint: disable=protected-access

    def test_refresh_raises_not_implemented(self):
        ref = Refreshable(None)
        with self.assertRaises(NotImplementedError):
            ref.refresh()


# ---------------------------------------------------------------------------
# refresh_on_error decorator (lives on Refreshable, tested via SSMParameter)
# ---------------------------------------------------------------------------


class MySpecialError(Exception):
    """Sentinel error for decorator tests."""


class TestRefreshOnError(TestBase):
    """Tests for Refreshable.refresh_on_error."""

    def setUp(self):
        super().setUp()
        self._create_params(["my_param", "my_grouped_param"])
        self.param = SSMParameter("my_param")
        self.group = SSMParameterGroup()
        self.grouped_param = self.group.parameter("my_grouped_param")

    def test_retries_on_error(self):
        @self.param.refresh_on_error()
        def fn(is_retry=False):
            if not is_retry:
                raise Exception("first attempt fails")
            return "OK"

        self.assertEqual("OK", fn())

    def test_retries_on_error_for_group(self):
        @self.group.refresh_on_error()
        def fn(is_retry=False):
            if not is_retry:
                raise Exception("first attempt fails")
            return "OK"

        self.assertEqual("OK", fn())

    def test_specific_error_class_handled(self):
        @self.param.refresh_on_error(MySpecialError)
        def fn(is_retry=False):
            if not is_retry:
                raise MySpecialError("special")
            return "OK"

        self.assertEqual("OK", fn())

    def test_generic_error_not_handled_when_specific_given(self):
        @self.param.refresh_on_error(MySpecialError)
        def fn(is_retry=False):
            if not is_retry:
                raise Exception("generic")
            return "OK"

        with self.assertRaises(Exception):
            fn()

    def test_callback_invoked_on_error(self):
        callback = Mock()

        @self.param.refresh_on_error(Exception, callback)
        def fn(is_retry=False):
            if not is_retry:
                raise Exception("oops")
            return "OK"

        self.assertEqual("OK", fn())
        self.assertEqual(1, callback.call_count)

    def test_invalid_callback_raises(self):
        with self.assertRaises(TypeError):

            @self.param.refresh_on_error(Exception, "not_callable")
            def fn():
                pass

    def test_custom_retry_argument_name(self):
        @self.param.refresh_on_error(retry_argument="my_retry")
        def fn(my_retry=False):
            if not my_retry:
                raise Exception("oops")
            return "OK"

        self.assertEqual("OK", fn())

    def test_only_first_exception_handled(self):
        @self.param.refresh_on_error()
        def fn(is_retry=False):
            raise Exception(f"{is_retry}")

        with self.assertRaises(Exception) as ctx:
            fn()
        self.assertEqual(str(ctx.exception), "True")

    def test_all_options_together(self):
        data = {"result": "KO"}

        def callback():
            data["result"] = "OK"

        @self.param.refresh_on_error(MySpecialError, callback, retry_argument="my_retry")
        def fn(my_retry=False):
            if not my_retry:
                raise MySpecialError("special")
            return data["result"]

        self.assertEqual("OK", fn())


# ---------------------------------------------------------------------------
# set_ssm_client override
# ---------------------------------------------------------------------------


class TestSetSSMClient(TestBase):
    """Tests for Refreshable.set_ssm_client."""

    PARAM_VALUE = "abc123"

    def test_illegal_client_not_an_object(self):
        with self.assertRaises(TypeError):
            SSMParameter.set_ssm_client(42)

    def test_illegal_client_missing_method(self):
        class PartialClient:
            def get_parameters(self):
                pass  # missing get_parameters_by_path

        with self.assertRaises(TypeError):
            SSMParameter.set_ssm_client(PartialClient())

    def test_valid_duck_typed_client(self):
        class FullClient:
            def get_parameters(self, *_, **__):
                return {
                    "InvalidParameters": [],
                    "Parameters": [
                        {
                            "Type": "String",
                            "Name": "my_param",
                            "Value": "abc123",
                            "Version": 1,
                        },
                    ],
                }

            def get_parameters_by_path(self, *_, **__):
                return {
                    "Parameters": [
                        {
                            "Type": "String",
                            "Name": "/foo/1",
                            "Value": "abc123",
                            "Version": 1,
                        },
                        {
                            "Type": "String",
                            "Name": "/foo/2",
                            "Value": "abc123",
                            "Version": 1,
                        },
                    ]
                }

        # Set on Refreshable (base class) so both SSMParameter and
        # SSMParameterGroup resolve the same client through MRO lookup
        # without any subclass shadow attribute interfering.
        from ssm_cache.refreshable import Refreshable

        Refreshable.set_ssm_client(FullClient())

        param = SSMParameter("my_param")
        self.assertEqual(param.value, self.PARAM_VALUE)

        group = SSMParameterGroup()
        grouped = group.parameter("my_param")
        self.assertEqual(grouped.value, self.PARAM_VALUE)

        params = group.parameters("/foo/")
        self.assertEqual(len(params), 2)
        for p in params:
            self.assertEqual(p.value, self.PARAM_VALUE)
