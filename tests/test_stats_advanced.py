def _create_team(client, name: str):
    r = client.post("/teams", json={"name": name, "league": "BUCS"})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _create_match(client, home_team_id: int, away_team_id: int, home_score: int, away_score: int, date: str):
    r = client.post(
        "/matches",
        json={
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": home_score,
            "away_score": away_score,
            "match_date": date,
        },
    )
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _create_player(client, team_id: int, name: str):
    r = client.post("/players", json={"name": name, "position": "Outside", "team_id": team_id})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _create_stats(client, player_id: int, match_id: int, points: int, assists: int, errors: int):
    r = client.post(
        "/stats",
        json={
            "player_id": player_id,
            "match_id": match_id,
            "points": points,
            "assists": assists,
            "errors": errors,
        },
    )
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_league_table_orders_by_points_then_diff(client):
    # Create 3 teams
    a = _create_team(client, "Table Team A")
    b = _create_team(client, "Table Team B")
    c = _create_team(client, "Table Team C")

    # Make A and B both win once (3 points each), but A has better points_diff
    # A beats C 3-0 => A diff +3
    _create_match(client, a, c, 3, 0, "2026-02-01")

    # B beats C 3-2 => B diff +1
    _create_match(client, b, c, 3, 2, "2026-02-02")

    # League table should rank A above B above C
    r = client.get("/analytics/league/table")
    assert r.status_code == 200
    rows = r.json()["data"]

    # Filter league table down to only the teams created in this test
    subset = [row for row in rows if row["team_id"] in {a, b, c}]
    assert len(subset) == 3

    # Now assert ordering within this subset
    assert subset[0]["team_id"] == a
    assert subset[1]["team_id"] == b
    assert subset[2]["team_id"] == c


def test_team_form_respects_last_n_limit(client):
    a = _create_team(client, "Form Team A")
    b = _create_team(client, "Form Team B")

    # Create 3 matches involving team A:
    # Date ascending: 1st W, 2nd L, 3rd W (latest should be W)
    _create_match(client, a, b, 3, 1, "2026-02-01")  # W
    _create_match(client, b, a, 3, 2, "2026-02-05")  # L (A away loses)
    _create_match(client, a, b, 3, 0, "2026-02-09")  # W

    # last_n=2 should include only the latest 2 results: (2026-02-09 W) and (2026-02-05 L)
    r = client.get(f"/analytics/team/{a}/form", params={"last_n": 2})
    assert r.status_code == 200
    data = r.json()["data"]

    assert data["played"] == 2
    assert data["wins"] == 1
    assert data["losses"] == 1
    assert data["recent_results"] == ["W", "L"]


def test_player_trend_improving_and_declining(client):
    # Create teams + two matches
    a = _create_team(client, "Trend Team A")
    b = _create_team(client, "Trend Team B")

    m1 = _create_match(client, a, b, 3, 1, "2026-02-01")
    m2 = _create_match(client, b, a, 3, 2, "2026-02-08")

    # Player with improving points: 10 -> 16
    p1 = _create_player(client, a, "Trend Player Improving")
    _create_stats(client, p1, m1, points=10, assists=2, errors=3)
    _create_stats(client, p1, m2, points=16, assists=4, errors=1)

    r1 = client.get(f"/analytics/player/{p1}/trend")
    assert r1.status_code == 200
    assert r1.json()["data"]["trend"] == "improving"
    assert r1.json()["data"]["best_match_id"] == m2

    # Player with declining points: 16 -> 10
    p2 = _create_player(client, a, "Trend Player Declining")
    _create_stats(client, p2, m1, points=16, assists=2, errors=3)
    _create_stats(client, p2, m2, points=10, assists=4, errors=1)

    r2 = client.get(f"/analytics/player/{p2}/trend")
    assert r2.status_code == 200
    assert r2.json()["data"]["trend"] == "declining"
    assert r2.json()["data"]["best_match_id"] == m1