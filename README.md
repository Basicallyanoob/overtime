# Overtime

Leaderboards, player profiles and a team balancer for university Overwatch clubs, built from the custom games ("inhouses") that never show up on public stat sites.

The club hosts its inhouses with the ScrimTime Workshop mode, which writes a log file for every map. Drop those logs into this repository and GitHub builds a static website: a ladder for each role, a profile for every member, a scoreboard for every map, and a team builder that splits tonight's lobby into the fairest 5v5.

![Leaderboard](docs/leaderboard.png)

Inspired by [Blueward](https://github.com/Kickblip/blueward), which does the same for League of Legends clubs. The site in this repository runs on an invented demo season so it works out of the box; every player and number in `logs/` is synthetic.

## What it does

- **Ratings per role.** After every finished map, winners go up and losers go down, more so when the result was a surprise. Players get an overall rating and one each for tank, damage and support, decided by the hero they spent most of the map on. The model is Plackett-Luce from [openskill](https://github.com/vivekjoshy/openskill.py), a Bayesian rating in the TrueSkill family.
- **Profiles.** Rating history, heroes with per-10-minute stats, best teammates, and every map played.
- **Match pages.** Both scoreboards, each player's rating change, and what the ratings predicted beforehand. Results the ratings gave less than a 35% chance are flagged as upsets.
- **Team builder.** Pick ten players and the roles each will play; it checks every legal 1-2-2 split and shows the three most even, with a win chance for each side and a button to copy the teams into Discord. It runs in the browser, so officers can use it from a phone in the lobby.
- **Alts and name changes.** `config/players.yaml` folds several in-game names into one profile.

![Team builder](docs/team-builder.png)

## How the data gets in

Overwatch has no public API for custom games, so the stats come from the Workshop. ScrimTime writes one CSV-style event log per map, including a cumulative stat line for every player on every hero at the end of each round.

1. **Host with ScrimTime.** Import the [ScrimTime](https://workshop.codes/FYHQV) mode by Caldoran into your custom game and turn on its Log Generator and Player Stat Summary in the Workshop settings.
2. **Turn on logging.** In Overwatch, enable *Options > Gameplay > Enable Workshop Inspector Log File*. Only the lobby host's game writes logs, so the host needs this on.
3. **Find the files.** Logs are saved to `Documents/Overwatch/Workshop`, one `Log-YYYY-MM-DD-HH-MM-SS.txt` per map.

## Set it up for your club

1. Create your own copy of this repository on GitHub.
2. Edit `config/club.yaml` with your club's name and season, and `config/players.yaml` with members who play under more than one name.
3. Delete the demo logs in `logs/` and add your own.
4. In the repository on GitHub, open *Settings > Pages* and set *Source* to *GitHub Actions*.

Every push to `main` now runs the tests, rebuilds the site and publishes it. GitHub shows the address under *Settings > Pages*.

**Adding a club night's games.** Copy that night's log files into `logs/` and push them. Officers who don't use git can open the `logs` folder on GitHub, choose *Add file > Upload files*, drag the logs in and commit. The site updates a minute or two later.

**New heroes.** If a hero is missing from `config/heroes.yaml`, the build lists it and the site shows a notice. Add the name exactly as the game spells it, under its role.

## Run it locally

Needs Python 3.10 or newer.

```
pip install -r requirements.txt
python -m overtime build          # writes the site to site/
python -m overtime teams examples/signups.csv
python -m pytest
```

Open `site/index.html` in a browser. `python scripts/make_demo_logs.py` regenerates the demo season.

## How the ratings work

Each player's skill is held as an estimate and an uncertainty. The number shown is the estimate, on a scale where everyone starts at 1,000; the uncertainty drives the win probabilities. A team result says little about any one player, so ratings stay jumpy for the first couple of dozen maps, and players need a minimum number of maps (`min_maps` in `config/club.yaml`) before they appear on a ladder. Only results feed the rating: eliminations, damage and healing are displayed but never counted, since a support who keeps their team alive can have quiet numbers on a winning map.

The team builder scores each split by the gap in summed role ratings, plus a cost worth 40 rating points for every step a player sits below their first-choice role, and returns the lowest.

## Project layout

```
overtime/parse.py     reads ScrimTime logs into one record per map
overtime/stats.py     season totals, heroes, teammates
overtime/ratings.py   rating updates and win probabilities
overtime/balance.py   the team builder's search (mirrored in static/builder.js)
overtime/site.py      renders the static site from templates/
config/               club settings, hero roles, player aliases
logs/                 one .txt log per map (demo data until you replace it)
tests/                parser, ratings, balancer, site build, and a check that
                      the browser builder picks the same teams as Python
```

## Limitations

- Only maps hosted with ScrimTime, by a host with log files switched on, are recorded.
- A log that stops before the end of the match is listed as unfinished and not rated.
- Ratings from a single term are noisy; treat small gaps as ties.
- The published site is public. Check that members are happy for their in-game names and stats to appear before turning it on.

## Credits

- [ScrimTime](https://workshop.codes/FYHQV) by Caldoran writes the logs. Its event format is also documented by [Parsertime](https://github.com/lucasdoell/parsertime), whose sample logs were used to check this parser.
- [openskill.py](https://github.com/vivekjoshy/openskill.py) for the rating model.
- Barlow and Barlow Condensed by Jeremy Tribby, under the SIL Open Font License (`overtime/static/fonts/OFL-Barlow.txt`).

Overwatch is a trademark of Blizzard Entertainment. This project is not affiliated with or endorsed by Blizzard.
