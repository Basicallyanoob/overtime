"""Overtime: build the stats site, import logs and players, and balance a lobby.

    overtime import [FOLDER/FILES/ZIP]   copy new ScrimTime logs into logs/
    overtime players [--add]            list in-game names missing from players.csv
    overtime build                      make the website in site/
    overtime teams signups.csv          balance ten players from a sign-up sheet
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .balance import Signup, balance, parse_roles
from .config import ROSTER_FILE, append_players, load_club, load_heroes, load_roster
from .parse import parse_folder
from .stats import build_season


def _season(args):
    config = Path(args.config)
    maps, warnings = parse_folder(args.logs)
    roster = load_roster(config)
    season = build_season(maps, roster, load_heroes(config))
    return season, warnings


def _maybe_add(args, names: dict[str, int]) -> None:
    if not names:
        return
    if args.add:
        path = append_players(Path(args.config), list(names))
        print(f"Added {len(names)} name{'s' if len(names) != 1 else ''} to {path}. Open it in a "
              "spreadsheet to give each person one display name, merge alts onto one row "
              "(in-game names separated by ;) and fill in their roles.")
    else:
        print(f"Run again with --add to put them in config/{ROSTER_FILE}.")


def cmd_build(args) -> int:
    from .site import render

    season, warnings = _season(args)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    if season.unknown_heroes:
        print("warning: add these heroes to config/heroes.yaml:",
              ", ".join(sorted(season.unknown_heroes)), file=sys.stderr)
    pages = render(season, load_club(Path(args.config)), Path(args.config), Path(args.out), warnings)
    if not season.maps:
        print(f"No maps in {args.logs}/ yet, so the site shows how to add them.")
    print(f"Built {len(pages)} pages from {len(season.maps)} maps and "
          f"{len(season.players)} players into {args.out}/")
    return 0


def cmd_import(args) -> int:
    from .importer import default_sources, import_logs

    try:
        sources = [Path(s) for s in args.sources] or default_sources()
        report = import_logs(sources, Path(args.logs), load_roster(Path(args.config)))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Looked in: {', '.join(str(s) for s in sources)}")
    print(f"Added {len(report.added)} new map{'s' if len(report.added) != 1 else ''}"
          f"{', skipped ' + str(report.duplicates) + ' already imported' if report.duplicates else ''}"
          f"{', ignored ' + str(len(report.not_logs)) + ' files that are not ScrimTime logs' if report.not_logs else ''}.")
    for p in report.added:
        print("  +", p.relative_to(Path(args.logs)) if p.is_relative_to(Path(args.logs)) else p)
    if report.unfinished:
        print("Unfinished (shown but not rated):", ", ".join(report.unfinished))
    if report.new_names:
        print("New in-game names, not in players.csv yet:",
              ", ".join(f"{n} ({c})" for n, c in report.new_names.items()))
    _maybe_add(args, report.new_names)
    return 0


def cmd_players(args) -> int:
    from .importer import unknown_names

    names = unknown_names(Path(args.logs), load_roster(Path(args.config)))
    if not names:
        print(f"Every in-game name in {args.logs}/ is in config/{ROSTER_FILE}.")
        return 0
    print(f"{len(names)} in-game name{'s' if len(names) != 1 else ''} not in config/{ROSTER_FILE} "
          "(maps played):")
    for n, c in names.items():
        print(f"  {n} ({c})")
    _maybe_add(args, names)
    return 0


def cmd_teams(args) -> int:
    season, _ = _season(args)
    with open(args.signups, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh) if r and r[0].strip() and not r[0].startswith("#")]
    if rows and rows[0][0].strip().lower() in ("player", "name"):
        rows = rows[1:]
    roster = season.roster
    signups = []
    for r in rows:
        name = roster.resolve(r[0].strip())
        given = r[1].strip() if len(r) > 1 else ""
        roles = parse_roles(given) if given else roster.roles.get(name) or parse_roles("any")
        signups.append(Signup(name, roles))
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
    ap = argparse.ArgumentParser(prog="overtime", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", default="logs", help="folder of ScrimTime .txt logs (default: logs)")
    ap.add_argument("--config", default="config", help="folder with club.yaml, heroes.yaml, players.csv")
    sub = ap.add_subparsers(dest="command", required=True)
    i = sub.add_parser("import", help="copy new ScrimTime logs into the logs folder")
    i.add_argument("sources", nargs="*", help="folders, .txt logs or a .zip (default: the Workshop folder)")
    i.add_argument("--add", "--add-players", dest="add", action="store_true",
                   help="also add new in-game names to players.csv")
    i.set_defaults(func=cmd_import)
    p = sub.add_parser("players", help="list in-game names missing from players.csv")
    p.add_argument("--add", action="store_true", help="append them to players.csv")
    p.set_defaults(func=cmd_players)
    b = sub.add_parser("build", help="build the static site")
    b.add_argument("--out", default="site", help="output folder (default: site)")
    b.set_defaults(func=cmd_build)
    t = sub.add_parser("teams", help="balance ten players from a sign-up CSV")
    t.add_argument("signups", help="CSV of player,roles; roles default to those in players.csv")
    t.add_argument("--options", type=int, default=3, help="how many lineups to show")
    t.set_defaults(func=cmd_teams)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
