from pathlib import Path
from django.conf import settings
from langchain_core.tools import tool

from apps.files.models import UploadedFile

from .client import call_custom_mcp_tool
from .path_helpers import resolve_user_file_path

INVALID_MESSAGE = "Invalid or unauthorized file path."
def user_mcp_root(user_id: int | str) -> str:
    """Return the scoped MCP filesystem root for one user."""

    return str(Path(settings.MCP_FILESYSTEM_ROOT) / "users" / str(user_id))

def list_files(path: str = "", user_id: int | str | None = None) -> str:
    """List files through the custom MCP server."""

    resolved = resolve_user_file_path(path, user_id, allow_root=True)

    if resolved is None:
        return INVALID_MESSAGE

    _database_path, mcp_path = resolved

    return call_custom_mcp_tool("list_files", {"path": mcp_path}, filesystem_root=user_mcp_root(user_id))


def search_files(query: str, path: str = "", user_id: int | str | None = None) -> str:
    """Search files through the custom MCP server."""

    resolved = resolve_user_file_path(path, user_id, allow_root=True)

    if resolved is None:
        return INVALID_MESSAGE

    _database_path, mcp_path = resolved

    return call_custom_mcp_tool("search_files", {"path": mcp_path, "query": query}, filesystem_root=user_mcp_root(user_id))


def read_file(path: str, user_id: int | str | None = None) -> str:
    """Read a file through the custom MCP server."""

    resolved = resolve_user_file_path(path, user_id, allow_root=False)

    if resolved is None:
        return INVALID_MESSAGE

    _database_path, mcp_path = resolved

    return call_custom_mcp_tool("read_file", {"path": mcp_path}, filesystem_root=user_mcp_root(user_id))


def delete_file(path: str, user_id: int | str | None = None) -> str:
    """Delete a file through the custom MCP server."""

    # Resolve the file path and normalize it
    resolved = resolve_user_file_path(path, user_id, allow_root=False)
    
    if resolved is None:
        return INVALID_MESSAGE
    
    _database_path, mcp_path = resolved

    # Call the delete_file tool from the custom MCP server
    result = call_custom_mcp_tool("delete_file",{"path": mcp_path},filesystem_root=user_mcp_root(user_id))

    # Delete the file from the database as well
    UploadedFile.objects.filter(owner_id=user_id, file=_database_path).delete()

    return result

def get_database_schema() -> str:
    """Get the database schema through the custom MCP server."""

    return call_custom_mcp_tool("get_database_schema", {})


def execute_sql(query: str) -> str:
    """Execute an SQL query through the custom MCP server."""

    return call_custom_mcp_tool("execute_sql", {"query": query})


# These just to expose the above functions as tools to be used by the agent

@tool("get_database_schema")
def get_database_schema_tool() -> str:
    """Get the database tables, columns, and relationships."""

    return get_database_schema()


@tool("execute_sql")
def execute_sql_tool(query: str) -> str:
    """Execute an SQL query to read or modify database records."""

    return execute_sql(query)

def get_tools(user_id: int | str | None = None):
    """Return the tools used by the agent."""

    # File tools require a user id so the MCP filesystem can be scoped to that user.
    if user_id is None:
        return [
            get_database_schema_tool,
            execute_sql_tool,
        ]

    @tool("list_files")
    def list_files_tool(path: str = "") -> str:
        """List uploaded files and folders by path."""

        return list_files(path, user_id=user_id)

    @tool("search_files")
    def search_files_tool(query: str, path: str = "") -> str:
        """Search uploaded files by filename pattern."""

        return search_files(query, path=path, user_id=user_id)

    @tool("read_file")
    def read_file_tool(path: str) -> str:
        """Read an uploaded file by path."""

        return read_file(path, user_id=user_id)

    @tool("delete_file")
    def delete_file_tool(path: str) -> str:
        """Delete an uploaded file by path."""

        return delete_file(path, user_id=user_id)

    return [
        list_files_tool,
        search_files_tool,
        read_file_tool,
        delete_file_tool,
        get_database_schema_tool,
        execute_sql_tool,
    ]
