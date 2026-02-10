def test_duplicate_team_name_returns_409(client):
    payload = {"name": "Leeds Volleyball", "league": "BUCS"}

    r1 = client.post("/teams", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/teams", json=payload)
    assert r2.status_code == 409
    body = r2.json()
    assert "detail" in body
    assert body["detail"]["code"] == "CONFLICT"


def test_invalid_match_home_equals_away_returns_422(client):
    # Create a team
    t = client.post("/teams", json={"name": "Team A", "league": "BUCS"})
    assert t.status_code == 201
    team_id = t.json()["data"]["id"]

    # Attempt to create invalid match where home == away
    bad_match = {
        "home_team_id": team_id,
        "away_team_id": team_id,
        "home_score": 3,
        "away_score": 1,
        "match_date": "2026-02-10",
    }
    r = client.post("/matches", json=bad_match)
    assert r.status_code == 422


def test_team_form_analytics_correct_wins_losses(client):
    # Create two teams
    t1 = client.post("/teams", json={"name": "Leeds Analytics", "league": "BUCS"})
    t2 = client.post("/teams", json={"name": "Sheffield Analytics", "league": "BUCS"})
    assert t1.status_code == 201 and t2.status_code == 201
    leeds_id = t1.json()["data"]["id"]
    sheff_id = t2.json()["data"]["id"]

    # Create two matches: Leeds wins first, loses second
    m1 = client.post(
        "/matches",
        json={
            "home_team_id": leeds_id,
            "away_team_id": sheff_id,
            "home_score": 3,
            "away_score": 1,
            "match_date": "2026-02-01",
        },
    )
    assert m1.status_code == 201

    m2 = client.post(
        "/matches",
        json={
            "home_team_id": sheff_id,
            "away_team_id": leeds_id,
            "home_score": 3,
            "away_score": 2,
            "match_date": "2026-02-08",
        },
    )
    assert m2.status_code == 201

    # Call analytics: team form
    r = client.get(f"/analytics/team/{leeds_id}/form", params={"last_n": 5})
    assert r.status_code == 200
    data = r.json()["data"]

    # Expected:
    # Played 2, wins 1, losses 1
    # points_for = 3 + 2 = 5
    # points_against = 1 + 3 = 4
    # recent_results newest first: ["L","W"]
    assert data["team_id"] == leeds_id
    assert data["played"] == 2
    assert data["wins"] == 1
    assert data["losses"] == 1
    assert data["points_for"] == 5
    assert data["points_against"] == 4
    assert data["recent_results"] == ["L", "W"]