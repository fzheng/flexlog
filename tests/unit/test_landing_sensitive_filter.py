"""Truth table for the sensitive-info heuristic used on the landing page
to avoid forwarding typed passwords / SSNs / credit-card numbers through
the Google search redirect."""
from __future__ import annotations

import pytest

from flexlog.web.landing_bp import (
    _looks_like_cc,
    _looks_like_password,
    _looks_like_ssn,
    _luhn_valid,
    looks_like_sensitive_info,
)


# ----------------------------------------------------------- Luhn

@pytest.mark.parametrize("digits", [
    "4111111111111111",   # Visa test
    "5500000000000004",   # Mastercard test
    "378282246310005",    # Amex test (15)
    "6011111111111117",   # Discover test
    "3530111333300000",   # JCB test
])
def test_luhn_accepts_valid_card_numbers(digits):
    assert _luhn_valid(digits) is True


@pytest.mark.parametrize("digits", [
    "4111111111111112",   # last digit wrong
    "1234567890123456",   # arbitrary
    "0000000000000001",
])
def test_luhn_rejects_invalid_card_numbers(digits):
    assert _luhn_valid(digits) is False


# ----------------------------------------------------------- password shape

@pytest.mark.parametrize("q", [
    "hunter2",            # 7 chars, digit
    "letmein01",          # 9 chars, digit
    "Tr0ub4dor&3",        # mixed case + digit + symbol
    "MyP@ss1",            # mix
    "iphone16",           # acceptable false positive (no space, digit)
    "win10pro",           # acceptable false positive
    "Pa$$word",           # symbol + mixed case
])
def test_password_shape_positive(q):
    assert _looks_like_password(q) is True


@pytest.mark.parametrize("q", [
    "",                   # empty
    "pasta recipes",      # has whitespace
    "weather",            # no digit/symbol/case mix
    "hi",                 # too short (< 6)
    "abcde",              # too short
    "a" * 65,             # too long (> 64)
    "all lowercase letters and a space",  # whitespace
])
def test_password_shape_negative(q):
    assert _looks_like_password(q) is False


# ----------------------------------------------------------- SSN

@pytest.mark.parametrize("q", [
    "123-45-6789",        # hyphenated
    "000-00-0000",        # all zeros (still SSN-shaped)
    "123456789",          # unhyphenated 9 digits
])
def test_ssn_positive(q):
    assert _looks_like_ssn(q) is True


@pytest.mark.parametrize("q", [
    "",                   # empty
    "12-345-6789",        # wrong group sizes
    "12345-6789",         # 5-4 split
    "12345678",           # only 8 digits
    "1234567890",         # 10 digits (phone)
    "123 45 6789",        # spaces instead of hyphens
    "abc-de-fghi",        # letters
])
def test_ssn_negative(q):
    assert _looks_like_ssn(q) is False


# ----------------------------------------------------------- credit card

@pytest.mark.parametrize("q", [
    "4111 1111 1111 1111",                  # Visa test, spaced
    "4111-1111-1111-1111",                  # Visa test, hyphenated
    "5500000000000004",                     # Mastercard test, no separator
    "378282246310005",                      # Amex test, 15 digits
    "6011111111111117",                     # Discover test
])
def test_cc_positive(q):
    assert _looks_like_cc(q) is True


@pytest.mark.parametrize("q", [
    "",                                     # empty
    "1234567890123456",                     # 16 digits, fails Luhn
    "4111111111111112",                     # one digit off, fails Luhn
    "411111111111",                         # only 12 digits
    "41111111111111111111",                 # 20 digits
    "4111 1111 1111 1111 extra",            # not all digits after strip
    "weather",                              # text
])
def test_cc_negative(q):
    assert _looks_like_cc(q) is False


# ----------------------------------------------------------- composed

@pytest.mark.parametrize("q", [
    "hunter2",                              # password
    "123-45-6789",                          # SSN
    "4111 1111 1111 1111",                  # CC
    "Tr0ub4dor&3",                          # password
])
def test_composed_positive(q):
    assert looks_like_sensitive_info(q) is True


@pytest.mark.parametrize("q", [
    "pasta recipes",
    "weather",
    "best italian restaurants nyc",
    "",
])
def test_composed_negative(q):
    assert looks_like_sensitive_info(q) is False
