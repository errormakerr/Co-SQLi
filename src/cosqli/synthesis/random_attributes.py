"""
Random value generators for SQL placeholder substitution.
"""

from __future__ import annotations

import random
import string
from datetime import date, timedelta
from typing import Optional


class GetRandomAttribute:
    """Static helpers that generate random scalar values for SQL placeholders."""

    @staticmethod
    def random_time() -> str:
        """Return a random time string in ``HH:MM:SS`` format."""
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    @staticmethod
    def random_date(
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """
        Return a random date string in ``YYYY-MM-DD`` format.

        Args:
            start_date: Earliest possible date (default: 2000-01-01).
            end_date:   Latest possible date  (default: 2025-12-31).

        Raises:
            ValueError: If *start_date* is later than *end_date*.
        """
        if start_date is None:
            start_date = date(2000, 1, 1)
        if end_date is None:
            end_date = date(2025, 12, 31)
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        delta = end_date - start_date
        return (start_date + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")

    @staticmethod
    def random_hex_number() -> str:
        """Return a random hex literal string (e.g. ``0x1a2b3c``)."""
        return hex(random.randint(0, 0xFFFFFFFF))

    @staticmethod
    def random_int_number(min_value: int = 0, max_value: int = 100) -> str:
        """Return a random integer as a string."""
        return str(random.randint(min_value, max_value))

    @staticmethod
    def random_float_number(
        min_value: float = 0.0,
        max_value: float = 10.0,
        ndigits: int = 2,
    ) -> str:
        """Return a random float as a string rounded to *ndigits* decimal places."""
        return str(round(random.uniform(min_value, max_value), ndigits))

    @staticmethod
    def random_character() -> str:
        """Return a random ASCII letter."""
        return random.choice(string.ascii_letters)
