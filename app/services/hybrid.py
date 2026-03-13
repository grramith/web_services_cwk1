"""Hybrid analytics and AI service for Sonic Insights Hybrid."""

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
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CatalogTrack, Insight, ListeningEvent, Track, TrackFeedback, UserFingerprint
from app.schemas import (
    ChangeMetric,
    FingerprintResult,
    FingerprintTraits,
    HighlightResult,
    InsightCritiqueIssue,
    InsightCritiqueResult,
    OverviewResult,
    RecentChangesResult,
    RecommendationExplainResult,
    RecommendationItem,
)

logger = logging.getLogger(__name__)


def _llm_chat(prompt: str, *, max_tokens: int = 250, temperature: float = 0.2) -> Optional[str]:
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


def _mood_label(energy: float, valence: float) -> str:
    if energy >= 0.55 and valence >= 0.55:
        return "happy"
    if energy >= 0.55 and valence < 0.55:
        return "intense"
    if energy < 0.55 and valence >= 0.55:
        return "calm"
    return "melancholic"


def _fingerprint_label(avg_energy: float, novelty_ratio: float, diversity_score: float, peak_hour: Optional[int]) -> str:
    if avg_energy >= 0.65 and novelty_ratio >= 0.55:
        return "Energetic Explorer"
    if avg_energy < 0.45 and diversity_score < 0.4:
        return "Calm Specialist"
    if peak_hour is not None and peak_hour >= 21:
        return "Late-Night Listener"
    if novelty_ratio < 0.35:
        return "Comfort Repeater"
    return "Balanced Listener"


def _load_events_and_tracks(db: Session, user_id: int, dt_from: Optional[datetime] = None, dt_to: Optional[datetime] = None):
    q = db.query(ListeningEvent).filter(ListeningEvent.user_id == user_id)
    if dt_from is not None:
        q = q.filter(ListeningEvent.listened_at >= dt_from)
    if dt_to is not None:
        q = q.filter(ListeningEvent.listened_at <= dt_to)
    events = q.order_by(ListeningEvent.listened_at).all()
    track_ids = {e.track_id for e in events}
    tracks = {t.id: t for t in db.query(Track).filter(Track.id.in_(track_ids)).all()} if track_ids else {}
    return events, tracks


def build_fingerprint(db: Session, user_id: int, *, persist: bool = True) -> UserFingerprint:
    events, tracks = _load_events_and_tracks(db, user_id)
    if not events:
        raise HTTPException(status_code=400, detail="Import Spotify listening data before generating a fingerprint")

    energies: list[float] = []
    valences: list[float] = []
    danceabilities: list[float] = []
    tempos: list[float] = []
    genres: list[str] = []
    artists: list[str] = []
    hours: list[int] = []
    moods: list[str] = []

    for event in events:
        track = tracks.get(event.track_id)
        if not track:
            continue
        if track.energy is not None:
            energies.append(track.energy)
        if track.valence is not None:
            valences.append(track.valence)
        if track.danceability is not None:
            danceabilities.append(track.danceability)
        if track.tempo is not None:
            tempos.append(track.tempo)
        if track.genre:
            genres.append(track.genre)
        if track.artist:
            artists.append(track.artist)
        if event.listened_at:
            hours.append(event.listened_at.hour)
        if track.energy is not None and track.valence is not None:
            moods.append(_mood_label(track.energy, track.valence))

    avg_energy = _safe_mean(energies, 0.5)
    avg_valence = _safe_mean(valences, 0.5)
    avg_danceability = _safe_mean(danceabilities, 0.5)
    avg_tempo = _safe_mean(tempos, 110.0)
    novelty_ratio = round(len(set(e.track_id for e in events)) / len(events), 4) if events else 0.0
    diversity_score = _norm_entropy(genres or artists)
    dominant_mood = Counter(moods).most_common(1)[0][0] if moods else None
    peak_hour = Counter(hours).most_common(1)[0][0] if hours else None
    top_genres = [name for name, _ in Counter(genres).most_common(5)]
    top_artists = [name for name, _ in Counter(artists).most_common(5)]
    label = _fingerprint_label(avg_energy, novelty_ratio, diversity_score, peak_hour)

    fp = db.query(UserFingerprint).filter(UserFingerprint.user_id == user_id).first()
    if not fp:
        fp = UserFingerprint(user_id=user_id, label=label)
        db.add(fp)

    fp.label = label
    fp.avg_energy = avg_energy
    fp.avg_valence = avg_valence
    fp.avg_danceability = avg_danceability
    fp.avg_tempo = avg_tempo
    fp.novelty_ratio = novelty_ratio
    fp.diversity_score = diversity_score
    fp.dominant_mood = dominant_mood
    fp.top_genres_json = top_genres
    fp.top_artists_json = top_artists
    fp.peak_hour = peak_hour
    fp.total_events = len(events)

    if persist:
        db.commit()
        db.refresh(fp)
    return fp


