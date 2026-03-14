"""
SQLAlchemy ORM models for Sonic Insights Hybrid.

This version keeps the original Spotify listening context tables and adds a
hybrid discovery catalog plus a clear CRUD model (`TrackFeedback`) and a
persisted `UserFingerprint`.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    JSON,
    Enum,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return uuid.uuid4().hex[:12]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    events = relationship("ListeningEvent", back_populates="user", cascade="all, delete-orphan")
    jobs = relationship("ImportJob", back_populates="user", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="user", cascade="all, delete-orphan")
    fingerprint = relationship(
        "UserFingerprint",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    feedback = relationship("TrackFeedback", back_populates="user", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    spotify_id = Column(String(64), unique=True, index=True)
    title = Column(String(300), nullable=False, index=True)
    artist = Column(String(300), nullable=False, index=True)
    album = Column(String(300))
    genre = Column(String(100), index=True)
    release_year = Column(Integer)
    duration_ms = Column(Integer)

    danceability = Column(Float)
    energy = Column(Float)
    valence = Column(Float)
    acousticness = Column(Float)
    instrumentalness = Column(Float)
    speechiness = Column(Float)
    liveness = Column(Float)
    loudness = Column(Float)
    tempo = Column(Float)

    created_at = Column(DateTime, default=_utcnow)

    events = relationship("ListeningEvent", back_populates="track")


class ListeningEvent(Base):
    __tablename__ = "listening_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    listened_at = Column(DateTime, default=_utcnow, index=True)
    duration_listened_ms = Column(Integer)
    source = Column(String(50), default="manual")

    user = relationship("User", back_populates="events")
    track = relationship("Track", back_populates="events")


class CatalogTrack(Base):
    __tablename__ = "catalog_tracks"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(300), nullable=False, index=True)
    artist = Column(String(300), nullable=False, index=True)
    album = Column(String(300))
    genre = Column(String(100), index=True)
    energy = Column(Float)
    valence = Column(Float)
    danceability = Column(Float)
    tempo = Column(Float)
    acousticness = Column(Float)
    instrumentalness = Column(Float)
    speechiness = Column(Float)
    liveness = Column(Float)
    source_dataset = Column(String(200), nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    feedback = relationship("TrackFeedback", back_populates="catalog_track")


class UserFingerprint(Base):
    __tablename__ = "user_fingerprints"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    label = Column(String(100), nullable=False)
    avg_energy = Column(Float, default=0.0)
    avg_valence = Column(Float, default=0.0)
    avg_danceability = Column(Float, default=0.0)
    avg_tempo = Column(Float, default=0.0)
    novelty_ratio = Column(Float, default=0.0)
    diversity_score = Column(Float, default=0.0)
    dominant_mood = Column(String(50))
    top_genres_json = Column(JSON, default=list)
    top_artists_json = Column(JSON, default=list)
    peak_hour = Column(Integer)
    total_events = Column(Integer, default=0)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="fingerprint")


class TrackFeedback(Base):
    __tablename__ = "track_feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_track_id = Column(Integer, ForeignKey("catalog_tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(String(20), nullable=False, index=True)  # like / dislike / save / skip
    note = Column(String(255))
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User", back_populates="feedback")
    catalog_track = relationship("CatalogTrack", back_populates="feedback")


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id = Column(String(12), primary_key=True, default=_uuid)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING)
    source = Column(String(50), default="spotify")
    time_range = Column(String(20), default="medium_term")
    tracks_found = Column(Integer, default=0)
    tracks_imported = Column(Integer, default=0)
    events_created = Column(Integer, default=0)
    errors = Column(JSON, default=list)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="jobs")


class Insight(Base):
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    insight_type = Column(String(50), default="hybrid")
    title = Column(String(200), default="Hybrid listening insight")
    insight_text = Column(Text, nullable=False)
    data_snapshot = Column(JSON, nullable=False)
    evidence = Column(JSON, default=list)
    model_used = Column(String(50), default="template")
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="insights")


# Legacy playlist tables kept so older migrations / code paths do not break.
class AIPlaylist(Base):
    __tablename__ = "ai_playlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    constraints = Column(JSON, nullable=False)
    track_ids = Column(JSON, default=list)
    explanation = Column(Text)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=_utcnow)




class InvalidatedToken(Base):
    """Blacklisted JWT tokens — used by logout to invalidate tokens before expiry."""
    __tablename__ = "invalidated_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    invalidated_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)

class PlaylistFeedback(Base):
    __tablename__ = "playlist_feedback"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("ai_playlists.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False)
    action = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=_utcnow)