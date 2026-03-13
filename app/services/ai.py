"""
AI service layer.

Design principles
-----------------
- Deterministic analytics first, LLM explanation second.
- No raw SQL generation from model outputs.
- Every AI feature returns structured evidence for explainability.
- Fallback templates keep the API functional without an OpenAI key.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests as http_requests
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AIPlaylist, Insight, ListeningEvent, PlaylistFeedback, Track
from app.schemas import (
    AIQueryResult,
    ChangeMetric,
    EvalCheck,
    EvalResult,
    FingerprintResult,
    FingerprintTraits,
    InsightCritiqueIssue,
    InsightCritiqueResult,
    MoodTrajectoryPoint,
    MoodTrajectoryResult,
    RecentChangesResult,
    RecommendationExplainResult,
    RecommendationItem,
)
from app.services import analytics as analytics_svc

logger = logging.getLogger(__name__)

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

VAGUE_TERMS = [
    "interesting",
    "nice",
    "better",
    "good",
    "strong",
    "varied",
    "diverse",
    "positive",
    "negative",
    "balanced",
    "unique",
]


# =====================================================================
# Shared helpers
# =====================================================================
def _llm_chat(prompt: str, *, max_tokens: int = 220, temperature: float = 0.2) -> Optional[str]:
    if not settings.OPENAI_API_KEY:
        return None
    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        logger.warning("LLM call returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
    return None


def _llm_json(prompt: str) -> Optional[dict[str, Any]]:
    if not settings.OPENAI_API_KEY:
        return None
    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 180,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return json.loads(resp.json()["choices"][0]["message"]["content"])
        logger.warning("LLM JSON call returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("LLM JSON call failed: %s", exc)
    return None


def _mood_label(energy: float, valence: float) -> str:
    if energy >= 0.5 and valence >= 0.5:
        return "Happy"
    if energy >= 0.5:
        return "Intense"
    if valence >= 0.5:
        return "Calm"
    return "Introspective"


def _safe_mean(values: list[float], default: float = 0.0) -> float:
    return round(statistics.mean(values), 4) if values else default


def _norm_entropy(labels: list[str]) -> float:
    if not labels:
        return 0.0
    counts = Counter(labels)
    total = sum(counts.values())
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
    return round(entropy / max_entropy, 4) if max_entropy else 0.0


def _base_events_query(db: Session, user_id: int, dt_from: Optional[datetime] = None, dt_to: Optional[datetime] = None):
    q = db.query(ListeningEvent).filter(ListeningEvent.user_id == user_id)
    if dt_from is not None:
        q = q.filter(ListeningEvent.listened_at >= dt_from)
    if dt_to is not None:
        q = q.filter(ListeningEvent.listened_at <= dt_to)
    return q


def _load_events_and_tracks(
    db: Session,
    user_id: int,
    dt_from: Optional[datetime] = None,
    dt_to: Optional[datetime] = None,
) -> tuple[list[ListeningEvent], dict[int, Track]]:
    events = _base_events_query(db, user_id, dt_from, dt_to).order_by(ListeningEvent.listened_at).all()
    track_ids = {e.track_id for e in events}
    tracks = {
        t.id: t
        for t in db.query(Track).filter(Track.id.in_(track_ids)).all()
    } if track_ids else {}
    return events, tracks


def _fingerprint_metrics(
    db: Session,
    user_id: int,
    dt_from: Optional[datetime] = None,
    dt_to: Optional[datetime] = None,
) -> dict[str, Any]:
    events, tracks = _load_events_and_tracks(db, user_id, dt_from, dt_to)
    if not events:
        raise HTTPException(status_code=400, detail="Need listening history before generating AI outputs")

    energies, valences, genres, artists = [], [], [], []
    hour_counts: Counter[int] = Counter()
    mood_counts: Counter[str] = Counter()
    repeated_counter: Counter[int] = Counter(e.track_id for e in events)

    for event in events:
        track = tracks.get(event.track_id)
        if not track:
            continue
        if track.energy is not None:
            energies.append(track.energy)
        if track.valence is not None:
            valences.append(track.valence)
        if track.genre:
            genres.append(track.genre)
        if track.artist:
            artists.append(track.artist)
        if event.listened_at:
            hour_counts[event.listened_at.hour] += 1
        if track.energy is not None and track.valence is not None:
            mood_counts[_mood_label(track.energy, track.valence)] += 1

    avg_energy = _safe_mean(energies, 0.5)
    avg_valence = _safe_mean(valences, 0.5)
    novelty_ratio = round(len(set(e.track_id for e in events)) / len(events), 4) if events else 0.0
    diversity_score = _norm_entropy(genres or artists)
    dominant_mood = mood_counts.most_common(1)[0][0] if mood_counts else None
    top_artist = Counter(artists).most_common(1)[0][0] if artists else None
    top_genre = Counter(genres).most_common(1)[0][0] if genres else None
    peak_hour = f"{hour_counts.most_common(1)[0][0]:02d}:00" if hour_counts else None
    replay_concentration = repeated_counter.most_common(1)[0][1] / len(events) if events else 0.0

    if novelty_ratio >= 0.65:
        exploration_tendency = "Exploration-heavy"
    elif novelty_ratio >= 0.4:
        exploration_tendency = "Balanced"
    else:
        exploration_tendency = "Comfort-seeking"

    if avg_energy >= 0.65 and novelty_ratio >= 0.55:
        label = "Energetic Explorer"
    elif avg_energy < 0.45 and avg_valence >= 0.5:
        label = "Calm Curator"
    elif avg_energy >= 0.6 and avg_valence < 0.45:
        label = "Intensity Chaser"
    elif avg_valence < 0.45 and novelty_ratio < 0.45:
        label = "Reflective Loyalist"
    else:
        label = "Balanced Listener"

    evidence = [
        {"claim": "Average energy", "support": avg_energy},
        {"claim": "Average valence", "support": avg_valence},
        {"claim": "Novelty ratio", "support": novelty_ratio},
        {"claim": "Diversity score", "support": diversity_score},
        {"claim": "Dominant mood", "support": dominant_mood},
        {"claim": "Top artist", "support": top_artist},
        {"claim": "Top genre", "support": top_genre},
        {"claim": "Peak hour", "support": peak_hour},
        {"claim": "Replay concentration", "support": round(replay_concentration, 4)},
    ]

    return {
        "period_start": dt_from.isoformat() if dt_from else "all-time",
        "period_end": dt_to.isoformat() if dt_to else "now",
        "total_events": len(events),
        "avg_energy": avg_energy,
        "avg_valence": avg_valence,
        "novelty_ratio": novelty_ratio,
        "diversity_score": diversity_score,
        "dominant_mood": dominant_mood,
        "peak_hour": peak_hour,
        "top_artist": top_artist,
        "top_genre": top_genre,
        "exploration_tendency": exploration_tendency,
        "label": label,
        "evidence": evidence,
        "replay_concentration": round(replay_concentration, 4),
    }


def _fingerprint_explanation(metrics: dict[str, Any]) -> str:
    prompt = (
        "Write a concise 3 sentence explanation of this music fingerprint. "
        "Stay grounded in the supplied metrics and avoid hype.\n\n"
        f"Fingerprint: {json.dumps(metrics)}"
    )
    llm_text = _llm_chat(prompt, max_tokens=140, temperature=0.2)
    if llm_text:
        return llm_text
    return (
        f"This listener fits the '{metrics['label']}' profile because their average energy is "
        f"{metrics['avg_energy']} and novelty ratio is {metrics['novelty_ratio']}. "
        f"Their dominant mood is {metrics['dominant_mood'] or 'unclear'}, with strongest activity at "
        f"{metrics['peak_hour'] or 'unknown times'}. "
        f"Top affinity currently centres on {metrics['top_artist'] or 'mixed artists'} and "
        f"{metrics['top_genre'] or 'mixed genres'}."
    )


# =====================================================================
# 1. Fingerprint + behaviour intelligence
# =====================================================================
def get_fingerprint(db: Session, user_id: int) -> FingerprintResult:
    metrics = _fingerprint_metrics(db, user_id)
    traits = FingerprintTraits(
        avg_energy=metrics["avg_energy"],
        avg_valence=metrics["avg_valence"],
        novelty_ratio=metrics["novelty_ratio"],
        diversity_score=metrics["diversity_score"],
        dominant_mood=metrics["dominant_mood"],
        peak_hour=metrics["peak_hour"],
        top_artist=metrics["top_artist"],
        top_genre=metrics["top_genre"],
        exploration_tendency=metrics["exploration_tendency"],
    )
    return FingerprintResult(
        period_start=metrics["period_start"],
        period_end=metrics["period_end"],
        fingerprint_label=metrics["label"],
        traits=traits,
        explanation=_fingerprint_explanation(metrics),
        evidence=metrics["evidence"],
    )


# =====================================================================
# 2. Grounded insight generation
# =====================================================================
def generate_insight(db: Session, user_id: int) -> Insight:
    metrics = _fingerprint_metrics(db, user_id)
    snapshot = {
        "total_events": metrics["total_events"],
        "avg_energy": metrics["avg_energy"],
        "avg_valence": metrics["avg_valence"],
        "novelty_ratio": metrics["novelty_ratio"],
        "diversity_score": metrics["diversity_score"],
        "dominant_mood": metrics["dominant_mood"],
        "peak_hour": metrics["peak_hour"],
        "top_artist": metrics["top_artist"],
        "top_genre": metrics["top_genre"],
        "fingerprint_label": metrics["label"],
    }
    evidence = metrics["evidence"]
    insight_text = _call_llm(snapshot, evidence)
    model_used = "openai" if settings.OPENAI_API_KEY else "template"

    record = Insight(
        user_id=user_id,
        insight_text=insight_text,
        data_snapshot=snapshot,
        evidence=evidence,
        model_used=model_used,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _call_llm(snapshot: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    prompt = (
        "You are an explainable music analytics assistant. Write a compact 4 sentence insight. "
        "Every sentence must be grounded in the provided metrics or evidence. Mention specific values.\n\n"
        f"Snapshot: {json.dumps(snapshot)}\nEvidence: {json.dumps(evidence)}"
    )
    llm_text = _llm_chat(prompt, max_tokens=220, temperature=0.3)
    return llm_text or _template_insight(snapshot)


def _template_insight(snapshot: dict[str, Any]) -> str:
    return (
        f"Your current fingerprint is '{snapshot.get('fingerprint_label', 'Balanced Listener')}', "
        f"with average energy {snapshot.get('avg_energy', 0.5)} and valence {snapshot.get('avg_valence', 0.5)}. "
        f"You listen most to {snapshot.get('top_artist', 'mixed artists')} and lean toward "
        f"{snapshot.get('top_genre', 'mixed genres')}. "
        f"A novelty ratio of {snapshot.get('novelty_ratio', 0.0)} and diversity score of "
        f"{snapshot.get('diversity_score', 0.0)} suggest {snapshot.get('fingerprint_label', 'a stable')} taste profile. "
        f"Your dominant mood is {snapshot.get('dominant_mood', 'unclear')} and your peak listening hour is "
        f"{snapshot.get('peak_hour', 'unknown')}.")


# =====================================================================
# 3. Behaviour shift / mood trajectory
# =====================================================================
def recent_changes(db: Session, user_id: int, days: int = 30) -> RecentChangesResult:
    now = datetime.now(timezone.utc)
    previous_start = now - timedelta(days=days * 2)
    previous_end = now - timedelta(days=days)
    recent_start = now - timedelta(days=days)

    previous = _fingerprint_metrics(db, user_id, previous_start, previous_end)
    recent = _fingerprint_metrics(db, user_id, recent_start, now)

    def delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None:
            return None
        return round(b - a, 4)

    metrics = [
        ChangeMetric(metric="avg_energy", previous=previous["avg_energy"], recent=recent["avg_energy"], delta=delta(previous["avg_energy"], recent["avg_energy"])),
        ChangeMetric(metric="avg_valence", previous=previous["avg_valence"], recent=recent["avg_valence"], delta=delta(previous["avg_valence"], recent["avg_valence"])),
        ChangeMetric(metric="novelty_ratio", previous=previous["novelty_ratio"], recent=recent["novelty_ratio"], delta=delta(previous["novelty_ratio"], recent["novelty_ratio"])),
        ChangeMetric(metric="diversity_score", previous=previous["diversity_score"], recent=recent["diversity_score"], delta=delta(previous["diversity_score"], recent["diversity_score"])),
        ChangeMetric(metric="dominant_mood", previous=previous["dominant_mood"], recent=recent["dominant_mood"]),
        ChangeMetric(metric="top_genre", previous=previous["top_genre"], recent=recent["top_genre"]),
        ChangeMetric(metric="top_artist", previous=previous["top_artist"], recent=recent["top_artist"]),
    ]

    changes = []
    energy_delta = delta(previous["avg_energy"], recent["avg_energy"])
    novelty_delta = delta(previous["novelty_ratio"], recent["novelty_ratio"])
    valence_delta = delta(previous["avg_valence"], recent["avg_valence"])

    if energy_delta is not None:
        if energy_delta > 0.08:
            changes.append("your listening became more energetic")
        elif energy_delta < -0.08:
            changes.append("your listening became calmer")
    if valence_delta is not None:
        if valence_delta > 0.08:
            changes.append("your music became more positive")
        elif valence_delta < -0.08:
            changes.append("your music became more introspective")
    if novelty_delta is not None:
        if novelty_delta > 0.08:
            changes.append("you explored more unfamiliar tracks")
        elif novelty_delta < -0.08:
            changes.append("you leaned back toward familiar favourites")
    if previous["top_genre"] != recent["top_genre"] and previous["top_genre"] and recent["top_genre"]:
        changes.append(f"your top genre shifted from {previous['top_genre']} to {recent['top_genre']}")
    if not changes:
        changes.append("your listening behaviour was broadly stable")

    summary_prompt = (
        "Write a concise explanation of a user's recent taste shift using these metrics. "
        "Be specific and grounded.\n\n"
        f"Previous: {json.dumps(previous)}\nRecent: {json.dumps(recent)}"
    )
    summary = _llm_chat(summary_prompt, max_tokens=170, temperature=0.2) or ("; ".join(changes).capitalize() + ".")

    shift = f"{previous['label']} → {recent['label']}" if previous['label'] != recent['label'] else previous['label']
    evidence = [
        {"claim": "Previous fingerprint", "support": previous["label"]},
        {"claim": "Recent fingerprint", "support": recent["label"]},
        {"claim": "Energy delta", "support": energy_delta},
        {"claim": "Valence delta", "support": valence_delta},
        {"claim": "Novelty delta", "support": novelty_delta},
    ]

    return RecentChangesResult(
        previous_window=f"{previous_start.date().isoformat()} to {previous_end.date().isoformat()}",
        recent_window=f"{recent_start.date().isoformat()} to {now.date().isoformat()}",
        fingerprint_shift=shift,
        summary=summary,
        metrics=metrics,
        evidence=evidence,
    )


def mood_trajectory(db: Session, user_id: int, window_days: int = 14, points: int = 6) -> MoodTrajectoryResult:
    now = datetime.now(timezone.utc)
    out_points: list[MoodTrajectoryPoint] = []
    summaries = []

    for idx in range(points):
        end = now - timedelta(days=window_days * (points - idx - 1))
        start = end - timedelta(days=window_days)
        try:
            metrics = _fingerprint_metrics(db, user_id, start, end)
            out_points.append(
                MoodTrajectoryPoint(
                    label=f"{start.date().isoformat()} → {end.date().isoformat()}",
                    dominant_mood=metrics["dominant_mood"],
                    avg_energy=metrics["avg_energy"],
                    avg_valence=metrics["avg_valence"],
                    total_events=metrics["total_events"],
                )
            )
        except HTTPException:
            out_points.append(
                MoodTrajectoryPoint(
                    label=f"{start.date().isoformat()} → {end.date().isoformat()}",
                    total_events=0,
                )
            )

    dominant_sequence = [p.dominant_mood for p in out_points if p.dominant_mood]
    if dominant_sequence:
        summaries.append(f"Most frequent mood across windows was {Counter(dominant_sequence).most_common(1)[0][0]}")
    valid_energy = [p.avg_energy for p in out_points if p.avg_energy is not None]
    if len(valid_energy) >= 2:
        drift = round(valid_energy[-1] - valid_energy[0], 4)
        if drift > 0.08:
            summaries.append(f"energy trended upward by {drift}")
        elif drift < -0.08:
            summaries.append(f"energy trended downward by {drift}")
        else:
            summaries.append("energy stayed broadly stable")

    return MoodTrajectoryResult(
        window_days=window_days,
        points=out_points,
        summary=("; ".join(summaries).capitalize() + ".") if summaries else "Not enough mood data yet.",
    )


# =====================================================================
# 4. Query classification / NL analytics
# =====================================================================
def _classify_query_with_llm(question: str) -> dict[str, Any]:
    prompt = f"""
