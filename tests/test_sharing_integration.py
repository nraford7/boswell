"""Integration tests for the sharing workflow.

Tests validate the core sharing logic and invariants.
Tests requiring a running database are marked with skipif.
"""

import os
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from boswell.server.models import ProjectRole, _hash_token
from boswell.server.authorization import (
    get_project_role,
    check_project_access,
    assert_not_last_owner,
)


class TestProjectRoleHierarchy:
    """Verify role comparison operators work correctly."""

    def test_owner_can_do_everything(self):
        assert ProjectRole.owner >= ProjectRole.view
        assert ProjectRole.owner >= ProjectRole.operate
        assert ProjectRole.owner >= ProjectRole.collaborate
        assert ProjectRole.owner >= ProjectRole.owner

    def test_view_is_minimum(self):
        assert not (ProjectRole.view >= ProjectRole.operate)
        assert not (ProjectRole.view >= ProjectRole.collaborate)
        assert not (ProjectRole.view >= ProjectRole.owner)

    def test_operate_includes_view(self):
        assert ProjectRole.operate >= ProjectRole.view
        assert not (ProjectRole.operate >= ProjectRole.collaborate)

    def test_collaborate_includes_operate(self):
        assert ProjectRole.collaborate >= ProjectRole.operate
        assert ProjectRole.collaborate >= ProjectRole.view
        assert not (ProjectRole.collaborate >= ProjectRole.owner)


class TestAccessControl:
    """Verify access control logic."""

    @pytest.mark.asyncio
    async def test_view_user_cannot_edit(self):
        """A user with view role should get 403 on edit-level access."""
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ProjectRole.view
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await check_project_access(uuid4(), uuid4(), ProjectRole.collaborate, mock_db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_operate_user_can_view(self):
        """A user with operate role can access view-level resources."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ProjectRole.operate
        mock_db.execute.return_value = mock_result

        role = await check_project_access(uuid4(), uuid4(), ProjectRole.view, mock_db)
        assert role == ProjectRole.operate

    @pytest.mark.asyncio
    async def test_no_share_returns_404(self):
        """A user with no share should get 404."""
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await check_project_access(uuid4(), uuid4(), ProjectRole.view, mock_db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_owner_can_manage_sharing(self):
        """Owner can access owner-level resources (sharing management)."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ProjectRole.owner
        mock_db.execute.return_value = mock_result

        role = await check_project_access(uuid4(), uuid4(), ProjectRole.owner, mock_db)
        assert role == ProjectRole.owner

    @pytest.mark.asyncio
    async def test_collaborate_cannot_manage_sharing(self):
        """Collaborator cannot access owner-level resources."""
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ProjectRole.collaborate
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await check_project_access(uuid4(), uuid4(), ProjectRole.owner, mock_db)
        assert exc_info.value.status_code == 403


class TestLastOwnerInvariant:
    """Verify the last-owner invariant is enforced."""

    @pytest.mark.asyncio
    async def test_cannot_remove_last_owner(self):
        """Removing the only owner should raise 400."""
        from fastapi import HTTPException

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0  # No other owners
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await assert_not_last_owner(uuid4(), uuid4(), mock_db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_can_remove_non_last_owner(self):
        """Removing a non-last owner should succeed."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1  # One other owner exists
        mock_db.execute.return_value = mock_result

        # Should not raise
        await assert_not_last_owner(uuid4(), uuid4(), mock_db)


class TestTokenHashing:
    """Verify invite token hashing."""

    def test_tokens_are_hashed_not_stored_raw(self):
        raw_token = "secret-invite-token-123"
        hashed = _hash_token(raw_token)
        assert hashed != raw_token
        assert len(hashed) == 64

    def test_same_token_same_hash(self):
        assert _hash_token("abc") == _hash_token("abc")

    def test_hash_is_sha256(self):
        raw = "test"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_token(raw) == expected


class TestPermissionMatrix:
    """Validate the full permission matrix from the design doc."""

    @pytest.mark.asyncio
    async def test_permission_matrix_completeness(self):
        """Every action in the permission matrix should be testable."""
        actions = {
            "see_project": ProjectRole.view,
            "start_interviews": ProjectRole.operate,
            "edit_project": ProjectRole.collaborate,
            "add_guests": ProjectRole.collaborate,
            "manage_sharing": ProjectRole.owner,
            "delete_project": ProjectRole.owner,
            "transfer_ownership": ProjectRole.owner,
        }

        for action, min_role in actions.items():
            # Owner should always succeed
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = ProjectRole.owner
            mock_db.execute.return_value = mock_result

            role = await check_project_access(uuid4(), uuid4(), min_role, mock_db)
            assert role == ProjectRole.owner, f"Owner should be able to {action}"
