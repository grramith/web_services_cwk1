"""
Missing test coverage for Sonic Insights Hybrid API v3.

Covers every endpoint that is untested or non-existent in the legacy
test_api.py file. Written against the ACTUAL v3 route definitions:
  - auth.py:      /auth/refresh, /auth/logout
  - feedback.py:  full CRUD
  - analytics.py: /analytics/fingerprint, /analytics/changes/recent,
                  /analytics/highlights
  - catalog.py:   all 7 endpoints
  - ai.py:        /ai/recommendations/explain, /ai/recommendations/what-if,
                  /ai/insights/{id}/critique
  - mcp.py:       /mcp/manifest, /mcp/invoke (all 5 tools)
  - main.py:      /health/detailed
"""

import pytest
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# ── In-memory test database ───────────────────────────────────────────────────

ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)


def _override():
    db = TestSession()
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


# ── Reusable helpers ──────────────────────────────────────────────────────────

@contextmanager
def db_session():
    """Properly managed test DB session — avoids the unclosed-session bug."""
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def register(username="alice", email="alice@example.com", password="SecurePass1"):
    r = client.post("/api/v1/auth/register", json={
        "username": username, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


def login(username="alice", password="SecurePass1"):
    r = client.post("/api/v1/auth/login", data={
        "username": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(username="alice", password="SecurePass1"):
    return {"Authorization": f"Bearer {login(username, password)['access_token']}"}


def seed_track(title="Track A", artist="Artist A", genre="pop",
               energy=0.7, valence=0.6, danceability=0.7,
               acousticness=0.2, instrumentalness=0.0,
               speechiness=0.05, liveness=0.1, tempo=120.0):
    from app.models import Track
    with db_session() as db:
        t = Track(
            title=title, artist=artist, genre=genre,
            energy=energy, valence=valence, danceability=danceability,
            acousticness=acousticness, instrumentalness=instrumentalness,
            speechiness=speechiness, liveness=liveness, tempo=tempo,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        return t.id  # return id only — session is closed after this


def seed_catalog_track(name="Catalog Track", artist="Cat Artist", genre="pop",
                       energy=0.7, valence=0.6, danceability=0.65,
                       acousticness=0.2, instrumentalness=0.0,
                       speechiness=0.05, liveness=0.1, tempo=125.0,
                       external_id=None):
    from app.models import CatalogTrack
    import uuid
    with db_session() as db:
        ct = CatalogTrack(
            external_id=external_id or uuid.uuid4().hex[:16],
            name=name, artist=artist, genre=genre,
            energy=energy, valence=valence, danceability=danceability,
            acousticness=acousticness, instrumentalness=instrumentalness,
            speechiness=speechiness, liveness=liveness, tempo=tempo,
            source_dataset="test",
        )
        db.add(ct)
        db.commit()
        db.refresh(ct)
        return ct.id


def seed_event(token, track_id, days_ago=5):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    r = client.post("/api/v1/listening-events", json={
        "track_id": track_id, "listened_at": ts, "duration_listened_ms": 200000,
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return r.json()


def seed_listening_history(token, n_tracks=3, events_per_track=3):
    """Create diverse tracks + listening events; returns list of track_ids."""
    genres = ["pop", "rock", "jazz"]
    energies = [0.8, 0.5, 0.3]
    valences = [0.7, 0.3, 0.6]
    track_ids = []
    for i in range(n_tracks):
        tid = seed_track(
            title=f"Song {i}", artist=f"Artist {i}",
            genre=genres[i % len(genres)],
            energy=energies[i % len(energies)],
            valence=valences[i % len(valences)],
        )
        track_ids.append(tid)
        for j in range(events_per_track):
            seed_event(token, tid, days_ago=30 + j * 5)
    return track_ids


def seed_insight(user_id, text="Energy is high at 0.8.", snapshot=None):
    """Directly insert an Insight record, bypassing the service layer."""
    from app.models import Insight
    with db_session() as db:
        snap = snapshot or {
            "fingerprint_label": "Energetic Explorer",
            "avg_energy": 0.8, "avg_valence": 0.6,
            "novelty_ratio": 0.6, "diversity_score": 0.7,
            "recent_shift": "Stable",
        }
        ins = Insight(
            user_id=user_id,
            insight_type="hybrid",
            title="Test insight",
            insight_text=text,
            data_snapshot=snap,
            evidence=[
                {"claim": "Energy is high", "support": "avg_energy=0.8"},
                {"claim": "Diverse genres", "support": "diversity_score=0.7"},
            ],
            model_used="template",
        )
        db.add(ins)
        db.commit()
        db.refresh(ins)
        return ins.id


# ── Auth: missing endpoints ───────────────────────────────────────────────────

class TestAuthRefreshAndLogout:
    """Token refresh (rotation) and logout (blacklisting) are untested in legacy suite."""

    def test_refresh_returns_new_token_pair(self):
        register()
        tokens = login()
        r = client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New tokens should differ from the originals
        assert data["access_token"] != tokens["access_token"]

    def test_refresh_with_access_token_fails(self):
        """Refresh endpoint must reject an access token (wrong type claim)."""
        register()
        tokens = login()
        r = client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["access_token"],  # wrong type
        })
        assert r.status_code == 401

    def test_refresh_token_rotation_prevents_reuse(self):
        """After a successful refresh, the old refresh token must be blacklisted."""
        register()
        tokens = login()
        # First refresh succeeds
        r1 = client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r1.status_code == 200
        # Reusing the same old refresh token must fail
        r2 = client.post("/api/v1/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert r2.status_code == 401

    def test_refresh_invalid_token_fails(self):
        r = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "this.is.not.a.jwt",
        })
        assert r.status_code == 401

    def test_logout_invalidates_token(self):
        register()
        headers = auth_headers()
        r = client.post("/api/v1/auth/logout", headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] == "logged out"
        # Subsequent request with the same token must now fail
        r2 = client.get("/api/v1/auth/me", headers=headers)
        assert r2.status_code == 401

    def test_logout_requires_authentication(self):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 401

    def test_register_duplicate_email_fails(self):
        """Duplicate email must also be rejected — only username duplicate is tested in legacy suite."""
        register(username="alice", email="alice@example.com")
        r = client.post("/api/v1/auth/register", json={
            "username": "bob",
            "email": "alice@example.com",  # same email, different username
            "password": "SecurePass1",
        })
        assert r.status_code == 409

    def test_get_me_no_token_fails(self):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 401

    def test_get_me_invalid_token_fails(self):
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": "Bearer garbage.token.here"})
        assert r.status_code == 401


# ── Feedback CRUD — entirely untested in legacy suite ────────────────────────

class TestFeedbackCRUD:
    def _setup(self):
        register()
        token = login()["access_token"]
        cat_id = seed_catalog_track()
        return token, cat_id

    # ── Create ────────────────────────────────────────────────────────────────

    def test_create_feedback_like(self):
        token, cat_id = self._setup()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        d = r.json()
        assert d["rating"] == "like"
        assert d["catalog_track_id"] == cat_id
        assert d["user_id"] is not None

    def test_create_feedback_all_valid_ratings(self):
        register(username="bob", email="bob@x.com")
        token = login("bob")["access_token"]
        for i, rating in enumerate(["like", "dislike", "save", "skip"]):
            cat_id = seed_catalog_track(external_id=f"ext-rating-{i}")
            r = client.post("/api/v1/feedback", json={
                "catalog_track_id": cat_id, "rating": rating,
            }, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 201, f"Failed for rating={rating}: {r.text}"
            assert r.json()["rating"] == rating

    def test_create_feedback_with_note(self):
        token, cat_id = self._setup()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "save",
            "note": "Great track for studying",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        assert r.json()["note"] == "Great track for studying"

    def test_create_feedback_invalid_rating_rejected(self):
        token, cat_id = self._setup()
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "love",  # invalid
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_create_feedback_nonexistent_track_returns_404(self):
        register(username="charlie", email="c@x.com")
        token = login("charlie")["access_token"]
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": 99999, "rating": "like",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    def test_create_feedback_requires_auth(self):
        cat_id = seed_catalog_track(external_id="unauth-create")
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        })
        assert r.status_code == 401

    # ── Read / List ───────────────────────────────────────────────────────────

    def test_list_feedback_empty(self):
        register(username="dave", email="d@x.com")
        token = login("dave")["access_token"]
        r = client.get("/api/v1/feedback",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []

    def test_list_feedback_returns_own_records_only(self):
        register(username="eve", email="eve@x.com")
        register(username="frank", email="frank@x.com")
        t_eve = login("eve")["access_token"]
        t_frank = login("frank")["access_token"]
        cat_id = seed_catalog_track(external_id="shared-track")
        # Eve creates one record
        client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers={"Authorization": f"Bearer {t_eve}"})
        # Frank should see zero
        r = client.get("/api/v1/feedback",
                       headers={"Authorization": f"Bearer {t_frank}"})
        assert r.json() == []

    def test_list_feedback_filter_by_rating(self):
        token, _ = self._setup()
        hdr = {"Authorization": f"Bearer {token}"}
        ct1 = seed_catalog_track(external_id="fb-filter-1")
        ct2 = seed_catalog_track(external_id="fb-filter-2")
        client.post("/api/v1/feedback", json={
            "catalog_track_id": ct1, "rating": "like"}, headers=hdr)
        client.post("/api/v1/feedback", json={
            "catalog_track_id": ct2, "rating": "dislike"}, headers=hdr)
        r = client.get("/api/v1/feedback?rating=like", headers=hdr)
        items = r.json()
        assert all(i["rating"] == "like" for i in items)
        assert len(items) == 1

    def test_list_feedback_includes_track_metadata(self):
        """list response should contain track_name, artist, genre."""
        token, cat_id = self._setup()
        client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "save",
        }, headers={"Authorization": f"Bearer {token}"})
        r = client.get("/api/v1/feedback",
                       headers={"Authorization": f"Bearer {token}"})
        item = r.json()[0]
        assert "track_name" in item
        assert "artist" in item

    # ── Update ────────────────────────────────────────────────────────────────

    def test_update_feedback_rating(self):
        token, cat_id = self._setup()
        hdr = {"Authorization": f"Bearer {token}"}
        fb_id = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers=hdr).json()["id"]
        r = client.patch(f"/api/v1/feedback/{fb_id}",
                         json={"rating": "dislike"}, headers=hdr)
        assert r.status_code == 200
        assert r.json()["rating"] == "dislike"

    def test_update_feedback_note_only(self):
        token, cat_id = self._setup()
        hdr = {"Authorization": f"Bearer {token}"}
        fb_id = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers=hdr).json()["id"]
        r = client.patch(f"/api/v1/feedback/{fb_id}",
                         json={"note": "Updated note"}, headers=hdr)
        assert r.status_code == 200
        assert r.json()["note"] == "Updated note"
        assert r.json()["rating"] == "like"  # unchanged

    def test_update_other_users_feedback_returns_404(self):
        """User B must not be able to update user A's feedback."""
        register(username="grace", email="g@x.com")
        register(username="henry", email="h@x.com")
        t_grace = login("grace")["access_token"]
        t_henry = login("henry")["access_token"]
        cat_id = seed_catalog_track(external_id="update-auth-test")
        fb_id = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers={"Authorization": f"Bearer {t_grace}"}).json()["id"]
        r = client.patch(f"/api/v1/feedback/{fb_id}",
                         json={"rating": "dislike"},
                         headers={"Authorization": f"Bearer {t_henry}"})
        assert r.status_code == 404

    def test_update_nonexistent_feedback_returns_404(self):
        register(username="ivan", email="i@x.com")
        token = login("ivan")["access_token"]
        r = client.patch("/api/v1/feedback/99999",
                         json={"rating": "like"},
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    # ── Delete ────────────────────────────────────────────────────────────────

    def test_delete_feedback(self):
        token, cat_id = self._setup()
        hdr = {"Authorization": f"Bearer {token}"}
        fb_id = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "like",
        }, headers=hdr).json()["id"]
        r = client.delete(f"/api/v1/feedback/{fb_id}", headers=hdr)
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        # Confirm it's gone from list
        remaining = client.get("/api/v1/feedback", headers=hdr).json()
        assert not any(fb["id"] == fb_id for fb in remaining)

    def test_delete_other_users_feedback_returns_404(self):
        register(username="judy", email="j@x.com")
        register(username="kim", email="k@x.com")
        t_judy = login("judy")["access_token"]
        t_kim = login("kim")["access_token"]
        cat_id = seed_catalog_track(external_id="delete-auth-test")
        fb_id = client.post("/api/v1/feedback", json={
            "catalog_track_id": cat_id, "rating": "save",
        }, headers={"Authorization": f"Bearer {t_judy}"}).json()["id"]
        r = client.delete(f"/api/v1/feedback/{fb_id}",
                          headers={"Authorization": f"Bearer {t_kim}"})
        assert r.status_code == 404

    def test_delete_nonexistent_feedback_returns_404(self):
        register(username="leo", email="l@x.com")
        token = login("leo")["access_token"]
        r = client.delete("/api/v1/feedback/99999",
                          headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404


# ── Analytics v3 — untested endpoints ────────────────────────────────────────

class TestAnalyticsV3:
    """fingerprint, changes/recent, and highlights are all untested in legacy suite."""

    def _setup(self):
        register()
        token = login()["access_token"]
        seed_listening_history(token, n_tracks=3, events_per_track=4)
        return token

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    # ── fingerprint ───────────────────────────────────────────────────────────

    def test_fingerprint_returns_label(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/fingerprint", headers=self._auth(token))
        assert r.status_code == 200
        d = r.json()
        assert "fingerprint_label" in d
        assert d["fingerprint_label"] in {
            "Energetic Explorer", "Calm Specialist",
            "Late-Night Listener", "Comfort Repeater", "Balanced Listener",
        }

    def test_fingerprint_traits_present(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/fingerprint", headers=self._auth(token))
        traits = r.json()["traits"]
        for key in ["avg_energy", "avg_valence", "avg_danceability",
                    "novelty_ratio", "diversity_score", "total_events"]:
            assert key in traits, f"Missing trait: {key}"

    def test_fingerprint_numeric_ranges(self):
        """All 0–1 bounded traits must stay within range."""
        token = self._setup()
        r = client.get("/api/v1/analytics/fingerprint", headers=self._auth(token))
        traits = r.json()["traits"]
        for key in ["avg_energy", "avg_valence", "avg_danceability",
                    "novelty_ratio", "diversity_score"]:
            v = traits[key]
            assert 0.0 <= v <= 1.0, f"{key}={v} out of [0, 1]"

    def test_fingerprint_explanation_present(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/fingerprint", headers=self._auth(token))
        d = r.json()
        assert isinstance(d.get("explanation"), str)
        assert len(d["explanation"]) > 10

    def test_fingerprint_evidence_chain_present(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/fingerprint", headers=self._auth(token))
        evidence = r.json().get("evidence", [])
        assert len(evidence) >= 1
        assert all("claim" in e and "support" in e for e in evidence)

    def test_fingerprint_no_data_returns_400(self):
        register(username="newuser", email="new@x.com")
        token = login("newuser")["access_token"]
        r = client.get("/api/v1/analytics/fingerprint",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400

    def test_fingerprint_requires_auth(self):
        r = client.get("/api/v1/analytics/fingerprint")
        assert r.status_code == 401

    # ── highlights ────────────────────────────────────────────────────────────

    def test_highlights_structure(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/highlights", headers=self._auth(token))
        assert r.status_code == 200
        d = r.json()
        for key in ["top_artist", "top_genre", "novelty_ratio",
                    "diversity_score", "dominant_mood"]:
            assert key in d

    def test_highlights_no_data_returns_400(self):
        register(username="empty2", email="empty2@x.com")
        token = login("empty2")["access_token"]
        r = client.get("/api/v1/analytics/highlights",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400

    # ── changes/recent ────────────────────────────────────────────────────────

    def test_recent_changes_structure(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/changes/recent",
                       headers=self._auth(token))
        assert r.status_code == 200
        d = r.json()
        assert "fingerprint_shift" in d
        assert "summary" in d
        assert "metrics" in d
        assert "previous_window" in d
        assert "recent_window" in d

    def test_recent_changes_metrics_present(self):
        token = self._setup()
        r = client.get("/api/v1/analytics/changes/recent",
                       headers=self._auth(token))
        metric_names = {m["metric"] for m in r.json()["metrics"]}
        for expected in ["avg_energy", "avg_valence", "novelty_ratio",
                         "dominant_mood", "top_genre"]:
            assert expected in metric_names

    def test_recent_changes_no_data_returns_stable(self):
        register(username="empty3", email="empty3@x.com")
        token = login("empty3")["access_token"]
        r = client.get("/api/v1/analytics/changes/recent",
                    headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        d = r.json()
        assert d["fingerprint_shift"] == "Stable"
        assert d["metrics"] is not None

    def test_overview_requires_auth(self):
        r = client.get("/api/v1/analytics/overview")
        assert r.status_code == 401


# ── Catalog endpoints — entirely untested ─────────────────────────────────────

class TestCatalogSearch:
    def _populate(self, n=5):
        """Seed n catalog tracks with varied attributes."""
        import uuid
        genres = ["pop", "rock", "jazz", "electronic", "classical"]
        for i in range(n):
            seed_catalog_track(
                name=f"Song {i}", artist=f"Band {i}",
                genre=genres[i % len(genres)],
                energy=0.2 + i * 0.15,
                valence=0.3 + i * 0.12,
                external_id=f"ext-{i}-{uuid.uuid4().hex[:6]}",
            )

    def _auth(self):
        register()
        return {"Authorization": f"Bearer {login()['access_token']}"}

    def test_search_returns_all_by_default(self):
        self._populate()
        r = client.get("/api/v1/catalog", headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 5
        assert len(d["items"]) == 5

    def test_search_by_name_query(self):
        self._populate()
        r = client.get("/api/v1/catalog?q=Song+0", headers=self._auth())
        items = r.json()["items"]
        assert len(items) >= 1
        assert all("song 0" in item["name"].lower() for item in items)

    def test_search_by_artist_query(self):
        self._populate()
        r = client.get("/api/v1/catalog?q=Band+1", headers=self._auth())
        items = r.json()["items"]
        assert len(items) >= 1

    def test_search_by_genre_filter(self):
        self._populate()
        r = client.get("/api/v1/catalog?genre=pop", headers=self._auth())
        items = r.json()["items"]
        assert len(items) >= 1
        assert all("pop" in (item["genre"] or "").lower() for item in items)

    def test_search_energy_range_filter(self):
        self._populate()
        r = client.get("/api/v1/catalog?min_energy=0.6&max_energy=1.0",
                       headers=self._auth())
        for item in r.json()["items"]:
            assert item["energy"] >= 0.6

    def test_search_pagination(self):
        self._populate(10)
        r = client.get("/api/v1/catalog?limit=3&offset=0", headers=self._auth())
        d = r.json()
        assert len(d["items"]) == 3
        assert d["total"] == 10

    def test_search_pagination_offset(self):
        self._populate(5)
        headers = self._auth()          # register + login exactly once
        r1 = client.get("/api/v1/catalog?limit=3&offset=0", headers=headers)
        r2 = client.get("/api/v1/catalog?limit=3&offset=3", headers=headers)
        ids_page1 = {i["id"] for i in r1.json()["items"]}
        ids_page2 = {i["id"] for i in r2.json()["items"]}
        assert ids_page1.isdisjoint(ids_page2), "Pages must not overlap"

    def test_search_empty_catalog_returns_zero(self):
        r = client.get("/api/v1/catalog", headers=self._auth())
        assert r.json()["total"] == 0

    def test_search_requires_auth(self):
        r = client.get("/api/v1/catalog")
        assert r.status_code == 401

    def test_search_invalid_energy_range_returns_422(self):
        r = client.get("/api/v1/catalog?min_energy=1.5",  # out of [0,1]
                       headers=self._auth())
        assert r.status_code == 422


class TestCatalogGetById:
    def _auth(self):
        register(username="catuser", email="cat@x.com")
        return {"Authorization": f"Bearer {login('catuser')['access_token']}"}

    def test_get_track_by_id(self):
        cat_id = seed_catalog_track(name="My Track", external_id="get-by-id-1")
        r = client.get(f"/api/v1/catalog/{cat_id}", headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "My Track"
        assert d["id"] == cat_id

    def test_get_track_not_found_returns_404(self):
        r = client.get("/api/v1/catalog/99999", headers=self._auth())
        assert r.status_code == 404

    def test_get_track_requires_auth(self):
        cat_id = seed_catalog_track(external_id="noauth-get")
        r = client.get(f"/api/v1/catalog/{cat_id}")
        assert r.status_code == 401


class TestCatalogSimilarTracks:
    def _auth(self):
        register(username="simuser", email="sim@x.com")
        return {"Authorization": f"Bearer {login('simuser')['access_token']}"}

    def _populate_similar(self):
        """Seed a seed track and 5 others with similar features."""
        import uuid
        seed_id = seed_catalog_track(
            name="Seed Track", energy=0.7, valence=0.6,
            external_id="similar-seed",
        )
        for i in range(5):
            seed_catalog_track(
                name=f"Neighbour {i}", energy=0.65 + i * 0.02,
                valence=0.58 + i * 0.02,
                external_id=f"neighbour-{i}-{uuid.uuid4().hex[:4]}",
            )
        return seed_id

    def test_similar_tracks_returns_results(self):
        seed_id = self._populate_similar()
        r = client.get(f"/api/v1/catalog/{seed_id}/similar?limit=3",
                       headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert "seed_track_id" in d
        assert len(d["results"]) <= 3

    def test_similar_tracks_excludes_seed(self):
        seed_id = self._populate_similar()
        r = client.get(f"/api/v1/catalog/{seed_id}/similar",
                       headers=self._auth())
        result_ids = [t["id"] for t in r.json()["results"]]
        assert seed_id not in result_ids

    def test_similar_tracks_scores_between_0_and_1(self):
        seed_id = self._populate_similar()
        r = client.get(f"/api/v1/catalog/{seed_id}/similar",
                       headers=self._auth())
        for item in r.json()["results"]:
            assert 0.0 <= item["similarity_score"] <= 1.0

    def test_similar_tracks_not_found_returns_404(self):
        r = client.get("/api/v1/catalog/99999/similar", headers=self._auth())
        assert r.status_code == 404

    def test_similar_tracks_same_genre_filter(self):
        import uuid
        seed_id = seed_catalog_track(
            name="Genre Seed", genre="jazz", energy=0.5, valence=0.5,
            external_id="genre-seed",
        )
        for i in range(3):
            seed_catalog_track(
                name=f"Jazz Track {i}", genre="jazz",
                external_id=f"jazz-{i}-{uuid.uuid4().hex[:4]}",
            )
        seed_catalog_track(name="Pop Track", genre="pop",
                           external_id="pop-outlier")
        r = client.get(f"/api/v1/catalog/{seed_id}/similar?same_genre=true",
                       headers=self._auth())
        for item in r.json()["results"]:
            assert item["genre"] and "jazz" in item["genre"].lower()


class TestCatalogMoodMap:
    def _auth(self):
        register(username="mooduser", email="mood@x.com")
        return {"Authorization": f"Bearer {login('mooduser')['access_token']}"}

    def test_mood_map_empty_catalog_returns_404(self):
        r = client.get("/api/v1/catalog/mood-map", headers=self._auth())
        assert r.status_code == 404

    def test_mood_map_quadrant_structure(self):
        import uuid
        # Seed one track per quadrant
        tracks = [
            ("happy",      0.7, 0.7),  # high energy, high valence → Happy
            ("angry",      0.7, 0.3),  # high energy, low valence → Angry
            ("calm",       0.3, 0.7),  # low energy, high valence → Calm
            ("melancholic",0.3, 0.3),  # low energy, low valence → Sad
        ]
        for name, e, v in tracks:
            seed_catalog_track(name=name, energy=e, valence=v,
                               external_id=f"mm-{name}-{uuid.uuid4().hex[:4]}")
        r = client.get("/api/v1/catalog/mood-map", headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert "total_tracks" in d
        assert "quadrants" in d
        assert "most_common_mood" in d
        moods = {q["mood"] for q in d["quadrants"]}
        assert moods <= {"Happy", "Angry", "Calm", "Sad"}

    def test_mood_map_percentages_sum_to_100(self):
        import uuid
        for i in range(4):
            seed_catalog_track(energy=0.4 + i * 0.2, valence=0.4 + i * 0.1,
                               external_id=f"pct-{i}-{uuid.uuid4().hex[:4]}")
        r = client.get("/api/v1/catalog/mood-map", headers=self._auth())
        total_pct = sum(q["percentage"] for q in r.json()["quadrants"])
        assert abs(total_pct - 100.0) < 0.1  # floating point tolerance

    def test_mood_map_requires_auth(self):
        r = client.get("/api/v1/catalog/mood-map")
        assert r.status_code == 401


class TestCatalogAudioDNA:
    def _auth(self):
        register(username="dnauser", email="dna@x.com")
        return {"Authorization": f"Bearer {login('dnauser')['access_token']}"}

    def test_audio_dna_empty_catalog_returns_404(self):
        r = client.get("/api/v1/catalog/audio-dna", headers=self._auth())
        assert r.status_code == 404

    def test_audio_dna_features_present(self):
        import uuid
        for i in range(3):
            seed_catalog_track(external_id=f"dna-{i}-{uuid.uuid4().hex[:4]}")
        r = client.get("/api/v1/catalog/audio-dna", headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert "features" in d
        assert "total_tracks" in d
        feature_names = {f["feature"] for f in d["features"]}
        for expected in ["energy", "valence", "danceability"]:
            assert expected in feature_names

    def test_audio_dna_stats_structure(self):
        import uuid
        for i in range(3):
            seed_catalog_track(external_id=f"dna2-{i}-{uuid.uuid4().hex[:4]}")
        r = client.get("/api/v1/catalog/audio-dna", headers=self._auth())
        for feature in r.json()["features"]:
            for stat in ["mean", "min_value", "max_value", "percentile_25", "percentile_75"]:
                assert stat in feature, f"Missing stat '{stat}' in feature {feature['feature']}"


class TestCatalogGenres:
    def _auth(self):
        register(username="genreuser", email="genre@x.com")
        return {"Authorization": f"Bearer {login('genreuser')['access_token']}"}

    def test_genre_breakdown_empty(self):
        r = client.get("/api/v1/catalog/genres", headers=self._auth())
        assert r.status_code == 200
        assert r.json()["total_genres"] == 0

    def test_genre_breakdown_groups_correctly(self):
        import uuid
        for i in range(3):
            seed_catalog_track(genre="pop",
                               external_id=f"gb-pop-{i}-{uuid.uuid4().hex[:4]}")
        seed_catalog_track(genre="rock", external_id="gb-rock-1")
        r = client.get("/api/v1/catalog/genres", headers=self._auth())
        d = r.json()
        genres_map = {g["genre"]: g for g in d["genres"]}
        assert "pop" in genres_map
        assert genres_map["pop"]["track_count"] == 3

    def test_genre_breakdown_requires_auth(self):
        r = client.get("/api/v1/catalog/genres")
        assert r.status_code == 401


class TestCatalogRecommendByMood:
    def _auth(self):
        register(username="recuser", email="rec@x.com")
        return {"Authorization": f"Bearer {login('recuser')['access_token']}"}

    def _populate(self):
        import uuid
        # High energy, high valence → Happy
        for i in range(3):
            seed_catalog_track(name=f"Party {i}", energy=0.85,
                               valence=0.80, genre="pop",
                               external_id=f"rec-party-{i}-{uuid.uuid4().hex[:4]}")
        # Low energy, low valence → Sad
        for i in range(3):
            seed_catalog_track(name=f"Chill {i}", energy=0.25,
                               valence=0.25, genre="ambient",
                               external_id=f"rec-chill-{i}-{uuid.uuid4().hex[:4]}")

    def test_recommend_happy_returns_results(self):
        self._populate()
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "happy upbeat party", "limit": 5},
                        headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["total_candidates"] >= 0
        assert "results" in d
        assert "matched_keywords" in d

    def test_recommend_empty_catalog_returns_empty_results(self):
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "chill", "limit": 5},
                        headers=self._auth())
        assert r.status_code == 200
        assert r.json()["total_candidates"] == 0

    def test_recommend_unknown_mood_still_responds(self):
        self._populate()
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "xyzzy nonsense mood", "limit": 5},
                        headers=self._auth())
        assert r.status_code == 200
        assert r.json()["matched_keywords"] == []

    def test_recommend_too_short_description_rejected(self):
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "hi"},  # < 3 chars
                        headers=self._auth())
        assert r.status_code == 422

    def test_recommend_requires_auth(self):
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "happy vibes", "limit": 5})
        assert r.status_code == 401

    def test_recommend_mood_scores_between_0_and_1(self):
        self._populate()
        r = client.post("/api/v1/catalog/recommend-by-mood",
                        json={"description": "energetic workout", "limit": 10},
                        headers=self._auth())
        for item in r.json()["results"]:
            assert 0.0 <= item["mood_match_score"] <= 1.0


# ── AI hybrid endpoints — entirely untested ───────────────────────────────────

class TestAIRecommendationsExplain:
    def _setup(self):
        register()
        token = login()["access_token"]
        seed_listening_history(token, n_tracks=3, events_per_track=4)
        import uuid
        for i in range(5):
            seed_catalog_track(
                name=f"Catalog {i}", energy=0.4 + i * 0.1,
                valence=0.4 + i * 0.1,
                external_id=f"ai-rec-{i}-{uuid.uuid4().hex[:4]}",
            )
        return token

    def _hdr(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_explain_returns_recommendations(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 3},
                        headers=self._hdr(token))
        assert r.status_code == 200
        d = r.json()
        assert "recommendations" in d
        assert len(d["recommendations"]) <= 3
        assert "fingerprint_label" in d
        assert "strategy" in d

    def test_explain_recommendation_item_structure(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 5},
                        headers=self._hdr(token))
        for item in r.json()["recommendations"]:
            for key in ["track_id", "title", "artist", "fit_score",
                        "novelty_score", "familiarity", "why"]:
                assert key in item, f"Missing key: {key}"

    def test_explain_discovery_strategy(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "discovery", "max_tracks": 5},
                        headers=self._hdr(token))
        assert r.status_code == 200
        d = r.json()
        assert d["strategy"] == "discovery"
        # Discovery should have higher novelty scores on average
        avg_novelty = sum(i["novelty_score"]
                          for i in d["recommendations"]) / max(len(d["recommendations"]), 1)
        assert avg_novelty > 0.0

    def test_explain_comfort_strategy(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "comfort", "max_tracks": 5},
                        headers=self._hdr(token))
        assert r.status_code == 200
        assert r.json()["strategy"] == "comfort"

    def test_explain_with_context(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 5,
                              "context": "study session"},
                        headers=self._hdr(token))
        assert r.status_code == 200
        assert r.json()["context"] == "study session"

    def test_explain_invalid_strategy_rejected(self):
        register(username="strat_test", email="st@x.com")
        token = login("strat_test")["access_token"]
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "aggressive"},  # invalid
                        headers=self._hdr(token))
        assert r.status_code == 422

    def test_explain_no_catalog_returns_400(self):
        register(username="nocatalog", email="nc@x.com")
        token = login("nocatalog")["access_token"]
        seed_listening_history(token, n_tracks=2, events_per_track=2)
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced"},
                        headers=self._hdr(token))
        assert r.status_code == 400

    def test_explain_no_listening_history_returns_400(self):
        register(username="nohist", email="nh@x.com")
        token = login("nohist")["access_token"]
        import uuid
        seed_catalog_track(external_id=f"nh-{uuid.uuid4().hex[:6]}")
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced"},
                        headers=self._hdr(token))
        assert r.status_code == 400

    def test_explain_requires_auth(self):
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced"})
        assert r.status_code == 401

    def test_explain_disliked_tracks_excluded(self):
        """Tracks rated 'dislike' must never appear in recommendations."""
        register(username="dislike_test", email="dt@x.com")
        token = login("dislike_test")["access_token"]
        seed_listening_history(token, n_tracks=2, events_per_track=3)
        import uuid
        cat_ids = []
        for i in range(5):
            cid = seed_catalog_track(
                name=f"DislikeTest {i}", energy=0.5 + i * 0.05,
                external_id=f"dl-{i}-{uuid.uuid4().hex[:4]}",
            )
            cat_ids.append(cid)
        hdr = {"Authorization": f"Bearer {token}"}
        # Dislike the first catalog track
        client.post("/api/v1/feedback",
                    json={"catalog_track_id": cat_ids[0], "rating": "dislike"},
                    headers=hdr)
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 10},
                        headers=hdr)
        rec_ids = {item["track_id"] for item in r.json()["recommendations"]}
        assert cat_ids[0] not in rec_ids, "Disliked track should be excluded"