You are an intent classifier for a music analytics API.
Classify the user question into exactly one of:
- top
- bottom
- mood
- temporal
- count
- discovery
- feature_low
- recommendation
- unsupported
- fingerprint
- change
- fallback

Also extract:
- entity: track | artist | genre | null
- feature: energy | valence | null

Return strict JSON only in this form:
{{
  "intent": "top",
  "entity": "artist",
  "feature": null,
  "reason": "..."
}}

Question: {question}
""".strip()
    data = _llm_json(prompt)
    if data:
        return data
    return {"intent": "fallback_rule_based"}


def ai_query(db: Session, user_id: int, question: str) -> AIQueryResult:
    classification = _classify_query_with_llm(question)
    intent = classification.get("intent")
    entity = classification.get("entity")
    feature = classification.get("feature")

    if intent == "fingerprint":
        fp = get_fingerprint(db, user_id)
        return AIQueryResult(
            question=question,
            interpreted_as="Listening fingerprint query",
            results=[fp.model_dump()],
            explanation=fp.explanation,
            query_type="fingerprint",
        )
    if intent == "change":
        ch = recent_changes(db, user_id)
        return AIQueryResult(
            question=question,
            interpreted_as="Recent taste change query",
            results=[ch.model_dump()],
            explanation=ch.summary,
            query_type="change",
        )
    if intent == "top":
        return _query_top(db, user_id, question, f"top {entity or 'track'}")
    if intent == "bottom":
        return _query_bottom(db, user_id, question, f"least played {entity or 'track'}")
    if intent == "mood":
        return _query_mood(db, user_id, question)
    if intent == "temporal":
        return _query_when(db, user_id, question)
    if intent == "count":
        return _query_count(db, user_id, question)
    if intent == "discovery":
        return _query_discoveries(db, user_id, question)
    if intent == "feature_low":
        feature_name = "energy" if feature == "energy" else "valence"
        return _query_lowest_feature(db, user_id, question, feature_name, f"lowest-{feature_name}")
    if intent == "recommendation":
        return AIQueryResult(
            question=question,
            interpreted_as="Recommendation request",
            results=[
                {
                    "recommended_endpoint": "/api/v1/ai/recommendations/explain",
                    "alternative_endpoint": "/api/v1/ai/recommendations/what-if",
                }
            ],
            explanation="This question is best answered by the explainable recommendation endpoints rather than analytics query routing.",
            query_type="recommendation_redirect",
        )
    if intent == "unsupported":
        return AIQueryResult(
            question=question,
            interpreted_as="Unsupported preference query",
            results=[],
            explanation="The API cannot infer hidden dislikes or quality judgements from listening history alone.",
            query_type="unsupported",
        )

    ql = question.lower().strip()
    if any(k in ql for k in ["fingerprint", "profile", "taste profile"]):
        fp = get_fingerprint(db, user_id)
        return AIQueryResult(question=question, interpreted_as="Listening fingerprint query", results=[fp.model_dump()], explanation=fp.explanation, query_type="fingerprint")
    if any(k in ql for k in ["changed", "shift", "drift", "recently changed"]):
        ch = recent_changes(db, user_id)
        return AIQueryResult(question=question, interpreted_as="Recent taste change query", results=[ch.model_dump()], explanation=ch.summary, query_type="change")
    if any(k in ql for k in ["better songs", "recommend", "what should i listen to"]):
        return AIQueryResult(
            question=question,
            interpreted_as="Recommendation request",
            results=[{"recommended_endpoint": "/api/v1/ai/recommendations/explain"}],
            explanation="Use the explainable recommendation endpoints for recommendation-style requests.",
            query_type="recommendation_redirect",
        )
    if any(k in ql for k in ["most played", "top", "favourite", "favorite"]):
        return _query_top(db, user_id, question, ql)
    if any(k in ql for k in ["least played", "rarely played"]):
        return _query_bottom(db, user_id, question, ql)
    if any(k in ql for k in ["mood", "happy", "sad", "energy", "valence"]):
        return _query_mood(db, user_id, question)
    if any(k in ql for k in ["when do i", "what time", "what day", "peak"]):
        return _query_when(db, user_id, question)
    if any(k in ql for k in ["how many", "count", "total"]):
        return _query_count(db, user_id, question)
    if any(k in ql for k in ["discover", "newest", "first time", "novel"]):
        return _query_discoveries(db, user_id, question)
    return _query_general(db, user_id, question)


def _query_top(db: Session, user_id: int, question: str, ql: str) -> AIQueryResult:
    entity = "artist" if "artist" in ql else "genre" if "genre" in ql else "track"
    events, tracks = _load_events_and_tracks(db, user_id)
    counter: Counter[str] = Counter()
    for event in events:
        track = tracks.get(event.track_id)
        if not track:
            continue
        if entity == "track":
            counter[track.title] += 1
        elif entity == "artist":
            counter[track.artist] += 1
        else:
            counter[track.genre or "Unknown"] += 1
    top5 = [{"name": name, "count": count} for name, count in counter.most_common(5)]
    return AIQueryResult(question=question, interpreted_as=f"Top 5 {entity}s by play count", results=top5, explanation=f"Ranked your {entity}s by total listening events.", query_type="top")


def _query_bottom(db: Session, user_id: int, question: str, ql: str) -> AIQueryResult:
    entity = "artist" if "artist" in ql else "genre" if "genre" in ql else "track"
    events, tracks = _load_events_and_tracks(db, user_id)
    counter: Counter[str] = Counter()
    for event in events:
        track = tracks.get(event.track_id)
        if not track:
            continue
        if entity == "track":
            counter[track.title] += 1
        elif entity == "artist":
            counter[track.artist] += 1
        else:
            counter[track.genre or "Unknown"] += 1
    ordered = sorted(counter.items(), key=lambda item: (item[1], item[0].lower()))
    results = [{"name": name, "count": count} for name, count in ordered[:5]]
    return AIQueryResult(question=question, interpreted_as=f"Least played {entity}s by play count", results=results, explanation=f"Ranked your least played {entity}s by total listening events.", query_type="bottom")


def _query_lowest_feature(db: Session, user_id: int, question: str, feature: str, label: str) -> AIQueryResult:
    events, tracks = _load_events_and_tracks(db, user_id)
    scored = []
    seen = set()
    for event in events:
        if event.track_id in seen:
            continue
        seen.add(event.track_id)
        track = tracks.get(event.track_id)
        if not track:
            continue
        value = getattr(track, feature, None)
        if value is None:
            continue
        scored.append({"track": track.title, "artist": track.artist, feature: value})
    scored.sort(key=lambda item: (item[feature], item["track"].lower()))
    return AIQueryResult(
        question=question,
        interpreted_as=f"Tracks ranked by lowest {feature}",
        results=scored[:5],
        explanation=f"Returned tracks with the lowest available {feature} values. This is a proxy metric, not a hidden dislike signal.",
        query_type="feature",
    )


def _query_when(db: Session, user_id: int, question: str) -> AIQueryResult:
    events, _tracks = _load_events_and_tracks(db, user_id)
    hour_counts = Counter(event.listened_at.hour for event in events if event.listened_at)
    day_counts = Counter(DAY_NAMES[event.listened_at.weekday()] for event in events if event.listened_at)
    peak_hour = hour_counts.most_common(1)[0] if hour_counts else ("N/A", 0)
    peak_day = day_counts.most_common(1)[0] if day_counts else ("N/A", 0)
    return AIQueryResult(
        question=question,
        interpreted_as="Peak listening times",
        results=[{"peak_hour": f"{peak_hour[0]}:00", "plays": peak_hour[1]}, {"peak_day": peak_day[0], "plays": peak_day[1]}],
        explanation=f"You listen most at {peak_hour[0]}:00 on {peak_day[0]}s.",
        query_type="temporal",
    )


def _query_mood(db: Session, user_id: int, question: str) -> AIQueryResult:
    profile = analytics_svc.mood_profile(db, user_id)
    results = [item.model_dump() for item in profile.items]
    dominant = profile.dominant_mood or "Unknown"
    return AIQueryResult(
        question=question,
        interpreted_as="Mood distribution from energy × valence quadrants",
        results=results,
        explanation=f"Your dominant mood is {dominant}, based on track energy and valence.",
        query_type="mood",
    )


def _query_count(db: Session, user_id: int, question: str) -> AIQueryResult:
    total = db.query(func.count(ListeningEvent.id)).filter(ListeningEvent.user_id == user_id).scalar() or 0
    unique = db.query(func.count(func.distinct(ListeningEvent.track_id))).filter(ListeningEvent.user_id == user_id).scalar() or 0
    return AIQueryResult(
        question=question,
        interpreted_as="Listening event counts",
        results=[{"total_events": total, "unique_tracks": unique}],
        explanation=f"You have {total} total listens across {unique} unique tracks.",
        query_type="count",
    )


def _query_discoveries(db: Session, user_id: int, question: str) -> AIQueryResult:
    events, tracks = _load_events_and_tracks(db, user_id)
    seen: set[int] = set()
    firsts = []
    for event in events:
        if event.track_id in seen:
            continue
        seen.add(event.track_id)
        track = tracks.get(event.track_id)
        if track:
            firsts.append({
                "track": track.title,
                "artist": track.artist,
                "first_listen": event.listened_at.isoformat() if event.listened_at else None,
            })
    return AIQueryResult(
        question=question,
        interpreted_as="Recent new discoveries",
        results=firsts[-10:][::-1],
        explanation=f"You've discovered {len(firsts)} unique tracks. Here are the most recent ones.",
        query_type="discovery",
    )


def _query_general(db: Session, user_id: int, question: str) -> AIQueryResult:
    total = db.query(func.count(ListeningEvent.id)).filter(ListeningEvent.user_id == user_id).scalar() or 0
    return AIQueryResult(
        question=question,
        interpreted_as="Unmatched query",
        results=[{"total_events": total, "supported_queries": query_examples()}],
        explanation="I could not safely map that question to a supported analysis. Try one of the supported examples instead.",
        query_type="fallback",
    )


def query_examples() -> list[str]:
    return [
        "what is my most played artist",
        "what mood do I listen to most",
        "when do I listen to music the most",
        "what are my newest discoveries",
        "what is my listening fingerprint",
        "has my music taste changed recently",
        "what is my least played song",
        "what are better songs to listen to",
    ]


# =====================================================================
# 5. Explainable recommendations
# =====================================================================
def _parse_context_preferences(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    lower = text.lower()
    prefs: dict[str, Any] = {}
    if any(k in lower for k in ["study", "focus", "work"]):
        prefs.update({"target_energy": 0.45, "target_valence": 0.55, "novelty_bonus": 0.1, "label": "focus"})
    elif any(k in lower for k in ["gym", "workout", "run", "hype"]):
        prefs.update({"target_energy": 0.8, "target_valence": 0.55, "novelty_bonus": 0.05, "label": "high-energy"})
    elif any(k in lower for k in ["chill", "calm", "sleep", "late night"]):
        prefs.update({"target_energy": 0.35, "target_valence": 0.45, "novelty_bonus": 0.0, "label": "calm"})
    elif any(k in lower for k in ["happy", "positive", "cheerful"]):
        prefs.update({"target_energy": 0.65, "target_valence": 0.75, "novelty_bonus": 0.05, "label": "positive"})
    elif any(k in lower for k in ["sad", "melancholic", "introspective"]):
        prefs.update({"target_energy": 0.35, "target_valence": 0.25, "novelty_bonus": 0.0, "label": "introspective"})
    return prefs


def _recommendation_summary(strategy: str, context: Optional[str], label: str, items: list[RecommendationItem]) -> str:
    preview = ", ".join(f"{item.title} by {item.artist}" for item in items[:3])
    prompt = (
        "Write a 2 sentence explanation of this recommendation set. Mention the fingerprint label, "
        "the strategy, and whether the set leans familiar or exploratory.\n\n"
        f"Context: {context}\nStrategy: {strategy}\nFingerprint: {label}\nPreview: {preview}"
    )
    llm_text = _llm_chat(prompt, max_tokens=120, temperature=0.3)
    if llm_text:
        return llm_text
    return f"This recommendation set uses the {strategy} strategy for a '{label}' listener. Preview tracks include {preview}."


def explain_recommendations(
    db: Session,
    user_id: int,
    context: Optional[str] = None,
    strategy: str = "balanced",
    max_tracks: int = 8,
) -> RecommendationExplainResult:
    fp = get_fingerprint(db, user_id)
    context_prefs = _parse_context_preferences(context)
    target_energy = context_prefs.get("target_energy", fp.traits.avg_energy)
    target_valence = context_prefs.get("target_valence", fp.traits.avg_valence)
    novelty_weight = {"comfort": 0.15, "balanced": 0.35, "discovery": 0.65}.get(strategy, 0.35)
    novelty_weight += context_prefs.get("novelty_bonus", 0.0)
    novelty_weight = max(0.0, min(1.0, novelty_weight))

    user_events, _tracks = _load_events_and_tracks(db, user_id)
    play_counts = Counter(event.track_id for event in user_events)
    candidates = db.query(Track).filter(Track.energy.isnot(None), Track.valence.isnot(None)).all()
    if not candidates:
        raise HTTPException(status_code=400, detail="No enriched tracks available for recommendation")

    scored: list[tuple[Track, float, float, float]] = []
    for track in candidates:
        affinity = 1.0 - ((abs(track.energy - target_energy) + abs(track.valence - target_valence)) / 2)
        novelty_component = 1.0 if play_counts.get(track.id, 0) == 0 else max(0.0, 1.0 - play_counts.get(track.id, 0) / 12)
        score = round((1 - novelty_weight) * affinity + novelty_weight * novelty_component, 4)
        scored.append((track, score, affinity, novelty_component))

    scored.sort(key=lambda item: (-item[1], item[0].title.lower()))

    results: list[RecommendationItem] = []
    seen_artists: set[str] = set()
    for track, score, affinity, discovery_score in scored:
        if len(results) >= max_tracks:
            break
        if track.artist in seen_artists and strategy == "discovery":
            continue
        familiarity = "discovery" if play_counts.get(track.id, 0) == 0 else "familiar"
        reason = (
            f"Matches target energy/valence profile ({round(affinity, 3)}) and offers "
            f"{'novelty' if familiarity == 'discovery' else 'continuity'} for your {fp.fingerprint_label.lower()} profile."
        )
        results.append(
            RecommendationItem(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                genre=track.genre,
                familiarity=familiarity,
                match_score=score,
                discovery_score=round(discovery_score, 4),
                reason=reason,
            )
        )
        seen_artists.add(track.artist)

    return RecommendationExplainResult(
        strategy=strategy,
        context=context,
        fingerprint_label=fp.fingerprint_label,
        recommendations=results,
        summary=_recommendation_summary(strategy, context, fp.fingerprint_label, results),
    )


def what_if_recommendations(db: Session, user_id: int, scenario: str, max_tracks: int = 8) -> RecommendationExplainResult:
    prefs = _parse_context_preferences(scenario)
    strategy = "discovery" if any(k in scenario.lower() for k in ["new", "different", "variety", "unfamiliar"]) else "balanced"
    context = scenario if prefs else f"what-if scenario: {scenario}"
    return explain_recommendations(db, user_id, context=context, strategy=strategy, max_tracks=max_tracks)


# =====================================================================
# 6. Playlists (legacy but improved)
# =====================================================================
def generate_playlist(db: Session, user_id: int, constraints: dict[str, Any]) -> AIPlaylist:
    mood = constraints.get("mood")
    energy_min = constraints.get("energy_min", 0.0)
    energy_max = constraints.get("energy_max", 1.0)
    max_tracks = constraints.get("max_tracks", 15)
    no_repeat = constraints.get("no_repeat_artists", False)
    novelty_bias = constraints.get("novelty_bias", 0.5)

    query = db.query(Track).filter(Track.energy.isnot(None), Track.valence.isnot(None))
    if energy_min is not None:
        query = query.filter(Track.energy >= energy_min)
    if energy_max is not None:
        query = query.filter(Track.energy <= energy_max)

    if mood:
        ml = str(mood).lower()
        if ml == "happy":
            query = query.filter(Track.energy >= 0.5, Track.valence >= 0.5)
        elif ml == "calm":
            query = query.filter(Track.energy < 0.5, Track.valence >= 0.5)
        elif ml == "sad":
            query = query.filter(Track.energy < 0.5, Track.valence < 0.5)
        elif ml in ("energetic", "intense"):
            query = query.filter(Track.energy >= 0.5)

    candidates = query.all()
    if not candidates:
        raise HTTPException(status_code=400, detail="No tracks match these constraints")

    user_events = db.query(ListeningEvent.track_id).filter(ListeningEvent.user_id == user_id).all()
    play_counts = Counter(row[0] for row in user_events)

    scored = []
    for track in candidates:
        novelty_score = 1.0 if play_counts.get(track.id, 0) == 0 else max(0.0, 1.0 - play_counts.get(track.id, 0) / 20)
        score = (1 - novelty_bias) * 0.5 + novelty_bias * novelty_score
        scored.append((track, score))

    scored.sort(key=lambda item: -item[1])
    selected = []
    seen_artists: set[str] = set()
    for track, _score in scored:
        if no_repeat and track.artist in seen_artists:
            continue
        selected.append(track)
        seen_artists.add(track.artist)
        if len(selected) >= max_tracks:
            break

    explanation = (
        f"Generated {len(selected)} tracks matching mood={mood or 'any'}, energy=[{energy_min}-{energy_max}], "
        f"novelty_bias={novelty_bias}."
    )
    playlist = AIPlaylist(
        user_id=user_id,
        name=f"🎵 {str(mood).title()} Mix" if mood else "🎵 Custom Mix",
        constraints=constraints,
        track_ids=[track.id for track in selected],
        explanation=explanation,
        version=1,
    )
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return playlist


def generate_quick_playlist(db: Session, user_id: int) -> AIPlaylist:
    fp = get_fingerprint(db, user_id)
    mood_map = {
        "Happy": "happy",
        "Calm": "calm",
        "Introspective": "sad",
        "Intense": "energetic",
    }
    constraints = {
        "mood": mood_map.get(fp.traits.dominant_mood or "", "happy"),
        "energy_min": max(0.0, round(fp.traits.avg_energy - 0.2, 2)),
        "energy_max": min(1.0, round(fp.traits.avg_energy + 0.2, 2)),
        "max_tracks": 12,
        "no_repeat_artists": True,
        "novelty_bias": 0.6,
    }
    return generate_playlist(db, user_id, constraints)


def regenerate_playlist(db: Session, playlist: AIPlaylist, feedback_text: str) -> AIPlaylist:
    fl = feedback_text.lower()
    new_constraints = dict(playlist.constraints or {})
    prefs = _parse_context_preferences(fl)
    if prefs.get("target_energy") is not None:
        target = prefs["target_energy"]
        new_constraints["energy_min"] = max(0.0, round(target - 0.15, 2))
        new_constraints["energy_max"] = min(1.0, round(target + 0.15, 2))
    if prefs.get("label") == "calm":
        new_constraints["mood"] = "calm"
    elif prefs.get("label") == "positive":
        new_constraints["mood"] = "happy"
    elif prefs.get("label") == "high-energy":
        new_constraints["mood"] = "energetic"
    elif prefs.get("label") == "introspective":
        new_constraints["mood"] = "sad"

    if any(word in fl for word in ["new", "discover", "variety"]):
        new_constraints["novelty_bias"] = min(new_constraints.get("novelty_bias", 0.5) + 0.2, 1.0)
    if "no repeat" in fl or "different artist" in fl:
        new_constraints["no_repeat_artists"] = True

    playlist.version += 1
    regenerated = generate_playlist(db, playlist.user_id, new_constraints)
    playlist.constraints = new_constraints
    playlist.track_ids = regenerated.track_ids
    playlist.explanation = f"[v{playlist.version}] {regenerated.explanation}"
    db.delete(regenerated)
    db.commit()
    db.refresh(playlist)
    return playlist


# =====================================================================
# 7. Insight critique / evaluation
# =====================================================================
def critique_insight(db: Session, insight: Insight) -> InsightCritiqueResult:
    _ = db
    issues: list[InsightCritiqueIssue] = []
    text = insight.insight_text or ""
    evidence = insight.evidence or []
    snapshot = insight.data_snapshot or {}

    lower_text = text.lower()
    for term in VAGUE_TERMS:
        if term in lower_text and str(snapshot.get("avg_energy", "")) not in text and str(snapshot.get("novelty_ratio", "")) not in text:
            issues.append(InsightCritiqueIssue(
                issue_type="vagueness",
                severity="medium",
                message=f"The term '{term}' appears without a directly adjacent metric.",
            ))
            break

    if len(evidence) < 2:
        issues.append(InsightCritiqueIssue(
            issue_type="evidence_gap",
            severity="high",
            message="The insight has fewer than two explicit evidence items.",
        ))

    if snapshot.get("top_artist") and snapshot["top_artist"].lower() not in lower_text:
        issues.append(InsightCritiqueIssue(
            issue_type="grounding_gap",
            severity="medium",
            message="The top artist in the snapshot is not referenced in the text.",
        ))

    if not any(str(snapshot.get(key, "")) in text for key in ["avg_energy", "avg_valence", "novelty_ratio", "diversity_score"]):
        issues.append(InsightCritiqueIssue(
            issue_type="numerical_grounding",
            severity="high",
            message="The insight does not explicitly mention any numerical metrics from the snapshot.",
        ))

    verdict = "Strongly grounded" if not issues else "Needs tighter grounding"
    grounding_score = max(0.0, 100.0 - (len(issues) * 20.0))

    improved_prompt = (
        "Rewrite this insight to be more grounded and specific while staying concise. "
        "Use the snapshot and evidence.\n\n"
        f"Insight: {text}\nSnapshot: {json.dumps(snapshot)}\nEvidence: {json.dumps(evidence)}"
    )
    improved_excerpt = _llm_chat(improved_prompt, max_tokens=160, temperature=0.2) or _template_insight(snapshot)

    return InsightCritiqueResult(
        insight_id=insight.id,
        overall_verdict=verdict,
        issues=issues,
        improved_excerpt=improved_excerpt,
        grounding_score=grounding_score,
    )


def eval_insight(db: Session, insight: Insight) -> EvalResult:
    _ = db
    checks: list[EvalCheck] = []
    score = 0.0

    required = {"total_events", "avg_energy", "avg_valence", "novelty_ratio"}
    snapshot = insight.data_snapshot or {}
    missing = required - set(snapshot.keys())
    checks.append(EvalCheck(check="schema_validity", passed=not missing, detail="All required keys present" if not missing else f"Missing keys: {sorted(missing)}"))
    if not missing:
        score += 25

    evidence = insight.evidence or []
    evidence_ok = len(evidence) >= 2 and all("claim" in item and "support" in item for item in evidence)
    checks.append(EvalCheck(check="evidence_coverage", passed=evidence_ok, detail=f"{len(evidence)} evidence items"))
    if evidence_ok:
        score += 25

    text = insight.insight_text or ""
    grounded = any(str(snapshot.get(key, "")) in text for key in ["avg_energy", "avg_valence", "novelty_ratio", "diversity_score"])
    checks.append(EvalCheck(check="text_grounding", passed=grounded, detail="Insight references specific metrics" if grounded else "Insight lacks explicit numerical grounding"))
    if grounded:
        score += 25

    values_ok = True
    for key in ["avg_energy", "avg_valence", "novelty_ratio", "diversity_score"]:
        value = snapshot.get(key)
        if value is not None and not (0 <= value <= 1):
            values_ok = False
            break
    checks.append(EvalCheck(check="value_consistency", passed=values_ok, detail="Values within expected ranges" if values_ok else "One or more values fall outside expected ranges"))
    if values_ok:
        score += 25

    return EvalResult(insight_id=insight.id, overall_score=score, checks=checks)
