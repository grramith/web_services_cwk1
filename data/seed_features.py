"""
Seed realistic audio features for tracks missing energy data.
Uses genre-based statistical distributions.

Usage:  python data/seed_features.py
"""

import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROFILES = {
    "pop":        {"energy":(0.65,0.15),"valence":(0.55,0.18),"danceability":(0.67,0.13),"acousticness":(0.20,0.18),"instrumentalness":(0.02,0.05),"speechiness":(0.06,0.05),"liveness":(0.16,0.12),"loudness":(-6.0,2.5),"tempo":(120.0,20.0)},
    "hip hop":    {"energy":(0.68,0.14),"valence":(0.48,0.19),"danceability":(0.75,0.10),"acousticness":(0.15,0.15),"instrumentalness":(0.01,0.03),"speechiness":(0.18,0.12),"liveness":(0.15,0.10),"loudness":(-6.5,2.0),"tempo":(128.0,25.0)},
    "rock":       {"energy":(0.75,0.15),"valence":(0.45,0.20),"danceability":(0.50,0.14),"acousticness":(0.15,0.18),"instrumentalness":(0.05,0.10),"speechiness":(0.05,0.04),"liveness":(0.20,0.15),"loudness":(-7.0,3.0),"tempo":(125.0,22.0)},
    "r&b":        {"energy":(0.55,0.17),"valence":(0.50,0.20),"danceability":(0.68,0.12),"acousticness":(0.30,0.22),"instrumentalness":(0.02,0.05),"speechiness":(0.08,0.07),"liveness":(0.14,0.10),"loudness":(-7.5,2.5),"tempo":(115.0,22.0)},
    "electronic": {"energy":(0.78,0.14),"valence":(0.40,0.20),"danceability":(0.70,0.12),"acousticness":(0.05,0.08),"instrumentalness":(0.35,0.30),"speechiness":(0.07,0.06),"liveness":(0.12,0.10),"loudness":(-6.5,2.5),"tempo":(128.0,15.0)},
    "indie":      {"energy":(0.58,0.18),"valence":(0.42,0.20),"danceability":(0.52,0.15),"acousticness":(0.35,0.25),"instrumentalness":(0.08,0.15),"speechiness":(0.04,0.03),"liveness":(0.15,0.12),"loudness":(-8.5,3.0),"tempo":(120.0,25.0)},
    "jazz":       {"energy":(0.35,0.18),"valence":(0.45,0.22),"danceability":(0.52,0.15),"acousticness":(0.65,0.22),"instrumentalness":(0.25,0.25),"speechiness":(0.05,0.04),"liveness":(0.18,0.14),"loudness":(-12.0,4.0),"tempo":(115.0,30.0)},
    "classical":  {"energy":(0.25,0.18),"valence":(0.35,0.20),"danceability":(0.28,0.15),"acousticness":(0.90,0.10),"instrumentalness":(0.85,0.15),"speechiness":(0.04,0.02),"liveness":(0.12,0.10),"loudness":(-18.0,6.0),"tempo":(110.0,35.0)},
    "metal":      {"energy":(0.90,0.08),"valence":(0.30,0.18),"danceability":(0.40,0.12),"acousticness":(0.03,0.05),"instrumentalness":(0.08,0.15),"speechiness":(0.06,0.05),"liveness":(0.20,0.15),"loudness":(-5.0,2.0),"tempo":(135.0,25.0)},
    "latin":      {"energy":(0.72,0.14),"valence":(0.62,0.18),"danceability":(0.74,0.10),"acousticness":(0.22,0.20),"instrumentalness":(0.02,0.05),"speechiness":(0.10,0.08),"liveness":(0.16,0.12),"loudness":(-6.0,2.5),"tempo":(118.0,22.0)},
}

DEFAULT = {"energy":(0.55,0.22),"valence":(0.45,0.22),"danceability":(0.55,0.18),"acousticness":(0.30,0.25),"instrumentalness":(0.10,0.20),"speechiness":(0.08,0.08),"liveness":(0.18,0.14),"loudness":(-9.0,4.0),"tempo":(120.0,28.0)}

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def get_profile(genre):
    if not genre:
        return DEFAULT
    gl = genre.lower()
    for key in PROFILES:
        if key in gl or gl in key:
            return PROFILES[key]
    return DEFAULT

def main():
    from app.database import SessionLocal
    from app.models import Track
    db = SessionLocal()
    tracks = db.query(Track).filter(Track.energy.is_(None)).all()
    if not tracks:
        print("All tracks already have audio features.")
        db.close()
        return
    print(f"Seeding features for {len(tracks)} tracks...")
    for t in tracks:
        p = get_profile(t.genre)
        for f in ["energy","valence","danceability","acousticness",
                   "instrumentalness","speechiness","liveness"]:
            setattr(t, f, round(clamp(random.gauss(*p[f])), 4))
        t.loudness = round(random.gauss(*p["loudness"]), 2)
        t.tempo = round(max(40.0, random.gauss(*p["tempo"])), 2)
    db.commit()
    db.close()
    print(f"Done — {len(tracks)} tracks updated.")

if __name__ == "__main__":
    main()
