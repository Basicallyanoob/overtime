"""Render a season into a static website (plain HTML, CSS and a little JS)."""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from .config import ROLES, Club
from .stats import PER10_KEYS, PlayerSeason, Season

ROLE_LABEL = {"tank": "Tank", "damage": "Damage", "support": "Support"}
UPSET = 0.35  # a win the ratings gave less than a 35% chance


def _env() -> Environment:
    env = Environment(loader=PackageLoader("overtime", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["num"] = lambda v, d=0: f"{v:,.{d}f}"
    env.filters["pct"] = lambda v: f"{v * 100:.0f}%"
    env.filters["signed"] = lambda v: f"+{v}" if v > 0 else (f"−{abs(v)}" if v < 0 else "±0")
    env.filters["mmss"] = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
    env.filters["day"] = lambda d: f"{d:%a} {d.day} {d:%b %Y}"
    env.filters["clock"] = lambda d: f"{d:%H:%M}"
    env.globals["ROLE_LABEL"] = ROLE_LABEL
    return env


def _record_text(w, l, d):
    return f"{w}–{l}" + (f"–{d}" if d else "")


def _night(m) -> str:
    return m.played_at.date().isoformat()


def leaderboard(season: Season, club: Club, role: str | None) -> dict:
    book = season.book
    nights = sorted({_night(m) for m in season.rated_maps})
    last_night = nights[-1] if nights else None
    rows, unranked = [], []
    for p in season.players.values():
        key = (p.name, role) if role else p.name
        table = book.by_role if role else book.overall
        if key not in table:
            continue
        r = table[key]
        w, l, d = p.record(role)
        games = w + l + d
        # Rating change over the latest club night (overall board only).
        change = None
        if role is None and last_night:
            hist = book.history.get(p.name, [])
            tonight = [v for mid, v in hist if _night(season_map(season, mid)) == last_night]
            earlier = [v for mid, v in hist if _night(season_map(season, mid)) != last_night]
            if tonight:
                change = tonight[-1] - (earlier[-1] if earlier else 1000)
        row = {
            "player": p, "rating": r.value, "maps": games, "record": _record_text(w, l, d),
            "winrate": w / games if games else 0, "change": change,
            "per10": {k: p.per10(k, role) for k in PER10_KEYS},
            "heroes": [h for h in p.top_heroes(6) if role is None or season.hero_roles.get(h) == role][:3],
        }
        (rows if games >= club.min_maps else unranked).append(row)
    rows.sort(key=lambda x: (-x["rating"], x["player"].name.lower()))
    unranked.sort(key=lambda x: (-x["maps"], x["player"].name.lower()))
    return {"role": role, "label": ROLE_LABEL.get(role, "Overall"), "rows": rows, "unranked": unranked}


_MAP_INDEX: dict[int, dict] = {}


def season_map(season: Season, map_id: str):
    idx = _MAP_INDEX.setdefault(id(season), {m.id: m for m in season.maps})
    return idx[map_id]


def match_view(season: Season, m) -> dict:
    deltas = season.book.deltas.get(m.id, {})
    pred = season.book.predictions.get(m.id)
    teams = []
    for t in (1, 2):
        rows = []
        for p in m.team(t):
            heroes = sorted(p.heroes, key=lambda h: -p.heroes[h]["time_played"])
            rows.append({
                "player": season.players[p.name], "ingame": p.name,
                "heroes": heroes, "role": season.hero_roles.on(p.main_hero, m.played_at),
                "stats": {k: p.total(k) for k in ("eliminations", "final_blows", "deaths",
                                                    "hero_damage", "healing", "damage_blocked")},
                "delta": deltas.get(p.name),
            })
        order = {r: i for i, r in enumerate(ROLES)}
        rows.sort(key=lambda r: (order.get(r["role"], 9), -r["stats"]["eliminations"]))
        teams.append({"no": t, "name": m.team_names[t - 1], "rows": rows,
                      "won": m.complete and m.winner == t, "first_kills": m.first_kills.get(t, 0)})
    upset = pred is not None and m.winner and (pred if m.winner == 1 else 1 - pred) < UPSET
    return {"map": m, "teams": teams, "prediction": pred, "upset": upset}


def rating_chart(points: list[tuple[str, int, str]], width=640, height=200) -> dict:
    """Coordinates for an SVG line of rating after each map."""
    if not points:
        return {}
    pad_l, pad_r, pad_t, pad_b = 44, 16, 14, 26
    values = [v for _, v, _ in points] + [1000]
    lo, hi = min(values), max(values)
    step = 50 if hi - lo <= 300 else 100
    lo, hi = (lo // step) * step, -(-hi // step) * step
    if hi == lo:
        hi += step
    n = len(points)
    x = lambda i: pad_l + (width - pad_l - pad_r) * (i / (n - 1) if n > 1 else 0.5)
    y = lambda v: pad_t + (height - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))
    pts = [{"x": round(x(i), 1), "y": round(y(v), 1), "v": v, "label": label, "id": mid}
           for i, (mid, v, label) in enumerate(points)]
    grid = [{"y": round(y(v), 1), "v": v} for v in range(lo, hi + 1, step)]
    return {"w": width, "h": height, "pts": pts, "grid": grid,
            "line": " ".join(f"{p['x']},{p['y']}" for p in pts),
            "base_y": round(y(1000), 1), "x0": pad_l, "x1": width - pad_r,
            "first": points[0][2], "last": points[-1][2]}


def player_view(season: Season, p: PlayerSeason, club: Club) -> dict:
    book = season.book
    hist = book.history.get(p.name, [])
    chart = rating_chart([(mid, v, f"{season_map(season, mid).played_at.day} {season_map(season, mid).played_at:%b}") for mid, v in hist])
    roles = []
    for role in ROLES:
        if (p.name, role) in book.by_role:
            r = book.by_role[(p.name, role)]
            w, l, d = p.record(role)
            roles.append({"role": role, "rating": r.value, "record": _record_text(w, l, d),
                          "maps": w + l + d})
    heroes = []
    for hero, h in sorted(p.heroes.items(), key=lambda kv: -kv[1]["time"]):
        mins = h["time"] / 60
        heroes.append({"hero": hero, "role": season.hero_roles.get(hero), "time": h["time"],
                       "maps": h["maps"], "winrate": h["wins"] / h["rated"] if h["rated"] else None,
                       "per10": {k: (h[k] / mins * 10 if mins else 0) for k in PER10_KEYS}})
    mates = []
    for name, (games, wins) in p.teammates.items():
        if games >= 3:
            mates.append({"player": season.players[name], "games": games, "wins": wins,
                          "winrate": wins / games})
    mates.sort(key=lambda x: (-x["winrate"], -x["games"]))
    recent = []
    for a in reversed(p.appearances):
        recent.append({"a": a, "delta": book.deltas.get(a.map.id, {}).get(p.name)})
    w, l, d = p.record()
    return {"p": p, "rating": book.get(p.name).value if p.name in book.overall else None,
            "record": _record_text(w, l, d), "maps": w + l + d, "winrate": w / (w + l + d) if w + l + d else 0,
            "chart": chart, "roles": roles, "heroes": heroes,
            "best_mates": mates[:3], "recent": recent,
            "per10": {k: p.per10(k) for k in PER10_KEYS}}


def hero_view(season: Season) -> dict:
    total_time = sum(h["time"] for h in season.heroes.values()) or 1
    by_role = defaultdict(list)
    for hero, h in season.heroes.items():
        top = max(season.players.values(), key=lambda p: p.heroes.get(hero, {}).get("time", 0))
        by_role[season.hero_roles.get(hero, "unknown")].append({
            "hero": hero, "share": h["time"] / total_time, "time": h["time"], "maps": h["maps"],
            "winrate": h["wins"] / h["rated"] if h["rated"] else None, "rated": h["rated"],
            "top": top})
    for rows in by_role.values():
        rows.sort(key=lambda r: -r["time"])
    return {r: by_role.get(r, []) for r in (*ROLES, "unknown") if by_role.get(r)}


def builder_data(season: Season) -> list[dict]:
    """Everyone who has played, plus roster members who have not yet."""
    book, roster = season.book, season.roster
    names = set(season.players) | set(roster.names)
    out = []
    for name in sorted(names, key=str.casefold):
        p = season.players.get(name)
        counts = p.role_maps() if p else {}
        history = [r for r in sorted(ROLES, key=lambda r: -counts.get(r, 0)) if counts.get(r)]
        o = book.get(name)
        out.append({
            "name": name, "rating": o.value if name in book.overall else None,
            "overall": [round(o.mu, 4), round(o.sigma, 4)],
            "roles": {r: [round(book.by_role[(name, r)].mu, 4), round(book.by_role[(name, r)].sigma, 4)]
                      for r in ROLES if (name, r) in book.by_role},
            # Roles the player asked for in players.csv win over what they have played.
            "usual": roster.roles.get(name) or history or list(ROLES),
        })
    return out


def render(season: Season, club: Club, config_dir: Path, out: Path, warnings: list[str]) -> list[Path]:
    env = _env()
    if out.exists():
        shutil.rmtree(out)
    (out / "players").mkdir(parents=True)
    (out / "matches").mkdir()
    shutil.copytree(Path(__file__).parent / "static", out, dirs_exist_ok=True)
    logo = None
    if club.logo and (config_dir / club.logo).is_file():
        logo = "logo" + (config_dir / club.logo).suffix.lower()
        shutil.copy(config_dir / club.logo, out / logo)

    nights = defaultdict(list)
    for m in reversed(season.maps):
        nights[m.played_at.date()].append(match_view(season, m))
    hours = sum(m.duration for m in season.maps) / 3600
    brand = " ".join(x for x in (club.short_name or club.name, club.game) if x)
    common = {"club": club, "brand": brand, "logo": logo, "built": datetime.now().replace(microsecond=0),
              "roster_size": len(season.roster.names),
              "summary": {"maps": len(season.maps), "players": len(season.players),
                          "hours": hours, "nights": len(nights)}}
    written = []

    def page(template: str, path: str, depth: int, **ctx):
        html = env.get_template(template).render(**common, **ctx, root="../" * depth, page=template)
        target = out / path
        target.write_text(html, encoding="utf-8")
        written.append(target)

    boards = [leaderboard(season, club, None)] + [leaderboard(season, club, r) for r in ROLES]
    recent = [match_view(season, m) for m in list(reversed(season.maps))[:6]]
    page("index.html", "index.html", 0, boards=boards, recent=recent, warnings=warnings,
         unknown_heroes=sorted(season.unknown_heroes))
    page("matches.html", "matches/index.html", 1, nights=nights)
    for night in nights.values():
        for v in night:
            page("match.html", f"matches/{v['map'].id}.html", 1, v=v)
    for p in season.players.values():
        page("player.html", f"players/{p.slug}.html", 1, v=player_view(season, p, club))
    page("heroes.html", "heroes.html", 0, roles=hero_view(season))
    page("builder.html", "builder.html", 0,
         data=json.dumps(builder_data(season), ensure_ascii=False).replace("</", "<\\/"))
    page("about.html", "about.html", 0)
    return written
