"""Model Context Protocol (MCP) server implementation.

Exposes Sonic Insights tools via the MCP standard, making the API
compatible with MCP-enabled AI clients (e.g. Claude Desktop, Cursor).

GET  /mcp/manifest  — list all available tools and their schemas
POST /mcp/invoke    — invoke a named tool with arguments
"""

import math
import statistics
from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import CatalogTrack, ListeningEvent, Track, User

router = APIRouter(prefix="/mcp", tags=["MCP"])


# ── MCP schemas ───────────────────────────────────────────────────────────────

class MCPToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True


class MCPTool(BaseModel):
    name: str
    description: str
    parameters: list[MCPToolParameter]


class MCPManifest(BaseModel):
    schema_version: str = "1.0"
    name: str
    description: str
    tools: list[MCPTool]


class MCPInvokeRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}


class MCPInvokeResult(BaseModel):
    tool: str
    success: bool
    result: Any
    error: Optional[str] = None


# ── tool registry ─────────────────────────────────────────────────────────────

TOOLS = [
    MCPTool(
        name="search_catalog",
        description="Search the Sonic Insights music catalog by track name, artist, or genre.",
        parameters=[
            MCPToolParameter(name="query", type="string",
                             description="Track name or artist to search for"),
            MCPToolParameter(name="genre", type="string",
                             description="Filter by genre e.g. pop, rock, hip hop",
                             required=False),
            MCPToolParameter(name="limit", type="integer",
                             description="Max results (default 5)",
                             required=False),
        ],
    ),
    MCPTool(
        name="recommend_by_mood",
        description=(
            "Get music recommendations based on a natural language mood description "
            "e.g. 'rainy sunday afternoon' or 'pre-match hype'."
        ),
        parameters=[
            MCPToolParameter(name="description", type="string",
                             description="Natural language mood description"),
            MCPToolParameter(name="limit", type="integer",
                             description="Number of recommendations (default 5)",
                             required=False),
        ],
    ),
    MCPTool(
        name="get_listening_summary",
        description="Get a summary of the user's listening history, top tracks, and mood profile.",
        parameters=[],
    ),
    MCPTool(
        name="get_catalog_mood_map",
        description=(
            "Get the mood quadrant breakdown of the full catalog showing how many tracks "
            "are Happy, Calm, Angry, or Sad based on their audio features."
        ),
        parameters=[],
    ),
    MCPTool(
        name="find_similar_tracks",
        description="Find catalog tracks sonically similar to a given track ID using cosine similarity.",
        parameters=[
            MCPToolParameter(name="track_id", type="integer",
                             description="Catalog track ID to find similar tracks for"),
            MCPToolParameter(name="limit", type="integer",
                             description="Number of similar tracks (default 5)",
                             required=False),
        ],
    ),
]


# ── tool implementations ──────────────────────────────────────────────────────

MOOD_KEYWORDS = {
    "happy": {"valence_min": 0.65}, "upbeat": {"valence_min": 0.6},
    "sad": {"valence_max": 0.4}, "dark": {"valence_max": 0.35},
    "energetic": {"energy_min": 0.7}, "calm": {"energy_max": 0.45},
    "chill": {"energy_max": 0.5}, "hype": {"energy_min": 0.75},
    "rainy": {"valence_max": 0.45, "energy_max": 0.5},
    "study": {"energy_max": 0.55}, "party": {"valence_min": 0.6, "energy_min": 0.65},
    "angry": {"valence_max": 0.45, "energy_min": 0.65},
    "night": {"energy_max": 0.55}, "morning": {"energy_max": 0.6, "valence_min": 0.45},
    "workout": {"energy_min": 0.7}, "focus": {"energy_max": 0.6},
    "acoustic": {"acousticness_min": 0.5}, "sunday": {"acousticness_min": 0.3, "energy_max": 0.55},
}

FEATURES = ["energy", "valence", "danceability", "acousticness",
            "instrumentalness", "speechiness", "liveness"]


