# src/boswell/server/main.py
"""FastAPI application for Boswell server."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from boswell.server.database import close_db, init_db

# Compute template directory relative to this file
_TEMPLATE_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup - database is initialized by alembic migrations in start_web.sh
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {"message": "Boswell API", "docs": "/docs"}
