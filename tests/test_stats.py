def _create_team(client, name: str):
    r = client.post("/teams", json={"name": name, "league": "BUCS"})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _create_player(client, team_id: int, name: str = "Stats Player"):
    r = client.post("/players", json={"name": name, "position": "Outside", "team_id": team_id})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def _create_match(client, home_team_id: int, away_team_id: int, date: str = "2026-02-10"):
    r = client.post(
        "/matches",
        json={
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": 3,
            "away_score": 1,
            "match_date": date,
        },
    )
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_duplicate_stats_returns_409(client):
    # Arrange: create teams, player, match
    team_a = _create_team(client, "Team A Stats")
    team_b = _create_team(client, "Team B Stats")
    player_id = _create_player(client, team_a, "Player Stats Duplicate")
    match_id = _create_match(client, team_a, team_b, "2026-02-01")

    payload = {
        "player_id": player_id,
        "match_id": match_id,
        "points": 12,
        "assists": 3,
        "errors": 2,
    }

    # Act: first insert succeeds
    r1 = client.post("/stats", json=payload)
    assert r1.status_code == 201

    # Act: second insert with same (player_id, match_id) should conflict
    r2 = client.post("/stats", json=payload)
    assert r2.status_code == 409

    body = r2.json()
    assert "detail" in body
    # Be tolerant: just ensure it's a conflict-style payload
    assert isinstance(body["detail"], dict)
    assert "message" in body["detail"]


def test_create_stats_missing_player_returns_404(client):
    team_a = _create_team(client, "Team A Missing Player")
    team_b = _create_team(client, "Team B Missing Player")
    match_id = _create_match(client, team_a, team_b, "2026-02-02")

    r = client.post(
        "/stats",
        json={
            "player_id": 999999,  # does not exist
            "match_id": match_id,
            "points": 5,
            "assists": 1,
            "errors": 0,
        },
    )
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body


def test_create_stats_missing_match_returns_404(client):
    team_a = _create_team(client, "Team A Missing Match")
    player_id = _create_player(client, team_a, "Player Missing Match")

    r = client.post(
        "/stats",
        json={
            "player_id": player_id,
            "match_id": 999999,  # does not exist
            "points": 5,
            "assists": 1,
            "errors": 0,
        },
    )
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body