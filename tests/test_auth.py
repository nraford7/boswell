"""Tests for password authentication helpers."""

import pytest

from boswell.server.auth_utils import hash_password, verify_password


class TestPasswordHelpers:
    def test_hash_and_verify(self):
        """Hashing then verifying should succeed."""
        pw = "secureP@ssword123"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        """Wrong password should not verify."""
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_hashes_are_unique(self):
        """Same password should produce different hashes (random salt)."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        # But both should verify
        assert verify_password("same", h1)
        assert verify_password("same", h2)

    def test_empty_password_hashes(self):
        """Empty string should still hash and verify."""
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("notempty", hashed)

    def test_long_ascii_password(self):
        """Passwords longer than 72 bytes are truncated by bcrypt."""
        long_pw = "a" * 100
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed)

    def test_long_utf8_password(self):
        """Multi-byte UTF-8 passwords longer than 72 bytes are handled."""
        # Each character is 3 bytes in UTF-8, so 30 chars = 90 bytes > 72
        long_pw = "\u00e9" * 40  # é is 2 bytes each, 80 bytes total
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed)

    def test_malformed_hash_returns_false(self):
        """verify_password should return False for corrupted hashes."""
        assert not verify_password("anything", "not-a-valid-hash")
        assert not verify_password("anything", "")