def _mood_label(energy: float, valence: float) -> str:
    if energy >= 0.55 and valence >= 0.55:
        return "Happy"
    if energy >= 0.55 and valence < 0.55:
        return "Angry"
    if energy < 0.55 and valence >= 0.55:
        return "Calm"
    return "Sad"


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    ma = math.sqrt(sum(x * x for x in a))
    mb = math.sqrt(sum(y * y for y in b))
    return round(dot / (ma * mb), 4) if ma and mb else 0.0


def _to_vec(track: CatalogTrack) -> list:
    vec = [getattr(track, f) or 0.0 for f in FEATURES]
    vec.append((track.tempo or 0.0) / 250.0)
    return vec


def _search_catalog(args: dict, db: Session) -> dict:
    query_str = args.get("query", "")
    genre = args.get("genre")
    limit = min(int(args.get("limit", 5)), 20)

    q = db.query(CatalogTrack)
    if query_str:
        p = f"%{query_str}%"
        q = q.filter(CatalogTrack.name.ilike(p) | CatalogTrack.artist.ilike(p))
    if genre:
        q = q.filter(CatalogTrack.genre.ilike(f"%{genre}%"))

    tracks = q.limit(limit).all()
    return {
        "total_found": len(tracks),
        "tracks": [
            {"id": t.id, "name": t.name, "artist": t.artist,
             "genre": t.genre, "energy": t.energy, "valence": t.valence}
            for t in tracks
        ],
    }


def _recommend_by_mood(args: dict, db: Session) -> dict:
    description = args.get("description", "")
    limit = min(int(args.get("limit", 5)), 20)

    words = description.lower().split()
    targets: dict = {}
    matched = []
    for word in words:
        if word in MOOD_KEYWORDS:
            matched.append(word)
            for k, v in MOOD_KEYWORDS[word].items():
                targets[k] = v

    def tval(feature):
        mn, mx = f"{feature}_min", f"{feature}_max"
        if mn in targets and mx in targets:
            return (targets[mn] + targets[mx]) / 2
        if mn in targets:
            return min(targets[mn] + 0.1, 1.0)
        if mx in targets:
            return max(targets[mx] - 0.1, 0.0)
        return 0.5

    target_vec = [tval(f) for f in FEATURES] + [0.5]

    q = db.query(CatalogTrack).filter(
        CatalogTrack.energy.isnot(None),
        CatalogTrack.valence.isnot(None),
    )
    if "energy_min" in targets:
        q = q.filter(CatalogTrack.energy >= targets["energy_min"])
    if "energy_max" in targets:
        q = q.filter(CatalogTrack.energy <= targets["energy_max"])
    if "valence_min" in targets:
        q = q.filter(CatalogTrack.valence >= targets["valence_min"])
    if "valence_max" in targets:
        q = q.filter(CatalogTrack.valence <= targets["valence_max"])

    candidates = q.all()
    scored = sorted(
        [(t, _cosine(target_vec, _to_vec(t))) for t in candidates],
        key=lambda x: -x[1]
    )

    return {
        "description": description,
        "matched_keywords": matched,
        "total_candidates": len(candidates),
        "recommendations": [
            {"id": t.id, "name": t.name, "artist": t.artist,
             "genre": t.genre, "mood_match_score": s,
             "mood_label": _mood_label(t.energy or 0.5, t.valence or 0.5)}
            for t, s in scored[:limit]
        ],
    }


def _get_listening_summary(args: dict, db: Session, user: User) -> dict:
    events = db.query(ListeningEvent).filter(
        ListeningEvent.user_id == user.id).all()
    if not events:
        return {"total_events": 0, "message": "No listening history found"}

    track_ids = {e.track_id for e in events}
    tracks = {t.id: t for t in db.query(Track).filter(
        Track.id.in_(track_ids)).all()}

    play_counts: Counter = Counter()
    moods: Counter = Counter()
    genres: Counter = Counter()

    for e in events:
        t = tracks.get(e.track_id)
        if not t:
            continue
        play_counts[t.title] += 1
        if t.energy is not None and t.valence is not None:
            moods[_mood_label(t.energy, t.valence)] += 1
        if t.genre:
            genres[t.genre] += 1

    return {
        "total_events": len(events),
        "unique_tracks": len(track_ids),
        "top_track": play_counts.most_common(1)[0][0] if play_counts else None,
        "dominant_mood": moods.most_common(1)[0][0] if moods else None,
        "top_genre": genres.most_common(1)[0][0] if genres else None,
        "mood_breakdown": dict(moods.most_common()),
    }


