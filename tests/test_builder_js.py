"""The browser team builder must pick the same teams as overtime/balance.py."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from overtime.balance import Signup, balance
from overtime.config import ROLES
from overtime.ratings import Rating, RatingBook

JS = Path(__file__).resolve().parents[1] / "overtime" / "static" / "builder.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(signups, ratings):
    script = (f"const b = require({json.dumps(str(JS))});"
              f"console.log(JSON.stringify(b.balance({json.dumps(signups)}, {json.dumps(ratings)})));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("seed", range(5))
def test_js_and_python_agree(seed):
    rng = random.Random(seed)
    book, ratings, signups = RatingBook(), {}, []
    for i in range(10):
        name = f"p{i}"
        roles = rng.sample(ROLES, rng.randint(1, 3))
        signups.append(Signup(name, roles))
        o = Rating(rng.uniform(18, 32), rng.uniform(2, 8))
        book.overall[name] = o
        ratings[name] = {"overall": [o.mu, o.sigma], "roles": {}}
        for r in roles[: rng.randint(0, len(roles))]:
            rr = Rating(rng.uniform(18, 32), rng.uniform(2, 8))
            book.by_role[(name, r)] = rr
            ratings[name]["roles"][r] = [rr.mu, rr.sigma]
    try:
        py = balance(signups, book)
    except ValueError:
        pytest.skip("random lobby has no legal teams")
    js = run_js([{"player": s.player, "roles": s.roles} for s in signups], ratings)
    assert len(js) == len(py)
    for a, b in zip(py, js):
        assert b["score"] == pytest.approx(a.score)
        assert b["win_probability"] == pytest.approx(a.win_probability, abs=1e-6)
    assert js[0]["team1"] == py[0].team1 and js[0]["team2"] == py[0].team2
