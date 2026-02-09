"""Integration tests for worker claim and job queue semantics.

These tests require a running PostgreSQL database.
Skip if DATABASE_URL is not set.
"""

import asyncio
import os
from uuid import uuid4

import pytest

# Skip all tests if no database
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set"
)


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_wins():
    """Two workers claiming simultaneously should result in exactly one claim."""
    # Create a started interview
    # Run two claim_next_interview calls concurrently
    # Assert exactly one returns the interview
    pass


@pytest.mark.asyncio
async def test_failed_interview_not_reclaimed_before_backoff():
    """A failed interview should not be claimable before its backoff period."""
    pass


@pytest.mark.asyncio
async def test_jobs_worker_processes_analysis_after_completion():
    """generate_analysis job should be processed after interview completion."""
    pass