def _fingerprint_evidence(fp: UserFingerprint) -> list[dict[str, Any]]:
    evidence = []
    evidence.append({"claim": f"Fingerprint label is {fp.label}", "support": f"Derived from energy={fp.avg_energy}, novelty={fp.novelty_ratio}, diversity={fp.diversity_score}"})
    if fp.dominant_mood:
        evidence.append({"claim": f"Dominant mood is {fp.dominant_mood}", "support": f"Average valence={fp.avg_valence}, energy={fp.avg_energy}"})
    if fp.top_artists_json:
        evidence.append({"claim": f"Top artist affinity is {fp.top_artists_json[0]}", "support": f"Top artist list: {fp.top_artists_json[:3]}"})
    if fp.top_genres_json:
        evidence.append({"claim": f"Top genre is {fp.top_genres_json[0]}", "support": f"Top genre list: {fp.top_genres_json[:3]}"})
    return evidence


def fingerprint_result(db: Session, user_id: int) -> FingerprintResult:
    fp = build_fingerprint(db, user_id)
    traits = FingerprintTraits(
        avg_energy=fp.avg_energy,
        avg_valence=fp.avg_valence,
        avg_danceability=fp.avg_danceability,
        avg_tempo=fp.avg_tempo,
        novelty_ratio=fp.novelty_ratio,
        diversity_score=fp.diversity_score,
        dominant_mood=fp.dominant_mood,
        peak_hour=f"{fp.peak_hour:02d}:00" if fp.peak_hour is not None else None,
        total_events=fp.total_events,
        top_artists=fp.top_artists_json or [],
        top_genres=fp.top_genres_json or [],
    )
    evidence = _fingerprint_evidence(fp)
    explanation = (
        f"Your fingerprint is {fp.label}: average energy {fp.avg_energy}, valence {fp.avg_valence}, "
        f"novelty ratio {fp.novelty_ratio}, and diversity score {fp.diversity_score}."
    )
    llm = _llm_chat(
        "Rewrite this listening-fingerprint explanation in 2 concise sentences, grounded in the data only:\n"
        + json.dumps({"label": fp.label, "traits": traits.model_dump(), "evidence": evidence})
    )
    if llm:
        explanation = llm
    return FingerprintResult(
        fingerprint_label=fp.label,
        traits=traits,
        explanation=explanation,
        evidence=evidence,
    )


def overview(db: Session, user_id: int) -> OverviewResult:
    fp = build_fingerprint(db, user_id)
    unique_spotify_tracks = db.query(Track.id).join(ListeningEvent, ListeningEvent.track_id == Track.id).filter(ListeningEvent.user_id == user_id).distinct().count()
    unique_catalog_feedback_tracks = db.query(TrackFeedback.catalog_track_id).filter(TrackFeedback.user_id == user_id).distinct().count()
    return OverviewResult(
        user_id=user_id,
        total_events=fp.total_events,
        unique_spotify_tracks=unique_spotify_tracks,
        unique_catalog_feedback_tracks=unique_catalog_feedback_tracks,
        avg_energy=fp.avg_energy,
        avg_valence=fp.avg_valence,
        dominant_mood=fp.dominant_mood,
        fingerprint_label=fp.label,
    )


def highlights(db: Session, user_id: int) -> HighlightResult:
    fp = build_fingerprint(db, user_id)
    return HighlightResult(
        top_artist=(fp.top_artists_json or [None])[0],
        top_genre=(fp.top_genres_json or [None])[0],
        novelty_ratio=fp.novelty_ratio,
        diversity_score=fp.diversity_score,
        peak_hour=f"{fp.peak_hour:02d}:00" if fp.peak_hour is not None else None,
        dominant_mood=fp.dominant_mood,
    )


