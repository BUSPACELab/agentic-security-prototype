"""
File operation helpers for the custom MCP server

This module contains reusable filesystem logic used by MCP tools. The functions
are kept separate from the MCP server entrypoint so the tool behavior can be
updated independently.
"""

from pathlib import Path
from uuid import uuid4

from ..config import MCP_ROOT
from config.security import system


def build_mcp_path(path: str = "") -> Path:
    """
    Build a filesystem path using the configured MCP root.

    Example:
    users/10/a.txt -> /project/media/users/10/a.txt
    """
    return (MCP_ROOT / (path or "")).resolve()


def list_files_impl(path: str, user_id: int | str ) -> str:
    """
    List files and folders for a path.

    args:
        path: The path to list
        user_id: The user requesting access to the path

    returns:
        A list of files and folders
    """
    target_path = build_mcp_path(path)

    entries = system.list(target_path, user_id, recursive=True)

    return "\n".join(str(entry) for entry in entries)


def search_files_impl(path: str, query: str, user_id: int | str) -> str:
    """
    Search files and folders by name.

    args:
        path: The path to search
        query: The search query
        user_id: The user requesting access to the path

    returns:
        A list of matching files
    """
    words = query.lower().strip().split()

    target_path = build_mcp_path(path)

    entries = system.list(target_path, user_id, recursive=True)

    matches = [entry for entry in entries if all(word in entry.name.lower() for word in words)]

    return "\n".join(str(match) for match in matches)


def read_file_impl(path: str, user_id: int | str) -> str:
    """
    Read a text file.

    args:
        path: The path to the file to read
        user_id: The user requesting access to the file

    returns:
        The contents of the file
    """

    path = build_mcp_path(path)

    return system.read_text(path, user_id)


def delete_file_impl(path: str, user_id: int | str) -> bool:
    """
    Delete a file.

    args:
        path: The path to the file to delete
        user_id: The user requesting access to the file
    returns:
        whether the file was deleted
    """
    source = build_mcp_path(path)

    deleted_root = MCP_ROOT / "_deleted" / str(user_id)
    deleted_root.mkdir(parents=True, exist_ok=True)

    destination = deleted_root / f"{uuid4().hex}_{source.name}"

    # Move the file to the "_deleted" folder
    system.move_file(source, destination, user_id)

    return True