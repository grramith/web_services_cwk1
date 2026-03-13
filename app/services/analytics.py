"""
Deterministic analytics service layer.

All computation is separated from route handlers and is fully
testable without any external API calls.

  overview       – high-level listening summary
  top            – top tracks / artists / genres by play count
  time_heatmap   – listening distribution by hour or day
  transitions    – common A→B track sequences
  novelty        – repeat vs explore score
"""

import math
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import Counter

from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from app.models import Track, ListeningEvent
from app.schemas import (
    OverviewResult, TopResult, TopItem,
    HeatmapResult, HeatmapCell,
    TransitionsResult, TransitionPair,
    NoveltyResult, MoodProfileResult, MoodBucket,
    PeriodCompareResult, CompareMetric, HighlightsResult,
)

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


def _mood_label(energy: float, valence: float) -> str:
    """Russell's Circumplex quadrant label."""
    if energy >= 0.5 and valence >= 0.5:
        return "Happy"
    elif energy >= 0.5:
        return "Angry"
    elif valence >= 0.5:
        return "Calm"
    return "Sad"


def _base_query(db: Session, user_id: int,
                dt_from: Optional[str], dt_to: Optional[str]):
    """Build a filtered query for a user's events in a date range."""
    q = (db.query(ListeningEvent)
         .filter(ListeningEvent.user_id == user_id))
    if dt_from:
        q = q.filter(ListeningEvent.listened_at >= dt_from)
    if dt_to:
        q = q.filter(ListeningEvent.listened_at <= dt_to)
    return q


# =====================================================================
# OVERVIEW
# =====================================================================
def overview(db: Session, user_id: int,
             dt_from: Optional[str] = None,
             dt_to: Optional[str] = None) -> OverviewResult:
    q = _base_query(db, user_id, dt_from, dt_to)
    events = q.all()
    total = len(events)

    track_ids = [e.track_id for e in events]
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(set(track_ids))).all()} if track_ids else {}

    artists = set()
    genres = set()
    energies = []
    valences = []
    total_ms = 0

    for e in events:
        t = tracks.get(e.track_id)
        if not t:
            continue
        artists.add(t.artist)
        if t.genre:
            genres.add(t.genre)
        if t.energy is not None:
            energies.append(t.energy)
        if t.valence is not None:
            valences.append(t.valence)
        total_ms += e.duration_listened_ms or 0

    avg_e = round(statistics.mean(energies), 4) if energies else None
    avg_v = round(statistics.mean(valences), 4) if valences else None
    mood = _mood_label(avg_e, avg_v) if avg_e is not None and avg_v is not None else None

    return OverviewResult(
        user_id=user_id,
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        total_events=total,
        unique_tracks=len(set(track_ids)),
        unique_artists=len(artists),
        unique_genres=len(genres),
        total_listening_ms=total_ms,
        avg_energy=avg_e,
        avg_valence=avg_v,
        dominant_mood=mood,
    )


# =====================================================================
# TOP (track | artist | genre)
# =====================================================================
def top(db: Session, user_id: int, entity: str, k: int = 10,
        dt_from: Optional[str] = None,
        dt_to: Optional[str] = None) -> TopResult:
    q = _base_query(db, user_id, dt_from, dt_to)
    events = q.all()
    track_ids = [e.track_id for e in events]
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(set(track_ids))).all()} if track_ids else {}

    counter: Counter = Counter()
    ms_counter: Counter = Counter()

    for e in events:
        t = tracks.get(e.track_id)
        if not t:
            continue
        if entity == "track":
            key = t.title
        elif entity == "artist":
            key = t.artist
        elif entity == "genre":
            key = t.genre or "Unknown"
        else:
            key = t.title
        counter[key] += 1
        ms_counter[key] += e.duration_listened_ms or 0

    items = [
        TopItem(rank=i + 1, name=name, count=cnt, total_ms=ms_counter[name])
        for i, (name, cnt) in enumerate(counter.most_common(k))
    ]
    return TopResult(
        entity=entity, k=k,
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        items=items,
    )


# =====================================================================
# TIME HEATMAP
# =====================================================================
def time_heatmap(db: Session, user_id: int, bucket: str = "hour",
                 dt_from: Optional[str] = None,
                 dt_to: Optional[str] = None) -> HeatmapResult:
    q = _base_query(db, user_id, dt_from, dt_to)
    events = q.all()
    track_ids = [e.track_id for e in events]
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(set(track_ids))).all()} if track_ids else {}

    buckets: dict[str, list] = {}
    for e in events:
        t = tracks.get(e.track_id)
        la = e.listened_at
        if bucket == "hour":
            dow = DAY_NAMES[la.weekday()] if la else "Unknown"
            hr = la.hour if la else 0
            key = f"{dow} {hr:02d}:00"
        else:
            key = la.strftime("%Y-%m-%d") if la else "Unknown"
        if key not in buckets:
            buckets[key] = []
        buckets[key].append(t)

    cells = []
    for key, ts in sorted(buckets.items()):
        es = [t.energy for t in ts if t and t.energy is not None]
        vs = [t.valence for t in ts if t and t.valence is not None]
        cells.append(HeatmapCell(
            bucket=key, count=len(ts),
            avg_energy=round(statistics.mean(es), 4) if es else None,
            avg_valence=round(statistics.mean(vs), 4) if vs else None,
        ))

    return HeatmapResult(
        bucket_type=bucket,
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        cells=cells,
    )