def recent_changes(db: Session, user_id: int, days: int = 30) -> RecentChangesResult:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=days)
    previous_start = recent_start - timedelta(days=days)
    previous_end = recent_start

    def window_metrics(start: datetime, end: datetime) -> dict[str, Any]:
        events, tracks = _load_events_and_tracks(db, user_id, start, end)
        if not events:
            return {
                "total_events": 0,
                "avg_energy": None,
                "avg_valence": None,
                "novelty_ratio": 0.0,
                "dominant_mood": None,
                "top_artist": None,
                "top_genre": None,
            }
        energies, valences, genres, artists, moods = [], [], [], [], []
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
            if track.energy is not None and track.valence is not None:
                moods.append(_mood_label(track.energy, track.valence))
        return {
            "total_events": len(events),
            "avg_energy": _safe_mean(energies, 0.0) if energies else None,
            "avg_valence": _safe_mean(valences, 0.0) if valences else None,
            "novelty_ratio": round(len(set(e.track_id for e in events)) / len(events), 4),
            "dominant_mood": Counter(moods).most_common(1)[0][0] if moods else None,
            "top_artist": Counter(artists).most_common(1)[0][0] if artists else None,
            "top_genre": Counter(genres).most_common(1)[0][0] if genres else None,
        }

    prev = window_metrics(previous_start, previous_end)
    recent = window_metrics(recent_start, now)
    metrics = [
        ChangeMetric(metric="total_events", previous=prev["total_events"], recent=recent["total_events"], delta=recent["total_events"] - prev["total_events"]),
        ChangeMetric(metric="avg_energy", previous=prev["avg_energy"], recent=recent["avg_energy"], delta=(round((recent["avg_energy"] or 0) - (prev["avg_energy"] or 0), 4) if prev["avg_energy"] is not None or recent["avg_energy"] is not None else None)),
        ChangeMetric(metric="avg_valence", previous=prev["avg_valence"], recent=recent["avg_valence"], delta=(round((recent["avg_valence"] or 0) - (prev["avg_valence"] or 0), 4) if prev["avg_valence"] is not None or recent["avg_valence"] is not None else None)),
        ChangeMetric(metric="novelty_ratio", previous=prev["novelty_ratio"], recent=recent["novelty_ratio"], delta=round(recent["novelty_ratio"] - prev["novelty_ratio"], 4)),
        ChangeMetric(metric="dominant_mood", previous=prev["dominant_mood"], recent=recent["dominant_mood"]),
        ChangeMetric(metric="top_artist", previous=prev["top_artist"], recent=recent["top_artist"]),
        ChangeMetric(metric="top_genre", previous=prev["top_genre"], recent=recent["top_genre"]),
    ]
    energy_delta = metrics[1].delta or 0.0
    novelty_delta = metrics[3].delta or 0.0
    shift = "Stable"
    if energy_delta > 0.08 and novelty_delta > 0.05:
        shift = "More energetic and exploratory"
    elif energy_delta < -0.08:
        shift = "Calmer recent listening"
    elif novelty_delta < -0.05:
        shift = "More repetitive recent listening"

    evidence = [
        {"claim": "Recent change summary", "support": f"energy delta={energy_delta}, novelty delta={novelty_delta}"},
        {"claim": "Dominant mood comparison", "support": f"previous={prev['dominant_mood']}, recent={recent['dominant_mood']}"},
    ]
    summary = (
        f"Compared with the previous {days}-day window, your recent listening is {shift.lower()}. "
        f"Top genre shifted from {prev['top_genre'] or 'n/a'} to {recent['top_genre'] or 'n/a'} and top artist moved from {prev['top_artist'] or 'n/a'} to {recent['top_artist'] or 'n/a'}."
    )
    llm = _llm_chat(
        "Write a concise 2-sentence recent taste change summary grounded only in these metrics:\n"
        + json.dumps({"previous": prev, "recent": recent, "metrics": [m.model_dump() for m in metrics]})
    )
    if llm:
        summary = llm
    return RecentChangesResult(
        previous_window=f"{previous_start.date().isoformat()} to {previous_end.date().isoformat()}",
        recent_window=f"{recent_start.date().isoformat()} to {now.date().isoformat()}",
        fingerprint_shift=shift,
        summary=summary,
        metrics=metrics,
        evidence=evidence,
    )


def _candidate_tracks(db: Session) -> list[CatalogTrack]:
    return db.query(CatalogTrack).all()


