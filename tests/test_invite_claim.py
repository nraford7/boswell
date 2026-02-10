"""Tests for invite claim logic."""

import hashlib
from boswell.server.models import _hash_token


class TestHashToken:
    def test_sha256(self):
        raw = "test-token-abc"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_token(raw) == expected

    def test_length(self):
        assert len(_hash_token("anything")) == 64

    def test_deterministic(self):
        assert _hash_token("foo") == _hash_token("foo")

    def test_different_inputs(self):
        assert _hash_token("a") != _hash_token("b")
