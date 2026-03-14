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
    {"name": "Auth", "description": "User registration, login, and profile access."},
    {"name": "Ingestion", "description": "Import your Spotify listening history and the public discovery catalog."},
    {"name": "Listening Events", "description": "Record and manage your personal listening history."},
    {"name": "Analytics", "description": "Listening fingerprint, mood analysis, taste drift, and highlights."},
    {"name": "AI", "description": "Explainable hybrid recommendations, insight generation, and critique."},
    {"name": "Catalog", "description": "Browse, search, and analyse the imported discovery catalog."},
    {"name": "Feedback", "description": "Full CRUD over user feedback on catalog tracks."},
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