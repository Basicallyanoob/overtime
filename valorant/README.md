# Valorant games

One folder per club night, one file per game. You normally never touch this
folder: the *Build site* workflow fetches new inhouse games from the HenrikDev
API every morning (or when you press *Run workflow*) and saves them here.

- **`.json` files** are games saved by the importer, trimmed to what the site uses.
- **`.csv` files** are games typed in from the end-of-game scoreboard, for when the
  API is down or none of the accounts in `config/valorant.yaml` was in the lobby.
  Copy `examples/valorant-scoreboard.csv`, fill in one row per player, and save it
  in the night's folder, for example `2026-10-15/1930-ascent.csv`.

To remove a game (a warm-up that slipped through, say), delete its file.
