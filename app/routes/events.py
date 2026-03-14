"""
Listening events — full CRUD entity + SSE live stream.

POST   /listening-events
GET    /listening-events
GET    /listening-events/stream   ← must be before /{event_id}
GET    /listening-events/{event_id}
PATCH  /listening-events/{event_id}
DELETE /listening-events/{event_id}
"""

import asyncio
import json as _json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import ListeningEvent, Track, User
from app.schemas import EventCreate, EventList, EventRead, EventUpdate

router = APIRouter(prefix="/listening-events", tags=["Listening Events"])


@router.post("", response_model=EventRead, status_code=201,
             summary="Record a new listening event")
def create_event(body: EventCreate,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if not db.query(Track).filter(Track.id == body.track_id).first():
        raise HTTPException(404, "Track not found")
    event = ListeningEvent(
        user_id=user.id,
        track_id=body.track_id,
        listened_at=body.listened_at or datetime.now(timezone.utc),
        duration_listened_ms=body.duration_listened_ms,
        source="manual",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=EventList,
            summary="List your listening events (paginated, filterable)")
def list_events(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    dt_from: Optional[str] = Query(None, alias="from"),
    dt_to: Optional[str] = Query(None, alias="to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ListeningEvent).filter(ListeningEvent.user_id == user.id)
    if dt_from:
        q = q.filter(ListeningEvent.listened_at >= dt_from)
    if dt_to:
        q = q.filter(ListeningEvent.listened_at <= dt_to)
    total = q.count()
    items = q.order_by(ListeningEvent.listened_at.desc()).offset(offset).limit(limit).all()
    return EventList(
        items=[EventRead.model_validate(e) for e in items],
        total=total, offset=offset, limit=limit,
    )


@router.get(
    "/stream",
    summary="Live stream of listening events via Server-Sent Events",
    description=(
        "Opens a persistent SSE connection that pushes a JSON event to the client "
        "every time a new listening event is recorded for the authenticated user. "
        "Also emits a heartbeat every 15 seconds to keep the connection alive. "
        "Compatible with MCP clients, Claude Desktop, and any EventSource-capable client."
    ),
    response_class=StreamingResponse,
)
async def stream_events(
    user: User = Depends(get_current_user),
):
    from app.database import SessionLocal

    user_id = user.id

    async def event_generator():
        # Each poll opens and closes its own DB session — safe for async context
        with SessionLocal() as db:
            last_seen_id = (
                db.query(ListeningEvent.id)
                .filter(ListeningEvent.user_id == user_id)
                .order_by(ListeningEvent.id.desc())
                .limit(1)
                .scalar() or 0
            )

        yield (
            f"event: connected\n"
            f"data: {_json.dumps({'status': 'connected', 'user_id': user_id, 'last_seen_id': last_seen_id})}\n\n"
        )

        heartbeat_counter = 0
        while True:
            await asyncio.sleep(2)
            heartbeat_counter += 1

            # Fresh session per poll — avoids stale state in async generator
            with SessionLocal() as db:
                new_events = (
                    db.query(ListeningEvent)
                    .filter(
                        ListeningEvent.user_id == user_id,
                        ListeningEvent.id > last_seen_id,
                    )
                    .order_by(ListeningEvent.id.asc())
                    .all()
                )
                payloads = []
                for event in new_events:
                    last_seen_id = event.id
                    track = db.query(Track).filter(Track.id == event.track_id).first()
                    payloads.append({
                        "event_id": event.id,
                        "track_id": event.track_id,
                        "track_title": track.title if track else None,
                        "artist": track.artist if track else None,
                        "genre": track.genre if track else None,
                        "listened_at": event.listened_at.isoformat() if event.listened_at else None,
                        "duration_ms": event.duration_listened_ms,
                        "source": event.source,
                    })

            for payload in payloads:
                yield f"event: new_event\ndata: {_json.dumps(payload)}\n\n"

            if heartbeat_counter % 8 == 0:
                yield f"event: heartbeat\ndata: {_json.dumps({'ts': asyncio.get_event_loop().time()})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{event_id}", response_model=EventRead,
            summary="Get a single listening event")
def get_event(event_id: int,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    e = db.query(ListeningEvent).filter(
        ListeningEvent.id == event_id,
        ListeningEvent.user_id == user.id,
    ).first()
    if not e:
        raise HTTPException(404, "Event not found")
    return e


@router.patch("/{event_id}", response_model=EventRead,
              summary="Update a listening event")
def update_event(event_id: int, body: EventUpdate,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    e = db.query(ListeningEvent).filter(
        ListeningEvent.id == event_id,
        ListeningEvent.user_id == user.id,
    ).first()
    if not e:
        raise HTTPException(404, "Event not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return e


@router.delete("/{event_id}", status_code=204,
               summary="Delete a listening event")
def delete_event(event_id: int,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    e = db.query(ListeningEvent).filter(
        ListeningEvent.id == event_id,
        ListeningEvent.user_id == user.id,
    ).first()
    if not e:
        raise HTTPException(404, "Event not found")
    db.delete(e)
    db.commit()