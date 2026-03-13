"""Catalog dataset import service using kagglehub."""

from __future__ import annotations

import os
from typing import Any

import kagglehub
from kagglehub import KaggleDatasetAdapter
from sqlalchemy.orm import Session

from app.models import CatalogTrack


COLUMN_ALIASES = {
    "track_name": "name",
    "song_name": "name",
    "song": "name",
    "name": "name",
    "artist_name": "artist",
    "artist": "artist",
    "album_name": "album",
    "album": "album",
    "track_genre": "genre",
    "genre": "genre",
    "id": "external_id",
    "track_id": "external_id",
    "danceability": "danceability",
    "energy": "energy",
    "valence": "valence",
    "tempo": "tempo",
    "acousticness": "acousticness",
    "instrumentalness": "instrumentalness",
    "speechiness": "speechiness",
    "liveness": "liveness",
}

FLOAT_FIELDS = [
    "energy", "valence", "danceability", "tempo",
    "acousticness", "instrumentalness", "speechiness", "liveness",
]


def _safe_float(value: Any):
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _inject_kaggle_credentials() -> None:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return
    try:
        from app.config import settings
        if settings.KAGGLE_USERNAME and settings.KAGGLE_KEY:
            os.environ["KAGGLE_USERNAME"] = settings.KAGGLE_USERNAME
            os.environ["KAGGLE_KEY"] = settings.KAGGLE_KEY
    except Exception:
        pass


def import_catalog_tracks(db: Session, dataset_slug: str, file_path: str = "") -> dict[str, int]:
    _inject_kaggle_credentials()

    df = kagglehub.load_dataset(
        KaggleDatasetAdapter.PANDAS,
        dataset_slug,
        file_path,
    )

    present_map = {src: dest for src, dest in COLUMN_ALIASES.items() if src in df.columns}
    df = df.rename(columns=present_map)

    defaults = {
        "external_id": None, "name": None, "artist": None,
        "album": None, "genre": None, "energy": None, "valence": None,
        "danceability": None, "tempo": None, "acousticness": None,
        "instrumentalness": None, "speechiness": None, "liveness": None,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    inserted = 0
    updated = 0
    seen_ids: set[str] = set()  # guard against duplicates within the CSV

    for _, row in df.iterrows():
        name = row.get("name")
        artist = row.get("artist")
        if not name or not artist:
            continue

        external_id = str(row.get("external_id") or f"{name}::{artist}")

        if external_id in seen_ids:
            continue
        seen_ids.add(external_id)

        existing = db.query(CatalogTrack).filter(CatalogTrack.external_id == external_id).first()

        payload = {
            "external_id": external_id,
            "name": str(name),
            "artist": str(artist),
            "album": str(row.get("album")) if row.get("album") is not None else None,
            "genre": str(row.get("genre")) if row.get("genre") is not None else None,
            "source_dataset": dataset_slug,
            "metadata_json": {},
        }
        for field in FLOAT_FIELDS:
            payload[field] = _safe_float(row.get(field))

        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            updated += 1
        else:
            db.add(CatalogTrack(**payload))
            inserted += 1

    db.commit()
    return {"inserted": inserted, "updated": updated, "total_rows": int(len(df))}