
"""Reset application data before evaluation trials"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    """Restore the same initial data in the selected workspaces"""

    # Select one version or all configured versions
    config = json.loads((ROOT / "config" / "versions.json").read_text())
    versions = [sys.argv[1]] if len(sys.argv) > 1 else list(config["branches"])

    for version in versions:
        if version not in config["branches"]:
            raise ValueError(f"Unknown version: {version}")

        workspace = ROOT / "workspaces" / version
        python = workspace / ".venv" / "bin" / "python"

        if not python.exists():
            raise FileNotFoundError(f"Run preparation first for {version}")

        # Clear the database while keeping its tables
        subprocess.run([str(python), "manage.py", "flush", "--noinput"], cwd=workspace, check=True)

        # Remove files created by previous trials
        shutil.rmtree(workspace / "media", ignore_errors=True)

        # Restore the shared evaluation dataset
        subprocess.run([str(python), "-m", "setup.seed", version], cwd=ROOT, check=True)

    print("Reset complete")


if __name__ == "__main__":
    main()