def _feedback_bias(db: Session, user_id: int) -> dict[int, str]:
    return {fb.catalog_track_id: fb.rating for fb in db.query(TrackFeedback).filter(TrackFeedback.user_id == user_id).all()}


def _score_candidate(track: CatalogTrack, fp: UserFingerprint, strategy: str = "balanced") -> tuple[float, float]:
    energy_gap = abs((track.energy or 0.5) - fp.avg_energy)
    valence_gap = abs((track.valence or 0.5) - fp.avg_valence)
    dance_gap = abs((track.danceability or 0.5) - fp.avg_danceability)
    tempo_norm_track = min((track.tempo or fp.avg_tempo) / 200.0, 1.0)
    tempo_norm_fp = min((fp.avg_tempo or 110.0) / 200.0, 1.0)
    tempo_gap = abs(tempo_norm_track - tempo_norm_fp)

    similarity = max(0.0, 1 - ((energy_gap + valence_gap + dance_gap + tempo_gap) / 4))
    novelty = 0.15
    if strategy == "discovery":
        novelty = min(0.4, 0.25 + abs((track.energy or fp.avg_energy) - fp.avg_energy))
    elif strategy == "comfort":
        novelty = 0.05
    else:
        novelty = 0.15 + min(0.15, abs((track.valence or fp.avg_valence) - fp.avg_valence))
    return round(similarity, 4), round(novelty, 4)


def _build_reason(track: CatalogTrack, fp: UserFingerprint, context: Optional[str], familiarity: str, fit_score: float, novelty_score: float) -> str:
    base = (
        f"This matches your {fp.label.lower()} profile with fit score {fit_score}. "
        f"Its energy and valence sit close to your listening fingerprint while offering {familiarity} discovery value ({novelty_score})."
    )
    if context:
        base += f" It was additionally filtered for the context: {context}."
    return base


def explain_recommendations(db: Session, user_id: int, context: Optional[str], strategy: str, max_tracks: int) -> RecommendationExplainResult:
    fp = build_fingerprint(db, user_id)
    candidates = _candidate_tracks(db)
    if not candidates:
        raise HTTPException(status_code=400, detail="Import the catalog dataset before requesting hybrid recommendations")

    feedback = _feedback_bias(db, user_id)
    scored: list[tuple[CatalogTrack, float, float]] = []
    for track in candidates:
        if feedback.get(track.id) == "dislike":
            continue
        fit_score, novelty_score = _score_candidate(track, fp, strategy)
        final_score = fit_score + novelty_score
        if context:
            ctx = context.lower()
            if "study" in ctx or "focus" in ctx:
                if track.energy is not None and track.energy <= fp.avg_energy + 0.1:
                    final_score += 0.05
            if "calm" in ctx and track.energy is not None and track.energy < fp.avg_energy:
                final_score += 0.08
            if "upbeat" in ctx and track.valence is not None and track.valence > fp.avg_valence:
                final_score += 0.06
        scored.append((track, round(final_score, 4), novelty_score))

    scored.sort(key=lambda item: (-item[1], item[0].name.lower()))
    items: list[RecommendationItem] = []
    for track, score, novelty_score in scored[:max_tracks]:
        familiarity = "comfort" if strategy == "comfort" else ("exploratory" if novelty_score >= 0.2 else "familiar")
        items.append(
            RecommendationItem(
                track_id=track.id,
                title=track.name,
                artist=track.artist,
                genre=track.genre,
                fit_score=round(max(0.0, score - novelty_score), 4),
                novelty_score=novelty_score,
                familiarity=familiarity,
                why=_build_reason(track, fp, context, familiarity, round(max(0.0, score - novelty_score), 4), novelty_score),
            )
        )

    summary = f"Generated {len(items)} hybrid recommendations by matching your Spotify-derived fingerprint against the external catalog."
    llm = _llm_chat(
        "Write a concise 2-sentence explanation of this hybrid recommendation set. Use only the structured data below:\n"
        + json.dumps({
            "fingerprint_label": fp.label,
            "context": context,
            "strategy": strategy,
            "recommendations": [i.model_dump() for i in items],
        })
    )
    if llm:
        summary = llm
    return RecommendationExplainResult(
        fingerprint_label=fp.label,
        strategy=strategy,
        context=context,
        recommendations=items,
        summary=summary,
    )


