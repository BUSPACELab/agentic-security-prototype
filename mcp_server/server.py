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
from .tools.profiles import send_password_reset_email_impl



mcp = FastMCP("Agentic Security Custom MCP Server")



@mcp.tool()
def list_files(path: str, user_id: int | str) -> str:
    """
    List files and folders using the custom MCP server.
    """
    return list_files_impl(path, user_id)

@mcp.tool()
def search_files(path: str, query: str, user_id: int | str) -> str:
    """
    Search files and folders using the custom MCP server.
    """
    return search_files_impl(path, query, user_id)


@mcp.tool()
def read_file(path: str, user_id: int | str) -> str:
    """Read a file using the custom MCP server."""

    return read_file_impl(path, user_id)


@mcp.tool()
def delete_file(path: str, user_id: int | str) -> bool:
    """
    Delete a file using the custom MCP server.
    """
    return delete_file_impl(path, user_id)

@mcp.tool()
async def send_password_reset_email(
    email: str,
    domain: str = "localhost:8000",
    use_https: bool = False,
) -> str:
    """
    Send a password reset email using the custom MCP server.
    """
    # Send the password reset email asynchronously 
    return await sync_to_async(send_password_reset_email_impl,thread_sensitive=True,)(email=email,domain=domain,use_https=use_https,)


if __name__ == "__main__":
    # Use stdio because the Django MCP client already connects to MCP over stdio.
    mcp.run(transport="stdio")