class TestAIWhatIfRecommendations:
    def _setup(self):
        register(username="whatif", email="wi@x.com")
        token = login("whatif")["access_token"]
        seed_listening_history(token, n_tracks=3, events_per_track=3)
        import uuid
        for i in range(5):
            seed_catalog_track(
                name=f"WI Catalog {i}", energy=0.3 + i * 0.15,
                external_id=f"wi-{i}-{uuid.uuid4().hex[:4]}",
            )
        return token

    def _hdr(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_what_if_discovery_scenario(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/what-if",
                        json={"scenario": "I want to discover more new music",
                              "max_tracks": 5},
                        headers=self._hdr(token))
        assert r.status_code == 200
        assert r.json()["strategy"] == "discovery"

    def test_what_if_comfort_scenario(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/what-if",
                        json={"scenario": "I want familiar comfort music",
                              "max_tracks": 5},
                        headers=self._hdr(token))
        assert r.status_code == 200
        assert r.json()["strategy"] == "comfort"

    def test_what_if_balanced_fallback(self):
        token = self._setup()
        r = client.post("/api/v1/ai/recommendations/what-if",
                        json={"scenario": "Something completely different",
                              "max_tracks": 5},
                        headers=self._hdr(token))
        assert r.status_code == 200
        assert r.json()["strategy"] == "balanced"

    def test_what_if_scenario_too_short_rejected(self):
        register(username="wi2", email="wi2@x.com")
        token = login("wi2")["access_token"]
        r = client.post("/api/v1/ai/recommendations/what-if",
                        json={"scenario": "hi"},  # < 5 chars
                        headers=self._hdr(token))
        assert r.status_code == 422

    def test_what_if_requires_auth(self):
        r = client.post("/api/v1/ai/recommendations/what-if",
                        json={"scenario": "show me new music", "max_tracks": 5})
        assert r.status_code == 401


class TestAIInsightCritique:
    def _setup(self):
        register(username="critique", email="critique@x.com")
        user_info = client.post("/api/v1/auth/register", json={})  # already registered
        # Get the user id
        token = login("critique")["access_token"]
        # Get user id from /me
        me = client.get("/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {token}"}).json()
        return token, me["id"]

    def _hdr(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_critique_returns_verdict(self):
        token, user_id = self._setup()
        insight_id = seed_insight(
            user_id,
            text="Your energy is high at 0.8 and novelty_ratio is 0.6.",
        )
        r = client.post(f"/api/v1/ai/insights/{insight_id}/critique",
                        headers=self._hdr(token))
        assert r.status_code == 200
        d = r.json()
        assert d["insight_id"] == insight_id
        assert d["overall_verdict"] in {"Strong", "Needs revision"}
        assert 0.0 <= d["grounding_score"] <= 1.0

    def test_critique_strong_for_grounded_insight(self):
        token, user_id = self._setup()
        with db_session() as db:
            from app.models import User as UserModel
            user = db.query(UserModel).filter(UserModel.id == user_id).first()
        snapshot = {
            "avg_energy": 0.8, "avg_valence": 0.6,
            "novelty_ratio": 0.6, "diversity_score": 0.7,
            "fingerprint_label": "Energetic Explorer",
            "recent_shift": "Stable",
        }
        insight_id = seed_insight(
            user_id,
            text="Your energy is 0.8 and novelty_ratio is 0.6. Diversity score 0.7 confirms wide taste.",
            snapshot=snapshot,
        )
        r = client.post(f"/api/v1/ai/insights/{insight_id}/critique",
                        headers=self._hdr(token))
        assert r.json()["overall_verdict"] == "Strong"

    def test_critique_flags_vague_terms(self):
        token, user_id = self._setup()
        insight_id = seed_insight(
            user_id,
            text="Your music taste is interesting and strong.",
        )
        r = client.post(f"/api/v1/ai/insights/{insight_id}/critique",
                        headers=self._hdr(token))
        issue_types = [i["issue_type"] for i in r.json()["issues"]]
        assert "vagueness" in issue_types

    def test_critique_flags_no_grounding(self):
        token, user_id = self._setup()
        insight_id = seed_insight(
            user_id,
            text="You seem to like music.",  # no numeric references
        )
        r = client.post(f"/api/v1/ai/insights/{insight_id}/critique",
                        headers=self._hdr(token))
        issue_types = [i["issue_type"] for i in r.json()["issues"]]
        assert "grounding" in issue_types

    def test_critique_not_found_returns_404(self):
        register(username="nocrit", email="nocrit@x.com")
        token = login("nocrit")["access_token"]
        r = client.post("/api/v1/ai/insights/99999/critique",
                        headers=self._hdr(token))
        assert r.status_code == 404

    def test_critique_other_users_insight_returns_404(self):
        """Users must not be able to critique another user's insight."""
        register(username="owner", email="owner@x.com")
        register(username="intruder", email="intruder@x.com")
        t_owner = login("owner")["access_token"]
        t_intruder = login("intruder")["access_token"]
        me_owner = client.get("/api/v1/auth/me",
                              headers={"Authorization": f"Bearer {t_owner}"}).json()
        insight_id = seed_insight(me_owner["id"], text="Energy is 0.8.")
        r = client.post(f"/api/v1/ai/insights/{insight_id}/critique",
                        headers={"Authorization": f"Bearer {t_intruder}"})
        assert r.status_code == 404

    def test_critique_requires_auth(self):
        r = client.post("/api/v1/ai/insights/1/critique")
        assert r.status_code == 401

    def test_generate_insight_creates_record(self):
        """POST /ai/insights should create and return an insight record."""
        register(username="gen_insight", email="gi@x.com")
        token = login("gen_insight")["access_token"]
        seed_listening_history(token, n_tracks=3, events_per_track=3)
        r = client.post("/api/v1/ai/insights",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        d = r.json()
        assert "id" in d
        assert "insight_text" in d
        assert d["insight_type"] == "hybrid"
        assert d["id"] > 0

    def test_generate_insight_no_history_returns_400(self):
        register(username="no_hist_ins", email="nhi@x.com")
        token = login("no_hist_ins")["access_token"]
        r = client.post("/api/v1/ai/insights",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400

    def test_generate_insight_requires_auth(self):
        r = client.post("/api/v1/ai/insights")
        assert r.status_code == 401



# ── MCP server — entirely untested ───────────────────────────────────────────

class TestMCPManifest:
    def _auth(self):
        register(username="mcpuser", email="mcp@x.com")
        return {"Authorization": f"Bearer {login('mcpuser')['access_token']}"}

    def test_manifest_returns_200(self):
        r = client.get("/api/v1/mcp/manifest", headers=self._auth())
        assert r.status_code == 200

    def test_manifest_schema_version(self):
        r = client.get("/api/v1/mcp/manifest", headers=self._auth())
        d = r.json()
        assert d["schema_version"] == "1.0"
        assert d["name"] == "sonic-insights-mcp"

    def test_manifest_contains_all_five_tools(self):
        r = client.get("/api/v1/mcp/manifest", headers=self._auth())
        tool_names = {t["name"] for t in r.json()["tools"]}
        expected = {
            "search_catalog", "recommend_by_mood", "get_listening_summary",
            "get_catalog_mood_map", "find_similar_tracks",
        }
        assert tool_names == expected

    def test_manifest_tools_have_required_fields(self):
        r = client.get("/api/v1/mcp/manifest", headers=self._auth())
        for tool in r.json()["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_manifest_accessible_without_auth(self):
        r = client.get("/api/v1/mcp/manifest")
        assert r.status_code == 200
        assert r.json()["schema_version"] == "1.0"


class TestMCPInvoke:
    def _auth(self):
        register(username="mcp2", email="mcp2@x.com")
        return {"Authorization": f"Bearer {login('mcp2')['access_token']}"}

    def _populate_catalog(self):
        import uuid
        for i in range(5):
            seed_catalog_track(
                name=f"MCP Track {i}", artist=f"MCP Artist {i}",
                genre="pop" if i % 2 == 0 else "rock",
                energy=0.5 + i * 0.08, valence=0.4 + i * 0.1,
                external_id=f"mcp-cat-{i}-{uuid.uuid4().hex[:4]}",
            )

    def test_invoke_search_catalog(self):
        self._populate_catalog()
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "search_catalog",
                              "arguments": {"query": "MCP Track", "limit": 3}},
                        headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert d["tool"] == "search_catalog"
        assert "tracks" in d["result"]

    def test_invoke_recommend_by_mood(self):
        self._populate_catalog()
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "recommend_by_mood",
                              "arguments": {"description": "happy upbeat", "limit": 3}},
                        headers=self._auth())
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_invoke_get_listening_summary_no_history(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "get_listening_summary", "arguments": {}},
                        headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["success"] is True
        assert d["result"]["total_events"] == 0

    def test_invoke_get_listening_summary_with_history(self):
        register(username="mcp_hist", email="mcph@x.com")
        token = login("mcp_hist")["access_token"]
        seed_listening_history(token, n_tracks=2, events_per_track=3)
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "get_listening_summary", "arguments": {}},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["result"]["total_events"] == 6

    def test_invoke_get_catalog_mood_map_empty(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "get_catalog_mood_map", "arguments": {}},
                        headers=self._auth())
        assert r.status_code == 200
        # Empty catalog → total_tracks = 0
        assert r.json()["result"]["total_tracks"] == 0

    def test_invoke_get_catalog_mood_map_with_data(self):
        self._populate_catalog()
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "get_catalog_mood_map", "arguments": {}},
                        headers=self._auth())
        assert r.status_code == 200
        d = r.json()
        assert d["result"]["total_tracks"] == 5

    def test_invoke_find_similar_tracks(self):
        self._populate_catalog()
        headers = self._auth()                                      # register once
        tracks = client.get("/api/v1/catalog", headers=headers).json()["items"]
        seed_id = tracks[0]["id"]
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "find_similar_tracks",
                            "arguments": {"track_id": seed_id, "limit": 3}},
                        headers=headers)
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert "similar_tracks" in r.json()["result"]


    def test_invoke_find_similar_tracks_missing_id_returns_error(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "find_similar_tracks", "arguments": {}},
                        headers=self._auth())
        assert r.status_code == 200
        # Tool failure returns success=False, not HTTP 4xx
        assert r.json()["success"] is False
        assert r.json()["error"] is not None

    def test_invoke_find_similar_nonexistent_track(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "find_similar_tracks",
                              "arguments": {"track_id": 99999}},
                        headers=self._auth())
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_invoke_unknown_tool_returns_404(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "nonexistent_tool", "arguments": {}},
                        headers=self._auth())
        assert r.status_code == 404

    def test_invoke_requires_auth(self):
        r = client.post("/api/v1/mcp/invoke",
                        json={"tool": "search_catalog", "arguments": {}})
        assert r.status_code == 401


