"""Turn parsed maps into season totals: players, heroes, ratings and teammates."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from .config import ROLES, Roster
from .parse import STAT_KEYS, MapResult
from .ratings import RatingBook, rate_maps

PER10_KEYS = ["eliminations", "final_blows", "deaths", "hero_damage", "healing", "damage_blocked"]


def slugify(name: str) -> str:
    """URL-safe page name that keeps non-Latin names distinct."""
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
    if not slug or slug != re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"):
        slug = (slug + "-" if slug else "p-") + "".join(f"{ord(c):x}" for c in name)[:16]
    return slug


@dataclass
class Appearance:
    map: MapResult
    team: int
    role: str | None
    hero: str
    totals: dict[str, float]

    @property
    def result(self) -> str:
        if not self.map.complete:
            return "unfinished"
        w = self.map.winner
        return "draw" if w == 0 else ("win" if w == self.team else "loss")


@dataclass
class PlayerSeason:
    name: str
    slug: str
    ingame_names: set[str] = field(default_factory=set)
    appearances: list[Appearance] = field(default_factory=list)
    heroes: dict[str, dict] = field(default_factory=dict)
    teammates: dict[str, list[int]] = field(default_factory=dict)  # name -> [maps, wins]

    @property
    def rated(self) -> list[Appearance]:
        return [a for a in self.appearances if a.map.complete]

    def record(self, role: str | None = None) -> tuple[int, int, int]:
        apps = [a for a in self.rated if role is None or a.role == role]
        return (sum(a.result == "win" for a in apps), sum(a.result == "loss" for a in apps),
                sum(a.result == "draw" for a in apps))

    def total(self, key: str, role: str | None = None) -> float:
        return sum(a.totals[key] for a in self.appearances if role is None or a.role == role)

    def per10(self, key: str, role: str | None = None) -> float:
        minutes = self.total("time_played", role) / 60
        return self.total(key, role) / minutes * 10 if minutes else 0.0

    def role_maps(self) -> dict[str, int]:
        out = {r: 0 for r in ROLES}
        for a in self.appearances:
            if a.role:
                out[a.role] += 1
        return out

    @property
    def main_role(self) -> str | None:
        counts = self.role_maps()
        return max(counts, key=counts.get) if any(counts.values()) else None

    def top_heroes(self, n: int = 3) -> list[str]:
        return sorted(self.heroes, key=lambda h: -self.heroes[h]["time"])[:n]


@dataclass
class Season:
    maps: list[MapResult]
    players: dict[str, PlayerSeason]
    heroes: dict[str, dict]
    hero_roles: dict[str, str]
    book: RatingBook
    unknown_heroes: set[str]
    roster: Roster = field(default_factory=Roster)

    @property
    def rated_maps(self) -> list[MapResult]:
        return [m for m in self.maps if m.complete]


def build_season(maps: list[MapResult], roster: Roster, hero_roles: dict[str, str]) -> Season:
    unknown: set[str] = set()
    players: dict[str, PlayerSeason] = {}
    heroes: dict[str, dict] = defaultdict(lambda: {"time": 0.0, "maps": 0, "wins": 0, "rated": 0})
    slugs: set[str] = set()

    for m in maps:
        for p in m.players:
            ingame = p.name
            p.name = roster.resolve(p.name)
            ps = players.get(p.name)
            if ps is None:
                slug = slugify(p.name)
                while slug in slugs:
                    slug += "-x"
                slugs.add(slug)
                ps = players[p.name] = PlayerSeason(p.name, slug)
            ps.ingame_names.add(ingame)
            main = p.main_hero
            role = hero_roles.get(main)
            for hero, s in p.heroes.items():
                if hero not in hero_roles:
                    unknown.add(hero)
            totals = {k: p.total(k) for k in STAT_KEYS}
            app = Appearance(m, p.team, role, main, totals)
            ps.appearances.append(app)
            for hero, s in p.heroes.items():
                h = ps.heroes.setdefault(hero, {"time": 0.0, "maps": 0, "wins": 0, "rated": 0,
                                                **{k: 0.0 for k in STAT_KEYS}})
                h["time"] += s["time_played"]
                h["maps"] += 1
                for k in STAT_KEYS:
                    h[k] += s[k]
                g = heroes[hero]
                g["time"] += s["time_played"]
                if hero == main:
                    g["maps"] += 1
                if m.complete and hero == main:
                    g["rated"] += 1
                    g["wins"] += app.result == "win"
                if m.complete:
                    h["rated"] += 1
                    h["wins"] += app.result == "win"
        if m.complete:
            for team in (1, 2):
                names = [p.name for p in m.team(team)]
                for a in names:
                    for b in names:
                        if a != b:
                            rec = players[a].teammates.setdefault(b, [0, 0])
                            rec[0] += 1
                            rec[1] += m.winner == team

    def lineup(m: MapResult, team: int):
        return [(p.name, hero_roles.get(p.main_hero)) for p in m.team(team)]

    book = rate_maps((m.id, m.winner, lineup(m, 1), lineup(m, 2)) for m in maps if m.complete)
    return Season(maps, players, dict(heroes), hero_roles, book, unknown, roster)
