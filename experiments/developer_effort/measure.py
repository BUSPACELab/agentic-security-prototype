"""Measure application developer effort across the three implementations."""

import ast
import csv
import json
import subprocess
from pathlib import Path
from collections import defaultdict
from radon.complexity import cc_visit, cc_rank, add_inner_blocks
from radon.visitors import Function


# 1. Setup
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/developer_effort"
CLASSIFICATION = Path(__file__).with_name("classification.csv")
VERSIONS = ("v1", "v2", "v3")


def save_csv(name, rows, fields=None):
    """Save measurement results."""
    with (OUT / name).open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(args, folder):
    return subprocess.check_output(args, cwd=folder, text=True)


# 2. General LOC
def source_files(folder):
    """Get tracked application Python files, excluding tests and migrations."""
    files = run(["git", "ls-files"], folder).splitlines()
    return [f for f in files if f.endswith(".py") and (f.startswith(("apps/", "config/", "mcp_client/", "mcp_server/")) or f == "manage.py") and not set(Path(f).parts) & {"tests", "test", "migrations"} and not Path(f).name.startswith("test_") and Path(f).stem != "tests"]


def cloc(folder, files):
    """Count source lines using CLOC."""
    if not files:
        return 0
    report = json.loads(run(["cloc", "--json", "--quiet", "--skip-uniqueness", *files], folder))
    return report.get("Python", {}).get("code", 0)


# 3. Classified LOC and counts
def selected_lines(rows, *kinds):
    """Collect unique classified line numbers for each file."""
    selected = defaultdict(set)
    for row in rows:
        if row["kind"] in kinds:
            selected[row["file"]].update(range(int(row["start"]), int(row["end"]) + 1))
    return selected


def count_loc(folder, selected):
    """Count classified code, excluding comments, blank lines and docstrings."""
    total = 0
    for file, selected_rows in selected.items():
        source = (folder / file).read_text(encoding="utf-8-sig")
        ignored = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node) is not None:
                doc = node.body[0]
                ignored.update(range(doc.lineno, doc.end_lineno + 1))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                ignored.update(range(node.lineno + 1, node.end_lineno))
        total += sum(i in selected_rows and i not in ignored and bool(line.strip()) and not line.lstrip().startswith("#") for i, line in enumerate(source.splitlines(), 1))
    return total


def count_items(rows, kind):
    return sum(1 for r in rows if r["kind"] == kind)


# 4. Complexity
def complexity(folder, version, files, selected):
    """Measure cyclomatic complexity of application functions and methods."""
    results = {}

    for file in files:
        source = (folder / file).read_text(encoding="utf-8-sig")

        # Include methods and nested functions
        for block in add_inner_blocks(cc_visit(source)):
            if isinstance(block, Function):
                lines = range(block.lineno, block.endline + 1)
                security_related = bool(selected.get(file, set()).intersection(lines))
                results[file, block.lineno, block.col_offset] = dict(version=version, file=file, function=block.name, line=block.lineno, complexity=block.complexity, grade=cc_rank(block.complexity), security_related=int(security_related))

    return list(results.values())


# 5. Comparison and differences
def comparison(totals):
    rows = [{"metric": m, **{v: totals[v][m] for v in VERSIONS}} for m in totals["v1"]]
    differences = []
    for row in rows:
        result = {"metric": row["metric"]}
        for a, b in [("v2", "v1"), ("v3", "v1"), ("v3", "v2")]:
            delta = row[a] - row[b]
            result[f"{a.upper()} - {b.upper()}"] = delta
            result[f"{a.upper()} vs {b.upper()} (%)"] = round(delta / row[b] * 100, 1) if row[b] else "N/A"
        differences.append(result)
    save_csv("comparison.csv", rows)
    save_csv("differences.csv", differences)


# 6. Main
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with CLASSIFICATION.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    totals, cc = {}, []
    for version in VERSIONS:
        folder = ROOT / "workspaces" / version
        reviewed = [r for r in rows if r["version"] == version]
        files = source_files(folder)
        total = cloc(folder, files)
        client = cloc(folder, [f for f in files if f.startswith("mcp_client/")])
        server = cloc(folder, [f for f in files if f.startswith("mcp_server/")])
        totals[version] = {
            "Application LOC": total - client - server,
            "MCP client LOC": client,
            "MCP server LOC": server,
            "Application security LOC": count_loc(folder, selected_lines(reviewed, "security_code")),
            "Application policy LOC": count_loc(folder, selected_lines(reviewed, "policy_code")),
            "Total LOC": total,
            "Security checks (count)": count_items(reviewed, "security_check"),
            "Policies (count)": count_items(reviewed, "policy"),
        }
        cc.extend(complexity(folder, version, files, selected_lines(reviewed, "security_code", "policy_code")))
    save_csv("complexity.csv", cc, ["version", "file", "function", "line", "complexity", "grade", "security_related"])
    comparison(totals)


if __name__ == "__main__":
    main()
