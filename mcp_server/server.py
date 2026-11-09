"""
Custom MCP server entrypoint

This module defines the MCP server and registers the tools exposed to the
Django application. The server is kept outside the Django apps package so it can
run as a separate process or service.
"""

from mcp.server.fastmcp import FastMCP
from asgiref.sync import sync_to_async

from .django_setup import setup_django
setup_django()

from .tools.files import list_files_impl, read_file_impl, delete_file_impl, search_files_impl
from .tools.sql import get_database_schema_impl, execute_sql_impl



mcp = FastMCP("Agentic Security Custom MCP Server")



@mcp.tool()
def list_files(path: str = "") -> str:
    """
    List files and folders using the custom MCP server.
    """
    return list_files_impl(path)

@mcp.tool()
def search_files(query: str) -> str:
    """
    Search files and folders using the custom MCP server.
    """
    return search_files_impl(query)


@mcp.tool()
def read_file(path: str) -> str:
    """
    Read a file using the custom MCP server.
    """
    return read_file_impl(path)


@mcp.tool()
def delete_file(path: str) -> str:
    """
    Delete a file using the custom MCP server.
    """
    return delete_file_impl(path)

@mcp.tool()
async def get_database_schema() -> str:
    """Get the database schema using the custom MCP server."""
    return await sync_to_async(get_database_schema_impl)()

@mcp.tool()
async def execute_sql(query: str) -> str:
    """Execute an SQL query using the custom MCP server."""
    return await sync_to_async(execute_sql_impl)(query)

if __name__ == "__main__":
    # Use stdio because the Django MCP client already connects to MCP over stdio.
    mcp.run(transport="stdio")