def _get_catalog_mood_map(args: dict, db: Session) -> dict:
    tracks = db.query(CatalogTrack).filter(
        CatalogTrack.energy.isnot(None),
        CatalogTrack.valence.isnot(None),
    ).all()

    buckets: Counter = Counter()
    for t in tracks:
        buckets[_mood_label(t.energy, t.valence)] += 1

    total = len(tracks)
    return {
        "total_tracks": total,
        "quadrants": {
            mood: {"count": count, "percentage": round(count / total * 100, 2)}
            for mood, count in buckets.most_common()
        },
        "most_common_mood": buckets.most_common(1)[0][0] if buckets else None,
    }


def _find_similar_tracks(args: dict, db: Session) -> dict:
    track_id = args.get("track_id")
    limit = min(int(args.get("limit", 5)), 20)

    if not track_id:
        raise ValueError("track_id is required")

    seed = db.query(CatalogTrack).filter(CatalogTrack.id == int(track_id)).first()
    if not seed:
        raise ValueError(f"Track {track_id} not found")

    seed_vec = _to_vec(seed)
    BAND = 0.35
    candidates = db.query(CatalogTrack).filter(
        CatalogTrack.id != seed.id,
        CatalogTrack.energy.isnot(None),
        CatalogTrack.valence.isnot(None),
        CatalogTrack.energy.between(
            max(0.0, (seed.energy or 0.5) - BAND),
            min(1.0, (seed.energy or 0.5) + BAND)),
        CatalogTrack.valence.between(
            max(0.0, (seed.valence or 0.5) - BAND),
            min(1.0, (seed.valence or 0.5) + BAND)),
    ).all()

    scored = sorted(
        [(t, _cosine(seed_vec, _to_vec(t))) for t in candidates],
        key=lambda x: -x[1]
    )

    return {
        "seed_track": {"id": seed.id, "name": seed.name, "artist": seed.artist},
        "similar_tracks": [
            {"id": t.id, "name": t.name, "artist": t.artist,
             "genre": t.genre, "similarity_score": s}
            for t, s in scored[:limit]
        ],
    }


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/manifest", response_model=MCPManifest,
            summary="List all available MCP tools and their input schemas")
def get_manifest():
    return MCPManifest(
        schema_version="1.0",
        name="sonic-insights-mcp",
        description=(
            "MCP server for Sonic Insights — exposes music catalog search, "
            "mood-based recommendations, listening history analysis, and "
            "audio similarity search as callable tools."
        ),
        tools=TOOLS,
    )


@router.post("/invoke", response_model=MCPInvokeResult,
             summary="Invoke a named MCP tool with arguments",
             description=(
                 "Executes one of the registered Sonic Insights tools by name. "
                 "Call GET /mcp/manifest first to see available tools and their parameters."
             ))
def invoke_tool(
    body: MCPInvokeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tool_names = {t.name for t in TOOLS}
    if body.tool not in tool_names:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{body.tool}' not found. Available tools: {sorted(tool_names)}"
        )

    try:
        if body.tool == "search_catalog":
            result = _search_catalog(body.arguments, db)
        elif body.tool == "recommend_by_mood":
            result = _recommend_by_mood(body.arguments, db)
        elif body.tool == "get_listening_summary":
            result = _get_listening_summary(body.arguments, db, user)
        elif body.tool == "get_catalog_mood_map":
            result = _get_catalog_mood_map(body.arguments, db)
        elif body.tool == "find_similar_tracks":
            result = _find_similar_tracks(body.arguments, db)
        else:
            raise ValueError(f"Tool handler not implemented: {body.tool}")

        return MCPInvokeResult(tool=body.tool, success=True, result=result)

    except ValueError as e:
        return MCPInvokeResult(tool=body.tool, success=False,
                               result=None, error=str(e))
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Tool execution failed: {str(e)}")