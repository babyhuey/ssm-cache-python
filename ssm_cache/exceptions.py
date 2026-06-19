"""Custom exceptions for ssm_cache."""


class InvalidParameterError(Exception):
    """Raised when something's wrong with the provided param name"""


class InvalidPathError(Exception):
    """Raised when a given path is not properly structured"""


class InvalidVersionError(Exception):
    """Raised when something's wrong with the provided param version"""
