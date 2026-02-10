from __future__ import annotations

from typing import List, Tuple, Optional

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models.team import Team
from app.models.match import Match
from app.models.player_stats import PlayerStats


def _result_for_team(team_id: int, match: Match) -> Tuple[str, int, int]:
    """
    Returns (result, points_for, points_against) where result is "W"/"L"/"D".
    """
    if match.home_team_id == team_id:
        pf, pa = match.home_score, match.away_score
    else:
        pf, pa = match.away_score, match.home_score

    if pf > pa:
        return "W", pf, pa
    if pf < pa:
        return "L", pf, pa
    return "D", pf, pa


def get_team_form(db: Session, team_id: int, last_n: int) -> dict:
    # Fetch last N matches involving the team
    stmt = (
        select(Match)
        .where(or_(Match.home_team_id == team_id, Match.away_team_id == team_id))
        .order_by(Match.match_date.desc(), Match.id.desc())
        .limit(last_n)
    )
    matches = db.execute(stmt).scalars().all()

    played = len(matches)
    wins = losses = draws = 0
    points_for = points_against = 0
    recent_results: List[str] = []

    for m in matches:
        res, pf, pa = _result_for_team(team_id, m)
        recent_results.append(res)
        points_for += pf
        points_against += pa
        if res == "W":
            wins += 1
        elif res == "L":
            losses += 1
        else:
            draws += 1

    win_percentage = (wins / played) if played > 0 else 0.0

    return {
        "team_id": team_id,
        "last_n": last_n,
        "played": played,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "points_for": points_for,
        "points_against": points_against,
        "win_percentage": round(win_percentage, 4),
        "recent_results": recent_results,
    }


def get_league_table(db: Session) -> List[dict]:
    teams = db.execute(select(Team).order_by(Team.id)).scalars().all()
    matches = db.execute(select(Match)).scalars().all()

    # Index team stats by id
    table = {}
    for t in teams:
        table[t.id] = {
            "team_id": t.id,
            "team_name": t.name,
            "played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "points_for": 0,
            "points_against": 0,
            "points_diff": 0,
            "points": 0,  # 3 win, 1 draw, 0 loss
        }

    for m in matches:
        # Home team update
        home = table.get(m.home_team_id)
        away = table.get(m.away_team_id)
        if home is None or away is None:
            # If teams were deleted (or soft-deleted later), skip safely
            continue

        home["played"] += 1
        away["played"] += 1

        home["points_for"] += m.home_score
        home["points_against"] += m.away_score
        away["points_for"] += m.away_score
        away["points_against"] += m.home_score

        if m.home_score > m.away_score:
            home["wins"] += 1
            away["losses"] += 1
            home["points"] += 3
        elif m.home_score < m.away_score:
            away["wins"] += 1
            home["losses"] += 1
            away["points"] += 3
        else:
            # draw (not typical for volleyball, but robust)
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1

    # Compute points difference
    for row in table.values():
        row["points_diff"] = row["points_for"] - row["points_against"]

    # Sort by: points desc, points_diff desc, points_for desc, team_name asc
    sorted_rows = sorted(
        table.values(),
        key=lambda r: (-r["points"], -r["points_diff"], -r["points_for"], r["team_name"].lower()),
    )
    return sorted_rows


def _simple_slope(values: List[float]) -> float:
    """
    Simple slope over index (0..n-1) using least squares.
    Returns 0.0 if not enough data.
    """
    n = len(values)
    if n < 2:
        return 0.0

    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n

    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    return (num / den) if den != 0 else 0.0


def get_player_trend(db: Session, player_id: int) -> dict:
    # Fetch all stats rows for player (ordered by match date)
    # We'll join Match implicitly by using match_id then sorting in Python.
    stats_rows = db.execute(
        select(PlayerStats).where(PlayerStats.player_id == player_id)
    ).scalars().all()

    if not stats_rows:
        return {
            "player_id": player_id,
            "matches_played": 0,
            "avg_points": 0.0,
            "avg_assists": 0.0,
            "avg_errors": 0.0,
            "best_match_id": None,
            "best_match_points": None,
            "trend": "stable",
        }

    # Load matches for ordering + best match logic
    match_ids = list({s.match_id for s in stats_rows})
    match_map = {m.id: m for m in db.execute(select(Match).where(Match.id.in_(match_ids))).scalars().all()}

    # Sort stats by match_date (fallback: match_id)
    stats_rows.sort(key=lambda s: (match_map.get(s.match_id).match_date if match_map.get(s.match_id) else None, s.match_id))

    points_list = [float(s.points) for s in stats_rows]
    assists_list = [float(s.assists) for s in stats_rows]
    errors_list = [float(s.errors) for s in stats_rows]

    matches_played = len(stats_rows)
    avg_points = sum(points_list) / matches_played
    avg_assists = sum(assists_list) / matches_played
    avg_errors = sum(errors_list) / matches_played

    # Best match by points
    best = max(stats_rows, key=lambda s: s.points)
    best_match_id = best.match_id
    best_match_points = best.points

    # Trend based on slope of points over time
    slope = _simple_slope(points_list)
    if slope > 0.1:
        trend = "improving"
    elif slope < -0.1:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "player_id": player_id,
        "matches_played": matches_played,
        "avg_points": round(avg_points, 4),
        "avg_assists": round(avg_assists, 4),
        "avg_errors": round(avg_errors, 4),
        "best_match_id": best_match_id,
        "best_match_points": best_match_points,
        "trend": trend,
    }
