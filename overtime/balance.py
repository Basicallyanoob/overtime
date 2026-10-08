"""Split ten sign-ups into two 1-2-2 role-queue teams that are as even as possible.

Every legal arrangement is checked (about 100,000 for ten flexible players),
so the result is the true optimum for the scoring rule below, not a heuristic.

Score = skill gap between the teams (sum of role-rating mu)
      + PREFERENCE_COST for each step a player sits below their first-choice role
Lower is better.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .config import ROLES, TEAM_SHAPE
from .ratings import RatingBook, win_probability

PREFERENCE_COST = 1.0  # in mu points, worth 40 points on the displayed rating scale


@dataclass
class Signup:
    player: str
    roles: list[str]  # in order of preference


@dataclass
class Lineup:
    team1: dict[str, list[str]]  # role -> players
    team2: dict[str, list[str]]
    gap: float  # team 1 skill minus team 2 skill, in mu points
    off_preference: int  # total steps below first choice
    win_probability: float  # team 1
    score: float


def parse_roles(text: str) -> list[str]:
    """'support>tank', 'dps, support' or 'any' -> ordered role list."""
    text = text.strip().lower()
    if text in ("", "any", "flex", "fill"):
        return list(ROLES)
    out = []
    for part in text.replace(">", ",").replace("/", ",").replace(";", ",").split(","):
        part = part.strip()
        part = {"dps": "damage", "dmg": "damage", "heals": "support", "supp": "support",
                "healer": "support", "tanks": "tank", "flex": None}.get(part, part)
        if part is None:
            return list(ROLES)
        if part not in ROLES:
            raise ValueError(f"unknown role '{part}' in '{text}'")
        if part not in out:
            out.append(part)
    return out


def balance(signups: list[Signup], book: RatingBook, top: int = 3) -> list[Lineup]:
    if len(signups) != 10:
        raise ValueError(f"need exactly 10 players, got {len(signups)}")
    names = [s.player for s in signups]
    if len(set(names)) != 10:
        raise ValueError("a player is listed twice")
    pref = {s.player: s.roles for s in signups}

    def skill(p, role):
        r = book.by_role.get((p, role))
        return (r.mu, r.sigma) if r else (book.get(p).mu, book.get(p).sigma)

    def can(p, role):
        return role in pref[p]

    results = []
    tanks_pool = [p for p in names if can(p, "tank")]
    for tanks in combinations(tanks_pool, 2):
        rest = [p for p in names if p not in tanks]
        for dps in combinations([p for p in rest if can(p, "damage")], 4):
            sups = [p for p in rest if p not in dps]
            if not all(can(p, "support") for p in sups):
                continue
            # Tank tanks[0] always goes to team 1, which removes mirror duplicates.
            for d1 in combinations(dps, 2):
                for s1 in combinations(sups, 2):
                    t1 = {"tank": [tanks[0]], "damage": list(d1), "support": list(s1)}
                    t2 = {"tank": [tanks[1]],
                          "damage": [p for p in dps if p not in d1],
                          "support": [p for p in sups if p not in s1]}
                    sk1 = [skill(p, r) for r, ps in t1.items() for p in ps]
                    sk2 = [skill(p, r) for r, ps in t2.items() for p in ps]
                    gap = sum(m for m, _ in sk1) - sum(m for m, _ in sk2)
                    off = sum(pref[p].index(r) for t in (t1, t2) for r, ps in t.items() for p in ps)
                    score = abs(gap) + PREFERENCE_COST * off
                    results.append((score, t1, t2, gap, off, sk1, sk2))
    if not results:
        raise ValueError("no legal teams: need 2 players who can tank, 4 damage and 4 support")
    results.sort(key=lambda x: x[0])
    return [Lineup(t1, t2, gap, off, win_probability(sk1, sk2), score)
            for score, t1, t2, gap, off, sk1, sk2 in results[:top]]


assert sum(TEAM_SHAPE.values()) == 5
