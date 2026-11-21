
"""Benchmark MCP tool execution without LLM inference"""

import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from apps.agents.tooling import get_tools_for_context
from apps.files.models import UploadedFile


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("scenario", [
    "list", "search", "read_small", "read_medium", "read_large",
    "schema", "select", "update", "delete"
])
def test_cold_start_execution(benchmark, scenario):
    """Measure tool execution with a new MCP process for each call"""

    # 1. Get the version and test user
    version = os.environ["EVAL_VERSION"]
    user = get_user_model().objects.get(username="alice")
    folder = f"users/{user.pk}"

    # 2. Define the tool calls for each scenario
    scenarios = {
        "list": ("list_files", {"path": folder}, "file"),
        "search": ("search_files", {"query": "notes"}, "file"),
        "read_small": ("read_file", {"path": f"{folder}/release_readiness_summary.txt"}, "file"),
        "read_medium": ("read_file", {"path": f"{folder}/customer_feedback_history.txt"}, "file"),
        "read_large": ("read_file", {"path": f"{folder}/portal_activity_records.csv"}, "file"),
        "schema": ("get_database_schema", {}, "file"),
        "select": ("execute_sql", {"query": f"SELECT title FROM files_uploadedfile WHERE file = '{folder}/notes.txt'"}, "file"),
        "update": ("execute_sql", {"query": f"UPDATE auth_user SET first_name = 'Benchmark' WHERE id = {user.pk}"}, "profile"),
        "delete": ("delete_file", {"path": f"{folder}/tasks.txt"}, "file"),
    }

    tool_name, arguments, context = scenarios[scenario]

    # 3. Get the tool available in the current context
    tools = get_tools_for_context(user, context) if version == "v2" else get_tools_for_context(context)
    tool = next(tool for tool in tools if tool.name == tool_name)

    # 4. Set the security context for V3
    security = nullcontext()

    if version == "v3":
        from security_system.context import Principal, SecurityContext, bind_security_context
        chat = "profile_chat" if context == "profile" else "file_chat"
        security = bind_security_context(SecurityContext(Principal(str(user.pk)), {"chat_context": chat}))

    # 5. Save the original data for verification and cleanup
    file_path = Path(settings.MEDIA_ROOT) / arguments["path"] if tool_name in {"read_file", "delete_file"} else None
    expected_content = file_path.read_text(encoding="utf-8") if scenario.startswith("read_") else None
    input_bytes = file_path.stat().st_size if scenario.startswith("read_") else None
    original_name = user.first_name
    result = None

    # 6. Define how the tool is executed
    def execute_tool():
        nonlocal result

        if version == "v2":
            from apps.agents.enforcement import authorize_tool_invocation, filter_tool_result
            permission = authorize_tool_invocation(user, context, tool_name, arguments)
            assert permission.allowed, permission.message
            result = filter_tool_result(context, tool_name, tool.invoke(permission.safe_args))
        else:
            result = tool.invoke(arguments)

        return result

    # 7. Define how to verify results and restore data
    def verify_and_restore():
        try:
            assert isinstance(result, str)

            if scenario == "list":
                expected_files = {p.name for p in (Path(settings.MEDIA_ROOT) / folder).iterdir() if p.is_file()}
                returned_files = [Path(line).name for line in result.splitlines()]
                assert set(returned_files) == expected_files
                assert len(returned_files) == len(expected_files)

            elif scenario == "search":
                assert "notes.txt" in result
                assert len(result.splitlines()) == (2 if version == "v1" else 1)

            elif scenario.startswith("read_"):
                assert result == expected_content

            elif scenario == "schema":
                assert "files_uploadedfile" in result
                if version != "v1":
                    assert "auth_user" not in result

            elif scenario == "select":
                assert json.loads(result)["rows"] == [["notes.txt"]]

            elif scenario == "update":
                assert get_user_model().objects.get(pk=user.pk).first_name == "Benchmark"

            elif scenario == "delete":
                assert not file_path.exists()
                assert not UploadedFile.objects.filter(file=arguments["path"]).exists()

        finally:
            if scenario == "update":
                get_user_model().objects.filter(pk=user.pk).update(first_name=original_name)
            elif scenario == "delete":
                connections.close_all()
                subprocess.run([sys.executable, "-m", "setup.reset", version], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

    # 8. Run the benchmark and save the results
    with security:
        benchmark.pedantic(execute_tool, rounds=30, warmup_rounds=2, teardown=verify_and_restore)

    benchmark.extra_info.update({
        "version": version,
        "scenario": scenario,
        "input_bytes": input_bytes,
        "response_bytes": len(result.encode("utf-8")),
    })