# =====================================================================
# TRANSITIONS (A→B sequences)
# =====================================================================
def transitions(db: Session, user_id: int, k: int = 10,
                dt_from: Optional[str] = None,
                dt_to: Optional[str] = None) -> TransitionsResult:
    q = (_base_query(db, user_id, dt_from, dt_to)
         .order_by(ListeningEvent.listened_at))
    events = q.all()
    track_ids = [e.track_id for e in events]
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(set(track_ids))).all()} if track_ids else {}

    pairs: Counter = Counter()
    valence_shifts: dict[tuple, list] = {}

    for i in range(1, len(events)):
        prev_t = tracks.get(events[i - 1].track_id)
        curr_t = tracks.get(events[i].track_id)
        if not prev_t or not curr_t:
            continue
        if prev_t.id == curr_t.id:
            continue
        pair = (prev_t.id, curr_t.id)
        pairs[pair] += 1
        if prev_t.valence is not None and curr_t.valence is not None:
            if pair not in valence_shifts:
                valence_shifts[pair] = []
            valence_shifts[pair].append(curr_t.valence - prev_t.valence)

    top_pairs = []
    for (pid, cid), cnt in pairs.most_common(k):
        pt = tracks.get(pid)
        ct = tracks.get(cid)
        if not pt or not ct:
            continue
        shifts = valence_shifts.get((pid, cid), [0])
        top_pairs.append(TransitionPair(
            from_track=pt.title, from_artist=pt.artist,
            to_track=ct.title, to_artist=ct.artist,
            count=cnt,
            avg_valence_shift=round(statistics.mean(shifts), 4),
        ))

    return TransitionsResult(
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        total_transitions=sum(pairs.values()),
        top_transitions=top_pairs,
    )


# =====================================================================
# NOVELTY (repeat vs explore)
# =====================================================================
def novelty(db: Session, user_id: int,
            dt_from: Optional[str] = None,
            dt_to: Optional[str] = None) -> NoveltyResult:
    q = _base_query(db, user_id, dt_from, dt_to)
    events = q.order_by(ListeningEvent.listened_at).all()

    total = len(events)
    if total == 0:
        return NoveltyResult(
            period_start=dt_from or "all-time",
            period_end=dt_to or "now",
            total_events=0, unique_tracks=0, repeat_listens=0,
            novelty_ratio=0.0, novelty_label="No data",
            new_discoveries=0,
        )

    seen = set()
    discoveries = 0
    for e in events:
        if e.track_id not in seen:
            seen.add(e.track_id)
            discoveries += 1

    unique = len(seen)
    repeats = total - unique
    ratio = round(unique / total, 4) if total else 0.0

    if ratio >= 0.8:
        label = "Explorer — constantly seeking new music"
    elif ratio >= 0.5:
        label = "Balanced — mix of familiar and new"
    elif ratio >= 0.3:
        label = "Comfort listener — leans towards favourites"
    else:
        label = "Loyalist — deep attachment to known tracks"

    return NoveltyResult(
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        total_events=total, unique_tracks=unique,
        repeat_listens=repeats, novelty_ratio=ratio,
        novelty_label=label, new_discoveries=discoveries,
    )


# =====================================================================
# MOOD PROFILE
# =====================================================================
def mood_profile(db: Session, user_id: int,
                 dt_from: Optional[str] = None,
                 dt_to: Optional[str] = None) -> MoodProfileResult:
    events = _base_query(db, user_id, dt_from, dt_to).all()
    if not events:
        return MoodProfileResult(
            period_start=dt_from or "all-time",
            period_end=dt_to or "now",
            total_events=0,
            dominant_mood=None,
            items=[],
        )

    track_ids = [e.track_id for e in events]
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(set(track_ids))).all()} if track_ids else {}

    counts: Counter = Counter()
    total_scored = 0
    for e in events:
        t = tracks.get(e.track_id)
        if not t or t.energy is None or t.valence is None:
            continue
        counts[_mood_label(t.energy, t.valence)] += 1
        total_scored += 1

    items = [
        MoodBucket(
            mood=name,
            count=count,
            proportion=round(count / total_scored, 4) if total_scored else 0.0,
        )
        for name, count in counts.most_common()
    ]
    dominant = items[0].mood if items else None
    return MoodProfileResult(
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        total_events=len(events),
        dominant_mood=dominant,
        items=items,
    )


