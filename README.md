# Sonic Insights Hybrid API

> COMP3011 — Web Services and Web Data | University of Leeds

A hybrid music-intelligence REST API that combines real Spotify listening behaviour with a public Kaggle discovery catalog to deliver explainable recommendations, a persisted listening fingerprint, and a fully compliant Model Context Protocol (MCP) server.

**API Documentation:** [api_documentation.pdf](api_documentation.pdf)

| Resource | URL |
|---|---|
| Live API | https://web-production-f9a4.up.railway.app/ |
| Swagger UI | https://web-production-f9a4.up.railway.app/docs |
| ReDoc | https://web-production-f9a4.up.railway.app/redoc |
| Health Dashboard | https://web-production-f9a4.up.railway.app/health/detailed |
| GitHub | https://github.com/grramith/web_services_cwk1 |

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Running the API](#running-the-api)
- [API Documentation](#api-documentation)
- [Endpoint Reference](#endpoint-reference)
- [Testing](#testing)
- [Version Control](#version-control)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)

---

## Overview

Sonic Insights solves the cold-start problem in music recommendation by fusing two data sources:

- **Spotify import pipeline** — ingests a user's top tracks, recently played, and saved library with full audio feature enrichment (energy, valence, danceability, tempo, etc.)
- **Kaggle discovery catalog** — a public dataset imported via `kagglehub` that acts as a broader recommendation pool beyond the user's existing listening history

The system then computes a **listening fingerprint** (a persisted psychoacoustic profile of the user), detects **recent taste drift**, and generates **explainable hybrid recommendations** with per-track `fit_score`, `novelty_score`, and a natural language `why` explanation. All AI endpoints follow a **deterministic-first** philosophy: analytics are fully computed before an LLM is optionally called for enrichment.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Application                  │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│   Auth   │ Catalog  │Listening │ Feedback │  Analytics  │
│  Routes  │  Routes  │  Events  │   CRUD   │   Routes    │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│                  Hybrid Service Layer                    │
│   Fingerprint · Recommendations · Insights · Critique   │
├─────────────────────────────────────────────────────────┤
│              SQLAlchemy ORM + SQLite / PostgreSQL        │
├─────────────────────────────────────────────────────────┤
│   Spotify Web API      │   Kaggle Dataset   │   Groq    │
└────────────────────────┴────────────────────┴───────────┘
```

Key design decisions:

- **Modular routers** — each domain (`auth`, `catalog`, `feedback`, `analytics`, `ai`, `mcp`) is a self-contained FastAPI router mounted under `/api/v1`
- **Service layer isolation** — all business logic lives in `app/services/hybrid.py`, keeping routes thin
- **JWT token rotation** — logout blacklists the access token JTI; refresh endpoint rotates refresh tokens immediately after use
- **MCP-compatible** — exposes a `/mcp/manifest` + `/mcp/invoke` interface so the API can be used as a tool by Claude Desktop, Cursor, and any MCP-enabled AI client
- **SSE live stream** — `/listening-events/stream` pushes real-time events via Server-Sent Events with per-poll session management

---

## Tech Stack

| Layer | Technology | Justification |
|---|---|---|
| Framework | FastAPI | Async-native, automatic OpenAPI docs, Pydantic v2 validation |
| Database | SQLAlchemy + SQLite | Simple local setup; schema-compatible with PostgreSQL for production |
| Auth | python-jose + passlib (bcrypt) | Industry-standard JWT with token blacklisting |
| HTTP client | httpx (async) | Non-blocking; replaces `requests` to avoid event loop blocking |
| Retry logic | tenacity | Exponential backoff on transient LLM/network failures |
| AI enrichment | Groq llama-3.3-70b-versatile | Free-tier LLM via Groq API; all endpoints degrade gracefully if key is absent |
| Data ingestion | kagglehub + pandas | Direct Kaggle dataset import with zero manual download |
| Testing | pytest + pytest-cov | In-memory SQLite via StaticPool; 118 tests, ~56% coverage |

---

## Setup

### Prerequisites

- Python 3.12+
- pip

### Install

```bash
# 1. Clone the repository
git clone https://github.com/grramith/web_services_cwk1.git
cd web_services_cwk1

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in the `project/` root directory:

```env
# Required
SECRET_KEY=your-secret-key-change-this-in-production
DATABASE_URL=sqlite:///./sonic_insights.db

# Optional — AI endpoints degrade gracefully without this
# Uses Groq API (free tier) — get key at console.groq.com
OPENAI_API_KEY=gsk_your_groq_key_here

# Defaults (no need to set unless changing)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

> **Note:** The `OPENAI_API_KEY` field accepts a Groq API key. Get a free key at console.groq.com. If not set, all AI endpoints return deterministic output.

---

## Running the API

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`

---

## API Documentation

Interactive documentation is auto-generated by FastAPI:

| Interface | URL |
|---|---|
| Swagger UI | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| OpenAPI JSON | http://127.0.0.1:8000/api/v1/openapi.json |

> **Submitted PDF documentation** is available in the repository root as `api_documentation.pdf`

---

## Endpoint Reference

### Auth — `/api/v1/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/register` | No | Register a new user account |
| POST | `/login` | No | Obtain access + refresh token pair |
| POST | `/refresh` | No | Rotate refresh token, get new pair |
| POST | `/logout` | ✓ | Blacklist current access token |
| GET | `/me` | ✓ | Get current user profile |

### Listening Events — `/api/v1/listening-events`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/` | ✓ | Record a new listening event |
| GET | `/` | ✓ | List events (paginated, date filterable) |
| GET | `/stream` | ✓ | Live SSE stream of new events |
| GET | `/{id}` | ✓ | Get a single event |
| PATCH | `/{id}` | ✓ | Update a listening event |
| DELETE | `/{id}` | ✓ | Delete a listening event |

### Data Import — `/api/v1/imports`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/spotify` | ✓ | Import from Spotify (top tracks, recently played, saved) |
| POST | `/catalog` | ✓ | Import public Kaggle discovery catalog |
| GET | `/jobs` | ✓ | List recent import jobs |
| GET | `/jobs/{id}` | ✓ | Check import job status |

### Feedback CRUD — `/api/v1/feedback`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/` | ✓ | Create feedback on a catalog track (`like/dislike/save/skip`) |
| GET | `/` | ✓ | List your feedback (filterable by rating) |
| PATCH | `/{id}` | ✓ | Update a feedback record |
| DELETE | `/{id}` | ✓ | Delete a feedback record |

### Analytics — `/api/v1/analytics`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/overview` | ✓ | High-level hybrid listening summary |
| GET | `/fingerprint` | ✓ | Full psychoacoustic listening fingerprint |
| GET | `/highlights` | ✓ | Compact top artist/genre/mood snapshot |
| GET | `/changes/recent` | ✓ | Detect recent taste drift vs previous 30 days |

### Catalog — `/api/v1/catalog`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | ✓ | Search catalog (name, artist, genre, energy, valence filters) |
| GET | `/mood-map` | ✓ | Classify all tracks into mood quadrants |
| GET | `/audio-dna` | ✓ | Full statistical feature distribution across catalog |
| GET | `/genres` | ✓ | Genre breakdown with audio feature averages |
| POST | `/recommend-by-mood` | ✓ | NLP mood description → cosine similarity recommendations |
| GET | `/{id}` | ✓ | Get a single catalog track |
| GET | `/{id}/similar` | ✓ | Find similar tracks via 8D cosine similarity |

### AI — `/api/v1/ai`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/insights` | ✓ | Generate and store a hybrid listening insight |
| POST | `/insights/{id}/critique` | ✓ | Self-critique a stored insight for grounding and specificity |
| POST | `/recommendations/explain` | ✓ | Explainable hybrid recommendations with fingerprint grounding |
| POST | `/recommendations/what-if` | ✓ | Counterfactual scenario recommendations |

### MCP Server — `/api/v1/mcp`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/manifest` | No | List all available MCP tools and schemas |
| POST | `/invoke` | ✓ | Execute a named MCP tool |

Available tools: `search_catalog`, `recommend_by_mood`, `get_listening_summary`, `get_catalog_mood_map`, `find_similar_tracks`

### System

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | No | Basic health check |
| GET | `/health/detailed` | No | DB stats, table counts, last import |

---

## Testing

### Run the test suite

```bash
# Run all tests with coverage report
pytest tests/ -v --cov=app --cov-report=term-missing

# Run only the v3 test file
pytest tests/test_api.py -v

# Stop on first failure
pytest tests/ -v -x

# Run a single test class
pytest tests/test_api.py::TestFeedbackCRUD -v
```

### Test architecture

- **Database isolation** — every test uses a fresh in-memory SQLite database via `StaticPool` and an `autouse` `reset_db` fixture
- **LLM mocking** — `tests/conftest.py` patches `_llm_chat` with an `AsyncMock` returning `None` so no real OpenAI calls are made and tests are fully hermetic
- **Two test files**:
  - `tests/test_api.py` — original suite covering auth, events CRUD, and core analytics
  - `tests/test_api.py` — full test suite: auth, feedback CRUD, analytics, catalog, AI hybrid, MCP, end-to-end workflows (121 tests)

### Coverage summary

```
app/routes/feedback.py      100%
app/routes/ai.py            100%
app/schemas.py              100%
app/auth.py                  97%
app/routes/analytics.py      95%
app/routes/catalog.py        93%
app/routes/mcp.py            90%
app/services/hybrid.py       86%
```

### End-to-end workflow tests

Four workflow tests verify the system works as a coherent whole:

- **Full discovery workflow** — register → listen → fingerprint → import catalog → get recommendations → leave feedback
- **Token rotation security chain** — login → refresh → old token rejected → logout → new token rejected
- **Catalog to MCP pipeline** — seed catalog → search via REST → find same track via MCP, verify consistent IDs
- **Feedback affects recommendations** — dislike tracks → verify they are excluded from recommendation results

---

## Version Control

Commit history follows the Conventional Commits standard:

```
feat:     new feature or endpoint
fix:      bug fix
test:     test additions or corrections
refactor: code restructure without behaviour change
docs:     documentation only
```

---

## Project Structure

```
project/
├── app/
│   ├── main.py              # FastAPI app, middleware, router registration
│   ├── config.py            # Pydantic settings from .env
│   ├── database.py          # SQLAlchemy engine and session
│   ├── auth.py              # JWT creation, verification, blacklisting
│   ├── middleware.py        # Request logging + IP rate limiting
│   ├── models.py            # SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── routes/
│   │   ├── auth.py          # Register, login, refresh, logout, me
│   │   ├── events.py        # Listening events CRUD + SSE
│   │   ├── imports.py       # Spotify + catalog import pipeline
│   │   ├── feedback.py      # TrackFeedback CRUD
│   │   ├── analytics.py     # Overview, fingerprint, highlights, changes
│   │   ├── catalog.py       # Search, mood-map, audio-dna, similar, recommend
│   │   ├── ai.py            # Hybrid recommendations + insight critique
│   │   └── mcp.py           # MCP manifest + invoke
│   └── services/
│       ├── hybrid.py        # Core analytics and AI service layer
│       └── catalog_import.py # Kaggle dataset ingestion
├── tests/
│   ├── conftest.py          # Shared fixtures (LLM mock)
│   ├── test_api.py          # Original test suite
│   └── test_api_v3_missing.py # Full v3 coverage (121 tests)
├── data/
│   └── seed_features.py     # Development data seeder
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Deployment

The API is deployed on Railway at https://web-production-f9a4.up.railway.app

To deploy your own instance:

1. Create a Railway account at railway.app
2. Connect your GitHub repository
3. Set environment variables: `SECRET_KEY`, `DATABASE_URL`, `OPENAI_API_KEY`
4. Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## Known Limitations

- **SQLite in development** — the default `DATABASE_URL` uses SQLite. For production or multi-worker deployment, switch to PostgreSQL by updating `DATABASE_URL` in `.env`. The ORM is fully compatible.
- **In-memory rate limiter** — `RateLimitMiddleware` stores hit counts in a Python dictionary. This resets on restart and is not shared across multiple workers. A Redis-backed implementation would be required for horizontal scaling.
- **Synchronous Spotify import** — the `/imports/spotify` endpoint runs synchronously. A production implementation would use a background task queue (Celery, ARQ).
- **Spotify import track limit** — the Spotify Web API caps top tracks at 50 per time range (short, medium, long term) and recently played at 50 items, giving a maximum of approximately 150 tracks per import. The `synthesise_history` flag generates plausible historical events from top-track affinity data to supplement the real import. A production solution would use the Spotify extended history export.
- **Kaggle credentials** — `POST /imports/catalog` requires a `~/.kaggle/kaggle.json` credentials file on the server. Without it the endpoint returns `500`.
- **LLM enrichment is optional** — the `OPENAI_API_KEY` field accepts a Groq API key (get one free at console.groq.com). If not set, all AI endpoints return deterministic template-based output. No endpoint fails without the key.
- **Swagger UI and SSE** — the `/listening-events/stream` SSE endpoint cannot be tested interactively through Swagger UI because Swagger closes the HTTP connection after the first response. This is a known limitation of OpenAPI tooling. The endpoint works correctly via curl or any EventSource-capable client.
