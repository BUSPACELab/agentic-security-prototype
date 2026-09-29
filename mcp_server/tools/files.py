"""
File operation helpers for the custom MCP server

This module contains reusable filesystem logic used by MCP tools. The functions
are kept separate from the MCP server entrypoint so the tool behavior can be
updated independently.
"""

from pathlib import Path
from uuid import uuid4

from config.security import system
from security_system.context import current_security_context

from ..config import MCP_ROOT


def build_mcp_path(path: str = "") -> Path:
    """
    Build a filesystem path using the configured MCP root.

    Example:
    users/10/a.txt -> /project/media/users/10/a.txt
    """
    return (MCP_ROOT / (path or "")).resolve()


def _default_user_path(path: str = "") -> str:
    """Return the provided path or the current user's root."""

    if path:
        return path

    user_id = current_security_context().principal.subject

    return f"users/{user_id}"


def list_files_impl(path: str = "") -> str:
    """List files and folders for a path."""

    target_path = build_mcp_path(_default_user_path(path))

    entries = system.list(target_path, recursive=True)

    return "\n".join(str(entry) for entry in entries)


def search_files_impl(query: str) -> str:
    """Search the current user's files and folders by name."""

    words = query.lower().strip().split()

    user_id = current_security_context().principal.subject
    target_path = build_mcp_path(f"users/{user_id}")

    entries = system.list(target_path, recursive=True)

    matches = [
        entry
        for entry in entries
        if all(word in entry.name.lower() for word in words)
    ]

    return "\n".join(str(match) for match in matches)


def read_file_impl(path: str) -> str:
    """Read a text file."""

    path = build_mcp_path(path)

    return system.read_text(path)


def delete_file_impl(path: str) -> bool:
    """Delete a file."""

    source = build_mcp_path(path)

    user_id = current_security_context().principal.subject

    deleted_root = MCP_ROOT / "_deleted" / user_id
    deleted_root.mkdir(parents=True, exist_ok=True)

    destination = deleted_root / f"{uuid4().hex}_{source.name}"

    # Move the file to the "_deleted" folder
    system.move_file(source, destination)

    return True