# =====================================================================
# PERIOD COMPARE
# =====================================================================
def compare_periods(db: Session, user_id: int,
                    from_a: Optional[str], to_a: Optional[str],
                    from_b: Optional[str], to_b: Optional[str]) -> PeriodCompareResult:
    oa = overview(db, user_id, from_a, to_a)
    ob = overview(db, user_id, from_b, to_b)
    na = novelty(db, user_id, from_a, to_a)
    nb = novelty(db, user_id, from_b, to_b)
    ta = top(db, user_id, 'artist', 1, from_a, to_a)
    tb = top(db, user_id, 'artist', 1, from_b, to_b)
    ga = top(db, user_id, 'genre', 1, from_a, to_a)
    gb = top(db, user_id, 'genre', 1, from_b, to_b)

    def _delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 4)

    metrics = [
        CompareMetric(metric='total_events', period_a=oa.total_events, period_b=ob.total_events, delta=_delta(oa.total_events, ob.total_events)),
        CompareMetric(metric='unique_tracks', period_a=oa.unique_tracks, period_b=ob.unique_tracks, delta=_delta(oa.unique_tracks, ob.unique_tracks)),
        CompareMetric(metric='avg_energy', period_a=oa.avg_energy, period_b=ob.avg_energy, delta=_delta(oa.avg_energy, ob.avg_energy)),
        CompareMetric(metric='avg_valence', period_a=oa.avg_valence, period_b=ob.avg_valence, delta=_delta(oa.avg_valence, ob.avg_valence)),
        CompareMetric(metric='novelty_ratio', period_a=na.novelty_ratio, period_b=nb.novelty_ratio, delta=_delta(na.novelty_ratio, nb.novelty_ratio)),
        CompareMetric(metric='dominant_mood', period_a=oa.dominant_mood, period_b=ob.dominant_mood, delta=None),
        CompareMetric(metric='top_artist', period_a=ta.items[0].name if ta.items else None, period_b=tb.items[0].name if tb.items else None, delta=None),
        CompareMetric(metric='top_genre', period_a=ga.items[0].name if ga.items else None, period_b=gb.items[0].name if gb.items else None, delta=None),
    ]

    shifts = []
    energy_delta = _delta(oa.avg_energy, ob.avg_energy)
    valence_delta = _delta(oa.avg_valence, ob.avg_valence)
    novelty_delta = _delta(na.novelty_ratio, nb.novelty_ratio)
    if energy_delta is not None:
        if energy_delta > 0.05:
            shifts.append(f'listening became more energetic (+{energy_delta})')
        elif energy_delta < -0.05:
            shifts.append(f'listening became calmer ({energy_delta})')
    if valence_delta is not None:
        if valence_delta > 0.05:
            shifts.append(f'music became more positive (+{valence_delta})')
        elif valence_delta < -0.05:
            shifts.append(f'music became more introspective ({valence_delta})')
    if novelty_delta is not None:
        if novelty_delta > 0.05:
            shifts.append(f'exploration increased (+{novelty_delta})')
        elif novelty_delta < -0.05:
            shifts.append(f'listening became more repetitive ({novelty_delta})')
    if not shifts:
        shifts.append('behaviour was broadly stable across the two periods')

    label_a = f"{from_a or 'all-time'} to {to_a or 'now'}"
    label_b = f"{from_b or 'all-time'} to {to_b or 'now'}"

    return PeriodCompareResult(
        label_a=label_a,
        label_b=label_b,
        metrics=metrics,
        summary='; '.join(shifts).capitalize() + '.',
    )


# =====================================================================
# HIGHLIGHTS (demo-friendly snapshot)
# =====================================================================
def highlights(db: Session, user_id: int,
               dt_from: Optional[str] = None,
               dt_to: Optional[str] = None) -> HighlightsResult:
    overview_result = overview(db, user_id, dt_from, dt_to)
    novelty_result = novelty(db, user_id, dt_from, dt_to)
    top_artist_result = top(db, user_id, "artist", 1, dt_from, dt_to)
    top_genre_result = top(db, user_id, "genre", 1, dt_from, dt_to)

    events = _base_query(db, user_id, dt_from, dt_to).all()
    peak_hour = None
    if events:
        hours = Counter(event.listened_at.hour for event in events if event.listened_at)
        if hours:
            hour, _ = hours.most_common(1)[0]
            peak_hour = f"{hour:02d}:00"

    return HighlightsResult(
        period_start=dt_from or "all-time",
        period_end=dt_to or "now",
        total_events=overview_result.total_events,
        top_artist=top_artist_result.items[0].name if top_artist_result.items else None,
        top_genre=top_genre_result.items[0].name if top_genre_result.items else None,
        novelty_ratio=novelty_result.novelty_ratio,
        dominant_mood=overview_result.dominant_mood,
        peak_hour=peak_hour,
    )


# =====================================================================
# RECENT VS PREVIOUS COMPARISON
# =====================================================================
def compare_recent(db: Session, user_id: int, days: int = 30) -> PeriodCompareResult:
    now = datetime.now(timezone.utc)
    period_b_start = (now - timedelta(days=days)).date().isoformat()
    period_b_end = now.date().isoformat()
    period_a_start = (now - timedelta(days=days * 2)).date().isoformat()
    period_a_end = (now - timedelta(days=days)).date().isoformat()
    return compare_periods(db, user_id, period_a_start, period_a_end, period_b_start, period_b_end)
