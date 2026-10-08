import itertools
import math

import pytest
from openskill.models import PlackettLuce

from overtime.balance import PREFERENCE_COST, Signup, balance, parse_roles
from overtime.ratings import BETA, MU, SIGMA, RatingBook, Rating, rate_maps, win_probability


def test_win_probability_matches_openskill():
    model = PlackettLuce(mu=MU, sigma=SIGMA, beta=BETA)
    a = [(30, 3), (25, 5), (22, 8), (27, 2), (24, 4)]
    b = [(26, 4), (28, 2), (20, 7), (25, 5), (23, 3)]
    expected = model.predict_win([[model.rating(mu=m, sigma=s) for m, s in t] for t in (a, b)])[0]
    assert win_probability(a, b) == pytest.approx(expected, abs=1e-9)


def test_winners_go_up_and_losers_down():
    team1 = [(f"a{i}", "damage") for i in range(5)]
    team2 = [(f"b{i}", "damage") for i in range(5)]
    book = rate_maps([("m1", 1, team1, team2)])
    assert book.get("a0").mu > MU > book.get("b0").mu
    assert book.get("a0", "damage").maps == 1
    assert book.deltas["m1"]["a0"] > 0 > book.deltas["m1"]["b0"]
    assert book.predictions["m1"] == pytest.approx(0.5)


def test_unknown_role_skips_role_ratings_only():
    team1 = [("a", None)] + [(f"a{i}", "tank") for i in range(4)]
    team2 = [(f"b{i}", "tank") for i in range(5)]
    book = rate_maps([("m1", 2, team1, team2)])
    assert "a" in book.overall and not book.by_role


def test_parse_roles():
    assert parse_roles("dps > support") == ["damage", "support"]
    assert parse_roles("any") == ["tank", "damage", "support"]
    with pytest.raises(ValueError):
        parse_roles("sniper")


def brute_force(signups, book):
    """Independent check: try every assignment of the ten slots."""
    pref = {s.player: s.roles for s in signups}
    slots = ["tank", "damage", "damage", "support", "support"] * 2
    best = math.inf
    for perm in itertools.permutations([s.player for s in signups]):
        if any(r not in pref[p] for p, r in zip(perm, slots)):
            continue
        mu = lambda p, r: book.by_role.get((p, r), book.get(p)).mu
        gap = sum(mu(p, r) for p, r in zip(perm[:5], slots[:5])) - sum(
            mu(p, r) for p, r in zip(perm[5:], slots[5:]))
        off = sum(pref[p].index(r) for p, r in zip(perm, slots))
        best = min(best, abs(gap) + PREFERENCE_COST * off)
    return best


def test_balancer_finds_the_true_optimum():
    book = RatingBook()
    names = [f"p{i}" for i in range(10)]
    for i, n in enumerate(names):
        for j, role in enumerate(("tank", "damage", "support")):
            book.by_role[(n, role)] = Rating(mu=20 + (i * 7 + j * 3) % 11, sigma=3)
    roles = [["tank"], ["tank", "damage"], ["damage"], ["damage", "support"], ["damage"],
             ["support"], ["support", "tank"], ["damage", "support", "tank"], ["support"], ["support", "damage"]]
    signups = [Signup(n, r) for n, r in zip(names, roles)]
    result = balance(signups, book, top=1)[0]
    assert result.score == pytest.approx(brute_force(signups, book))
    for team in (result.team1, result.team2):
        assert [len(team[r]) for r in ("tank", "damage", "support")] == [1, 2, 2]


def test_balancer_rejects_impossible_lobbies():
    with pytest.raises(ValueError, match="exactly 10"):
        balance([Signup("a", ["tank"])], RatingBook())
    with pytest.raises(ValueError, match="no legal teams"):
        balance([Signup(f"p{i}", ["damage"]) for i in range(10)], RatingBook())


def test_hero_role_changes_apply_by_date(tmp_path):
    from datetime import datetime

    from overtime.config import load_heroes

    (tmp_path / "heroes.yaml").write_text(
        "damage: [Tracer]\nsupport: [Sombra]\n"
        "role_changes:\n  - hero: Sombra\n    was: damage\n    from: 2026-10-06\n", encoding="utf-8")
    roles = load_heroes(tmp_path)
    assert roles.get("Sombra") == "support"
    assert roles.on("Sombra", datetime(2026, 10, 5, 20, 0)) == "damage"
    assert roles.on("Sombra", datetime(2026, 10, 6, 19, 0)) == "support"
    assert roles.on("Tracer", datetime(2020, 1, 1)) == "damage"
