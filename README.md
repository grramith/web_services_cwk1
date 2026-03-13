# Sonic Insights Hybrid API

A hybrid music-intelligence API for COMP3011 that combines:
- **Spotify listening context** for real user behaviour
- **A public Kaggle music dataset** as a broader discovery catalog
- **Explainable AI** for recommendations, insight generation, and critique

## Core capabilities
- Spotify import with audio-feature enrichment
- Catalog import from Kaggle via `kagglehub`
- Persisted user listening fingerprint
- Focused analytics: overview, fingerprint, highlights, recent taste drift
- Full CRUD for catalog track feedback
- Explainable hybrid recommendations
- Grounded insight generation and critique

## Main endpoints
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/imports/spotify`
- `POST /api/v1/imports/catalog`
- `POST /api/v1/feedback`
- `GET /api/v1/feedback`
- `PATCH /api/v1/feedback/{feedback_id}`
- `DELETE /api/v1/feedback/{feedback_id}`
- `GET /api/v1/analytics/overview`
- `GET /api/v1/analytics/fingerprint`
- `GET /api/v1/analytics/changes/recent`
- `GET /api/v1/analytics/highlights`
- `POST /api/v1/ai/recommendations/explain`
- `POST /api/v1/ai/recommendations/what-if`
- `POST /api/v1/ai/insights`
- `POST /api/v1/ai/insights/{insight_id}/critique`

## Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Environment
Create `.env` in the project root.

```env
OPENAI_API_KEY=your_openai_key
DATABASE_URL=sqlite:///./sonic_insights.db
SECRET_KEY=change-me
```

## Notes
- `POST /api/v1/imports/catalog` defaults to the dataset slug `ramithgajjala/ramith-top-songs`
- `POST /api/v1/imports/spotify` remains the live-context ingestion path
- AI endpoints remain deterministic-first: analytics are computed first, LLMs are used second for explanation
