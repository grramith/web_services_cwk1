import math
import statistics
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import CatalogTrack, User
from app.schemas import (
    AudioDNAFeature, CatalogAudioDNAResult, CatalogMoodMapResult,
    CatalogSearchResult, CatalogTrackRead, MoodQuadrantStat,
    MoodRecommendItem, MoodRecommendRequest, MoodRecommendResult,
    SimilarTrackItem, SimilarTracksResult,
)

router = APIRouter(prefix="/catalog", tags=["Catalog"])



FEATURES = ["energy", "valence", "danceability", "acousticness",
            "instrumentalness", "speechiness", "liveness"]
TEMPO_MAX = 250.0

FEATURE_DESCRIPTIONS = {
    "energy":           "Intensity and activity — higher means louder and faster",
    "valence":          "Musical positivity — higher means happier and more cheerful",
    "danceability":     "How suitable a track is for dancing based on tempo and rhythm",
    "acousticness":     "Confidence that the track is acoustic (unplugged)",
    "instrumentalness": "Predicts whether a track contains no vocals",
    "speechiness":      "Presence of spoken words — high values indicate rap or spoken word",
    "liveness":         "Likelihood the track was performed live",
    "tempo":            "Estimated tempo in BPM, normalised 0–1",
}

MOOD_KEYWORDS: dict[str, dict[str, Any]] = {
    "energetic": {"energy_min": 0.7},
    "hype":      {"energy_min": 0.75},
    "pump":      {"energy_min": 0.75},
    "workout":   {"energy_min": 0.7},
    "intense":   {"energy_min": 0.7},
    "loud":      {"energy_min": 0.65},
    "quiet":     {"energy_max": 0.4},
    "soft":      {"energy_max": 0.45},
    "gentle":    {"energy_max": 0.4},
    "calm":      {"energy_max": 0.45},
    "chill":     {"energy_max": 0.5},
    "relax":     {"energy_max": 0.5},
    "sleep":     {"energy_max": 0.35},
    "peaceful":  {"energy_max": 0.4},
    "background": {"energy_max": 0.5},
    "happy":     {"valence_min": 0.65},
    "upbeat":    {"valence_min": 0.6},
    "joyful":    {"valence_min": 0.7},
    "positive":  {"valence_min": 0.6},
    "fun":       {"valence_min": 0.6},
    "party":     {"valence_min": 0.6, "energy_min": 0.65},
    "sad":       {"valence_max": 0.4},
    "melancholy": {"valence_max": 0.4},
    "dark":      {"valence_max": 0.35},
    "gloomy":    {"valence_max": 0.4},
    "rainy":     {"valence_max": 0.45, "energy_max": 0.5},
    "heartbreak": {"valence_max": 0.4},
    "angry":     {"valence_max": 0.45, "energy_min": 0.65},
    "dance":     {"danceability_min": 0.7},
    "groove":    {"danceability_min": 0.65},
    "club":      {"danceability_min": 0.7, "energy_min": 0.65},
    "acoustic":  {"acousticness_min": 0.5},
    "unplugged": {"acousticness_min": 0.6},
    "organic":   {"acousticness_min": 0.5},
    "sunday":    {"acousticness_min": 0.3, "energy_max": 0.55},
    "morning":   {"energy_max": 0.6, "valence_min": 0.45},
    "night":     {"energy_max": 0.55},
    "late":      {"energy_max": 0.5},
    "study":     {"energy_max": 0.55, "speechiness_max": 0.1},
    "focus":     {"energy_max": 0.6, "speechiness_max": 0.1},
    "drive":     {"energy_min": 0.55},
    "road":      {"energy_min": 0.5},
}


def _mood_label(energy: float, valence: float) -> str:
    if energy >= 0.55 and valence >= 0.55:
        return "Happy"
    if energy >= 0.55 and valence < 0.55:
        return "Angry"
    if energy < 0.55 and valence >= 0.55:
        return "Calm"
    return "Sad"


def _safe_mean(vals: list) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _percentile(vals: list, p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (idx - lo), 4)


def _to_vector(track: CatalogTrack) -> list[float]:
    vec = [getattr(track, f) or 0.0 for f in FEATURES]
    vec.append((track.tempo or 0.0) / TEMPO_MAX)
    return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return round(dot / (mag_a * mag_b), 4)






