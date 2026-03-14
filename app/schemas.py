"""Pydantic schemas for Sonic Insights Hybrid."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Auth
class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# Imports
class ImportStartRequest(BaseModel):
    spotify_token: str
    time_range: str = Field("all", pattern="^(short_term|medium_term|long_term|all)$")
    include_recently_played: bool = True
    include_saved_tracks: bool = True
    saved_tracks_max_pages: int = Field(5, ge=1, le=20)
    synthesise_history: bool = True


class CatalogImportRequest(BaseModel):
    dataset_slug: str = "ramithgajjala/ramith-top-songs"
    file_path: str = "ramith-top-songs.csv"


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: int
    status: str
    source: str
    time_range: str
    tracks_found: int
    tracks_imported: int
    events_created: int
    errors: List[Any]
    started_at: datetime
    completed_at: Optional[datetime] = None


class CatalogImportResult(BaseModel):
    status: str
    dataset: str
    imported_by: str
    inserted: int
    updated: int
    total_rows: int


# Feedback CRUD
class FeedbackCreate(BaseModel):
    catalog_track_id: int
    rating: str = Field(..., pattern="^(like|dislike|save|skip)$")
    note: Optional[str] = Field(None, max_length=255)


class FeedbackUpdate(BaseModel):
    rating: Optional[str] = Field(None, pattern="^(like|dislike|save|skip)$")
    note: Optional[str] = Field(None, max_length=255)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    catalog_track_id: int
    rating: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class FeedbackListItem(FeedbackRead):
    track_name: Optional[str] = None
    artist: Optional[str] = None
    genre: Optional[str] = None


# Analytics / fingerprint
class OverviewResult(BaseModel):
    user_id: int
    total_events: int
    unique_spotify_tracks: int
    unique_catalog_feedback_tracks: int
    avg_energy: Optional[float] = None
    avg_valence: Optional[float] = None
    dominant_mood: Optional[str] = None
    fingerprint_label: Optional[str] = None


class HighlightResult(BaseModel):
    top_artist: Optional[str] = None
    top_genre: Optional[str] = None
    novelty_ratio: float
    diversity_score: float
    peak_hour: Optional[str] = None
    dominant_mood: Optional[str] = None


class FingerprintTraits(BaseModel):
    avg_energy: float
    avg_valence: float
    avg_danceability: float
    avg_tempo: float
    novelty_ratio: float
    diversity_score: float
    dominant_mood: Optional[str] = None
    peak_hour: Optional[str] = None
    total_events: int
    top_artists: List[str]
    top_genres: List[str]


class FingerprintResult(BaseModel):
    fingerprint_label: str
    traits: FingerprintTraits
    explanation: str
    evidence: List[Dict[str, Any]]


class ChangeMetric(BaseModel):
    metric: str
    previous: Any
    recent: Any
    delta: Optional[float] = None


class RecentChangesResult(BaseModel):
    previous_window: str
    recent_window: str
    fingerprint_shift: str
    summary: str
    metrics: List[ChangeMetric]
    evidence: List[Dict[str, Any]]


# AI / recommendations / insights
class RecommendationExplainRequest(BaseModel):
    context: Optional[str] = Field(None, max_length=200)
    strategy: str = Field("balanced", pattern="^(balanced|discovery|comfort)$")
    max_tracks: int = Field(5, ge=1, le=20)


class WhatIfRecommendationRequest(BaseModel):
    scenario: str = Field(..., min_length=5, max_length=200)
    max_tracks: int = Field(5, ge=1, le=20)


class RecommendationItem(BaseModel):
    track_id: int
    title: str
    artist: str
    genre: Optional[str] = None
    fit_score: float
    novelty_score: float
    familiarity: str
    why: str


class RecommendationExplainResult(BaseModel):
    fingerprint_label: str
    strategy: str
    context: Optional[str] = None
    recommendations: List[RecommendationItem]
    summary: str


class InsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    user_id: int
    insight_type: str
    title: str
    insight_text: str
    data_snapshot: Dict[str, Any]
    evidence: List[Any]
    model_used: str
    created_at: datetime


class InsightCritiqueIssue(BaseModel):
    issue_type: str
    severity: str
    message: str


class InsightCritiqueResult(BaseModel):
    insight_id: int
    overall_verdict: str
    issues: List[InsightCritiqueIssue]
    improved_excerpt: str
    grounding_score: float


# Catalog
class CatalogTrackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: str
    name: str
    artist: str
    album: Optional[str] = None
    genre: Optional[str] = None
    energy: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    tempo: Optional[float] = None
    acousticness: Optional[float] = None
    instrumentalness: Optional[float] = None
    speechiness: Optional[float] = None
    liveness: Optional[float] = None
    source_dataset: str
    created_at: datetime


class CatalogSearchResult(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[CatalogTrackRead]


# Genre analytics
class GenreStat(BaseModel):
    genre: str
    track_count: int
    avg_energy: Optional[float] = None
    avg_valence: Optional[float] = None
    avg_danceability: Optional[float] = None
    avg_tempo: Optional[float] = None


class GenreBreakdownResult(BaseModel):
    total_genres: int
    genres: List[GenreStat]


# Similarity search
class SimilarTrackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    artist: str
    genre: Optional[str] = None
    energy: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    tempo: Optional[float] = None
    similarity_score: float
    feature_breakdown: Dict[str, float]


class SimilarTracksResult(BaseModel):
    seed_track_id: int
    seed_name: str
    seed_artist: str
    algorithm: str
    results: List[SimilarTrackItem]


# Listening Events
class EventCreate(BaseModel):
    track_id: int
    listened_at: Optional[datetime] = None
    duration_listened_ms: Optional[int] = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    track_id: int
    listened_at: datetime
    duration_listened_ms: Optional[int] = None
    source: Optional[str] = None


class EventUpdate(BaseModel):
    listened_at: Optional[datetime] = None
    duration_listened_ms: Optional[int] = None


class EventList(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[EventRead]


# Analytics — Top
class TopItem(BaseModel):
    name: str
    count: int


class TopResult(BaseModel):
    entity: str
    k: int
    items: List[TopItem]


# Analytics — Heatmap
class HeatmapCell(BaseModel):
    bucket: str
    count: int


class HeatmapResult(BaseModel):
    bucket_type: str
    cells: List[HeatmapCell]


# Analytics — Transitions
class TransitionItem(BaseModel):
    from_track: str
    to_track: str
    count: int
    avg_valence_shift: Optional[float] = None


class TransitionsResult(BaseModel):
    total_transitions: int
    top_transitions: List[TransitionItem]


# Analytics — Novelty
class NoveltyResult(BaseModel):
    novelty_ratio: float
    novelty_label: str
    unique_tracks: int
    total_events: int


# Analytics — Mood Profile
class MoodProfileItem(BaseModel):
    mood: str
    count: int
    percentage: float


class MoodProfileResult(BaseModel):
    total_events: int
    dominant_mood: Optional[str] = None
    items: List[MoodProfileItem]


# Analytics — Compare
class CompareMetric(BaseModel):
    metric: str
    period_a: Any
    period_b: Any
    delta: Optional[float] = None


class CompareResult(BaseModel):
    period_a: str
    period_b: str
    metrics: List[CompareMetric]
    summary: str


# Updated Overview (add fields tests expect)
class OverviewResultV2(BaseModel):
    user_id: int
    total_events: int
    unique_tracks: int
    unique_genres: int
    unique_spotify_tracks: int
    unique_catalog_feedback_tracks: int
    avg_energy: Optional[float] = None
    avg_valence: Optional[float] = None
    dominant_mood: Optional[str] = None
    fingerprint_label: Optional[str] = None


# AI Query
class AIQueryRequest(BaseModel):
    question: str


class AIQueryResult(BaseModel):
    question: str
    query_type: str
    results: List[Any]
    summary: str


# AI Playlists
class PlaylistCreate(BaseModel):
    mood: str = Field(..., description="Mood for playlist e.g. happy, calm, intense, sad")
    max_tracks: int = Field(10, ge=1, le=50)
    genre: Optional[str] = None


class PlaylistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    track_ids: List[int]
    explanation: Optional[str] = None
    version: int
    created_at: datetime


class PlaylistRegenerateRequest(BaseModel):
    feedback: Optional[str] = None


class PlaylistFeedbackCreate(BaseModel):
    track_id: int
    action: str = Field(..., pattern="^(like|dislike|skip)$")


class PlaylistFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    playlist_id: int
    track_id: int
    action: str
    created_at: datetime


# AI Eval
class EvalCheck(BaseModel):
    check: str
    passed: bool
    detail: str


class EvalResult(BaseModel):
    insight_id: int
    overall_score: float
    checks: List[EvalCheck]
    verdict: str


# ── Catalog Mood Map ─────────────────────────────────────────────────────────
class MoodQuadrantStat(BaseModel):
    mood: str
    count: int
    percentage: float
    avg_energy: float
    avg_valence: float
    avg_danceability: float
    example_tracks: List[str]


class CatalogMoodMapResult(BaseModel):
    total_tracks: int
    quadrants: List[MoodQuadrantStat]
    most_common_mood: str
    description: str


# ── Catalog Audio DNA ────────────────────────────────────────────────────────
class AudioDNAFeature(BaseModel):
    feature: str
    mean: float
    percentile_25: float
    percentile_75: float
    min_value: float
    max_value: float
    description: str


class CatalogAudioDNAResult(BaseModel):
    total_tracks: int
    features: List[AudioDNAFeature]
    genre_fingerprints: Dict[str, Dict[str, float]]
    insight: str


# ── Catalog Mood Recommendation ──────────────────────────────────────────────
class MoodRecommendRequest(BaseModel):
    description: str = Field(
        ..., min_length=3, max_length=300,
        description="Natural language mood e.g. 'rainy sunday afternoon'"
    )
    limit: int = Field(10, ge=1, le=50)
    genre: Optional[str] = None


class MoodRecommendItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    artist: str
    genre: Optional[str] = None
    energy: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    tempo: Optional[float] = None
    mood_match_score: float
    matched_keywords: List[str]
    mood_label: str


class MoodRecommendResult(BaseModel):
    description: str
    interpreted_targets: Dict[str, Any]
    matched_keywords: List[str]
    total_candidates: int
    results: List[MoodRecommendItem]