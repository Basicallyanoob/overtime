"""Skill ratings from inhouse results.

Each player has an overall rating and one per role, updated map by map with
the Plackett-Luce model from `openskill` (a Bayesian rating like TrueSkill).
A rating is a belief: mu is the estimate, sigma the uncertainty. Pages show mu
on a scale where an average player is 1,000; sigma feeds the win probabilities.
Team results tell the model little about each individual, so sigma shrinks
slowly, and a minimum number of maps keeps lucky newcomers off the ladder.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from openskill.models import PlackettLuce

MU, SIGMA = 25.0, 25.0 / 3
BETA = MU / 6


def display(mu: float) -> int:
    """Map a skill estimate onto a scale where the starting value is 1,000."""
    return round(1000 + 40 * (mu - MU))


def win_probability(team_a: list[tuple[float, float]], team_b: list[tuple[float, float]]) -> float:
    """P(team A beats team B) from (mu, sigma) pairs; matches openskill.predict_win."""
    mu_a, mu_b = sum(m for m, _ in team_a), sum(m for m, _ in team_b)
    var = 2 * BETA**2 + sum(s**2 for _, s in team_a) + sum(s**2 for _, s in team_b)
    return 0.5 * (1 + math.erf((mu_a - mu_b) / math.sqrt(2 * var)))


@dataclass
class Rating:
    mu: float = MU
    sigma: float = SIGMA
    maps: int = 0

    @property
    def value(self) -> int:
        return display(self.mu)


@dataclass
class RatingBook:
    overall: dict[str, Rating] = field(default_factory=dict)
    by_role: dict[tuple[str, str], Rating] = field(default_factory=dict)
    # player -> list of (map id, overall display rating after that map)
    history: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    # map id -> {player: overall display change}
    deltas: dict[str, dict[str, int]] = field(default_factory=dict)
    # map id -> probability team 1 wins, computed before the map was played
    predictions: dict[str, float] = field(default_factory=dict)

    def get(self, player: str, role: str | None = None) -> Rating:
        if role is None:
            return self.overall.get(player, Rating())
        return self.by_role.get((player, role), Rating())


def rate_maps(lineups) -> RatingBook:
    """Rate maps in order.

    `lineups` yields (map_id, winner, team1, team2), where winner is 1, 2 or 0
    for a draw and each team is a list of (player, role or None).
    """
    model = PlackettLuce(mu=MU, sigma=SIGMA, beta=BETA)
    book = RatingBook()

    def update(table, key_fn, team1, team2, winner):
        teams = [[table.get(key_fn(p, r), Rating()) for p, r in t] for t in (team1, team2)]
        ranks = [1, 1] if winner == 0 else ([1, 2] if winner == 1 else [2, 1])
        rated = model.rate(
            [[model.rating(mu=x.mu, sigma=x.sigma) for x in t] for t in teams], ranks=ranks
        )
        for t, new_t, old_t in zip((team1, team2), rated, teams):
            for (p, r), new, old in zip(t, new_t, old_t):
                table[key_fn(p, r)] = Rating(new.mu, new.sigma, old.maps + 1)

    for map_id, winner, team1, team2 in lineups:
        before = {p: book.get(p).value for p, _ in team1 + team2}
        book.predictions[map_id] = win_probability(
            [(book.get(p).mu, book.get(p).sigma) for p, _ in team1],
            [(book.get(p).mu, book.get(p).sigma) for p, _ in team2],
        )
        update(book.overall, lambda p, r: p, team1, team2, winner)
        # Role ratings only when every player's role is known.
        if all(r for _, r in team1 + team2):
            update(book.by_role, lambda p, r: (p, r), team1, team2, winner)
        book.deltas[map_id] = {}
        for p, _ in team1 + team2:
            after = book.get(p).value
            book.deltas[map_id][p] = after - before[p]
            book.history.setdefault(p, []).append((map_id, after))
    return book
