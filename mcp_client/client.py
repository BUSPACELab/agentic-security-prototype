import asyncio
import os
import sys
from pathlib import Path

from django.conf import settings
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The MCP server will operate on the same root directory as Django's file storage
# It is media/ from the settings
MCP_ROOT = Path(settings.MCP_FILESYSTEM_ROOT).resolve()

# Instead of using one global root (media), we customize it to pass the signed in user's root directory
# However, the default root is still media/
def build_custom_server_params(filesystem_root: str | None = None) -> StdioServerParameters:
    """
    Build MCP server parameters.

    If filesystem_root is provided, the MCP server starts with that root.
    Otherwise it uses the default media root.
    """
    root = filesystem_root or str(MCP_ROOT)

    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "mcp_server.server",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(settings.BASE_DIR),
            "MCP_FILESYSTEM_ROOT": root,
            "MCP_DELETED_ROOT": str(MCP_ROOT / "_deleted"),
            "DJANGO_SETTINGS_MODULE": os.environ.get(
                "DJANGO_SETTINGS_MODULE",
                "config.settings",
            ),
        },
    )


# The tools below are wrappers around the tools exposed by the custom MCP server
# _call_custom_tool is a helper function that connects to the MCP server and calls a tool with the given arguments, returning the raw result from the MCP server
async def _call_custom_tool(tool_name: str, arguments: dict, filesystem_root: str | None = None): 
    """Call one tool on the custom Python MCP server."""

    server_params = build_custom_server_params(filesystem_root)

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

# _list_custom_tools is a helper function that lists the tools exposed by the custom MCP server 
async def _list_custom_tools():
    """List tools exposed by the custom Python MCP server."""

    server_params = build_custom_server_params()

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.list_tools()

# _extract_text is a helper function that extracts plain text from an MCP result, handling different possible formats of the result
def _extract_text(result) -> str:
    """Extract plain text from an MCP result."""

    if hasattr(result, "structuredContent") and result.structuredContent:
        content = result.structuredContent.get("content")

        if content is not None:
            return str(content)

    if hasattr(result, "content") and result.content:
        parts = []

        for item in result.content:
            text = getattr(item, "text", None)

            if text is not None:
                parts.append(text)

        if parts:
            return "\n".join(parts)

    return ""


def call_custom_mcp_tool(tool_name: str, arguments: dict, filesystem_root: str | None = None) -> str:
    """Call one tool on the custom Python MCP server."""

    result = asyncio.run(_call_custom_tool(tool_name, arguments, filesystem_root))
    return _extract_text(result)


def list_custom_mcp_tools() -> list[str]:
    """Return names of tools exposed by the custom Python MCP server."""

    result = asyncio.run(_list_custom_tools())
    return [tool.name for tool in result.tools]
