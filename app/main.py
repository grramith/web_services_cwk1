"""Sonic Insights Hybrid API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.middleware import RequestLoggingMiddleware, RateLimitMiddleware
from app.routes import ai, analytics, auth, catalog, events, feedback, imports

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
    {"name": "Auth", "description": "Register, login, and view your profile."},
    {"name": "Ingestion", "description": "One-time imports: pass a Spotify OAuth token to pull your listening history, or trigger the Kaggle catalog download. All other endpoints read from the stored results."},
    {"name": "Listening Events", "description": "Your imported Spotify history: browse, manually record, update, and delete listening events stored from your Spotify import."},
    {"name": "Analytics", "description": "Computed from your Spotify history: listening fingerprint, mood breakdown, taste drift over time, and listening highlights."},
    {"name": "AI", "description": "Powered by your Spotify fingerprint: explainable hybrid recommendations matched against the catalog, what-if scenarios, grounded insight generation, and self-critique."},
    {"name": "Catalog", "description": "Kaggle dataset (1926 tracks): search and filter, cosine similarity search, mood quadrant map, audio feature DNA statistics, and natural language mood recommendations."},
    {"name": "Feedback", "description": "Your ratings on catalog tracks: create, view, update, and delete likes, dislikes, saves, and skips."},
    {"name": "System", "description": "API health check."},
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
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth.router, prefix=API)
app.include_router(imports.router, prefix=API)
app.include_router(events.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(ai.router, prefix=API)
app.include_router(catalog.router, prefix=API)
app.include_router(feedback.router, prefix=API)


@app.get("/health", tags=["System"], summary="API health check")
def health():
    return {"status": "healthy", "version": "3.0.0"}