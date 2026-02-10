"""Tests for the authorization module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from boswell.server.authorization import (
    get_project_role,
    check_project_access,
    assert_not_last_owner,
)
from boswell.server.models import ProjectRole


@pytest.mark.asyncio
async def test_get_project_role_returns_role():
    """Returns role when user has a share."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.collaborate
    mock_db.execute.return_value = mock_result

    role = await get_project_role(uuid4(), uuid4(), mock_db)
    assert role == ProjectRole.collaborate


@pytest.mark.asyncio
async def test_get_project_role_returns_none():
    """Returns None when no share exists."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    role = await get_project_role(uuid4(), uuid4(), mock_db)
    assert role is None


@pytest.mark.asyncio
async def test_check_access_passes_when_sufficient():
    """Doesn't raise when role >= min_role."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.owner
    mock_db.execute.return_value = mock_result

    result = await check_project_access(uuid4(), uuid4(), ProjectRole.view, mock_db)
    assert result == ProjectRole.owner


@pytest.mark.asyncio
async def test_check_access_404_when_no_access():
    """Raises 404 when no share exists."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(uuid4(), uuid4(), ProjectRole.view, mock_db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_check_access_403_when_insufficient():
    """Raises 403 when role < min_role."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ProjectRole.view
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await check_project_access(uuid4(), uuid4(), ProjectRole.owner, mock_db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_not_last_owner_passes_with_others():
    """Doesn't raise when other owners exist."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 2  # 2 other owners
    mock_db.execute.return_value = mock_result

    await assert_not_last_owner(uuid4(), uuid4(), mock_db)  # Should not raise


@pytest.mark.asyncio
async def test_assert_not_last_owner_raises_when_last():
    """Raises 400 when user is the only owner."""
    from fastapi import HTTPException

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0  # No other owners
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await assert_not_last_owner(uuid4(), uuid4(), mock_db)
    assert exc_info.value.status_code == 400