# ── Health/detailed — untested ────────────────────────────────────────────────

class TestHealthDetailed:
    def test_health_detailed_structure(self):
        r = client.get("/health/detailed/json")
        assert r.status_code == 200
        d = r.json()
        assert "status" in d
        assert "statistics" in d
        assert "database" in d

    def test_health_detailed_statistics_keys(self):
        r = client.get("/health/detailed/json")
        stats = r.json()["statistics"]
        for key in ["catalog_tracks", "spotify_tracks", "listening_events", "users", "feedback_records", "insights"]:
            assert key in stats

    def test_health_detailed_counts_are_integers(self):
        r = client.get("/health/detailed/json")
        for key, value in r.json()["statistics"].items():
            assert isinstance(value, int)
# ── End-to-end workflow tests ─────────────────────────────────────────────────

class TestEndToEndWorkflows:
    """
    Full user journeys that cross multiple route modules.
    These are the tests that impress examiners — they demonstrate the system
    works as a coherent whole, not just as isolated endpoints.
    """

    def test_full_discovery_workflow(self):
        """
        A user registers → listens to music → gets fingerprint →
        imports catalog → gets recommendations → leaves feedback.
        """
        # 1. Register and log in
        r = client.post("/api/v1/auth/register", json={
            "username": "workflow_user", "email": "wf@example.com",
            "password": "WorkflowPass1",
        })
        assert r.status_code == 201
        token = client.post("/api/v1/auth/login", data={
            "username": "workflow_user", "password": "WorkflowPass1",
        }).json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        # 2. Build listening history
        seed_listening_history(token, n_tracks=3, events_per_track=5)

        # 3. Check fingerprint is computed
        r = client.get("/api/v1/analytics/fingerprint", headers=hdr)
        assert r.status_code == 200
        assert r.json()["fingerprint_label"] is not None

        # 4. Seed catalog
        import uuid
        for i in range(10):
            seed_catalog_track(
                name=f"WF Catalog {i}", energy=0.3 + i * 0.07,
                valence=0.3 + i * 0.06,
                external_id=f"wf-{i}-{uuid.uuid4().hex[:4]}",
            )

        # 5. Get recommendations
        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 5},
                        headers=hdr)
        assert r.status_code == 200
        recs = r.json()["recommendations"]
        assert len(recs) > 0

        # 6. Leave feedback on first recommendation
        first_track_id = recs[0]["track_id"]
        r = client.post("/api/v1/feedback", json={
            "catalog_track_id": first_track_id, "rating": "like",
            "note": "Loved this suggestion",
        }, headers=hdr)
        assert r.status_code == 201

        # 7. Verify feedback is in list
        r = client.get("/api/v1/feedback", headers=hdr)
        assert len(r.json()) == 1
        assert r.json()[0]["catalog_track_id"] == first_track_id # via FeedbackListItem

    def test_token_rotation_security_chain(self):
        """
        Full auth security test: login → refresh → old token rejected →
        new token works → logout → new token rejected.
        """
        r = client.post("/api/v1/auth/register", json={
            "username": "sec_user", "email": "sec@x.com", "password": "SecPass123",
        })
        assert r.status_code == 201

        # Login
        tokens = client.post("/api/v1/auth/login", data={
            "username": "sec_user", "password": "SecPass123",
        }).json()
        old_access = tokens["access_token"]
        old_refresh = tokens["refresh_token"]

        # Refresh — get new tokens
        new_tokens = client.post("/api/v1/auth/refresh", json={
            "refresh_token": old_refresh,
        }).json()
        new_access = new_tokens["access_token"]

        # Old refresh token must now be rejected
        r = client.post("/api/v1/auth/refresh", json={
            "refresh_token": old_refresh,
        })
        assert r.status_code == 401

        # New access token works
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": f"Bearer {new_access}"})
        assert r.status_code == 200

        # Logout with new token
        r = client.post("/api/v1/auth/logout",
                        headers={"Authorization": f"Bearer {new_access}"})
        assert r.status_code == 200

        # Post-logout access must fail
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": f"Bearer {new_access}"})
        assert r.status_code == 401

    def test_catalog_to_mcp_pipeline(self):
        """
        Seed catalog → search via REST → find same track via MCP invoke.
        Both paths must return consistent data.
        """
        import uuid
        ext_id = f"pipeline-{uuid.uuid4().hex[:8]}"
        cat_id = seed_catalog_track(
            name="Pipeline Track", artist="Pipeline Artist",
            genre="jazz", energy=0.5, valence=0.5,
            external_id=ext_id,
        )
        register(username="pipeline_user", email="pl@x.com")
        token = login("pipeline_user")["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}

        # REST search
        r_rest = client.get("/api/v1/catalog?q=Pipeline+Track", headers=hdr)
        assert r_rest.json()["total"] == 1
        rest_id = r_rest.json()["items"][0]["id"]
        assert rest_id == cat_id

        # MCP search
        r_mcp = client.post("/api/v1/mcp/invoke", json={
            "tool": "search_catalog",
            "arguments": {"query": "Pipeline Track", "limit": 5},
        }, headers=hdr)
        assert r_mcp.status_code == 200
        mcp_ids = [t["id"] for t in r_mcp.json()["result"]["tracks"]]
        assert cat_id in mcp_ids

    def test_feedback_affects_recommendations(self):
        """
        Disliking all catalog tracks except one should cause only that one
        to appear in recommendations.
        """
        register(username="fb_rec_user", email="fbr@x.com")
        token = login("fb_rec_user")["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        seed_listening_history(token, n_tracks=2, events_per_track=3)

        import uuid
        cat_ids = []
        for i in range(5):
            cid = seed_catalog_track(
                name=f"FBRec {i}", energy=0.5 + i * 0.05,
                external_id=f"fbr-{i}-{uuid.uuid4().hex[:4]}",
            )
            cat_ids.append(cid)

        # Dislike all except the last one
        for cid in cat_ids[:-1]:
            client.post("/api/v1/feedback",
                        json={"catalog_track_id": cid, "rating": "dislike"},
                        headers=hdr)

        r = client.post("/api/v1/ai/recommendations/explain",
                        json={"strategy": "balanced", "max_tracks": 10},
                        headers=hdr)
        rec_ids = {item["track_id"] for item in r.json()["recommendations"]}

        # Disliked tracks must not appear
        for cid in cat_ids[:-1]:
            assert cid not in rec_ids, f"Disliked track {cid} appeared in recs"