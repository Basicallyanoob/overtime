"""Render the Valorant half of the site into site/valorant/."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment

from .config import AGENT_CLASSES, Club, ValorantSettings
from .site import UPSET, _night, _record_text, rating_chart
from .val_stats import ValPlayerSeason, ValSeason, rates

CLASS_LABEL = {"duelist": "Duelist", "initiator": "Initiator", "controller": "Controller", "sentinel": "Sentinel"}
SECTIONS = {"val_index.html": "index", "val_matches.html": "matches", "val_match.html": "matches",
            "val_agents.html": "heroes", "val_builder.html": "builder", "val_about.html": "about"}


def _map(season: ValSeason, map_id: str):
    return season.__dict__.setdefault("_index", {m.id: m for m in season.maps})[map_id]


def leaderboard(season: ValSeason, club: Club) -> dict:
    book = season.book
    nights = sorted({_night(m) for m in season.maps})
    last_night = nights[-1] if nights else None
    rows, unranked = [], []
    for p in season.players.values():
        if p.name not in book.overall:
            continue
        w, l, d = p.record()
        games = w + l + d
        change = None
        hist = book.history.get(p.name, [])
        tonight = [v for mid, v in hist if _night(_map(season, mid)) == last_night]
        earlier = [v for mid, v in hist if _night(_map(season, mid)) != last_night]
        if tonight:
            change = tonight[-1] - (earlier[-1] if earlier else 1000)
        cls = p.main_class(season.classes)
        row = {"player": p, "rating": book.overall[p.name].value, "maps": games, "record": _record_text(w, l, d),
               "winrate": w / games if games else 0, "change": change, "r": p.rates,
               "agents": p.top_agents(3), "cls": CLASS_LABEL.get(cls, "")}
        (rows if games >= club.min_maps else unranked).append(row)
    rows.sort(key=lambda x: (-x["rating"], x["player"].name.lower()))
    unranked.sort(key=lambda x: (-x["maps"], x["player"].name.lower()))
    return {"rows": rows, "unranked": unranked}


def match_view(season: ValSeason, m) -> dict:
    deltas = season.book.deltas.get(m.id, {})
    pred = season.book.predictions.get(m.id)
    teams = []
    for t in (1, 2):
        rows = []
        for p in m.team(t):
            tot = {"rounds": m.rounds, "score": p.score, "kills": p.kills, "deaths": p.deaths, "assists": p.assists,
                   "damage": p.damage or 0, "damage_rounds": m.rounds if p.damage is not None else 0,
                   "headshots": p.headshots or 0,
                   "shots": (p.headshots or 0) + (p.bodyshots or 0) + (p.legshots or 0) if p.headshots is not None else 0,
                   "first_bloods": p.first_bloods or 0, "fb_rounds": m.rounds if p.first_bloods is not None else 0}
            rows.append({"player": season.players[p.name], "line": p, "r": rates(tot),
                         "cls": CLASS_LABEL.get(season.classes.get(p.agent), ""), "delta": deltas.get(p.name),
                         "riot": p.riot_id})
        rows.sort(key=lambda r: -(r["r"]["acs"] or 0))
        teams.append({"no": t, "name": m.team_names[t - 1], "rows": rows, "won": m.winner == t})
    upset = pred is not None and m.winner and (pred if m.winner == 1 else 1 - pred) < UPSET
    return {"map": m, "teams": teams, "prediction": pred, "upset": upset}


def player_view(season: ValSeason, p: ValPlayerSeason) -> dict:
    book = season.book
    hist = book.history.get(p.name, [])
    chart = rating_chart([(mid, v, f"{_map(season, mid).played_at.day} {_map(season, mid).played_at:%b}")
                          for mid, v in hist])
    agents = []
    for agent, a in sorted(p.agents.items(), key=lambda kv: (-kv[1]["maps"], -kv[1]["rounds"])):
        agents.append({"agent": agent, "cls": CLASS_LABEL.get(season.classes.get(agent), "Unknown"),
                       "maps": a["maps"], "winrate": a["wins"] / a["maps"] if a["maps"] else None, "r": rates(a)})
    counts = p.class_maps(season.classes)
    total = sum(counts.values()) or 1
    classes = [{"cls": CLASS_LABEL[c], "maps": counts[c], "share": counts[c] / total}
               for c in AGENT_CLASSES if counts[c]]
    mates = [{"player": season.players[n], "games": g, "wins": w, "winrate": w / g}
             for n, (g, w) in p.teammates.items() if g >= 3]
    mates.sort(key=lambda x: (-x["winrate"], -x["games"]))
    recent = [{"a": a, "delta": book.deltas.get(a.map.id, {}).get(p.name),
               "acs": a.line.score / a.map.rounds if a.map.rounds else 0} for a in reversed(p.appearances)]
    w, l, d = p.record()
    return {"p": p, "rating": book.get(p.name).value if p.name in book.overall else None,
            "record": _record_text(w, l, d), "maps": w + l + d, "winrate": w / (w + l + d) if w + l + d else 0,
            "chart": chart, "agents": agents, "classes": classes, "best_mates": mates[:3], "recent": recent,
            "r": p.rates, "others": sorted(i for i in p.riot_ids if i.partition("#")[0] != p.name)}


def agent_view(season: ValSeason) -> dict:
    total = sum(a["rounds"] for a in season.agents.values()) or 1
    by_class = defaultdict(list)
    for agent, a in season.agents.items():
        top = max(season.players.values(), key=lambda p: p.agents.get(agent, {}).get("rounds", 0))
        by_class[season.classes.get(agent, "unknown")].append({
            "agent": agent, "share": a["rounds"] / total, "maps": a["maps"],
            "winrate": a["wins"] / a["maps"] if a["maps"] else None, "r": rates(a), "top": top})
    for rows in by_class.values():
        rows.sort(key=lambda r: -r["share"])
    return {c: by_class[c] for c in (*AGENT_CLASSES, "unknown") if by_class.get(c)}


def builder_data(season: ValSeason) -> list[dict]:
    """Everyone who has played Valorant, plus roster members with a Riot ID who have not yet."""
    book, roster = season.book, season.roster
    names = set(season.players) | {n for n in roster.riot.values()}
    out = []
    for name in sorted(names, key=str.casefold):
        p = season.players.get(name)
        o = book.get(name)
        cls = p.main_class(season.classes) if p else None
        out.append({"name": name, "rating": o.value if name in book.overall else None,
                    "overall": [round(o.mu, 4), round(o.sigma, 4)],
                    "cls": cls, "agents": p.top_agents(2) if p else []})
    return out


def render_valorant(env: Environment, out: Path, common: dict, club: Club, season: ValSeason,
                    settings: ValorantSettings, warnings: list[str], ow_slugs: dict[str, str]) -> list[Path]:
    base = out / "valorant"
    (base / "players").mkdir(parents=True)
    (base / "matches").mkdir()
    env.globals["CLASS_LABEL"] = CLASS_LABEL
    nights = defaultdict(list)
    for m in reversed(season.maps):
        nights[m.played_at.date()].append(match_view(season, m))
    hours = sum(m.duration for m in season.maps) / 3600
    ctx = {**common, "game": "valorant", "settings": settings,
           "brand": " ".join(x for x in (club.short_name or club.name, "Valorant") if x),
           "summary": {"maps": len(season.maps), "players": len(season.players), "hours": hours,
                       "nights": len(nights), "rounds": sum(m.rounds for m in season.maps),
                       "manual": sum(m.source == "manual" for m in season.maps)}}
    written = []

    def page(template: str, path: str, depth: int, **extra):
        root = "../" * depth
        html = env.get_template(template).render(**{**ctx, **extra}, root=root, groot=root + "valorant/",
                                                 page=template, section=SECTIONS.get(template))
        target = out / path
        target.write_text(html, encoding="utf-8")
        written.append(target)

    recent = [match_view(season, m) for m in list(reversed(season.maps))[:6]]
    page("val_index.html", "valorant/index.html", 1, board=leaderboard(season, club), recent=recent,
         warnings=warnings, unknown_agents=sorted(season.unknown_agents))
    page("val_matches.html", "valorant/matches/index.html", 2, nights=nights)
    for views in nights.values():
        for v in views:
            page("val_match.html", f"valorant/matches/{v['map'].id}.html", 2, v=v)
    for p in season.players.values():
        page("val_player.html", f"valorant/players/{p.slug}.html", 2, v=player_view(season, p),
             other=f"../../players/{ow_slugs[p.name]}.html" if p.name in ow_slugs else None)
    page("val_agents.html", "valorant/agents.html", 1, classes=agent_view(season))
    page("val_builder.html", "valorant/builder.html", 1,
         data=json.dumps(builder_data(season), ensure_ascii=False).replace("</", "<\\/"))
    page("val_about.html", "valorant/about.html", 1)
    return written
