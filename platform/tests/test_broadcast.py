"""Tests for ws/broadcast.py — _json_default helper."""

from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from ws.broadcast import _json_default


class TestJsonDefault:
    def test_decimal_to_float(self):
        result = _json_default(Decimal("3.14"))
        assert result == 3.14
        assert isinstance(result, float)

    def test_datetime_to_isoformat(self):
        dt = datetime(2025, 1, 15, 12, 30, 0)
        result = _json_default(dt)
        assert result == "2025-01-15T12:30:00"
        assert isinstance(result, str)

    def test_date_to_isoformat(self):
        d = date(2025, 6, 1)
        result = _json_default(d)
        assert result == "2025-06-01"

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="not JSON serializable"):
            _json_default(set())
