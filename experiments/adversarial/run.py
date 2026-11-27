"""Run the adversarial scenarios against each implementation."""

import json
import os
import subprocess
import sys
from itertools import permutations
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "scenarios.json").read_text())
VERSIONS = ("v1", "v2", "v3")


def main():
    # 1. Choose the scenarios and number of runs
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    selected = sys.argv[2:]
    ids = [case["id"] for case in CASES]

    if runs < 1 or len(ids) != len(set(ids)) or set(selected) - set(ids):
        raise ValueError("Invalid run count or scenario IDs")

    # 2. Generate and shuffle all possible version orders
    orders = list(permutations(VERSIONS))
    Random(42).shuffle(orders)

    # 3. Run every version with the same scenarios
    for run in range(1, runs + 1):
        for version in orders[(run - 1) % len(orders)]:
            # 4. Configure the selected version and result file
            workspace = ROOT / "workspaces" / version
            python = workspace / ".venv/bin/python"
            report = ROOT / "results/adversarial" / f"run_{run}" / f"adversarial_{version}.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"commit_info": None, "evaluations": []}, indent=2) + "\n")
            env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", "EVAL_VERSION": version, "EVAL_REPORT": str(report), "EVAL_RUN": str(run), "EVAL_CASES": ",".join(selected)}

            # 5. Execute all selected scenarios in one pytest process
            print(f"Run {run} | {version}", flush=True)
            subprocess.run([str(python), "-m", "pytest", "-p", "no:django", str(HERE / "test_adversarial.py"), "-q"], cwd=workspace, env=env, timeout=180 * max(1, len(selected) or len(CASES)), check=True)
            print(f"Saved: {report}", flush=True)


if __name__ == "__main__":
    main()
