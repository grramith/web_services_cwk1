"""Sonic Insights Hybrid API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.middleware import RequestLoggingMiddleware, RateLimitMiddleware
from app.routes import ai, analytics, auth, catalog, events, feedback, imports, mcp
from sqlalchemy import text
from app.database import SessionLocal
from fastapi.responses import HTMLResponse
import os


API = "/api/v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


openapi_tags = [
    {"name": "Auth", "description": "User registration, login, and profile access."},
    {"name": "Ingestion", "description": "Import Spotify listening context and the public discovery catalog."},
    {"name": "Listening Events", "description": "Record and manage your listening history."}, {"name": "Catalog", "description": "Browse and search the imported discovery catalog."}, {"name": "Feedback", "description": "Full CRUD over user feedback on catalog tracks."},
    {"name": "Analytics", "description": "Focused hybrid analytics including overview, fingerprint, highlights, and recent change detection."},
    {"name": "AI", "description": "Explainable hybrid recommendations, grounded insight generation, and critique."},
    {"name": "MCP", "description": "Model Context Protocol server — exposes Sonic Insights tools for AI client integration (Claude Desktop, Cursor, etc.)."},
    {"name": "System", "description": "Operational health endpoints."},
]

app = FastAPI(
    title="Sonic Insights Hybrid API",
    version="3.0.0",
    description=(
        "A hybrid music intelligence API that combines Spotify user behaviour with a public discovery catalog. "
        "It computes a listening fingerprint, detects recent taste drift, supports explainable recommendations, "
        "and critiques its own generated insights."
    ),
    openapi_tags=openapi_tags,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{API}/openapi.json",
)

app.add_middleware(RateLimitMiddleware, max_requests=1000, window_seconds=60)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth.router, prefix=API)
app.include_router(events.router, prefix=API)
app.include_router(imports.router, prefix=API)
app.include_router(feedback.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(catalog.router, prefix=API)
app.include_router(ai.router, prefix=API)
app.include_router(mcp.router, prefix=API)


@app.get("/health", tags=["System"], summary="API health check")
def health():
    return {"status": "healthy", "version": "3.0.0"}


@app.get("/health/detailed", tags=["System"], summary="Detailed system health with database statistics")
def health_detailed():
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        stats = {}
        for table, label in [
            ("catalog_tracks", "catalog_tracks"),
            ("tracks", "spotify_tracks"),
            ("listening_events", "listening_events"),
            ("users", "users"),
            ("track_feedback", "feedback_records"),
            ("insights", "insights"),
        ]:
            try:
                stats[label] = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            except Exception:
                stats[label] = 0

        from app.models import ImportJob
        last_import = db.query(ImportJob).order_by(
            ImportJob.started_at.desc()).first()

        return {
            "status": "healthy",
            "version": "3.0.0",
            "database": "connected",
            "statistics": stats,
            "last_import": {
                "source": last_import.source if last_import else None,
                "status": last_import.status if last_import else None,
                "started_at": last_import.started_at.isoformat() if last_import else None,
            },
        }
    finally:
        db.close()


@app.get("/", include_in_schema=False)
def root():
    html_path = os.path.join(os.path.dirname(__file__), "static", "landing.html")
    with open(html_path, "r") as f:
        return HTMLResponse(f.read())