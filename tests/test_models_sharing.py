"""Tests for sharing-related models and enums."""

import hashlib
import pytest
from boswell.server.models import ProjectRole, _hash_token


class TestProjectRole:
    def test_values(self):
        assert ProjectRole.view.value == "view"
        assert ProjectRole.operate.value == "operate"
        assert ProjectRole.collaborate.value == "collaborate"
        assert ProjectRole.owner.value == "owner"

    def test_ordering(self):
        roles = [ProjectRole.view, ProjectRole.operate, ProjectRole.collaborate, ProjectRole.owner]
        for i, role in enumerate(roles):
            for j, other in enumerate(roles):
                if i >= j:
                    assert role >= other, f"{role} should be >= {other}"
                if i > j:
                    assert role > other, f"{role} should be > {other}"
                if i <= j:
                    assert role <= other, f"{role} should be <= {other}"
                if i < j:
                    assert role < other, f"{role} should be < {other}"

    def test_owner_is_highest(self):
        assert ProjectRole.owner >= ProjectRole.collaborate
        assert ProjectRole.owner >= ProjectRole.operate
        assert ProjectRole.owner >= ProjectRole.view

    def test_view_is_lowest(self):
        assert ProjectRole.view <= ProjectRole.operate
        assert ProjectRole.view <= ProjectRole.collaborate
        assert ProjectRole.view <= ProjectRole.owner


class TestHashToken:
    def test_returns_sha256_hex(self):
        raw = "test-token-abc"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_token(raw) == expected

    def test_length_is_64(self):
        assert len(_hash_token("anything")) == 64

    def test_deterministic(self):
        assert _hash_token("foo") == _hash_token("foo")

    def test_different_inputs_differ(self):
        assert _hash_token("a") != _hash_token("b")
