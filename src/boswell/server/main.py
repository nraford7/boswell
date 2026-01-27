# src/boswell/server/main.py
"""FastAPI application for Boswell server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.staticfiles import StaticFiles

from boswell.server.database import close_db, get_session_context, init_db

logger = logging.getLogger(__name__)

# Compute template directory relative to this file
_TEMPLATE_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup - run any pending migrations
    try:
        async with get_session_context() as db:
            # Check if topic column needs migration from varchar to text
            result = await db.execute(text("""
                SELECT data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = 'interviews' AND column_name = 'topic'
            """))
            row = result.fetchone()
            if row and row[1] is not None:  # character_maximum_length is set (varchar)
                await db.execute(text(
                    "ALTER TABLE interviews ALTER COLUMN topic TYPE TEXT"
                ))
                await db.commit()
                logger.info("Applied migration: topic column to TEXT")
    except Exception as e:
        logger.warning(f"Migration check failed: {e}")

    yield
    # Shutdown
    await close_db()


app = FastAPI(
    title="Boswell",
    description="AI Research Interviewer",
    version="0.1.0",
    lifespan=lifespan,
)

# Templates
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# Import and include routers after app is created to avoid circular imports
from boswell.server.routes import admin, auth, guest  # noqa: E402

app.include_router(auth.router, prefix="/admin")
app.include_router(admin.router)
app.include_router(guest.router)  # No prefix - routes start with /i/

# Mount static files for room-ui
app.mount("/static", StaticFiles(directory=str(_TEMPLATE_DIR.parent / "static")), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {"message": "Boswell API", "docs": "/docs"}