def what_if_recommendations(db: Session, user_id: int, scenario: str, max_tracks: int) -> RecommendationExplainResult:
    scenario_lower = scenario.lower()
    strategy = "balanced"
    context = scenario
    if "more variety" in scenario_lower or "new" in scenario_lower or "discover" in scenario_lower:
        strategy = "discovery"
    elif "comfort" in scenario_lower or "familiar" in scenario_lower or "closer to what i like" in scenario_lower:
        strategy = "comfort"
    return explain_recommendations(db, user_id, context=context, strategy=strategy, max_tracks=max_tracks)


def generate_hybrid_insight(db: Session, user_id: int) -> Insight:
    fp = build_fingerprint(db, user_id)
    changes = recent_changes(db, user_id)
    snapshot = {
        "fingerprint_label": fp.label,
        "avg_energy": fp.avg_energy,
        "avg_valence": fp.avg_valence,
        "avg_danceability": fp.avg_danceability,
        "avg_tempo": fp.avg_tempo,
        "novelty_ratio": fp.novelty_ratio,
        "diversity_score": fp.diversity_score,
        "dominant_mood": fp.dominant_mood,
        "top_artists": fp.top_artists_json or [],
        "top_genres": fp.top_genres_json or [],
        "recent_shift": changes.fingerprint_shift,
    }
    evidence = _fingerprint_evidence(fp) + changes.evidence
    text = (
        f"Your listening fingerprint is {fp.label}, characterised by average energy {fp.avg_energy}, valence {fp.avg_valence}, "
        f"and a novelty ratio of {fp.novelty_ratio}. Recently, your behaviour has shifted as follows: {changes.summary}"
    )
    llm = _llm_chat(
        "Write a 4-sentence grounded hybrid music insight using only this data:\n"
        + json.dumps({"snapshot": snapshot, "evidence": evidence})
    )
    model_used = "template"
    if llm:
        text = llm
        model_used = "openai"
    record = Insight(
        user_id=user_id,
        insight_type="hybrid",
        title="Hybrid listening intelligence insight",
        insight_text=text,
        data_snapshot=snapshot,
        evidence=evidence,
        model_used=model_used,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def critique_insight(db: Session, user_id: int, insight_id: int) -> InsightCritiqueResult:
    insight = db.query(Insight).filter(Insight.id == insight_id, Insight.user_id == user_id).first()
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    issues: list[InsightCritiqueIssue] = []
    text = insight.insight_text or ""
    snapshot = insight.data_snapshot or {}
    evidence = insight.evidence or []

    for term in ["better", "interesting", "nice", "strong", "unique"]:
        if term in text.lower():
            issues.append(InsightCritiqueIssue(issue_type="vagueness", severity="medium", message=f"The term '{term}' is vague and could be grounded more explicitly."))

    grounded_hits = 0
    for key in ["avg_energy", "avg_valence", "novelty_ratio", "diversity_score"]:
        value = snapshot.get(key)
        if value is not None and str(value) in text:
            grounded_hits += 1
    if grounded_hits == 0:
        issues.append(InsightCritiqueIssue(issue_type="grounding", severity="high", message="The insight does not reference concrete numeric evidence from the snapshot."))
    if len(evidence) < 2:
        issues.append(InsightCritiqueIssue(issue_type="evidence", severity="medium", message="The evidence chain is thin; add at least two explicit supports."))

    grounding_score = round(min(1.0, (grounded_hits / 3) + (0.25 if len(evidence) >= 2 else 0.0)), 2)
    overall = "Strong" if grounding_score >= 0.75 and not any(i.severity == "high" for i in issues) else "Needs revision"

    improved_excerpt = (
        f"Your profile is {snapshot.get('fingerprint_label', 'Balanced Listener')}, with average energy {snapshot.get('avg_energy')} and novelty ratio {snapshot.get('novelty_ratio')}. "
        f"Recent change analysis indicates: {snapshot.get('recent_shift', 'stable listening behaviour')}."
    )
    llm = _llm_chat(
        "Rewrite this insight excerpt to be more grounded and precise, using only the provided snapshot:\n"
        + json.dumps({"text": text, "snapshot": snapshot})
    )
    if llm:
        improved_excerpt = llm
    return InsightCritiqueResult(
        insight_id=insight.id,
        overall_verdict=overall,
        issues=issues,
        improved_excerpt=improved_excerpt,
        grounding_score=grounding_score,
    )
