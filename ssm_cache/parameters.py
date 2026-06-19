from ssm_cache.exceptions import (
    InvalidParameterError,
    InvalidVersionError,
)
from ssm_cache.refreshable import Refreshable


class SSMParameter(Refreshable):
    """Concrete class for an individual SSM Parameter."""

    def __init__(self, param_name, max_age=None, with_decryption=True):
        super().__init__(max_age)

        if not param_name:
            raise ValueError("Must specify name")

        (
            self._name,
            self._version,
            self._is_pinned_version,
        ) = self._parse_version(param_name)

        self._value = None
        self._with_decryption = with_decryption
        self._group = None

    def load(self, value, version):
        """Load parameter values without direct protected mutation."""
        self._value = value
        self._version = version

    @staticmethod
    def _parse_version(param_name):
        name, version, is_pinned_version = param_name, None, False

        if ":" in param_name:
            name, version = param_name.split(":")

            if version.isdigit() and int(version) > 0:
                version = int(version)
                is_pinned_version = True
            else:
                raise InvalidVersionError(f"Invalid version: {version}")

        return name, version, is_pinned_version

    def _should_refresh(self):
        if self._group:
            return self._group._should_refresh()

        return super()._should_refresh()

    def _refresh(self):
        if self._group:
            self._group.refresh()

        items, invalid_parameters = self._get_parameters(
            [self.full_name],
            self._with_decryption,
        )

        if invalid_parameters or self._name not in items:
            raise InvalidParameterError(f"{self._name} is invalid. {invalid_parameters} - {items}")

        self.load(
            value=items[self._name]["Value"],
            version=items[self._name]["Version"],
        )

    @property
    def name(self):
        return self._name

    @property
    def full_name(self):
        if self._version and self._is_pinned_version:
            return f"{self._name}:{self._version}"

        return self._name

    @property
    def version(self):
        if self._version is None or self._should_refresh():
            self.refresh()

        return self._version

    @property
    def value(self):
        if self._value is None or self._should_refresh():
            self.refresh()

        return self._value


class SecretsManagerParameter(SSMParameter):
    PREFIX = "/aws/reference/secretsmanager/"

    def __init__(self, param_name, max_age=None, with_decryption=True):
        param_name = self._add_prefix(param_name)
        super().__init__(param_name, max_age, with_decryption)

    @classmethod
    def _add_prefix(cls, param_name):
        if not param_name:
            raise ValueError("Secret name can't be empty")

        if not param_name.startswith(cls.PREFIX):
            if param_name.startswith("/"):
                raise InvalidParameterError(param_name)

            param_name = f"{cls.PREFIX}{param_name}"

        return param_name
