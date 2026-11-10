import pytest
from app import compute

def test_compute_standard_scoring(sample_state):
    """
    Points calculation check:
    Placement table: [15, 12, 10, 8, 6], kill_points: 2
    Game 1:
      Alpha (slot 1): rank 1 (15 pts) + 5 kills * 2 = 15 + 10 = 25 pts
      Bravo (slot 2): rank 2 (12 pts) + 3 kills * 2 = 12 + 6 = 18 pts
      Charlie (slot 3): rank 3 (10 pts) + 0 kills * 2 = 10 pts
    Game 2:
      Alpha (slot 1): rank 2 (12 pts) + 4 kills * 2 = 12 + 8 = 20 pts
      Bravo (slot 2): rank 1 (15 pts) + 6 kills * 2 = 15 + 12 = 27 pts
      Charlie (slot 3): noshow -> 0 pts
    Totals:
      Bravo: 18 + 27 = 45 pts (Place pts: 12 + 15 = 27, Kills: 9)
      Alpha: 25 + 20 = 45 pts (Place pts: 15 + 12 = 27, Kills: 9)
      Charlie: 10 + 0 = 10 pts (Place pts: 10, Kills: 0)
    """
    standings = compute(sample_state)
    assert len(standings) == 3

    # Bravo and Alpha are tied at 45 pts. Tiebreaker in compute sorts by -total, then slot.
    # Alpha has slot 1, Bravo has slot 2, so Alpha is rank 1, Bravo rank 2.
    assert standings[0]["name"] == "Alpha Squad"
    assert standings[0]["total"] == 45
    assert standings[0]["place_pts"] == 27
    assert standings[0]["kills"] == 9
    assert standings[0]["rank"] == 1

    assert standings[1]["name"] == "Bravo Team"
    assert standings[1]["total"] == 45
    assert standings[1]["place_pts"] == 27
    assert standings[1]["kills"] == 9
    assert standings[1]["rank"] == 2

    assert standings[2]["name"] == "Charlie Crew"
    assert standings[2]["total"] == 10
    assert standings[2]["rank"] == 3


def test_compute_noshow_and_dq():
    state = {
        "games": 1,
        "placement_points": [10, 6, 4],
        "kill_points": 1,
        "teams": [
            {"name": "Team Normal", "logo": ""},
            {"name": "Team NoShow", "logo": ""},
            {"name": "Team DQ", "logo": ""},
        ],
        "results": [
            [
                {"rank": 1, "kills": 5, "noshow": False, "dq": False},
                {"rank": 2, "kills": 4, "noshow": True, "dq": False},
                {"rank": 3, "kills": 3, "noshow": False, "dq": True},
            ]
        ],
    }
    standings = compute(state)
    by_name = {s["name"]: s for s in standings}

    # Normal scores 10 + 5 = 15
    assert by_name["Team Normal"]["total"] == 15
    assert by_name["Team Normal"]["place_pts"] == 10
    assert by_name["Team Normal"]["kills"] == 5

    # NoShow scores 0 despite rank and kills
    assert by_name["Team NoShow"]["total"] == 0
    assert by_name["Team NoShow"]["place_pts"] == 0
    assert by_name["Team NoShow"]["kills"] == 0
    assert by_name["Team NoShow"]["games"][0]["noshow"] is True

    # DQ scores 0 despite rank and kills
    assert by_name["Team DQ"]["total"] == 0
    assert by_name["Team DQ"]["place_pts"] == 0
    assert by_name["Team DQ"]["kills"] == 0
    assert by_name["Team DQ"]["games"][0]["dq"] is True


def test_compute_skips_empty_team_names():
    state = {
        "games": 1,
        "placement_points": [10],
        "kill_points": 1,
        "teams": [
            {"name": "   ", "logo": ""},
            {"name": "Real Team", "logo": ""},
            {"name": "", "logo": ""},
        ],
        "results": [
            [
                {"rank": 1, "kills": 1, "noshow": False},
                {"rank": 1, "kills": 2, "noshow": False},
                {"rank": 1, "kills": 3, "noshow": False},
            ]
        ],
    }
    standings = compute(state)
    assert len(standings) == 1
    assert standings[0]["name"] == "Real Team"
    assert standings[0]["slot"] == 2
    assert standings[0]["total"] == 12


def test_compute_rank_outside_placement_points_table():
    state = {
        "games": 1,
        "placement_points": [15, 12, 10],  # only top 3 get placement points
        "kill_points": 2,
        "teams": [
            {"name": "Team 4th", "logo": ""},
        ],
        "results": [
            [
                {"rank": 4, "kills": 3, "noshow": False},
            ]
        ],
    }
    standings = compute(state)
    assert len(standings) == 1
    # rank 4 is > len(placement_points), so place_pts = 0; kills = 3 * 2 = 6
    assert standings[0]["place_pts"] == 0
    assert standings[0]["kills"] == 3
    assert standings[0]["total"] == 6
