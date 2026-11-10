import pytest
from app import analytics_for

def test_analytics_team_performance(sample_state):
    data = analytics_for(sample_state)
    teams = data["teams"]
    assert len(teams) == 3

    # Alpha Squad:
    # Game 1: rank 1 (win, top3)
    # Game 2: rank 2 (top3)
    # Wins: 1, Top 3: 2, avg placement: (1 + 2) / 2 = 1.5, games_played: 2
    alpha = next(t for t in teams if t["name"] == "Alpha Squad")
    assert alpha["wins"] == 1
    assert alpha["top3"] == 2
    assert alpha["average_placement"] == 1.5
    assert alpha["games_played"] == 2
    assert alpha["total"] == 45
    assert alpha["kills"] == 9

    # Bravo Team:
    # Game 1: rank 2 (top3)
    # Game 2: rank 1 (win, top3)
    # Wins: 1, Top 3: 2, avg placement: (2 + 1) / 2 = 1.5, games_played: 2
    bravo = next(t for t in teams if t["name"] == "Bravo Team")
    assert bravo["wins"] == 1
    assert bravo["top3"] == 2
    assert bravo["average_placement"] == 1.5
    assert bravo["games_played"] == 2
    assert bravo["total"] == 45
    assert bravo["kills"] == 9

    # Charlie Crew:
    # Game 1: rank 3 (top3)
    # Game 2: noshow (ignored in played ranks)
    # Wins: 0, Top 3: 1, avg placement: 3.0, games_played: 1
    charlie = next(t for t in teams if t["name"] == "Charlie Crew")
    assert charlie["wins"] == 0
    assert charlie["top3"] == 1
    assert charlie["average_placement"] == 3.0
    assert charlie["games_played"] == 1
    assert charlie["total"] == 10
    assert charlie["kills"] == 0


def test_analytics_player_mvp(sample_state):
    data = analytics_for(sample_state)
    players = data["players"]
    assert len(players) > 0

    # Let's inspect Alpha Squad's Alice:
    # Game 1: pk = [3, 2, 0, 0] -> Alice = 3 kills
    # Game 2: pk = [2, 1, 1, 0] -> Alice = 2 kills
    # Total kills: 5, games: 2, best game: 3, avg kills: 2.5
    alice = next(p for p in players if p["name"] == "Alice")
    assert alice["team"] == "Alpha Squad"
    assert alice["kills"] == 5
    assert alice["best_game"] == 3
    assert alice["games_played"] == 2
    assert alice["average_kills"] == 2.5

    # Bravo Team's Eve:
    # Game 1: pk = [1, 1, 1, 0] -> Eve = 1 kill
    # Game 2: pk = [3, 2, 1, 0] -> Eve = 3 kills
    # Total kills: 4, best game: 3
    eve = next(p for p in players if p["name"] == "Eve")
    assert eve["team"] == "Bravo Team"
    assert eve["kills"] == 4
    assert eve["best_game"] == 3

    # MVP list sorted by kills descending
    top_mvp = players[0]
    assert top_mvp["kills"] == max(p["kills"] for p in players)


def test_analytics_no_results():
    empty_state = {
        "title": "Empty Scrim",
        "date": "2026-11-10",
        "theme": "#7b2fe0",
        "slots": 2,
        "games": 1,
        "placement_points": [10, 5],
        "kill_points": 1,
        "teams": [
            {"name": "Team A", "players": []},
            {"name": "Team B", "players": []},
        ],
        "results": [
            [
                {"rank": None, "kills": 0, "noshow": False, "dq": False, "pk": [None]},
                {"rank": None, "kills": 0, "noshow": False, "dq": False, "pk": [None]},
            ]
        ],
    }
    data = analytics_for(empty_state)
    assert len(data["teams"]) == 2
    for t in data["teams"]:
        assert t["wins"] == 0
        assert t["top3"] == 0
        assert t["average_placement"] is None
        assert t["games_played"] == 0
    assert data["players"] == []
