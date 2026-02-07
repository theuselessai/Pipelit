"""Tests for shared operator definitions."""

from __future__ import annotations

import pytest

from components.operators import OPERATORS, UNARY_OPERATORS, _resolve_field, _to_num, _to_dt, _to_bool


class TestEquality:
    def test_equals(self):
        assert OPERATORS["equals"]("hello", "hello")
        assert not OPERATORS["equals"]("hello", "world")

    def test_equals_coerces_to_string(self):
        assert OPERATORS["equals"](42, "42")
        assert OPERATORS["equals"](True, "True")

    def test_not_equals(self):
        assert OPERATORS["not_equals"]("a", "b")
        assert not OPERATORS["not_equals"]("a", "a")


class TestStringOps:
    def test_contains(self):
        assert OPERATORS["contains"]("hello world", "world")
        assert not OPERATORS["contains"]("hello", "world")

    def test_contains_list(self):
        assert OPERATORS["contains"]([1, 2, 3], 2)
        assert not OPERATORS["contains"]([1, 2, 3], 4)

    def test_not_contains(self):
        assert OPERATORS["not_contains"]("hello", "world")
        assert not OPERATORS["not_contains"]("hello world", "world")

    def test_not_contains_list(self):
        assert OPERATORS["not_contains"]([1, 2], 3)
        assert not OPERATORS["not_contains"]([1, 2], 2)

    def test_starts_with(self):
        assert OPERATORS["starts_with"]("hello world", "hello")
        assert not OPERATORS["starts_with"]("hello", "world")

    def test_not_starts_with(self):
        assert OPERATORS["not_starts_with"]("hello", "world")
        assert not OPERATORS["not_starts_with"]("hello", "hello")

    def test_ends_with(self):
        assert OPERATORS["ends_with"]("hello world", "world")
        assert not OPERATORS["ends_with"]("hello", "world")

    def test_not_ends_with(self):
        assert OPERATORS["not_ends_with"]("hello", "world")
        assert not OPERATORS["not_ends_with"]("hello world", "world")

    def test_matches_regex(self):
        assert OPERATORS["matches_regex"]("hello123", r"\d+")
        assert not OPERATORS["matches_regex"]("hello", r"\d+")

    def test_not_matches_regex(self):
        assert OPERATORS["not_matches_regex"]("hello", r"\d+")
        assert not OPERATORS["not_matches_regex"]("hello123", r"\d+")

    def test_regex_with_invalid_pattern(self):
        # Invalid regex raises, which is expected behavior
        with pytest.raises(Exception):
            OPERATORS["matches_regex"]("test", "[invalid")


class TestExistence:
    def test_exists(self):
        assert OPERATORS["exists"]("something", "")
        assert OPERATORS["exists"](0, "")
        assert not OPERATORS["exists"](None, "")

    def test_does_not_exist(self):
        assert OPERATORS["does_not_exist"](None, "")
        assert not OPERATORS["does_not_exist"]("something", "")

    def test_is_empty(self):
        assert OPERATORS["is_empty"](None, "")
        assert OPERATORS["is_empty"]("", "")
        assert OPERATORS["is_empty"]([], "")
        assert OPERATORS["is_empty"]({}, "")
        assert not OPERATORS["is_empty"]("hello", "")
        assert not OPERATORS["is_empty"]([1], "")

    def test_is_not_empty(self):
        assert OPERATORS["is_not_empty"]("hello", "")
        assert OPERATORS["is_not_empty"]([1], "")
        assert not OPERATORS["is_not_empty"](None, "")
        assert not OPERATORS["is_not_empty"]("", "")
        assert not OPERATORS["is_not_empty"]([], "")


class TestNumericOps:
    def test_gt(self):
        assert OPERATORS["gt"](10, 5)
        assert not OPERATORS["gt"](5, 10)
        assert not OPERATORS["gt"](5, 5)

    def test_lt(self):
        assert OPERATORS["lt"](5, 10)
        assert not OPERATORS["lt"](10, 5)

    def test_gte(self):
        assert OPERATORS["gte"](10, 5)
        assert OPERATORS["gte"](5, 5)
        assert not OPERATORS["gte"](4, 5)

    def test_lte(self):
        assert OPERATORS["lte"](5, 10)
        assert OPERATORS["lte"](5, 5)
        assert not OPERATORS["lte"](6, 5)

    def test_string_number_coercion(self):
        assert OPERATORS["gt"]("10", "5")
        assert OPERATORS["lt"]("5", "10")

    def test_non_numeric_falls_back_to_zero(self):
        # _to_num returns None for non-numeric, operator uses 0
        assert OPERATORS["gt"](5, "abc")  # 5 > 0
        assert not OPERATORS["gt"]("abc", 5)  # 0 > 5 = False


