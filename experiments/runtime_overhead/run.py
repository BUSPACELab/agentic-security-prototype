
"""Run cold-start or persistent-session MCP benchmarks"""

import os
import subprocess
import sys
from itertools import permutations
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[2]

TESTS = {
    "cold_start": "test_runtime_overhead.py",
    "persistent_session": "test_persistent_session.py",
}


def main():
    # 1. Choose the benchmark and number of runs
    mode = sys.argv[1] if len(sys.argv) > 1 else "cold_start"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 6

    if mode not in TESTS or runs < 1:
        raise ValueError("Invalid benchmark mode or number of runs")

    test = Path(__file__).with_name(TESTS[mode])
    output = ROOT / "results/runtime_overhead" / mode

    # 2. Generate and shuffle all possible version orders
    orders = list(permutations(("v1", "v2", "v3")))
    Random(42).shuffle(orders)

    # 3. Run each benchmark with a different version order
    for run in range(1, runs + 1):
        versions = orders[(run - 1) % len(orders)]
        print(f"\n{'=' * 60}")
        print(f"Run {run}/{runs} | {mode} | Order: {', '.join(versions)}")
        print(f"{'=' * 60}", flush=True)

        for version in versions:
            print(f"\n--- Benchmarking {version.upper()} ---", flush=True)
            workspace = ROOT / "workspaces" / version
            python = workspace / ".venv/bin/python"
            report = output / f"run_{run}" / f"overhead_{version}.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "EVAL_VERSION": version, "DJANGO_SETTINGS_MODULE": "config.settings"}

            # 4. Reset the data and run the benchmark
            report.unlink(missing_ok=True)
            subprocess.run([sys.executable, "-m", "setup.reset", version], cwd=ROOT, check=True)

            try:
                subprocess.run([str(python), "-m", "pytest", "-p", "no:django", str(test), "-q", f"--benchmark-json={report}"], cwd=workspace, env=env, check=True)
            finally:
                subprocess.run([sys.executable, "-m", "setup.reset", version], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
