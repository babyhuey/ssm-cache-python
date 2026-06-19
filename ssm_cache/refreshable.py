from datetime import timedelta
from functools import wraps

import botocore.exceptions

from ssm_cache.filters import SSMFilter
from ssm_cache.utils import batch, utcnow


class Refreshable:
    """Abstract class for refreshable objects (with max-age)."""

    _ssm_client = None

    @classmethod
    def set_ssm_client(cls, client):
        required_methods = ("get_parameters", "get_parameters_by_path")

        for method in required_methods:
            if not hasattr(client, method):
                raise TypeError(f"client must have a {method} method")

        cls._ssm_client = client

    @classmethod
    def _get_ssm_client(cls):
        if cls._ssm_client is None:
            import boto3

            cls._ssm_client = boto3.client("ssm")

        return cls._ssm_client

    def __init__(self, max_age):
        self._last_refresh_time = None
        self._max_age = max_age
        self._max_age_delta = timedelta(seconds=max_age or 0)

    def _refresh(self):
        raise NotImplementedError

    def _should_refresh(self):
        if not self._max_age:
            return False

        if not self._last_refresh_time:
            return True

        return utcnow() > self._last_refresh_time + self._max_age_delta

    def _update_refresh_time(self, keep_oldest_value=False):
        now = utcnow()

        if keep_oldest_value and self._last_refresh_time:
            self._last_refresh_time = min(now, self._last_refresh_time)
        else:
            self._last_refresh_time = now

    def refresh(self):
        self._refresh()
        self._update_refresh_time()

    @staticmethod
    def _parse_value(param_value, param_type):
        if param_type == "StringList":
            return param_value.split(",")

        return param_value

    @classmethod
    def _get_parameters(cls, names, with_decryption):
        items = {}
        invalid_names = []

        for name_batch in batch(names, 10):
            try:
                response = cls._get_ssm_client().get_parameters(
                    Names=list(name_batch),
                    WithDecryption=with_decryption,
                )
            except botocore.exceptions.ClientError as exc:
                # SSM raises ParameterNotFound (rather than listing names in
                # InvalidParameters) when a Secrets Manager reference doesn't
                # exist.  Normalise to the same invalid-name path so callers
                # always get InvalidParameterError.
                code = exc.response.get("Error", {}).get("Code", "")
                if code == "ParameterNotFound":
                    invalid_names.extend(list(name_batch))
                    continue
                raise

            invalid_names.extend(response["InvalidParameters"])

            for item in response["Parameters"]:
                item["Value"] = cls._parse_value(item["Value"], item["Type"])
                items[item["Name"]] = item

        return items, invalid_names

    @classmethod
    def _get_parameters_by_path(
        cls,
        with_decryption,
        path,
        recursive=True,
        filters=None,
    ):
        items = {}

        client = cls._get_ssm_client()
        has_builtin_paginator = hasattr(client, "get_paginator")

        def serialize_filter(filter_obj):
            if isinstance(filter_obj, SSMFilter):
                return filter_obj.to_dict()

            return filter_obj

        if has_builtin_paginator:
            pages = client.get_paginator("get_parameters_by_path").paginate(
                Path=path,
                Recursive=recursive,
                WithDecryption=with_decryption,
                ParameterFilters=[serialize_filter(filter_obj) for filter_obj in (filters or [])],
            )
        else:
            pages = [
                client.get_parameters_by_path(
                    Path=path,
                    Recursive=recursive,
                    WithDecryption=with_decryption,
                    ParameterFilters=[
                        serialize_filter(filter_obj) for filter_obj in (filters or [])
                    ],
                )
            ]

        for page in pages:
            for item in page["Parameters"]:
                item["Value"] = cls._parse_value(item["Value"], item["Type"])
                items[item["Name"]] = item

        return items

    def refresh_on_error(
        self,
        error_class=Exception,
        error_callback=None,
        retry_argument="is_retry",
    ):
        if error_callback and not callable(error_callback):
            raise TypeError("error_callback must be callable")

        def true_decorator(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except error_class:
                    self.refresh()

                    if error_callback:
                        error_callback()

                    if retry_argument:
                        kwargs[retry_argument] = True

                    return func(*args, **kwargs)

            return wrapped

        return true_decorator
