"""Test base class shared by all test modules."""

import logging
import os
import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws

from ssm_cache.groups import SSMParameterGroup
from ssm_cache.parameters import SSMParameter

logging.getLogger("boto3").setLevel(logging.CRITICAL)
logging.getLogger("botocore").setLevel(logging.CRITICAL)

# Fake credentials moto expects.  Forced via patch.dict so they always win
# over any real credentials already present (IAM role, ~/.aws/credentials,
# existing env vars).  os.environ.setdefault was the previous approach; it
# silently left real credentials in place, causing boto3 to bypass moto.
_FAKE_AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
}


class TestBase(unittest.TestCase):
    """Activates a fresh moto mock before every test and tears it down after.

    patch.dict forces fake AWS credentials for the lifetime of each test so
    that any boto3 client created inside Refreshable._get_ssm_client() —
    which supplies no credentials of its own — is intercepted by moto rather
    than reaching real AWS.  The originals are restored by patch.dict.stop()
    in tearDown.
    """

    PARAM_VALUE = "abc123"
    PARAM_LIST_COUNT = 2

    def setUp(self):
        self._env_patcher = patch.dict(os.environ, _FAKE_AWS_ENV)
        self._env_patcher.start()

        self.mock = mock_aws()
        self.mock.start()

        self.ssm_client = boto3.client("ssm", region_name="us-east-1")
        self.secretsmanager_client = boto3.client("secretsmanager", region_name="us-east-1")

    def tearDown(self):
        from ssm_cache.refreshable import Refreshable

        for cls in (SSMParameter, SSMParameterGroup, Refreshable):
            if "_ssm_client" in cls.__dict__:  # pylint: disable=protected-access
                delattr(cls, "_ssm_client")
        Refreshable._ssm_client = None  # pylint: disable=protected-access

        self.mock.stop()
        self._env_patcher.stop()

    # ------------------------------------------------------------------

    def _create_params(self, names, value=PARAM_VALUE, parameter_type="String"):
        if parameter_type == "StringList" and not isinstance(value, list):
            value = ",".join([value] * self.PARAM_LIST_COUNT)
        for name in names:
            args = dict(Name=name, Value=value, Type=parameter_type, Overwrite=True)
            if parameter_type == "SecureString":
                args["KeyId"] = "alias/aws/ssm"
            self.ssm_client.put_parameter(**args)

    def _create_secrets(self, names, value=PARAM_VALUE, parameter_type="SecretString"):
        for name in names:
            args = dict(Name=name, Description=name)
            if parameter_type == "SecretString":
                args["SecretString"] = value
            elif parameter_type == "SecretBinary":
                args["SecretBinary"] = value
            try:
                self.secretsmanager_client.create_secret(**args)
            except self.secretsmanager_client.exceptions.ResourceExistsException:
                pass
