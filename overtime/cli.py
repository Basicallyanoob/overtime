"""Command line: `overtime build` makes the site, `overtime teams` balances a lobby."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .balance import Signup, balance, parse_roles
from .config import load_club, load_heroes, load_roster
from .parse import parse_folder
from .stats import build_season


def _season(args):
    config = Path(args.config)
    maps, warnings = parse_folder(args.logs)
    season = build_season(maps, load_roster(config), load_heroes(config))
    return season, warnings


def cmd_build(args) -> int:
    from .site import render

    season, warnings = _season(args)
    if not season.maps:
        print(f"No usable logs in {args.logs}. Copy ScrimTime .txt logs there first.", file=sys.stderr)
        return 1
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    if season.unknown_heroes:
        print("warning: add these heroes to config/heroes.yaml:",
              ", ".join(sorted(season.unknown_heroes)), file=sys.stderr)
    pages = render(season, load_club(Path(args.config)), Path(args.out), warnings)
    print(f"Built {len(pages)} pages from {len(season.maps)} maps and "
          f"{len(season.players)} players into {args.out}/")
    return 0


def cmd_teams(args) -> int:
    season, _ = _season(args)
    with open(args.signups, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].startswith("#")]
    if rows and rows[0][0].strip().lower() == "player":
        rows = rows[1:]
    roster = load_roster(Path(args.config))
    signups = [Signup(roster.resolve(r[0].strip()), parse_roles(r[1] if len(r) > 1 else "any"))
               for r in rows]
    for s in signups:
        if s.player not in season.players:
            print(f"note: {s.player} has no maps yet, so is treated as an average new player")
    try:
        options = balance(signups, season.book, top=args.options)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for i, o in enumerate(options, 1):
        print(f"\nOption {i}: {abs(o.gap) * 40:.0f} rating points apart, "
              f"{o.off_preference} steps off first-choice roles, "
              f"team 1 wins {o.win_probability:.0%} of the time")
        for name, team in (("Team 1", o.team1), ("Team 2", o.team2)):
            print(f"  {name}: " + " | ".join(f"{r.title()}: {', '.join(ps)}" for r, ps in team.items()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="overtime", description=__doc__)
    ap.add_argument("--logs", default="logs", help="folder of ScrimTime .txt logs (default: logs)")
    ap.add_argument("--config", default="config", help="folder with club.yaml, heroes.yaml, players.yaml")
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--out", default="site", help="output folder (default: site)")
    b.set_defaults(func=cmd_build)
    t = sub.add_parser("teams", help="balance ten players from a sign-up CSV")
    t.add_argument("signups", help="CSV of player,roles e.g. 'Kestrel,damage' or 'Pike,tank>support'")
    t.add_argument("--options", type=int, default=3, help="how many lineups to show")
    t.set_defaults(func=cmd_teams)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
