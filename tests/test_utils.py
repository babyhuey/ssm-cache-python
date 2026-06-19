"""Tests for ssm_cache/utils.py"""

import unittest
from datetime import datetime, timezone

from ssm_cache.utils import batch, utcnow


class TestUtcNow(unittest.TestCase):
    """utcnow() returns a timezone-aware UTC datetime."""

    def test_returns_datetime(self):
        result = utcnow()
        self.assertIsInstance(result, datetime)

    def test_is_timezone_aware(self):
        result = utcnow()
        self.assertIsNotNone(result.tzinfo)

    def test_is_utc(self):
        result = utcnow()
        self.assertEqual(result.tzinfo, timezone.utc)


class TestBatch(unittest.TestCase):
    """batch() splits an iterable into fixed-size chunks."""

    def test_exact_multiple(self):
        result = list(batch([1, 2, 3, 4], 2))
        self.assertEqual(result, [[1, 2], [3, 4]])

    def test_remainder(self):
        result = list(batch([1, 2, 3, 4, 5], 2))
        self.assertEqual(result, [[1, 2], [3, 4], [5]])

    def test_larger_than_input(self):
        result = list(batch([1, 2], 10))
        self.assertEqual(result, [[1, 2]])

    def test_empty(self):
        result = list(batch([], 5))
        self.assertEqual(result, [])

    def test_batch_of_one(self):
        result = list(batch([1, 2, 3], 1))
        self.assertEqual(result, [[1], [2], [3]])
