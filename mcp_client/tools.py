from django.conf import settings
from langchain_core.tools import tool

from apps.files.models import UploadedFile

from .client import call_custom_mcp_tool



def list_files(path: str = "") -> str:
    """List files through the custom MCP server."""

    return call_custom_mcp_tool("list_files",{"path": path},)


def search_files(query: str) -> str:
    """Search files through the custom MCP server."""

    return call_custom_mcp_tool("search_files",{"query": query},)


def read_file(path: str) -> str:
    """Read a file through the custom MCP server."""

    return call_custom_mcp_tool("read_file",{"path": path},)


def delete_file(path: str) -> str:
    """Delete a file through the custom MCP server."""

    # Call the delete_file tool from the custom MCP server
    result = call_custom_mcp_tool("delete_file",{"path": path},)

    # Delete the file from the database as well
    UploadedFile.objects.filter(file=str(path).replace(str(settings.MCP_FILESYSTEM_ROOT) + "/", "").lstrip("/")).delete()

    return result

def get_database_schema() -> str:
    """Get the database schema through the custom MCP server."""

    return call_custom_mcp_tool("get_database_schema", {})


def execute_sql(query: str) -> str:
    """Execute an SQL query through the custom MCP server."""

    return call_custom_mcp_tool("execute_sql", {"query": query})

# These just to expose the above functions as tools to be used by the agent
@tool("list_files")
def list_files_tool(path: str = "") -> str:
    """List uploaded files and folders by path."""

    return list_files(path)


@tool("search_files")
def search_files_tool(query: str) -> str:
    """Search uploaded files by filename pattern."""

    return search_files(query)


@tool("read_file")
def read_file_tool(path: str) -> str:
    """Read an uploaded file by path."""

    return read_file(path)


@tool("delete_file")
def delete_file_tool(path: str) -> str:
    """Delete an uploaded file by path."""

    return delete_file(path)


@tool("get_database_schema")
def get_database_schema_tool() -> str:
    """Get the database tables, columns, and relationships."""

    return get_database_schema()


@tool("execute_sql")
def execute_sql_tool(query: str) -> str:
    """Execute an SQL query to read or modify database records."""

    return execute_sql(query)

def get_tools():
    """Return the tools used by the agent."""

    return [
        list_files_tool,
        search_files_tool,
        read_file_tool,
        delete_file_tool,
        get_database_schema_tool,
        execute_sql_tool,
    ]
