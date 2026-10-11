"""The Valorant team builder must find the most even split of ten players."""
import json
import random
import shutil
import subprocess
from itertools import combinations
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "overtime" / "static" / "valbuilder.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(names, ratings):
    script = (f"const b = require({json.dumps(str(JS))});"
              f"console.log(JSON.stringify(b.balance({json.dumps(names)}, {json.dumps(ratings)})));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def score(team, names, ratings):
    """The builder's rule, written out independently: rating gap + 1.0 per side without a controller main."""
    other = [p for p in names if p not in team]
    gap = abs(sum(ratings[p]["overall"][0] for p in team) - sum(ratings[p]["overall"][0] for p in other))
    smokes = lambda t: any(ratings[p].get("cls") == "controller" for p in t)
    spread = sum(ratings[p].get("cls") == "controller" for p in names) >= 2
    return gap + (sum(not smokes(t) for t in (team, other)) if spread else 0)


@pytest.mark.parametrize("seed", range(8))
def test_best_split_is_the_true_optimum(seed):
    rng = random.Random(seed)
    names = [f"p{i}" for i in range(10)]
    classes = ["duelist", "initiator", "controller", "sentinel", None]
    ratings = {n: {"overall": [rng.uniform(18, 32), rng.uniform(2, 8)], "cls": rng.choice(classes)} for n in names}
    best = min(score(t, names, ratings) for t in combinations(names, 5))
    js = run_js(names, ratings)
    assert len(js) == 3 and js[0]["score"] == pytest.approx(best)
    assert sorted(js[0]["team1"] + js[0]["team2"]) == sorted(names)
    assert js[0]["score"] <= js[1]["score"] <= js[2]["score"]


def test_two_controller_mains_go_to_different_sides():
    names = [f"p{i}" for i in range(10)]
    ratings = {n: {"overall": [25, 5], "cls": "duelist"} for n in names}
    ratings["p0"]["cls"] = ratings["p1"]["cls"] = "controller"
    best = run_js(names, ratings)[0]
    assert "p0" in best["team1"] and "p1" in best["team2"]  # p0 is always placed in team 1
