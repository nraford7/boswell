"""Tests for password authentication helpers."""

import pytest

# Import directly from passlib to avoid circular import during tests
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return _pwd_context.verify(password, password_hash)


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
