"""Turn stored Valorant games into season totals: players, agents, ratings and teammates."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import AGENT_CLASSES, AgentClasses, Roster, normalise_riot
from .ratings import RatingBook, rate_maps
from .stats import slugify
from .valorant import ValMatch, ValPlayer

TOTAL_KEYS = ("rounds", "score", "kills", "deaths", "assists", "damage", "damage_rounds",
              "headshots", "shots", "first_bloods", "fb_rounds")


def _blank() -> dict:
    return {k: 0 for k in TOTAL_KEYS}


def add_line(tot: dict, p: ValPlayer, rounds: int) -> None:
    tot["rounds"] += rounds
    tot["score"] += p.score
    tot["kills"] += p.kills
    tot["deaths"] += p.deaths
    tot["assists"] += p.assists
    if p.damage is not None:
        tot["damage"] += p.damage
        tot["damage_rounds"] += rounds
    if p.headshots is not None:
        tot["headshots"] += p.headshots
        tot["shots"] += p.headshots + (p.bodyshots or 0) + (p.legshots or 0)
    if p.first_bloods is not None:
        tot["first_bloods"] += p.first_bloods
        tot["fb_rounds"] += rounds


def rates(tot: dict) -> dict:
    """Per-round and ratio figures; None where the games had no data for it."""
    r = tot["rounds"]
    return {
        "acs": tot["score"] / r if r else None,
        "kd": tot["kills"] / tot["deaths"] if tot["deaths"] else (float(tot["kills"]) if r else None),
        "kpr": tot["kills"] / r if r else None,
        "adr": tot["damage"] / tot["damage_rounds"] if tot["damage_rounds"] else None,
        "hs": tot["headshots"] / tot["shots"] if tot["shots"] else None,
        "fb": tot["first_bloods"] / tot["fb_rounds"] * 24 if tot["fb_rounds"] else None,  # per 24 rounds
    }


@dataclass
class ValAppearance:
    map: ValMatch
    line: ValPlayer

    @property
    def team(self) -> int:
        return self.line.team

    @property
    def result(self) -> str:
        w = self.map.winner
        return "draw" if w == 0 else ("win" if w == self.team else "loss")


@dataclass
class ValPlayerSeason:
    name: str
    slug: str
    riot_ids: set[str] = field(default_factory=set)
    appearances: list[ValAppearance] = field(default_factory=list)
    totals: dict = field(default_factory=_blank)
    agents: dict[str, dict] = field(default_factory=dict)  # agent -> totals + maps, wins
    teammates: dict[str, list[int]] = field(default_factory=dict)  # name -> [maps, wins]

    def record(self) -> tuple[int, int, int]:
        res = [a.result for a in self.appearances]
        return res.count("win"), res.count("loss"), res.count("draw")

    @property
    def rates(self) -> dict:
        return rates(self.totals)

    def top_agents(self, n: int = 3) -> list[str]:
        return sorted(self.agents, key=lambda a: (-self.agents[a]["maps"], -self.agents[a]["rounds"]))[:n]

    def class_maps(self, classes: AgentClasses) -> dict[str, int]:
        out = {c: 0 for c in AGENT_CLASSES}
        for a in self.appearances:
            c = classes.get(a.line.agent)
            if c:
                out[c] += 1
        return out

    def main_class(self, classes: AgentClasses) -> str | None:
        counts = self.class_maps(classes)
        return max(counts, key=counts.get) if any(counts.values()) else None


@dataclass
class ValSeason:
    maps: list[ValMatch]
    players: dict[str, ValPlayerSeason]
    agents: dict[str, dict]
    classes: AgentClasses
    book: RatingBook
    unknown_agents: set[str]
    roster: Roster = field(default_factory=Roster)

    @property
    def rated_maps(self) -> list[ValMatch]:
        return self.maps


def _names(maps: list[ValMatch], roster: Roster) -> dict[str, str]:
    """Club name for every player id.

    Roster members are matched by Riot ID; once one of their games is seen,
    their account id follows them through Riot name changes. Anyone else is
    shown under their latest Riot name, with the tag added only when two
    different people share a name.
    """
    by_id: dict[str, str] = {}
    latest: dict[str, ValPlayer] = {}
    for m in maps:
        for p in m.players:
            club = roster.resolve_riot(p.riot_name, p.tag)
            if club:
                by_id.setdefault(p.puuid, club)
            latest[p.puuid] = p
    # Typed-in scoreboards have no account id: link them to an API player with the same Riot ID.
    riot_to_id: dict[str, str] = {}
    for pid, p in latest.items():
        if not pid.startswith("manual:"):
            riot_to_id[normalise_riot(p.riot_id)] = pid
            riot_to_id.setdefault(normalise_riot(p.riot_name), pid)

    def canonical(pid: str) -> str:
        if not pid.startswith("manual:"):
            return pid
        p = latest[pid]
        return riot_to_id.get(normalise_riot(p.riot_id)) or riot_to_id.get(normalise_riot(p.riot_name)) or pid

    shown: dict[str, str] = {}  # canonical id -> name
    taken: dict[str, str] = {}  # name -> canonical id
    for pid in latest:
        cid = canonical(pid)
        if cid in shown:
            continue
        p = latest[cid]
        name = by_id.get(cid) or by_id.get(pid) or roster.resolve_riot(p.riot_name, p.tag)
        if not name:
            name = p.riot_name
            if taken.get(name, cid) != cid or name in roster.names:
                name = p.riot_id
        shown[cid] = name
        taken.setdefault(name, cid)
    return {pid: shown[canonical(pid)] for pid in latest}


def build_val_season(maps: list[ValMatch], roster: Roster, classes: AgentClasses) -> ValSeason:
    names = _names(maps, roster)
    players: dict[str, ValPlayerSeason] = {}
    agents: dict[str, dict] = defaultdict(lambda: {**_blank(), "maps": 0, "wins": 0})
    unknown: set[str] = set()
    slugs: set[str] = set()
    for m in maps:
        for p in m.players:
            p.name = names.get(p.puuid, p.riot_name)
            ps = players.get(p.name)
            if ps is None:
                slug = slugify(p.name)
                while slug in slugs:
                    slug += "-x"
                slugs.add(slug)
                ps = players[p.name] = ValPlayerSeason(p.name, slug)
            ps.riot_ids.add(p.riot_id)
            app = ValAppearance(m, p)
            ps.appearances.append(app)
            add_line(ps.totals, p, m.rounds)
            a = ps.agents.setdefault(p.agent, {**_blank(), "maps": 0, "wins": 0})
            add_line(a, p, m.rounds)
            a["maps"] += 1
            a["wins"] += app.result == "win"
            g = agents[p.agent]
            add_line(g, p, m.rounds)
            g["maps"] += 1
            g["wins"] += app.result == "win"
            if p.agent not in classes:
                unknown.add(p.agent)
        for team in (1, 2):
            ns = [p.name for p in m.team(team)]
            for a in ns:
                for b in ns:
                    if a != b:
                        rec = players[a].teammates.setdefault(b, [0, 0])
                        rec[0] += 1
                        rec[1] += m.winner == team

    book = rate_maps((m.id, m.winner, [(p.name, None) for p in m.team(1)], [(p.name, None) for p in m.team(2)])
                     for m in maps)
    return ValSeason(maps, players, dict(agents), classes, book, unknown, roster)