class TestDatetimeOps:
    def test_after(self):
        assert OPERATORS["after"]("2024-06-01", "2024-01-01")
        assert not OPERATORS["after"]("2024-01-01", "2024-06-01")

    def test_before(self):
        assert OPERATORS["before"]("2024-01-01", "2024-06-01")
        assert not OPERATORS["before"]("2024-06-01", "2024-01-01")

    def test_after_or_equal(self):
        assert OPERATORS["after_or_equal"]("2024-06-01", "2024-06-01")
        assert OPERATORS["after_or_equal"]("2024-06-02", "2024-06-01")

    def test_before_or_equal(self):
        assert OPERATORS["before_or_equal"]("2024-06-01", "2024-06-01")
        assert OPERATORS["before_or_equal"]("2024-05-31", "2024-06-01")

    def test_invalid_date_defaults(self):
        # Invalid dates should not cause errors
        assert not OPERATORS["after"]("not-a-date", "2024-01-01")
        assert not OPERATORS["before"]("not-a-date", "2024-01-01")


class TestBooleanOps:
    def test_is_true(self):
        assert OPERATORS["is_true"](True, "")
        assert OPERATORS["is_true"]("true", "")
        assert OPERATORS["is_true"]("1", "")
        assert OPERATORS["is_true"]("yes", "")
        assert not OPERATORS["is_true"](False, "")
        assert not OPERATORS["is_true"]("false", "")

    def test_is_false(self):
        assert OPERATORS["is_false"](False, "")
        assert OPERATORS["is_false"]("false", "")
        assert not OPERATORS["is_false"](True, "")


class TestLengthOps:
    def test_length_eq(self):
        assert OPERATORS["length_eq"]("abc", 3)
        assert OPERATORS["length_eq"]([1, 2], 2)
        assert not OPERATORS["length_eq"]("ab", 3)

    def test_length_neq(self):
        assert OPERATORS["length_neq"]("ab", 3)
        assert not OPERATORS["length_neq"]("abc", 3)

    def test_length_gt(self):
        assert OPERATORS["length_gt"]("abcd", 3)
        assert not OPERATORS["length_gt"]("ab", 3)

    def test_length_lt(self):
        assert OPERATORS["length_lt"]("ab", 3)
        assert not OPERATORS["length_lt"]("abcd", 3)

    def test_length_gte(self):
        assert OPERATORS["length_gte"]("abc", 3)
        assert OPERATORS["length_gte"]("abcd", 3)
        assert not OPERATORS["length_gte"]("ab", 3)

    def test_length_lte(self):
        assert OPERATORS["length_lte"]("abc", 3)
        assert OPERATORS["length_lte"]("ab", 3)
        assert not OPERATORS["length_lte"]("abcd", 3)

    def test_length_on_non_sequence(self):
        assert not OPERATORS["length_eq"](42, 2)
        assert OPERATORS["length_neq"](42, 2)
        assert not OPERATORS["length_gt"](42, 1)
        assert not OPERATORS["length_lt"](42, 1)


class TestUnaryOperators:
    def test_unary_set_correct(self):
        expected = {"exists", "does_not_exist", "is_empty", "is_not_empty", "is_true", "is_false"}
        assert UNARY_OPERATORS == expected


class TestResolveField:
    def test_simple_field(self):
        state = {"route": "chat"}
        assert _resolve_field("route", state) == "chat"

    def test_nested_field(self):
        state = {"node_outputs": {"cat1": {"category": "chat"}}}
        assert _resolve_field("node_outputs.cat1.category", state) == "chat"

    def test_state_prefix_stripped(self):
        state = {"route": "chat"}
        assert _resolve_field("state.route", state) == "chat"

    def test_missing_field_returns_none(self):
        state = {"a": 1}
        assert _resolve_field("b", state) is None

    def test_deeply_nested_missing(self):
        state = {"a": {"b": {}}}
        assert _resolve_field("a.b.c", state) is None

    def test_non_dict_intermediate(self):
        state = {"a": "not_a_dict"}
        assert _resolve_field("a.b", state) is None


class TestHelpers:
    def test_to_num_valid(self):
        assert _to_num("42") == 42.0
        assert _to_num(3.14) == 3.14
        assert _to_num("0") == 0.0

    def test_to_num_invalid(self):
        assert _to_num("abc") is None
        assert _to_num(None) is None

    def test_to_dt_valid(self):
        dt = _to_dt("2024-01-15")
        assert dt is not None
        assert dt.year == 2024

    def test_to_dt_with_z_suffix(self):
        dt = _to_dt("2024-01-15T10:30:00Z")
        assert dt is not None

    def test_to_dt_invalid(self):
        assert _to_dt("not-a-date") is None
        assert _to_dt(None) is None
        assert _to_dt(42) is None

    def test_to_bool(self):
        assert _to_bool(True) is True
        assert _to_bool(False) is False
        assert _to_bool("true") is True
        assert _to_bool("1") is True
        assert _to_bool("yes") is True
        assert _to_bool("false") is False
        assert _to_bool("no") is False
        assert _to_bool(1) is True
        assert _to_bool(0) is False
