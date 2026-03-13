"""Track feedback CRUD routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import CatalogTrack, TrackFeedback, User
from app.schemas import FeedbackCreate, FeedbackListItem, FeedbackRead, FeedbackUpdate

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("", response_model=FeedbackRead, status_code=201, summary="Create feedback for a catalog track")
def create_feedback(
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(CatalogTrack).filter(CatalogTrack.id == body.catalog_track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Catalog track not found")
    fb = TrackFeedback(user_id=user.id, catalog_track_id=body.catalog_track_id, rating=body.rating, note=body.note)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


@router.get("", response_model=list[FeedbackListItem], summary="List your feedback records")
def list_feedback(
    rating: str | None = Query(None, pattern="^(like|dislike|save|skip)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(TrackFeedback, CatalogTrack).join(CatalogTrack, CatalogTrack.id == TrackFeedback.catalog_track_id).filter(TrackFeedback.user_id == user.id)
    if rating:
        q = q.filter(TrackFeedback.rating == rating)
    rows = q.order_by(TrackFeedback.updated_at.desc()).all()
    items = []
    for fb, track in rows:
        items.append(FeedbackListItem(
            id=fb.id,
            user_id=fb.user_id,
            catalog_track_id=fb.catalog_track_id,
            rating=fb.rating,
            note=fb.note,
            created_at=fb.created_at,
            updated_at=fb.updated_at,
            track_name=track.name,
            artist=track.artist,
            genre=track.genre,
        ))
    return items


@router.patch("/{feedback_id}", response_model=FeedbackRead, summary="Update a feedback record")
def update_feedback(
    feedback_id: int,
    body: FeedbackUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fb = db.query(TrackFeedback).filter(TrackFeedback.id == feedback_id, TrackFeedback.user_id == user.id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if body.rating is not None:
        fb.rating = body.rating
    if body.note is not None:
        fb.note = body.note
    db.commit()
    db.refresh(fb)
    return fb


@router.delete("/{feedback_id}", summary="Delete a feedback record")
def delete_feedback(feedback_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fb = db.query(TrackFeedback).filter(TrackFeedback.id == feedback_id, TrackFeedback.user_id == user.id).first()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    db.delete(fb)
    db.commit()
    return {"status": "deleted", "feedback_id": feedback_id}
