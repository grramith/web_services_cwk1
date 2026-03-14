"""
Comprehensive test suite for Sonic Insights API v2.

Uses SQLite in-memory database with StaticPool.
Each test gets a fresh database via the autouse ``reset_db`` fixture.
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# ── Test database ─────────────────────────────────────────────────────
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


# ── Helpers ───────────────────────────────────────────────────────────
def register(username="testuser", email="test@test.com",
             password="TestPass123"):
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
    """Insert a track directly into the test DB."""
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
    db = Session()
    try:
        return db
    except Exception:
        db.close()
        raise


def seed_events(token, tracks, n_per_track=3, days_spread=90):
    """Create listening events for the given tracks."""
    created = []
    for t in tracks:
        for i in range(n_per_track):
            ts = (datetime.now(timezone.utc)
                  - timedelta(days=days_spread - i * 10)).isoformat()
            r = client.post("/api/v1/listening-events", json={
                "track_id": t.id, "listened_at": ts,
                "duration_listened_ms": 200000,
            }, headers=hdr(token))
            assert r.status_code == 201
            created.append(r.json())
    return created


# =====================================================================
# AUTH (6 tests)
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
# IMPORT JOBS (3 tests — pipeline modelling, no real Spotify)
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
        r = client.get("/api/v1/imports/jobs/nonexistent",
                       headers=hdr(token))
        assert r.status_code == 404

    def test_start_import_bad_token(self):
        register()
        token = login()
        r = client.post("/api/v1/imports/spotify", json={
            "spotify_token": "invalid", "time_range": "medium_term",
        }, headers=hdr(token))
        # Will fail because token is invalid — should return 401
        assert r.status_code == 401


# =====================================================================
# LISTENING EVENTS CRUD (8 tests)
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
        r2 = client.get(f"/api/v1/listening-events/{eid}",
                        headers=hdr(token))
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
        """Events are scoped to the authenticated user."""
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
        # User 2 cannot see User 1's event
        r2 = client.get(f"/api/v1/listening-events/{eid}",
                        headers=hdr(t2))
        assert r2.status_code == 404


# =====================================================================
# ANALYTICS — OVERVIEW (2 tests)
# =====================================================================
class TestOverview:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Pop Hit", genre="pop",
                       energy=0.8, valence=0.7),
            seed_track(db, title="Rock Jam", genre="rock",
                       energy=0.9, valence=0.3),
            seed_track(db, title="Jazz Chill", genre="jazz",
                       energy=0.3, valence=0.6),
        ]
        db.close()
        seed_events(token, tracks, n_per_track=2)
        return token

    def test_overview(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/overview", headers=hdr(token))
        d = r.json()
        assert d["total_events"] == 6
        assert d["unique_tracks"] == 3
        assert d["unique_genres"] == 3
        assert d["dominant_mood"] is not None

    def test_overview_empty(self):
        register()
        token = login()
        r = client.get("/api/v1/analytics/overview", headers=hdr(token))
        assert r.json()["total_events"] == 0


# =====================================================================
# ANALYTICS — TOP (3 tests)
# =====================================================================
class TestTop:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        t1 = seed_track(db, title="Hit", artist="StarArtist",
                        genre="pop")
        t2 = seed_track(db, title="Deep Cut", artist="IndieArtist",
                        genre="indie")
        db.close()
        # Hit played 5 times, Deep Cut 2 times
        for _ in range(5):
            client.post("/api/v1/listening-events",
                        json={"track_id": t1.id}, headers=hdr(token))
        for _ in range(2):
            client.post("/api/v1/listening-events",
                        json={"track_id": t2.id}, headers=hdr(token))
        return token

    def test_top_tracks(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/top?entity=track&k=5",
                       headers=hdr(token))
        items = r.json()["items"]
        assert items[0]["name"] == "Hit"
        assert items[0]["count"] == 5

    def test_top_artists(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/top?entity=artist",
                       headers=hdr(token))
        assert r.json()["items"][0]["name"] == "StarArtist"

    def test_top_genres(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/top?entity=genre",
                       headers=hdr(token))
        assert r.json()["items"][0]["name"] == "pop"


# =====================================================================
# ANALYTICS — HEATMAP (2 tests)
# =====================================================================
class TestHeatmap:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db)
        db.close()
        seed_events(token, [t], n_per_track=5)
        return token

    def test_hourly(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/time-heatmap?bucket=hour",
                       headers=hdr(token))
        assert r.json()["bucket_type"] == "hour"
        assert len(r.json()["cells"]) > 0

    def test_daily(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/time-heatmap?bucket=day",
                       headers=hdr(token))
        assert r.json()["bucket_type"] == "day"


# =====================================================================
# ANALYTICS — TRANSITIONS (2 tests)
# =====================================================================
class TestTransitions:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        t1 = seed_track(db, title="Song A", energy=0.8, valence=0.9)
        t2 = seed_track(db, title="Song B", energy=0.2, valence=0.1)
        db.close()
        # A→B→A→B pattern
        now = datetime.now(timezone.utc)
        for i in range(4):
            tid = t1.id if i % 2 == 0 else t2.id
            ts = (now - timedelta(hours=4 - i)).isoformat()
            client.post("/api/v1/listening-events", json={
                "track_id": tid, "listened_at": ts,
            }, headers=hdr(token))
        return token

    def test_transitions(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/transitions",
                       headers=hdr(token))
        d = r.json()
        assert d["total_transitions"] > 0
        assert len(d["top_transitions"]) > 0

    def test_valence_shift(self):
        token = self._seed()
        r = client.get("/api/v1/analytics/transitions",
                       headers=hdr(token))
        for t in r.json()["top_transitions"]:
            assert "avg_valence_shift" in t


# =====================================================================
# ANALYTICS — NOVELTY (3 tests)
# =====================================================================
class TestNovelty:
    def test_explorer(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [seed_track(db, title=f"T{i}") for i in range(5)]
        db.close()
        # Each track once = high novelty
        for t in tracks:
            client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        r = client.get("/api/v1/analytics/novelty", headers=hdr(token))
        assert r.json()["novelty_ratio"] == 1.0
        assert "Explorer" in r.json()["novelty_label"]

    def test_loyalist(self):
        register()
        token = login()
        db = get_db_session()
        t = seed_track(db, title="OneTrack")
        db.close()
        # Same track 10 times = low novelty
        for _ in range(10):
            client.post("/api/v1/listening-events",
                        json={"track_id": t.id}, headers=hdr(token))
        r = client.get("/api/v1/analytics/novelty", headers=hdr(token))
        assert r.json()["novelty_ratio"] == 0.1
        assert "Loyalist" in r.json()["novelty_label"]

    def test_empty(self):
        register()
        token = login()
        r = client.get("/api/v1/analytics/novelty", headers=hdr(token))
        assert r.json()["novelty_label"] == "No data"


# =====================================================================
# AI INSIGHTS — stored + versioned (4 tests)
# =====================================================================
class TestInsights:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Pop", genre="pop",
                       energy=0.8, valence=0.7),
            seed_track(db, title="Rock", genre="rock",
                       energy=0.9, valence=0.3),
            seed_track(db, title="Jazz", genre="jazz",
                       energy=0.3, valence=0.6),
        ]
        db.close()
        seed_events(token, tracks, n_per_track=3)
        return token

    def test_generate(self):
        token = self._seed()
        r = client.post("/api/v1/analytics/insights",
                        headers=hdr(token))
        assert r.status_code == 201
        d = r.json()
        assert len(d["insight_text"]) > 30
        assert "total_events" in d["data_snapshot"]
        assert len(d["evidence"]) >= 1
        assert d["id"] > 0  # stored in DB

    def test_retrieve(self):
        token = self._seed()
        r = client.post("/api/v1/analytics/insights",
                        headers=hdr(token))
        iid = r.json()["id"]
        r2 = client.get(f"/api/v1/analytics/insights/{iid}",
                        headers=hdr(token))
        assert r2.json()["id"] == iid

    def test_list(self):
        token = self._seed()
        client.post("/api/v1/analytics/insights",
                    headers=hdr(token))
        client.post("/api/v1/analytics/insights",
                    headers=hdr(token))
        r = client.get("/api/v1/analytics/insights",
                       headers=hdr(token))
        assert len(r.json()) == 2

    def test_export_markdown(self):
        token = self._seed()
        r = client.post("/api/v1/analytics/insights",
                        headers=hdr(token))
        iid = r.json()["id"]
        r2 = client.get(
            f"/api/v1/analytics/insights/{iid}/export?format=markdown",
            headers=hdr(token),
        )
        assert r2.status_code == 200
        assert "# Sonic Insights Report" in r2.text


# =====================================================================
# AI QUERY (5 tests)
# =====================================================================
class TestAIQuery:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Blinding Lights",
                       artist="The Weeknd", genre="pop",
                       energy=0.8, valence=0.7),
            seed_track(db, title="Bohemian Rhapsody",
                       artist="Queen", genre="rock",
                       energy=0.4, valence=0.3),
        ]
        db.close()
        seed_events(token, tracks, n_per_track=5)
        return token

    def test_top_query(self):
        token = self._seed()
        r = client.post("/api/v1/ai/query",
                        json={"question": "What is my most played track?"},
                        headers=hdr(token))
        d = r.json()
        assert d["query_type"] == "top"
        assert len(d["results"]) > 0

    def test_mood_query(self):
        token = self._seed()
        r = client.post("/api/v1/ai/query",
                        json={"question": "What mood do I listen to most?"},
                        headers=hdr(token))
        assert r.json()["query_type"] == "mood"

    def test_when_query(self):
        token = self._seed()
        r = client.post("/api/v1/ai/query",
                        json={"question": "When do I listen most?"},
                        headers=hdr(token))
        assert r.json()["query_type"] == "temporal"

    def test_count_query(self):
        token = self._seed()
        r = client.post("/api/v1/ai/query",
                        json={"question": "How many songs have I listened to?"},
                        headers=hdr(token))
        assert r.json()["query_type"] == "count"

    def test_fallback_query(self):
        token = self._seed()
        r = client.post("/api/v1/ai/query",
                        json={"question": "Tell me something random"},
                        headers=hdr(token))
        assert r.json()["query_type"] == "fallback"


# =====================================================================
# AI PLAYLISTS (5 tests)
# =====================================================================
class TestAIPlaylists:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title=f"Happy{i}", genre="pop",
                       energy=0.8, valence=0.8)
            for i in range(5)
        ] + [
            seed_track(db, title=f"Calm{i}", genre="ambient",
                       energy=0.2, valence=0.7)
            for i in range(5)
        ]
        db.close()
        seed_events(token, tracks, n_per_track=2)
        return token

    def test_generate(self):
        token = self._seed()
        r = client.post("/api/v1/ai/playlists", json={
            "mood": "happy", "max_tracks": 5,
        }, headers=hdr(token))
        assert r.status_code == 201
        d = r.json()
        assert len(d["track_ids"]) > 0
        assert d["version"] == 1
        assert d["explanation"] is not None

    def test_get_playlist(self):
        token = self._seed()
        r = client.post("/api/v1/ai/playlists", json={
            "mood": "happy", "max_tracks": 5,
        }, headers=hdr(token))
        pid = r.json()["id"]
        r2 = client.get(f"/api/v1/ai/playlists/{pid}",
                        headers=hdr(token))
        assert r2.json()["id"] == pid

    def test_regenerate(self):
        token = self._seed()
        r = client.post("/api/v1/ai/playlists", json={
            "mood": "happy", "max_tracks": 10,
        }, headers=hdr(token))
        pid = r.json()["id"]
        r2 = client.post(f"/api/v1/ai/playlists/{pid}/regenerate",
                         json={"feedback": "make it more chill and calm"},
                         headers=hdr(token))
        assert r2.json()["version"] >= 2

    def test_feedback(self):
        token = self._seed()
        r = client.post("/api/v1/ai/playlists", json={
            "mood": "happy", "max_tracks": 5,
        }, headers=hdr(token))
        d = r.json()
        pid = d["id"]
        tid = d["track_ids"][0]
        r2 = client.post(f"/api/v1/ai/playlists/{pid}/feedback",
                         json={"track_id": tid, "action": "like"},
                         headers=hdr(token))
        assert r2.status_code == 201
        assert r2.json()["action"] == "like"

    def test_feedback_wrong_track(self):
        token = self._seed()
        r = client.post("/api/v1/ai/playlists", json={
            "mood": "happy", "max_tracks": 5,
        }, headers=hdr(token))
        pid = r.json()["id"]
        r2 = client.post(f"/api/v1/ai/playlists/{pid}/feedback",
                         json={"track_id": 99999, "action": "skip"},
                         headers=hdr(token))
        assert r2.status_code == 400


# =====================================================================
# AI EVAL (3 tests)
# =====================================================================
class TestEval:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="A", genre="pop",
                       energy=0.8, valence=0.7),
            seed_track(db, title="B", genre="rock",
                       energy=0.5, valence=0.3),
        ]
        db.close()
        seed_events(token, tracks, n_per_track=3)
        return token

    def test_eval_scorecard(self):
        token = self._seed()
        r = client.post("/api/v1/analytics/insights",
                        headers=hdr(token))
        iid = r.json()["id"]
        r2 = client.post(f"/api/v1/ai/eval/insights?insight_id={iid}",
                         headers=hdr(token))
        assert r2.status_code == 200
        d = r2.json()
        assert 0 <= d["overall_score"] <= 100
        assert len(d["checks"]) == 4

    def test_eval_schema_check(self):
        token = self._seed()
        r = client.post("/api/v1/analytics/insights",
                        headers=hdr(token))
        iid = r.json()["id"]
        r2 = client.post(f"/api/v1/ai/eval/insights?insight_id={iid}",
                         headers=hdr(token))
        checks = {c["check"]: c for c in r2.json()["checks"]}
        assert checks["schema_validity"]["passed"] is True
        assert checks["value_consistency"]["passed"] is True

    def test_eval_not_found(self):
        register()
        token = login()
        r = client.post("/api/v1/ai/eval/insights?insight_id=9999",
                        headers=hdr(token))
        assert r.status_code == 404


# =====================================================================
# HEALTH
# =====================================================================
class TestHealth:
    def test_health(self):
        assert client.get("/health").json()["status"] == "healthy"


class TestOpenAPIAndAdvancedAnalytics:
    def _seed(self):
        register()
        token = login()
        db = get_db_session()
        tracks = [
            seed_track(db, title="Bright Pop", artist="Artist A", genre="pop", energy=0.8, valence=0.8),
            seed_track(db, title="Dark Rock", artist="Artist B", genre="rock", energy=0.8, valence=0.2),
            seed_track(db, title="Soft Jazz", artist="Artist C", genre="jazz", energy=0.3, valence=0.6),
        ]
        db.close()
        now = datetime.now(timezone.utc)
        # older period A
        for i in range(3):
            client.post('/api/v1/listening-events', json={
                'track_id': tracks[0].id,
                'listened_at': (now - timedelta(days=60-i)).isoformat(),
                'duration_listened_ms': 200000,
            }, headers=hdr(token))
        # recent period B
        for i in range(4):
            client.post('/api/v1/listening-events', json={
                'track_id': tracks[1].id if i < 2 else tracks[2].id,
                'listened_at': (now - timedelta(days=5-i)).isoformat(),
                'duration_listened_ms': 210000,
            }, headers=hdr(token))
        return token

    def test_openapi_has_no_duplicate_ai_sections(self):
        spec = client.get('/api/v1/openapi.json').json()
        tag_names = [t['name'] for t in spec.get('tags', [])]
        assert 'AI' in tag_names
        assert 'Analytics' in tag_names
        assert 'AI — Query' not in tag_names
        assert 'AI — Playlists' not in tag_names
        assert 'AI — Evaluation' not in tag_names
        assert 'AI — Insights' not in tag_names

    def test_mood_profile_endpoint(self):
        token = self._seed()
        r = client.get('/api/v1/analytics/mood-profile', headers=hdr(token))
        assert r.status_code == 200
        data = r.json()
        assert data['total_events'] == 7
        assert len(data['items']) >= 1
        assert data['dominant_mood'] in {'Happy', 'Angry', 'Calm', 'Sad'}

    def test_compare_endpoint(self):
        token = self._seed()
        now = datetime.now(timezone.utc)
        r = client.get(
            '/api/v1/analytics/compare',
            params={
                'from_a': (now - timedelta(days=70)).isoformat(),
                'to_a': (now - timedelta(days=30)).isoformat(),
                'from_b': (now - timedelta(days=10)).isoformat(),
                'to_b': now.isoformat(),
            },
            headers=hdr(token),
        )
        assert r.status_code == 200
        data = r.json()
        metric_names = {m['metric'] for m in data['metrics']}
        assert 'avg_energy' in metric_names
        assert 'novelty_ratio' in metric_names
        assert isinstance(data['summary'], str) and len(data['summary']) > 5

    def test_eval_insight_uses_request_body(self):
        token = self._seed()
        created = client.post('/api/v1/analytics/insights', headers=hdr(token))
        assert created.status_code == 201
        insight_id = created.json()['id']
        r = client.post('/api/v1/ai/eval/insights', json={'insight_id': insight_id}, headers=hdr(token))
        assert r.status_code == 200
        assert r.json()['insight_id'] == insight_id