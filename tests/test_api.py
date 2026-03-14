"""
Test suite for Sonic Insights Hybrid API.
Tests only the endpoints that exist in the deployed API.
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

ENGINE = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)


def _override():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    yield
    Base.metadata.drop_all(bind=ENGINE)


# ── helpers ───────────────────────────────────────────────────────────────────

def register(username="testuser", email="test@test.com", password="TestPass123"):
    r = client.post("/api/v1/auth/register", json={
        "username": username, "email": email, "password": password,
    })
    assert r.status_code == 201
    return r.json()


def login(username="testuser", password="TestPass123"):
    r = client.post("/api/v1/auth/login", data={
        "username": username, "password": password,
    })
    assert r.status_code == 200
    return r.json()["access_token"]


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def seed_track(db_session, **kw):
    from app.models import Track
    defaults = dict(
        title="Test Song", artist="Test Artist", genre="pop",
        energy=0.7, valence=0.6, danceability=0.8,
        acousticness=0.2, instrumentalness=0.0,
        speechiness=0.05, liveness=0.15, loudness=-5.0, tempo=120.0,
    )
    defaults.update(kw)
    t = Track(**defaults)
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


def get_db_session():
    return Session()


def seed_listening_events(token, tracks, n_per_track=3):
    for t in tracks:
        for i in range(n_per_track):
            ts = (datetime.now(timezone.utc) - timedelta(days=i * 10)).isoformat()
            r = client.post("/api/v1/listening-events", json={
                "track_id": t.id,
                "listened_at": ts,
                "duration_listened_ms": 200000,
            }, headers=hdr(token))
            assert r.status_code == 201


def seed_catalog_track(db_session, **kw):
    from app.models import CatalogTrack
    defaults = dict(
        external_id="test-ext-001",
        name="Catalog Song",
        artist="Catalog Artist",
        genre="pop",
        energy=0.7,
        valence=0.6,
        danceability=0.8,
        source_dataset="test/dataset",
        metadata_json={},
    )
    defaults.update(kw)
    t = CatalogTrack(**defaults)
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


# =====================================================================
# AUTH
# =====================================================================
class TestAuth:
    def test_register(self):
        u = register()
        assert u["username"] == "testuser"

    def test_register_duplicate_username(self):
        register()
        r = client.post("/api/v1/auth/register", json={
            "username": "testuser", "email": "other@x.com",
            "password": "TestPass123",
        })
        assert r.status_code == 409

    def test_register_short_password(self):
        r = client.post("/api/v1/auth/register", json={
            "username": "abc", "email": "a@b.com", "password": "short",
        })
        assert r.status_code == 422

    def test_login(self):
        register()
        token = login()
        assert len(token) > 10

    def test_login_wrong_password(self):
        register()
        r = client.post("/api/v1/auth/login",
                        data={"username": "testuser", "password": "wrong"})
        assert r.status_code == 401

    def test_get_me(self):
        register()
        token = login()
        r = client.get("/api/v1/auth/me", headers=hdr(token))
        assert r.json()["username"] == "testuser"


# =====================================================================
# IMPORT JOBS
# =====================================================================
class TestImportJobs:
    def test_list_jobs_empty(self):
        register()
        token = login()
        r = client.get("/api/v1/imports/jobs", headers=hdr(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_get_job_not_found(self):
        register()
        token = login()
        r = client.get("/api/v1/imports/jobs/nonexistent", headers=hdr(token))
        assert r.status_code == 404

    def test_start_import_bad_token(self):
        register()
        token = login()
        r = client.post("/api/v1/imports/spotify", json={
            "spotify_token": "invalid", "time_range": "medium_term",
        }, headers=hdr(token))
        assert r.status_code == 401


# =====================================================================
# LISTENING EVENTS
# =====================================================================
class TestEvents:
    def test_create(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        r = client.post("/api/v1/listening-events", json={
            "track_id": t.id, "duration_listened_ms": 180000,
        }, headers=hdr(token))
        assert r.status_code == 201
        assert r.json()["track_id"] == t.id

    def test_create_nonexistent_track(self):
        register()
        token = login()
        r = client.post("/api/v1/listening-events", json={
            "track_id": 9999,
        }, headers=hdr(token))
        assert r.status_code == 404

    def test_list(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        for _ in range(3):
            client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        r = client.get("/api/v1/listening-events", headers=hdr(token))
        assert r.json()["total"] == 3

    def test_list_pagination(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        for _ in range(5):
            client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        r = client.get("/api/v1/listening-events?limit=2&offset=0",
                       headers=hdr(token))
        assert len(r.json()["items"]) == 2
        assert r.json()["total"] == 5

    def test_get_by_id(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        r = client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        eid = r.json()["id"]
        r2 = client.get(f"/api/v1/listening-events/{eid}", headers=hdr(token))
        assert r2.status_code == 200
        assert r2.json()["id"] == eid

    def test_update(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        r = client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        eid = r.json()["id"]
        r2 = client.patch(f"/api/v1/listening-events/{eid}",
                          json={"duration_listened_ms": 300000},
                          headers=hdr(token))
        assert r2.json()["duration_listened_ms"] == 300000

    def test_delete(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        r = client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        eid = r.json()["id"]
        assert client.delete(f"/api/v1/listening-events/{eid}",
                             headers=hdr(token)).status_code == 204

    def test_privacy_scope(self):
        register("u1", "u1@t.com")
        register("u2", "u2@t.com")
        t1 = login("u1")
        t2 = login("u2")
        db = get_db_session()
        t = seed_track(db)
        db.close()
        r = client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(t1))
        eid = r.json()["id"]
        r2 = client.get(f"/api/v1/listening-events/{eid}", headers=hdr(t2))
        assert r2.status_code == 404


# =====================================================================
# CATALOG
# =====================================================================
class TestCatalog:
    def test_search_empty(self):
        register()
        token = login()
        r = client.get("/api/v1/catalog", headers=hdr(token))
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    def test_search_returns_tracks(self):
        register()
        token = login()
        db = get_db_session()
        seed_catalog_track(db, external_id="c1", name="Blinding Lights", artist="The Weeknd")
        seed_catalog_track(db, external_id="c2", name="Shape of You", artist="Ed Sheeran")
        db.close()
        r = client.get("/api/v1/catalog", headers=hdr(token))
        assert r.json()["total"] == 2

    def test_search_by_query(self):
        register()
        token = login()
        db = get_db_session()
        seed_catalog_track(db, external_id="c1", name="Blinding Lights", artist="The Weeknd")
        seed_catalog_track(db, external_id="c2", name="Shape of You", artist="Ed Sheeran")
        db.close()
        r = client.get("/api/v1/catalog?q=Blinding", headers=hdr(token))
        assert r.json()["total"] == 1
        assert r.json()["items"][0]["name"] == "Blinding Lights"

    def test_get_by_id(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db, external_id="c1", name="Blinding Lights", artist="The Weeknd")
        db.close()
        r = client.get(f"/api/v1/catalog/{ct.id}", headers=hdr(token))
        assert r.status_code == 200
        assert r.json()["name"] == "Blinding Lights"

    def test_get_by_id_not_found(self):
        register()
        token = login()
        r = client.get("/api/v1/catalog/9999", headers=hdr(token))
        assert r.status_code == 404

    def test_similar_tracks(self):
        register()
        token = login()
        db = get_db_session()
        ct1 = seed_catalog_track(db, external_id="c1", name="Track A", artist="Artist A",
                                  energy=0.7, valence=0.6)
        seed_catalog_track(db, external_id="c2", name="Track B", artist="Artist B",
                           energy=0.75, valence=0.65)
        seed_catalog_track(db, external_id="c3", name="Track C", artist="Artist C",
                           energy=0.1, valence=0.1)
        db.close()
        r = client.get(f"/api/v1/catalog/{ct1.id}/similar?limit=5", headers=hdr(token))
        assert r.status_code == 200
        assert "results" in r.json()
        assert r.json()["seed_track_id"] == ct1.id


# =====================================================================
# FEEDBACK
# =====================================================================
class TestFeedback:
    def test_create_feedback(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db)
        db.close()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": ct.id, "rating": "like", "note": "great track",
        }, headers=hdr(token))
        assert r.status_code == 201
        assert r.json()["rating"] == "like"

    def test_list_feedback(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db)
        db.close()
        client.post("/api/v1/feedback", json={
            "catalog_track_id": ct.id, "rating": "like",
        }, headers=hdr(token))
        r = client.get("/api/v1/feedback", headers=hdr(token))
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_update_feedback(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db)
        db.close()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": ct.id, "rating": "like",
        }, headers=hdr(token))
        fid = r.json()["id"]
        r2 = client.patch(f"/api/v1/feedback/{fid}",
                          json={"rating": "dislike"}, headers=hdr(token))
        assert r2.json()["rating"] == "dislike"

    def test_delete_feedback(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db)
        db.close()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": ct.id, "rating": "like",
        }, headers=hdr(token))
        fid = r.json()["id"]
        r2 = client.delete(f"/api/v1/feedback/{fid}", headers=hdr(token))
        assert r2.status_code == 200

    def test_feedback_invalid_rating(self):
        register()
        token = login()
        db = get_db_session()
        ct = seed_catalog_track(db)
        db.close()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": ct.id, "rating": "invalid",
        }, headers=hdr(token))
        assert r.status_code == 422

    def test_feedback_track_not_found(self):
        register()
        token = login()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": 9999, "rating": "like",
        }, headers=hdr(token))
        assert r.status_code == 404


# =====================================================================
# ANALYTICS
# =====================================================================
class TestAnalytics:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Pop Hit", genre="pop", energy=0.8, valence=0.7),
            seed_track(db, title="Rock Jam", genre="rock", energy=0.9, valence=0.3),
            seed_track(db, title="Jazz Chill", genre="jazz", energy=0.3, valence=0.6),
        ]
        db.close()
        seed_listening_events(token, tracks, n_per_track=2)
        return token

    def test_overview(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/overview", headers=hdr(token))
        assert r.status_code == 200
        d = r.json()
        assert "total_events" in d or "user_id" in d

    def test_overview_requires_auth(self):
        r = client.get("/api/v1/analytics/overview")
        assert r.status_code == 401

    def test_fingerprint(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/fingerprint", headers=hdr(token))
        assert r.status_code == 200
        assert "fingerprint_label" in r.json()

    def test_highlights(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/highlights", headers=hdr(token))
        assert r.status_code == 200
        assert "novelty_ratio" in r.json()

    def test_recent_changes(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/changes/recent", headers=hdr(token))
        assert r.status_code == 200
        assert "fingerprint_shift" in r.json()

    def test_genres_empty(self):
        register()
        token = login()
        r = client.get("/api/v1/analytics/genres", headers=hdr(token))
        assert r.status_code == 200
        assert "genres" in r.json()


# =====================================================================
# AI
# =====================================================================
class TestAI:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Pop", genre="pop", energy=0.8, valence=0.7),
            seed_track(db, title="Rock", genre="rock", energy=0.9, valence=0.3),
        ]
        db.close()
        seed_listening_events(token, tracks, n_per_track=3)
        return token

    def _seed_with_catalog(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Pop", genre="pop", energy=0.8, valence=0.7),
            seed_track(db, title="Rock", genre="rock", energy=0.9, valence=0.3),
        ]
        seed_catalog_track(db, external_id="c1", name="Catalog Track 1",
                           artist="Artist A", genre="pop")
        seed_catalog_track(db, external_id="c2", name="Catalog Track 2",
                           artist="Artist B", genre="rock")
        db.close()
        seed_listening_events(token, tracks, n_per_track=3)
        return token

    def test_recommendations_explain(self):
        token = self._seed_with_catalog()
        r = client.post("/api/v1/ai/recommendations/explain", json={
            "context": "study session",
            "strategy": "balanced",
            "max_tracks": 5,
        }, headers=hdr(token))
        assert r.status_code == 200
        assert "recommendations" in r.json()
        assert "fingerprint_label" in r.json()

    def test_recommendations_what_if(self):
        token = self._seed_with_catalog()
        r = client.post("/api/v1/ai/recommendations/what-if", json={
            "scenario": "I want to discover new music",
            "max_tracks": 5,
        }, headers=hdr(token))
        assert r.status_code == 200
        assert "recommendations" in r.json()

    def test_generate_insight(self):
        token = self._seed()
        r = client.post("/api/v1/ai/insights", headers=hdr(token))
        assert r.status_code == 201
        d = r.json()
        assert "insight_text" in d
        assert len(d["insight_text"]) > 10
        assert d["id"] > 0

    def test_list_insights(self):
        token = self._seed()
        client.post("/api/v1/ai/insights", headers=hdr(token))
        client.post("/api/v1/ai/insights", headers=hdr(token))
        r = client.get("/api/v1/ai/insights", headers=hdr(token))
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_critique_insight(self):
        token = self._seed()
        r = client.post("/api/v1/ai/insights", headers=hdr(token))
        iid = r.json()["id"]
        r2 = client.post(f"/api/v1/ai/insights/{iid}/critique", headers=hdr(token))
        assert r2.status_code == 200
        assert "overall_verdict" in r2.json()


# =====================================================================
# HEALTH & OPENAPI
# =====================================================================
class TestSystem:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_openapi_tags(self):
        spec = client.get("/api/v1/openapi.json").json()
        tag_names = [t["name"] for t in spec.get("tags", [])]
        assert "AI" in tag_names
        assert "Analytics" in tag_names
        assert "Auth" in tag_names