
"""Prepare the three application versions for evaluation"""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "workspaces"


def main():
    """Clone, initialize, and record the three application versions"""

    # Read the repository and branch configuration
    config = json.loads((ROOT / "config" / "versions.json").read_text())
    WORKSPACES.mkdir(exist_ok=True)

    manifest = {}

    for version, branch in config["branches"].items():
        folder = WORKSPACES / version

        # Clone the latest branch only if it is missing
        if not folder.exists():
            subprocess.run(["git", "clone", "--branch", branch, config["repository"], str(folder)], check=True)

        # Verify the existing workspace is the expected branch
        current_branch = subprocess.check_output(["git", "-C", str(folder), "branch", "--show-current"], text=True).strip()
        if current_branch != branch:
            raise RuntimeError(f"Unexpected branch for {version}")

        # Create an independent Python environment
        python = folder / ".venv" / "bin" / "python"
        if not python.exists():
            subprocess.run([sys.executable, "-m", "venv", str(folder / ".venv")], check=True)

        # Install dependencies and initialize Django
        subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=folder, check=True)
        subprocess.run([str(python), "manage.py", "migrate", "--noinput"], cwd=folder, check=True)

        # Record the exact commit used
        commit = subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()
        manifest[version] = {"branch": branch, "commit": commit}
        print(f"{version} ready: {commit[:12]}")

    # Save the commits for reproducibility
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    (results / "setup_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print("Preparation complete")


if __name__ == "__main__":
    main()
