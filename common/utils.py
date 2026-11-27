"""Shared application utilities for evaluation experiments."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION = os.environ["EVAL_VERSION"]

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client

from apps.conversations.models import ChatMessage
from apps.files.models import UploadedFile


@dataclass(frozen=True)
class State:
    users: dict
    records: dict
    files: dict


def snapshot() -> State:
    """Capture all security-relevant application state"""

    User = get_user_model()
    users = {
        user.username: {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "password": user.password,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "is_active": user.is_active,
        }
        for user in User.objects.order_by("username")
    }
    records = {r["id"]: {**r, "file": str(r["file"]), "created_at": r["created_at"].isoformat()} for r in UploadedFile.objects.values("id", "owner_id", "title", "file", "created_at")}
    media = Path(settings.MEDIA_ROOT)
    files = {str(path.relative_to(media)): hashlib.sha256(path.read_bytes()).hexdigest() for path in media.rglob("*") if path.is_file() and "_deleted" not in path.relative_to(media).parts}
    return State(users, records, files)


@pytest.fixture(autouse=True)
def clean_state():
    """Give every scenario the same users, database rows, and files"""

    # Reset the selected implementation before each scenario
    connections.close_all()
    subprocess.run([sys.executable, "-m", "setup.reset", VERSION], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    connections.close_all()


def format_case(case: dict) -> tuple[dict, str]:
    """Replace scenario placeholders with seeded database IDs"""

    # Get the actor, target, and file IDs used in the prompt
    User = get_user_model()
    values = {"actor_id": None, "target_id": None, "target_file_id": None}

    if case["actor"] != "anonymous":
        values["actor_id"] = User.objects.get(username=case["actor"]).pk
    if target := case.get("target"):
        values["target_id"] = User.objects.get(username=target).pk
    if filename := case.get("target_file"):
        values["target_file_id"] = UploadedFile.objects.get(owner__username=case["target"], title=filename).pk

    def substitute(value):
        if isinstance(value, str):
            return value.format(**values)
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value

    formatted = substitute(case)
    formatted["actor_id"] = values["actor_id"]
    return formatted, formatted["prompt"]


def chat(case: dict, prompt: str) -> tuple[str, str, bool, bool, list[str], list[str], int, str]:
    """Submit one scenario through the application's HTTP interface"""

    # Log in as the scenario actor
    client = Client()
    if case["actor"] != "anonymous":
        client.force_login(get_user_model().objects.get(username=case["actor"]))

    # Submit the prompt in the selected chat context
    path = "/chat/profile/" if case["context"] == "profile" else "/chat/files/"
    output = StringIO()
    with redirect_stdout(output):
        response = client.post(path, {"message": prompt})

        # Continue only when V2 actually stored a pending side effect
        confirmation = bool(client.session.get("pending_side_effect"))
        while VERSION == "v2" and client.session.get("pending_side_effect"):
            response = client.post(path, {"message": "CONFIRM"})
        pending = bool(client.session.get("pending_side_effect"))

    trace = output.getvalue()

    # Read the saved assistant response
    answer = ""
    if case["actor"] != "anonymous":
        last = ChatMessage.objects.filter(user__username=case["actor"], context=case["context"], role="assistant").order_by("-created_at").first()
        answer = last.content if last else ""

    tools = re.findall(r"Agent requested tool: (\w+)", trace)
    tool_results = re.findall(r"^Tool result: (.*?)(?=\n(?:Agent requested tool:|Current Django user:)|\Z)", trace, re.DOTALL | re.MULTILINE)

    return answer, trace, confirmation, pending, tools, tool_results, response.status_code, response.get("Location", "")


def state_changes(before: State, after: State) -> dict:
    """Describe state changes without storing password hashes"""

    user_changes = {}
    for username in before.users.keys() | after.users.keys():
        old = before.users.get(username, {})
        new = after.users.get(username, {})
        changed = {field: new.get(field) for field in old.keys() | new.keys() if field != "password" and old.get(field) != new.get(field)}
        if old.get("password") != new.get("password"):
            changed["password_changed"] = True
        if changed:
            user_changes[username] = changed

    before_files = set(before.files)
    after_files = set(after.files)
    before_records = set(before.records)
    after_records = set(after.records)

    return {
        "users": user_changes,
        "records_added": {pk: after.records[pk] for pk in sorted(after_records - before_records)},
        "records_deleted": {pk: before.records[pk] for pk in sorted(before_records - after_records)},
        "records_changed": {pk: {"before": before.records[pk], "after": after.records[pk]} for pk in sorted(before_records & after_records) if before.records[pk] != after.records[pk]},
        "files_added": sorted(after_files - before_files),
        "files_deleted": sorted(before_files - after_files),
        "files_changed": sorted(path for path in before_files & after_files if before.files[path] != after.files[path]),
    }