@router.get("", response_model=CatalogSearchResult, summary="Search and filter the discovery catalog")
def search_catalog(
    q: Optional[str] = Query(None, description="Search by track name or artist (case-insensitive)"),
    genre: Optional[str] = Query(None, description="Filter by genre (e.g. pop, rock, hip hop)"),
    min_energy: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum energy value"),
    max_energy: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum energy value"),
    min_valence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum valence (positivity)"),
    max_valence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum valence (positivity)"),
    min_danceability: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum danceability"),
    max_danceability: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum danceability"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CatalogTrack)

    if q:
        pattern = f"%{q}%"
        query = query.filter(
            CatalogTrack.name.ilike(pattern) | CatalogTrack.artist.ilike(pattern)
        )
    if genre:
        query = query.filter(CatalogTrack.genre.ilike(f"%{genre}%"))
    if min_energy is not None:
        query = query.filter(CatalogTrack.energy >= min_energy)
    if max_energy is not None:
        query = query.filter(CatalogTrack.energy <= max_energy)
    if min_valence is not None:
        query = query.filter(CatalogTrack.valence >= min_valence)
    if max_valence is not None:
        query = query.filter(CatalogTrack.valence <= max_valence)
    if min_danceability is not None:
        query = query.filter(CatalogTrack.danceability >= min_danceability)
    if max_danceability is not None:
        query = query.filter(CatalogTrack.danceability <= max_danceability)

    total = query.count()
    items = query.order_by(CatalogTrack.name).offset(offset).limit(limit).all()

    return CatalogSearchResult(total=total, limit=limit, offset=offset, items=items)


@router.get("/mood-map", response_model=CatalogMoodMapResult,
            summary="Classify all catalog tracks into mood quadrants with deep statistics",
            description=(
                "Divides the entire catalog into four mood quadrants using the energy-valence "
                "plane: Happy (high energy + high valence), Angry (high energy + low valence), "
                "Calm (low energy + high valence), Sad (low energy + low valence). "
                "Returns per-quadrant statistics including track count, average audio features, "
                "and representative example tracks."
            ))
def get_mood_map(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = db.query(CatalogTrack).filter(
        CatalogTrack.energy.isnot(None),
        CatalogTrack.valence.isnot(None),
    ).all()

    if not tracks:
        raise HTTPException(404, "No catalog tracks found — run the catalog import first")

    buckets: dict[str, list] = defaultdict(list)
    for t in tracks:
        buckets[_mood_label(t.energy, t.valence)].append(t)

    total = len(tracks)
    quadrants = []
    for mood in ["Happy", "Calm", "Angry", "Sad"]:
        group = buckets.get(mood, [])
        if not group:
            continue
        energies = [t.energy for t in group if t.energy is not None]
        valences = [t.valence for t in group if t.valence is not None]
        danceabilities = [t.danceability for t in group if t.danceability is not None]
        examples = [f"{t.name} — {t.artist}" for t in group[:3]]
        quadrants.append(MoodQuadrantStat(
            mood=mood,
            count=len(group),
            percentage=round(len(group) / total * 100, 2),
            avg_energy=_safe_mean(energies),
            avg_valence=_safe_mean(valences),
            avg_danceability=_safe_mean(danceabilities),
            example_tracks=examples,
        ))

    most_common = max(quadrants, key=lambda x: x.count).mood
    descriptions = {
        "Happy": "Your catalog leans upbeat and energetic — great for workouts and parties.",
        "Calm":  "Your catalog leans calm and positive — ideal for studying and relaxing.",
        "Angry": "Your catalog leans intense and driven — perfect for focus and motivation.",
        "Sad":   "Your catalog leans reflective and mellow — suited for late nights.",
    }
    return CatalogMoodMapResult(
        total_tracks=total,
        quadrants=quadrants,
        most_common_mood=most_common,
        description=descriptions.get(most_common, "A balanced mood distribution."),
    )


@router.get("/audio-dna", response_model=CatalogAudioDNAResult,
            summary="Full statistical audio feature distribution across the entire catalog",
            description=(
                "Computes the complete statistical profile of every audio feature: mean, "
                "25th percentile, 75th percentile, min, and max across all catalog tracks. "
                "Also returns a per-genre fingerprint for direct comparison between styles."
            ))
def get_audio_dna(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = db.query(CatalogTrack).filter(
        CatalogTrack.energy.isnot(None)).all()

    if not tracks:
        raise HTTPException(404, "No catalog tracks found — run the catalog import first")

    feature_data: dict[str, list[float]] = defaultdict(list)
    for t in tracks:
        for f in FEATURES:
            v = getattr(t, f)
            if v is not None:
                feature_data[f].append(v)
        if t.tempo is not None:
            feature_data["tempo"].append(round(t.tempo / TEMPO_MAX, 4))

    features = []
    for f in FEATURES + ["tempo"]:
        vals = feature_data[f]
        if not vals:
            continue
        features.append(AudioDNAFeature(
            feature=f,
            mean=_safe_mean(vals),
            percentile_25=_percentile(vals, 25),
            percentile_75=_percentile(vals, 75),
            min_value=round(min(vals), 4),
            max_value=round(max(vals), 4),
            description=FEATURE_DESCRIPTIONS.get(f, f),
        ))

    genre_buckets: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for t in tracks:
        if not t.genre:
            continue
        g = t.genre.strip().lower()
        for f in FEATURES:
            v = getattr(t, f)
            if v is not None:
                genre_buckets[g][f].append(v)

    genre_fingerprints = {
        genre: {f: _safe_mean(vals) for f, vals in feat_map.items()}
        for genre, feat_map in genre_buckets.items()
        if len(feat_map.get("energy", [])) >= 3
    }

    energy_mean = next((f.mean for f in features if f.feature == "energy"), 0.5)
    valence_mean = next((f.mean for f in features if f.feature == "valence"), 0.5)
    dance_mean = next((f.mean for f in features if f.feature == "danceability"), 0.5)
    insight = (
        f"Across {len(tracks)} catalog tracks, the average energy is {energy_mean} "
        f"and average valence is {valence_mean}, placing the catalog in the "
        f"'{_mood_label(energy_mean, valence_mean)}' mood quadrant. "
        f"Average danceability is {dance_mean} across "
        f"{len(genre_fingerprints)} distinct genre fingerprints."
    )

    return CatalogAudioDNAResult(
        total_tracks=len(tracks),
        features=features,
        genre_fingerprints=genre_fingerprints,
        insight=insight,
    )


@router.post("/recommend-by-mood", response_model=MoodRecommendResult,
             summary="Natural language mood → ranked catalog recommendations",
             description=(
                 "Parses a free-text mood description (e.g. 'rainy sunday afternoon') into "
                 "audio feature targets using keyword matching, then ranks all matching catalog "
                 "tracks by cosine similarity to those targets. Combines NLP intent parsing "
                 "with 8-dimensional vector similarity search."
             ))
def recommend_by_mood(
    body: MoodRecommendRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    words = body.description.lower().replace(",", " ").replace(".", " ").split()
    targets: dict[str, float] = {}
    matched_keywords: list[str] = []

    for word in words:
        if word in MOOD_KEYWORDS:
            matched_keywords.append(word)
            for feature, value in MOOD_KEYWORDS[word].items():
                if feature in targets:
                    targets[feature] = round((targets[feature] + value) / 2, 3)
                else:
                    targets[feature] = value

    def _target_value(feature: str) -> float:
        min_k = f"{feature}_min"
        max_k = f"{feature}_max"
        if min_k in targets and max_k in targets:
            return (targets[min_k] + targets[max_k]) / 2
        if min_k in targets:
            return min(targets[min_k] + 0.1, 1.0)
        if max_k in targets:
            return max(targets[max_k] - 0.1, 0.0)
        return 0.5

    target_vec = [_target_value(f) for f in FEATURES] + [0.5]

    query = db.query(CatalogTrack).filter(
        CatalogTrack.energy.isnot(None),
        CatalogTrack.valence.isnot(None),
    )
    if "energy_min" in targets:
        query = query.filter(CatalogTrack.energy >= targets["energy_min"])
    if "energy_max" in targets:
        query = query.filter(CatalogTrack.energy <= targets["energy_max"])
    if "valence_min" in targets:
        query = query.filter(CatalogTrack.valence >= targets["valence_min"])
    if "valence_max" in targets:
        query = query.filter(CatalogTrack.valence <= targets["valence_max"])
    if "danceability_min" in targets:
        query = query.filter(CatalogTrack.danceability >= targets["danceability_min"])
    if "acousticness_min" in targets:
        query = query.filter(CatalogTrack.acousticness >= targets["acousticness_min"])
    if "speechiness_max" in targets:
        query = query.filter(CatalogTrack.speechiness <= targets["speechiness_max"])
    if body.genre:
        query = query.filter(CatalogTrack.genre.ilike(f"%{body.genre}%"))

    candidates = query.all()
    scored = sorted(
        [(t, _cosine_similarity(target_vec, _to_vector(t))) for t in candidates],
        key=lambda x: -x[1],
    )

    results = [
        MoodRecommendItem(
            id=t.id, name=t.name, artist=t.artist, genre=t.genre,
            energy=t.energy, valence=t.valence,
            danceability=t.danceability, tempo=t.tempo,
            mood_match_score=score,
            matched_keywords=matched_keywords,
            mood_label=_mood_label(t.energy or 0.5, t.valence or 0.5),
        )
        for t, score in scored[:body.limit]
    ]

    return MoodRecommendResult(
        description=body.description,
        interpreted_targets={k: round(v, 3) for k, v in targets.items()},
        matched_keywords=matched_keywords,
        total_candidates=len(candidates),
        results=results,
    )



@router.get("/{track_id}", response_model=CatalogTrackRead, summary="Get a single catalog track by ID")
def get_catalog_track(
    track_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Catalog track not found")
    return track


@router.get(
    "/{track_id}/similar",
    summary="Find catalog tracks similar to a given track using cosine similarity",
    description=(
        "Computes cosine similarity across 8 audio features (energy, valence, danceability, "
        "tempo, acousticness, instrumentalness, speechiness, liveness) to find the closest "
        "matches to the seed track in the catalog."
    ),
)
def get_similar_tracks(
    track_id: int,
    limit: int = Query(10, ge=1, le=50, description="Number of similar tracks to return"),
    same_genre: bool = Query(False, description="Restrict results to the same genre"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import math
    from app.schemas import SimilarTrackItem, SimilarTracksResult

    seed = db.query(CatalogTrack).filter(CatalogTrack.id == track_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Catalog track not found")

    # Audio feature vector definition — order matters for cosine similarity
    FEATURES = ["energy", "valence", "danceability", "acousticness",
                "instrumentalness", "speechiness", "liveness"]
    # Tempo lives on a different scale (0-250 BPM) so normalise it to 0-1
    TEMPO_MAX = 250.0

    def to_vector(track: CatalogTrack) -> list[float]:
        vec = [getattr(track, f) or 0.0 for f in FEATURES]
        vec.append((track.tempo or 0.0) / TEMPO_MAX)
        return vec

    def cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return round(dot / (mag_a * mag_b), 4)

    def feature_breakdown(seed_vec: list[float], candidate_vec: list[float]) -> dict:
        all_features = FEATURES + ["tempo_norm"]
        return {
            f: round(1.0 - abs(seed_vec[i] - candidate_vec[i]), 4)
            for i, f in enumerate(all_features)
        }

    seed_vec = to_vector(seed)

    query = db.query(CatalogTrack).filter(CatalogTrack.id != seed.id)
    if same_genre and seed.genre:
        query = query.filter(CatalogTrack.genre.ilike(f"%{seed.genre}%"))

    candidates = query.all()

    scored = []
    for track in candidates:
        candidate_vec = to_vector(track)
        score = cosine_similarity(seed_vec, candidate_vec)
        scored.append((track, score, candidate_vec))

    scored.sort(key=lambda x: -x[1])

    results = [
        SimilarTrackItem(
            id=track.id,
            name=track.name,
            artist=track.artist,
            genre=track.genre,
            energy=track.energy,
            valence=track.valence,
            danceability=track.danceability,
            tempo=track.tempo,
            similarity_score=score,
            feature_breakdown=feature_breakdown(seed_vec, vec),
        )
        for track, score, vec in scored[:limit]
    ]

    return SimilarTracksResult(
        seed_track_id=seed.id,
        seed_name=seed.name,
        seed_artist=seed.artist,
        algorithm="cosine-similarity-8d-audio-features",
        results=results,
    )