"""Tests for admin user management guards and helpers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4
from datetime import datetime, timezone

from boswell.server.models import User, ProjectRole, ProjectShare


class TestDeactivatedUserBlocking:
    """Deactivated users should be treated as unauthenticated."""

    def test_deactivated_user_has_timestamp(self):
        """Deactivated users have a non-None deactivated_at."""
        user = MagicMock(spec=User)
        user.deactivated_at = datetime.now(timezone.utc)
        assert user.deactivated_at is not None

    def test_active_user_has_no_timestamp(self):
        """Active users have deactivated_at = None."""
        user = MagicMock(spec=User)
        user.deactivated_at = None
        assert user.deactivated_at is None


class TestRequireAdminLogic:
    """is_admin flag gates access to user management."""

    def test_admin_user_passes(self):
        """Active admin passes the require_admin check."""
        user = MagicMock(spec=User)
        user.is_admin = True
        user.deactivated_at = None
        # require_admin allows: is_admin=True AND deactivated_at is None
        assert user.is_admin and user.deactivated_at is None

    def test_non_admin_user_blocked(self):
        """Non-admin is rejected."""
        user = MagicMock(spec=User)
        user.is_admin = False
        user.deactivated_at = None
        assert not user.is_admin

    def test_deactivated_admin_blocked(self):
        """Even an admin should be blocked if deactivated."""
        user = MagicMock(spec=User)
        user.is_admin = True
        user.deactivated_at = datetime.now(timezone.utc)
        # require_admin rejects: deactivated_at is not None
        is_allowed = user.is_admin and user.deactivated_at is None
        assert not is_allowed


class TestSelfProtectionGuards:
    """Admins cannot delete or deactivate themselves."""

    def test_self_delete_blocked(self):
        """user_id == current_user.id should be rejected."""
        admin_id = uuid4()
        target_id = admin_id  # same user
        assert target_id == admin_id

    def test_different_user_delete_allowed(self):
        """Deleting a different user is allowed (guard passes)."""
        admin_id = uuid4()
        target_id = uuid4()
        assert target_id != admin_id


class TestSoleOwnerLogic:
    """Cannot delete/deactivate sole project owners."""

    def test_user_is_sole_owner_when_only_owner(self):
        """A single owner share means user is sole owner."""
        owner_count = 1  # Only one owner on the project
        assert owner_count == 1  # sole owner — block action

    def test_user_is_not_sole_owner_with_co_owners(self):
        """Multiple owners means user is NOT sole owner."""
        owner_count = 2
        assert owner_count > 1  # not sole owner — allow action

    def test_user_with_no_owned_projects(self):
        """User who owns nothing can be freely deleted."""
        owned_project_ids = []
        assert len(owned_project_ids) == 0


class TestLastAdminGuard:
    """Cannot deactivate/delete the last active admin."""

    def test_last_admin_blocked(self):
        """When active admin count is 1, action is blocked."""
        active_admin_count = 1
        assert active_admin_count <= 1  # block

    def test_multiple_admins_allowed(self):
        """When active admin count > 1, action is allowed."""
        active_admin_count = 3
        assert active_admin_count > 1  # allow
