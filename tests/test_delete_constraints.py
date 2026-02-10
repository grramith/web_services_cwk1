def test_delete_team_referenced_by_match_returns_409(client):
    # Create two teams
    t1 = client.post("/teams", json={"name": "Delete Team A", "league": "BUCS"})
    t2 = client.post("/teams", json={"name": "Delete Team B", "league": "BUCS"})
    assert t1.status_code == 201 and t2.status_code == 201
    a = t1.json()["data"]["id"]
    b = t2.json()["data"]["id"]

    # Create a match referencing team A
    m = client.post("/matches", json={
        "home_team_id": a,
        "away_team_id": b,
        "home_score": 3,
        "away_score": 1,
        "match_date": "2026-02-10"
    })
    assert m.status_code == 201

    # Attempt to delete referenced team A
    r = client.delete(f"/teams/{a}")
    assert r.status_code == 409