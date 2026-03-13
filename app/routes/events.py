"""
Listening events — full CRUD entity.

POST   /listening-events
GET    /listening-events?from=&to=&limit=&offset=
GET    /listening-events/{event_id}
PATCH  /listening-events/{event_id}
DELETE /listening-events/{event_id}
"""

import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Track, ListeningEvent
from app.schemas import EventCreate, EventRead, EventUpdate, EventList
from app.auth import get_current_user

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
    dt_from: Optional[str] = Query(None, alias="from",
                                   description="ISO date start filter"),
    dt_to: Optional[str] = Query(None, alias="to",
                                 description="ISO date end filter"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (db.query(ListeningEvent)
         .filter(ListeningEvent.user_id == user.id))
    if dt_from:
        q = q.filter(ListeningEvent.listened_at >= dt_from)
    if dt_to:
        q = q.filter(ListeningEvent.listened_at <= dt_to)
    total = q.count()
    items = (q.order_by(ListeningEvent.listened_at.desc())
             .offset(offset).limit(limit).all())
    return EventList(
        items=[EventRead.model_validate(e) for e in items],
        total=total, offset=offset, limit=limit,
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
